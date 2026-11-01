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
