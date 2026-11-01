# Security and permission plan

## Authorization model

Apply identity active membership action permission company ownership and optional partner restriction to every route service query download import export and job. Authorization defaults to denied. Do not trust submitted organization or parent IDs. Recheck current rights when jobs execute. A link or object identifier never grants access by itself. The seven default roles below are seed bundles; grants are explicit and reviewed.

| Role | Permitted responsibility | Boundary |
| --- | --- | --- |
| Owner | Manage company membership and approved role assignments; configure operating data | Cannot erase history or bypass independent approval; last owner protected |
| Quality manager | Inspection review holds case approval closure and controlled release | Cannot approve their own submitted case or release their own hold |
| Production operator | Prepare and post permitted production records | Cannot release held lots or approve recall scope |
| Warehouse operator | Prepare receipts transfers and shipments; Expanded returns and counts | Cannot dispatch held or unavailable stock; no unrestricted quality override |
| Recall coordinator | Prepare cases traces tasks notices and recovery evidence | Cannot independently approve their own operational response |
| Auditor | Read authorized business and audit records and permitted exports | No mutations; no authentication secrets or unrestricted partner personal data |
| Partner viewer | Read their own approved notices and submit or record acknowledgements | Company plus partner restriction; no full internal genealogy or other partner details |

## Authentication and session controls

Use Argon2id through argon2-cffi with parameters reviewed against current OWASP guidance and measured on the deployment hardware [S14]. Initial password policy is at least 15 characters and at most 128, allows spaces and paste, and rejects known compromised/common choices through a controlled blocklist. Do not impose arbitrary character-class composition rules. Use generic login and recovery responses and rate limits shared across workers.

Flask Login provides user context. Flask Session stores session data on shared Redis. Rotate the server session identifier after successful authentication and privilege change [S11]. Maintain auth_sessions as a connected registry: session data contains a private random reference whose digest is checked against an unexpired nonrevoked row on each authenticated request. Compare the recorded authentication version with users.auth_version. Resetting a password increments this version and revokes active sessions. Remember-me cookies are disabled for the initial release.

Production cookies are Secure HttpOnly SameSite=Lax with a __Host- name and Path=/, without Domain. Proposed idle timeout is 30 minutes and absolute timeout 8 hours; high impact actions require MFA verified within 10 minutes. These are project policy defaults to validate, not properties supplied automatically by an extension. Expiring cookies alone do not implement server revocation.

Owners quality managers and recall coordinators enroll TOTP before privileged approvals. Encrypt factor secrets using a maintained cryptography library and a versioned deployment key; store recovery codes only as digests. Reject repeated time steps and consume recovery codes atomically. MFA recovery requires an audited verified administrative process, not a security question or an emailed plaintext factor secret.

## Request and browser controls

Enable Flask WTF CSRF globally for every state-changing cookie-authenticated request, including signout and preference changes. Use server form validators plus domain rules and database constraints. Valid form submission uses a 303 redirect to GET and a flash message. Invalid input renders field errors without writing business data. Validate redirect destinations against an allowlisted local path.

Use Jinja autoescaping and quote attributes. Do not apply safe to submitted HTML. Validate links and external tracking templates. Ship a restrictive CSP and applicable content-type frame and referrer headers. Enable HTTPS and HSTS only after domain/proxy configuration is verified. Set trusted hosts and trust only the known proxy hops [S03]. Production refuses debug mode missing secrets SQLite or process-local rate storage.

## Evidence and data protection

Allow only validated PDF JPEG and PNG evidence initially; reject HTML SVG executable files and content/type mismatches. Proposed limits are 10 MiB per evidence file and 10 MiB or 10000 rows per CSV import, with bounded fields and request time. Use generated object keys private storage and a quarantine state. External untrusted evidence is scanned before release; if the scanner is unavailable the file remains unavailable. Do not treat a filename extension or MIME header alone as validation.

Downloads require live object authorization; private storage URLs expire and are never public object URLs. Prevent path traversal and render original filenames only as escaped labels. Audit details exclude secret tokens passwords factor seeds file contents and unnecessary personal contact data. TLS protects network connections and storage encryption protects backups and evidence according to the chosen platform. Encryption keys do not reside beside encrypted secrets in source control.

Imports use a parser with size row and field bounds and an allowlist of supported operations. Validate all rows before atomic application; no uploaded Python SQL or executable formula is evaluated. Exports mitigate spreadsheet formula injection while preserving documented data meaning. Both imports and exports retain requester and company scope and revalidate permissions.

## Threat cases and verification

| Threat | Control | Planned evidence |
| --- | --- | --- |
| Cross company object access | Company scoped lookups and composite foreign keys | T001 T002 T003 T062 |
| Partner information leakage | Restricted partner membership and recipient scoped notice content | T004 |
| Stolen or replayed authentication | Token digests expiry session revocation MFA replay controls | T005 T006 T008 |
| Forged form or repeated posting | CSRF plus unique idempotency keys and payload digests | T009 T016 T017 |
| Concurrent stock overspend | Shared lot locks refreshed balances and atomic journal posting | T018 T022 T033 |
| Stale or partial recall scope | Trace revisions explicit completeness and approval validation | T029 T030 T032 |
| Malicious evidence or CSV | Allowlisted parsing quarantine private storage and output handling | T040 T041 T042 T044 |
| Background authorization bypass | Execution-time access checks and durable outbox processing | T034 T045 T049 |
| Audit alteration | Runtime database privileges controlled triggers and separate migration role | T047 T048 |
| Unavailable infrastructure | Fail-closed configuration bounded retries restore exercises | T058 T060 |

Use applicable OWASP ASVS requirements as a checklist with requirement ID implementation evidence test result and remaining gap [S08]. The checklist is not certification. Application append-only logs do not establish tamper resistance against a privileged database administrator; stronger external integrity controls require a separate design.

## Permission actions

Use stable action codes such as company.manage access.manage catalog.manage inventory.receive inventory.transfer inventory.dispatch production.post quality.inspect quality.hold quality.release trace.run case.prepare case.approve case.close notice.prepare notice.approve notice.acknowledge recovery.record evidence.read evidence.upload reports.export and audit.read. No generic is_admin bypass grants every business action. Cross-company access is not granted by a role code.
