"""Export only the fictional read-only UI and public assets for static hosting."""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.preview import PAGES, create_preview_app

CANONICAL_PATHS = (
    "/",
    "/investigations/c10",
    "/stock",
    "/catalog",
    "/notices",
    "/evidence",
    "/access",
    "/settings",
)
STATIC_SUFFIXES = {
    ".css",
    ".js",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".txt",
}
DEFAULT_HOST = "muhammad-faizan-1606.github.io"


def validated_base_path(value):
    if value in {"", "/"}:
        return ""
    if not isinstance(value, str) or not value.startswith("/") or "\\" in value:
        raise ValueError(
            "The base path must be an absolute URL path, not a URL or filesystem path."
        )
    if value.endswith("/"):
        value = value[:-1]
    if any(
        not re.fullmatch(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*", part)
        for part in value[1:].split("/")
    ):
        raise ValueError("The base path contains an empty, unsafe or encoded path segment.")
    return value


def export_preview(output, base_path, *, host=DEFAULT_HOST):
    """Render a standalone artifact without loading business data or credentials."""
    base_path = validated_base_path(base_path)
    output = Path(output)
    if any(parent.is_symlink() for parent in output.absolute().parents):
        raise ValueError("The output path must not traverse a symlink.")
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise ValueError("The output must be a regular directory, not a symlink or file.")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite a nonempty output directory.")
    app = create_preview_app({"ALLOWED_HOSTS": host, "TRUSTED_PROXY_HOPS": 0})
    source = Path(app.static_folder)
    if source.is_symlink():
        raise ValueError("The static asset directory must not be a symlink.")
    source = source.resolve(strict=True)
    destination = output.resolve()
    if destination.is_relative_to(Path(app.root_path).resolve()):
        raise ValueError("Export outside the application source directory.")
    assets = []
    for asset in source.rglob("*"):
        if asset.is_symlink() or not asset.resolve().is_relative_to(source):
            raise ValueError("Static asset symlinks are not allowed in the public artifact.")
        if asset.is_file() and (
            asset.suffix.lower() in STATIC_SUFFIXES or asset.name == "BOOTSTRAP-LICENSE"
        ):
            assets.append((asset, asset.relative_to(source)))

    client = app.test_client()
    documents = {}

    def render(path, expected=200):
        response = client.get(
            path,
            base_url="https://" + host,
            environ_overrides={"SCRIPT_NAME": base_path},
        )
        if response.status_code != expected:
            raise ValueError("Preview rendering did not return its expected status.")
        return response.data

    paths = CANONICAL_PATHS + tuple("/preview/" + page for page in PAGES)
    for path in paths:
        documents[Path(path.lstrip("/")) / "index.html"] = render(path)
    for name in ("live", "ready"):
        payload = render("/health/" + name)
        documents[Path("health") / name / "index.html"] = payload
        documents[Path("health") / name / "index.json"] = payload
    for filename in ("robots.txt", "favicon.ico"):
        documents[Path(filename)] = render("/" + filename)
    # An SVG alias can be preferred by the preview's head without removing its
    # existing favicon route. Preserve it when the factory provides it.
    if any(rule.rule == "/favicon.svg" for rule in app.url_map.iter_rules()):
        documents[Path("favicon.svg")] = render("/favicon.svg")
    documents[Path("404.html")] = render("/__outside_preview__", expected=404)
    documents[Path(".nojekyll")] = b""

    output.mkdir(parents=True, exist_ok=True)
    for relative, data in documents.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for asset, relative in assets:
        target = output / "static" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(asset, target)
    return {"html_pages": len(paths), "static_assets": len(assets), "base_path": base_path}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-path", default="")
    parser.add_argument("--host", default=DEFAULT_HOST)
    args = parser.parse_args(argv)
    try:
        report = export_preview(args.output, args.base_path, host=args.host)
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
