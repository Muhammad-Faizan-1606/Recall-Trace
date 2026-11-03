# RecallTrace

RecallTrace is a Flask/Jinja application for company-scoped batch traceability and controlled recall investigations. The selected release is **72 related Core models**. The original 28 Expanded models are outside the agreed scope. PostgreSQL is the connected source of business records; Redis supplies shared sessions and rate counters.

The Core application includes company access, partner/catalog/facility/lot management, purchasing and receipts, stock journal and transfers, production genealogy, sales and dispatch, inspections and holds, upstream/downstream tracing, independently approved recall cases, recipient notices, recovery/disposition, private evidence, item CSV imports, scoped exports, notifications and a durable delivery outbox. Protected history uses controlled workflows; it is not exposed through arbitrary table editors.

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
ACCOUNT_MAIL_DIR=account-mail MAIL_MODE=local .venv/bin/gunicorn --config gunicorn.conf.py --bind 127.0.0.1:8000 wsgi:app
```

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

`ACCOUNT_MAIL_DIR=account-mail` enables a private local account mailbox under `instance/account-mail`. Message files contain one-time codes and are never served by the application. Use them locally for invitations, verification and password recovery; no real email is sent. `MAIL_MODE=local` similarly records development notice attempts as `local_written`, never external `sent`.

Open **Account security** to enroll an authenticator. Enrollment confirms the current password, encrypts the TOTP secret, and displays one-time recovery codes privately. Enrolled accounts must verify each login; approval/release/closure actions require recent MFA. TOTP steps and recovery codes cannot be replayed. Password recovery does not bypass an enrolled factor. Back up the MFA encryption key/version separately from the database.

Invite a second reviewer through Company access with explicit quality/case/notice permissions; review authority does not require owner access. Partner accounts must use a portal-only `notice.read`/`notice.acknowledge` role and a same-company partner restriction. They see only their own approved recipient notices. Role/membership changes revoke affected sessions, and current grants remain enforced on every operation.

## Checks

```sh
.venv/bin/python -m pytest -q --tb=short
.venv/bin/ruff check app tests scripts migrations wsgi.py gunicorn.conf.py
.venv/bin/ruff format --check app tests scripts migrations wsgi.py gunicorn.conf.py
.venv/bin/flask --app wsgi:app db check
.venv/bin/python -m pip check
.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt
bash scripts/security_checks.sh
```

Integration tests use only the dedicated **recalltrace_test** database and Redis databases 2/3. The test PostgreSQL user needs database-creation privileges. Never point these checks at shared business infrastructure. CSRF, sessions, rate limiting, PostgreSQL constraints and transaction locks remain enabled. The suite covers real competing stock consumption and access changes, not just syntax or model counts.

With Gunicorn running and the appropriate private password files:

```sh
.venv/bin/python scripts/browser_smoke.py --password-file /private/demo-password
.venv/bin/python scripts/access_browser_smoke.py --password-file /private/owner-password
.venv/bin/python scripts/core_browser_smoke.py --password-file /private/owner-password
```

Chromium defaults to `/usr/bin/chromium`; the isolated synthetic test browser uses `--no-sandbox` and must not browse untrusted sites. Account/access smoke retains uniquely named fictional access records. `/health/live` reports process liveness; `/health/ready` checks PostgreSQL, shared sessions and rate storage without exposing credentials.

See [the adversarial security review](documentation/SECURITY_REVIEW.md) for the latest regression results, confirmed fixes and unresolved container advisories.

## Hosting and operational limits

The deployment path is **Render web + Supabase PostgreSQL/private storage + authenticated TLS Redis + Resend + a trusted malware scanner**, with an independently supervised outbox runner. `render.yaml`, the non-root Docker image, configuration validation, CI workflow and backup/restore tools are included. Production rejects missing/insecure configuration; see the deployment guide for exact fields, certificate trust, migrations and runtime database privileges.

No external accounts, public database, DNS, production credentials, scanner or authorized mail sender have been provisioned here. Free-tier services may sleep, pause or lack durable workers/backups. The app's filesystem is not durable evidence storage on an ephemeral web host. Production provider connectivity, HTTPS ingress, real delivery, shared storage, worker supervision and full disaster recovery must be verified in the selected deployment before claiming business readiness.

Core imports currently support items; exports support the documented scoped kinds. Receipt/transfer stock corrections use compensating reversals. Production/shipment history is preserved; arbitrary retroactive genealogy/dispatch rewrites are intentionally unavailable. The original course's interpretation of CRUD for protected system/history records remains a grading clarification. No production SLA, legal retention policy, security certification, full performance target or complete evidence/key recovery is implied by local tests.
