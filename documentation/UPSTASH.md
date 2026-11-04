# Upstash Redis setup

RecallTrace uses Redis for server-side sessions and shared rate limits. The public GitHub Pages preview is read-only and does not use Redis; this setup prepares the full backend, which is not publicly deployed yet.

## Create the free database

1. Sign in to the [Upstash Console](https://console.upstash.com/redis).
2. Select **Create Database**, name it `recalltrace`, and explicitly choose **Free**. Choose one primary region near the intended backend; additional read regions are unnecessary for the current deployment.
3. Keep TLS enabled. Do not select PAYG, a fixed paid plan, an automatic paid upgrade or a production-pack add-on.
4. Open the database's **Connect → TCP** section. Use the full-write `default` connection, not `default_ro` and not the REST SDK settings.

The console's **Token is the database password**. The read-only token cannot store sessions or update rate counters. Copy the TCP connection URI privately; never paste it into chat or commit it.

The documented Free allowance is one database, 250 MB of data, 500,000 commands/month and 10 GB/month bandwidth. Check the console's current entitlement before creating it. Adding a payment method converts the account's free resources to paid plans; retain the zero-budget constraint and do not add billing merely to complete this setup. See [official pricing documentation](https://github.com/upstash/docs/blob/main/redis/overall/billing.mdx).

## Configure both application settings

Upstash supports **only logical database 0**. Use the same TLS connection in both secure runtime settings:

```text
SESSION_REDIS_URL=rediss://default:URL_ENCODED_TOKEN@YOUR_ENDPOINT:YOUR_PORT/0?ssl_check_hostname=true&ssl_cert_reqs=required
RATELIMIT_STORAGE_URI=rediss://default:URL_ENCODED_TOKEN@YOUR_ENDPOINT:YOUR_PORT/0?ssl_check_hostname=true&ssl_cert_reqs=required
```

The values above are templates, not working credentials. Prefer the URI from **Connect → TCP** and ensure it uses `rediss://`, `/0` and both certificate-verification query options. If constructing it manually, URL-encode the password component rather than the entire URI; do not double-encode an already encoded password. If the copied URI already contains query options, append the verification options using `&`.

Enter the real values through secure environment/hosting settings. They are direct process connection settings for a native TCP client, not HTTPS proxy credentials. Keep the URI out of HTML, browser code, source control, command arguments and logs.

The existing app already separates session keys (`recalltrace:`) from rate-limit keys (`LIMITS:`). Sharing database 0 therefore requires no new tables or prefix changes. The REST endpoint/token settings are for HTTP clients and cannot replace these Redis protocol URLs. See [official client connection instructions](https://github.com/upstash/docs/blob/main/redis/howto/connect-client.mdx) and [database selection](https://github.com/upstash/docs/blob/main/redis/commands/connection/select.mdx).

Preserve the local development Redis URLs in `.env` and the dedicated integration-test Redis databases 2/3. Do not point the test suite at this remote database or flush it to test connectivity.

## Verify before activating the backend

After the connection is supplied, verify native TCP/TLS authentication, a uniquely named expiring test key, binary session round-trip, expiry and the rate limiter's Lua operations; delete only the test keys. Certificate and hostname verification must remain enabled. Upstash documents [EVAL](https://github.com/upstash/docs/blob/main/redis/commands/scripting/eval.mdx) and [EVALSHA](https://github.com/upstash/docs/blob/main/redis/commands/scripting/evalsha.mdx), which the rate-limit library uses.

The managed environment currently has no outbound TCP grants. Native verification may require the provider hostname/port to be allowed through its supported network configuration, or execution from the authorized backend runtime. An HTTP/REST `PING`, a saved URI or a populated environment field does not prove the application's native Redis connection works.

Free database inactivity/availability and command quotas still need monitoring. Keep Redis failures fail-closed and include the session/rate stores in deployed readiness checks. This setup does not supply the background worker, malware scanner, authorized email sender or the remaining production acceptance checks in [the launch record](PRODUCTION_LAUNCH.md).
