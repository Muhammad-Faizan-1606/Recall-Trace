"""Real separate-role PostgreSQL checks without changing any existing database ACL."""

import os
import secrets

import psycopg
import pytest
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask_migrate import upgrade
from psycopg import sql
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db
from app.models import Organization
from app.models.operations import StockTransaction
from operations import database_access as access


@pytest.fixture(autouse=True)
def records():
    # Override the suite's truncation fixture: these checks use only a new random
    # database and roles, never recalltrace_test or the application database.
    yield


def configured_app(url):
    return create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "SECRET_KEY": secrets.token_hex(32),
            "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "MFA_KEY_VERSION": "v1",
            "SQLALCHEMY_DATABASE_URI": url.render_as_string(hide_password=False),
        }
    )


@pytest.fixture(scope="module")
def isolated_database():
    load_dotenv()
    original = make_url(os.environ["DATABASE_URL"])
    suffix = secrets.token_hex(6)
    name = "recalltrace_access_" + suffix
    migration = "rt_migration_" + suffix
    runtime = "rt_runtime_" + suffix
    api = "rt_api_" + suffix
    password = secrets.token_urlsafe(32)
    admin_url = original.set(database="postgres", drivername="postgresql")
    with psycopg.connect(admin_url.render_as_string(hide_password=False), autocommit=True) as admin:
        try:
            for role in (migration, runtime, api):
                admin.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION NOBYPASSRLS NOINHERIT PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
            admin.execute(
                sql.SQL("CREATE DATABASE {} OWNER {} TEMPLATE template0").format(
                    sql.Identifier(name), sql.Identifier(migration)
                )
            )
            owner_url = original.set(database=name, username=migration, password=password)
            app = configured_app(owner_url)
            with app.app_context():
                upgrade(directory="migrations")
                db.engine.dispose()
            scratch_url = original.set(database=name, drivername="postgresql")
            with psycopg.connect(
                scratch_url.render_as_string(hide_password=False), autocommit=True
            ) as connection:
                yield {
                    "connection": connection,
                    "database": name,
                    "migration": migration,
                    "runtime": runtime,
                    "api": api,
                    "runtime_url": owner_url.set(username=runtime),
                    "api_url": owner_url.set(username=api),
                }
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            for role in (api, runtime, migration):
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


@pytest.fixture
def policy(isolated_database, monkeypatch):
    monkeypatch.setattr(access, "API_ROLES", (isolated_database["api"],))
    return isolated_database


def apply(policy):
    return access.apply_access(
        policy["connection"], policy["runtime"], policy["migration"], dedicated_database=True
    )


def connect(url):
    return psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    )


def test_explicit_dedicated_database_acknowledgement_required(policy):
    with pytest.raises(access.AccessError, match="dedicated-database"):
        access.apply_access(policy["connection"], policy["runtime"], policy["migration"])


def test_apply_is_atomic_idempotent_and_check_can_run_readonly(policy):
    assert apply(policy)["status"] == "verified"
    assert apply(policy)["status"] == "verified"
    with policy["connection"].transaction():
        policy["connection"].execute("SET TRANSACTION READ ONLY")
        report = access.check_access(policy["connection"], policy["runtime"], policy["migration"])
    assert report["findings"] == []
    assert report["core_tables"] == 88


