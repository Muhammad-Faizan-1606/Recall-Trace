"""Constrained hosts must reject oversized files before provider or response I/O."""

import hashlib
import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask, render_template
from jinja2 import ChoiceLoader, DictLoader

from app.blueprints import evidence as evidence_routes
from app.services import evidence
from app.services.business import DomainError


@pytest.fixture(autouse=True)
def records():
    # Override the integration fixture: these checks use no database or Redis.
    yield


@pytest.fixture
def size_app(tmp_path):
    app = Flask(
        "evidence-size-tests",
        template_folder=str(Path(__file__).resolve().parents[1] / "app" / "templates"),
    )
    app.config.update(
        EVIDENCE_MAX_BYTES=8,
        EVIDENCE_ROOT=str(tmp_path / "evidence"),
        LOGIN_DISABLED=True,
        WTF_CSRF_ENABLED=False,
    )
    # Workspace templates use the application's display filters (quantities, status tags).
    from app.presentation import register as register_presentation

    register_presentation(app)
    with app.app_context():
        yield app


class BoundedStream(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        assert size > 0, "Evidence reads must always be bounded."
        self.read_sizes.append(size)
        return super().read(size)


class ProviderResponse:
    status_code = 200

    def __init__(self, data=b""):
        self.raw = BoundedStream(data)

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def document(data, **overrides):
    values = {
        "object_key": uuid.uuid4().hex + "/" + "a" * 48,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    return SimpleNamespace(**(values | overrides))


def forbid_io(*_args, **_kwargs):
    raise AssertionError("Oversized evidence must be rejected before external I/O.")


def test_default_file_ceiling_is_unchanged(size_app):
    size_app.config.pop("EVIDENCE_MAX_BYTES")
    assert evidence.max_bytes() == 10 * 1024 * 1024
    assert evidence.max_bytes_label() == "10 MiB"


@pytest.mark.parametrize("limit", [0, -1, evidence.MAX_BYTES + 1, True, "8", 1.5, None])
def test_invalid_or_raised_deployment_limits_fail_closed(size_app, limit):
    size_app.config["EVIDENCE_MAX_BYTES"] = limit
    with pytest.raises(RuntimeError, match="EVIDENCE_MAX_BYTES"):
        evidence.max_bytes()


@pytest.mark.parametrize("backend", ["filesystem", "supabase"])
@pytest.mark.parametrize("data", [b"", b"x" * 9])
def test_rejected_writes_never_touch_storage(size_app, monkeypatch, backend, data):
    size_app.config["STORAGE_BACKEND"] = backend
    monkeypatch.setattr(evidence, "_storage_url", forbid_io)
    monkeypatch.setattr(evidence, "_storage_root", forbid_io)
    with pytest.raises(DomainError, match="1 byte to 8 bytes"):
        evidence.put_bytes(uuid.uuid4(), data)


def test_local_file_exactly_at_limit_round_trips_with_integrity(size_app):
    data = b"12345678"
    key = evidence.put_bytes(uuid.uuid4(), data)
    row = document(data, object_key=key)
    assert evidence.read_bytes(row) == data
    path = Path(size_app.config["EVIDENCE_ROOT"]) / key
    assert path.stat().st_mode & 0o077 == 0
    path.write_bytes(b"87654321")
    with pytest.raises(DomainError, match="integrity"):
        evidence.read_bytes(row)
    path.write_bytes(b"123456789")
    with pytest.raises(DomainError, match="file limit"):
        evidence.read_bytes(row)


def test_remote_write_exactly_at_limit_sends_the_original_bytes(size_app, monkeypatch):
    size_app.config["STORAGE_BACKEND"] = "supabase"
    monkeypatch.setattr(
        evidence, "_storage_url", lambda _key: ("https://storage.example.test/private", {})
    )
    post = Mock(return_value=ProviderResponse())
    monkeypatch.setattr(evidence.requests, "post", post)
    evidence.put_bytes(uuid.uuid4(), b"12345678")
    post.assert_called_once()
    assert post.call_args.kwargs["data"] == b"12345678"
    assert post.call_args.kwargs["headers"]["Content-Type"] == "application/octet-stream"
    assert post.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("backend", ["filesystem", "supabase"])
def test_existing_large_document_is_rejected_before_storage_lookup(size_app, monkeypatch, backend):
    size_app.config["STORAGE_BACKEND"] = backend
    monkeypatch.setattr(evidence, "_storage_url", forbid_io)
    monkeypatch.setattr(evidence, "_storage_root", forbid_io)
    with pytest.raises(DomainError, match="current 8 bytes file limit"):
        evidence.read_bytes(document(b"123456789"))


@pytest.mark.parametrize(
    ("data", "expected_error"),
    [(b"12345678", None), (b"123456789", "file limit"), (b"87654321", "integrity")],
)
def test_remote_reads_are_bounded_and_keep_integrity_checks(
    size_app, monkeypatch, data, expected_error
):
    size_app.config["STORAGE_BACKEND"] = "supabase"
    monkeypatch.setattr(
        evidence, "_storage_url", lambda _key: ("https://storage.example.test/private", {})
    )
    response = ProviderResponse(data)
    get = Mock(return_value=response)
    monkeypatch.setattr(evidence.requests, "get", get)
    row = document(b"12345678")
    if expected_error:
        with pytest.raises(DomainError, match=expected_error):
            evidence.read_bytes(row)
    else:
        assert evidence.read_bytes(row) == data
    assert response.raw.read_sizes == [9]
    assert get.call_args.kwargs["stream"] is True
    assert get.call_args.kwargs["allow_redirects"] is False


def test_upload_is_bounded_and_rejected_before_scan_or_store(size_app, monkeypatch):
    require = Mock()
    monkeypatch.setattr(evidence, "require", require)
    monkeypatch.setattr(evidence, "membership_for", lambda _company: SimpleNamespace(id=1))
    monkeypatch.setattr(evidence, "db", SimpleNamespace(session=SimpleNamespace(rollback=Mock())))
    monkeypatch.setattr(evidence, "scan_bytes", forbid_io)
    monkeypatch.setattr(evidence, "put_bytes", forbid_io)
    stream = BoundedStream(b"x" * 30)
    company_id = uuid.uuid4()
    with pytest.raises(DomainError, match="1 byte to 8 bytes"):
        evidence.upload(company_id, "oversized.pdf", stream)
    assert stream.read_sizes == [9]
    require.assert_called_once_with(company_id, "evidence.upload")


def test_csv_exactly_at_limit_parses_and_one_extra_byte_is_rejected(size_app):
    data = b"code,name,kind\nPART,Part,component\n"
    size_app.config["EVIDENCE_MAX_BYTES"] = len(data)
    assert evidence.parse_items_csv(data) == [{"code": "PART", "name": "Part", "kind": "component"}]
    with pytest.raises(DomainError, match="CSV must contain"):
        evidence.parse_items_csv(data + b"\n")


def test_import_stream_is_bounded_and_rejected_before_business_writes(size_app, monkeypatch):
    monkeypatch.setattr(evidence, "actor", lambda *_args: SimpleNamespace(id=1))
    monkeypatch.setattr(evidence, "company_lock", forbid_io)
    monkeypatch.setattr(evidence, "put_bytes", forbid_io)
    stream = BoundedStream(b"code,name,kind\nPART,Part,component\n")
    with pytest.raises(DomainError, match="CSV must contain 1 byte to 8 bytes"):
        evidence.prepare_import(uuid.uuid4(), "items.csv", stream, "synthetic_import_id")
    assert stream.read_sizes == [9]


def minimal_template_base(app):
    app.jinja_loader = ChoiceLoader(
        [DictLoader({"base.html": "{% block content %}{% endblock %}"}), app.jinja_loader]
    )


def test_large_existing_download_returns_safe_http_error(size_app, monkeypatch):
    minimal_template_base(size_app)
    size_app.register_blueprint(evidence_routes.bp)
    rollback = Mock()
    monkeypatch.setattr(
        evidence_routes, "db", SimpleNamespace(session=SimpleNamespace(rollback=rollback))
    )
    monkeypatch.setattr(evidence, "require", Mock())
    monkeypatch.setattr(
        evidence,
        "scoped",
        lambda *_args: document(
            b"123456789", archived_at=None, scan_status="clean", state="active"
        ),
    )
    monkeypatch.setattr(evidence, "_storage_root", forbid_io)
    response = size_app.test_client().get(
        f"/companies/{uuid.uuid4()}/evidence/{uuid.uuid4()}/download"
    )
    assert response.status_code == 409
    assert "File exceeds the current 8 bytes file limit." in response.text
    rollback.assert_called_once()


def test_evidence_page_displays_the_configured_file_limit(size_app, monkeypatch):
    size_app.config["EVIDENCE_MAX_BYTES"] = 4 * 1024 * 1024
    minimal_template_base(size_app)
    size_app.register_blueprint(evidence_routes.bp)
    monkeypatch.setattr(evidence_routes, "membership_for", lambda _company: SimpleNamespace(id=1))
    monkeypatch.setattr(evidence_routes, "allowed", lambda *_args: True)
    monkeypatch.setattr(
        evidence_routes,
        "db",
        SimpleNamespace(session=SimpleNamespace(get=lambda *_args: SimpleNamespace(name="Test"))),
    )
    with size_app.test_request_context("/"):
        html = render_template(
            "evidence/list.html",
            page=SimpleNamespace(items=[], has_prev=False, has_next=False),
            imports=[],
            exports=[],
            upload_form=evidence_routes.UploadForm(),
            import_form=evidence_routes.ImportForm(),
            export_form=evidence_routes.ExportForm(),
            **evidence_routes.context(uuid.uuid4()),
        )
    assert "File limit: 4 MiB per file" in html
    assert "up to 10 MiB" not in html
