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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from app.extensions import csrf, db, limiter
from app.vercel import FILE_LIMIT, create_vercel_app


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
        "MAIL_MODE": "resend",
        "MAIL_API_KEY": "synthetic-mail-key-4c7d2e9f1a",
        "MAIL_FROM": "RecallTrace <app@sender.example>",
    }
    for name in ("ACCOUNT_MAIL_DIR", "CLAMAV_HOST", "RENDER_EXTERNAL_HOSTNAME"):
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
        assert isinstance(db.engine.pool, NullPool)
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
            "assert len(db.metadata.tables) == 72; "
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
