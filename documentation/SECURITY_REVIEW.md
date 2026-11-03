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
