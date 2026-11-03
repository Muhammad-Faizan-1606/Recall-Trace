# RecallTrace implementation status

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
