"""Pure deployment configuration checks; no network clients are opened here."""

import base64
import os

import pytest
from flask import Flask

from app.configuration import configure_environment, validate_config


def configuration(tmp_path):
    root = tmp_path / "provider-root.crt"
    root.write_text("Test path only: TLS handshake is covered by live deployment checks.")
    app = Flask(__name__)
    app.config.update(
        APP_ENV="production",
        SECRET_KEY="0d4a60e7c181454489dbc55fc44e4ee5311b7ac16cf4471e99c5cfac27277a12",
        MFA_ENCRYPTION_KEY=base64.urlsafe_b64encode(os.urandom(32)).decode(),
        SQLALCHEMY_DATABASE_URI=f"postgresql+psycopg://runtime:private@db.provider.example/recalltrace?sslmode=verify-full&sslrootcert={root}",
        SESSION_REDIS_URL="rediss://default:private@redis.provider.example:6379/0?ssl_check_hostname=true&ssl_cert_reqs=required",
        RATELIMIT_STORAGE_URI="rediss://default:private@redis.provider.example:6379/1?ssl_check_hostname=true&ssl_cert_reqs=required",
        ALLOWED_HOSTS="recalltrace.provider.example",
        TRUSTED_PROXY_HOPS="1",
        STORAGE_BACKEND="supabase",
        SUPABASE_URL="https://project.supabase.co",
        SUPABASE_STORAGE_BUCKET="private-evidence",
        SUPABASE_SERVICE_KEY="private-test-service-key-a17b3c4d5e6f7g8h9",
        SCANNER_ENDPOINT="https://scanner.provider.example/scan",
        SCANNER_TOKEN="synthetic-scanner-token-7f3a9c2e5b1d8f4a6c0e",
        MAIL_MODE="resend",
        MAIL_API_KEY="private-test-mail-key-a17b3c4d5e6",
        MAIL_FROM="RecallTrace <mail@sender.example>",
    )
    return app


def test_validated_configuration_sets_host_cookie_and_bounded_pool(tmp_path):
    app = configuration(tmp_path)
    configure_environment(app)
    assert app.config["SESSION_COOKIE_NAME"] == "__Host-recalltrace"
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_DOMAIN"] is None
    assert app.config["TRUSTED_HOSTS"] == ["recalltrace.provider.example"]
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"]["pool_size"] == 3
    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"]["pool_pre_ping"] is True
    assert app.wsgi_app.x_proto == 1
    assert app.config["RATELIMIT_STORAGE_OPTIONS"]["ssl_check_hostname"] is True


@pytest.mark.parametrize(
    "name,value",
    [
        ("SECRET_KEY", "x" * 64),
        ("MFA_ENCRYPTION_KEY", "not-a-key"),
        ("MFA_KEY_VERSION", ""),
        ("MFA_KEY_VERSION", "v" * 21),
        ("DEBUG", True),
        ("TESTING", True),
        ("SQLALCHEMY_ECHO", True),
        ("SQLALCHEMY_DATABASE_URI", "sqlite:///production.db"),
        ("SQLALCHEMY_DATABASE_URI", "malformed-url"),
        (
            "SQLALCHEMY_DATABASE_URI",
            "postgresql+psycopg://runtime:private@remote.example/app?sslmode=require",
        ),
        ("SESSION_REDIS_URL", "redis://default:private@remote.example/0"),
        ("SESSION_REDIS_URL", "rediss://default:private@remote.example/0"),
        ("RATELIMIT_STORAGE_URI", "memory://"),
        ("RATELIMIT_STORAGE_URI", "rediss://default:private@remote.example/1?ssl_cert_reqs=none"),
        ("TRUSTED_PROXY_HOPS", "-1"),
        ("TRUSTED_PROXY_HOPS", "4"),
        ("ALLOWED_HOSTS", "*"),
        ("ALLOWED_HOSTS", "https://app.example"),
        ("STORAGE_BACKEND", "public"),
        ("SUPABASE_URL", "http://project.supabase.co"),
        ("SUPABASE_SERVICE_KEY", "replace_me"),
        ("SCANNER_ENDPOINT", ""),
        ("SCANNER_TOKEN", ""),
        ("SCANNER_TOKEN", "too-short"),
        ("MAIL_MODE", "local"),
        ("MAIL_API_KEY", ""),
        ("ACCOUNT_MAIL_DIR", "account-mail"),
    ],
)
def test_unsafe_production_configuration_fails_before_clients(tmp_path, name, value):
    app = configuration(tmp_path)
    app.config[name] = value
    with pytest.raises(RuntimeError, match="Production deployment requires"):
        configure_environment(app)


def test_render_hostname_is_used_without_trusting_forwarded_host(tmp_path, monkeypatch):
    app = configuration(tmp_path)
    app.config.pop("ALLOWED_HOSTS")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "recalltrace.onrender.com")
    configure_environment(app)
    assert app.config["TRUSTED_HOSTS"] == ["recalltrace.onrender.com"]
    assert app.wsgi_app.x_host == 0


def test_private_filesystem_requires_existing_private_persistent_root(tmp_path):
    app = configuration(tmp_path)
    directory = tmp_path / "private-volume"
    directory.mkdir(mode=0o700)
    app.config.update(STORAGE_BACKEND="filesystem", EVIDENCE_ROOT=str(directory))
    configure_environment(app)
    directory.chmod(0o755)
    with pytest.raises(RuntimeError, match="readable only"):
        validate_config(app)


def test_production_rejects_relaxed_cookie_after_configuration(tmp_path):
    app = configuration(tmp_path)
    configure_environment(app)
    app.config["SESSION_COOKIE_SECURE"] = False
    with pytest.raises(RuntimeError, match="cookies"):
        validate_config(app)
