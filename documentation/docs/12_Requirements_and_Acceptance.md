# Requirements and acceptance

All entries are planned requirements. Each is linked to at least one defined test case; execution results are recorded later. Core features form one complete release.

## Functional requirements

| ID | Requirement | Actor | Phase |
| --- | --- | --- | --- |
| FR01 | Company and partner scope | Owner | Core |
| FR02 | Authentication lifecycle | All users | Core |
| FR03 | Permission management | Owner | Core |
| FR04 | Privileged multifactor verification | Owner Quality manager Recall coordinator | Core |
| FR05 | Catalog and counterparties | Authorized staff | Core |
| FR06 | Locations and lots | Warehouse operator | Core |
| FR07 | Receipt posting | Warehouse operator | Core |
| FR08 | Production posting | Production operator | Core |
| FR09 | Inventory transfer | Warehouse operator | Core |
| FR10 | Inspection records | Quality manager | Core |
| FR11 | Quality holds | Quality manager | Core |
| FR12 | Case creation | Recall coordinator | Core |
| FR13 | Bidirectional tracing | Recall coordinator Auditor | Core |
| FR14 | Trace presentation | Recall coordinator Auditor | Core |
| FR15 | Case approval | Quality manager | Core |
| FR16 | Recall communication | Recall coordinator | Core |
| FR17 | Acknowledgements and recovery | Recall coordinator Partner viewer | Core |
| FR18 | Case closure | Quality manager | Core |
| FR19 | Private evidence | Authorized staff | Core |
| FR20 | CSV import | Owner Authorized staff | Core |
| FR21 | Exports | Authorized staff Auditor | Core |
| FR22 | Search and dashboards | Authorized staff | Core |
| FR23 | Audit history | Auditor Owner | Core |
| FR24 | Background delivery | System | Core |
| FR25 | Advanced production mapping | Production operator | Expanded |
| FR26 | Serial and count operations | Warehouse operator | Expanded |
| FR27 | Sample testing | Quality manager | Expanded |
| FR28 | Return workflows | Warehouse operator | Expanded |
| FR29 | Usable forms and feedback | All users | Core |
| FR30 | Controlled record lifecycle | Authorized staff | Core |

### FR01 Company and partner scope

Create separate company workspaces and explicitly restricted partner memberships.

Acceptance: Company A cannot read or change any Company B object or job result; partner users see only approved information for their partner.

Planned tests: T001 T002 T003 T004 T062.

### FR02 Authentication lifecycle

Register or accept an invitation, verify email, sign in, recover passwords and revoke sessions.

Acceptance: Invalid expired and reused tokens fail; password reset and membership removal invalidate relevant active access.

Planned tests: T005 T006 T009 T010 T058.

### FR03 Permission management

Assign action permissions through roles with independent high impact approvals.

Acceptance: Changing navigation cannot bypass a denied server action; last active owner is protected.

Planned tests: T007 T062.

### FR04 Privileged multifactor verification

Enroll a TOTP factor and use step up verification for privileged approvals.

Acceptance: A reused time step or recovery code fails and a revoked factor cannot authorize an action.

Planned tests: T008.

### FR05 Catalog and counterparties

Maintain variants base units categories supplier and customer records.

Acceptance: Related CRUD works with server validation; referenced master records archive instead of breaking history.

Planned tests: T011 T012.

### FR06 Locations and lots

Maintain warehouses bins and stable lot identifiers.

Acceptance: Duplicate internal lot codes and cross company parent relationships are rejected.

Planned tests: T011.

### FR07 Receipt posting

Receive purchase order quantities into identified lots and locations.

Acceptance: A receipt posts journal and balance changes once; invalid rows or overreceipt roll back the entire transaction.

Planned tests: T014 T015 T016 T017 T061.

### FR08 Production posting

Record consumed input lots and produced output lots.

Acceptance: Posting atomically consumes and produces stock; rejects unavailable stock held lots and cyclic ancestry.

Planned tests: T018 T019 T020 T061.

### FR09 Inventory transfer

Transfer available lots between authorized locations.

Acceptance: The transfer preserves total quantity and cannot release held stock.

Planned tests: T021.

### FR10 Inspection records

Define versioned inspection criteria and record lot observations.

Acceptance: Completed inspections retain their criterion version; invalid observation types fail validation.

Planned tests: T023.

### FR11 Quality holds

Place holds and request independent release review.

Acceptance: Held lots cannot be consumed dispatched or transferred to evade a hold; release checks reviewer independence.

Planned tests: T022 T024.

### FR12 Case creation

Create an investigation with root lots evidence owner and severity.

Acceptance: Draft cases support CRUD; root lots and evidence belong to the same company and refer to consistent records.

Planned tests: T025 T061.

### FR13 Bidirectional tracing

Trace upstream sources and downstream output lots from posted records.

Acceptance: The trace reports direction algorithm version data revision and completeness; repeated paths do not duplicate affected lot identities.

Planned tests: T026 T027 T028 T029 T030 T059 T061.

### FR14 Trace presentation

Inspect path evidence and related shipments in a graph and accessible table.

Acceptance: Both views contain the same authorized lot set; truncated display is clearly separated from computation completeness.

Planned tests: T031 T055.

### FR15 Case approval

Review a complete current trace and authorize the operational response.

