# Production launch record

This is the remaining deployment work for the 72-model Core release. Local tests and scans are recorded in SECURITY_REVIEW.md; they do not establish that the external services below work. No public production URL has been created or verified from this environment.

The owner also selected Vercel for the backend and has created an account. [Vercel preparation](VERCEL.md) is committed separately from the static frontend preview: it keeps the real production gates, adds bounded serverless connections and limits files to 4 MiB. Vercel project creation/deployment remains blocked on secure account access and actual hosting prerequisites. Its `VERCEL_TOKEN` requirement and `api.vercel.com` destination were saved to the cloud environment draft; they are not yet applied or authenticated. The matching Upstash runtime URLs now pass offline syntax/TLS-option checks, but native connectivity remains unverified.

## Verified progress — 4 November 2026

Render, Supabase and Resend management credentials are active and authenticated API inventories succeeded. The existing dedicated Supabase project `Recall Trace` (`cacsvupttgdgcpacddmg`, PostgreSQL 17.11, Mumbai region) now has 72 Core tables plus Alembic metadata at `c72a03`. Separate migration/runtime logins and application grants were provisioned atomically. A fresh read-only cloud check executed 70 catalog queries and returned no findings; all 72 business tables are empty. No fictional seed or existing development history was copied. Native PostgreSQL login/TLS from the deployed web service remains unverified.

Provider database TLS enforcement is enabled and read back as applied successfully. The application `public` schema is no longer exposed by the Data API or present in its extra search path; existing `graphql_public` and `extensions` settings remain. Direct application-table API grants are revoked. Native runtime connections and anonymous external API checks still need to be exercised after the remaining service access is available.

The reviewed Supabase automatic-RLS event trigger is preserved. This backend uses Flask authorization and restricted database grants; RLS was disabled only on its 73 new application objects so the backend can operate. The access tool now requires an explicit opt-in and exact provider metadata/source hashes to accept that provider function; other public definer functions/views remain blocked. See DATABASE_ACCESS.md for the boundary.

