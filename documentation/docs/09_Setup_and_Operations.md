# Setup deployment and operations contract

## Repository and dependency setup

This is the setup contract for the implementation phase. The companion pack contains specifications and a dependency proposal; it does not contain the application or runnable Flask commands yet. When bootstrap is complete, replace this contract in the application README with commands verified from a clean checkout.

Create a Python 3.13 virtual environment. On Linux/macOS use python3 -m venv .venv and activate .venv/bin/activate. On Windows use py -3.13 -m venv .venv and activate .venv/Scripts/Activate.ps1 in PowerShell. Resolve the dependency proposal in an isolated environment, test it, and commit exact production and development dependency versions with reproducible hashes where supported.

The planned local service set is PostgreSQL shared Redis a private development evidence volume and an email sink. Docker Compose is the preferred repeatable development option; a documented direct Python option remains available. Secrets are generated locally and never committed. Use fictional seed data and reserved .test email addresses. No default administrator password is shipped; the bootstrap administrator is created through a one-time local command.

The Linux image must include libmagic for content inspection. Production evidence scanning needs a configured malware scanner adapter and endpoint; ClamAV is the initial integration candidate. SCAN_MODE and SCANNER_ENDPOINT select it. Scanner outage leaves evidence quarantined. The direct Windows development guide must document the corresponding native file-inspection dependency or use the container path.

## Planned application commands

After the application package and service files exist, the README must verify: pip install -r requirements.txt; flask --app wsgi:app db upgrade; flask --app wsgi:app seed-demo; flask --app wsgi:app create-owner; flask --app wsgi:app run --debug for local development; python -m pytest for the appropriate suites; and a Celery worker invocation for app.jobs.celery_app. Production uses Gunicorn wsgi:app with explicit workers timeouts and graceful shutdown behind HTTPS. These command names are an implementation contract, not commands validated in this documentation delivery.

## Environment variables

APP_ENV selects development testing or production. SECRET_KEY is a generated signing/CSRF secret. DATABASE_URL uses the configured PostgreSQL driver. SESSION_REDIS_URL RATELIMIT_STORAGE_URI and CELERY_BROKER_URL select authenticated shared services. Their separate logical Redis databases are a local convenience rather than a security boundary. MFA_ENCRYPTION_KEY is supplied through a secret manager or protected deployment environment. ALLOWED_HOSTS and TRUSTED_PROXY_HOPS configure the known ingress. STORAGE_BACKEND and its private bucket/credentials configure evidence storage. MAIL_MODE and mail credentials select the local sink or approved external service. LOG_LEVEL controls redacted logs. No environment value is printed by a failure page.

Production startup rejects missing or placeholder secrets debug mode SQLite process-local sessions/rate limits publicly readable evidence and incomplete required endpoints. Development relaxations require explicit configuration; production never inherits a development fallback key. Keep database broker and storage services private to the application network. Apply least privilege credentials and do not expose development email or database consoles publicly.

## Deploy and recover

Build a non-root Linux image from the reviewed source commit and lock file. Validate configuration before changing live state. Back up the database and evidence manifest before reviewed migrations, apply migrations once through the deployment job, start web/workers, verify readiness and perform smoke tests. Liveness exposes only process state; readiness verifies required services without revealing credentials or company data. A rollback plan considers database compatibility and may require a forward fix rather than destructive downgrade.

Back up PostgreSQL evidence objects and encryption-key recovery material through separate protected channels. The initial recovery planning targets are a 24-hour RPO and 4-hour RTO, subject to a measured restore exercise. Test restoration to a fresh environment using inventory counts journal reconciliation trace fixtures and file checksums. Record achieved timings and any missing objects. A database dump alone does not restore missing evidence files or keys.

## Monitoring and retention

Monitor error rates request latency queue age retry/ambiguous deliveries trace failures stale approvals active hold dispatch attempts and stock reconciliation differences. Alert the designated operator with redacted identifiers. Configure retention by data category and approved company policy; do not invent legal retention periods. Expire temporary exports and tokens and remove abandoned quarantined files through scoped maintenance jobs. Retain posted operational history until an authorized retention procedure permits disposition.

## Cost and external services

The classroom demonstration can use local containers a local email sink and synthetic records without a paid AI API. Hosting email storage monitoring and backup costs depend on the selected provider and workload; no price estimate is asserted here. Choose providers after the deployment requirements and budget are known.
