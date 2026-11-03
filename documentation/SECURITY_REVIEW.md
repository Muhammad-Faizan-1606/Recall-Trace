# Security remediation review — 3 November 2026

The two follow-ups from the earlier review are addressed: the shipped images use supported Alpine bases without the affected Debian packages, and public account recovery/verification requests enqueue encrypted intent before any account lookup or mail transport. The application still has exactly 72 Core models. This is local verification, not certification or proof that no vulnerabilities remain.

## Current verification

| Check | Observed result |
| --- | --- |
| Complete PostgreSQL/Redis suite | **343 passed in 131.02s**, deprecations treated as errors. |
| Browser workflows | Catalog, access and Core Chromium scripts passed; recovery was delivered by the live background worker. The existing owner was already verified; verification consumption is covered by integration tests. |
| Python dependencies and static checks | Runtime 43 and development 76 locked distributions: no known pip-audit advisories. Application Bandit: zero findings. Ruff check/format passed. The old coverage percentages below were not remeasured for this release. |
| Final web image | Trivy 0.76.1, **zero vulnerabilities across all severities**, no suppressions; 29 OS and 43 Python packages inventoried. |
| Final database-tools image | Same unsuppressed scanner, **zero vulnerabilities across all severities**; 45 OS packages inventoried. |
| Actual image runtime | Alpine 3.24.3, Python 3.13.18; native Argon2/Fernet/HKDF/TOTP and content validation; UID 10001, source read-only, private writable instance directory 0700, no pip/ensurepip or copied secrets; PostgreSQL/Redis and Gunicorn readiness passed. |
| Real account queue in image | Encrypted fictional unknown-account request committed and processed by `jobs.run_one`; no challenge or mail transport for the unknown address. |
| Migration and recovery | Fresh database upgraded to `c72a03`; no schema drift and 72 Core tables. Populated archive restored with separate PostgreSQL 17.11 tools into an isolated database: 11 journal lines, 3 trace results, reconciliation passed in 4.312001s; temporary databases removed. |

The new regression cases cover encrypted payload privacy, no user lookup/provider I/O on the public path, current eligibility in the worker, tampering, rotation, expiry, supersession, simultaneous consumption, missing configuration, ambiguous delivery, abandoned claims, global/company scope constraints and backup tooling credential/TLS handling. A separate read-only review found no concrete defect in the account queue changes.

## Supported container replacement

The earlier nine Debian CVEs were not repaired upstream. Their affected Debian package set is absent from the new supported Alpine runtime. This is a base/platform change, with native musllinux wheels installed using the unchanged fully hashed application lock. There are no unsupported package substitutions or vulnerability exclusions. OS package inventories remain available to the scanner.

The default `web` target uses official `python:3.13-alpine` pinned by digest. Administrative `pg_dump`/`pg_restore` run from a separate `database-tools` target based on official `postgres:17-alpine`, also pinned. The web image needs no PostgreSQL client, libmagic, compiler, package installer or Bash. Bounded content signature checks and fail-closed malware scanning remain enforced. Operator backups run from a trusted host, with either local clients or the tools image; database credentials stay out of arguments, TLS material is mounted read-only, and archives stream through private host files.

| Final local image ID | SHA-256 |
| --- | --- |
| Web | `b7116147ccd8a6bc04185ebe4d6032a2186ca63501fcf0c42af38c460aa86f64` |
| Database tools | `f8dd4035db79d2147439c8753d84a33c6ac75fcf4c2c4ebef8a4a4f592d38f56` |

Trivy used the official `ghcr.io/aquasecurity/trivy-db:2` through verified proxy/CA trust. Advisory database updated `2026-11-03T07:14:02Z`; final scans completed at `2026-11-03T16:20:23Z` (web) and `2026-11-03T16:20:06Z` (tools). These are point-in-time results; future advisory updates require rebuilding and rescanning. These local image IDs are not published registry manifest digests.

Private instance artifacts: `/tmp/recall-alpine-final-web.json` (report SHA-256 `28e832f768e0638fd5b2bf05e54aac050196487cd614db5ff478192fed3629b2`), `/tmp/recall-alpine-final-tools.json` (`858b968f5e5c896790d9984b3a79880c0dfc240ed3bf8738850f1eab55ecd016`), `/tmp/recall-alpine-final-smoke.log` and `/tmp/recall-alpine-backup-restore.log`. Final build inputs were rehashed unchanged after verification. Temporary artifacts are not a durable off-machine archive.

## Account-email timing remediation

