"""Request-based Vercel entrypoint; the normal production checks still apply."""

import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app import create_app

FILE_LIMIT = 4 * 1024 * 1024
# Public provider root certificate (not a secret) bundled through vercel.json includeFiles.
DATABASE_ROOT_CERT = Path(__file__).resolve().parent.parent / "certs" / "supabase-ca.crt"


def database_url(raw, cert=DATABASE_ROOT_CERT):
    """Turn a pasted provider connection string into a verified psycopg URL.

    Only missing settings are added. An explicit weaker sslmode is preserved so that
    production validation rejects it instead of this helper silently upgrading it.
    """
    url = make_url(raw.strip())
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    query = dict(url.query)
    query.setdefault("sslmode", "verify-full")
    query.setdefault("sslrootcert", str(cert))
    return url.update_query_dict(query).render_as_string(hide_password=False)


def redis_url(raw):
    """Select database 0 and require certificate plus hostname verification."""
    parts = urlsplit(raw.strip())
    query = dict(parse_qsl(parts.query))
    query.setdefault("ssl_cert_reqs", "required")
    query.setdefault("ssl_check_hostname", "true")
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path if parts.path not in {"", "/"} else "/0",
            urlencode(query),
            "",
        )
    )


def _redis_options():
    return {
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "max_connections": 4,
        "retry": Retry(NoBackoff(), 0),
    }


def _hosts():
    # Vercel exposes the project's production domain as a system variable. An explicit
    # ALLOWED_HOSTS still wins; protected per-deployment URLs are deliberately excluded.
    return os.environ.get("ALLOWED_HOSTS") or os.environ.get("VERCEL_PROJECT_PRODUCTION_URL", "")


def create_vercel_app():
    """Use external state and bounded connections without starting background work."""
    if os.environ.get("APP_ENV") != "production":
        raise RuntimeError("Set APP_ENV=production before starting the Vercel backend.")
    if os.environ.get("STORAGE_BACKEND") != "supabase":
        raise RuntimeError(
            "Vercel requires STORAGE_BACKEND=supabase; local files are not persistent."
        )
    overrides = {
        # A warm function must not retain idle PostgreSQL connections. Use the
        # provider's verified pooler and leave its connection budget explicit.
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "poolclass": NullPool,
            "connect_args": {"connect_timeout": 5, "prepare_threshold": None},
        },
        "SESSION_REDIS_OPTIONS": _redis_options(),
        "RATELIMIT_STORAGE_OPTIONS": _redis_options(),
        # Leave room for multipart fields around the 4 MiB file. Existing
        # larger objects are rejected by the evidence service before reading.
        "MAX_CONTENT_LENGTH": FILE_LIMIT + 128 * 1024,
        "EVIDENCE_MAX_BYTES": FILE_LIMIT,
        "ALLOWED_HOSTS": _hosts(),
        # Vercel's edge is the single proxy hop and overwrites X-Forwarded-For.
        "TRUSTED_PROXY_HOPS": os.environ.get("TRUSTED_PROXY_HOPS", "1"),
    }
    if os.environ.get("DATABASE_URL"):
        overrides["SQLALCHEMY_DATABASE_URI"] = database_url(os.environ["DATABASE_URL"])
    session_redis = os.environ.get("SESSION_REDIS_URL") or os.environ.get("REDIS_URL")
    if session_redis:
        overrides["SESSION_REDIS_URL"] = redis_url(session_redis)
        overrides["RATELIMIT_STORAGE_URI"] = redis_url(
            os.environ.get("RATELIMIT_STORAGE_URI") or session_redis
        )
    return create_app(overrides)