The existing unrelated suspended Render application was left unchanged; there is no RecallTrace web service yet. Resend reports no sending domains. [Hosted CI passed for the provider-policy commit](https://github.com/Muhammad-Faizan-1606/Recall-Trace/actions/runs/41807505023), including the complete suite, both Python dependency audits and both container vulnerability scans. The provider-specific access tool also passed 41 local tests in 5.59s after environment restoration.

The real storage credential is now active. Created the private `recalltrace-private` bucket with a 10 MiB limit and `application/octet-stream` uploads, matching the server adapter. The actual application adapter uploaded and downloaded a harmless synthetic PDF with matching bytes/checksum; an incorrect digest was rejected. Both anonymous private-object and public-object requests were denied (HTTP 400), and the exact disposable object was deleted and its absence independently verified. No Document/business row was created. The unconfigured scanner correctly returned `unavailable`; no file was marked clean or released. A sanitized report is retained privately in `instance/production/storage-report.json`.

These checks establish storage connectivity, integrity and provider privacy. Deployed tenant authorization, persistence through a web-service replacement, scanning and full evidence recovery remain unverified.

## Connected secure settings

The following credentials are connected; keep them in secure settings:

| Secure setting | Used for | Obtain privately |
| --- | --- | --- |
| `RENDER_API_KEY` | Inspect/configure the owner's Render services | Render account API-key settings |
| `SUPABASE_ACCESS_TOKEN` | Inspect/configure Supabase projects | Supabase account access-token settings |
| `MAIL_API_KEY` | Inspect the authorized Resend account/sender | Resend API-key settings; use permissions appropriate to the operation |
| `SUPABASE_SERVICE_KEY` | Server-side private-storage operations; verified against the real bucket | The dedicated Supabase project's server service-role key, entered securely |

Enter these values in environment settings, never chat, source, issues or logs. These setup/API credentials are separate from the application's PostgreSQL password, Redis password and storage service key. Proxy-backed credentials must be used through their configured HTTPS API destinations; their local placeholders are not credentials to copy into provider runtime settings.

The four API destinations `api.render.com`, `api.supabase.com`, `api.resend.com` and `api.github.com`, plus the project storage hostname `cacsvupttgdgcpacddmg.supabase.co`, are active. `SUPABASE_SERVICE_KEY` was supplied through a secure binding; no existing service-role key was downloaded or stored locally. Proxy placeholders remain usable only at their configured API destinations and must not be copied into Render runtime settings. A draft save does not itself apply network changes or create a deployment.

## Zero-budget deployment constraints

Retain the zero-budget requirement. Inspect available regions, quotas, expiry and current free eligibility before creating resources. Do not accept a paid plan or silently upgrade resources. An existing account does not establish an available free service.

The web blueprint only declares a Render web service. Automatic account recovery and verification require a continuously supervised outbox worker with the same database, keys and mail settings. A scanner is also required to release uploaded evidence from quarantine. Select hosting for both and verify that it remains running independently of web requests. Manual drains and an operator laptop can support a university demonstration; they do not establish continuous business availability.

The owner has neither a university VM nor a computer that can remain running. A suitable free provider for worker/scanner compute is therefore still required. Render Key Value/Redis inventory endpoints returned a provider Cloudflare 403 while service inventory worked; this does not establish an invalid credential or usable free TLS Redis capacity. No paid worker, scanner or plan upgrade was created.

Resend still needs an authorized sender on a domain whose DNS the owner controls. Gmail can receive messages; a Gmail inbox alone cannot authorize sending from `gmail.com` through Resend. A paid business mailbox is not required merely to verify a domain. No real test email or recall communication was sent.

An authenticated TCP/TLS Redis service is still needed for sessions and rate limits. A REST-only cache endpoint does not satisfy this application. Verify its connection, available database numbers and limits before filling the two Redis settings; the application supports separate key prefixes on a shared Redis database.

## Release gates

These gates require verification on the actual deployment. Database schema/ACL checks, provider storage connectivity/privacy/integrity, and the linked hosted CI run above are completed portions; native application connectivity and the remaining end-to-end gates are pending. Record the real result, date and reviewed source/image reference as each gate is completed; do not mark a gate passed because an environment variable is present.

| Gate | Required evidence |
| --- | --- |
| Database | Verified TLS connection, migrations through the current head, dedicated migration/runtime roles, runtime privilege check passed, and unused Supabase Data API access disabled or separately reviewed, including RPCs/views. See DATABASE_ACCESS.md. |
| Redis | Authenticated verified TLS, shared sessions/rate limits across web processes, safe behavior during a connection failure. |
| Private storage | Bucket is private; authorized upload/download works; cross-company access fails; checksums match after a web replacement. |
| Scanner | Known clean fixture accepted, harmless recognized test signature blocked, unavailable scanner keeps the file quarantined. Use an authorized scanner test environment. |
| Email and worker | Authorized sender, explicit test recipient, actual account recovery/verification processed after commit, stopped/restarted worker behavior checked. Do not send real recall communications for this exercise. |
| Public ingress | HTTPS, exact host/proxy configuration, Secure cookies, security headers and readiness verified at the actual public hostname. |
| Business acceptance | Stock conservation, held-stock rejection, tenant/partner isolation, trace inclusion/exclusion, independent approval and recovery demonstrated by intended users. |
| Recovery | Off-host database and evidence backups plus separate key recovery; restore all three to an isolated installation and verify checksums, access and trace results. Record recovery time and restored-data age. |
| Operations | Process restarts, failure/queue/backup/quota alerts, named operator, retention policy and rollback procedure checked. |
| Capacity and release | Realistic expected load measured; hosted CI and fresh scans pass; provider connection/memory/storage limits fit the intended workload. |

## Deployment sequence

1. Connect the secure API access above and inspect the existing accounts/resources.
2. Select free-eligible database/storage, Redis, worker/scanner and web capacity; resolve any resource that cannot satisfy the requirements within the budget.
3. Protect database access using the dedicated-project procedure in DATABASE_ACCESS.md, apply migrations once with the migration account, then use the restricted runtime account for web and worker.
4. Configure verified connections, private storage, scanner, sender and independent signing/encryption secrets. Keep key recovery material separate and local mail disabled.
5. Deploy the reviewed application and worker. Bootstrap the real company/owner with the supported interactive commands, enable MFA and assign minimal roles. Do not import the fictional development database or seed records.
6. Execute the release gates with authorized synthetic records before admitting real operational data. Keep any failed or unrun gates explicit.

DEPLOYMENT.md contains the exact settings, migration, worker and database backup commands. Production clearance remains pending until the deployed gates pass and an operator accepts the service's documented limits.