def test_runtime_bootstrap_and_ordinary_writes_work(policy):
    apply(policy)
    app = configured_app(policy["runtime_url"])
    runner = app.test_cli_runner()
    company = "access-" + secrets.token_hex(4)
    result = runner.invoke(
        args=["create-company", "--name", "Synthetic access check", "--slug", company]
    )
    assert result.exit_code == 0, result.output
    password = "Synthetic access bootstrap passphrase 492!"
    result = runner.invoke(
        args=["create-owner", "--company", company, "--email", company + "@example.test"],
        input=password + "\n" + password + "\n",
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(args=["init-business", "--company", company])
    assert result.exit_code == 0, result.output
    with app.app_context():
        row = db.session.scalar(db.select(Organization).where(Organization.slug == company))
        row.name = "Renamed synthetic access check"
        db.session.commit()
        assert row.name == "Renamed synthetic access check"
        db.session.remove()
        db.engine.dispose()


def test_history_row_locks_work_without_allowing_actual_changes(policy):
    apply(policy)
    app = configured_app(policy["runtime_url"])
    with app.app_context():
        organization = Organization(
            name="Synthetic journal", slug="journal-" + secrets.token_hex(4)
        )
        db.session.add(organization)
        db.session.flush()
        transaction = StockTransaction(
            organization_id=organization.id,
            kind="receipts",
            status="posted",
            idempotency_key=secrets.token_hex(8),
            payload_digest="0" * 64,
        )
        db.session.add(transaction)
        db.session.commit()
        identifier = transaction.id
        db.session.remove()
        db.engine.dispose()
    with connect(policy["runtime_url"]) as runtime:
        with runtime.transaction():
            assert (
                runtime.execute(
                    "SELECT id FROM public.stock_transactions WHERE id = %s FOR UPDATE",
                    (identifier,),
                ).fetchone()[0]
                == identifier
            )
            # Even an empty result requires PostgreSQL's row-lock privilege.
            runtime.execute("SELECT id FROM public.trace_runs WHERE false FOR UPDATE")
            runtime.execute("SELECT id FROM public.case_comments WHERE false FOR UPDATE")
        with pytest.raises(psycopg.errors.CheckViolation):
            runtime.execute(
                "UPDATE public.stock_transactions SET id = id WHERE id = %s", (identifier,)
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute(
                "UPDATE public.stock_transactions SET kind = 'reversal' WHERE id = %s",
                (identifier,),
            )


def test_disabled_history_trigger_and_indirect_api_paths_fail_closed(policy):
    apply(policy)
    connection = policy["connection"]
    connection.execute("ALTER TABLE public.stock_transactions DISABLE TRIGGER immutable_history")
    try:
        with pytest.raises(access.AccessError, match="history guard"):
            access.check_access(connection, policy["runtime"], policy["migration"])
    finally:
        connection.execute("ALTER TABLE public.stock_transactions ENABLE TRIGGER immutable_history")
    connection.execute("CREATE VIEW public.synthetic_api_path AS SELECT email FROM public.users")
    try:
        with pytest.raises(access.AccessError, match="public views"):
            apply(policy)
    finally:
        connection.execute("DROP VIEW public.synthetic_api_path")
    connection.execute(
        "CREATE FUNCTION public.synthetic_api_path() RETURNS bigint "
        "LANGUAGE sql SECURITY DEFINER AS 'SELECT count(*) FROM public.users'"
    )
    try:
        with pytest.raises(access.AccessError, match="SECURITY DEFINER"):
            apply(policy)
    finally:
        connection.execute("DROP FUNCTION public.synthetic_api_path()")


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE public.should_not_exist(id integer)",
        "CREATE SCHEMA should_not_exist",
        "CREATE TEMP TABLE should_not_exist(id integer)",
        "TRUNCATE public.users",
        "ALTER TABLE public.users DISABLE TRIGGER ALL",
        "UPDATE public.alembic_version SET version_num = 'tampered'",
        "UPDATE public.audit_events SET action = 'tampered'",
        "DELETE FROM public.stock_transactions",
        "SET session_replication_role = replica",
    ],
)
def test_runtime_cannot_ddl_truncate_migrate_or_tamper(policy, statement):
    apply(policy)
    with connect(policy["runtime_url"]) as connection:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(statement)


def test_api_column_grants_and_default_exposure_are_removed(policy):
    connection = policy["connection"]
    connection.execute(
        sql.SQL("GRANT SELECT(email) ON public.users TO {}").format(sql.Identifier(policy["api"]))
    )
    connection.execute(sql.SQL("GRANT SELECT(action) ON public.audit_events TO PUBLIC"))
    connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT ON TABLES TO {}"
        ).format(sql.Identifier(policy["migration"]), sql.Identifier(policy["api"]))
    )
    report = access.check_access(connection, policy["runtime"], policy["migration"])
    assert any("api_table_privilege" in finding for finding in report["findings"])
    assert any("public_column_privilege" in finding for finding in report["findings"])
    assert any("unsafe_schema_default_acl" in finding for finding in report["findings"])
    apply(policy)
    with connect(policy["api_url"]) as api:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("SELECT email FROM public.users")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            api.execute("SELECT public.recalltrace_history_guard()")
    with connection.transaction():
        connection.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(policy["migration"])))
        connection.execute("CREATE TABLE public.synthetic_future_private(id integer)")
        connection.execute(
            "CREATE FUNCTION public.synthetic_future_private() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
        )
        with connect(policy["api_url"]) as api:
            # Uncommitted objects are invisible; inspect their ACLs in the creating
            # transaction, then perform real API-role execution after commit below.
            assert not connection.execute(
                "SELECT has_table_privilege(%s, 'public.synthetic_future_private', 'SELECT')",
                (policy["api"],),
            ).fetchone()[0]
    try:
        with connect(policy["api_url"]) as api:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                api.execute("SELECT * FROM public.synthetic_future_private")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                api.execute("SELECT public.synthetic_future_private()")
    finally:
        connection.execute("DROP TABLE public.synthetic_future_private")
        connection.execute("DROP FUNCTION public.synthetic_future_private()")