Every syntactically valid public password-reset or email-verification request performs the same normalized, encrypted global outbox insertion. The request handler does not query `users`, decide eligibility, create a token, write a mailbox or call a provider. Eligibility and transport run only after the worker claims committed intent. Existing rate limits and generic response text remain enabled. This removes account/provider-dependent HTTP work; shared database contention means it is not a formal constant-time guarantee.

HKDF derives separate Fernet and HMAC keys from the existing MFA encryption key and validated key version. Outbox rows contain an authenticated ciphertext and keyed recipient/purpose pseudonym, never a plaintext address or any raw challenge code. Codes are generated only in worker memory, stored as digests in challenge tables and delivered privately. Requests expire after 15 minutes; a newer request supersedes previous codes even before its worker runs. Per-recipient/purpose serialization orders enqueue, issuance and consumption, and all locks are released before external I/O. Rotation, corruption and missing keys fail closed.

Migration `c72a03` reuses `job_outbox`, with a database CHECK allowing unscoped rows only for system account challenges without an actor. Company jobs still require a company, and company UI/retry paths exclude system rows. No new table was added. Ambiguous delivery and abandoned claims are retained without automatic resending; a fresh request creates fresh intent/code. Downgrade refuses to discard existing global security history.

A supervised `flask --app wsgi:app outbox-run --watch` process is now required for automatic recovery/verification delivery. A bounded manual drain is supported for a synthetic demo; stopping the worker does not deliver instructions. Existing authenticated company invitations remain synchronous and do not use account-existence eligibility branching. Key rotation requires coordinated web/worker configuration and recovery of the private encryption key.

## Reproduce and remaining boundaries

After `bash scripts/setup.sh`, run:

```sh
.venv/bin/python -m pytest -q -W error::DeprecationWarning --tb=short
bash scripts/security_checks.sh
docker build --target web -t recalltrace-web-review .
docker build --target database-tools -t recalltrace-tools-review .
```

Scan both images with the official Trivy 0.76.1 image using its configured proxy/CA, `image --scanners vuln --severity UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL --exit-code 1 --db-repository ghcr.io/aquasecurity/trivy-db:2`, without an ignore list. The CI workflow builds both targets, verifies runtime contracts and scans both images at all severities using a digest-pinned scanner; GitHub Actions results are separate from these local results. See [deployment instructions](DEPLOYMENT.md) for worker supervision and host backup commands.

No public provider, real email, ingress TLS/host assessment, full workload benchmark, external evidence/key disaster recovery or business SLA was verified. Application Bandit has zero findings; intentional smoke assertions and controlled operator subprocess/temp-file usage remain reviewable static notices outside that application-only scan. Scanning and tests do not establish full security or always-on availability on free hosting.

<details>
<summary>Historical adversarial review before this remediation (307 tests; Debian image findings)</summary>

The following records the previous image and implementation. Its remaining-CVE and synchronous-public-email statements are superseded by the remediation above.

# Adversarial security review — 3 November 2026

This review tested RecallTrace's local 72-model Core implementation. It is a code/integration/container review, not a production penetration test, ASVS certification, public provider assessment or assurance that no vulnerabilities remain. Only fictional local data and mocked external responses were used. No real recall mail or third-party targets were exercised.

## Results

| Check | Observed result |
| --- | --- |
| Original baseline | 188 tests passed in 76.50s. |
| Final complete PostgreSQL/Redis suite | **307 passed in 140.97s**, with deprecations treated as errors. Includes 119 additional adversarial cases and existing regression coverage. |
| Coverage | 83.0% statements, 69.6% branches, 80.3% combined line/branch coverage. These measurements do not establish security completeness. |
| Browser regressions | Catalog, access and Core Chromium smoke checks passed. The existing demo owner was already verified, so the access smoke explicitly did not repeat verification consumption. |
| Runtime lock audit | 43 locked distributions; zero known advisories returned by pip-audit. |
| Development lock audit | 76 locked distributions including Bandit 1.9.4; zero known advisories returned by pip-audit. |
| Application static analysis | Bandit 1.9.4, all application modules: zero findings, no suppressions. |
| Application + verification/backup scripts | 11 remaining analyzer notices reviewed below; no claim that all static notices were eliminated. |
| Container HIGH/CRITICAL scan | Trivy 0.76.1: fixed-available Python findings 5→0; all image HIGH records 53→48, distinct advisories 14→9; zero CRITICAL. Remaining Debian advisories have no available fixed version in the current vendor data. |
| Final image runtime | UID 10001; application source root-owned and not writable; private instance directory writable 0700; pip/ensurepip absent; no copied .env/password; 72 models; real Gunicorn readiness against PostgreSQL/Redis passed. |
| Consistency | Ruff, formatting, dependency consistency, schema drift and unchanged 72-model inventory checked. No migration was required for these fixes. |

