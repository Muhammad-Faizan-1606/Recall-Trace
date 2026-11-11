# RecallTrace

**Batch traceability and recall investigation for a manufacturing company.**

If a supplier says "switch lot C10 is faulty", RecallTrace answers four questions from recorded data:
which finished lots contain it, where those lots are now (in stock or shipped to which customer), how to
block the stock that is still on hand, and how to notify the customers who received it and prove the goods
were recovered.

It is a Flask / Jinja2 / PostgreSQL web application built for **Web Engineering (CSE601330)**. Every record
belongs to a company (multi-tenancy), and risky actions such as approving a recall or releasing a quality
hold need a *second, MFA-verified person* (the "four-eyes" rule).

- **Live backend:** <https://recall-trace-three.vercel.app> (Vercel + Supabase PostgreSQL + Upstash Redis). Free tiers may be slow to wake. Uploads stay quarantined there because no malware scanner is configured.
- **Read-only preview (fictional data, no login):** <https://muhammad-faizan-1606.github.io/Recall-Trace/>

---

## Contents

1. [Features](#features)
2. [Tech stack](#tech-stack)
3. [Quick start (local)](#quick-start-local)
4. [Environment variables](#environment-variables)
5. [Seed data and demo accounts](#seed-data-and-demo-accounts)
6. [Using the application](#using-the-application)
7. [Project structure](#project-structure)
8. [Database and migrations](#database-and-migrations)
9. [Tests and quality checks](#tests-and-quality-checks)
10. [Security design in brief](#security-design-in-brief)
11. [Deployment](#deployment)
12. [Known limitations](#known-limitations)
13. [Acknowledgements](#acknowledgements)
14. [Further documentation](#further-documentation)

---

## Features

| Area | What you can do |
|---|---|
| **Company access** | Roles and permissions, invitations, MFA (TOTP) with recovery codes, revocable sessions, password reset and email verification, partner-only portal accounts. |
| **Catalog and master data** | Items, units of measure, SKUs; suppliers and customers with roles, contacts and addresses; sites, warehouses, storage locations; lots; carriers; categories. |
| **Operations** | Purchase orders, goods receipts, transfers, production runs (inputs and outputs, i.e. genealogy), sales orders, shipments. Stock is kept in an append-only journal plus a balance table; corrections use compensating reversals. |
| **Quality** | Inspection templates (frozen once published), inspections, nonconformances, lot holds that block stock movement, and hold release by a different reviewer. |
| **Investigations** | Add suspect source lots, compute an upstream or downstream trace (bounded breadth-first search over posted production genealogy), review exposure by SKU, submit, approve independently, record recovery, close. |
| **Notices** | Recipient-specific recall notices, independent approval, queued delivery, acknowledgement (kept separate from physical recovery). |
| **Evidence and reports** | Private file uploads (PDF, PNG, JPEG) that stay quarantined until scanned clean, item CSV import with dry run and atomic commit, scoped exports, notifications. |

All of this is implemented with **72 related SQLAlchemy models**.

## Tech stack

| Layer | Technology |
|---|---|
| Language / web | Python 3.13, Flask 3.1, Jinja2, Bootstrap 5 (served locally, no CDN) |
| Data | PostgreSQL 17, SQLAlchemy 2, Flask-SQLAlchemy, Alembic via Flask-Migrate, psycopg 3 |
| Sessions and limits | Redis 7.4 with Flask-Session and Flask-Limiter |
| Security | Flask-Login, Flask-WTF (CSRF), argon2-cffi, cryptography (Fernet) |
| Server / ops | gunicorn, Docker / Docker Compose, GitHub Actions |
| Hosting used | Vercel (web), Supabase (database and private storage), Upstash (Redis), Resend (email) |
| Tooling | pytest, ruff, bandit, pip-audit, Playwright |

---

## Quick start (local)

### Prerequisites

- Python 3.13 and either [`uv`](https://docs.astral.sh/uv/) or the Python 3.13 `venv`/`ensurepip` component
- Docker with Docker Compose (runs local PostgreSQL 17 and Redis 7.4)
- Git
- Linux or macOS. The setup script is Bash and uses `.venv/bin/...` paths; on Windows use WSL.
- Chromium is needed only for the optional browser smoke tests.

### 1. Clone and set up

```sh
git clone https://github.com/Muhammad-Faizan-1606/Recall-Trace.git
cd Recall-Trace
bash scripts/setup.sh
```

`scripts/setup.sh` does the following, and is safe to re-run:

1. Creates `.venv` and installs the hash-pinned dependencies from `requirements-dev.txt`.
2. Creates `.env` once, with a generated `SECRET_KEY`, database password and local connection URLs.
3. Adds a generated `MFA_ENCRYPTION_KEY` to `.env` if one is missing.
4. Starts PostgreSQL and Redis on `127.0.0.1` with `docker compose up -d --wait`.
5. Applies all migrations with `flask db upgrade`.

### 2. Create demo data

```sh
.venv/bin/flask --app wsgi:app seed-demo
.venv/bin/flask --app wsgi:app create-owner --company aurora --email owner@aurora.test
.venv/bin/flask --app wsgi:app init-business --company aurora
.venv/bin/flask --app wsgi:app seed-investigation-demo --company aurora --owner-email owner@aurora.test
.venv/bin/flask --app wsgi:app seed-demo-extras --company aurora --owner-email owner@aurora.test
```

`seed-demo` and `create-owner` prompt for a password. **No default password is shipped.** The seed commands
are development-only (they refuse to run when `APP_ENV` is not `development`), are repeatable, and never
overwrite existing accounts or records.

### 3. Run the web server

```sh
ACCOUNT_MAIL_DIR=account-mail MAIL_MODE=local \
  .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8000 wsgi:app
```

Open <http://127.0.0.1:8000/login> and sign in as `owner@aurora.test` with the password you chose.

### 4. Run the outbox worker (second terminal)

```sh
ACCOUNT_MAIL_DIR=account-mail MAIL_MODE=local .venv/bin/flask --app wsgi:app outbox-run --watch
```

Password reset, email verification and recall notices are **queued in the database and delivered by this
worker**. Starting only the web server will not deliver them. For a one-off drain use
`outbox-run --limit 20` instead of `--watch`. Account requests expire 15 minutes after being queued.

With these settings no real email is sent. Messages are written as files under `instance/account-mail/`
(these contain one-time codes: never commit or share them).

### Starting a real, empty installation

Skip both demo seeds and create the company before its first owner:

```sh
.venv/bin/flask --app wsgi:app create-company --name "Your company" --slug your-company
.venv/bin/flask --app wsgi:app create-owner --company your-company --email you@example.com
.venv/bin/flask --app wsgi:app init-business --company your-company
```

`init-business` grants the owner role the full catalogue of 23 Core permissions (defined in
`app/core_admin.py`). Give everyone else narrower roles through **Company access** in the app.

---

## Environment variables

The app reads `.env` automatically (python-dotenv). `.env.example` is the template; `scripts/setup.sh`
generates a working local `.env`. Never commit `.env` or the `instance/` directory.

### Required in every environment

| Variable | Meaning |
|---|---|
| `APP_ENV` | `development`, `testing` or `production`. Any other value stops the app from starting. |
| `SECRET_KEY` | Random signing secret, at least 32 characters. |
| `DATABASE_URL` | PostgreSQL URL; must start with `postgresql+psycopg://`. Local: `postgresql+psycopg://recalltrace:<password>@127.0.0.1:5432/recalltrace`. |
| `SESSION_REDIS_URL` | Redis for server-side sessions. Default `redis://127.0.0.1:6379/0`. |
| `RATELIMIT_STORAGE_URI` | Redis for rate-limit counters. Default `redis://127.0.0.1:6379/1`. |
| `MFA_ENCRYPTION_KEY` | Fernet key that encrypts MFA secrets and queued account requests. Generated by `scripts/init_security.py`. The web app and the worker must share it. Back it up separately from the database. |
| `MFA_KEY_VERSION` | Key label, default `v1`. |

### Local development extras

| Variable | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | Used by `compose.yaml` for the local database. Generated into `.env`. |
| `ACCOUNT_MAIL_DIR` | Set to `account-mail` to write development emails (invitations, recovery, verification) as private files in `instance/account-mail/`. **Must be unset in production.** |
| `MAIL_MODE` | `unconfigured` (default), `local` (development; records attempts as `local_written`) or `resend` (production). |

### Production only (validated at startup; the app refuses to start if unsafe)

| Variable | Meaning |
|---|---|
| `ALLOWED_HOSTS` | Comma-separated exact public hostnames (no wildcards). Render and Vercel can supply it automatically. |
| `TRUSTED_PROXY_HOPS` | Number of proxies in front of the app, 0 to 3. |
| `STORAGE_BACKEND` | `supabase` (private bucket) or `filesystem`. |
| `EVIDENCE_ROOT` | With `filesystem`: absolute path of an existing directory readable only by the app user. |
| `SUPABASE_URL`, `SUPABASE_STORAGE_BUCKET`, `SUPABASE_SERVICE_KEY` | Private evidence storage on Supabase. |
| `SCANNER_ENDPOINT` or `CLAMAV_HOST` / `CLAMAV_PORT` | Malware scanner (HTTPS endpoint, or ClamAV daemon, default port 3310). |
| `SCANNER_MODE` | `required` (default) or `unconfigured`. The latter is an explicit demo opt-in: uploads are stored but stay quarantined forever. |
| `MAIL_MODE=resend`, `MAIL_API_KEY`, `MAIL_FROM` | Real email through Resend. |

Production also requires: PostgreSQL with `sslmode=verify-full` and a trusted `sslrootcert` for remote hosts,
and authenticated TLS (`rediss://`, certificate and hostname verification) for both Redis URLs. Details are in
[documentation/DEPLOYMENT.md](documentation/DEPLOYMENT.md).

### Other, optional

| Variable | Meaning |
|---|---|
| `RECALLTRACE_PREVIEW=read-only` | Required to start the read-only preview app (`app.preview`). |
| `REDIS_URL`, `VERCEL_PROJECT_PRODUCTION_URL`, `RENDER_EXTERNAL_HOSTNAME` | Fallbacks read by the Vercel and Render adapters. |
| `DATABASE_ACCESS_ADMIN_URL` | Used only by the operator tool `operations/database_access.py`. |
| `RECALLTRACE_PG_TOOLS_IMAGE`, `_NETWORK`, `_HOST` | Optional settings for backup tooling in Docker. |

---

## Seed data and demo accounts

`seed-demo` creates two fictional companies, **Aurora Lamps** (`aurora`) and **Beacon Components** (`beacon`),
each with an item `LAMP`, a SKU `LAMP-01` and unit `EA`, plus these users (all with the password you typed at
the prompt):

| Account | Role |
|---|---|
| `catalog-editor@aurora.test`, `catalog-editor@beacon.test` | Read and manage catalog |
| `auditor@aurora.test`, `auditor@beacon.test` | Read-only |

`create-owner` adds the company administrator. `seed-investigation-demo` posts the fictional **C10** case
through the real posting services:

| Event | Quantity |
|---|---|
| Switch lot C10 received | 200 switches |
| Run A consumes 100 C10, makes lamps in lot L1 | 100 lamps |
| Run B consumes 50 C10, makes lamps in lot L2 | 50 lamps |
| Shipment S1 (from L1) / S2 (from L2) | 60 / 50 lamps |
| Unrelated lot C11, producing L3, shipped as S3 | excluded from the trace |

Expected trace result for C10: **150 potentially affected lamps (110 dispatched, 40 in stock)**, and **50 unused
switches counted separately**. L3 and S3 are excluded. These numbers describe recorded *potential* exposure, not
proof that products are defective. `seed-demo-extras` adds readable names, contacts, a carrier, a completed
inspection, a quality issue and a case task. It creates no holds, approvals or notices, so those remain live
demo steps.

All demo records are fictional and use `.test` addresses. Never use them on a real deployment.

---

## Using the application

1. **Master data and catalog:** create items, units, SKUs, partners (suppliers and customers), sites, warehouses, locations and lots.
2. **Operations:** create and post purchase orders and receipts, record production inputs and outputs, transfers, sales orders and shipments. Posting is atomic and idempotent; held or insufficient stock is rejected.
3. **Quality:** publish inspection criteria, record observations, raise findings, place holds. A hold is released by a *different* reviewer with MFA verified in the last 10 minutes.
4. **Investigations:** add source lots, compute a trace, review SKU totals, submit a current, complete downstream trace. A different MFA-verified reviewer approves, which places holds on every reached lot. If shipments or production change afterwards, the scope is stale and must be recomputed.
5. **Notices:** prepare one notice per affected recipient, approve it independently, queue it, then let the worker deliver it. Record acknowledgement separately from verified recovery.
6. **Evidence and reports:** upload evidence (quarantined until scanned), import items from CSV (header exactly `code,name,kind`; dry run first, then commit), export, read notifications.

To demonstrate approvals you need a second user: invite a reviewer through **Company access**, and let both
users enroll an authenticator in **Account security**. A step-by-step walkthrough, including the partner portal,
is in [documentation/CORE_GUIDE.md](documentation/CORE_GUIDE.md).

---

## Project structure

```
wsgi.py, index.py          entry points (containers / Vercel)
app/
  __init__.py              create_app(): config, extensions, security headers, health checks
  extensions.py            db, migrate, login, csrf, sessions, rate limiter
  configuration.py         environment handling and production safety checks
  core_admin.py, cli.py    flask commands, the permission catalogue
  forms.py, presentation.py  base forms; Jinja filters (qty, tag)
  policies/                authorization checks (membership, permission)
  models/                  72 ORM models in 9 modules
  services/                business rules and transactions (21 modules)
  blueprints/              HTTP routes (12 modules)
  templates/, static/      Jinja pages, local Bootstrap, fonts, CSS
  preview.py, vercel.py    read-only preview app; Vercel adapter
migrations/                Alembic revisions (schema history)
operations/                operator tool for database role permissions
scripts/                   setup, backup/restore, smoke tests, preview export
tests/                     pytest suite (PostgreSQL + Redis)
documentation/             specification, design docs, deployment and security notes
certs/                     public Supabase root certificate
.github/workflows/         CI, Vercel deploy, outbox worker, preview publishing
```

Layering rule: **blueprints** parse forms, call a **service** and render; **services** check permissions,
take row locks, apply rules, write audit rows and commit once; **models** declare tables and database
constraints.

---

## Database and migrations

- 72 tables, all company-owned tables linked with **composite foreign keys** `(organization_id, id)`, so a row can never reference another company's record.
- Quantities are `NUMERIC` in each SKU's base unit; never floats.
- Posted history (stock journal, audit, trace snapshots, hold reviews and so on) is protected by database triggers; corrections are reversals.

```sh
.venv/bin/flask --app wsgi:app db upgrade     # apply migrations
.venv/bin/flask --app wsgi:app db check       # model/migration drift check
```

Revisions: `f8f8a10682e5` (identity, sessions, catalog) → `b048a3685ae0` (invitations, account tokens) →
`a25c70d62f52` (complete 72-model schema) → `c72a01`–`c72a04` (history protection, partner scope, encrypted
account queue, line-guard fix). ER diagrams are in `documentation/diagrams/`.

---

## Tests and quality checks

Tests run against real PostgreSQL and Redis (SQLite cannot verify the row-locking behavior). They use a
dedicated database `recalltrace_test` and Redis databases 2 and 3, so the DB user from `.env` must be allowed to
create databases. **Never point them at shared infrastructure.**

```sh
.venv/bin/python -m pytest -q --tb=short
.venv/bin/ruff check app tests scripts operations migrations wsgi.py index.py gunicorn.conf.py
.venv/bin/ruff format --check app tests scripts operations migrations wsgi.py index.py gunicorn.conf.py
.venv/bin/flask --app wsgi:app db check
.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt
bash scripts/security_checks.sh        # pip-audit and bandit
```

The suite covers CSRF and sessions, rate limits, MFA, tenant isolation, competing stock consumption, holds,
self-approval and stale-trace attacks, evidence quarantine, the outbox, deployment configuration and the C10
fixture. Some tests in `tests/test_database_access.py` need PostgreSQL 17 (`docker compose` provides it).
Optional browser checks (need Chromium and a running app) are `scripts/*_smoke.py`. See
[STATUS.md](STATUS.md) for the dated record of what was actually run.

Health endpoints: `/health/live` (process is up) and `/health/ready` (database, session Redis and rate-limit
Redis reachable).

---

## Security design in brief

- Login with Argon2id hashing, rate limits, generic error messages; server-side Redis sessions that can be revoked; `__Host-` cookies in production.
- CSRF protection on every form; strict Content-Security-Policy; no inline scripts.
- Authorization is rechecked on every action (membership, permission, company, partner restriction); UUIDs in URLs are never treated as access control.
- Uploads are validated by content, kept private, and not downloadable until a scanner reports them clean.
- No external calls inside web requests: email intent is stored in `job_outbox` and sent by a separate worker. Ambiguous provider outcomes are never retried automatically.

Details and test results: [documentation/SECURITY_REVIEW.md](documentation/SECURITY_REVIEW.md).

---

## Deployment

The same code runs on Vercel (`index.py`) or in Docker (`Dockerfile`, `wsgi.py`, e.g. Render). Production needs
managed PostgreSQL, authenticated TLS Redis, private evidence storage, a malware scanner, a mail provider and a
supervised outbox worker (`flask --app wsgi:app outbox-run`). On Vercel the scheduled workflow
`.github/workflows/outbox-worker.yml` plays the worker role. See
[documentation/DEPLOYMENT.md](documentation/DEPLOYMENT.md), [VERCEL.md](documentation/VERCEL.md),
[UPSTASH.md](documentation/UPSTASH.md) and [PRODUCTION_LAUNCH.md](documentation/PRODUCTION_LAUNCH.md).

The read-only preview needs no database: `RECALLTRACE_PREVIEW=read-only` and
`gunicorn --config gunicorn.conf.py 'app.preview:create_preview_app()'`
(see [documentation/FRONTEND_PREVIEW.md](documentation/FRONTEND_PREVIEW.md)).

## Known limitations

- This is a university demonstration. Passing local tests is not a security certification, production SLA or legal-retention policy.
- The live deployment has no malware scanner configured, so uploaded evidence stays quarantined. Its mail sender is Resend's sandbox address, which delivers only to the account owner.
- GitHub Actions schedules the outbox worker on a best-effort basis, so delivery can be delayed by several minutes. Free-tier hosting may sleep or pause.
- CSV import supports **items only**. Exports cover the documented kinds only.
- Receipt and transfer errors are corrected by compensating reversals. Production and shipment history cannot be rewritten.
- The 28 additional models in the original 100-model design are intentionally out of scope. The implemented schema is the 72 Core models.
- How the course interprets CRUD for protected history records (edit/delete versus reversal) is still a grading clarification.

## Acknowledgements

- **Course:** Web Engineering (CSE601330). The project follows the supplied Flask project rubric (`references/Flask_Project_Rubric.pdf`).
- **Team:** [add the names of the students who built and can explain this project]
- **Third-party material:** [Bootstrap](https://getbootstrap.com/) 5.3.8 (MIT License, `app/static/vendor/BOOTSTRAP-LICENSE`); [IBM Plex Sans](https://github.com/IBM/plex) (SIL Open Font License 1.1, `app/static/vendor/fonts/IBM-PLEX-OFL-LICENSE`); the open-source Python packages listed in `requirements.in`; the public Supabase root certificate in `certs/`.
- **AI assistance:** this project was developed with the help of an AI coding agent (OpenAI Codex), as recorded in `AGENTS.md`, `STATUS.md` and `DECISIONS.md`. [Edit this line to match your course's disclosure policy and describe which parts you wrote or reviewed yourselves.]

## Further documentation

| File | Content |
|---|---|
| [STATUS.md](STATUS.md) | Executed checks, results and limitations, by date |
| [DECISIONS.md](DECISIONS.md), [PLAN.md](PLAN.md) | Design decisions and milestones |
| [documentation/CORE_GUIDE.md](documentation/CORE_GUIDE.md) | Demonstration walkthrough and the C10 case |
| [documentation/docs/](documentation/docs/) | Proposal, architecture, database dictionary, routes, CRUD coverage, trace rules, security, test plan |
| [documentation/diagrams/](documentation/diagrams/) | ER diagrams and architecture diagram (Mermaid and PNG) |




# RecallTrace

RecallTrace is a Flask/Jinja application for company-scoped batch traceability and controlled recall investigations. The selected release is **72 related Core models**. The original 28 Expanded models are outside the agreed scope. PostgreSQL is the connected source of business records; Redis supplies shared sessions and rate counters.

The Core application includes company access, partner/catalog/facility/lot management, purchasing and receipts, stock journal and transfers, production genealogy, sales and dispatch, inspections and holds, upstream/downstream tracing, independently approved recall cases, recipient notices, recovery/disposition, private evidence, item CSV imports, scoped exports, notifications and a durable delivery outbox. Protected history uses controlled workflows; it is not exposed through arbitrary table editors.

An isolated **read-only frontend preview** is also available for browsing fictional data before production services are connected. It includes eight sample screens and the C10 trace graph, without a login or database connection. Buttons that would change data are disabled. See [the preview guide](documentation/FRONTEND_PREVIEW.md) and the separate `render.preview.yaml`; the production application still uses `wsgi:app` and its required service validation.

**[Open the live application](https://recall-trace-three.vercel.app)** — the real Flask backend on Vercel with Supabase PostgreSQL and Upstash Redis; sign in with the owner account created by the deploy workflow. Uploads stay quarantined because no malware scanner is configured.

**[Open the public frontend preview](https://muhammad-faizan-1606.github.io/Recall-Trace/)** — fictional sample data, read-only, no login required. This does not activate the production backend.

See [STATUS.md](STATUS.md) for executed checks and limitations, [the Core guide](documentation/CORE_GUIDE.md) for a demonstration walkthrough, and [deployment and recovery](documentation/DEPLOYMENT.md) for external hosting requirements. A runnable university demonstration is distinct from a verified public business deployment.

## Local setup

Use the existing checkout; a cloud task is already isolated and does not need a Git worktree. Requirements are Python 3.13, `uv` (or Python 3.13 venv/ensurepip), Docker Compose, and Chromium for browser checks.

From the repository root:

```sh
bash scripts/setup.sh
.venv/bin/flask --app wsgi:app seed-demo
.venv/bin/flask --app wsgi:app create-owner --company aurora --email owner@aurora.test
.venv/bin/flask --app wsgi:app init-business --company aurora
.venv/bin/flask --app wsgi:app seed-investigation-demo --company aurora --owner-email owner@aurora.test
.venv/bin/flask --app wsgi:app seed-demo-extras --company aurora --owner-email owner@aurora.test
ACCOUNT_MAIL_DIR=account-mail MAIL_MODE=local .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8000 wsgi:app
```

Keep a second terminal running the account/notice worker with the same local mail settings:

```sh
ACCOUNT_MAIL_DIR=account-mail MAIL_MODE=local .venv/bin/flask --app wsgi:app outbox-run --watch
```

Password recovery and email verification require this worker. For a manual demonstration, replace watch mode with `--limit 20` after submitting a request; account requests expire after 15 minutes in the queue. Starting the web server alone does not deliver them.

`seed-demo` and `create-owner` prompt privately for passwords. No default password is shipped. `init-business` explicitly grants the owner's role the implemented Core permission catalogue; assign narrower roles through **Company access**. All commands preserve existing accounts and business records. The fictional investigation seed is development-only and repeatable; it sends no notices.

Setup installs hash-verified dependencies, creates `.env` once with generated local database/signing secrets, adds an MFA encryption key if absent, starts loopback PostgreSQL 17 and Redis 7.4, and runs Alembic migrations. Existing values and volumes are preserved. Keep `.env`, the entire private `instance/` directory, passwords, MFA recovery codes and backups out of Git. A restored cloud task must restart its services; live processes are not part of a durable snapshot.

In this onboarding instance, previously generated demo/owner credentials are privately retained in ignored `instance/onboarding-password.txt`; read/use them only locally. Future fresh installations should choose their own passwords. This development file is not a production credential-management system.

For a real empty installation, create the company before its first owner instead of running either demo seed:

```sh
.venv/bin/flask --app wsgi:app create-company --name "Your company" --slug your-company
.venv/bin/flask --app wsgi:app create-owner --company your-company --email your-real-owner-address
.venv/bin/flask --app wsgi:app init-business --company your-company
```

Replace the example name/slug/address with your own. Production configuration and a migration credential must already be configured as described in the deployment guide. The owner command prompts privately; it never prints a default password.

The demo creates Aurora and Beacon workspaces with catalog editors and read-only auditors at `catalog-editor@aurora.test`, `auditor@aurora.test`, and equivalent `@beacon.test` addresses. The owner bootstrap creates the first administrator of an existing company. Never use fictional accounts on a real operational deployment.

## Use the Core workflows

1. Sign in and open a company. Use **Master data** for suppliers/customers and their roles, contacts, facilities, locations and lots; use the catalog for items, base units and SKUs.
2. In **Operations**, create a purchase order with lines and post it. Create its receipt with lot/location quantities and post it. Record production inputs and outputs, transfers, sales orders and shipment lines before posting/dispatch. Quantities use each SKU's base-unit precision; active holds and insufficient stock reject consumption atomically.
3. In **Quality**, publish inspection criteria, record and complete observations, raise findings, and place/review holds. Another eligible reviewer with recent MFA must release a hold.
4. In **Investigations**, add source lots, compute a trace and inspect the accessible graph/table and separate SKU totals. Submit a current complete downstream scope. A different MFA-verified reviewer approves it and places holds atomically. Changed exposure requires reopening, retracing, resubmission and independent reapproval; existing holds are preserved.
5. Create recipient-specific **Notices**, independently approve and queue them, then drain the committed outbox. Record acknowledgement separately from verified recovery/disposition. Closure requires current scope, completed independent tasks, resolved quantities and reviewed delivery/acknowledgement exceptions.
6. **Evidence & reports** handles private uploads, validated item CSV dry runs/atomic commits, exports and notifications. Uploads remain quarantined until a configured scanner accepts them. Unconfigured scanning never silently marks uploads clean.

For the seeded C10 case, expect **150 potentially affected lamps: 110 dispatched and 40 in stock**, plus **50 unused switches separately**. Unrelated L3/S3 are excluded. These numbers describe recorded potential exposure, not proof of defective products.

## Account delivery, MFA and partner access

`ACCOUNT_MAIL_DIR=account-mail` enables a private local account mailbox under `instance/account-mail`. Message files contain one-time codes and are never served by the application. Use them locally for invitations, verification and password recovery; no real email is sent. Public recovery/verification requests enqueue encrypted account requests before any account lookup. The worker checks eligibility and creates/delivers the code; only its digest is stored in the challenge table. Authenticated company invitations still use their existing direct delivery path. `MAIL_MODE=local` similarly records development notice attempts as `local_written`, never external `sent`.

Open **Account security** to enroll an authenticator. Enrollment confirms the current password, encrypts the TOTP secret, and displays one-time recovery codes privately. Enrolled accounts must verify each login; approval/release/closure actions require recent MFA. TOTP steps and recovery codes cannot be replayed. Password recovery does not bypass an enrolled factor. Back up the MFA encryption key/version separately from the database.

Invite a second reviewer through Company access with explicit quality/case/notice permissions; review authority does not require owner access. Partner accounts must use a portal-only `notice.read`/`notice.acknowledge` role and a same-company partner restriction. They see only their own approved recipient notices. Role/membership changes revoke affected sessions, and current grants remain enforced on every operation.

## Checks

```sh
.venv/bin/python -m pytest -q --tb=short
.venv/bin/ruff check app tests scripts operations migrations wsgi.py gunicorn.conf.py
.venv/bin/ruff format --check app tests scripts operations migrations wsgi.py gunicorn.conf.py
.venv/bin/flask --app wsgi:app db check
.venv/bin/python -m pip check
.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt
bash scripts/security_checks.sh
```

Integration tests use only the dedicated **recalltrace_test** database and Redis databases 2/3. The test PostgreSQL user needs database-creation privileges. Never point these checks at shared business infrastructure. CSRF, sessions, rate limiting, PostgreSQL constraints and transaction locks remain enabled. The suite covers real competing stock consumption and access changes, not just syntax or model counts.

With Gunicorn and the outbox worker running with local mail enabled, and the appropriate private password files:

```sh
.venv/bin/python scripts/browser_smoke.py --password-file /private/demo-password
.venv/bin/python scripts/access_browser_smoke.py --password-file /private/owner-password
.venv/bin/python scripts/core_browser_smoke.py --password-file /private/owner-password
```

Chromium defaults to `/usr/bin/chromium`; the isolated synthetic test browser uses `--no-sandbox` and must not browse untrusted sites. Account/access smoke retains uniquely named fictional access records. `/health/live` reports process liveness; `/health/ready` checks PostgreSQL, shared sessions and rate storage without exposing credentials.

See [the adversarial security review](documentation/SECURITY_REVIEW.md) for the latest regression results, confirmed fixes and scan evidence. The reviewed Alpine web and separate PostgreSQL-tools images each returned zero Trivy findings across all severities without suppression; this is a dated scan result, not a guarantee against future advisories.

## Hosting and operational limits

Follow [the production launch record](documentation/PRODUCTION_LAUNCH.md) for secure account connections and the remaining deployment checks.

The deployment path uses **Vercel or Render web + Supabase PostgreSQL/private storage + authenticated TLS Redis + Resend + a trusted malware scanner**, with an independently supervised outbox runner. [Vercel setup](documentation/VERCEL.md) uses a separate Python 3.13 entrypoint, bounded connections and a 4 MiB file limit. The Render blueprint, non-root Alpine web image, separate `database-tools` Docker target, configuration validation, CI workflow and backup/restore tools remain available. Production rejects missing/insecure configuration; see the deployment guide for exact fields, certificate trust, migrations and runtime database privileges.

The read-only sample frontend is live on GitHub Pages. The dedicated Supabase schema, restricted roles and private storage were provisioned and checked as recorded in STATUS.md. A full backend is not deployed; native database/Redis connectivity, scanner, authorized mail sender, worker and remaining release gates are pending. Free-tier services may sleep, pause or lack durable workers/backups. The app's filesystem is not durable evidence storage on an ephemeral web host. Production connectivity, HTTPS ingress, real delivery, worker supervision and full disaster recovery must be verified before claiming business readiness.

Core imports currently support items; exports support the documented scoped kinds. Receipt/transfer stock corrections use compensating reversals. Production/shipment history is preserved; arbitrary retroactive genealogy/dispatch rewrites are intentionally unavailable. The original course's interpretation of CRUD for protected system/history records remains a grading clarification. No production SLA, legal retention policy, security certification, full performance target or complete evidence/key recovery is implied by local tests.