Acceptance: Approval revalidates revision and exposure applies holds atomically and requires an independent approver.

Planned tests: T030 T032 T033 T061.

### FR16 Recall communication

Prepare approve and queue recipient specific notices.

Acceptance: No unapproved stale or cross partner content is delivered; failed and ambiguous deliveries remain visible.

Planned tests: T004 T034 T035 T061.

### FR17 Acknowledgements and recovery

Record notice acknowledgement and verified recovery evidence.

Acceptance: Duplicate acknowledgements are harmless; quantity and return allocations cannot be counted twice.

Planned tests: T004 T036 T037 T061.

### FR18 Case closure

Close a case after defined investigation and follow up checks.

Acceptance: Mandatory tasks are verified trace is current and complete and remaining exposure has a recorded disposition.

Planned tests: T038 T039 T061.

### FR19 Private evidence

Upload allowed evidence and retrieve it through scoped permissions.

Acceptance: Quarantined unsupported oversized and unauthorized files cannot be downloaded; URLs do not bypass checks.

Planned tests: T003 T040 T041 T058 T062.

### FR20 CSV import

Preview and commit supported master and draft transaction imports.

Acceptance: All rows pass validation before atomic commit; duplicate submission is idempotent; imports never write posted tables directly.

Planned tests: T002 T042 T043.

### FR21 Exports

Generate a private filtered export for permitted objects.

Acceptance: Authorization is checked at execution and download; formula like cell values are rendered safely for spreadsheets.

Planned tests: T002 T044 T045.

### FR22 Search and dashboards

Find records with company scoped filters and paginated lists.

Acceptance: Totals reconcile to the same filtered data and no unbounded list query is used.

Planned tests: T046 T059.

### FR23 Audit history

Inspect redacted actor action and object history.

Acceptance: Business users cannot rewrite audit events or recover credentials from audit details.

Planned tests: T047 T048 T060.

### FR24 Background delivery

Process durable work requests after their business transaction commits.

Acceptance: A rollback creates no external work; retries do not duplicate stock events and ambiguous email delivery is reconciled.

Planned tests: T016 T034 T035 T049 T058 T060.

### FR25 Advanced production mapping

Use BOM revisions explicit input allocations and split merge or repack events.

Acceptance: Expanded mappings preserve ancestry and applicable quantity rules; unknown allocations remain conservative.

Planned tests: T020 T050.

### FR26 Serial and count operations

Track serial units reserve demand and post independently reviewed stock counts.

Acceptance: Serial identities are unique; stock count adjustments remain journaled and reservations cannot exceed available quantity.

Planned tests: T051.

### FR27 Sample testing

Record samples versioned methods reviewed results and corrective actions.

Acceptance: Sample and result evidence stays associated with the correct lot and method revision.

Planned tests: T052.

### FR28 Return workflows

Process supplier and customer returns plus dispatch and receipt evidence.

Acceptance: Return quantities remain bounded by original received or shipped quantities; returned customer stock enters quarantine.

Planned tests: T053.

### FR29 Usable forms and feedback

Use labeled Jinja forms with server validation flash feedback and Post Redirect Get.

Acceptance: Valid POST redirects to GET; invalid input preserves safe submitted values with field errors and no database change.

Planned tests: T009 T013 T054 T055.

### FR30 Controlled record lifecycle

Create read update and delete eligible business records and reverse posted events.

Acceptance: The per model CRUD matrix identifies owner screen permitted operations and immutable record handling.

Planned tests: T011 T012 T056 T057.

## Nonfunctional requirements

| ID | Area | Target behavior | Evidence |
| --- | --- | --- | --- |
| NFR01 | Isolation | Every company and partner boundary applies equally to synchronous and queued operations. | T001 to T004 T045 T062 |
| NFR02 | Integrity | Posted journal reconciles to balances; no invalid negative stock or cyclic genealogy commits. | T014 to T022 T050 |
| NFR03 | Security verification | Applicable ASVS controls have implementation and test evidence with recorded gaps. | Security checklist and T005 to T010 T040 to T048 |
| NFR04 | Performance target | On a recorded 4 vCPU 8 GiB benchmark environment: p95 common list GET below 1 second at 25 concurrent users and trace of 5000 lots 25000 edges below 5 seconds of worker compute. | T059; targets are unverified until measured; report queue time separately |
| NFR05 | Bounded processing | Initial page size 25 maximum 100; evidence 10 MiB; CSV 10000 rows and 10 MiB; graph display 500 nodes; compute limit 10000 lots. | T029 T040 T042 T046 |
| NFR06 | Recovery target | Initial deployment planning targets RPO 24 hours and RTO 4 hours; actual restore exercise establishes achieved values. | T060 |
| NFR07 | Accessibility | Labeled controls keyboard navigation visible focus error association meaningful table headers and graph alternative. | T031 T055 |
| NFR08 | Maintainability | Focused blueprints services typed interfaces consistent formatting reviewed migrations and a dependency lock. | Ruff review migration and clean setup output |
| NFR09 | Observability | Structured redacted logs correlation IDs job failure visibility queue age and stock reconciliation checks. | T035 T048 T049 |
| NFR10 | Reproducibility | A teammate can install migrate seed run and demonstrate the selected release from documented steps. | T056 T061 |
