"""Exercise M2 development account flows against a running local app and private mailbox."""

import argparse
import getpass
import json
import re
import secrets
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:8000")
parser.add_argument("--owner-email", default="owner@aurora.test")
parser.add_argument("--password-file", type=Path)
parser.add_argument("--mail-dir", type=Path, default=Path("instance/account-mail"))
args = parser.parse_args()
password = (
    args.password_file.read_text().strip()
    if args.password_file
    else getpass.getpass("Owner password: ")
)
suffix = secrets.token_hex(4)
email = f"browser-{suffix}@aurora.test"
member_password = secrets.token_urlsafe(24)
new_password = secrets.token_urlsafe(24)


def code_for(recipient, subject):
    for path in sorted(
        args.mail_dir.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True
    ):
        message = json.loads(path.read_text())
        if message["recipient"] == recipient and subject in message["subject"]:
            return re.search(r"\n([A-Za-z0-9_-]{43})\n", message["body"]).group(1)
    raise AssertionError("Expected private development message was not delivered")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.base_url + "/login")
    page.get_by_label("Email", exact=True).fill(args.owner_email)
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("article").filter(has_text="Aurora Lamps").get_by_role(
        "link", name="Open catalog"
    ).click()
    page.get_by_role("link", name="Company access", exact=True).click()
    page.get_by_role("link", name="New role", exact=True).click()
    page.get_by_label("Code", exact=True).fill(f"browser-{suffix}")
    page.get_by_label("Name", exact=True).fill(f"Browser viewer {suffix}")
    page.get_by_label("Permissions", exact=True).select_option("catalog.read")
    page.get_by_role("button", name="Save role", exact=True).click()
    expect(page.get_by_role("heading", name="Company access")).to_be_visible()
    page.get_by_role("link", name="Invite member", exact=True).click()
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Role", exact=True).select_option(label=f"Browser viewer {suffix}")
    page.get_by_role("button", name="Send invitation", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Invitation saved and delivery confirmed")
    token = code_for(email, "company invitation")
    assert token not in page.content()
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.get_by_role("link", name="Accept an invitation", exact=True).click()
    page.get_by_label("Invitation code", exact=True).fill(token)
    page.get_by_label("Display name (new accounts)", exact=True).fill("Browser invited member")
    page.get_by_label("Password (new accounts)", exact=True).fill(member_password)
    page.get_by_role("button", name="Accept invitation", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Invitation accepted")
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(member_password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Open catalog").click()
    expect(page.get_by_role("heading", name="Items", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="New record")).to_have_count(0)
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.get_by_role("link", name="Forgot your password?", exact=True).click()
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_role("button", name="Request instructions").click()
    token = code_for(email, "password recovery")
    page.goto(args.base_url + "/account/reset")
    page.get_by_label("One-time code", exact=True).fill(token)
    page.get_by_label("New password", exact=True).fill(new_password)
    page.get_by_label("Confirm new password", exact=True).fill(new_password)
    page.get_by_role("button", name="Change password", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Password changed")
    page.get_by_label("Email", exact=True).fill(email)
    page.get_by_label("Password", exact=True).fill(new_password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("link", name="Your sessions", exact=True).click()
    expect(page.get_by_role("heading", name="Your sessions", exact=True)).to_be_visible()
    page.get_by_role("button", name="Revoke this session", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    before_mail = set(args.mail_dir.glob("*.json"))
    page.get_by_role("link", name="Verify your email", exact=True).click()
    page.get_by_label("Email", exact=True).fill(args.owner_email)
    page.get_by_role("button", name="Request instructions").click()
    if set(args.mail_dir.glob("*.json")) - before_mail:
        token = code_for(args.owner_email, "email verification")
        page.goto(args.base_url + "/account/verify")
        page.get_by_label("One-time code", exact=True).fill(token)
        page.get_by_role("button", name="Verify email", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("Email verified")
        verification_result = "email verification passed"
    else:
        verification_result = "verification consumption not rerun (owner already verified)"
    assert not errors, errors
    browser.close()
print(verification_result)
print(
    "PASS: narrow-screen role creation, invitation, limited member access, password recovery, session revocation and verification request. Synthetic membership and role retained for history."
)
