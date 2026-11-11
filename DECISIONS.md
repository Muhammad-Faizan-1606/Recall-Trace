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

## 4 November 2026 — Upstash connection and scanner sizing

The user selected Upstash and confirmed an account without a database. Use the dashboard's explicit Free database route and only its native TCP/TLS connection credentials, avoiding an unnecessary account-wide management key. Configure both backend stores against database 0 with existing distinct prefixes, verified TLS and hostname checks. These are direct process settings, not HTTP-only proxy credentials; the public static preview does not use them. Preserve local/test Redis and never flush a remote store for connectivity checks. Native authentication, expiry/session round-trip and Lua verification remain pending the actual endpoint, credentials and supported network access.

Worker/scanner sizing is planning guidance, not a measured capacity claim. The sequential outbox worker is lightweight; ClamAV's official Docker guidance specifies 3 GiB minimum and 4 GiB preferred for the scanner alone because signature loading/reloading consumes memory. A modest 2-core, 6–8 GiB combined Linux host with operating-system headroom is a reasonable small-pilot target; no GPU is required. Continuous availability and private/authenticated scanner access matter alongside hardware.

## 4 November 2026 — Vercel university demonstration deployment

Deadline-driven decision by the owner: deploy the real Flask backend to Vercel (Hobby) for the course demonstration. The owner configured Resend, so mail remains strictly required. No free malware-scanner hosting exists, so the owner chose an explicit `SCANNER_MODE=unconfigured` opt-in. It is the only relaxation: production still refuses to start without it, refuses it when a scanner *is* configured, and keeps every upload quarantined because `scan_bytes` returns `unavailable`. A visible banner states this on every page. Download/acceptance of evidence therefore cannot be demonstrated live; it remains covered by the scanner-injected tests.

Deployments run from the manual `deploy-vercel.yml` GitHub Actions workflow, with values held as GitHub repository secrets and passed as per-deployment Vercel variables. Vercel Git auto-deployments are disabled so a build without those settings cannot replace production. The adapter derives the allowed host from Vercel's `VERCEL_PROJECT_PRODUCTION_URL`, adds `verify-full` plus the bundled public Supabase root certificate to a pasted pooler URL, and adds certificate/hostname verification to a pasted Upstash URL; explicitly weaker settings are preserved so validation rejects them.

The workflow's optional bootstrap job is the authorized operator runtime: it applies migrations, creates the company/owner/permissions and seeds the fictional C10 investigation (development mode on the runner only, so the fixture's development guard is unchanged). `outbox-worker.yml` runs a bounded `outbox-run` every five minutes as the supervised external worker; GitHub schedules are best-effort, so a delayed run can let a 15-minute account request expire but cannot send it twice. This is a university demonstration, not a business uptime or security certification.

## 4 November 2026 — Interface design system

Owner request: a more professional, user-friendly interface that does not look generated, with practicality first. Direction taken from the subject (factory quality control and warehouses) rather than generic SaaS defaults, after reviewing published guidance on the common tells of generated interfaces (cream/terracotta palettes, identical shadowed cards, all-caps eyebrows, "A · B · C" meta strings, decorative gradients):

- Palette: cool paper grey background, white surfaces, slate ink, one signal blue for actions and links. Status colours follow physical quality tags: green released/complete, amber held/waiting, red failed/severe, grey neutral.
- Type: IBM Plex Sans (400/500/600) bundled locally under its SIL Open Font License (`app/static/vendor/fonts`), because the strict CSP blocks external fonts. Tabular numbers in tables.
- Layout: app shell with a grouped left sidebar (Recall; Stock and quality; Records; Administration) and current-page highlighting; a horizontally scrolling strip on phones. Compact tables, neutral secondary buttons, no decorative shadows.
- One distinctive element: status tags shaped like hanging inspection tags. The sign-in page explains the product in one sentence beside a small C10 → L1/L2 → shipped diagram.
- Quantities display without storage padding (50.000000 → 50) through a `qty` filter; stored Decimal values are unchanged.

Templates keep every link name and flow, so the change is presentational. The separate read-only preview keeps its own stylesheet.

## 11 November 2026 — Request performance

Measured on the live deployment before the change: about 8.7 s on a cold start, about 1.0–1.2 s for a warm sign-in page (0.43 s of that network), static files served through the Python function with `Cache-Control: no-store`, and 14–22 database queries per signed-in page.

- Static assets get content-hashed URLs and a one-year immutable policy so Vercel's CDN serves them. Static requests skip the server-side session and the rate limiter, so they make no Redis or database call and set no cookie. Pages keep `no-store`.
- Every response carries `Server-Timing` (database time and query count, connection time, Redis time and calls, total). Requests over one second are logged with that breakdown. Only durations and counts are exposed.
- Session activity ("last seen") is written at most once a minute. The per-request SELECT still enforces revocation, expiry, account version and the 30-minute idle limit, so idle expiry keeps one-minute precision.
- Membership and permission codes are read once per request and cached in the request only. The cache is discarded when the company lock is taken and on every commit or rollback, so locked mutations still re-check authorization under the lock.
- Lot names are cached per product variant within a request (removes an N+1).
- Vercel uses a small bounded SQLAlchemy pool (2 + 3 overflow, pre-ping, 120 s recycle) through the Supabase transaction pooler instead of a new TLS connection per request, with Fluid compute enabled so warm instances are reused. Alembic loads only outside Vercel request functions.

