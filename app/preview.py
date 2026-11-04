"""Isolated, read-only public UI preview with fictional bundled data.

This factory never initializes application extensions, authenticates users,
opens a database, or registers business-action endpoints. The production
factory and its required services remain independent.
"""

import os
import re
from types import SimpleNamespace

from flask import Flask, Response, abort, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

PAGES = {
    "dashboard": (
        "Workspace overview",
        "An evidence-backed view of your operations.",
        "dashboard.html",
    ),
    "investigation": (
        "C10 · Switch contact investigation",
        "Follow recorded genealogy, review exposure and coordinate an independent response.",
        "investigation.html",
    ),
    "stock": (
        "Stock & lots",
        "Recorded quantities, locations and controlled movement.",
        "stock.html",
    ),
    "catalog": (
        "Catalog & partners",
        "The identities that connect every recorded event.",
        "catalog.html",
    ),
    "notices": (
        "Recall communications",
        "Recipient-specific notices, independent approval and honest delivery status.",
        "communications.html",
    ),
    "evidence": (
        "Evidence & reports",
        "Private documents, integrity checks and a complete evidence trail.",
        "communications.html",
    ),
    "access": (
        "Company access",
        "Explicit roles, independent review and scoped access.",
        "access.html",
    ),
    "settings": (
        "Account & workspace",
        "Security controls and deployment connections.",
        "settings.html",
    ),
}

NAVIGATION = (
    ("dashboard", "Overview", "01"),
    ("investigation", "Investigations", "02"),
    ("stock", "Stock & lots", "03"),
    ("catalog", "Catalog & partners", "04"),
    ("notices", "Notices", "05"),
    ("evidence", "Evidence & reports", "06"),
    ("access", "Company access", "07"),
    ("settings", "Account & workspace", "08"),
)


def _hosts(config):
    selected = (
        config.get("ALLOWED_HOSTS")
        or os.getenv("ALLOWED_HOSTS")
        or os.getenv("RENDER_EXTERNAL_HOSTNAME")
    )
    hosts = selected.split(",") if isinstance(selected, str) else selected
    if not isinstance(hosts, (list, tuple)) or not hosts:
        raise RuntimeError("Configure exact preview ALLOWED_HOSTS or Render's external hostname.")
    result = []
    for host in hosts:
        if not isinstance(host, str):
            raise RuntimeError("Preview hosts must be exact hostnames.")
        host = host.strip()
        if not host or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise RuntimeError(
                "Preview hosts must be exact hostnames without schemes or wildcards."
            )
        if ".." in host:
            raise RuntimeError("Preview hosts must be exact hostnames.")
        result.append(host)
    return result


def create_preview_app(config=None):
    """Create only the explicitly selected public, fictional read-only preview."""
    if os.getenv("RECALLTRACE_PREVIEW") != "read-only":
        raise RuntimeError("The isolated preview requires RECALLTRACE_PREVIEW=read-only.")
    selected = dict(config or {})
    if (
        selected.get("DEBUG")
        or selected.get("TESTING")
        or os.getenv("FLASK_DEBUG", "").lower() not in {"", "0", "false"}
    ):
        raise RuntimeError("Debug and testing modes are unavailable for the public preview.")
    try:
        hops = int(selected.get("TRUSTED_PROXY_HOPS", os.getenv("TRUSTED_PROXY_HOPS", "0")))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Preview TRUSTED_PROXY_HOPS must be 0 or 1.") from exc
    if hops not in (0, 1):
        raise RuntimeError("Preview TRUSTED_PROXY_HOPS must be 0 or 1.")

    app = Flask(__name__)
    app.config.update(
        DEBUG=False,
        TESTING=False,
        APP_ENV="preview",
        TRUSTED_HOSTS=_hosts(selected),
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1024,
    )
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=0)

    @app.context_processor
    def preview_context():
        # The shared base only uses this to decide whether to show authenticated
        # account controls. A preview viewer is never a real signed-in user.
        return {"current_user": SimpleNamespace(is_authenticated=False)}

    def page_response(page):
        if page not in PAGES:
            abort(404)
        title, subtitle, template = PAGES[page]
        return render_template(
            "preview/" + template,
            current_page=page,
            page_title=title,
            page_subtitle=subtitle,
            navigation=NAVIGATION,
        )

    # This shared-base brand link resolves locally; no production blueprint is
    # registered and its business routes remain absent.
    app.add_url_rule(
        "/",
        endpoint="catalog.companies",
        view_func=lambda: page_response("dashboard"),
        methods=["GET"],
    )

    @app.get("/preview/<page>")
    def preview_page(page):
        return page_response(page)

    canonical = {
        "/investigations/c10": "investigation",
        "/stock": "stock",
        "/catalog": "catalog",
        "/notices": "notices",
        "/evidence": "evidence",
        "/access": "access",
        "/settings": "settings",
    }
    for index, (path, page) in enumerate(canonical.items()):
        app.add_url_rule(
            path,
            endpoint=f"preview_canonical_{index}",
            view_func=lambda selected_page=page: page_response(selected_page),
            methods=["GET"],
        )

    @app.get("/health/live")
    def preview_live():
        return {"status": "alive", "mode": "read-only-preview"}

    @app.get("/health/ready")
    def preview_ready():
        # This confirms bundled frontend readiness, never production services.
        return {"status": "ready", "mode": "read-only-preview"}

    @app.get("/robots.txt")
    def preview_robots():
        return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")

    @app.get("/favicon.ico")
    def preview_favicon():
        return Response(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<rect width="64" height="64" rx="16" fill="#172d3b"/>'
            '<path d="M18 46V18h15c17 0 17 21 2 22l12 6H34L24 34v12zm6-19h9'
            'c6 0 6 6 0 6h-9z" fill="#d9f4c5"/></svg>',
            mimetype="image/svg+xml",
        )

    @app.errorhandler(404)
    def preview_missing(_error):
        return (
            render_template(
                "preview/error.html",
                current_page="",
                page_title="This page is outside the preview",
                page_subtitle="Explore the sample workspace using the navigation.",
                navigation=NAVIGATION,
            ),
            404,
        )

    @app.after_request
    def preview_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        response.headers["X-RecallTrace-Mode"] = "read-only-preview"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    return app
