"""Vercel must run the strict backend without depending on local state."""

import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import QueuePool

from app.extensions import csrf, db, limiter
from app.vercel import FILE_LIMIT, create_vercel_app, database_url, redis_url


@pytest.fixture(autouse=True)
def records():
    # These checks must never truncate a database or reset a remote Redis store.
    yield


@pytest.fixture
def deployment(monkeypatch, tmp_path):
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    root = tmp_path / "provider-root.crt"
    root.write_text("Path fixture only; this test does not establish a TLS handshake.")
    settings = {
        "APP_ENV": "production",
        "SECRET_KEY": secrets.token_hex(32),
        "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "MFA_KEY_VERSION": "v1",
        "DATABASE_URL": (
            "postgresql+psycopg://runtime:synthetic@db.example.test/core"
            f"?sslmode=verify-full&sslrootcert={root}"
        ),
        "SESSION_REDIS_URL": (
            "rediss://default:synthetic@redis.example.test:6379/0"
            "?ssl_check_hostname=true&ssl_cert_reqs=required"
        ),
        "RATELIMIT_STORAGE_URI": (
            "rediss://default:synthetic@redis.example.test:6379/0"
            "?ssl_check_hostname=true&ssl_cert_reqs=required"
        ),
        "ALLOWED_HOSTS": "recalltrace.vercel.app",
        "TRUSTED_PROXY_HOPS": "1",
        "STORAGE_BACKEND": "supabase",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_STORAGE_BUCKET": "recalltrace-private",
        "SUPABASE_SERVICE_KEY": "synthetic-storage-key-7b4c2d1e9f6a",
        "SCANNER_ENDPOINT": "https://scanner.example.test/scan",
        "SCANNER_TOKEN": "synthetic-scanner-token-7f3a9c2e5b1d8f4a6c0e",
        "MAIL_MODE": "resend",
        "MAIL_API_KEY": "synthetic-mail-key-4c7d2e9f1a",
        "MAIL_FROM": "RecallTrace <app@sender.example>",
    }
    for name in (
        "ACCOUNT_MAIL_DIR",
        "CLAMAV_HOST",
        "RENDER_EXTERNAL_HOSTNAME",
        "SCANNER_MODE",
        "VERCEL_PROJECT_PRODUCTION_URL",
        "REDIS_URL",
        "TRUSTED_PROXY_HOPS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in settings.items():
        monkeypatch.setenv(name, value)
    return settings


@pytest.mark.parametrize("mode", [None, "development", "testing"])
def test_vercel_refuses_accidental_development_deployment(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", mode)
    with pytest.raises(RuntimeError, match="APP_ENV=production"):
        create_vercel_app()


@pytest.mark.parametrize(
    "setting,value,reason",
    [
        ("SCANNER_ENDPOINT", "", "malware scanner"),
        ("MAIL_API_KEY", "", "Resend"),
        ("ALLOWED_HOSTS", "", "ALLOWED_HOSTS"),
        ("STORAGE_BACKEND", "filesystem", "STORAGE_BACKEND=supabase"),
        (
            "SESSION_REDIS_URL",
            "rediss://default:synthetic@redis.example.test/0?ssl_cert_reqs=none",
            "certificate verification",
        ),
    ],
)
def test_vercel_retains_production_gates_before_clients(
    deployment, monkeypatch, setting, value, reason
):
    monkeypatch.setenv(setting, value)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unsafe deployment initialized a Redis client.")

    monkeypatch.setattr(Redis, "from_url", forbidden)
    with pytest.raises(RuntimeError, match=reason):
        create_vercel_app()


def test_vercel_refuses_ephemeral_evidence_even_with_private_directory(
    deployment, monkeypatch, tmp_path
):
    directory = tmp_path / "private-but-ephemeral"
    directory.mkdir(mode=0o700)
    monkeypatch.setenv("STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("EVIDENCE_ROOT", str(directory))
    with pytest.raises(RuntimeError, match="local files are not persistent"):
        create_vercel_app()


def test_vercel_uses_external_state_and_bounded_verified_clients(deployment):
    app = create_vercel_app()
    with app.app_context():
        assert isinstance(db.engine.pool, QueuePool)
        assert db.engine.pool.size() == 2 and db.engine.pool._max_overflow == 3
        assert db.engine.pool._pre_ping and db.engine.pool._recycle == 120
        for client in (app.config["SESSION_REDIS"], limiter.limiter.storage.storage):
            options = client.connection_pool.connection_kwargs
            assert options["socket_connect_timeout"] == 3
            assert options["socket_timeout"] == 3
            assert options["ssl_check_hostname"] is True
            assert options["ssl_cert_reqs"] == "required"
            assert client.connection_pool.max_connections == 4
    assert app.config["SESSION_COOKIE_NAME"] == "__Host-recalltrace"
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["STORAGE_BACKEND"] == "supabase"


def test_vercel_health_does_not_report_ready_during_database_failure(deployment, monkeypatch):
    app = create_vercel_app()

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("Synthetic private connection failure; never expose this.")

    with app.app_context():
        monkeypatch.setattr(db.engine, "connect", unavailable)
    client = app.test_client()
    assert client.get("/health/live", base_url="https://recalltrace.vercel.app").json == {
        "status": "alive"
    }
    response = client.get("/health/ready", base_url="https://recalltrace.vercel.app")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}
    assert "private" not in response.text


def test_vercel_health_does_not_report_ready_during_redis_failure(deployment, monkeypatch):
    app = create_vercel_app()

    def unavailable(*args, **kwargs):
        raise RedisConnectionError("Synthetic private Redis failure; never expose this.")

    monkeypatch.setattr(db.session, "execute", lambda *args, **kwargs: None)
    monkeypatch.setattr(Redis, "execute_command", unavailable)
    response = app.test_client().get("/health/ready", base_url="https://recalltrace.vercel.app")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}
    assert "private" not in response.text


def test_vercel_rejects_unlisted_host(deployment):
    response = (
        create_vercel_app().test_client().get("/health/live", base_url="https://untrusted.example")
    )
    assert response.status_code == 400


def test_vercel_rejects_large_request_before_processing(deployment):
    app = create_vercel_app()
    processed = []

    @app.post("/test-body-limit")
    @csrf.exempt
    @limiter.exempt
    def body_limit():
        from flask import request

        data = request.get_data()
        processed.append(len(data))
        return {"bytes": len(data)}

    response = app.test_client().post(
        "/test-body-limit",
        base_url="https://recalltrace.vercel.app",
        data=b"x" * (FILE_LIMIT + 128 * 1024 + 1),
    )
    assert response.status_code == 413
    assert not processed
    assert app.config["EVIDENCE_MAX_BYTES"] == FILE_LIMIT


def test_entrypoint_imports_without_local_configuration_or_operator_files(deployment, tmp_path):
    source = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "function"
    bundle.mkdir()
    shutil.copytree(source / "app", bundle / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(source / "index.py", bundle / "index.py")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import index; from app.extensions import db; "
            "assert len(db.metadata.tables) == 95; "
            "index.app.jinja_env.get_template('operations/editor.html'); "
            "response = index.app.test_client().get('/health/live', "
            "base_url='https://recalltrace.vercel.app'); "
            "assert response.status_code == 200; "
            "assert response.json == {'status': 'alive'}; "
            "print('isolated backend import passed')",
        ],
        cwd=bundle,
        env={**os.environ, "PYTHONPATH": str(bundle)},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "isolated backend import passed"


def test_pasted_provider_database_url_gains_verified_tls(tmp_path):
    root = tmp_path / "root.crt"
    url = make_url(
        database_url("postgresql://runtime.ref:pw@pooler.example.com:6543/postgres", root)
    )
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "pw"
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"] == str(root)


def test_weaker_explicit_database_tls_is_preserved_for_validation_to_reject(
    deployment, monkeypatch
):
    weak = deployment["DATABASE_URL"].replace("verify-full", "require")
    assert make_url(database_url(weak)).query["sslmode"] == "require"
    monkeypatch.setenv("DATABASE_URL", weak)
    with pytest.raises(RuntimeError, match="verify-full"):
        create_vercel_app()


def test_pasted_upstash_url_selects_database_zero_with_verification():
    url = redis_url("rediss://default:pw@example.upstash.io:6379")
    assert url.startswith("rediss://default:pw@example.upstash.io:6379/0?")
    assert "ssl_cert_reqs=required" in url and "ssl_check_hostname=true" in url
    weak = redis_url("rediss://default:pw@example.upstash.io:6379/0?ssl_cert_reqs=none")
    assert "ssl_cert_reqs=none" in weak


def test_single_redis_url_serves_sessions_and_limiter(deployment, monkeypatch):
    monkeypatch.delenv("SESSION_REDIS_URL")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI")
    monkeypatch.setenv("REDIS_URL", "rediss://default:synthetic@redis.example.test:6379")
    app = create_vercel_app()
    assert app.config["SESSION_REDIS_URL"] == app.config["RATELIMIT_STORAGE_URI"]
    assert app.config["SESSION_REDIS_URL"].startswith("rediss://default:synthetic@")


def test_production_domain_comes_from_vercel_when_hosts_unset(deployment, monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "recall-trace-demo.vercel.app")
    client = create_vercel_app().test_client()
    assert client.get("/health/live", base_url="https://recall-trace-demo.vercel.app").json == {
        "status": "alive"
    }
    assert client.get("/health/live", base_url="https://other.vercel.app").status_code == 400


def test_demo_scanner_opt_in_boots_and_keeps_uploads_quarantined(deployment, monkeypatch):
    monkeypatch.delenv("SCANNER_ENDPOINT")
    monkeypatch.setenv("SCANNER_MODE", "unconfigured")
    app = create_vercel_app()
    assert app.config["SCANNER_MODE"] == "unconfigured"
    with app.app_context():
        from app.services.evidence import scan_bytes

        assert scan_bytes(b"%PDF-1.7 synthetic") == "unavailable"
    from flask_login import AnonymousUserMixin

    page = app.jinja_env.get_template("base.html").render(
        config=app.config,
        current_user=AnonymousUserMixin(),
        get_flashed_messages=lambda **kwargs: [],
        url_for=lambda *args, **kwargs: "/",
    )
    assert "malware scanning is not configured" in page


@pytest.mark.parametrize(
    "mode,endpoint,reason",
    [
        ("unconfigured", "https://scanner.example.test/scan", "SCANNER_MODE=required"),
        ("off", "", "SCANNER_MODE set to required or unconfigured"),
        ("required", "", "malware scanner"),
    ],
)
def test_scanner_mode_cannot_be_ambiguous(deployment, monkeypatch, mode, endpoint, reason):
    monkeypatch.setenv("SCANNER_MODE", mode)
    monkeypatch.setenv("SCANNER_ENDPOINT", endpoint)
    with pytest.raises(RuntimeError, match=reason):
        create_vercel_app()


def test_vercel_git_auto_deployments_are_disabled():
    # Production deployments carry their settings from the operator workflow; an
    # automatic Git build without them must never replace the production alias.
    import json

    config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text())
    assert config["git"] == {"deploymentEnabled": False}
    assert config["functions"]["index.py"]["includeFiles"] == "certs/**"


def test_pasted_trailing_line_breaks_are_not_part_of_settings(deployment, monkeypatch):
    for name in ("MAIL_FROM", "SECRET_KEY", "MFA_ENCRYPTION_KEY", "ALLOWED_HOSTS"):
        monkeypatch.setenv(name, deployment[name] + "\n")
    app = create_vercel_app()
    assert app.config["MAIL_FROM"] == deployment["MAIL_FROM"]
    assert app.config["SECRET_KEY"] == deployment["SECRET_KEY"]
