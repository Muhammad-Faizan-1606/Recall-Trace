"""Exercise the running M1 UI in Chromium; only synthetic temporary catalog data."""

import argparse
import getpass
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--password-file", type=Path)
parser.add_argument("--chromium", default="/usr/bin/chromium")
args = parser.parse_args()
origin = urlsplit(args.base_url)
if (
    origin.scheme not in {"http", "https"}
    or not origin.hostname
    or origin.username
    or origin.password
):
    parser.error("Use an HTTP(S) test-server address without embedded credentials.")
password = (
    args.password_file.read_text().strip()
    if args.password_file
    else getpass.getpass("Demo password: ")
)
code = "BROWSER-" + secrets.token_hex(4)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    assert context.request.get(args.base_url + "/health/ready").json() == {"status": "ready"}
    page.goto(args.base_url + "/login")
    page.get_by_label("Email", exact=True).fill("catalog-editor@aurora.test")
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="Your companies")).to_be_visible()
    page.get_by_role("article").filter(has_text="Aurora Lamps").get_by_role(
        "link", name="Open catalog"
    ).click()
    expect(page.get_by_role("heading", name="Items", exact=True)).to_be_visible()
    for section in ["Variants", "Units", "Items"]:
        page.get_by_role("navigation", name="Catalog", exact=True).get_by_role(
            "link", name=section, exact=True
        ).click()
        expect(page.get_by_role("heading", name=section, exact=True)).to_be_visible()
    page.get_by_role("link", name="New record").click()
    page.get_by_label("Code", exact=True).fill(code)
    page.get_by_label("Name", exact=True).fill("Synthetic browser item")
    page.get_by_label("Kind", exact=True).select_option("component")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("heading", name="Synthetic browser item")).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Record saved.")
    detail_url = page.url
    page.reload()
    expect(page.get_by_role("heading", name="Synthetic browser item")).to_be_visible()
    page.get_by_role("link", name="Edit", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Updated browser item")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("heading", name="Updated browser item")).to_be_visible()
    # Concurrent authenticated requests exercise the registry across WSGI workers.
    from concurrent.futures import ThreadPoolExecutor

    detail_origin = urlsplit(detail_url)
    if (detail_origin.scheme, detail_origin.hostname, detail_origin.port) != (
        origin.scheme,
        origin.hostname,
        origin.port,
    ):
        raise RuntimeError("Browser left the selected test-server origin.")
    cookie = "; ".join(f"{c['name']}={c['value']}" for c in context.cookies())

    def fetch(_):
        # Never forward an authenticated test cookie through an external redirect.
        with requests.get(
            detail_url, headers={"Cookie": cookie}, timeout=10, allow_redirects=False
        ) as response:
            return response.status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(fetch, range(8))) == [200] * 8
    page.get_by_role("button", name="Delete unused / archive referenced", exact=True).click()
    expect(page.get_by_role("heading", name="Items", exact=True)).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Unused record deleted.")
    expect(page.get_by_role("cell", name=code, exact=True)).to_have_count(0)
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    assert not errors, errors
    browser.close()
print(
    "PASS: readiness, narrow-screen sign-in, three catalog lists, item CRUD, refresh, concurrent authenticated requests, signout; no browser JavaScript errors."
)
