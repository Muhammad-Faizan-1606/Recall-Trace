"""Fault injection and hostile configuration/input tests at application boundaries."""

import pytest
from conftest import login, post_form, root
from redis.exceptions import ConnectionError as RedisConnectionError

from app import create_app
from app.extensions import db, limiter, login_manager
from app.models import Item
from app.services.business import DomainError, quantity


@pytest.mark.parametrize("environment", ["prod", "Production", "staging", "", "production "])
def test_mistyped_environment_never_silently_uses_development(environment):
    with pytest.raises(RuntimeError, match="APP_ENV"):
        create_app({"APP_ENV": environment})


def test_liveness_ignores_rate_counter_outage(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RedisConnectionError("synthetic rate storage outage")

    monkeypatch.setattr(limiter.limiter.storage, "incr", unavailable)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json == {"status": "alive"}


def test_readiness_returns_503_when_rate_storage_fails(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RedisConnectionError("synthetic rate storage outage")

    monkeypatch.setattr(limiter.limiter.storage, "check", unavailable)
    monkeypatch.setattr(limiter.limiter.storage, "incr", unavailable)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json == {"status": "unavailable"}


def test_health_probes_do_not_load_authenticated_user(client, monkeypatch):
    login(client)

    def fail_identity(_):
        raise RuntimeError("Synthetic identity backend outage")

    monkeypatch.setattr(login_manager, "_user_callback", fail_identity)
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("resource", ["catalog", "master"])
def test_nul_text_never_reaches_postgresql(client, records, resource):
    login(client)
    if resource == "catalog":
        path = root(records) + "/new"
        values = {
            "code": "INVALID-NUL",
            "name": "Invalid\x00name",
            "kind": "component",
            "version": 0,
        }
    else:
        path = f"/companies/{records['companies']['aurora']}/master/partners/new"
        values = {
            "code": "INVALID-NUL",
            "name": "Invalid\x00name",
            "status": "active",
            "version": 0,
        }
    response = post_form(client, path, values)
    assert response.status_code == 422
    assert db.session.query(Item).filter_by(code="INVALID-NUL").count() == 0


@pytest.mark.parametrize("value", ["1e999999999", "-1e999999999", "1e-999999999"])
def test_extreme_decimal_exponents_are_domain_errors(value):
    with pytest.raises(DomainError):
        quantity(value)