The initial full adversarial run passed 306 tests and caught one fixture that opened a browser session after MFA enrollment without verifying that login. The expected redirect showed MFA was working. The fixture was reordered without bypassing MFA, deprecated form choices were replaced, and the complete final 307-case run passed with warnings treated as errors.

## Confirmed issues fixed

| Area | Problem and resulting behavior | Regression evidence |
| --- | --- | --- |
| Authentication guessing | IP-only buckets permitted distributed password/MFA guessing. Password checks now also use a hashed account bucket; all MFA code endpoints share a per-user budget across IPs and sessions. | tests/test_adversarial_auth.py |
| MFA malformed input | Unicode decimal digits passed a regex but caused ASCII-only constant-time comparison to raise TypeError. Only ASCII six-digit TOTP inputs reach comparison. | tests/test_adversarial_auth.py |
| Privilege audit | Role grant creation/updates did not append audit history. Changes now record atomic scoped events; rejected stale edits leave no phantom event. | tests/test_adversarial_auth.py |
| Reversal authorization | A transfer-only user could reverse a supplier receipt. Receipt reversal now requires inventory.receive; transfer reversal requires inventory.transfer, including UI gating. | tests/test_adversarial_operations.py |
| Stale operational parents | Posting/reversal could use suppliers/customers or facility ancestors made inactive after draft creation. Headers and location→warehouse→site are revalidated under the shared guard. | tests/test_adversarial_operations.py |
| Input availability | Oversized/malformed versions, out-of-range definition integers, extreme decimal exponents, Unicode/NUL text and omitted optional notes could cause server errors. Inputs now reject safely before database writes. Exact whitespace-normalized idempotency keys retry consistently. | tests/test_adversarial_runtime.py, test_adversarial_operations.py, test_adversarial_recall.py |
| Evidence authorization | Quality/recall/reconciliation selectors exposed private filenames to users lacking evidence.read. Both display and service actions now enforce the evidence permission. | tests/test_adversarial_recall.py, test_adversarial_evidence.py |
| Quality evidence integrity | A referenced nonconformance could be moved to another lot/inspection, leaving case/hold evidence inconsistent. Referenced identity is frozen; cancelled tasks cannot change. Task verification requires recent MFA. | tests/test_adversarial_recall.py |
| Trace resource bounds | Shipment exposure could be materialized without a bound and recovery totals were queried per line. A cap yields an explicitly incomplete nonapprovable result, and recovery totals are grouped. | tests/test_adversarial_recall.py |
| Recovery integrity | Retrying a recovery could substitute its notice reference; recipient linkage was insufficient. Payload checks include the notice and its customer. Overlapping cases now project the same immutable physical disposition without allocating it twice and show its original case/evidence reference. | tests/test_adversarial_recall.py |
| External payload privacy | Storage/scanner/mail HTTP redirects could forward private bytes or custom credential headers. Redirects are disabled; non-success/malformed JSON is rejected or marked ambiguous. Missing/null provider receipts never prove delivery. | tests/test_adversarial_evidence.py |
| CSV/worker availability | Malformed CSV headers escaped the parse error handler; corrupt outbox payloads could stop the worker or refer to unrelated delivery rows. They now fail safely without affecting unrelated work. | tests/test_adversarial_evidence.py |
| Evidence I/O locking | Slow scanning/storage held the company's stock/approval guard. I/O now runs outside that guard, followed by fresh authorization/content/version checks; rejected staged objects are cleaned up privately. | Scanner/storage NOWAIT and concurrent revocation/rename cases in tests/test_adversarial_evidence.py |
| Stale unsent notices | Reopening scope or changing a contact could leave an unsendable notice permanently blocking closure. Controlled independent MFA withdrawal cancels never-sent intents while preserving attempts; processing, sent, locally written and ambiguous deliveries cannot be withdrawn. | tests/test_adversarial_evidence.py |
| Configuration/health | Mistyped APP_ENV silently used development defaults. Unknown modes now fail startup. Redis rate failures no longer prevent liveness or turn readiness into an uncaught 500; health does not load authenticated identity. | tests/test_adversarial_runtime.py |
| Runtime image | pip's bundled msgpack/setuptools/urllib3 copies had five fixable advisory matches despite clean app locks. Unneeded installer modules were removed after locked installation/validation. Runtime source is now read-only for UID 10001. | Final image smoke and Trivy report |

