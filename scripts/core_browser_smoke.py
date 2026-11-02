"""Exercise the connected Core UI using only uniquely named fictional data.

Requires the C10 seed and an owner with Core grants. No real communications are sent.
The imported item/source job and private export remain as demonstration history.
"""

import argparse
import base64
import getpass
import re
import secrets
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--password-file", type=Path)
parser.add_argument("--email", default="owner@aurora.test")
parser.add_argument("--chromium", default="/usr/bin/chromium")
args = parser.parse_args()
password = (
    args.password_file.read_text().strip()
    if args.password_file
    else getpass.getpass("Owner password: ")
)
code = "CORE-" + secrets.token_hex(5)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
    context = browser.new_context(viewport={"width": 390, "height": 844}, accept_downloads=True)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    assert context.request.get(args.base_url + "/health/ready").json() == {"status": "ready"}
    page.goto(args.base_url + "/login")
    page.get_by_label("Email", exact=True).fill(args.email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="Your companies")).to_be_visible()
    page.get_by_role("article").filter(has_text="Aurora Lamps").get_by_role(
        "link", name="Open catalog"
    ).click()
    workspace = page.get_by_role("navigation", name="Workspace", exact=True)
    workspace.get_by_role("link", name="Master data", exact=True).click()
    page.get_by_role("link", name="Open partners", exact=True).click()
    page.get_by_role("link", name="New record", exact=True).click()
    page.get_by_label("Code", exact=True).fill(code)
    page.get_by_label("Name", exact=True).fill("Fictional browser customer")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_contain_text(code)
    page.get_by_role("link", name="Edit", exact=True).click()
    page.get_by_label("Name", exact=True).fill("Updated fictional browser customer")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_contain_text("Updated fictional")
    page.get_by_role("button", name="Delete unused / archive referenced", exact=True).click()
    expect(page.get_by_role("link", name=re.compile(code))).to_have_count(0)
    for name, heading in [
        ("Operations", "Operations"),
        ("Quality", "Quality and holds"),
        ("Investigations", "Recall investigations"),
    ]:
        page.get_by_role("navigation", name="Workspace", exact=True).get_by_role(
            "link", name=name, exact=True
        ).click()
        expect(page.get_by_role("heading", level=1)).to_have_text(heading)
    page.get_by_role("link", name="C10-INVESTIGATION", exact=True).click()
    page.get_by_role("link", name=re.compile("downstream$")).first.click()
    expect(page.get_by_role("heading", name="Downstream trace", exact=True)).to_be_visible()
    expect(page.get_by_role("img", name=re.compile("Recorded lot genealogy"))).to_be_visible()
    rows = page.get_by_role("row")
    lamp = rows.filter(has_text="C10-LAMP-01").first
    expect(lamp).to_contain_text("150.000000")
    expect(lamp).to_contain_text("110.000000")
    expect(lamp).to_contain_text("40.000000")
    expect(page.get_by_role("cell", name="L3", exact=True)).to_have_count(0)
    page.get_by_role("navigation", name="Workspace", exact=True).get_by_role(
        "link", name="Evidence & reports", exact=True
    ).click()
    page.get_by_label("UTF-8 item CSV (code,name,kind)", exact=True).set_input_files(
        {
            "name": code + ".csv",
            "mimeType": "text/csv",
            "buffer": f"code,name,kind\n{code},Fictional browser import,component\n".encode(),
        }
    )
    page.get_by_role("button", name="Validate and preview", exact=True).click()
    expect(page.get_by_role("heading", name="Catalog import preview", exact=True)).to_be_visible()
    expect(page.get_by_role("cell", name=code, exact=True)).to_be_visible()
    page.get_by_role("button", name="Commit all rows", exact=True).click()
    expect(page.get_by_text(re.compile("1 rows, committed"))).to_be_visible()
    page.get_by_role("link", name="Evidence and data tools", exact=True).click()
    with page.expect_download() as download:
        page.get_by_role("button", name="Create CSV export", exact=True).click()
    exported = Path(download.value.path()).read_text()
    assert code in exported
    # Missing scanner must fail closed; never invent a clean verdict.
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB9sAAAAASUVORK5CYII="
    )
    page.get_by_label("PDF, PNG or JPEG (up to 10 MiB)", exact=True).set_input_files(
        {
            "name": code + ".png",
            "mimeType": "image/png",
            "buffer": png,
        }
    )
    page.get_by_role("button", name="Upload privately", exact=True).click()
    expect(page.get_by_role("heading", name=code + ".png", exact=True)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="quarantined")).to_be_visible()
    expect(page.get_by_role("link", name="Download evidence", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Delete unused document", exact=True).click()
    page.get_by_role("link", name="Your notifications", exact=True).click()
    expect(page.get_by_role("heading", level=1)).to_have_text("Your notifications")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page).to_have_url(re.compile(r"/login$"))
    assert not errors, errors
    browser.close()
print(
    "PASS: narrow-screen master CRUD, operations/quality navigation, C10 trace graph/totals, CSV preview/commit/private export, quarantine, notifications and signout; no JavaScript errors. Synthetic import/export history retained."
)
