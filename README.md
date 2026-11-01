# RecallTrace

RecallTrace is a Flask/Jinja application for company-scoped batch traceability and recall investigation. **M1 and the first M2 access slice are implemented:** catalog CRUD, company invitations, role/membership administration, email verification, password recovery, and session revocation. The investigation, stock, quality, and recall workflows remain planned; see [STATUS.md](STATUS.md) and [PLAN.md](PLAN.md).

## Local development

Prerequisites: Python 3.13, Docker with Compose, and either `uv` or Python's `venv`/`ensurepip` component. Tested here on Python 3.13.5, PostgreSQL 17.11 and Redis 7.4.12. Use the existing checkout; cloud tasks already have an isolated workspace and do not need a Git worktree.

From the repository root:

```sh
bash scripts/setup.sh
.venv/bin/flask --app wsgi:app seed-demo
.venv/bin/flask --app wsgi:app run --host 127.0.0.1 --port 8000
```

The setup script installs the hashed development lock, creates `.env` with random signing/database secrets if absent, starts private local PostgreSQL/Redis containers, and applies Alembic migrations. It preserves existing `.env` and database contents. On Debian/Ubuntu without `uv`, install the matching Python 3.13 venv component first. Setup was tested with `uv`; the host lacks `ensurepip`.

`seed-demo` prompts for a password (15–128 characters; common choices rejected). It creates fictional Aurora and Beacon workspaces, an item/unit/variant per company, and four accounts:

| Account | Access |
| --- | --- |
| catalog-editor@aurora.test | Aurora catalog read/write |
| auditor@aurora.test | Aurora read only |
| catalog-editor@beacon.test | Beacon catalog read/write |
| auditor@beacon.test | Beacon read only |

All four receive the password you supply locally. No default password is shipped. Repeating the seed preserves existing passwords/data. In the current cloud instance, a generated demo password is retained privately in `/tmp/recall-demo-password`; no value is in source or logs. This file is not a durable credential-management solution.

For a dedicated WSGI server during local checks:

```sh
.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
```

`/health/ready` checks PostgreSQL, Redis sessions, and rate storage. Ports 5432 and 6379 are bound only to loopback. Local PostgreSQL/Redis are for development, not production deployment. Live containers and web processes may need restarting in a restored cloud task; rerun setup, then start the web server.

## Company access and local account delivery

After migrating and seeding an existing company, bootstrap its first owner with a password supplied privately:

```sh
.venv/bin/flask --app wsgi:app create-owner --company aurora --email owner@aurora.test
ACCOUNT_MAIL_DIR=account-mail .venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app
```

`create-owner` is a local operator command, not a web endpoint. It creates only the first active owner, preserves existing passwords, and requires the current password when reusing an account. Subsequent owners can be invited or assigned through Company access. The current instance's generated owner credential is stored privately in ignored `instance/owner-password.txt`.

The owner can open **Company access** from the catalog, create/edit roles from implemented permissions, manage memberships, and invite users. Unused roles can be deleted; referenced roles archive. The protected owner role and last active owner cannot be removed. Membership or role changes revoke affected users' sessions, requiring a new login. The membership editor assigns one role at a time.

`ACCOUNT_MAIL_DIR=account-mail` opts into a development mailbox at `instance/account-mail`. It must be inside the Flask instance directory. Local message files contain one-time codes, have mode 0600, and must remain private; they are never served by the app. Read a message locally and paste its code into the linked account form. Raw codes never appear in HTTP URLs or rendered responses. No external SMTP service is configured. Delivery is synchronous local development tooling, without the future durable outbox/retry guarantee. An unavailable mailbox is shown as unconfigured; a write failure does not prove delivery.

Login links lead to invitation acceptance, password recovery, and email verification. New invitees set their own password; existing users must sign in to the invited account. Invitations last 48 hours, verification codes 24 hours, and reset codes 30 minutes. Codes are single-use; requesting a newer account code invalidates the previous one. Password reset revokes all sessions. Invitations prove ownership of the invited email, while existing M1 users can request separate verification. Email verification is recorded but is not yet an application-wide login prerequisite.

The **Your sessions** screen shows only the signed-in user's recent registry entries and permits revocation, including the current session.

