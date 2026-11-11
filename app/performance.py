"""Request performance: CDN-cacheable static assets and per-request timing.

Static files get content-hashed URLs (``app.css?v=1a2b3c4d5e``) and a one-year
immutable cache policy, so a CDN can serve them without invoking the application.
Static requests never open the server-side session, so they cost no Redis or
database round trip and never set a cookie that would prevent CDN caching.

Every other response carries a ``Server-Timing`` header with database, connection
and Redis time, so the cost of a page is visible in browser developer tools.
Only durations and counts are exposed; never query text or parameters.
"""

import hashlib
import time
from functools import wraps
from pathlib import Path

from flask import g, has_request_context, request
from sqlalchemy import event

STATIC_CACHE = "public, max-age=31536000, s-maxage=31536000, immutable"
UNVERSIONED_STATIC_CACHE = "public, max-age=86400, s-maxage=86400"
SLOW_REQUEST_MS = 1000


def _timings():
    if not has_request_context():
        return None
    return g.setdefault(
        "_timing",
        {"db_ms": 0.0, "db_count": 0, "connect_ms": 0.0, "redis_ms": 0.0, "redis_count": 0},
    )


def is_static_path(app, path):
    prefix = (app.static_url_path or "/static").rstrip("/") + "/"
    return path.startswith(prefix)


class StaticAwareSessionInterface:
    """Skip server-side session work for static files; delegate everything else."""

    def __init__(self, app, inner):
        self.app = app
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def open_session(self, app, request):
        if is_static_path(app, request.path):
            return self.inner.make_null_session(app)
        return self.inner.open_session(app, request)

    def save_session(self, app, session, response):
        if is_static_path(app, request.path):
            return None
        return self.inner.save_session(app, session, response)

    def is_null_session(self, obj):
        return self.inner.is_null_session(obj)


def _instrument_redis(client):
    """Time each Redis command on this client instance."""
    if client is None or getattr(client, "_recalltrace_timed", False):
        return
    original = client.execute_command

    @wraps(original)
    def timed(*args, **kwargs):
        timings = _timings()
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            if timings is not None:
                timings["redis_ms"] += (time.perf_counter() - started) * 1000
                timings["redis_count"] += 1

    client.execute_command = timed
    client._recalltrace_timed = True


def _instrument_engine(engine):
    if getattr(engine, "_recalltrace_timed", False):
        return

    @event.listens_for(engine, "do_connect")
    def connect_started(dialect, conn_rec, cargs, cparams):
        conn_rec.info["_connect_started"] = time.perf_counter()

    @event.listens_for(engine.pool, "connect")
    def connect_finished(dbapi_connection, connection_record):
        started = connection_record.info.pop("_connect_started", None)
        timings = _timings()
        if started is not None and timings is not None:
            timings["connect_ms"] += (time.perf_counter() - started) * 1000

    @event.listens_for(engine, "before_cursor_execute")
    def query_started(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_query_started", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def query_finished(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_query_started")
        timings = _timings()
        if starts and timings is not None:
            timings["db_ms"] += (time.perf_counter() - starts.pop()) * 1000
            timings["db_count"] += 1

    engine._recalltrace_timed = True


_STATIC_VERSIONS = {}


def static_version(app, filename):
    """Short content hash of a static file, cached per process."""
    _cache = _STATIC_VERSIONS
    key = (app.static_folder, filename)
    if key not in _cache:
        path = Path(app.static_folder) / filename
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
        except OSError:
            digest = None
        _cache[key] = digest
    return _cache[key]


def register(app, db, limiter):
    app.session_interface = StaticAwareSessionInterface(app, app.session_interface)

    @limiter.request_filter
    def static_assets_are_not_rate_limited():
        # Static files are public, cacheable and cheap; counting them costs a Redis call.
        return is_static_path(app, request.path)

    @app.url_defaults
    def versioned_static(endpoint, values):
        if endpoint == "static" and "filename" in values and "v" not in values:
            version = static_version(app, values["filename"])
            if version:
                values["v"] = version

    @app.before_request
    def start_timer():
        g._request_started = time.perf_counter()
        _timings()

    @app.after_request
    def finish_timer(response):
        if is_static_path(app, request.path):
            versioned = request.args.get("v")
            filename = request.path[len((app.static_url_path or "/static").rstrip("/")) + 1 :]
            current = static_version(app, filename) if versioned else None
            response.headers["Cache-Control"] = (
                STATIC_CACHE if versioned and versioned == current else UNVERSIONED_STATIC_CACHE
            )
            response.headers.pop("Set-Cookie", None)
            response.vary.discard("Cookie")
            return response
        started = g.get("_request_started")
        timings = g.get("_timing")
        if started is None or timings is None:
            return response
        total = (time.perf_counter() - started) * 1000
        other = max(total - timings["db_ms"] - timings["connect_ms"] - timings["redis_ms"], 0)
        response.headers["Server-Timing"] = ", ".join(
            [
                f'db;dur={timings["db_ms"]:.1f};desc="{timings["db_count"]} queries"',
                f"db-connect;dur={timings['connect_ms']:.1f}",
                f'redis;dur={timings["redis_ms"]:.1f};desc="{timings["redis_count"]} calls"',
                f"app;dur={other:.1f}",
                f"total;dur={total:.1f}",
            ]
        )
        if total >= SLOW_REQUEST_MS:
            app.logger.warning(
                "Slow request %s %s: total=%.0fms db=%.0fms/%d connect=%.0fms redis=%.0fms/%d",
                request.method,
                request.url_rule.rule if request.url_rule else "unmatched",
                total,
                timings["db_ms"],
                timings["db_count"],
                timings["connect_ms"],
                timings["redis_ms"],
                timings["redis_count"],
            )
        return response

    with app.app_context():
        _instrument_engine(db.engine)
    _instrument_redis(app.config.get("SESSION_REDIS"))
    storage = getattr(getattr(limiter, "limiter", None), "storage", None)
    _instrument_redis(getattr(storage, "storage", None))
