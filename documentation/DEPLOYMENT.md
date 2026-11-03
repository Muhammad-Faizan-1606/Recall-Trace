# RecallTrace deployment and recovery

The final application scope is the 72-model Core design. This deployment guide describes an installation path, not a claim that every business workflow or a public deployment has passed validation. See STATUS.md for checks actually executed.

Use [the production launch record](PRODUCTION_LAUNCH.md) for current account-access requirements and deployment gates. The owner has Render, Supabase and Resend accounts; provider credentials and live resources are not connected to this environment yet. Use [database access provisioning](DATABASE_ACCESS.md) to prepare and verify the restricted application role before switching web/worker credentials.

## University demonstration and free services

Use the existing local Docker Compose PostgreSQL/Redis stack for an offline university demonstration with fictional `.test` identities. `bash scripts/setup.sh` installs the hash-locked Python environment and applies migrations. Run the application and browser checks as described in README.md. Keep generated secrets private and preserve the ignored `instance/` directory when appropriate. Do not create an extra Git worktree for a cloud task: the task already has an isolated checkout.

A possible public deployment uses Render for the Flask/Gunicorn web service, Supabase for PostgreSQL and a private storage bucket, an authenticated TLS Redis provider, Resend for transactional mail, and an authorized scanner endpoint. The included `render.yaml` declares the web service and secret requirements. It does not create or authenticate these external accounts, create Supabase storage/database resources, or configure a scanner. Check each provider's current available regions, free eligibility, quotas, database/connection limits, acceptable use and expiry conditions before activation.

Free plans may sleep or pause, may lack persistent local disk and scheduled/background workers, and may not include backups or an uptime commitment. A database and private object storage must survive web service replacement. Never use Render's ephemeral container filesystem for persistent evidence. A 72-model implementation and passing tests do not change these hosting limits. A zero-budget university deployment cannot be represented as a continuously available business service.

Vercel is not the initial deployment target: this application uses a conventional WSGI server, persistent PostgreSQL/Redis state and durable job processing. Avoid splitting the Flask/Jinja application into a separate frontend merely to fit a host.

## Create the external resources

1. Create the Supabase project in a selected region. Create a database and a dedicated runtime role. Reserve the project owner or a separate migration role for reviewed migrations. Use the provider's direct connection or session pooler compatible with psycopg; do not assume a transaction pooler supports prepared statements/session semantics. Set connection pool limits within the provider quota.
2. Download the provider's root certificate through the dashboard's authenticated, verified HTTPS route. Install it as a read-only public configuration file in the runtime. Set `DATABASE_URL` with `postgresql+psycopg://`, an encoded password, and `sslmode=verify-full&sslrootcert=/absolute/path/to/provider-root.crt`. Keep hostname verification enabled. The system CA bundle may be used only if it verifies the actual provider certificate chain. Test the resulting live connection before deploying.
3. Create a **private** bucket named `recalltrace-private`. Disable public access. Set `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET` and `SUPABASE_SERVICE_KEY` in secure server settings. The service key stays server-side; it never belongs in HTML or JavaScript. The application authorizes each streamed download before using storage credentials.
4. Provision authenticated Redis over TLS. Configure `SESSION_REDIS_URL` and `RATELIMIT_STORAGE_URI` explicitly using `rediss://` and the query options `?ssl_check_hostname=true&ssl_cert_reqs=required` on each URL. Do not use process-memory rate counters in a multi-worker deployment, or disable certificate verification. Separate logical databases are a naming convenience, not a security boundary.
5. Configure Resend and a sender the provider authorizes. Set `MAIL_MODE=resend`, `MAIL_API_KEY` and `MAIL_FROM`. Account access codes and recall notices must never be printed in access logs. Provider acceptance is not proof of physical recovery. No real messages should be sent while validating the fictional demo.
6. Configure `SCANNER_ENDPOINT` as an authorized HTTPS scanner accepting bounded file bytes and returning `{"status":"clean"}` or `{"status":"infected"}`; alternatively use a private ClamAV service selected by `CLAMAV_HOST`/`CLAMAV_PORT`. A timeout or unavailable scanner leaves files quarantined. A scanner that returns `clean` unconditionally is not a production scanner.
7. Configure `SECRET_KEY` as a new cryptographically random secret and `MFA_ENCRYPTION_KEY` as a Fernet key through secure settings. `MFA_KEY_VERSION` defaults to `v1`; preserve this key and its version separately from database backups. The account-request queue derives separate encryption/HMAC keys from this key; web and worker must share the same key/version. Losing it makes enrolled factors and pending account requests unrecoverable. Changing the key without a supported re-encryption/rotation procedure is unsafe. The version must contain 1–20 ASCII letters, digits, dots, underscores or hyphens.

Do not send service passwords, raw keys or database URLs in chat. Enter them in secure provider/environment settings. Cloud environment proxy-backed secret placeholders may be suitable only for their configured HTTPS destinations; a PostgreSQL or Redis URL requires the provider/runtime's supported direct credential mechanism. Never assume a proxy-injected HTTPS value is a raw local database password.

## Build and configure the web service

