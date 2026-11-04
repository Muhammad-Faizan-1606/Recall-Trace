"""Browse the public sample UI without credentials or production-side effects."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", required=True)
parser.add_argument("--chromium", default="/usr/bin/chromium")
parser.add_argument("--screenshots-dir", type=Path, default=Path("instance/preview/screenshots"))
args = parser.parse_args()
base = args.base_url.rstrip("/")
parsed = urlsplit(base)
if (
    parsed.scheme not in {"http", "https"}
    or not parsed.hostname
    or parsed.username
    or parsed.password
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
):
    parser.error("Select the reviewed preview's HTTP(S) origin without credentials or a path.")
origin = (parsed.scheme, parsed.netloc)
args.screenshots_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
pages = (
    "/",
    "/investigations/c10",
    "/stock",
    "/catalog",
    "/notices",
    "/evidence",
    "/access",
    "/settings",
)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 1440, "height": 1000})

    def same_origin_only(route):
        destination = urlsplit(route.request.url)
        if (destination.scheme, destination.netloc) == origin:
            route.continue_()
        else:
            route.abort()

    context.route("**/*", same_origin_only)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    health = context.request.get(base + "/health/ready", max_redirects=0)
    assert health.status == 200
    assert health.json() == {"status": "ready", "mode": "read-only-preview"}
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
        for path in pages:
            response = page.goto(base + path, wait_until="networkidle")
            assert response is not None and response.status == 200
            expect(
                page.get_by_text("Demo with sample data. Changes are disabled.", exact=True)
            ).to_be_visible()
            expect(page.locator("h1")).to_be_visible()
            assert page.locator("form").count() == 0
            assert page.locator("button:not([disabled])").count() == 0
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            if path in {"/", "/investigations/c10"}:
                name = "overview" if path == "/" else "c10-investigation"
                page.screenshot(
                    path=str(args.screenshots_dir / f"{name}-{width}.png"), full_page=True
                )
        page.goto(base + "/", wait_until="networkidle")
        page.get_by_role("navigation", name="Preview workspace", exact=True).get_by_role(
            "link", name="Investigations", exact=False
        ).click()
        expect(page.locator("h1")).to_contain_text("C10")
        expect(page.locator("svg[role='img']")).to_be_visible()
    assert context.request.post(base + "/catalog", max_redirects=0).status == 405
    assert not errors, errors
    assert context.cookies() == []
    browser.close()
print(
    json.dumps(
        {"preview_browser": "passed", "pages": len(pages), "widths": [1440, 390], "read_only": True}
    )
)
