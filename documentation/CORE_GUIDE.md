# Core release and university demonstration

The agreed final scope is the 72 Core models. The 28 Expanded models in the original design are excluded; no empty Expanded tables were added. `documentation/source/schema.json` retains the historical complete design. The executable model registry and migrations define the implemented schema; `test_schema_matches_selected_72_core_models` verifies the Core table set exactly.

## Demonstration preparation

Follow README.md for setup, first-owner bootstrap, `init-business` and the development-only `seed-investigation-demo` command. Sign in as the owner, open Aurora and use the workspace navigation. Local account messages stay in the private `instance/account-mail` directory. Never distribute its codes, demo passwords or MFA enrollment material with source/screenshots.

Create a separate reviewer through **Company access**. A useful restricted reviewer role includes `catalog.read`, `evidence.read`, `quality.inspect`, `quality.release`, `case.approve`, `case.close`, `notice.approve`, and `recovery.record`; add task/case preparation permissions only if that reviewer also needs to manage tasks. Grant only implemented actions needed by that user. Both participants can enroll authenticator apps through Account security. High-impact actions require a currently verified factor and recent session MFA; different accounts must submit and approve cases/notices and place/release holds.

For a partner demonstration, create a customer partner/contact, a portal-only role containing `notice.read` and optionally `notice.acknowledge`, then invite the user with that partner restriction. An unrestricted operational/owner role cannot be bound to a partner. The portal is limited to that partner's approved notice revisions; acknowledgement requires its own live grant. Company/catalog/evidence/graph endpoints remain inaccessible.

## C10 investigation

The repeatable fixture posts real business documents, journal entries and balance changes:

| Event | Recorded movement |
| --- | --- |
| Supplier receipt | 200 switches in C10; 10 unrelated switches in C11 |
| Production A | Consume 100 C10; produce 100 lamps in L1 |
| Production B | Consume 50 C10; produce 50 lamps in L2 |
| Unrelated production C | Consume 10 C11; produce 10 lamps in L3 |
| Dispatch S1 | 60 lamps from L1 |
| Dispatch S2 | 50 lamps from L2 |
| Unrelated dispatch S3 | 10 lamps from L3 |

Open C10-INVESTIGATION and its downstream trace. The graph/table contains C10, L1 and L2, with 150 recorded lamp outputs, 110 dispatched lamps and 40 lamps remaining. Report the 50 unused switches in a separate SKU bucket. L3/S3 are excluded. An upstream trace supports investigation but cannot authorize downstream recall decisions. Bounded/partial/stale computations cannot authorize approval, notices or closure.

Submit the investigation as the coordinator. Sign in as the independent MFA-verified reviewer and approve the current complete trace. Approval places holds on the traced lots atomically. Attempting to consume/transfer/dispatch held stock fails without changing journal/balances. A reviewer cannot release their own hold. Approval is not a way to bypass physical stock controls.

A later genealogy/dispatch change invalidates the revision. Reopen with a reason and recent MFA, recompute, submit and independently approve again. Existing holds remain. New traces cannot silently extend a previously approved operational scope.

## Quality, evidence and notice exercise

Publish a versioned inspection template with checks; record results for a lot and complete the inspection. The template criteria and completed observations freeze. Raise a nonconformance, place a hold and have a different reviewer record a retain/release decision. A release is recorded with its reason; active history cannot be deleted.

Upload a small synthetic PNG/JPEG/PDF through Evidence. With no scanner configured the expected result is quarantine, with no download or business-attachment option. Configure an authorized ClamAV/trusted HTTPS scanner before demonstrating clean evidence acceptance. Application-generated CSV exports and validated import-source files cannot be relabeled as shared active evidence. Private export download remains restricted to its requester, current grants and expiry.

Create a recipient contact for the affected customer's partner. Prepare the case notice; the generated text contains only that customer's affected shipment lines. Have a different authorized user approve it, then queue the durable delivery intent. During a local demonstration use:

```sh
.venv/bin/flask --app wsgi:app outbox-run --limit 20
```

The worker needs the same `MAIL_MODE=local ACCOUNT_MAIL_DIR=account-mail` process configuration as the web application for local notice delivery. A local attempt is `local_written`; it is never described as external `sent`. Missing mail configuration produces a failed attempt that can be reviewed/retried within its limit. Interrupted/ambiguous deliveries require independent, evidence-backed reconciliation, not automatic repetition.

Record recipient acknowledgement independently of physical recovery. Recovery/disposition requires shipment scope, a positive base-unit quantity, evidence text/reference, no over-recovery and payload-consistent repeat handling. Mandatory tasks require independent verification. Close only after reviewing current scope, resolved exposure, task completion and delivery/acknowledgement exceptions; holds continue to need their own independent release.

## Model and lifecycle coverage

The following modules provide actual forms/actions; associations are edited through the owning workflow. Security challenges, audit records, snapshots, posted ledger rows and delivery attempts have controlled system lifecycles rather than generic CRUD.

| Model group | Implemented tables | Owning interface/service |
| --- | --- | --- |
| Identity and account security | organizations, users, memberships, roles, permissions, role_permissions, membership_roles, invitations, auth_sessions, password_reset_tokens, email_verification_tokens, mfa_factors, audit_events | Seed/bootstrap CLI, Company access, account recovery, Your sessions, Account security, audit reader |
| Partner/catalog/facilities | sites, partners, partner_role_assignments, partner_contacts, partner_addresses, items, item_variants, item_categories, item_category_assignments, units_of_measure, supplier_items, warehouses, storage_locations, lots, carriers | Catalog and Master data CRUD with archive/frozen identity safeguards |
| Stock and trading | stock_transactions, stock_transaction_lines, stock_balances, stock_transfers, stock_transfer_lines, purchase_orders, purchase_order_lines, goods_receipts, goods_receipt_lines, receipt_documents, production_runs, production_inputs, production_outputs, sales_orders, sales_order_lines, shipments, shipment_lines, shipment_events | Operations draft forms/owned lines, posting, journal reconciliation and compensating receipt/transfer reversal |
| Quality | inspection_templates, inspection_checks, inspections, inspection_results, nonconformances, quality_holds, hold_reviews, quality_documents | Quality criteria/observations/findings, evidence attachment, hold placement and independent review |
| Recall investigation | recall_cases, case_sources, trace_runs, trace_results, case_affected_shipments, case_tasks, case_comments, case_documents, recovery_records | Investigation editor, graph/table snapshots, controlled submit/approve/reopen/closure, task verification, comments and recovery |
| Evidence and communications | recall_notices, notice_deliveries, notice_acknowledgements, documents, notifications, notification_preferences, job_outbox, import_jobs, export_jobs | Recipient notices/portal, private Evidence & reports, notifications, CSV preview/commit, exports, outbox worker |

Organization/account creation is an operator/bootstrap responsibility; invitation acceptance creates accounts and memberships. Tenant access and immutable histories remain protected rather than exposing a universal table editor. The instructor's exact grading interpretation for these controlled lifecycles still needs confirmation.

## Verification boundaries

Local PostgreSQL integration/concurrency tests, real Chromium checks, dependency validation, clean migrations, non-root image validation and database backup/restore provide the evidence listed in STATUS.md. Production storage/scanner/mail SDK responses mocked in tests are adapter tests, not proof of live provider authorization. A database restore does not recover external evidence bytes or a lost MFA encryption key. No public deployment, always-on free worker, measured business SLA, legal retention policy or complete disaster recovery is asserted here.
