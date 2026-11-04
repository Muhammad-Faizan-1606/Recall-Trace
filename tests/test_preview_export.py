"""Static artifacts must expose only fictional UI and explicitly public assets."""

import json

import pytest

from app.preview import PAGES, create_preview_app
from scripts.export_preview import CANONICAL_PATHS, export_preview, validated_base_path


@pytest.fixture(autouse=True)
def records(monkeypatch):
    # Override the database-seeding fixture; this feature must work with no DB.
    monkeypatch.setenv("RECALLTRACE_PREVIEW", "read-only")
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    yield


def test_project_export_has_prefixed_navigation_and_only_public_content(tmp_path, monkeypatch):
    secret = "PRIVATE_DEPLOYMENT_VALUE_MUST_NEVER_BE_EXPORTED_492"
    monkeypatch.setenv("SECRET_KEY", secret)
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://private:" + secret + "@db.test/private"
    )
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", secret)
    output = tmp_path / "_site"
    result = export_preview(output, "/Recall-Trace")
    assert result["html_pages"] == 16
    for route in CANONICAL_PATHS + tuple("/preview/" + page for page in PAGES):
        path = output / route.lstrip("/") / "index.html"
        assert path.is_file()
        content = path.read_text()
        assert "Demo with sample data. Changes are disabled." in content
        assert 'href="/Recall-Trace/static/' in content
        assert 'href="/Recall-Trace/preview/' in content
        assert secret not in content
        assert "<form" not in content
    for name in ("live", "ready"):
        directory = output / "health" / name
        assert json.loads((directory / "index.html").read_text())["mode"] == "read-only-preview"
        assert (directory / "index.json").read_bytes() == (directory / "index.html").read_bytes()
    assert (output / "static/vendor/bootstrap.min.css").is_file()
    assert (output / "static/preview.css").is_file()
    assert (output / "robots.txt").is_file()
    assert (output / "favicon.ico").is_file()
    assert (output / "404.html").is_file()
    assert (output / ".nojekyll").is_file()
    names = [str(path.relative_to(output)) for path in output.rglob("*") if path.is_file()]
    assert not any(name.endswith((".py", ".db", ".sqlite", ".env")) for name in names)
    assert not any(name.startswith(("migrations/", "instance/", "app/")) for name in names)
    assert all(
        secret.encode() not in path.read_bytes() for path in output.rglob("*") if path.is_file()
    )


def test_export_does_not_overwrite_existing_output(tmp_path):
    original = tmp_path / "original.txt"
    original.write_text("preserve this")
    with pytest.raises(ValueError, match="nonempty"):
        export_preview(tmp_path, "/Recall-Trace")
    assert original.read_text() == "preserve this"


def test_static_symlink_cannot_export_private_file(tmp_path, monkeypatch):
    private = tmp_path / "private.env"
    private.write_text("not public")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "innocent.css").symlink_to(private)
    app = create_preview_app({"ALLOWED_HOSTS": "muhammad-faizan-1606.github.io"})
    app.static_folder = str(assets)
    monkeypatch.setattr("scripts.export_preview.create_preview_app", lambda _config: app)
    with pytest.raises(ValueError, match="symlink"):
        export_preview(tmp_path / "_site", "/Recall-Trace")
    assert not (tmp_path / "_site").exists()


@pytest.mark.parametrize(
    "path",
    [
        "relative",
        "//outside.test",
        "/../site",
        "/a/../../b",
        "/a//b",
        "/a%2fb",
        "/a?x=1",
        "/a#b",
        "/a\\b",
    ],
)
def test_unsafe_base_path_is_rejected(path):
    with pytest.raises(ValueError):
        validated_base_path(path)


def test_static_asset_filter_excludes_configuration_and_source_files(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "good.css").write_text("body { color: black; }")
    for name in (".env", "server.py", "database.sqlite", "credentials.json"):
        (assets / name).write_text("PRIVATE")
    app = create_preview_app({"ALLOWED_HOSTS": "muhammad-faizan-1606.github.io"})
    app.static_folder = str(assets)
    monkeypatch.setattr("scripts.export_preview.create_preview_app", lambda _config: app)
    output = tmp_path / "_site"
    export_preview(output, "/Recall-Trace")
    assert (output / "static/good.css").is_file()
    assert [path.name for path in (output / "static").iterdir()] == ["good.css"]