The browser verification helper also restricts its authenticated concurrent requests to the selected HTTP(S) origin and refuses redirects rather than forwarding a test cookie to another server.

## Remaining container advisories

Final image: `sha256:e9a944779faf611ce18d86de108a9f2794b6b7df729fef0a3d6725b81240ffd7`.

Trivy scanned HIGH/CRITICAL severities with the official `ghcr.io/aquasecurity/trivy-db:2` database, using verified TLS; no vulnerability ignore list, severity suppression or insecure transport was used. The default mirror was denied by network policy, so the supported official GHCR repository was used through the same proxy. Scan timestamp: `2026-11-03T10:17:46.346072976Z`.

There are 48 HIGH package/advisory records representing these **nine distinct Debian CVEs**. Repeated source-package advisories account for the difference between record and CVE counts. The current official base digest is unchanged and apt's available update was tzdata; no fixed Debian package versions for these advisories were reported. This review did not attempt privileged exploitation or prove that every affected component is reachable from the web application. Non-root execution is not a reason to suppress the findings.

| Advisory | Reported installed binary packages | Vendor result at scan time |
| --- | --- | --- |
| CVE-2025-69720 | libncursesw6, libtinfo6, ncurses-base, ncurses-bin | No fixed Debian version reported |
| CVE-2026-119373 | libsqlite3-0 | No fixed Debian version reported |
| CVE-2026-16742 | libsystemd0, libudev1 | No fixed Debian version reported |
| CVE-2026-54369 | libacl1 | No fixed Debian version reported |
| CVE-2026-76642 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | No fixed Debian version reported |
| CVE-2026-78408 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | No fixed Debian version reported |
| CVE-2026-78409 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | No fixed Debian version reported |
| CVE-2026-78410 | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux | No fixed Debian version reported |
| CVE-2026-9538 | libperl5.40, perl, perl-base, perl-modules-5.40 | No fixed Debian version reported |

Recheck the vendor/advisory database and rebuild when fixes become available. Do not represent this image as vulnerability-free or fully production-cleared while these findings remain unresolved. Do not use unsupported package swaps, disabled verification or scanner ignores to manufacture a passing result.

## Reviewed static notices and remaining limits

The wider Bandit run still reports eight B101 assertions in intentional smoke-test scripts, one B404 import/B603 fixed-argument subprocess invocation in the operator backup utility, and one B108 notice for Gunicorn's temporary directory. Assertions are verification code, not authorization controls; runs here used ordinary Python, not optimized -O. Backup subprocesses use fixed pg_dump/pg_restore argument arrays with no shell and keep credentials in their environment. Gunicorn uses secure temporary-file creation rather than an attacker-selected fixed filename. These are reviewed notices, not a blanket scanner suppression or an assertion of zero risk in every deployment.

Production recovery/invitation email is still synchronous. Generic response text and shared rate limits do not establish that provider-dependent response timing hides account existence. No live mail provider was configured or measured; a durable encrypted account-delivery design remains a follow-up before a stronger anti-enumeration claim. Raw account codes must not be placed into plaintext job payloads.

No live public TLS/host/proxy assessment, provider storage/scanner/mail test, full workload benchmark, external evidence/key recovery exercise or legal/security certification was performed. Previously documented free-hosting and deployment requirements remain.

## Reproduce

From the existing checkout after `bash scripts/setup.sh`:

```sh
.venv/bin/python -m pytest -q -W error::DeprecationWarning --cov=app --cov-branch
bash scripts/security_checks.sh
.venv/bin/bandit -r app scripts wsgi.py gunicorn.conf.py -f json -o instance/bandit-full.json
```

The last command intentionally returns a nonzero result for the reviewed script notices; review its report rather than treating it as a clean application scan. CI now checks both dependency locks, the application Bandit scan, and the non-root immutable-source image contract. CI execution on GitHub is separate from these local results.

Container checks require the managed Docker daemon or another trusted Docker host. Use the official scanner with the configured proxy/CA and cached/official advisory repository. Runtime advisory reports contain machine metadata; the sanitized findings above are the repository record. Full execution artifacts are retained privately in `/tmp/recall-security-*`, `/tmp/recall-container-vulns-final.json` and `/tmp/recall-container-security-smoke-final.log` for this instance only.

</details>
