"""Operator check: connect to the deployment's PostgreSQL and Redis like the app does.

Prints the dependency and the driver's first error line; never prints URLs or passwords.
Run with DATABASE_URL and REDIS_URL set to the deployment's values.
"""

import os
import sys

import psycopg
from redis import Redis
from sqlalchemy.engine import make_url

from app.vercel import _redis_options, database_url, redis_url


def first_line(exc):
    return f"{type(exc).__name__}: {str(exc).splitlines()[0][:300] if str(exc) else ''}"


def main():
    failed = False
    url = make_url(database_url(os.environ["DATABASE_URL"]))
    print(f"database: user={url.username} host={url.host} port={url.port} db={url.database}")
    try:
        with psycopg.connect(
            host=url.host,
            port=url.port,
            user=url.username,
            password=url.password,
            dbname=url.database,
            sslmode=url.query["sslmode"],
            sslrootcert=url.query["sslrootcert"],
            connect_timeout=10,
            prepare_threshold=None,
        ) as connection:
            connection.execute("SELECT 1")
        print("database: OK")
    except Exception as exc:  # noqa: BLE001 - report every failure class to the operator
        failed = True
        print("database: FAILED", first_line(exc))
    raw = os.environ["REDIS_URL"]
    print(f"redis: scheme={raw.split(':', 1)[0]}")
    try:
        Redis.from_url(redis_url(raw), **_redis_options()).ping()
        print("redis: OK")
    except Exception as exc:  # noqa: BLE001
        failed = True
        print("redis: FAILED", first_line(exc))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
