# Read-only frontend preview

The owner requested a public frontend demonstration while email, Redis and worker/scanner hosting are arranged. This preview displays fictional sample screens with the application's shared Jinja base and locally served styles. It does not connect to the real database, storage, authentication or external delivery services.

The overview, C10 investigation/SVG graph, stock/lots, catalog/partners, notices, evidence, company access and settings pages work without signing in. Each page identifies itself as a read-only demo; actions are disabled. No business or security records are created and no real communications are sent. The sample C10 scope keeps 150 lamps separate from the 50 unused switches and excludes unrelated C11/L3/S3.

## Run or deploy

With the project's runtime dependencies installed, start the independent factory:

```sh
RECALLTRACE_PREVIEW=read-only ALLOWED_HOSTS=localhost,127.0.0.1 TRUSTED_PROXY_HOPS=0 WEB_CONCURRENCY=1 .venv/bin/gunicorn --config gunicorn.conf.py 'app.preview:create_preview_app()'
```

For a public Render service use the separate `render.preview.yaml`: Docker runtime, explicitly free plan, one web worker, `/health/ready`, and the preview command override. Render supplies its exact external hostname; only that hostname is trusted. Set `RECALLTRACE_PREVIEW=read-only`, `WEB_CONCURRENCY=1` and `TRUSTED_PROXY_HOPS=1`. No production database, storage, email or signing/encryption credentials belong in this service. Free web hosting may sleep; this is a demonstration rather than an always-on business deployment.

The regular Docker command and `render.yaml` still start the complete application via `wsgi:app`. The preview flag does not bypass its production checks. Do not change the real application to development mode to deploy it publicly.

## Verification

```sh
.venv/bin/python -m pytest -q tests/test_preview.py -W error::DeprecationWarning --tb=short
.venv/bin/python scripts/preview_browser_smoke.py --base-url YOUR_REVIEWED_PREVIEW_ORIGIN
```

The isolated test module needs no database/Redis fixtures. It checks explicit opt-in, debug/test rejection, service independence, exact Host enforcement, security headers, GET-only screens, absent production endpoints and local assets. Chromium checks all eight screens at desktop and mobile widths, navigation, the trace graph, no horizontal page overflow, no active forms/actions and no browser/session errors. Screenshots remain under the ignored private instance directory.

The application's production tenant, stock, MFA, delivery, scanner and recovery workflows remain separately implemented and tested. A functioning preview is not evidence that those services are connected or production cleared. Follow PRODUCTION_LAUNCH.md for their remaining requirements.
