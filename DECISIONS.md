# RecallTrace decision log

## Selected product

RecallTrace is the selected course project. ProcureFlow, Meridian and DataSteward were explored but are not the selected implementation.

## Product identity

Preserve recorded batch genealogy, evidence paths and coordinated approved recall actions as the main workflow. General inventory functions support that workflow.

## Stack and baseline

Keep the graded backend in Flask, Jinja and SQLAlchemy with PostgreSQL. The detailed stack and baseline version families are documented. Exact patch compatibility remains a bootstrap verification task. Dependency and environment plan files are not finalized runnable setup files.

## Scope

The full logical design targets 100 related ORM models. Core has 72; Expanded adds 28. Every included model requires a meaningful feature and lifecycle. The original rubric's hard minimum is 40; counts alone do not establish working CRUD or a high grade.

## Integrity

Protected history uses controlled corrections/reversals. Trace scope is conservative unless recorded allocations justify precision. Stale or partial traces do not authorize responses. Company/partner isolation and stock correctness take priority in every release.

## Still to confirm

Exact submission date, weekly availability, named module owners, any hosting budget, and the instructor's protected-record CRUD interpretation. None of these has an invented answer in the supplied files. Continue independent local foundation work while they are pending.

## Later entries

Append material implementation decisions, their reason, affected requirements and verification evidence. Preserve earlier decisions rather than rewriting history to match the current code.

## 31 October 2026 — M1 implementation

- Imported the supplied handoff into the existing `/workspace/Recall-Trace` checkout. Started from an unborn `work` branch with no application or commits; no worktree or remote changes were needed.
- Kept Python 3.13/Flask 3.1/SQLAlchemy 2.0/PostgreSQL 17 as specified. Resolved artifact-hashed runtime/development locks and tested Python 3.13.5, PostgreSQL 17.11 and Redis 7.4.12. Used available `uv` because the host Python lacks ensurepip; setup retains a conventional venv/pip fallback for machines with it installed.
- M1 implements 11 logical model tables, with same-company composite foreign keys and meaningful catalog/access behavior. Deferred `memberships.partner_id`'s FK until M2 introduces partners; every non-null partner restriction denies internal catalog access. No unimplemented table is counted.
- Added explicit `catalog.read` alongside documented `catalog.manage`, so auditor read rights are an actual grant rather than an admin bypass. Seeded catalog editors, not privileged owners; full role administration and owner/MFA workflows remain M2.
- Catalog paths use `/companies/<uuid>/catalog/...` and login uses `/login`; routes are explicitly registered for items, units and variants. This is a naming refinement of the documented route inventory, with UUID converters and the same HTTP/authorization semantics.
- Natural company code/SKU uniqueness prevents duplicate creates. Row locks plus version checks reject stale edits. Do not extrapolate this into stock-posting idempotency or stock concurrency guarantees. Unit dimension/precision become immutable once referenced by a variant; archival preserves existing relationships.
- Implemented Redis sessions/rate counters and a digest-only PostgreSQL auth session registry now. Session touch uses an atomic update to avoid concurrent browser requests conflicting on the registry ORM version. Production deliberately refuses startup until the remaining security/deployment controls are implemented.
- Reserved `.test` identities require syntax validation with email-validator's test environment mode. This is a development-only application; it does not send email or assert verification of those addresses.
- Local Bootstrap 5.3.8 is served without a CDN and includes its license. CSS SHA-256: `d85327d99c7a3ee1f9b5d0500d1370acea3ad2db39c163c2f51f232baedbdede`.
- Verification: PostgreSQL/Redis suite, separate-transaction tests, migration drift check, real Chromium/two-worker HTTP smoke, lint/format, dependency consistency and runtime dependency audit. Actual results and early corrected failures are recorded in STATUS.md. Instructor clarification about protected-history CRUD remains unanswered.


## 1 November 2026 — M2 access slice

- Continued the existing M1 implementation after publication. No environment publication or configuration-draft rewrite was performed.
- Added three implemented Core tables: invitations, password_reset_tokens and email_verification_tokens. Invitation.role_id and revoked_at extend the logical design to bind a grant at issue time and preserve revocation. Partner invitations are deferred; this migration has no dependency on the absent partners table.
- Added the explicit access.manage permission and a local, password-prompted create-owner bootstrap. Subsequent access changes are authorized web operations, with no is_admin bypass. UI membership editing assigns one role at a time. Protected owner role definitions cannot be edited/deleted, and the final active owner is preserved under a company-row lock.
- Role and membership changes invalidate affected users' sessions rather than carry privileged sessions across a grant change. Authentication checks the verified password hash/auth_version under the same user-row lock used for recovery; stale passwords cannot win a reset/login race.
- Account codes are entered in POST bodies, never URLs. Only digests are stored in PostgreSQL. Development messages are written opt-in under the private instance directory, with 0600 files; this is synchronous local delivery without external SMTP or outbox guarantees. Production remains disabled.
- Accepted invitations establish verified email possession. Existing M1 users can verify separately; universal verification enforcement and privileged MFA remain follow-up controls, not completed claims.
- Kept original specification files intact. Current schema/route refinements and evidence are recorded here, README.md and STATUS.md. Full M2/master data, Core scope and rubric minimum remain incomplete.