To exercise these screens with real Chromium:

```sh
.venv/bin/python scripts/access_browser_smoke.py
```

This prompts for the owner's password and expects `owner@aurora.test`, Aurora, and the local mailbox above. It creates unique fictional users/roles and retains those access records. It tests email verification consumption when the owner is unverified; repeat runs explicitly report that consumption was not rerun for an already verified owner.

## Configuration

`.env.example` documents supported settings. `scripts/init_local.py` creates the ignored local `.env` once, with mode 0600. Never commit `.env`, session cookies, or passwords. `DATABASE_URL` must use `postgresql+psycopg://`; SQLite is intentionally unsupported. Sessions use `SESSION_REDIS_URL`, and rate limits use `RATELIMIT_STORAGE_URI`. Local HTTP cookies are HttpOnly and SameSite=Lax. **APP_ENV=production deliberately refuses startup** until M2–M7 controls and deployment validation are complete; this release makes no production-readiness claim.

## Checks

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests scripts migrations wsgi.py
.venv/bin/ruff format --check app tests scripts migrations wsgi.py
.venv/bin/flask --app wsgi:app db check
.venv/bin/python -m pip check
.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt
```

Tests require the local services. They create/migrate **recalltrace_test**, then truncate only that dedicated database between cases. The local PostgreSQL development user needs database creation rights. Test rate limits use Redis database 2; sessions use database 3. Do not point this test environment at shared production infrastructure. CSRF, Redis sessions, and rate limiting stay enabled. The suite includes real PostgreSQL competing inserts and independent-session optimistic conflict checks, not stock-locking verification.

For a real browser check, start the server and install Chromium locally (this cloud image supplies `/usr/bin/chromium`), then run:

```sh
.venv/bin/python scripts/browser_smoke.py
```

The script prompts for the demo password, uses Playwright with the specified local Chromium (`--chromium /path/to/chromium`), and checks sign-in, narrow-screen catalog navigation, item CRUD, refresh, concurrent authenticated requests, and signout. It creates/deletes a uniquely named fictional item. `--password-file` is available for private local automation. This isolated development browser uses `--no-sandbox`; do not use it for browsing untrusted sites.

## Implementation boundaries

- Factory and blueprints: `app/`; explicit UUID routes for three catalog resources.
- WTForms validation, global CSRF, escaped Jinja templates/macros, local Bootstrap 5.3.8 assets, flash feedback, and 303 redirects.
- Services enforce live action permissions and company ownership. Partner-restricted memberships cannot access internal catalogs.
- PostgreSQL composite foreign keys prevent cross-company parent assignments. Natural code/SKU uniqueness rejects repeated create submissions; stale versioned updates return 409. This is not general business-posting idempotency.
- Unused catalog records can be deleted. Referenced items/units archive and remain readable through existing variants. Referenced unit dimension/precision cannot change.
- Argon2id passwords, rotated Redis session IDs, digest-only revocable session registry, 30-minute idle/8-hour absolute expiry, and shared login rate counters.
- Fourteen implemented model tables; the supplied design still targets 72 Core and 28 Expanded. The rubric's 40-model minimum is not yet met.

M2 still needs privileged MFA, audit history, partner records, facilities and lot identity, plus fuller account-lifecycle and deployment controls. Stock posting, trace algorithms, evidence storage, Celery/outbox, notices, benchmarks, and backup/restore are not implemented. The small initial password blocklist is not a breached-password service. Restricted partner views are not implemented; internal access is denied instead.

## Dependencies and references

Runtime and development inputs are `requirements.in` and `requirements-dev.in`; resolved packages and artifact hashes are in the matching `.txt` locks. To intentionally refresh them, use `uv pip compile --generate-hashes ...`, then repeat setup and checks. Do not edit lock hashes to silence verification failures.

Original specification files remain under `documentation/` and `references/`; their planned acceptance scenarios are not test results. The original course rubric is `references/Flask_Project_Rubric.pdf`. Bootstrap 5.3.8 comes from the official npm tarball over verified TLS; its MIT license is in `app/static/vendor/BOOTSTRAP-LICENSE`. No frontend framework or external API is required for M1.
