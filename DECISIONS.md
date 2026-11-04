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

## 3 November 2026 — Final Core scope and deployment boundary

The user selected exactly 72 Core models as the final release, excluded the original 28 Expanded models, and specified a university project with no hosting budget and business-quality behavior. The active instructions/plan/handoff now reflect this choice; original specifications and rubric are retained as references. The executable table inventory is checked against the exact Core set.

Core operational writers share a company-row transaction guard before current authorization and per-record/lot reads. This intentionally favors understandable stock/hold/trace/access serialization over maximum per-company throughput. Membership identity-map refresh prevents cached partner/status flags from bypassing a concurrently committed revocation. Posted business documents/lines, journal, audit, quality snapshots and trace snapshots receive database guards in addition to service checks. Receipt/transfer correction uses a compensating journal event; arbitrary retroactive production/dispatch rewrites are unavailable.

Recall approval requires a current, complete downstream trace and an independent recently MFA-verified reviewer. Approved cases cannot compute replacement operational scope; reopening preserves holds and requires retracing/submission/independent reapproval. Approval time also bounds the accepted snapshot. Recovery references provide repeat-payload checking, and acknowledgement remains distinct from verified physical resolution.

The Core delivery runner claims committed PostgreSQL outbox records directly. A Celery broker/always-on worker is not required for a local demonstration; free hosting must not silently depend on a paid background-worker feature. The runner supports bounded manual drains and separately supervised watch mode. Inactive companies fail queued work safely; ambiguous external attempts require independent evidence-backed reconciliation. Real mail/storage/scanner adapters remain unconfigured until provider authorization can be tested. Local mailbox writes are marked local_written, never external delivery.

Trace visualization uses a bounded server-rendered SVG plus an accessible evidence table, preserving Flask/Jinja and the complete authorized server result without a CDN or additional browser dependency. Partial computations never authorize operational decisions; quantities remain separated by SKU/base unit.

The initial MFA dependency selection was rejected by the final vulnerability audit. The lock was updated to cryptography 50.0.2 with verified artifact hashes; the runtime audit then reported no known vulnerabilities. This is an observed dependency check, not security certification.

Render web, Supabase PostgreSQL/private storage, authenticated TLS Redis, Resend and a trusted scanner form the documented deployment path. No provider accounts, credentials, public database or site have been provisioned. Production configuration rejects insecure/missing connections, public storage, missing scanner/mail and relaxed cookies. Non-root image/local database verification is separate from live deployment validation. Free tiers do not establish an always-on business service, backup guarantee, legal retention policy or SLA. Database backup/restore verification excludes external evidence bytes and encryption-key recovery.

## 3 November 2026 — Adversarial review and security regressions

A local defensive review expanded validation to 307 cases, including malformed input, distributed authentication guessing, role/action boundaries, stale operational parents, private metadata, redirecting providers, corrupt worker payloads, external-I/O locking, overlapping physical recovery and unsendable notice withdrawal. Fixes preserve CSRF/MFA/tenant/transaction controls; no schema expansion was needed. Shared recovery evidence retains its original company/case/reference and resolves physical units once across overlapping scopes. Never-sent notices may be independently withdrawn with recent MFA; processing/ambiguous/sent attempts remain protected.

The final image removes unneeded installers and prevents UID 10001 from modifying source. Trivy still reports nine distinct HIGH Debian CVEs with no vendor fix; they are not suppressed or described as harmless. Source-level and dependency checks are not a full production clearance. See documentation/SECURITY_REVIEW.md for evidence and remaining limits.

## 3 November 2026 — Container and account-delivery remediation

The preceding Debian advisory record is historical. Replace the default web base with supported, digest-pinned official Python 3.13 Alpine and install the existing hash-locked native musllinux wheels. Keep PostgreSQL administrative clients in a separate digest-pinned official PostgreSQL 17 Alpine tools target. This avoids carrying unrelated OS/backup packages in the web runtime, preserves host-operated backup/restore, and needs no additional APK download destination. Package inventories remain intact; both final images returned zero Trivy findings at all severities without exclusions. Native crypto, content validation, real database/cache readiness and populated backup/restore were verified. Future advisories still require rebuilding and rescanning.

Public recovery/verification must not branch on account eligibility or provider latency. Persist the same encrypted request for every syntactically valid address; a separately supervised outbox worker checks current eligibility and sends after committing the challenge digest and releasing locks. Raw challenge codes exist only in worker memory/private delivery, never in the outbox. HKDF separates encryption and pseudonym keys from the existing MFA key; versions, authenticated payload binding, short queue TTL and per-recipient/purpose serialization govern rotation, supersession and consumption. Ambiguous/abandoned account attempts are not automatically resent; users submit fresh intent. Existing authenticated invitations remain direct delivery because they do not perform the public eligibility branch.

Reuse `job_outbox` to preserve the agreed 72 models. Migration `c72a03` permits a NULL company only for actor-free `account.challenge` system rows, enforced by a database CHECK and partial indexes; all other jobs require their company and scoped company UI/retry paths exclude global jobs. This is a deliberate bounded exception to company-owned job rows, not removal of tenant authorization. The downgrade refuses to erase existing system/security history. Tests and independent review support the change; shared database contention prevents a formal constant-time claim. The mail worker is now a required startup process for automatic recovery/verification, and its keys/settings must match the web process.

Final local validation: 343 tests with deprecations treated as errors, three browser workflows, clean runtime/development lock audits, application static analysis and both exact-source image scans. See documentation/SECURITY_REVIEW.md for hashes and evidence; provider deployment, always-on free hosting and external evidence/key disaster recovery remain separate operational work.

## 3 November 2026 — Dedicated production database access

