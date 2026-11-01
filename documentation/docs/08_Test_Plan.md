# Testing and release evidence

This plan defines 62 acceptance scenarios. All software test results start as Not executed. A defined case is not an automated test implementation and a completed specification is not a passing application.

## Test environments

Use isolated PostgreSQL for relational integrity transaction and concurrency tests. SQLite-only tests cannot establish PostgreSQL row lock or constraint behavior. Each test has independent fixtures. Browser tests use seeded fictional company and partner accounts and a local email sink. Security test configurations explicitly enable CSRF rate limits and production cookie/header behavior for the relevant checks. Convenience fixtures may disable a control only in unrelated tests and must never be cited as verification of that control.

Unit cases cover permitted state transitions traversal result normalization unit precision and rule decisions. Integration cases exercise database services and authenticated requests. Concurrency cases use separate committed database connections and synchronization barriers rather than two calls within one session. Browser cases verify the complete Jinja workflow. Operational cases exercise real migration configuration and recovery procedures.

## Planned case inventory

| ID | Type | Scenario | Expected result |
| --- | --- | --- | --- |
| T001 | Integration | Read a foreign company lot using its UUID | 404 and no foreign record metadata |
| T002 | Integration | Submit a foreign parent through a form import and export filter | Rejected with no write or data disclosure |
| T003 | Integration | Request another company private evidence or completed export | No file bytes returned |
| T004 | Integration | Partner A requests Partner B notice case view or acknowledgement | 404 and no partner B content |
| T005 | Integration | Use expired consumed and malformed email reset and invitation tokens | Generic safe rejection and no authentication |
| T006 | Integration | Reset password or revoke a session then reuse old cookies | Old session rejected on the next authenticated request |
| T007 | Integration | Call forbidden endpoint directly and remove the last owner | Denied server action; company retains an active owner |
| T008 | Integration | Replay a TOTP step and reuse a recovery code concurrently | At most one successful consumption |
| T009 | Integration | Submit mutating forms with missing or incorrect CSRF token | 400 or documented CSRF failure response; no write |
| T010 | Integration | Exceed login and reset limits using two web workers | Shared limit produces 429 and safe retry response |
| T011 | Integration | Create view update and delete unused catalog partner location and lot records | Complete UI CRUD with same company foreign keys |
| T012 | Integration | Delete a referenced variant or posted lot identity | Deletion blocked or archive offered; ancestry remains readable |
| T013 | Integration | Submit invalid quantity date URL and mismatched parent identifiers | Field or domain errors; no partial write |
| T014 | Integration | Post one valid partial supplier receipt | Journal and balance increase by actual accepted quantity only |
| T015 | Integration | Fail one line of a multi line receipt | No receipt line journal or balance changes commit |
| T016 | Concurrency | Post the same receipt concurrently with one idempotency key | One posting; repeated request resolves to the original result |
| T017 | Concurrency | Reuse an idempotency key with a different payload | 409 and no extra posting |
| T018 | Concurrency | Consume the same available stock from two production runs | Only valid total consumption commits; balances never become negative |
| T019 | Integration | Post a run with one input and two output lots | All outputs link to input ancestry and stock reconciles |
| T020 | Integration | Attempt self ancestry or a longer lot cycle | Posting rejected with traceable validation error |
| T021 | Integration | Transfer a lot and reverse that transfer | Company total conserved; reversal creates compensating entries |
| T022 | Concurrency | Dispatch or consume stock while a hold is being approved | Serialized result honors the committed hold and preserves valid history |
| T023 | Integration | Edit a referenced inspection template version | A new revision is created; prior inspection meaning stays stable |
| T024 | Integration | Ask the original hold placer to approve release | Independent reviewer required |
| T025 | Integration | Create edit and delete a draft case with root associations | Full draft CRUD and owned child lifecycle demonstrated |
| T026 | Unit and integration | Trace A to B and C then both to D | D appears once with valid path evidence |
| T027 | Unit and integration | Trace from two overlapping roots | Unique affected lots and shipment lines; no duplicated exposure totals |
| T028 | Unit and integration | Reverse trace a finished lot with two component ancestors | Both upstream branches appear without downstream unrelated lots |
| T029 | Unit and integration | Trace reaches a configured node or time limit | is_complete false with reason; approval cannot proceed |
| T030 | Integration | Post new genealogy after trace completion before case approval | Stale revision rejected and a fresh trace is required |
| T031 | Browser | Compare graph nodes with the accessible affected lot table | Same authorized computed lot set; graph display cap is labeled |
| T032 | Integration | Try self approval or approval from an incomplete trace | Denied with no notice or hold side effects |
| T033 | Concurrency | Approve a case while a relevant shipment is dispatched | Latest committed eligible exposure is included and future release is held |
| T034 | Integration | Prepare a notice then roll back its approval transaction | No delivery intent is emitted |
| T035 | Integration | Retry a worker after an uncertain provider response | Ambiguous status retained; reconciliation avoids blind duplicate delivery |
| T036 | Integration | Submit the same acknowledgement twice | One effective acknowledgement for that notice revision |
| T037 | Concurrency | Allocate the same returned quantity to two recovery entries | Second over allocation rejected; recovery stays bounded |
| T038 | Integration | Close a case with an unverified mandatory task or stale trace | Closure rejected with unmet criteria |
| T039 | Integration | Close a reviewed case with recorded remaining exposure disposition | Closure succeeds and operational history remains readable |
| T040 | Integration | Upload executable disguised as PDF HTML SVG and oversized evidence | Unsupported or mismatched content quarantined or rejected |
| T041 | Integration | Request traversal filename object key or expired document link | No filesystem escape or unauthorized content |
| T042 | Integration | Dry run a CSV with one invalid row then try commit | Errors identify rows without leaking sensitive values; no rows apply |
| T043 | Concurrency | Commit a valid import twice using one idempotency key | Exactly one import operation applies |
| T044 | Integration | Export cells beginning with spreadsheet formula characters | Consumer spreadsheet treats exported user content as data |
| T045 | Integration | Remove requester membership while an export is queued | Worker and download deny access |
| T046 | Integration | Filter and paginate a large company dataset | Stable ordering totals and bounded query count |
| T047 | Integration | Update or delete an audit event using the application database role | Denied by application and configured database privileges |
| T048 | Integration | Inspect audit records after login reset upload and case changes | No token secret password or raw evidence contents in logs |
| T049 | Integration | Crash after business commit before queue publication | Outbox publisher recovers pending intent without another stock posting |
| T050 | Integration | Post split merge and explicit partial allocation fixtures | Applicable quantity conservation and conservative uncertainty rules hold |
| T051 | Integration | Reserve excess stock reuse a serial or self approve a count | All invalid operations rejected |
| T052 | Integration | Link test result to the wrong lot or edit a signed method | Mismatch rejected and signed method revision preserved |
| T053 | Integration | Over return a shipment and receive returned goods | Excess blocked and valid returned goods quarantined |
| T054 | Browser | Submit valid form then refresh destination page | 303 redirect followed by safe GET; no duplicate transaction |
| T055 | Browser | Use keyboard only at narrow viewport with validation errors | Labels focus error association graph alternative and actions remain usable |
| T056 | Migration | Upgrade a clean PostgreSQL database and inspect ORM metadata | Selected release model inventory matches migrated tables and constraints |
| T057 | Integration | Exercise each mapped master draft child and immutable lifecycle | All permitted CRUD paths work; forbidden history mutations fail |
| T058 | Operational | Start production without secrets shared rate storage or private file configuration | Startup fails safely without exposing configuration values |
| T059 | Operational | Run documented workload on stated hardware | Record actual p50 p95 throughput errors queue delay and trace completeness |
| T060 | Operational | Restore PostgreSQL and file metadata to a fresh environment | Record counts journal reconciliation and evidence references validate |
| T061 | Browser end to end | Run the fictional defective switch recall scenario | Receipt production trace approval notice acknowledgement recovery and closure complete |
| T062 | Browser end to end | Run the same scenario with foreign company and partner identities | Forbidden records and evidence remain inaccessible |

## Release evidence

Keep a dated result record for each implemented case with software commit environment selected release fixture version command outcome and failure reference. Record successful and failed runs. The release must have no unresolved authorization stock integrity trace completeness or destructive migration defect. A percentage coverage target alone is not a release criterion.

Run formatting and static checks once the implementation exists, then meaningful unit and PostgreSQL integration/concurrency tests, then browser end-to-end checks, dependency and secret scans, workload measurement and a restore exercise. New failures or changed code determine what needs rerunning. Do not report benchmark or security results that were not measured.

## Demonstration script

Use the C10 L1 L2 L3 fixture defined in the project proposal. Demonstrate master record CRUD and server validation first. Post receipt and production show journal reconciliation and dispatch S1/S2. Create a case run a trace inspect path evidence and exclude unrelated S3. Attempt a forbidden cross-company lookup and an invalid self approval. Approve using the independent quality account show held-stock dispatch rejection queue notices to the local email sink record acknowledgement and recovery evidence and complete closure checks. Refresh a successful POST destination to demonstrate PRG. Show the selected model inventory Jinja inheritance route converters and README setup.