def test_unsafe_membership_fails_before_mutation(policy):
    connection = policy["connection"]
    connection.execute(
        sql.SQL("GRANT {} TO {}").format(
            sql.Identifier(policy["migration"]), sql.Identifier(policy["runtime"])
        )
    )
    try:
        with pytest.raises(access.AccessError, match="member"):
            apply(policy)
    finally:
        connection.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(policy["migration"]), sql.Identifier(policy["runtime"])
            )
        )


def test_check_detects_grant_option_drift_and_apply_repairs_it(policy):
    apply(policy)
    connection = policy["connection"]
    connection.execute(
        sql.SQL(
            "GRANT EXECUTE ON FUNCTION public.recalltrace_history_guard() TO {} WITH GRANT OPTION"
        ).format(sql.Identifier(policy["runtime"]))
    )
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {} WITH GRANT OPTION").format(
            sql.Identifier(policy["database"]), sql.Identifier(policy["runtime"])
        )
    )
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {} WITH GRANT OPTION").format(
            sql.Identifier(policy["runtime"])
        )
    )
    report = access.check_access(connection, policy["runtime"], policy["migration"])
    assert "runtime_database_or_schema_grant_option" in report["findings"]
    assert "runtime_function_grant_option:recalltrace_history_guard" in report["findings"]
    assert apply(policy)["status"] == "verified"


def test_unexpected_schema_capability_rolls_back_all_changes(policy):
    connection = policy["connection"]
    connection.execute("CREATE SCHEMA synthetic_unreviewed")
    connection.execute(
        sql.SQL("GRANT CREATE ON SCHEMA synthetic_unreviewed TO {}").format(
            sql.Identifier(policy["runtime"])
        )
    )
    connection.execute(
        sql.SQL("GRANT SELECT(email) ON public.users TO {}").format(sql.Identifier(policy["api"]))
    )
    try:
        with pytest.raises(access.AccessError, match="rolled back"):
            apply(policy)
        assert connection.execute(
            "SELECT has_any_column_privilege(%s, 'public.users', 'SELECT')", (policy["api"],)
        ).fetchone()[0]
    finally:
        connection.execute("DROP SCHEMA synthetic_unreviewed")
        apply(policy)


def test_admin_url_failure_is_redacted(monkeypatch, capsys):
    secret = "private-admin-value-that-must-not-appear"
    monkeypatch.setenv("DATABASE_ACCESS_ADMIN_URL", "invalid://" + secret)
    assert access.main(["check", "--runtime-role", "runtime", "--migration-role", "owner"]) == 1
    assert secret not in capsys.readouterr().err


# Reviewed provider code is public SQL, not a credential or executed fixture.
SUPABASE_AUTO_RLS_SOURCE = """
DECLARE
  cmd record;
  tbl name;
BEGIN
  FOR cmd IN
    SELECT *
    FROM pg_event_trigger_ddl_commands()
    WHERE command_tag IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
      AND object_type IN ('table','partitioned table')
  LOOP
     IF cmd.schema_name IS NOT NULL AND cmd.schema_name IN ('public') AND cmd.schema_name NOT IN ('pg_catalog','information_schema') AND cmd.schema_name NOT LIKE 'pg_toast%' AND cmd.schema_name NOT LIKE 'pg_temp%' THEN
      BEGIN
        SELECT c.relname INTO tbl FROM pg_catalog.pg_class c WHERE c.oid = cmd.objid;
        EXECUTE format('alter table if exists %I.%I enable row level security', cmd.schema_name, tbl);
        RAISE LOG 'rls_auto_enable: enabled RLS on %', cmd.object_identity;
      EXCEPTION
        WHEN OTHERS THEN
          RAISE LOG 'rls_auto_enable: failed to enable RLS on %', cmd.object_identity;
      END;
     ELSE
        RAISE LOG 'rls_auto_enable: skip % (either system schema or not in enforced list: %.)', cmd.object_identity, cmd.schema_name;
     END IF;
  END LOOP;
END;
"""