Build from a reviewed source commit and current lockfiles:

```sh
docker build -t recalltrace:reviewed .
```

The default web image uses Python 3.13 on Alpine, installs only hash-verified binary wheels, and runs as UID/GID 10001. It contains neither PostgreSQL administrative clients nor Bash/libmagic; file signatures are checked in Python and accepted uploads still require the separately configured malware scanner. Build operator clients separately with `docker build --target database-tools -t recalltrace:database-tools .`. The reviewed builds use Python 3.13.18 / Alpine 3.24.3 and PostgreSQL clients 17.11. It excludes `.env`, private evidence, local account mail, passwords and test data from the build context. The base image is pinned to the registry manifest digest resolved during this task; refresh that digest deliberately when applying base image updates. Updates require rebuilding and rerunning checks.

In managed Codex cloud builds, retain the session proxy and CA trust. Read the cloud runtime Docker guidance before building. If the image's dependency-install step needs the session CA, pass the CA as a BuildKit secret and set the install tool's trust path for that step. This Dockerfile accepts `docker build --secret id=proxy_ca,src="$CODEX_PROXY_CERT" -t recalltrace:reviewed .`; the secret is used by pip only during installation. Do not disable TLS verification or copy a session CA into a release layer.

Required configuration includes:

| Setting | Purpose |
| --- | --- |
| `APP_ENV=production` | Enables strict validation; never publish a production deployment in development mode to bypass failures. |
| `ALLOWED_HOSTS` | Comma-separated exact public hostnames. Render's injected `RENDER_EXTERNAL_HOSTNAME` is used if this setting is absent. |
| `TRUSTED_PROXY_HOPS` | Explicit known ingress proxy count, normally 1 for a single platform proxy. Expose web traffic only through that ingress. |
| `PORT` | Platform listener port; defaults to 8000. |
| `WEB_CONCURRENCY` | Gunicorn worker count; start at 1 for a constrained demo and measure memory. |
| `DATABASE_URL` | Private PostgreSQL runtime connection with verified TLS remotely. |
| `SESSION_REDIS_URL`, `RATELIMIT_STORAGE_URI` | Shared authenticated TLS session/rate stores. |
| `STORAGE_BACKEND=supabase` | Persistent private evidence for ephemeral web hosts. |
| `MFA_ENCRYPTION_KEY`, `SECRET_KEY` | Securely supplied encryption/signing secrets. |
| `MAIL_MODE`, `MAIL_API_KEY`, `MAIL_FROM` | Explicit supported external account/notice delivery. |
| `SCANNER_ENDPOINT` or `CLAMAV_HOST` | Real evidence scanning endpoint. |

`configure_environment(app)` must run after explicit application configuration overrides and before extension initialization. It validates production configuration and sets Secure, HttpOnly, SameSite=Lax `__Host-recalltrace` cookies with Path `/` and no Domain. It trusts only the configured proxy count for client IP/protocol; it never trusts `X-Forwarded-Host`. Flask validates the actual Host against exact allowed names. SQLAlchemy pools use 3 persistent plus at most 2 overflow connections per worker by default; include workers and migration/worker clients when checking the provider's database limit.

Production startup rejects debug/test mode, SQL statement logging, weak/missing secrets, insecure remote database/Redis connections, wildcard hosts, unconfigured storage/scanner/mail and local account mail. Passing configuration validation does not prove those credentials or services work. `/health/ready` verifies the application's required live database/session/rate connections; verify storage, scanning, email and job processing separately with authorized synthetic test records.

## Deploy, migrate, and validate

1. Run tests, Ruff, dependency consistency/audit, clean-database installation and the business acceptance fixture. Record the reviewed commit, migration head, image digest and exact results.
2. Take a private database backup and independently preserve evidence objects/manifests and MFA key recovery material. Rehearse restoration before putting real operational data into the system.
3. In a one-off controlled deployment job, run `flask --app wsgi:app db upgrade` using the migration role. Do this **once**, not independently in every Gunicorn worker or every web startup. The Render blueprint intentionally has no automatic migration-at-web-start command. If a free plan has no deployment job/shell, run the migration from a trusted local/cloud operator environment with the same reviewed code, CA trust and securely injected migration credential.
4. Switch the web service back to the runtime role. It must not own tables, create/drop/alter schema, bypass tenant checks through ad hoc console tooling, or modify append-only audit/journal history. Grant only the table operations required by implemented workflows; PostgreSQL triggers also protect immutable history. Review grants after every migration. PostgreSQL row ownership and superuser access can bypass ordinary application assumptions; retain those credentials separately.
5. Start `gunicorn --config gunicorn.conf.py wsgi:app`. Verify HTTPS, host rejection, Secure session cookies, login/MFA, authorization, migration head, readiness, catalog/stock/trace/case workflows and scanner/mail adapters. Keep secret values and HTTP query strings out of logs.
6. Run `flask --app wsgi:app outbox-run --watch` in a separately supervised worker with the same database, encryption key/version and delivery settings. This worker is required for public password recovery and email verification: their HTTP requests enqueue encrypted work without account lookup or provider I/O. The worker checks eligibility and creates the one-time code, storing only its digest; raw codes are never placed in outbox payloads. `flask --app wsgi:app outbox-run --limit 20` performs one bounded drain. A free web service is not an always-on job worker. For a synthetic university demo, an operator can drain jobs manually within the account-request queue TTL of 15 minutes. Failed, expired or ambiguous account delivery requires a fresh public request; it is not automatically resent. Authenticated company invitations retain direct delivery. Never mark queued or ambiguous work as delivered because a process started.
7. Record a rollback plan that accounts for migration compatibility; do not assume destructive downgrades preserve business history. Monitor failed requests, queue age/ambiguous deliveries, database/storage quota and backup age. Assign an operator before using real business data.

