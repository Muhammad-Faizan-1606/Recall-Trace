"""Provision and verify bounded PostgreSQL access for an existing runtime role.

Run from a trusted operator host, never from the public web process. No password
is accepted in arguments, generated or changed. The administrative URL is read
only from DATABASE_ACCESS_ADMIN_URL and errors never echo connection details.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_ROLES = ("anon", "authenticated", "service_role")
SUPABASE_AUTO_RLS_NORMALIZED_SHA256 = (
    "eec1416e97015448e828711ff68681d41d2e513819ca91c5919de17b7f7170af"
)
SUPABASE_AUTO_RLS_RAW_SHA256 = "325ae266d9b166715ef5230ceaf7ff9d523e483cf5610dfb9779ab3f183f4af9"
FUNCTIONS = (
    "recalltrace_history_guard",
    "recalltrace_document_guard",
    "recalltrace_child_guard",
)
# Column UPDATE(id) permits existing row-locking workflows; the unconditional
# immutable-history trigger still rejects every actual UPDATE on these tables.
# 72 Core tables plus 13 Factory Suite tables (migrations f01a01 to f03a01).
APPLICATION_TABLES = 85
ROW_LOCK_TABLES = frozenset({"stock_transactions", "trace_runs", "case_comments"})
IMMUTABLE = frozenset(
    {
        "audit_events",
        "stock_transactions",
        "stock_transaction_lines",
        "shipment_events",
        "hold_reviews",
        "notice_acknowledgements",
        "recovery_records",
        "case_comments",
        "trace_runs",
        "trace_results",
        "machine_status_events",
    }
)


class AccessError(Exception):
    """A safe bounded operator error, without SQL or connection details."""


def table_names():
    from app import models  # noqa: F401
    from app.extensions import db

    tables = sorted(db.metadata.tables)
    if len(tables) != APPLICATION_TABLES or not IMMUTABLE.issubset(tables):
        raise AccessError(
            f"Review the access policy against the current {APPLICATION_TABLES}-model inventory."
        )
    return tables + ["alembic_version"]


def _identity(connection, runtime, migration):
    for name in (runtime, migration):
        if (
            not isinstance(name, str)
            or not 1 <= len(name.encode("utf-8")) <= 63
            or any(ord(character) < 32 for character in name)
        ):
            raise AccessError("Select existing bounded PostgreSQL role names.")
    if runtime == migration or runtime in API_ROLES or runtime.startswith("pg_"):
        raise AccessError("The runtime must be a separate dedicated application login role.")
    row = connection.execute(
        "SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, rolreplication, "
        "rolbypassrls, rolinherit FROM pg_catalog.pg_roles WHERE rolname = %s",
        (runtime,),
    ).fetchone()
    owner = connection.execute(
        "SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s", (migration,)
    ).fetchone()
    if row is None or owner is None:
        raise AccessError("Precreate both database roles before running this tool.")
    if not row[1] or any(row[2:]):
        raise AccessError(
            "Runtime requires LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, "
            "NOREPLICATION, NOBYPASSRLS and NOINHERIT."
        )
    if connection.execute(
        "SELECT 1 FROM pg_catalog.pg_auth_members WHERE member = %s LIMIT 1", (row[0],)
    ).fetchone():
        raise AccessError("Runtime must not be a member of any other database role.")
    database = connection.execute(
        "SELECT oid, datname, datdba FROM pg_catalog.pg_database "
        "WHERE datname = pg_catalog.current_database()"
    ).fetchone()
    if database[2] == row[0]:
        raise AccessError("Runtime must not own the database.")
    return database, row[0], owner[0]


def _canonical_supabase_auto_rls(function, triggers):
    """Recognize one reviewed non-RPC provider event function, never by name alone."""
    if len(triggers) != 1:
        return False
    source = function.get("prosrc")
    if not isinstance(source, str):
        return False
    expected = {
        "nspname": "public",
        "proname": "rls_auto_enable",
        "owner": "postgres",
        "prosecdef": True,
        "result_type": "event_trigger",
        "language": "plpgsql",
        "proconfig": ["search_path=pg_catalog"],
        "pronargs": 0,
        "prokind": "f",
        "proretset": False,
    }
    expected_trigger = {
        "evtname": "ensure_rls",
        "owner": "postgres",
        "evtevent": "ddl_command_end",
        "evtenabled": "O",
        "evttags": ["CREATE TABLE", "CREATE TABLE AS", "SELECT INTO"],
        "evtfoid": function.get("oid"),
    }
    return (
        all(function.get(name) == value for name, value in expected.items())
        and function.get("oid") is not None
        and all(triggers[0].get(name) == value for name, value in expected_trigger.items())
        and hashlib.sha256(source.encode()).hexdigest() == SUPABASE_AUTO_RLS_RAW_SHA256
        and hashlib.sha256(" ".join(source.split()).encode()).hexdigest()
        == SUPABASE_AUTO_RLS_NORMALIZED_SHA256
    )


def _verified_supabase_auto_rls(connection, oid):
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
    row = connection.execute(
        "SELECT p.oid, n.nspname, p.proname, pg_catalog.pg_get_userbyid(p.proowner), "
        "p.prosecdef, pg_catalog.format_type(p.prorettype, NULL), l.lanname, "
        "p.proconfig, p.prosrc, p.pronargs, p.prokind, p.proretset "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "JOIN pg_catalog.pg_language l ON l.oid = p.prolang WHERE p.oid = %s",
        (oid,),
    ).fetchone()
    if row is None:
        return False
    trigger_fields = ("evtname", "owner", "evtevent", "evtenabled", "evttags", "evtfoid")
    triggers = connection.execute(
        "SELECT evtname, pg_catalog.pg_get_userbyid(evtowner), evtevent, evtenabled, evttags, evtfoid "
        "FROM pg_catalog.pg_event_trigger WHERE evtfoid = %s",
        (oid,),
    ).fetchall()
    return _canonical_supabase_auto_rls(
        dict(zip(fields, row, strict=True)),
        [dict(zip(trigger_fields, trigger, strict=True)) for trigger in triggers],
    )


def _inventory(connection, migration_oid, *, allow_supabase_auto_rls=False):
    names = table_names()
    rows = connection.execute(
        "SELECT c.relname, c.oid, c.relowner, c.relkind, c.relrowsecurity "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s)",
        (names,),
    ).fetchall()
    if set(row[0] for row in rows) != set(names):
        raise AccessError(
            "Migrate all application tables and Alembic metadata before provisioning."
        )
    if any(row[2] != migration_oid or row[3] != "r" or row[4] for row in rows):
        raise AccessError(
            "Core tables must be ordinary tables owned by the named migration role; "
            "a separate policy review is required for RLS or alternative ownership."
        )
    functions = connection.execute(
        "SELECT p.proname, p.oid, p.proowner, p.prosecdef, "
        "p.prorettype = 'pg_catalog.trigger'::pg_catalog.regtype "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = ANY(%s) AND p.pronargs = 0",
        (list(FUNCTIONS),),
    ).fetchall()
    if set(row[0] for row in functions) != set(FUNCTIONS) or any(
        row[2] != migration_oid or row[3] or not row[4] for row in functions
    ):
        raise AccessError(
            "The three migration-owned, SECURITY INVOKER trigger guards are required."
        )
    unexpected_view = connection.execute(
        "SELECT 1 FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm') LIMIT 1"
    ).fetchone()
    definers = connection.execute(
        "SELECT p.oid FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.prosecdef"
    ).fetchall()
    if unexpected_view or any(
        not allow_supabase_auto_rls or not _verified_supabase_auto_rls(connection, row[0])
        for row in definers
    ):
        raise AccessError(
            "Review unexpected public views or SECURITY DEFINER routines before provisioning; "
            "they can bypass direct table ACLs through a provider API."
        )
    history_oid = next(row[1] for row in functions if row[0] == "recalltrace_history_guard")
    source = connection.execute(
        "SELECT prosrc FROM pg_catalog.pg_proc WHERE oid = %s", (history_oid,)
    ).fetchone()[0]
    expected = (
        "BEGIN RAISE EXCEPTION 'Posted history is immutable; use a compensating workflow' "
        "USING ERRCODE = '23514'; END"
    )
    if " ".join(source.split()) != expected:
        raise AccessError("The immutable-history guard body differs from the reviewed migration.")
    for table, oid, *_ in rows:
        if table not in IMMUTABLE:
            continue
        if not connection.execute(
            "SELECT 1 FROM pg_catalog.pg_trigger WHERE tgrelid = %s "
            "AND tgname = 'immutable_history' AND tgfoid = %s AND tgtype = 27 "
            "AND tgenabled IN ('O', 'A') AND tgqual IS NULL AND tgnargs = 0 AND NOT tgisinternal",
            (oid, history_oid),
        ).fetchone():
            raise AccessError(
                "Each immutable table requires its enabled unconditional history guard."
            )
    return sorted(rows), sorted(functions)


def _principals(connection):
    present = connection.execute(
        "SELECT rolname FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)", (list(API_ROLES),)
    ).fetchall()
    return ["PUBLIC"] + sorted(row[0] for row in present)


def _role_sql(name):
    return sql.SQL("PUBLIC") if name == "PUBLIC" else sql.Identifier(name)


def _permissions(table):
    if table == "alembic_version":
        return ("SELECT",)
    if table in IMMUTABLE:
        return ("SELECT", "INSERT")
    return ("SELECT", "INSERT", "UPDATE", "DELETE")


def check_access(connection, runtime, migration, *, allow_supabase_auto_rls=False):
    """Read-only catalog verification; never performs writes or SET ROLE."""
    database, runtime_oid, migration_oid = _identity(connection, runtime, migration)
    tables, functions = _inventory(
        connection, migration_oid, allow_supabase_auto_rls=allow_supabase_auto_rls
    )
    findings = []
    for capability in ("CREATE", "TEMP"):
        if connection.execute(
            "SELECT pg_catalog.has_database_privilege(%s, %s, %s)",
            (runtime_oid, database[0], capability),
        ).fetchone()[0]:
            findings.append(f"runtime_database_{capability.lower()}")
    if not connection.execute(
        "SELECT pg_catalog.has_database_privilege(%s, %s, 'CONNECT')",
        (runtime_oid, database[0]),
    ).fetchone()[0]:
        findings.append("runtime_database_connect_missing")
    if connection.execute(
        "SELECT 1 FROM pg_catalog.pg_namespace "
        "WHERE pg_catalog.has_schema_privilege(%s, oid, 'CREATE') LIMIT 1",
        (runtime_oid,),
    ).fetchone():
        findings.append("runtime_schema_create")
    if not connection.execute(
        "SELECT pg_catalog.has_schema_privilege(%s, 'public', 'USAGE')", (runtime_oid,)
    ).fetchone()[0]:
        findings.append("runtime_schema_usage_missing")
    if (
        connection.execute(
            "SELECT 1 FROM pg_catalog.pg_database d, LATERAL pg_catalog.aclexplode(d.datacl) a "
            "WHERE d.oid = %s AND a.grantee = %s AND a.is_grantable LIMIT 1",
            (database[0], runtime_oid),
        ).fetchone()
        or connection.execute(
            "SELECT 1 FROM pg_catalog.pg_namespace n, LATERAL pg_catalog.aclexplode(n.nspacl) a "
            "WHERE n.nspname = 'public' AND a.grantee = %s AND a.is_grantable LIMIT 1",
            (runtime_oid,),
        ).fetchone()
    ):
        findings.append("runtime_database_or_schema_grant_option")
    if connection.execute(
        "SELECT pg_catalog.has_parameter_privilege(%s, 'session_replication_role', 'SET')",
        (runtime_oid,),
    ).fetchone()[0]:
        findings.append("runtime_can_disable_triggers")
    settings = connection.execute(
        "SELECT setconfig FROM pg_catalog.pg_db_role_setting WHERE setrole = %s AND setdatabase = %s",
        (runtime_oid, database[0]),
    ).fetchone()
    if settings is None or "search_path=pg_catalog, public" not in settings[0]:
        findings.append("runtime_fixed_search_path_missing")
    principals = _principals(connection)
    names = [table[0] for table in tables]
    privileges = [
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "TRUNCATE",
        "REFERENCES",
        "TRIGGER",
        "MAINTAIN",
    ]
    for table, privilege, actual in connection.execute(
        "SELECT c.relname, p.privilege, pg_catalog.has_table_privilege(%s, c.oid, p.privilege) "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN unnest(%s::text[]) AS p(privilege) "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s)",
        (runtime_oid, privileges, names),
    ).fetchall():
        if actual != (privilege in _permissions(table)):
            findings.append(f"runtime_table_policy:{table}:{privilege}")
    for table, privilege in connection.execute(
        "SELECT c.relname, p.privilege FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) AS p(privilege) "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s) "
        "AND pg_catalog.has_any_column_privilege(%s, c.oid, p.privilege)",
        (names, runtime_oid),
    ).fetchall():
        if privilege not in _permissions(table) and not (
            table in ROW_LOCK_TABLES and privilege == "UPDATE"
        ):
            findings.append(f"runtime_column_policy:{table}:{privilege}")
    for table, column, permitted in connection.execute(
        "SELECT c.relname, a.attname, pg_catalog.has_column_privilege(%s, c.oid, a.attnum, 'UPDATE') "
        "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped",
        (runtime_oid, list(ROW_LOCK_TABLES)),
    ).fetchall():
        if permitted != (column == "id"):
            findings.append(f"runtime_row_lock_column_policy:{table}:{column}")
    for table, grantee, _grantable in connection.execute(
        "SELECT DISTINCT c.relname, a.grantee, a.is_grantable FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(COALESCE(c.relacl, "
        "pg_catalog.acldefault('r', c.relowner))) a "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s) "
        "AND (a.grantee = 0 OR (a.grantee = %s AND a.is_grantable))",
        (names, runtime_oid),
    ).fetchall():
        findings.append(
            f"public_table_privilege:{table}"
            if grantee == 0
            else f"runtime_table_grant_option:{table}"
        )
    for table, grantee in connection.execute(
        "SELECT DISTINCT c.relname, a.grantee FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "JOIN pg_catalog.pg_attribute column_acl ON column_acl.attrelid = c.oid "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(column_acl.attacl) a "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s) "
        "AND (a.grantee = 0 OR (a.grantee = %s AND a.is_grantable))",
        (names, runtime_oid),
    ).fetchall():
        findings.append(
            f"public_column_privilege:{table}"
            if grantee == 0
            else f"runtime_column_grant_option:{table}"
        )
    for table, principal in connection.execute(
        "SELECT c.relname, r.rolname FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN pg_catalog.pg_roles r "
        "WHERE n.nspname = 'public' AND c.relname = ANY(%s) AND r.rolname = ANY(%s) "
        "AND (pg_catalog.has_table_privilege(r.oid, c.oid, %s) "
        "OR pg_catalog.has_any_column_privilege(r.oid, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))",
        (names, principals[1:], ",".join(privileges)),
    ).fetchall():
        findings.append(f"api_table_privilege:{principal}:{table}")
    for function, oid, *_ in functions:
        if not connection.execute(
            "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (runtime_oid, oid)
        ).fetchone()[0]:
            findings.append(f"runtime_guard_execute_missing:{function}")
        if connection.execute(
            "SELECT 1 FROM pg_catalog.pg_proc p, LATERAL pg_catalog.aclexplode(p.proacl) a "
            "WHERE p.oid = %s AND a.grantee = %s AND a.is_grantable LIMIT 1",
            (oid, runtime_oid),
        ).fetchone():
            findings.append(f"runtime_function_grant_option:{function}")
        if connection.execute(
            "SELECT 1 FROM pg_catalog.pg_proc p, "
            "LATERAL pg_catalog.aclexplode(COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))) a "
            "WHERE p.oid = %s AND a.grantee = 0 LIMIT 1",
            (oid,),
        ).fetchone():
            findings.append(f"public_function_execute:{function}")
        for principal in principals[1:]:
            if connection.execute(
                "SELECT pg_catalog.has_function_privilege(%s, %s, 'EXECUTE')", (principal, oid)
            ).fetchone()[0]:
                findings.append(f"api_function_execute:{principal}:{function}")
    default_grantees = [0, runtime_oid] + [
        connection.execute(
            "SELECT oid FROM pg_catalog.pg_roles WHERE rolname = %s", (name,)
        ).fetchone()[0]
        for name in principals[1:]
    ]
    for kind in ("r", "S", "f"):
        global_acl = connection.execute(
            "SELECT defaclacl FROM pg_catalog.pg_default_acl "
            "WHERE defaclrole = %s AND defaclnamespace = 0 AND defaclobjtype = %s",
            (migration_oid, kind),
        ).fetchone()
        defaults = global_acl[0] if global_acl else None
        if connection.execute(
            "SELECT 1 FROM pg_catalog.aclexplode(COALESCE(%s::aclitem[], "
            'pg_catalog.acldefault(%s::"char", %s))) a WHERE a.grantee = ANY(%s) LIMIT 1',
            (defaults, kind, migration_oid, default_grantees),
        ).fetchone():
            findings.append(f"unsafe_global_default_acl:{kind}")
        if connection.execute(
            "SELECT 1 FROM pg_catalog.pg_default_acl d "
            "JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace "
            "CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a "
            "WHERE d.defaclrole = %s AND n.nspname = 'public' AND d.defaclobjtype = %s "
            "AND a.grantee = ANY(%s) LIMIT 1",
            (migration_oid, kind, default_grantees),
        ).fetchone():
            findings.append(f"unsafe_schema_default_acl:{kind}")
    return {
        "status": "verified" if not findings else "blocked",
        "database": database[1],
        "runtime_role": runtime,
        "core_tables": APPLICATION_TABLES,
        "findings": findings,
    }


def apply_access(
    connection, runtime, migration, *, dedicated_database=False, allow_supabase_auto_rls=False
):
    """Atomically revoke unsafe ACLs and grant this version's exact object policy."""
    if not dedicated_database:
        raise AccessError(
            "Apply requires --dedicated-database to acknowledge database/schema ACL effects."
        )
    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout = '5s'")
        connection.execute("SET LOCAL statement_timeout = '30s'")
        database, _, migration_oid = _identity(connection, runtime, migration)
        tables, functions = _inventory(
            connection, migration_oid, allow_supabase_auto_rls=allow_supabase_auto_rls
        )
        principals = _principals(connection)
        for principal in principals + [runtime]:
            recipient = _role_sql(principal)
            connection.execute(
                sql.SQL("REVOKE CREATE, TEMPORARY ON DATABASE {} FROM {}").format(
                    sql.Identifier(database[1]), recipient
                )
            )
            connection.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(recipient))
            for table, oid, *_ in tables:
                target = sql.Identifier("public", table)
                connection.execute(
                    sql.SQL("REVOKE ALL ON TABLE {} FROM {}").format(target, recipient)
                )
                columns = connection.execute(
                    "SELECT attname FROM pg_catalog.pg_attribute "
                    "WHERE attrelid = %s AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
                    (oid,),
                ).fetchall()
                column_list = sql.SQL(", ").join(sql.Identifier(row[0]) for row in columns)
                connection.execute(
                    sql.SQL(
                        "REVOKE SELECT ({}), INSERT ({}), UPDATE ({}), REFERENCES ({}) "
                        "ON TABLE {} FROM {}"
                    ).format(column_list, column_list, column_list, column_list, target, recipient)
                )
            for function, *_ in functions:
                connection.execute(
                    sql.SQL("REVOKE ALL ON FUNCTION {}() FROM {}").format(
                        sql.Identifier("public", function), recipient
                    )
                )
            for object_type in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                # Global function defaults grant PUBLIC execute. Per-schema
                # revocation cannot remove a global/default privilege.
                for scope in (sql.SQL(""), sql.SQL(" IN SCHEMA public")):
                    connection.execute(
                        sql.SQL(
                            "ALTER DEFAULT PRIVILEGES FOR ROLE {}{} REVOKE ALL ON {} FROM {}"
                        ).format(sql.Identifier(migration), scope, sql.SQL(object_type), recipient)
                    )
        connection.execute(
            sql.SQL("REVOKE GRANT OPTION FOR CONNECT ON DATABASE {} FROM {}").format(
                sql.Identifier(database[1]), sql.Identifier(runtime)
            )
        )
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database[1]), sql.Identifier(runtime)
            )
        )
        connection.execute(
            sql.SQL("REVOKE GRANT OPTION FOR USAGE ON SCHEMA public FROM {}").format(
                sql.Identifier(runtime)
            )
        )
        connection.execute(
            sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(runtime))
        )
        connection.execute(
            sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path = pg_catalog, public").format(
                sql.Identifier(runtime), sql.Identifier(database[1])
            )
        )
        for table, *_ in tables:
            connection.execute(
                sql.SQL("GRANT {} ON TABLE {} TO {}").format(
                    sql.SQL(", ").join(sql.SQL(privilege) for privilege in _permissions(table)),
                    sql.Identifier("public", table),
                    sql.Identifier(runtime),
                )
            )
            if table in ROW_LOCK_TABLES:
                connection.execute(
                    sql.SQL("GRANT UPDATE(id) ON TABLE {} TO {}").format(
                        sql.Identifier("public", table), sql.Identifier(runtime)
                    )
                )
        for function, *_ in functions:
            connection.execute(
                sql.SQL("GRANT EXECUTE ON FUNCTION {}() TO {}").format(
                    sql.Identifier("public", function), sql.Identifier(runtime)
                )
            )
        report = check_access(
            connection, runtime, migration, allow_supabase_auto_rls=allow_supabase_auto_rls
        )
        if report["findings"]:
            raise AccessError(
                "Access verification failed; all provisioning changes were rolled back."
            )
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("apply", "check"):
        command = commands.add_parser(name)
        command.add_argument("--runtime-role", required=True)
        command.add_argument("--migration-role", required=True)
        command.add_argument(
            "--allow-supabase-auto-rls",
            action="store_true",
            help="Allow only the exact reviewed Supabase ensure_rls event-trigger function.",
        )
        if name == "apply":
            command.add_argument("--dedicated-database", action="store_true")
    args = parser.parse_args(argv)
    try:
        url = make_url(os.environ["DATABASE_ACCESS_ADMIN_URL"])
        if url.drivername != "postgresql+psycopg" or not all(
            (url.host, url.database, url.username, url.password)
        ):
            raise AccessError(
                "Supply DATABASE_ACCESS_ADMIN_URL securely as a PostgreSQL psycopg URL."
            )
        if url.host not in {"localhost", "127.0.0.1", "::1"} and (
            url.query.get("sslmode") != "verify-full"
            or not Path(url.query.get("sslrootcert", "")).is_file()
        ):
            raise AccessError(
                "Remote administration requires verify-full TLS and an installed root CA."
            )
        with psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
            connect_timeout=10,
        ) as connection:
            if args.command == "apply":
                report = apply_access(
                    connection,
                    args.runtime_role,
                    args.migration_role,
                    dedicated_database=args.dedicated_database,
                    allow_supabase_auto_rls=args.allow_supabase_auto_rls,
                )
            else:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    report = check_access(
                        connection,
                        args.runtime_role,
                        args.migration_role,
                        allow_supabase_auto_rls=args.allow_supabase_auto_rls,
                    )
        print(json.dumps(report))
        return 0 if not report["findings"] else 1
    except AccessError as exc:
        print(str(exc), file=sys.stderr)
    except (KeyError, ValueError, ArgumentError, OSError, psycopg.Error):
        print(
            "Database access operation failed; check roles, migrations and private configuration.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
