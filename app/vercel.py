"""Request-based Vercel entrypoint; the normal production checks still apply."""

import os

from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy.pool import NullPool

from app import create_app

FILE_LIMIT = 4 * 1024 * 1024


def _redis_options():
    return {
        "socket_connect_timeout": 3,
        "socket_timeout": 3,
        "max_connections": 4,
        "retry": Retry(NoBackoff(), 0),
    }


def create_vercel_app():
    """Use external state and bounded connections without starting background work."""
    if os.environ.get("APP_ENV") != "production":
        raise RuntimeError("Set APP_ENV=production before starting the Vercel backend.")
    if os.environ.get("STORAGE_BACKEND") != "supabase":
        raise RuntimeError(
            "Vercel requires STORAGE_BACKEND=supabase; local files are not persistent."
        )
    return create_app(
        {
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
        }
    )
