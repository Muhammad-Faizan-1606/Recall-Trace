# Production launch record

This is the remaining deployment work for the 72-model Core release. Local tests and scans are recorded in SECURITY_REVIEW.md; they do not establish that the external services below work. No public production URL has been created or verified from this environment.

## Access needed to continue

The owner confirmed existing Render, Supabase and Resend accounts. Their projects, quotas and configuration have not been inspected because no provider access is connected. Secure credential requirements are saved in the cloud environment draft:

| Secure setting | Used for | Obtain privately |
| --- | --- | --- |
| `RENDER_API_KEY` | Inspect/configure the owner's Render services | Render account API-key settings |
| `SUPABASE_ACCESS_TOKEN` | Inspect/configure Supabase projects | Supabase account access-token settings |
| `MAIL_API_KEY` | Inspect the authorized Resend account/sender | Resend API-key settings; use permissions appropriate to the operation |

Enter these values in environment settings, never chat, source, issues or logs. These setup/API credentials are separate from the application's PostgreSQL password, Redis password and storage service key. Proxy-backed credentials must be used through their configured HTTPS API destinations; their local placeholders are not credentials to copy into provider runtime settings.

The draft includes API destinations `api.render.com`, `api.supabase.com`, `api.resend.com` and `api.github.com`. A draft save is not an applied network change, account connection, resource creation or deployment. Review/save environment settings and publish the prepared environment when appropriate. GitHub source push works; the Actions API request was forbidden in the current runtime, so no successful hosted CI run is claimed.

## Zero-budget deployment constraints

Retain the zero-budget requirement. Inspect available regions, quotas, expiry and current free eligibility before creating resources. Do not accept a paid plan or silently upgrade resources. An existing account does not establish an available free service.

The web blueprint only declares a Render web service. Automatic account recovery and verification require a continuously supervised outbox worker with the same database, keys and mail settings. A scanner is also required to release uploaded evidence from quarantine. Select hosting for both and verify that it remains running independently of web requests. Manual drains and an operator laptop can support a university demonstration; they do not establish continuous business availability.

An authenticated TCP/TLS Redis service is still needed for sessions and rate limits. A REST-only cache endpoint does not satisfy this application. Verify its connection, available database numbers and limits before filling the two Redis settings; the application supports separate key prefixes on a shared Redis database.

## Release gates

Every row below remains unverified on external infrastructure. Record the real result, date and reviewed source/image reference as each gate is completed; do not mark a gate passed because an environment variable is present.

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
