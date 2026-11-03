"""Private PostgreSQL backups and restore rehearsal to a fresh isolated database.

Connection credentials are passed to PostgreSQL clients only in their environment.
Existing databases are never overwritten; a rehearsal database is kept for inspection
and removed only with --drop-after-success. Evidence storage needs a separate backup.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class BackupError(Exception):
    pass


def connection_environment(database_name=None):
    try:
        url = make_url(os.environ["DATABASE_URL"])
        if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
            raise ValueError
    except (KeyError, ValueError, ArgumentError) as exc:
        raise BackupError("Set DATABASE_URL securely to a PostgreSQL psycopg connection.") from exc
    child = dict(os.environ)
    for key in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGOPTIONS",
    ):
        child.pop(key, None)
    child.update(
        PGHOST=url.host,
        PGPORT=str(url.port or 5432),
        PGUSER=url.username or "",
        PGPASSWORD=url.password or "",
        PGDATABASE=database_name or url.database,
        PGCONNECT_TIMEOUT="10",
    )
    for query, variable in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        if query in url.query:
            child[variable] = url.query[query]
    return child


def run_private(command, child):
    # PostgreSQL error output can include connection information. Emit a bounded safe
    # outcome, not the command's stdout/stderr or credentials.
    try:
        if child.get("RECALLTRACE_PG_TOOLS_IMAGE"):
            result = run_container_client(command, child)
        else:
            result = subprocess.run(command, env=child, capture_output=True, check=False)
    except OSError as exc:
        raise BackupError(f"Required PostgreSQL client is unavailable: {command[0]}.") from exc
    if result.returncode:
        raise BackupError(
            f"{command[0]} failed (exit {result.returncode}); inspect the database/provider privately."
        )


def run_container_client(command, child):
    """Stream archives through a separate trusted PostgreSQL client container.

    Only PG variable names appear in arguments; Docker receives their values
    from the protected client environment. No daemon runs in the web image.
    """
    if not command or command[0] not in {"pg_dump", "pg_restore"}:
        raise BackupError("Only PostgreSQL dump/restore clients are supported.")
    image = child["RECALLTRACE_PG_TOOLS_IMAGE"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]+", image):
        raise BackupError("Select a trusted PostgreSQL tools image name or digest.")
    environment = dict(child)
    if child.get("RECALLTRACE_PG_TOOLS_HOST"):
        environment["PGHOST"] = child["RECALLTRACE_PG_TOOLS_HOST"]
    invocation = ["docker", "run", "--rm", "-i"]
    if hasattr(os, "getuid"):
        invocation += ["--user", f"{os.getuid()}:{os.getgid()}"]
    network = child.get("RECALLTRACE_PG_TOOLS_NETWORK")
    if network:
        if network == "host" or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", network):
            raise BackupError("Select an existing private Docker network, not host networking.")
        invocation += ["--network", network]
    for variable in ("PGSSLROOTCERT", "PGSSLCERT", "PGSSLKEY"):
        if not environment.get(variable):
            continue
        source = Path(environment[variable]).resolve(strict=True)
        if not source.is_file() or any(c in str(source) for c in (",", "\r", "\n")):
            raise BackupError("TLS client files must be regular files with supported paths.")
        destination = f"/run/recalltrace-{variable.lower()}.pem"
        invocation += ["--mount", f"type=bind,source={source},target={destination},readonly"]
        environment[variable] = destination
    for variable in (
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGPASSWORD",
        "PGDATABASE",
        "PGCONNECT_TIMEOUT",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "PGSSLCERT",
        "PGSSLKEY",
    ):
        if variable in environment:
            invocation += ["--env", variable]
    invocation += ["--entrypoint", command[0], image]
    arguments = list(command[1:])
    if command[0] == "pg_dump":
        file_arguments = [arg for arg in arguments if arg.startswith("--file=")]
        if len(file_arguments) != 1:
            raise BackupError("A single private dump destination is required.")
        file_argument = file_arguments[0]
        arguments.remove(file_argument)
        with open(file_argument.split("=", 1)[1], "wb") as target:
            return subprocess.run(
                invocation + arguments,
                env=environment,
                stdout=target,
                stderr=subprocess.PIPE,
                check=False,
            )
    if not arguments:
        raise BackupError("A private restore archive is required.")
    with open(arguments.pop(), "rb") as source:
        return subprocess.run(
            invocation + arguments,
            env=environment,
            stdin=source,
            capture_output=True,
            check=False,
        )


def backup(destination):
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.stat().st_mode & 0o077:
        raise BackupError(
            "Backup directory must have mode 0700; existing permissions were preserved."
        )
    suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    path = destination / f"recalltrace-{suffix}.dump"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    try:
        run_private(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", f"--file={path}"],
            connection_environment(),
        )
        if not path.stat().st_size:
            raise BackupError("PostgreSQL produced an empty backup.")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        manifest = {
            "format": "postgres-custom",
            "filename": path.name,
            "sha256": digest,
            "created_at": datetime.now(UTC).isoformat(),
            "scope": "database only; evidence objects and MFA key recovery excluded",
        }
        with os.fdopen(
            os.open(path.with_suffix(".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as handle:
            json.dump(manifest, handle, indent=2)
        print(json.dumps({"status": "backed_up", "archive": str(path), "sha256": digest}))
    except Exception:
        path.unlink(missing_ok=True)
        raise


def restore(archive, drop_after):
    archive = archive.resolve(strict=True)
    if not stat.S_ISREG(archive.stat().st_mode) or archive.stat().st_mode & 0o077:
        raise BackupError("Restore archive must be a private regular file (mode 0600).")
    manifest = json.loads(archive.with_suffix(".json").read_text())
    with archive.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != manifest.get("sha256"):
        raise BackupError("Backup checksum mismatch; archive was not used.")
    environment = connection_environment("postgres")
    # psycopg doesn't consume arbitrary mapping variables; use explicit arguments.
    arguments = {
        "host": environment["PGHOST"],
        "port": environment["PGPORT"],
        "user": environment["PGUSER"],
        "password": environment["PGPASSWORD"],
        "dbname": "postgres",
        "connect_timeout": 10,
    }
    for name, variable in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        if variable in environment:
            arguments[name] = environment[variable]
    name = "recalltrace_restore_" + secrets.token_hex(8)
    started = datetime.now(UTC)
    with psycopg.connect(**arguments, autocommit=True) as administrator:
        administrator.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        # Do not drop a failed restore: retain evidence for the operator to inspect.
        run_private(
            [
                "pg_restore",
                "--exit-on-error",
                "--no-owner",
                "--no-acl",
                "--dbname",
                name,
                str(archive),
            ],
            connection_environment(name),
        )
        restored_args = dict(arguments, dbname=name)
        with psycopg.connect(**restored_args) as connection:
            tables = [
                row[0]
                for row in connection.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                )
            ]
            if "alembic_version" not in tables:
                raise BackupError("Restored database is missing migration metadata.")
            migration = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            counts = {}
            for table in tables:
                counts[table] = connection.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
            # Reconcile journal projection when the stock slice has been migrated.
            if {"stock_balances", "stock_transaction_lines", "stock_transactions"}.issubset(tables):
                differences = connection.execute("""
                    WITH journal AS (
                        SELECT l.organization_id,l.lot_id,l.location_id,sum(l.quantity_delta) quantity
                        FROM stock_transaction_lines l JOIN stock_transactions t
                          ON t.organization_id=l.organization_id AND t.id=l.transaction_id
                        WHERE t.status='posted' GROUP BY l.organization_id,l.lot_id,l.location_id
                    )
                    SELECT count(*) FROM journal j FULL JOIN stock_balances b
                      USING (organization_id,lot_id,location_id)
                    WHERE coalesce(j.quantity,0) <> coalesce(b.quantity,0)
                """).fetchone()[0]
                if differences:
                    raise BackupError("Restored journal does not reconcile with stock balances.")
        retained = not drop_after
        if drop_after:
            administrator.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
    print(
        json.dumps(
            {
                "status": "restore_verified",
                "database": name,
                "retained": retained,
                "seconds": (datetime.now(UTC) - started).total_seconds(),
                "migrations": [row[0] for row in migration],
                "table_counts": counts,
                "limitation": "Does not verify evidence objects, MFA recovery keys, or complete business acceptance.",
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("backup")
    make.add_argument("--directory", type=Path, default=Path("instance/backups"))
    verify = commands.add_parser("restore")
    verify.add_argument("archive", type=Path)
    verify.add_argument(
        "--drop-after-success",
        action="store_true",
        help="Remove only the new randomly named rehearsal database after successful verification.",
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "backup":
            backup(args.directory)
        else:
            restore(args.archive, args.drop_after_success)
    except (BackupError, psycopg.Error, OSError, ValueError) as exc:
        if isinstance(exc, BackupError):
            print(str(exc), file=sys.stderr)
        else:
            print(
                "Backup/restore operation failed; inspect provider status and private configuration.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