The user requested hands-on production deployment and confirmed Render, Supabase and Resend accounts. Access is not connected; save secure API requirements and explicit external release gates rather than inventing provider resources or claiming deployment. Preserve zero budget, and inspect free eligibility before provisioning; continuous worker/scanner hosting and Redis remain unresolved.

Implement host-only database ACL provisioning and read-only verification in `operations/`, outside Docker COPY paths, to prepare the separate runtime/migration roles required by the deployment guide. Require explicit dedicated-database acknowledgement, exact current object ownership/inventory and atomic verification; never create/change passwords or alter business rows. Revoke direct API/public/column/default grants, prevent runtime DDL/escalation, and preserve immutable triggers. Three existing history workflows require `SELECT FOR UPDATE`; grant only `UPDATE(id)` on stock_transactions, trace_runs and case_comments and verify their unconditional enabled history guard, so actual mutation remains forbidden. Unexpected public views or definer functions require review; this is not tenant RLS or a substitute for disabling/reviewing Supabase Data API exposure and other schemas. Nineteen isolated PostgreSQL tests and independent review support the policy. Existing application data/grants and scanned web image inputs are unchanged.

## 4 November 2026 — Actual Supabase provisioning and provider policy

The user connected management API access. Reuse the existing empty dedicated Recall Trace Supabase project rather than creating another project or altering an unrelated Render app. Apply the reviewed 72-model migrations and new separate migration/runtime roles atomically through the authenticated management API. Do not reset the existing provider PostgreSQL password, copy fictional business data or create paid resources. A fresh live catalog verification passed 70 queries with zero findings; native runtime login/TLS is a separate unverified gate.

The provider installs `public.rls_auto_enable()` as a security-definer event-trigger function. Its event-trigger return type prevents ordinary RPC invocation. Preserve that provider object and recognize it only behind an explicit operator flag with exact raw/normalized source hashes, owner/language/search-path checks and the single canonical event-trigger attachment; arbitrary definer routines remain rejected. Automatic RLS on the 73 newly migrated backend objects was deliberately disabled because the current backend uses Flask authorization and exact object grants, with API/public defaults revoked. This is not a claim of tenant RLS or generic acceptance of provider-definer functions. Forty-one local regression cases and independent review cover the exception.

Keep storage credentials in secure bindings/provider settings; no existing service-role key was downloaded. The user has no always-on local/university host and Resend has no sending domain. Worker/scanner capacity, verified TCP/TLS Redis, sender authorization, storage persistence and full recovery/operational acceptance remain external prerequisites to production clearance.

Enable the dedicated project's database TLS enforcement and remove only the backend application schema `public` from the Data API's exposed schemas and extra search path, preserving the existing provider schemas. Read back both settings before recording them as applied. This hardens the remote database without treating management-API catalog verification as proof of native runtime TLS, external anonymous authorization or a public application deployment.

## 4 November 2026 — Real private-storage verification

Use the newly supplied secure storage binding directly at its allowed project hostname; do not download a privileged service-role key or persist its value. Create a private bucket with the same 10 MiB bound as the application and allow the server adapter's `application/octet-stream` content type. A PDF/JPEG/PNG-only bucket header allowlist would reject the existing adapter even when its validated bytes are legitimate; content validation and mandatory scanning remain application controls.

Verify the real adapter with one harmless disposable object, matching bytes/digest, rejected integrity mismatch, denied anonymous object routes and independent cleanup confirmation. Do not create accepted Document rows or substitute a clean scanner. These checks passed and the object was removed. Record the result as storage-provider connectivity/privacy/integrity only; deployed tenant behavior, scanner operation, evidence persistence through web replacement and full recovery still require their own acceptance checks.

## 4 November 2026 — Public frontend preview before production launch

The user explicitly requested deployment now to see the frontend and deferred the remaining infrastructure. Deploy a separate read-only preview with bundled fictional sample views rather than relaxing the production factory's requirements or exposing real data. Preserve the complete Flask/Jinja/PostgreSQL application; the default `wsgi:app` entry point and production blueprint remain unchanged. The preview uses its own explicit opt-in, trusted hostname, security headers and GET-only routes, with no login, production extensions, provider credentials or active data-changing controls.

Use a separate free Render web service and command override, one Gunicorn worker, and no automatic redeploy until reviewed. Existing unrelated services remain untouched. The preview demonstrates navigation, C10 trace scope and representative screens; it does not claim functional production delivery, scanning, persistence or recovery. Local verification passed 36 isolation/security cases plus actual desktop/mobile browser navigation. Continue the real deployment through the existing production launch gates when its external prerequisites are supplied.

Render's actual free-service request required billing information (HTTP 402), so preserve the zero-budget constraint and prepare GitHub Pages static publishing instead. Render's server deployment option remains available for later; no service or paid resource was created. Export the same fictional Jinja views with the repository URL prefix and approved public assets only. The exporter rejects symlinks, unsafe prefixes and nonempty output directories. Keep the original application source/configuration/database out of the artifact.

The connected GitHub integration cannot enable Pages (HTTP 403) even though the owner has repository administration. Use the supported one-time owner setting, Source → GitHub Actions; do not attempt to bypass the permission with the workflow token. The official configure-pages action requires a different appropriately privileged token for enablement, while normal deployment can use the workflow's narrowly scoped Pages/OIDC permissions after the owner enables it. The build artifact is prepared before this provider gate, so the owner can review a concrete tested result.

After the owner enabled the Pages source, rerun the authorized publishing workflow and verify success plus the provider's actual HTTPS URL. The frontend was published at https://muhammad-faizan-1606.github.io/Recall-Trace/ from tested source `fae81b8`. Keep it publicly read-only with fictional data, no login and no production credentials. Provider deployment and local browser proof do not substitute for an unexecuted public-browser check or completion of the separate production backend.
