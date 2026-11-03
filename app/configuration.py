"""Deployment configuration: fail before opening network clients on unsafe settings."""

import base64
import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from werkzeug.middleware.proxy_fix import ProxyFix

PRODUCTION_SETTINGS = (
    "MFA_ENCRYPTION_KEY",
    "MFA_KEY_VERSION",
    "SESSION_REDIS_URL",
    "ALLOWED_HOSTS",
    "TRUSTED_PROXY_HOPS",
    "STORAGE_BACKEND",
    "EVIDENCE_ROOT",
    "SUPABASE_URL",
    "SUPABASE_STORAGE_BUCKET",
    "SUPABASE_SERVICE_KEY",
    "SCANNER_ENDPOINT",
    "CLAMAV_HOST",
    "CLAMAV_PORT",
    "MAIL_MODE",
    "MAIL_API_KEY",
    "MAIL_FROM",
)


def _failure(message):
    raise RuntimeError(f"Production deployment requires {message}.")


def _secret(value, minimum=32):
    if not isinstance(value, str) or len(value) < minimum:
        return False
    lowered = value.lower()
    return len(set(value)) >= 10 and not any(
        marker in lowered
        for marker in ("change_me", "changeme", "replace_me", "placeholder", "example-secret")
    )


def _endpoint(value):
    try:
        parsed = urlsplit(value or "")
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
    except ValueError:
        return False


def configure_environment(app):
    """Call after create_app's explicit overrides, before initializing extensions.

    Explicit test/application overrides win over process settings. Production cookie
    properties are always strengthened, never relaxed by an inherited development default.
    """
    if app.config.get("APP_ENV") not in {"development", "testing", "production"}:
        raise RuntimeError("APP_ENV must be development, testing, or production.")
    for name in PRODUCTION_SETTINGS:
        if name not in app.config and name in os.environ:
            app.config[name] = os.environ[name]
    app.config.setdefault(
        "SQLALCHEMY_ENGINE_OPTIONS",
        {
            "pool_pre_ping": True,
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 10,
            "pool_recycle": 300,
        },
    )
    app.config.setdefault("SQLALCHEMY_ECHO", False)
    app.config.setdefault("MFA_KEY_VERSION", "v1")
    app.config.setdefault("STORAGE_BACKEND", "filesystem")
    app.config.setdefault("MAIL_MODE", "unconfigured")
    app.config.setdefault("MAX_CONTENT_LENGTH", 11 * 1024 * 1024)
    if app.config.get("APP_ENV") != "production":
        return
    hosts = app.config.get("ALLOWED_HOSTS") or os.getenv("RENDER_EXTERNAL_HOSTNAME", "")
    app.config["TRUSTED_HOSTS"] = (
        [h.strip() for h in hosts.split(",") if h.strip()] if isinstance(hosts, str) else hosts
    )
    app.config.update(
        SESSION_COOKIE_NAME="__Host-recalltrace",
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_PATH="/",
        SESSION_COOKIE_DOMAIN=None,
        PREFERRED_URL_SCHEME="https",
    )
    validate_config(app)
    app.config["RATELIMIT_STORAGE_OPTIONS"] = {
        **app.config.get("RATELIMIT_STORAGE_OPTIONS", {}),
        "ssl_check_hostname": True,
        "ssl_cert_reqs": "required",
    }
    hops = int(app.config["TRUSTED_PROXY_HOPS"])
    if hops:
        # Deployment must permit ingress only through these known proxy hops.
        # Host is never accepted from X-Forwarded-Host; Flask checks the actual Host.
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=hops, x_proto=hops, x_host=0, x_port=0, x_prefix=0
        )