## 11 November 2026 — Malware scanner on an Azure VM

The owner has Azure for Students credit. ClamAV needs about 1.2 GB of RAM for its signatures, so the scanner runs on a B1ms-class VM (2 GB) rather than the free 1 GB size or a serverless function. Microsoft Defender malware scanning was not used because it scans only Azure Storage, and evidence lives in Supabase storage.

The VM runs a standard-library HTTP service in front of the local ClamAV socket, with Caddy providing automatic HTTPS. Because the endpoint is public and Vercel has no fixed outbound IP to allowlist, the service requires a bearer token (`SCANNER_TOKEN`, at least 32 random characters, compared in constant time). Production now refuses an HTTPS scanner endpoint without a strong token. Any non-definite outcome (wrong token, ClamAV down, malformed reply) is reported as unavailable, so files stay quarantined. The deploy workflow enables scanning only when both `SCANNER_ENDPOINT` and `SCANNER_TOKEN` secrets exist; otherwise it keeps the explicit `SCANNER_MODE=unconfigured` opt-in.

## 11 November 2026 — Operating-system security updates in images

CI's Trivy scan began failing after new Alpine advisories (zlib in both images; krb5-libs and libxslt in the database-tools image), all with fixed packages available. Python dependencies had no findings. Both images keep their digest-pinned bases and now run `apk upgrade --no-cache` at build time, so published distribution fixes are applied without waiting for a new base digest. No findings are suppressed.

## 11 November 2026 — Dark console redesign

Owner request: a more engaging, easy-to-navigate interface inspired by dark product dashboards (teal-glow and violet-glass task boards) and the Tranquil site (near-black, DM Sans-style headlines, pill buttons). Implemented as a dark-first theme with a light theme toggle (saved per browser, applied before paint by a same-origin script, so the strict CSP is unchanged):

- DM Sans (400–700) bundled locally under the SIL Open Font License; IBM Plex removed.
- Lucide icons (ISC) as a 28-symbol local SVG sprite.
- App shell: fixed sidebar with icons, company switcher and profile card with sign-out; sticky top bar with greeting, date, global search (press "/" to focus) and the theme toggle; on phones the sidebar becomes a slide-out drawer (Escape closes it).
- New company-scoped search across investigations, lots, items, partners, quality issues and shipments, with LIKE wildcards escaped.
- Design tokens for both themes; semantic status colours unchanged in meaning. The read-only preview omits the theme toggle because its pages must expose only disabled buttons.

## 11 November 2026 — "Recall desk" redesign replaces the dark console

Owner feedback: the dark console still read as generic AI-generated UI and was not easy enough to understand. The owner pointed to four public anti-slop design guides (Vanszs/Anti-AI-UI, pbakaus/impeccable, Leonxlnx/taste-skill, nextlevelbuilder/ui-ux-pro-max-skill). Their shared list of tells matched the previous design: dark by habit, an accent glow, pill buttons everywhere, a "Welcome, name" greeting, and gradient big-number tiles. The redesign follows their rules for data-dense operational tools:

- Theme is chosen from the use scene. Investigators work in offices and warehouses during the day, so light (warm paper surfaces, ink text) is the default. Dark follows the operating-system setting or the toggle, uses warm neutrals and has no glow.
- One accent (ink blue), used only for actions, the current navigation item, focus rings and the current progress step. Green, amber and red are reserved for status, and the written status always accompanies the colour.
- Two type families: Bricolage Grotesque (600, SIL OFL, bundled locally) for page and section titles only; DM Sans for everything else, with tabular figures.
- Small radii (6px controls, 8px panels), border-only panels with no shadows and no nesting, rectangular buttons, and transitions of colour only. `prefers-reduced-motion` disables all transitions.
- Signature element: status tags styled as printed quality labels (square swatch plus label).
- Navigation and structure:
  - The greeting is replaced by a company / section breadcrumb.
  - Items, Variants and Units are one Catalog entry with tabs.
  - Every list page has the same header (title, one-line purpose, primary action on the right).
  - The Overview shows a plain facts line and tables instead of hero tiles, and groups activity by day.
  - The investigation page uses two columns: evidence on the left, and a sticky rail with next step, progress and key facts on the right. On phones the rail comes first.
  - Master data and Operations show a grouped directory with one-line explanations instead of an identical card grid.
  - The quality dashboard uses tables with jump links.
- No change to routes, permissions, forms or business rules. Visible wording that tests and the presenter guide rely on is unchanged.

## 11 November 2026 — Owner-supplied logo

The owner supplied the RecallTrace logo: a running coral "R" with a mint trace path and a location pin, beside a navy and coral wordmark. It was cut from the supplied image with a colour-preserving matte (no redrawing) and served as local WebP assets under `app/static/brand/`. A dark-theme copy swaps only the navy ink for a light ink so the wordmark stays readable. It is used in the sidebar, the sign-in page and the phone top bar (mark only); the 32px favicon and the 180px home-screen icon use the mark on the logo's cream background. The interface accent stays ink blue: the logo's coral is close to the red used for failed and severe status, so it remains a brand colour only.
