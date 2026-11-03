import os
import re
import secrets

import psycopg
import pytest
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask.testing import FlaskClient
from flask_migrate import upgrade
from redis import Redis
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app import create_app
from app.extensions import db, limiter
from app.models import Item, ItemVariant, Organization, UnitsOfMeasure

PASSWORD = "Fictional integration password 492!"


@pytest.fixture(scope="session")
def app():
    load_dotenv()
    url = make_url(os.environ["DATABASE_URL"])
    # Hard-coded dedicated database; never drop or truncate the application database.
    test_url = url.set(database="recalltrace_test")
    with psycopg.connect(
        url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False),
        autocommit=True,
    ) as connection:
        if not connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = 'recalltrace_test'"
        ).fetchone():
            connection.execute("CREATE DATABASE recalltrace_test")
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": secrets.token_hex(32),
            "MFA_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "MFA_KEY_VERSION": "v1",
            "SQLALCHEMY_DATABASE_URI": test_url.render_as_string(hide_password=False),
            "SESSION_REDIS": Redis.from_url("redis://127.0.0.1:6379/3"),
            "SESSION_KEY_PREFIX": "recalltrace-test:",
            "RATELIMIT_STORAGE_URI": "redis://127.0.0.1:6379/2",
        }
    )
    app.test_client_class = RequestContextClient
    with app.app_context():
        upgrade(directory="migrations")
    yield app


@pytest.fixture(autouse=True)
def records(app):
    with app.app_context():
        assert make_url(app.config["SQLALCHEMY_DATABASE_URI"]).database == "recalltrace_test"
        names = ", ".join('"' + name + '"' for name in db.metadata.tables)
        db.session.execute(text(f"TRUNCATE {names} CASCADE"))
        db.session.commit()
        limiter.reset()
        result = app.test_cli_runner().invoke(args=["seed-demo", "--password", PASSWORD])
        assert result.exit_code == 0, result.output
        companies = {r.slug: r.id for r in db.session.scalars(select(Organization))}
        ids = {"companies": companies}
        for slug, company_id in companies.items():
            for kind, model in [
                ("items", Item),
                ("variants", ItemVariant),
                ("units", UnitsOfMeasure),
            ]:
                row = db.session.scalar(select(model).where(model.organization_id == company_id))
                ids[f"{slug}_{kind}"] = row.id
        yield ids
        db.session.remove()


class RequestContextClient(FlaskClient):
    def open(self, *args, **kwargs):
        # The test keeps a DB context; real HTTP requests have fresh application state.
        with self.application.app_context():
            response = super().open(*args, **kwargs)
        db.session.expire_all()
        return response


@pytest.fixture
def client(app):
    return RequestContextClient(app)


def csrf(response):
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', response.text)
    assert match, response.text
    return match.group(1)


def login(client, email="catalog-editor@aurora.test"):
    token = csrf(client.get("/login"))
    response = client.post(
        "/login", data={"email": email, "password": PASSWORD, "csrf_token": token}
    )
    assert response.status_code == 303, response.text
    return response


def root(records, kind="items", company="aurora"):
    return f"/companies/{records['companies'][company]}/catalog/{kind}"


def post_form(client, path, data):
    page = client.get(path)
    payload = dict(data, csrf_token=csrf(page))
    return client.post(path, data=payload)


@pytest.fixture
def mail_spool(app):
    import tempfile
    from pathlib import Path

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    previous = app.config.get("ACCOUNT_MAIL_DIR")
    with tempfile.TemporaryDirectory(prefix="test-mail-", dir=app.instance_path) as directory:
        app.config["ACCOUNT_MAIL_DIR"] = directory
        yield Path(directory)
    app.config["ACCOUNT_MAIL_DIR"] = previous


def read_mail_token(mail_spool, subject):
    import json

    from app.models.evidence import JobOutbox
    from app.services.jobs import run_one

    # Public recovery requests are asynchronous. Simulate the real worker in
    # tests that deliberately await account mail; never in the HTTP handler.
    for _ in range(100):
        pending = db.session.scalar(
            select(JobOutbox.id)
            .where(JobOutbox.kind == "account.challenge", JobOutbox.status == "pending")
            .limit(1)
        )
        if pending is None:
            break
        run_one()

    for path in sorted(mail_spool.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        message = json.loads(path.read_text())
        if subject in message["subject"]:
            return re.search(r"\n([A-Za-z0-9_-]{43})\n", message["body"]).group(1)
    raise AssertionError("Expected private development message was not delivered")


@pytest.fixture
def owner(app, records):
    result = app.test_cli_runner().invoke(
        args=[
            "create-owner",
            "--company",
            "aurora",
            "--email",
            "owner@aurora.test",
            "--password",
            PASSWORD,
        ]
    )
    assert result.exit_code == 0, result.output
    return "owner@aurora.test"
