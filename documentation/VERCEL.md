# Vercel backend deployment

## Current demonstration path (4 November 2026)

1. Add GitHub repository secrets: `VERCEL_TOKEN`, `SECRET_KEY`, `MFA_ENCRYPTION_KEY`,
   `REDIS_URL` (Upstash TLS URL as copied), `DATABASE_URL` (Supabase transaction
   pooler, restricted runtime role `ROLE.PROJECTREF`), `MIGRATION_DATABASE_URL`
   (session pooler, migration role), `SUPABASE_SERVICE_KEY`, `MAIL_API_KEY`,
   `MAIL_FROM`, `OWNER_EMAIL`, `OWNER_PASSWORD`.
2. Commit Supabase's public root certificate as `certs/supabase-ca.crt`.
3. Run **Actions → Deploy backend to Vercel** with `bootstrap` ticked once; later
   deployments leave it unticked. The job summary prints the production URL and the
   `/health/ready` result.
4. `outbox-worker.yml` drains account/notice intents every five minutes once the
   secrets exist.

Pasted URLs are normalized by `app/vercel.py` (psycopg driver, `verify-full`, bundled
certificate, Redis `/0` with certificate/hostname checks). `SCANNER_MODE=unconfigured`
is the explicit demonstration opt-in described in DECISIONS.md: uploads stay
quarantined and a banner says so. The sections below are the original preparation
notes; where they say a scanner or worker is required, this path supplies the
documented opt-in and the scheduled worker instead.

This deploys the real Flask backend from `index:app`, not the GitHub Pages sample
preview. The normal container entrypoint remains `wsgi:app`. Vercel account
creation does not create this project or copy this workspace's environment
settings to it. The current deployment result is recorded in STATUS.md.

## What is prepared

- `.python-version` selects Python 3.13. `[tool.vercel]` selects `index:app` so the
  existing `app` package and container entrypoint do not cause ambiguity.
- `vercel.json` selects Flask, the Mumbai function region, and a 60-second request
  duration. Vercel must accept the actual account's settings during deployment;
  the configuration is not an entitlement or a capacity test.
- The explicit install command installs the existing runtime requirements with
  hashes and binary wheels. A tooling-only `pyproject.toml` must not cause the
  requirements file to be overlooked by automatic dependency discovery.
- The adapter requires `APP_ENV=production`; all normal production startup gates
  apply. It uses `NullPool` so idle PostgreSQL connections do not accumulate in
  warm functions, a five-second connection timeout, and no automatic prepared
  statements. Use the actual provider pooler and review its connection budget.
- Both Redis clients have three-second connect/socket timeouts and bounded
  pools. Certificate and hostname checks remain required. Session and limiter
  keys retain their separate prefixes in Upstash database 0.
- Files are limited to 4 MiB, with 128 KiB extra request space for multipart form
  data. Uploads, imports, exports and downloads use the same file ceiling.
  Existing larger files are rejected before storage access rather than passed
  to the function response. This conservative bound still needs verification
  against the deployed provider's current request/response limits.
- `.vercelignore` excludes local credentials, virtual environments, private
  reports and development material from CLI uploads. Function exclusions also
  omit operator/development folders. Never upload `.env` or `instance/`.

## Connect the account securely

