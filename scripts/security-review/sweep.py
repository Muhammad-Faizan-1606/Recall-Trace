"""Authorization sweep against the LOCAL demo database only (never production).

1. Crawl every reachable page as the demo owner (member of both victim companies), keeping a
   few real URLs and forms per route pattern.
2. Replay as: (a) nobody signed in, (b) the outsider company's owner on the victim's URL,
   (c) the outsider on their own company URL carrying the victim's record IDs.
3. POST every form the same way with a valid CSRF token, and fingerprint the victim companies'
   rows before and after: any change means the outsider wrote into another company.
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

from sqlalchemy import text  # noqa: E402

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
PUBLIC = (
    "/login",
    "/health/",
    "/invitations/accept",
    "/account/reset",
    "/account/verify",
    "/static/",
)
PER_PATTERN = 2


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
        elif (
            self.form is not None
            and tag in ("input", "select", "textarea", "button")
            and a.get("name")
        ):
            if a.get("type") in ("checkbox", "radio") and "checked" not in a:
                return
            self.form["fields"].setdefault(a["name"], a.get("value") or "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.form = None


def pattern(path):
    return re.sub(UUID, "{id}", path.split("?")[0])


def login(client, email, password):
    page = client.get("/login")
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={"email": email, "password": password, "csrf_token": token})
    assert r.status_code == 303, (email, r.status_code)


def csrf_of(client, url):
    page = client.get(url)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.text) or re.search(
        r'data-csrf="([^"]+)"', page.text
    )
    return m.group(1) if m else None


def fingerprint(org_ids):
    """Per table: row count, sum of versions and latest update, for the victim companies."""
    out = {}
    tables = (
        db.session.execute(
            text(
                "SELECT table_name FROM information_schema.columns WHERE column_name='organization_id' "
                "AND table_schema='public'"
            )
        )
        .scalars()
        .all()
    )
    for t in tables:
        cols = set(
            db.session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
                {"t": t},
            ).scalars()
        )
        parts = ["count(*)"]
        if "version" in cols:
            parts.append("coalesce(sum(version),0)")
        if "updated_at" in cols:
            parts.append("max(updated_at)::text")
        row = db.session.execute(
            text(f"SELECT {', '.join(parts)} FROM {t} WHERE organization_id = ANY(:ids)"),
            {"ids": list(org_ids)},
        ).one()
        out[t] = tuple(str(v) for v in row)
    db.session.rollback()
    return out


def main():
    app = create_app()
    app.config["RATELIMIT_ENABLED"] = False
    from app.extensions import limiter

    limiter.enabled = False
    owner, outsider, anon = app.test_client(), app.test_client(), app.test_client()
    with app.app_context():
        orgs = dict(db.session.execute(text("SELECT slug, id::text FROM organizations")).all())
    victims = {orgs["video-demo"], orgs[[s for s in orgs if s.startswith("lahore")][0]]}
    own = orgs["outsider-demo"]
    login(owner, "owner@video-demo.test", os.environ["DEMO_OWNER_PASSWORD"])
    login(outsider, "owner@outsider-demo.test", os.environ["OUTSIDER_PASSWORD"])

    # ---------- crawl ----------
    seen, kept, forms = set(), collections.defaultdict(list), {}
    queue = ["/"] + [
        f"/companies/{v}/{p}"
        for v in victims
        for p in ("overview", "home", "factory/map", "factory/planning")
    ]
    while queue:
        url = queue.pop(0)
        if url in seen or "/logout" in url:
            continue
        seen.add(url)
        pat = pattern(url)
        if len(kept[pat]) >= PER_PATTERN:
            continue
        r = owner.get(url)
        if r.status_code != 200 or "text/html" not in r.content_type:
            if r.status_code == 200:
                kept[pat].append(url)
            continue
        kept[pat].append(url)
        p = Page()
        p.feed(r.text)
        for href in p.links:
            full = urljoin(url, href)
            s = urlsplit(full)
            if s.netloc or not s.path.startswith("/") or s.path.startswith("/static"):
                continue
            target = s.path + (("?" + s.query) if s.query and "page=" not in s.query else "")
            if target not in seen and len(kept[pattern(target)]) < PER_PATTERN:
                queue.append(target)
        for f in p.forms:
            if f["method"] != "post":
                continue
            action = urlsplit(urljoin(url, f["action"] or url)).path
            forms.setdefault(pattern(action), (action, f["fields"], url))
    rules = {
        re.sub(r"<[^>]+>", "{id}", r.rule)
        for r in app.url_map.iter_rules()
        if "static" not in r.rule
    }

    findings = []
    # ---------- GET replay ----------
    for urls in kept.values():
        for url in urls:
            if any(url.startswith(p) for p in PUBLIC):
                continue
            r = anon.get(url)
            if r.status_code == 200:
                findings.append(("anon-read", url, r.status_code))
            if not url.startswith("/companies/"):
                continue
            r = outsider.get(url)
            if r.status_code < 300:
                findings.append(("cross-company-read", url, r.status_code))
            company = url.split("/")[2]
            swapped = url.replace(company, own, 1)
            if re.search(UUID, swapped.replace(own, "", 1)):
                r = outsider.get(swapped)
                if r.status_code < 300:
                    findings.append(("foreign-id-read", swapped, r.status_code))

    # ---------- POST replay ----------
    with app.app_context():
        before = fingerprint(victims)
    token_own = csrf_of(outsider, f"/companies/{own}/overview")
    posted = 0
    for action, fields, _source in forms.values():
        if "/logout" in action or not action.startswith("/companies/"):
            continue
        company = action.split("/")[2]
        data = {k: v for k, v in fields.items() if k != "csrf_token"}
        for target in (action, action.replace(company, own, 1)):
            r = outsider.post(
                target, data={**data, "csrf_token": token_own}, headers={"X-CSRFToken": token_own}
            )
            posted += 1
            if r.status_code < 300 or (
                r.status_code in (302, 303) and "/login" not in r.headers.get("Location", "")
            ):
                findings.append(("cross-company-post-accepted?", target, r.status_code))
            r = anon.post(target, data=data)
            if r.status_code < 300:
                findings.append(("anon-post", target, r.status_code))
    # JSON endpoints the pages call from scripts.
    with app.app_context():
        bundle = db.session.execute(
            text("SELECT id::text, version FROM cut_bundles WHERE status='cut' LIMIT 1")
        ).one()
        order = db.session.execute(
            text(
                "SELECT id::text, version FROM production_orders WHERE status IN ('planned','draft') LIMIT 1"
            )
        ).one()
        lahore = db.session.execute(
            text("SELECT organization_id::text FROM cut_bundles LIMIT 1")
        ).scalar()
    for c in (lahore, own):
        for path, body in (
            (
                f"/companies/{c}/factory/map/bundles/{bundle[0]}",
                {"step": "issue", "version": bundle[1]},
            ),
            (
                f"/companies/{c}/factory/planning/orders/{order[0]}/change",
                {"priority": 1, "lines": 1, "version": order[1]},
            ),
        ):
            r = outsider.post(path, json=body, headers={"X-CSRFToken": token_own})
            posted += 1
            if r.status_code < 300:
                findings.append(("json-post-accepted", path, r.status_code))
        r = outsider.get(
            f"/companies/{c}/factory/planning/orders/{order[0]}/preview.json?priority=1"
        )
        if r.status_code < 300:
            findings.append(("json-read", f"preview.json in {c}", r.status_code))
    with app.app_context():
        after = fingerprint(victims)
    changed = {t: (before[t], after[t]) for t in before if before[t] != after[t]}

    covered = {p for p in kept} | set(forms)
    norm = lambda p: re.sub(r"/companies/\{id\}", "/companies/{id}", p)  # noqa: E731
    missing = sorted(
        r
        for r in rules
        if not any(
            norm(c) == r or re.fullmatch(re.escape(r).replace(r"\{id\}", "[^/]+"), c)
            for c in covered
        )
    )
    print(
        json.dumps(
            {
                "pages_crawled": len(seen),
                "route_patterns_reached": len(covered),
                "routes_total": len(rules),
                "posts_replayed": posted,
                "victim_data_changed": changed,
                "findings": findings,
                "routes_not_reached": missing,
            },
            indent=1,
            default=str,
        )
    )


main()
