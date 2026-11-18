"""Hostile-input sweep against the LOCAL demo database only (never production).

As the legitimate owner, submit every form with one field replaced by a hostile value, then
re-crawl the pages and look for any payload rendered unescaped. Findings: HTTP 500s (unhandled
input), and stored or reflected markup/script in HTML.
"""

import collections
import json
import os
import re
import sys
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

assert "recalltrace_video" in os.environ["DATABASE_URL"], "demo database only"
sys.path.insert(0, os.getcwd())

from app import create_app  # noqa: E402
from app.extensions import limiter  # noqa: E402

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
MARK = "zq7x"
PAYLOADS = [
    f"<script>{MARK}()</script>",
    f'"><img src=x onerror={MARK}()>',
    f"{{{{7*7}}}}{MARK}{{% raw %}}",
    "' OR '1'='1' --",
    "1; DROP TABLE users;--",
    "-1",
    "1e309",
    "NaN",
    "Infinity",
    "0x41",
    "9" * 40,
    "A" * 20000,
    "\u0000nul",
    "../../../../etc/passwd",
    "javascript:alert(1)",
]
SKIP_FIELDS = {"csrf_token", "idempotency_key"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.forms, self.form = [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "form":
            self.form = {
                "action": a.get("action") or "",
                "method": (a.get("method") or "get").lower(),
                "fields": {},
            }
            self.forms.append(self.form)
        elif self.form is not None and tag in ("input", "select", "textarea") and a.get("name"):
            if a.get("type") in ("checkbox", "radio") and "checked" not in a:
                return
            if a.get("type") == "file":
                return
            self.form["fields"].setdefault(a["name"], a.get("value") or "")
        elif self.form is not None and tag == "option" and "selected" in a:
            pass

    def handle_endtag(self, tag):
        if tag == "form":
            self.form = None


def pattern(path):
    return re.sub(UUID, "{id}", path.split("?")[0])


def main():
    app = create_app()
    limiter.enabled = False
    c = app.test_client()
    page = c.get("/login")
    tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text).group(1)
    c.post(
        "/login",
        data={
            "email": "owner@video-demo.test",
            "password": os.environ["DEMO_OWNER_PASSWORD"],
            "csrf_token": tok,
        },
    )

    def crawl(limit=2):
        seen, kept, forms = set(), collections.defaultdict(list), {}
        queue = ["/"]
        while queue:
            url = queue.pop(0)
            if url in seen or "/logout" in url:
                continue
            seen.add(url)
            if len(kept[pattern(url)]) >= limit:
                continue
            r = c.get(url)
            if r.status_code != 200 or "text/html" not in r.content_type:
                continue
            kept[pattern(url)].append((url, r.text))
            p = Page()
            p.feed(r.text)
            for href in p.links:
                s = urlsplit(urljoin(url, href))
                if s.netloc or s.path.startswith("/static"):
                    continue
                t = s.path + (("?" + s.query) if s.query and "page=" not in s.query else "")
                if t not in seen and len(kept[pattern(t)]) < limit:
                    queue.append(t)
            for f in p.forms:
                if f["method"] == "post" and "/logout" not in f["action"]:
                    action = urlsplit(urljoin(url, f["action"] or url)).path
                    forms.setdefault(pattern(action), (action, f["fields"], url))
        return kept, forms

    _, forms = crawl()
    errors, posted = [], 0
    for pat, (action, fields, source) in sorted(forms.items()):
        # Never sign out, delete company access, or revoke our own sessions mid-sweep.
        if any(
            k in action for k in ("/sessions/", "/security/disable", "/access/members", "/team/")
        ):
            continue
        targets = [k for k in fields if k not in SKIP_FIELDS] or [None]
        for field in targets:
            for payload in PAYLOADS:
                tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', c.get(source).text)
                data = dict(fields)
                if tok:
                    data["csrf_token"] = tok.group(1)
                if field:
                    data[field] = payload
                r = c.post(action, data=data)
                posted += 1
                if r.status_code >= 500:
                    errors.append((pat, field, payload[:30], r.status_code))
                if r.status_code < 400 and (
                    f"<script>{MARK}()</script>" in r.text
                    or f"<img src=x onerror={MARK}()>" in r.text
                ):
                    errors.append(("REFLECTED-UNESCAPED", pat, field, payload[:30]))
    kept, _ = crawl(limit=3)
    stored = []
    for pages in kept.values():
        for url, html in pages:
            # Only raw tags count: an escaped payload (&lt;img ... onerror=...&gt;) is safe text.
            if f"<script>{MARK}()</script>" in html or f"<img src=x onerror={MARK}()>" in html:
                stored.append(url)
            if f"49{MARK}" in html:
                stored.append("SSTI evaluated: " + url)
    print(
        json.dumps(
            {
                "forms": len(forms),
                "posts": posted,
                "server_errors": errors,
                "stored_unescaped": stored,
            },
            indent=1,
        )
    )


main()