For API-assisted project creation, create a short-lived token from
[Vercel account tokens](https://vercel.com/account/tokens), scoped to the account
that should own the project. Enter it only in the cloud environment's secure
`VERCEL_TOKEN` field. Its allowed HTTPS destination is `api.vercel.com`. Review,
save and publish the environment when the configuration UI requires it, then
check current readiness before using the API. Do not paste the token into chat.

Use only the free Hobby plan for this university deployment. Do not start a paid
trial, add billing or upgrade automatically. Check Vercel's current eligibility,
usage limits and permitted use; suitability for a university demonstration is
not an uptime commitment for a commercial business.

The project should import `Muhammad-Faizan-1606/Recall-Trace` with the repository
root as its root directory and Flask as its framework. The Vercel account's
GitHub integration must permit access to the repository. A token alone does not
prove that integration access exists. The committed configuration supplies the
install command; do not replace it with an unpinned dependency installation.

## Supply real hosting settings before deployment

Enter actual values in the **Vercel project's** environment settings. Cloud
workspace variables are not automatically present on Vercel. Proxy-backed
workspace values such as `SUPABASE_SERVICE_KEY` and `MAIL_API_KEY` may be
placeholders usable only through the workspace proxy; never copy those
placeholders into Vercel. Enter the real keys privately through hosting settings.

| Setting | Required value |
| --- | --- |
| `APP_ENV` | `production` |
| `SECRET_KEY` | A newly generated random production signing secret, at least 32 characters |
| `MFA_ENCRYPTION_KEY` | A production Fernet key, securely backed up independently |
| `MFA_KEY_VERSION` | `v1` initially; retain it consistently across web and worker |
| `DATABASE_URL` | Restricted runtime role, `postgresql+psycopg://`, actual reachable Supabase endpoint/pooler, `sslmode=verify-full` and a bundled trusted `sslrootcert` |
| `SESSION_REDIS_URL` | Actual Upstash native `rediss://` URL, `/0`, explicit certificate/hostname verification |
| `RATELIMIT_STORAGE_URI` | The same verified Upstash connection; preserve its distinct limiter namespace |
| `ALLOWED_HOSTS` | Exact assigned public hostnames, comma separated; no schemes or wildcards |
| `TRUSTED_PROXY_HOPS` | Explicit reviewed hop count; verify ingress behavior on Vercel before release |
| `STORAGE_BACKEND` | `supabase` |
| `SUPABASE_URL` | `https://cacsvupttgdgcpacddmg.supabase.co` |
| `SUPABASE_STORAGE_BUCKET` | `recalltrace-private` |
| `SUPABASE_SERVICE_KEY` | The actual server-side storage credential, never a browser setting |
| `SCANNER_ENDPOINT` | A real authorized HTTPS malware scanner, or configure a reachable ClamAV service with `CLAMAV_HOST`/`CLAMAV_PORT` |
| `MAIL_MODE` | `resend` |
| `MAIL_API_KEY` | The real Resend sending credential |
| `MAIL_FROM` | A sender authorized for the configured Resend domain |

Package the actual provider's trusted **public** PostgreSQL root certificate in
`certs/`, which the function explicitly includes. Select its bundled path with
`sslrootcert`, and verify the path in the deployed runtime. A certificate is not
a private key; never commit private keys or connection passwords. Do not replace
`verify-full` with `require` or disable verification to bypass a failed handshake.

The scanner and authorized sender are required by the existing backend's
production checks. Missing infrastructure must remain missing; do not insert
dummy endpoints or use the development environment to make the deployment boot.
The real cloud schema is empty and has no public signup. Bootstrap the company
and first owner once from an authorized operator runtime using README's
`create-company`, `create-owner` and `init-business` commands. Do not expose a
public bootstrap/migration endpoint or import the fictional local database.

## Verify the deployment

1. Confirm the reviewed Git commit, Python version, hashed installation and
   successful function build. A source push alone is not a deployment.
2. On the actual backend hostname, `/health/live` must report `alive` and
   `/health/ready` must return HTTP 200 with exactly `{"status":"ready"}`. Readiness
   executes PostgreSQL `SELECT 1` and checks both actual Redis connections.
   A preview response containing `mode=read-only-preview` proves no backend
   connectivity.
3. From an authorized runtime, test the actual Redis binary session round-trip,
   expiry and limiter Lua operations using UUID-prefixed synthetic keys. Delete
   only those keys. Do not run the integration suite against Upstash: its test
   fixtures reset rate storage and use separate local databases 2/3.
4. Verify exact hosts, HTTPS, secure session cookies, proxy behavior, tenant
   isolation, private storage and accepted/rejected/unavailable scanning through
   the real app. Check upload and download bounds on Vercel, including a formerly
   accepted larger object.
5. Run the remaining launch gates in PRODUCTION_LAUNCH.md, including recovery and
   realistic load/connection/quota checks. Local tests are separate evidence.

## Worker and scanner remain separate

Vercel request functions do not run `outbox-run --watch` or a ClamAV daemon.
The committed account-request outbox needs a supervised external worker using
the same database and encryption key. Requests expire after 15 minutes, so an
infrequent cron does not replace this worker. Do not move mail delivery into the
public request, silently drop queued work, or start background threads inside a
request to avoid this requirement. Free worker/scanner hosting remains an
unresolved deployment prerequisite.

Official implementation references reviewed for this configuration:

- [Flask support and example](https://github.com/vercel/vercel/tree/main/examples/flask)
- [Entrypoint configuration](https://github.com/vercel/vercel/blob/main/packages/python/src/entrypoint.ts)
- [Python versions](https://github.com/vercel/vercel/blob/main/packages/python/src/version.ts)
- [Manifest selection](https://github.com/vercel/vercel/blob/main/packages/python-analysis/src/manifest/package.ts)
- [Python build and install commands](https://github.com/vercel/vercel/blob/main/packages/python/src/index.ts)
- [Seeded installer environment](https://github.com/vercel/vercel/blob/main/packages/python/src/utils.ts)

Current account-specific plan limits, ingress behavior, build packaging and live
connectivity still require the real provider deployment; source inspection does
not establish those results.
