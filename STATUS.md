# RecallTrace implementation status

## Request performance — 11 November 2026

See DECISIONS.md for the measured baseline and design. Locally, queries per signed-in page fell from 14 to 9 (investigations), 22 to 13 (operations) and 16 to 11 (quality); static requests make zero Redis calls. New `tests/test_performance.py` covers versioned immutable static caching without cookies, private pages with Server-Timing, the once-a-minute activity write, and authorization being re-read under the company lock. Full suite: **483 passed, 16 failed** (the PostgreSQL-17-only privilege tests); Ruff and Bandit clean. Live before/after numbers are recorded below once deployed.

## Interface redesign and quantity formatting — 4 November 2026

New app shell and design system (see DECISIONS.md): grouped sidebar navigation, locally bundled IBM Plex Sans, quality-tag status colours, compact tables, a sign-in page that explains the product, and quantities without storage padding. `app/presentation.py` provides the `qty` and `tag` filters (tags built with auto-escaping `Markup.format`).

Local verification: full suite **479 passed, 16 failed** (the same PostgreSQL-17-only privilege tests); new `tests/test_presentation.py`; Ruff and application Bandit clean. Chromium screenshots of sign-in, companies, investigations, case, trace, operations, quality, items, master data and company access at 1440px and 390px showed no horizontal overflow and no browser errors.

## Readable labels and demonstration data — 4 November 2026

Screens now explain codes to first-time viewers: lots read "L1 — LED desk lamp" in stock, master data, investigations and the trace graph/table; investigation exposure shows "Shipment C10-S1 to Northside Home Stores (fictional retailer), lot L1 — LED desk lamp" instead of line UUIDs; trace evidence paths name production runs (C10-RUN-A) instead of UUIDs; SKU totals show product names; detail pages use plain labels ("Product (SKU)", "Supplier", "Warehouse") instead of "variant id"; the company heading no longer says "/ Catalog" on every page.