No endpoint/provider behavior is considered verified merely because its environment variables are present. Public DNS/TLS, provider account authorization, database grants, background supervision, external delivery, object persistence and restore timing require validation in the selected deployment.

## Database backup and restore rehearsal

Run these utilities on a trusted operator host with the project Python dependencies and either PostgreSQL 17 clients on PATH or Docker with the separate tools image. The web image contains no backup clients. The client major version must match or be newer than the server. From a protected operator shell with `DATABASE_URL` injected securely:

```sh
bash scripts/backup.sh --directory /private/backups
python scripts/restore_verify.py restore /private/backups/recalltrace-TIMESTAMP.dump --drop-after-success
```

For local development, use `.venv/bin/python` and load the private `.env` through the application's supported dotenv tooling before running these commands. The scripts do not source a shell file or print a connection string. The wrapper selects `.venv/bin/python` when available; `RECALLTRACE_PYTHON` can select the appropriate interpreter explicitly.

To use the separate PostgreSQL clients instead of host-installed clients:

```sh
docker build --target database-tools -t recalltrace:database-tools .
export RECALLTRACE_PG_TOOLS_IMAGE=recalltrace:database-tools
bash scripts/backup.sh --directory /private/backups
.venv/bin/python scripts/restore_verify.py restore /private/backups/recalltrace-TIMESTAMP.dump --drop-after-success
```

Use a reviewed image digest for deployed operator tooling. Archives stream between the host and client container; database passwords are passed through the protected child environment, never command arguments. Configured TLS certificate/key files are mounted read-only and `verify-full` remains enabled. On POSIX hosts the client uses the operator's UID/GID to preserve private-key access permissions. For a local Compose database, set `RECALLTRACE_PG_TOOLS_NETWORK` to its existing private bridge network and `RECALLTRACE_PG_TOOLS_HOST=postgres` so only the container client resolves that service name; the Python verifier still connects using the host address in `DATABASE_URL`. Do not use host networking. No network override is normally needed for an authorized remote database.

Backups are PostgreSQL custom-format archives with mode 0600, a SHA-256 manifest and a private 0700 destination directory. Retain archives on separate protected storage rather than ephemeral web disk. Restore first checks the manifest hash, then creates a new randomly named `recalltrace_restore_*` database. It never overwrites the application's database. The operator needs temporary database-creation privileges for this rehearsal. Failed restorations are kept for private diagnosis; successful rehearsals are kept unless `--drop-after-success` is supplied. Only the newly created rehearsal database is eligible for that cleanup.

The verifier checks migration metadata, reports table counts and reconciles the posted stock journal against balance projections when present. This is database verification, not a complete business/evidence restore test. Separately restore every evidence object and compare its checksum/size to `documents`, recover the correct MFA encryption key/version through a separate channel, and run the C10 trace plus access/hold/recovery checks. Record measured recovery time and the age of restored data. No achieved RPO/RTO is claimed until that exercise completes.

## CI and remaining external work

`.github/workflows/ci.yml` installs hashed development dependencies with Python 3.13, starts actual PostgreSQL 17 and Redis, runs migrations/integration tests, checks model drift, Ruff and dependency audit. CI executes only when the workflow is pushed and GitHub Actions runs; the presence of this file is not a recorded successful CI run. Branch protection, secret configuration, required checks and release permissions are provider/repository settings.

The user must create/link hosting services, securely supply credentials and complete provider verification/domain steps before a public deployment can be exercised. The repository does not create paid resources, send real recall communications, or publish a site automatically.

## Security review follow-up

Read SECURITY_REVIEW.md before deployment. Runtime application files are root-owned/read-only for UID 10001; only the private instance directory is writable. Package installation and dependency validation happen at build time; pip/ensurepip are deliberately absent from the runtime image. Rebuild for dependency updates rather than installing packages inside a running web container.

The supported Alpine web image and separate PostgreSQL-tools image replace the Debian image carrying nine unresolved advisories. Final Trivy 0.76.1 scans returned zero findings across all severities in both images without suppression; see SECURITY_REVIEW.md for digests and dated evidence. Runtime and development Python lock audits are also clean. Public recovery/verification now use the encrypted worker queue, removing account eligibility and provider latency from their HTTP path. Shared database contention means this is not a formal constant-time guarantee. Public provider access remains unconfigured, and future dependency/base-image updates require fresh scans.
