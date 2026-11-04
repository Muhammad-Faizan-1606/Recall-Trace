"""The public frontend preview must remain independent and read-only."""

from html.parser import HTMLParser

import pytest

from app.preview import create_preview_app

HOST = "preview.example.test"
PAGES = (
    "/",
    "/investigations/c10",
    "/stock",
    "/catalog",
    "/notices",
    "/evidence",
    "/access",
    "/settings",
)


@pytest.fixture(autouse=True)
def records():
    # This module intentionally has no PostgreSQL or Redis test dependency.
    yield


@pytest.fixture
def preview_app(monkeypatch):
    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")
    return create_preview_app({"ALLOWED_HOSTS": HOST, "TRUSTED_PROXY_HOPS": 0})


class Controls(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self.buttons = []

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form":
            self.forms.append(fields)
        if tag == "button":
            self.buttons.append(fields)


@pytest.mark.parametrize("value", [None, "", "1", "true", "production"])
def test_preview_requires_explicit_read_only_opt_in(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RECALLTRACE_PREVIEW", raising=False)
    else:
        monkeypatch.setenv("RECALLTRACE_PREVIEW", value)
    with pytest.raises(RuntimeError):
        create_preview_app({"ALLOWED_HOSTS": HOST})


@pytest.mark.parametrize("setting", ["DEBUG", "TESTING"])
def test_preview_refuses_public_debug_and_test_modes(monkeypatch, setting):
    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")
    with pytest.raises(RuntimeError):
        create_preview_app({"ALLOWED_HOSTS": HOST, setting: True})


def test_preview_never_initializes_production_clients(monkeypatch):
    from app import extensions

    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")

    def forbidden(*args, **kwargs):
        raise AssertionError("A public preview must not initialize production services.")

    monkeypatch.setattr(extensions.db, "init_app", forbidden)
    monkeypatch.setattr(extensions.sessions, "init_app", forbidden)
    monkeypatch.setattr(extensions.limiter, "init_app", forbidden)
    app = create_preview_app({"ALLOWED_HOSTS": HOST, "TRUSTED_PROXY_HOPS": 0})
    response = app.test_client().get("/", base_url="https://" + HOST)
    assert response.status_code == 200
    assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("path", PAGES)
def test_fictional_pages_render_without_login_or_active_forms(preview_app, path):
    response = preview_app.test_client().get(path, base_url="https://" + HOST)
    assert response.status_code == 200
    assert b"Demo with sample data" in response.data
    assert b"Changes are disabled" in response.data
    controls = Controls()
    controls.feed(response.text)
    assert not controls.forms
    assert all("disabled" in button for button in controls.buttons)
    assert "Set-Cookie" not in response.headers


@pytest.mark.parametrize("path", PAGES + ("/health/ready",))
def test_preview_cannot_accept_mutations(preview_app, path):
    response = preview_app.test_client().post(path, base_url="https://" + HOST)
    assert response.status_code == 405


@pytest.mark.parametrize(
    "path", ["/login", "/account/reset/request", "/account/verify/request", "/api/users"]
)
def test_preview_does_not_register_production_entry_points(preview_app, path):
    assert preview_app.test_client().get(path, base_url="https://" + HOST).status_code == 404


def test_preview_rejects_untrusted_host_and_sets_security_headers(preview_app):
    client = preview_app.test_client()
    assert client.get("/", base_url="https://untrusted.example").status_code == 400
    response = client.get("/", base_url="https://" + HOST)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "object-src 'none'" in response.headers["Content-Security-Policy"]
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_render_hostname_is_exactly_trusted(monkeypatch):
    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "recalltrace-preview.onrender.com")
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    app = create_preview_app({"TRUSTED_PROXY_HOPS": 1})
    client = app.test_client()
    assert client.get("/", base_url="https://recalltrace-preview.onrender.com").status_code == 200
    assert client.get("/", base_url="https://other.onrender.com").status_code == 400


@pytest.mark.parametrize("host", ["*", ".example.com", "https://preview.example.com"])
def test_preview_rejects_unsafe_host_configuration(monkeypatch, host):
    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")
    with pytest.raises(RuntimeError):
        create_preview_app({"ALLOWED_HOSTS": host})


def test_health_and_local_assets_are_available(preview_app):
    client = preview_app.test_client()
    for path, status in (("/health/live", "alive"), ("/health/ready", "ready")):
        response = client.get(path, base_url="https://" + HOST)
        assert response.status_code == 200
        assert response.json["status"] == status
    for name in ("vendor/bootstrap.min.css", "app.css", "preview.css"):
        response = client.get("/static/" + name, base_url="https://" + HOST)
        assert response.status_code == 200
        assert response.data


def test_c10_scope_is_separate_from_unaffected_source(preview_app):
    response = preview_app.test_client().get("/investigations/c10", base_url="https://" + HOST)
    assert response.status_code == 200
    for expected in ("C10", "L1", "L2", "S1", "S2", "150", "110", "40", "50", "C11"):
        assert expected in response.text