New idempotent, development-mode-only `seed-demo-extras` command (run by the deploy workflow's bootstrap) renames the generic fixture names (only while still unchanged) and adds fictional, `.test`-addressed records through the normal services: item categories and classifications, supplier/customer contacts and addresses, a supplier part number, a carrier, a published incoming-inspection checklist, a completed inspection of C10 with two failed checks, a high-severity quality issue linked to it, and an investigation task and discussion note. No holds, approvals or notices are created, so those remain live demo steps.

Local verification (PostgreSQL 16, Redis 7): full suite **470 passed, 16 failed**; the 16 are the same PostgreSQL-17-only `MAINTAIN` privilege tests in `tests/test_database_access.py`. New `tests/test_demo_extras.py` checks idempotency and the rendered labels. A local Chromium pass over operations, quality, lots, supplier item, investigation and trace pages showed the new labels with no page errors.

## Live Vercel backend — 4 November 2026

**https://recall-trace-three.vercel.app** is the real Flask backend (not the read-only preview). Deploy run [41909004874](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41909004874) from `main` returned `/health/live` → `{"status":"alive"}` and `/health/ready` → HTTP 200 `{"status":"ready"}`, which executes PostgreSQL `SELECT 1` through the Supabase transaction pooler (restricted `recalltrace_runtime` role, `sslmode=verify-full` with the bundled Supabase root CA) and pings Upstash Redis over verified TLS for sessions and rate limits.

The operator bootstrap ([run 41898005923](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41898005923)) applied `c72a04` to Supabase, created company `recalltrace-demo` with its owner and Core permissions, and seeded the fictional C10 case: 150 lamps produced (110 dispatched, 40 on hand) and 50 unused switches, matching the specification. Mail uses Resend's `onboarding@resend.dev` sender, which only delivers to the Resend account's own address; the owner chose not to change DNS on a business domain. Malware scanning is the explicit `SCANNER_MODE=unconfigured` opt-in, so uploads stay quarantined with a visible banner. Deployment problems found and fixed on the way: a newline in a pasted secret, the offline-SQL `%%I` trigger defect (`c72a04`), missing mail secrets and a runtime-role password mismatch.

Live Chromium check (1440px and 390px): `/login`, `/invitations/accept` and `/` (redirects to sign-in) return 200 with the quarantine banner and no horizontal overflow; a wrong login shows the generic "Invalid email or password"; a POST without a CSRF token returns 400; the session cookie is `__Host-recalltrace` with Secure/HttpOnly/SameSite=Lax; responses carry HSTS, a restrictive CSP and `nosniff`. The owner reported a successful sign-in on the live site.

**Not yet verified live:** the authenticated MFA/trace/approval walkthrough by an automated check (credentials are not shared with the agent), the scheduled outbox worker's first real delivery, evidence upload quarantine on Vercel and load/recovery behaviour. This is a university demonstration deployment, not a production-readiness or security certification.

## Vercel deployment workflow — 4 November 2026

**Production defect found and fixed by the first real bootstrap.** The Supabase schema had been applied from offline SQL, which escapes `%` to `%%`; the draft-line guard therefore executed the literal `%I` and rejected every document-line insert/update/delete (purchase orders, receipts, production, shipments). Migration `c72a04` rebuilds `recalltrace_child_guard` with `quote_ident` concatenation, which renders identically online and offline; `tests/test_offline_migration_sql.py` guards the offline rendering. The bootstrap run also confirmed live verified-TLS PostgreSQL access through the Supabase pooler and created the company, owner and Core permissions.

Added the manual `deploy-vercel.yml` operator workflow (optional company/owner/C10 bootstrap, production deployment, readiness check), the scheduled `outbox-worker.yml`, URL/host normalization in `app/vercel.py`, and the explicit `SCANNER_MODE=unconfigured` demonstration opt-in with a visible quarantine banner. See DECISIONS.md and documentation/VERCEL.md. Vercel Git auto-deployments are disabled.

Local verification on PostgreSQL **16** and Redis 7 (this session had no Docker): `pytest -q` gave **466 passed, 16 failed**. All 16 failures are in `tests/test_database_access.py` because PostgreSQL 16 lacks the `MAINTAIN` privilege; they fail identically without these changes. CI's PostgreSQL 17 is the authoritative run. 30 Vercel cases pass, including the new normalization, host, scanner-mode and Git-setting tests. Ruff check/format (102 files) and application Bandit passed. **Not yet executed:** the GitHub secrets, the Supabase root certificate, the real Vercel build, live database/Redis TLS and the bootstrap/seed against Supabase.

## Vercel backend preparation — 4 November 2026

The owner has a Vercel account and requested backend deployment; no Vercel project is created or authenticated here yet. Added a separate `index:app` entrypoint, explicit Python 3.13/Flask settings, hash-verified binary-wheel installation, Mumbai function region and a requested 60-second duration. The adapter requires production mode and Supabase storage, closes idle PostgreSQL connections with `NullPool`, bounds PostgreSQL/Redis connection waits, and retains the existing scanner/sender/TLS/host/cookie checks. The Vercel file ceiling is 4 MiB with explicit rejection of existing larger objects; other deployments retain 10 MiB. Local credentials/private reports are excluded from uploads; operational templates remain included. See documentation/VERCEL.md.

The full local PostgreSQL/Redis regression run passed **470 tests in 141.19s**, with deprecations treated as errors. After the final Vercel-only storage guard and isolated entrypoint case, **88 focused Vercel/evidence/preview cases passed in 2.45s**. The isolated import exercised the actual backend entrypoint, 72 models, an operational template and liveness without `.env`, `instance/` or operator files; provider calls were not made. Actual Git-style upload-ignore checks confirmed private paths are excluded and required backend/template files remain included. Ruff, application Bandit and diff checks passed. No production schema change was needed.

Render's current authenticated inventory returned HTTP 200 and no RecallTrace backend. Vercel API access remains missing: saved a `VERCEL_TOKEN` requirement and `api.vercel.com` destination to the environment draft, without supplying a token or publishing/applying the draft. A real Vercel project/build, hosting secrets, trusted database certificate, native database/Redis checks, scanner, sender, supervised worker and owner bootstrap remain outstanding. These local changes do not establish a live backend or production readiness.

## Upstash preparation — 4 November 2026

The owner supplied matching native TLS URLs in the direct runtime settings `SESSION_REDIS_URL` and `RATELIMIT_STORAGE_URI`. Both are observed ready and parse as database `/0` with explicit required certificate/hostname verification. Their existing distinct session/rate prefixes remain unchanged. Native verification failed before TLS/authentication at executor DNS; a public control hostname failed too. This workspace has no supported public raw-TCP route, so neither the password nor provider session/Lua behavior has been verified. Existing local development/test Redis configuration was preserved. See documentation/UPSTASH.md for Free-plan setup and safe provider checks; do not treat URI validation or a REST response as native application readiness.

## Public frontend published — 4 November 2026

The owner enabled Pages with GitHub Actions as its source. The previously blocked publishing workflow was rerun and **succeeded**, including build/export/artifact upload and deployment. The public read-only sample UI is **https://muhammad-faizan-1606.github.io/Recall-Trace/**, with enforced HTTPS and no login. [Publishing proof](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41818371923) matches tested source `fae81b8`; its separate full integration/security workflow passed too. A sanitized live deployment report is retained privately in `instance/preview/pages-live-report.json`.

The static artifact was verified locally in Chromium across eight screens at 1440px/390px, including navigation, graph, assets and read-only behavior. Direct public HTTP/browser verification from this managed environment is not claimed: the Pages hostname is outside its active network allowlist. This publishes the requested fictional frontend preview only. Production database connectivity, email, Redis, worker/scanner, evidence/recovery and business readiness remain separate; no production credentials or business data are in the site.

## Read-only frontend preview — 4 November 2026

Render's actual free-service creation was blocked by HTTP 402 requiring payment information; no resource or upgrade was created. Prepared a free GitHub Pages alternative with a pinned deployment workflow and static exporter. GitHub's integration returned HTTP 403 when enabling Pages; the owner subsequently completed Settings → Pages → Source → GitHub Actions as recorded above. The static export contains only fictional UI/public assets, not credentials, application source or database files. **49 isolated preview/export cases passed in 0.45s**; all 16 HTML routes are exported under `/Recall-Trace`.

The owner authorized a public frontend demonstration while the remaining production services are arranged. Added an independent, explicitly enabled `app.preview:create_preview_app()` factory with eight fictional sample screens, a C10 SVG trace and separate preview styles/Render blueprint. It reuses the Jinja base through two default-preserving template blocks. It initializes no production clients, accepts no business mutations and includes no real database, storage, auth or delivery credentials. The normal production factory/Docker command and service requirements remain unchanged.

**36 isolated preview tests passed in 0.54s.** Actual Chromium passed all eight screens at 1440px and 390px, navigation/trace SVG, layout bounds, disabled mutations and no browser errors/cookies. Ruff check/format (96 Python files), application Bandit and diff checks passed. Public deployment status is recorded after the provider's actual build/health result; local success alone is not a live URL claim. See documentation/FRONTEND_PREVIEW.md.

## Live private storage — 4 November 2026

The user-supplied `SUPABASE_SERVICE_KEY` binding and project hostname are active. Created `recalltrace-private` with `public=false`, a 10 MiB limit and the adapter's `application/octet-stream` MIME type. The real application storage adapter passed upload/download byte and checksum checks, incorrect-digest rejection, anonymous denial on private/public object routes, and deletion followed by an independent listing check. The harmless test object was removed; no application/business rows were created. The real scanner remains unconfigured and returned `unavailable`. The storage key was used only through its secure binding, never downloaded or persisted locally. Sanitized proof is retained privately in `instance/production/storage-report.json`.

This validates provider storage behavior, not a complete deployed evidence/tenant/scanner/recovery workflow. No RecallTrace web service is public yet. Sender domain, authenticated TLS Redis and suitable free worker/scanner hosting remain unresolved. [GitHub CI passed for `d2a5f68`](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41807505023), including tests, dependency audits and both image scans; application runtime source is unchanged by this storage setup.

## Cloud database setup — 4 November 2026

The existing dedicated Supabase `Recall Trace` project now contains the actual 72 Core tables plus Alembic metadata, head `c72a03`, with separate migration/runtime logins and reviewed object grants. A fresh cloud verifier completed **70 read-only catalog queries with zero findings**; every Core business table is empty. New restricted credentials are retained only in an ignored private directory (0700, files 0600); no existing PostgreSQL password, provider guard or non-application data was changed. Native PostgreSQL authentication/TLS from an application runtime remains unverified.

Database TLS enforcement was enabled through the provider API and read back as applied successfully. The application `public` schema was removed from both Data API exposure and its extra search path; `graphql_public` exposure and `extensions` search path were preserved. These verified provider settings supplement the direct API-role grant revocations. End-to-end native database and anonymous external API tests remain separate deployment gates. Sanitized reports are retained privately under `instance/production/` so they survive restoration with the checkout's private state.

Supabase's canonical automatic-RLS event function required a narrowly reviewed operator-tool opt-in; its exact body, ownership, return type and attachment are checked. Provider functions/event triggers remain intact. Only the 73 new backend application objects had automatic RLS disabled; Flask tenant authorization plus restricted database grants govern them. **41 database-access regressions passed in 5.59s** after restoration, with deprecations treated as errors. Ruff check/format (93 files), operator Bandit and diff checks passed. Runtime build inputs are unchanged from `95148b4` by Git comparison.

Management access to Render/Supabase/Resend is active. [GitHub CI passed for published commit `4ea28c2`](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41688141146). No RecallTrace web service was created; the unrelated suspended Render service was preserved. Resend has no sending domain. Private storage was connected and verified later on 4 November as recorded above. Redis and free worker/scanner hosting remain unresolved; the owner confirmed no always-on local/university compute is available. No real email or paid resources were created. See documentation/PRODUCTION_LAUNCH.md for current external gates; earlier disconnected-account statements below describe the prior preparation stage.

## Production deployment preparation — 3 November 2026

The owner confirmed existing Render, Supabase and Resend accounts. No provider credentials, inspected resources or public production URL are connected here. Secure API-key requirements and API destinations were saved to the cloud environment draft; saving does not apply/publish the configuration or provision resources. GitHub source pushes work, but the Actions API request was forbidden in the current runtime. Redis and free-eligible worker/scanner hosting still need to be arranged. See documentation/PRODUCTION_LAUNCH.md for the explicit external release gates; none is marked passed based on local testing alone.

Added host-only `operations/database_access.py` with explicit atomic provisioning and a read-only verifier for a separate restricted runtime role, exact Core tables/functions, immutable history and direct API/default ACLs. Unexpected public views/definer routines fail for review; provider Data API exposure still requires separate validation. **19 new isolated PostgreSQL role/ACL tests passed in 6.12s**; temporary databases/roles were removed without changing development/test database grants. Independent static review found no blocking defect. Ruff check/format (93 files), operator Bandit and diff/credential-marker checks passed. The existing 343-test application result below is unchanged and was not repeated for this host-only tooling; all 119 previously scanned image build inputs remain unchanged. See documentation/DATABASE_ACCESS.md for privileged-operation scope and remaining Supabase boundaries.

## Latest remediation — 3 November 2026

Both requested follow-ups are implemented and tested. **343 PostgreSQL/Redis tests passed in 131.02s** with deprecations treated as errors, and catalog/access/Core Chromium checks passed with the live account worker. Runtime/development pip-audit and the application Bandit scan are clean. Ruff and schema drift checks passed; the schema remains exactly 72 Core tables at migration `c72a03`.

The supported Alpine web and separate PostgreSQL-tools images each have **zero Trivy 0.76.1 vulnerabilities across all severities**, with inventories retained and no findings suppressed. This removes the affected Debian package set; it does not invent upstream fixes. Final local image IDs: web `sha256:b7116147ccd8a6bc04185ebe4d6032a2186ca63501fcf0c42af38c460aa86f64`, tools `sha256:f8dd4035db79d2147439c8753d84a33c6ac75fcf4c2c4ebef8a4a4f592d38f56`. Native crypto/content checks, source permissions, PostgreSQL/Redis and Gunicorn readiness passed in the final web image. Fresh migrations and populated database backup/restore passed using the separate PostgreSQL 17.11 tools.

Public password-reset/email-verification requests now enqueue encrypted global intent before any user eligibility lookup or mail I/O. The worker creates codes in memory, stores their digests, commits and releases locks before transport. Key derivation/versioning, expiry, tampering, supersession, claim recovery and database job-scope constraints are covered. A supervised outbox worker is required for automatic account delivery; a bounded manual drain supports the demo. Authenticated invitations retain direct delivery. Shared database contention remains possible, so this is not a formal constant-time guarantee.

See [the security review](documentation/SECURITY_REVIEW.md) for dated scan evidence, reproduction and remaining deployment limits. This section supersedes the historical image/advisory/test records below. Public hosting and live provider integrations remain unprovisioned; local validation is not security certification.

## Historical adversarial review before remediation — 3 November 2026

The completed Core release was tested beyond its original happy-path/regression suite. **307 tests passed in 140.97s**, with deprecations treated as errors, including 119 additional adversarial cases. Catalog, access and Core Chromium smoke checks passed. Runtime 43 and development 76 locked distributions have no known pip-audit advisories; Bandit's application scan has zero findings. Combined line/branch coverage is 80.3% (83.0% statements, 69.6% branches), not proof of complete security coverage.

Confirmed permission, malformed-input, stale-parent, evidence-disclosure, provider-redirect, worker-payload, slow-I/O lock, overlapping-recovery and stale-notice defects were fixed with regressions. Unknown APP_ENV fails startup. Non-root runtime code is read-only; unneeded pip/ensurepip were removed. CI now audits both locks and the application and verifies runtime source permissions. No schema change or new model was required.

The final image has zero Python/CRITICAL Trivy matches in the HIGH/CRITICAL scan, but **48 HIGH Debian package records across nine distinct CVEs remain without an available vendor fix**. No findings were suppressed. Synchronous account-mail timing and untested live-provider/deployment limits remain documented. See documentation/SECURITY_REVIEW.md for exact fixes, evidence, reproduction commands, remaining advisories and final image digest. This section supersedes earlier validation counts/image hashes below; it is not a production security certification.


Updated 3 November 2026 (Asia/Karachi). The selected final release is the **72-model Core application**, not the original 100-model plan. The 28 Expanded models are excluded. The Core schema, connected local PostgreSQL/Redis environment, operational workflows and deployment artifacts are implemented and validated locally. **No public production deployment has been provisioned or verified.**

## Current Core implementation

- Exactly 72 related ORM tables, matching the Core table set in the original logical schema, with reviewed Alembic migrations through `c72a03`; Alembic's infrastructure table is not counted.
- Company/owner bootstrap for real empty installations; explicit 23-action permission catalogue, role/membership management, internal and partner invitations, recovery/verification and revocable shared sessions. Partner accounts require live portal grants and recipient scope; they cannot access internal catalog, evidence or genealogy.
- Encrypted TOTP enrollment, per-login verification, step replay protection, digest-only one-time recovery codes, recent independent approval/release controls and safe removal/revocation. Company-scoped audited operations and immutable audit history.
- Finite validated catalog/master forms for partners, roles/contacts/addresses, facilities/locations, categories, supplier SKUs and lot identities. Referenced identities freeze, linked records archive, and positive stock prevents unsafe lot/facility archival.
- Purchase orders, receipts, production inputs/outputs, transfers, sales orders, shipment lines/events, an atomic stock journal/balance projection, stable company-first/lot locking, Decimal precision, payload-bound idempotency, order fulfillment caps, holds and journal reconciliation. Receipt/transfer reversal preserves original history.
- Published inspection criteria/completed observations, nonconformances, lot holds with independent reviews, and accepted private evidence attachment. Database guards protect posted business documents/lines, quality snapshots and immutable journal/history rows.
- Upstream/downstream bounded trace snapshots, graph/table evidence, separate SKU totals and exposure deduplication. Complete current downstream scope, recent MFA and independent approval create holds atomically. Reopening preserves holds and requires fresh submission/approval; a later snapshot cannot silently expand approved scope.
- Investigation sources/tasks/comments/evidence, independent task verification, recovery/disposition with durable evidence references/payload checks and quantity caps, and reviewed closure conditions.
- Private bounded PDF/PNG/JPEG storage, integrity checks, fail-closed scanner integration, validated item CSV dry-run/atomic import, requester-restricted expiring exports, notifications/preferences, recipient notices, independent approval, durable outbox, execution-time authorization and safe retry/ambiguous reconciliation. Local delivery is visibly `local_written`.
- Non-root pinned-base Docker image, Gunicorn configuration, Render blueprint, fail-closed production configuration, CI workflow and private SHA-verified database backup/restore tooling. Requirements are hash locked, including cryptography 50.0.2 and an explicit runtime HTTP client.

## Executed current-instance verification

| Check | Observed result |
| --- | --- |
| `bash scripts/setup.sh`, repeated on final source | Passed; preserved private local credentials/MFA key and existing development business data, synced 73 packages, restarted/reused PostgreSQL 17 and Redis 7.4, migrated safely. |
| `.venv/bin/python -m pytest -q --tb=short` | **188 passed in 75.43s (0:01:15)**, no skips in the final run. Includes the original 60 regressions and new Core/security/operational/production-configuration tests. |
| Ruff check and format check | Passed, 82 Python files. |
| `.venv/bin/flask --app wsgi:app db check` | No new upgrade operations detected; current head `c72a02`. |
| Fresh isolated PostgreSQL database | All migrations from empty passed; 72 Core tables plus Alembic; verification database removed. |
| C10 public-service fixture and repeat seed | 150 affected lamp outputs, 110 dispatched, 40 lamps in stock; 50 unused switches reported separately; unrelated L3/S3 excluded. Repeat preserved posted stock and identities. |
| Original catalog Chromium smoke | Passed sign-in, narrow navigation, catalog/item CRUD, refresh, concurrent authenticated requests and signout; no JavaScript errors. |
| Access Chromium smoke | Passed role creation, invitation/limited member, recovery and session revocation. Verification request passed; consumption was not repeated because the existing demo owner was already verified. Synthetic access history retained. |
| New Core Chromium smoke | Passed narrow master CRUD, operations/quality navigation, C10 graph/totals, CSV preview/commit, actual private export download, quarantine/no download, notifications and signout; no JavaScript errors. Synthetic import/export history retained. |
| Final runtime image | `sha256:d980b615de5792b639626f3e4f3dc4a9199e8b22f048ccb974d9e1c08204472f`; built with verified runtime hashes. UID 10001, no copied .env/password, cryptography 50.0.2, 72 models; real Gunicorn inside the image reached ready against connected PostgreSQL/Redis. |
| Dependency consistency/audit | `pip check`: no broken requirements. Final `pip-audit --disable-pip --no-deps -r requirements.txt`: no known vulnerabilities found at execution time. Not certification. |
| Populated database backup/restore | Private custom archive+SHA manifest restored into a new random database, migration `c72a02`, 72 Core tables, 11 journal lines, 3 trace results, stock reconciliation passed; restore verification 0.953801s for this tiny fixture; temporary database removed. This is not a measured business RTO. |
| Original reference manifest | `sha256sum -c MANIFEST.sha256` from documentation passed; original specification/schema/rubric references retained. |
| Reusable environment configuration | Updated `install_script` and `start_skill` saved successfully to the draft. Saving did not publish a snapshot or deploy an app. |

Earlier integration runs correctly exposed problems: colliding composite-FK names, stale role catalogue/partner bindings, self-step-down auditing after deactivation, tests trying to mutate immutable traces, inaccessible duplicate file-control IDs, a runtime-only image missing its explicit HTTP dependency, and advisories against the initial MFA encryption-library selection. The relevant sources/locks/tests were corrected, the fixed encryption release audited, and the final checks above passed. Do not reuse earlier failing logs as current readiness evidence.

## Remaining external work and limits

1. No Render/Supabase/Redis/mail/scanner provider accounts or credentials are connected. The database created and tested here is **private local development PostgreSQL**, not a public Supabase database. Follow documentation/DEPLOYMENT.md to create resources and securely supply real values. Never send passwords/API keys in chat.
2. Production settings validation is tested, but live provider TLS/certificates, HTTPS ingress/cookies, least-privilege runtime/migration roles, private bucket persistence, malware scanning and real authorized email have not been exercised. Missing scanner leaves uploaded files quarantined. No real recall communication was sent.
3. Free plans can sleep/pause and may not provide durable workers, backups or an uptime commitment. A supervised outbox runner, monitoring/operator, retention policy and external backup/key recovery remain deployment responsibilities. Manual bounded local drains are available for the university demo.
4. Database restore passed for the synthetic populated fixture. External evidence-object restoration, separate MFA-key recovery, full end-to-end disaster recovery, target workload performance and a business SLA remain unverified. No production-readiness/security certification claim is made.
5. Core CSV import supports items; exports expose documented scoped kinds. Production/shipment history cannot be arbitrarily rewritten; receipt/transfer corrections use compensating events. The 28 Expanded workflows are excluded. The instructor's interpretation of CRUD for protected/security/history records still needs confirmation.
6. Source publication is recorded separately in Git history and the accompanying push result. GitHub Actions execution, public application publication and fresh-task snapshot restoration have not been verified here. Review/save environment settings and publish the environment snapshot to retain the prepared workspace.

README.md and documentation/CORE_GUIDE.md describe the runnable workflow. Continue from this implementation, not from the historical documentation-only state below.

---

## Historical pre-Core implementation records

# RecallTrace implementation status

Updated 1 November 2026 (Asia/Karachi). M1 and the first M2 access slice are implemented in the existing published checkout. The original specification and its 62 planned acceptance scenarios remain design references, not evidence that the full product works.

## Implemented — M1

- Python 3.13 Flask factory, auth/catalog blueprints, Jinja inheritance/macros and pinned locally served Bootstrap.
- Authenticated company selection and complete item, variant and base-unit list/detail/create/edit/delete UI, with archive behavior for referenced items/units.
- Server validation, same-company parent choices and composite database FKs, active membership/action permissions, read-only role, partner denial, CSRF, escaped output, flash feedback and 303 Post-Redirect-Get.
- Argon2id login, Redis-backed rotated server sessions, digest-only revocable auth registry, idle/absolute expiry and shared Redis rate counters. Live membership/role/session changes are checked on requests.
- Versioned catalog edits and database uniqueness for repeated create submissions; referenced unit semantic changes are rejected.
- Idempotent fictional seed command, private generated local configuration, Docker Compose services, hashed runtime/development locks and tested setup/start commands in README.md.

## M1 baseline schema inventory (31 October 2026)

Migration: `migrations/versions/f8f8a10682e5_m1_identity_sessions_and_company_catalog.py`.

11 implemented ORM tables: organizations, users, memberships, roles, permissions, role_permissions, membership_roles, auth_sessions, items, item_variants, units_of_measure. Alembic's version table is additional infrastructure and is not counted.

The full target remains 72 Core + 28 Expanded. The rubric requires at least 40 meaningful related tables; M1 does not meet that final submission minimum. `memberships.partner_id` is a deferred M2 relation with internal access denied whenever populated; partner records/screens do not yet exist.

## M1 verification evidence (historical)

Environment: existing `/workspace/Recall-Trace` checkout, initially no commits (unborn `work` branch). Python 3.13.5; Flask 3.1.3; SQLAlchemy 2.0.55; PostgreSQL 17.11; Redis 7.4.12. No commit SHA exists for this uncommitted implementation.

| Executed command/check | Observed result |
| --- | --- |
| Hashed lock resolution and installation with `uv pip compile --generate-hashes` / `uv pip sync` | Installed and exercised compatible runtime/development dependencies. |
| `bash scripts/setup.sh` | Passed after adapting for missing host ensurepip; preserves `.env`, restarts/reuses healthy services and reapplies migration safely. Fresh config creation and second-run preservation separately verified in a temporary directory, mode 0600. |
| `.venv/bin/flask --app wsgi:app db upgrade` | Clean PostgreSQL application migration passed; test database separately migrated from empty. |
| `.venv/bin/flask --app wsgi:app db check` | No new upgrade operations detected. |
| `.venv/bin/python -m pytest -q` | **36 passed in 11.94s**, no skips or warnings in the final run. |
| `.venv/bin/ruff check app tests scripts migrations wsgi.py` | Passed. |
| `.venv/bin/ruff format --check app tests scripts migrations wsgi.py` | Passed (22 files). |
| `.venv/bin/python -m pip check` | No broken requirements found. |
| `.venv/bin/pip-audit --disable-pip --no-deps -r requirements.txt` | No known runtime dependency vulnerabilities found at execution time; not a security certification. |
| `.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 wsgi:app` and `.venv/bin/python scripts/browser_smoke.py --password-file /tmp/recall-demo-password` | Real Chromium passed readiness, 390px viewport sign-in, all three catalog lists, item create/read/update/delete, refresh, eight concurrent authenticated GETs, and signout; no browser JavaScript errors. |

The 36 tests exercise positive CRUD for all three resources, invalid inputs, duplicate creates, stale edits/deletes, company read/write isolation, foreign parent rejection in forms and PostgreSQL, cross-company role assignment rejection, read-only action denial, live membership/partner/role revocation, reference archival, protected unit semantics, CSRF with controls enabled, session rotation/replay/revocation/expiry/auth-version checks, login limits shared between clients, local redirect handling, production refusal, repeatable seeds, and migration/ORM inventory agreement. Competing insert tests use two independent PostgreSQL transactions; stale ORM edits use separate sessions. These do not test stock locking or the later recall workflows.

Early runs failed and were corrected: the first generated migration duplicated unique-constraint names; initial login forms rejected reserved `.test` addresses; an initial pytest invocation lacked the project import path; a test fixture incorrectly reused application-context state between requests; and the first local-config helper used an unsupported Path.open argument. Corrected implementations and subsequent checks passed. WTForms tuple-choice deprecations were replaced with SelectChoice before the final suite run.

Original documentation integrity was rechecked with `sha256sum -c MANIFEST.sha256` from `documentation/`: all entries passed. The specification files and rubric were preserved.

Reusable environment `install_script` and `start_skill` were saved successfully to the configuration draft. They reference the tested setup and service startup commands and preserve the existing checkout. Saving did not publish a new environment snapshot; review/save in environment settings and publish when desired. Current services and application were validated in this instance only.

## Implemented — M2 access slice, 1 November 2026

- Owner bootstrap CLI for existing companies; explicit access.manage permission, protected owner role, and last-owner protection serialized on the company row.
- Company access screens for role create/read/edit, deletion of unused roles, archive of referenced roles, and membership role/status changes. Users cannot grant actions above their own current authority; affected sessions are revoked on access changes.
- Internal company invitations with issuer and role composite FKs, digest-only 48-hour codes, revocation, and single-use acceptance. Acceptance rechecks issuer/role/company eligibility. Existing accounts require their own authenticated session; new accounts set a password. Accepted invitations are retained.
- Email verification and password recovery with shared rate limits, CSRF, generic request responses, digest-only expiring codes, and atomic consumption. Reset increments auth_version and revokes all sessions. Login rechecks the verified password/version under a user lock, preventing an old-password login racing a reset.
- Own-session listing and revocation UI; cross-user registry access denied. Tokens/digests are not exposed in rendered session metadata.
- Opt-in private local account mailbox under instance/, mode 0600 per message; no external mail sent. Account codes are pasted into POST forms and never put into URLs.

Current inventory: **14 ORM tables**, adding invitations, password_reset_tokens and email_verification_tokens to M1's 11. Additive migration: `b048a3685ae0`, following `f8f8a10682e5`. No schema-count claim is made for unimplemented features, and the final rubric minimum of 40 models is still unmet.

## M2 execution evidence

Current source remains uncommitted on the existing unborn work branch. PostgreSQL/Redis services were restarted from the published environment; prior implementation files were preserved. No environment was published and no saved configuration was reapplied or rewritten in this task.

| Check | Observed result |
| --- | --- |
| `.venv/bin/flask --app wsgi:app db upgrade` | Applied the additive access migration to the existing development database. |
| `.venv/bin/python -m pytest -q` | **60 passed in 15.94s**, no skips or warnings. Includes all 36 M1 regression cases. |
| `.venv/bin/flask --app wsgi:app db check` | No new upgrade operations detected. |
| Fresh temporary PostgreSQL databases, Alembic upgrade/inspection | Clean install passed with all 14 models; M1-to-M2 upgrade preserved all four seeded users and showed no metadata drift. Temporary verification databases were removed afterward. |
| `.venv/bin/ruff check app tests scripts migrations wsgi.py` and matching `ruff format --check` | Passed. |
| `.venv/bin/python -m pip check` | No broken requirements; dependency locks unchanged. |
| `.venv/bin/python scripts/access_browser_smoke.py --password-file instance/owner-password.txt` against two Gunicorn workers | Real Chromium at 390px passed role creation, invitation acceptance, read-only membership navigation, password reset, session revocation and email verification; no browser JavaScript errors. Synthetic access records retained. |

The final browser smoke was repeated successfully after reloading the latest application. It explicitly reported that verification consumption was not rerun because the owner had already been verified by the first run. The original documentation SHA-256 manifest also passed unchanged.

New tests cover token expiry/replay/supersession and no secret echo, account/request CSRF, rate limits, reset revocation, separate-transaction competing reset consumption, old-password login/reset race, invitation company/role binding and issuer revocation, existing-account takeover rejection, protected role changes, stale roles, role delete/archive lifecycle, last-owner denial and simultaneous two-owner step-down, member session revocation, owner bootstrap repeatability, and own-session isolation.

An initial version of the new login/reset race test attempted to monkeypatch an immutable argon2 object method and failed (59 other tests passed). The test instrumentation was corrected to replace the module's hasher interface; the complete final run passed. No runtime failure remains in the executed checks.

## Remaining scope and limits

- Complete M2: privileged MFA and secure recovery, audit events, partner data, facilities/warehouses/locations, lot identity and broader account administration. This access slice is not all of M2.
- Email verification is recorded and invitation possession verifies the invited address; it is not yet a universal login prerequisite. The initial password blocklist remains minimal.
- The local mailbox is development delivery only. External mail, durable delivery intent/retry, production TLS/cookie validation and operational deployment remain unconfigured/unverified. APP_ENV=production deliberately refuses startup.
- M3–M7 remain: stock/production, quality/holds, tracing/recall investigation, durable notices/recovery, evidence, complete Core then Expanded workflows, operational/performance/backup validation.
- No full C10 fixture, full browser acceptance suite, workload benchmark, backup/restore exercise, production readiness or final rubric score is claimed.
- Test database recalltrace_test and Redis databases 2/3 remain isolated from development data. Secrets and local mail stay ignored and private.
- Instructor clarification about protected-history CRUD remains pending.

## Next task

Continue M2 with privileged MFA/audit controls and partner/facility/lot master data. Preserve the company constraints, last-owner lock protocol, session revocation, single-use token behavior and protected reference lifecycles. Update this record only from observed implementation and checks.