def validate_config(app):
    """Validate production settings; this does not claim live service readiness."""
    cfg = app.config
    if cfg.get("APP_ENV") != "production":
        return
    if cfg.get("DEBUG") or cfg.get("TESTING") or cfg.get("SQLALCHEMY_ECHO"):
        _failure("debug, testing and SQL statement logging disabled")
    if not _secret(cfg.get("SECRET_KEY")):
        _failure("a unique random SECRET_KEY of at least 32 characters")
    try:
        key = cfg.get("MFA_ENCRYPTION_KEY", "")
        if len(base64.urlsafe_b64decode(key.encode("ascii"))) != 32:
            raise ValueError
    except (ValueError, TypeError, AttributeError, UnicodeError):
        _failure("a valid Fernet MFA_ENCRYPTION_KEY from secure configuration")
    if not isinstance(cfg.get("MFA_KEY_VERSION"), str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]{1,20}", cfg["MFA_KEY_VERSION"]
    ):
        _failure("a bounded MFA_KEY_VERSION for encrypted account requests and factors")
    try:
        database = make_url(cfg.get("SQLALCHEMY_DATABASE_URI", ""))
        if (
            database.drivername != "postgresql+psycopg"
            or not database.host
            or not database.database
            or not database.username
            or not database.password
        ):
            raise ValueError
    except (ValueError, TypeError, ArgumentError):
        _failure("an authenticated PostgreSQL psycopg database connection")
    if database.host not in ("127.0.0.1", "localhost", "::1"):
        if database.query.get("sslmode") != "verify-full":
            _failure("PostgreSQL TLS with sslmode=verify-full")
        cert = database.query.get("sslrootcert")
        if not cert or not Path(cert).is_file():
            _failure("an installed PostgreSQL root certificate selected by sslrootcert")
    redis_url = cfg.get("SESSION_REDIS_URL")
    if not redis_url:
        _failure("SESSION_REDIS_URL selected explicitly")
    for name, value in (
        ("SESSION_REDIS_URL", redis_url),
        ("RATELIMIT_STORAGE_URI", cfg.get("RATELIMIT_STORAGE_URI")),
    ):
        try:
            endpoint = urlsplit(value or "")
            valid = endpoint.scheme == "rediss" and endpoint.hostname and endpoint.password
            options = parse_qs(endpoint.query.lower())
            insecure_tls = any(
                option not in ("required", "2")
                for option in options.get("ssl_cert_reqs", ["missing"])
            ) or any(
                option not in ("true", "1")
                for option in options.get("ssl_check_hostname", ["missing"])
            )
        except ValueError:
            valid, insecure_tls = False, True
        if not valid or insecure_tls:
            _failure(f"authenticated TLS Redis for {name}, with certificate verification enabled")
    hosts = cfg.get("TRUSTED_HOSTS")
    if not hosts or not isinstance(hosts, (list, tuple)):
        _failure("explicit ALLOWED_HOSTS (or Render's external hostname)")
    for host in hosts:
        if (
            not isinstance(host, str)
            or not host
            or host.startswith(".")
            or any(c in host for c in ("/", ":", "*", " "))
        ):
            _failure("exact public hostnames without wildcards or URL schemes")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith(".test"):
                _failure("public deployment hostnames")
    try:
        hops = int(cfg.get("TRUSTED_PROXY_HOPS", ""))
        if not 0 <= hops <= 3:
            raise ValueError
    except (ValueError, TypeError):
        _failure("explicit TRUSTED_PROXY_HOPS between 0 and 3")
    if cfg.get("STORAGE_BACKEND") == "supabase":
        if (
            not _endpoint(cfg.get("SUPABASE_URL"))
            or not cfg.get("SUPABASE_STORAGE_BUCKET")
            or not _secret(cfg.get("SUPABASE_SERVICE_KEY"))
        ):
            _failure("a private Supabase bucket and securely supplied storage credentials")
    elif cfg.get("STORAGE_BACKEND") == "filesystem":
        evidence = cfg.get("EVIDENCE_ROOT")
        if not evidence or not Path(evidence).is_absolute() or not Path(evidence).is_dir():
            _failure("an explicit existing private persistent EVIDENCE_ROOT")
        if Path(evidence).stat().st_mode & 0o077:
            _failure("EVIDENCE_ROOT readable only by the application user")
    else:
        _failure("an implemented private evidence storage backend")
    if not _endpoint(cfg.get("SCANNER_ENDPOINT")) and not cfg.get("CLAMAV_HOST"):
        _failure(
            "a configured evidence malware scanner (unavailable scanners keep files quarantined)"
        )
    if (
        cfg.get("MAIL_MODE") != "resend"
        or not _secret(cfg.get("MAIL_API_KEY"), 20)
        or not cfg.get("MAIL_FROM")
    ):
        _failure("Resend mail credentials and an authorized sending address")
    for field in ("MAIL_FROM", "CLAMAV_HOST"):
        if any(c in str(cfg.get(field, "")) for c in ("\r", "\n")):
            _failure("valid mail and scanner configuration")
    if cfg.get("ACCOUNT_MAIL_DIR"):
        _failure("the local account mailbox disabled")
    if (
        cfg.get("SESSION_COOKIE_NAME") != "__Host-recalltrace"
        or not cfg.get("SESSION_COOKIE_SECURE")
        or not cfg.get("SESSION_COOKIE_HTTPONLY")
        or cfg.get("SESSION_COOKIE_PATH") != "/"
        or cfg.get("SESSION_COOKIE_DOMAIN")
    ):
        _failure("Secure HttpOnly __Host- cookies without Domain")