def provider_snapshot():
    function = {
        "oid": 12001,
        "nspname": "public",
        "proname": "rls_auto_enable",
        "owner": "postgres",
        "prosecdef": True,
        "result_type": "event_trigger",
        "language": "plpgsql",
        "proconfig": ["search_path=pg_catalog"],
        "prosrc": SUPABASE_AUTO_RLS_SOURCE,
        "pronargs": 0,
        "prokind": "f",
        "proretset": False,
    }
    trigger = {
        "evtname": "ensure_rls",
        "owner": "postgres",
        "evtevent": "ddl_command_end",
        "evtenabled": "O",
        "evttags": ["CREATE TABLE", "CREATE TABLE AS", "SELECT INTO"],
        "evtfoid": 12001,
    }
    return function, [trigger]


def test_exact_reviewed_supabase_provider_snapshot_is_recognized():
    function, triggers = provider_snapshot()
    assert access._canonical_supabase_auto_rls(function, triggers)


def test_provider_catalog_lookup_accepts_only_the_canonical_function_and_attachment():
    function, triggers = provider_snapshot()

    class Rows:
        def __init__(self, values):
            self.values = values

        def fetchone(self):
            return self.values[0] if self.values else None

        def fetchall(self):
            return self.values

    class ProviderCatalog:
        def execute(self, statement, parameters):
            assert parameters == (function["oid"],)
            if "pg_catalog.pg_event_trigger" in statement:
                fields = ("evtname", "owner", "evtevent", "evtenabled", "evttags", "evtfoid")
                return Rows([tuple(trigger[field] for field in fields) for trigger in triggers])
            assert "pg_catalog.pg_proc" in statement
            fields = (
                "oid",
                "nspname",
                "proname",
                "owner",
                "prosecdef",
                "result_type",
                "language",
                "proconfig",
                "prosrc",
                "pronargs",
                "prokind",
                "proretset",
            )
            return Rows([tuple(function[field] for field in fields)])

    assert access._verified_supabase_auto_rls(ProviderCatalog(), function["oid"])
    triggers[0]["evtfoid"] += 1
    assert not access._verified_supabase_auto_rls(ProviderCatalog(), function["oid"])


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("function", "nspname", "untrusted"),
        ("function", "proname", "same_body_different_entrypoint"),
        ("function", "owner", "untrusted"),
        ("function", "prosecdef", False),
        ("function", "result_type", "integer"),
        ("function", "language", "sql"),
        ("function", "proconfig", ["search_path=public, pg_catalog"]),
        ("function", "pronargs", 1),
        ("function", "prokind", "p"),
        ("function", "proretset", True),
        ("function", "prosrc", "BEGIN RETURN; END;"),
        ("function", "prosrc", SUPABASE_AUTO_RLS_SOURCE.replace("BEGIN", "BEGIN ", 1)),
        ("trigger", "evtname", "unreviewed_event"),
        ("trigger", "owner", "untrusted"),
        ("trigger", "evtevent", "ddl_command_start"),
        ("trigger", "evtenabled", "D"),
        ("trigger", "evttags", None),
        ("trigger", "evtfoid", 12002),
    ],
)
def test_provider_lookalike_or_metadata_drift_is_rejected(target, field, value):
    function, triggers = provider_snapshot()
    (function if target == "function" else triggers[0])[field] = value
    assert not access._canonical_supabase_auto_rls(function, triggers)


def test_provider_requires_exactly_one_matching_event_trigger():
    function, triggers = provider_snapshot()
    assert not access._canonical_supabase_auto_rls(function, [])
    assert not access._canonical_supabase_auto_rls(function, triggers + triggers)


def test_opt_in_rejects_real_provider_function_name_with_unreviewed_body(policy):
    connection = policy["connection"]
    connection.execute(
        "CREATE FUNCTION public.rls_auto_enable() RETURNS event_trigger "
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog "
        "AS 'BEGIN RETURN; END;'"
    )
    try:
        for opt_in in (False, True):
            with pytest.raises(access.AccessError, match="SECURITY DEFINER"):
                access.apply_access(
                    connection,
                    policy["runtime"],
                    policy["migration"],
                    dedicated_database=True,
                    allow_supabase_auto_rls=opt_in,
                )
    finally:
        connection.execute("DROP FUNCTION public.rls_auto_enable()")
