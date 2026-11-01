# RecallTrace Project Specification

Technical Design and Rubric Alignment

Web Engineering CSE601330

31 October 2026

Version 1.0

We will build a Flask application that connects supplier lots, production batches and shipments to support product recall investigations. This specification defines the user workflows, technical stack, related database model plan, security controls, acceptance tests and submission evidence for that work.

The design covers 100 models across nine domains, with 72 Core models and 28 Expanded models. Implementation and execution evidence follow the specification. The companion developer pack contains the full field dictionary, per-model lifecycle matrix, detailed requirements, route patterns and test cases.

## Reading guide

The proposal explains the product and demonstration. The rubric matrix connects the design to the marking scheme. Architecture and business rules define the implementation approach. The model inventory specifies the scope. Security, verification, operations and delivery sections define how the team will establish a working release.

# 1 Project proposal and scope

We will build RecallTrace as a Flask web application for investigating reported product defects through recorded batch history. Quality staff will start with a suspect component or product lot, identify connected production batches and shipments, coordinate an approved response, and record the resulting follow up. The main experience is a traceability investigation supported by evidence and controlled operational workflows.

The project serves Web Engineering CSE601330. Its implementation must demonstrate routing, Jinja inheritance, SQLAlchemy relationships and CRUD, validated forms, cookies and sessions, testing, and reproducible setup. This specification defines planned behavior and acceptance evidence. Software test cases are not execution results.

## Problem and proposed value

When component, production and shipment records are disconnected, staff must manually reconstruct where a suspect batch went. RecallTrace will connect those records and show why each lot or shipment is in scope. An authorized reviewer will approve the response; the system will then track stock holds, partner communications, acknowledgements, recovery evidence and closure. A trace indicates recorded relationships and potential exposure; it does not establish the physical cause of a defect.

GS1 guidance describes how batch and serial identifiers support targeted recall actions [S09]. RecallTrace will use stable lot identifiers and preserve event history. The course product does not claim GS1 certification, regulatory compliance, or validation for a particular industry.

## Users and operational setting

The initial setting is one fictional electronics manufacturer with its own supplier, warehouse, production and customer records. Each additional company receives a separate workspace. Partner accounts receive restricted views of their own approved notices and acknowledgements. The platform operator does not obtain routine access to company business data through a business administrator role.

The principal users are company owners, quality managers, production operators, warehouse operators, recall coordinators, auditors and restricted partner viewers. An illustrative pilot could include 25 factory staff and 15 retailer contacts. These 40 possible accounts are a sizing example, not measured adoption or impact. Beneficiaries beyond those accounts depend on actual shipments and the available contact records.

## Scope and release boundaries

The complete design contains 100 distinct ORM model definitions. The first coherent release contains 72 Core models; the Expanded release adds 28 models for serial tracking, advanced transformations, sample testing and return workflows. These are logical model targets, not implemented tables. A release may only claim features that work through their documented UI and services. The submitted database inventory must match the implemented release and contain at least 40 meaningful related models.

Core includes company access, privileged authentication, partner and SKU records, purchase receipts, stock movements, production inputs and outputs, inspection evidence, holds, bidirectional tracing, case approval, recipient notices, recovery records, private files, imports, exports and audit history. All Core screens and workflows must be complete before Expanded work enters the release.

Expanded includes supplier qualifications and advance delivery records, explicit partial production allocations, BOM revisions, split/merge/repack workflows, serial units, reservations, stock counts, sample methods and results, corrective actions, delivery confirmations and supplier/customer returns.

Real carrier APIs, ERP synchronization, physical IoT devices, payment processing, autonomous safety decisions and legal compliance assessments are outside this release. Notices use a local email sink in development; external delivery is configured and verified separately.

## Reference demonstration

A supplier delivers lot SWITCH C10 containing 200 switches. Production run A consumes 100 switches and produces 100 lamps in lot LAMP L1. Run B consumes 50 switches and produces 50 lamps in lot LAMP L2. Shipment S1 sends 60 L1 lamps to Retailer One. Shipment S2 sends 50 L2 lamps to Retailer Two. The warehouse retains 40 L1 lamps and 50 unused switches. A separate source lot C11 feeds an unrelated 70 lamp lot L3 and shipment S3.

A quality manager reports a problem against C10. A downstream trace identifies L1 and L2 and their relevant shipments while leaving L3 and S3 outside the recorded lineage. The display shows 150 potentially affected finished lamps, including 110 dispatched lamps and 40 lamps still on hand. It reports the 50 remaining switches separately because quantities from different SKUs are not added together.

The coordinator submits the case. An independent quality manager approves a current complete trace. Holds block the affected on hand lots. Approved recipient specific notices are queued. Staff record acknowledgement and verification of recovered or otherwise resolved quantities. Case closure requires completed mandatory tasks and an approved disposition for remaining exposure. Core recovery evidence does not silently create a warehouse receipt; physical stock reentry requires its own authorized stock posting.

## Outcomes to measure

Measure the time to identify recorded affected shipments, accuracy against known trace fixtures, unauthorized access failures, stock reconciliation differences, repeated posting prevention, notice delivery status and the completeness of closure evidence. Measure actual results during testing and a pilot; do not substitute table count or hypothetical customer numbers for these outcomes.

# 2 Rubric alignment

Source S01 is the supplied course rubric. Its eight criteria total 100 marks. The 40 related table/model minimum is a hard submission requirement. This matrix maps intended implementation and future proof; it does not award a grade or certify that those features already exist.

| Criterion | Marks | Planned implementation | Evidence | Planned tests |
| --- | --- | --- | --- | --- |
| Project Setup and Structure | 10 | Virtual environment; accurate locked requirements.txt; app factory; blueprints; migrations; separate configuration. | README setup transcript; dependency lock; app/__init__.py; app/extensions.py; migrations; clean startup. | T056 T058 |
| Routing and View Functions | 15 | Focused route functions with GET forms and POST mutations; UUID converters; permission and company guards. | docs/04_Routes_and_Screens.md; application route map; 404 405 409 and PRG demonstrations. | T001 T007 T013 T054 |
| Templates and Jinja2 Usage | 15 | Shared base layout; extends and block; macros for fields tables pagination; explicit loops and conditionals. | templates/base.html; macros/forms.html; macros/pagination.html; template review and narrow viewport screenshots. | T031 T055 |
| Database Integration and CRUD | 20 | 100 related model design; Core 72 and Expanded 28; primary keys foreign keys checks unique constraints; full mapped business CRUD. | docs/03_Database_Design.md; source/schema.json; docs/05_CRUD_Coverage.md; ERDs; migrated model inventory. | T011 T012 T014 T018 T026 T056 T057 |
| Forms Validation Cookies and Sessions | 15 | Flask WTF server validation; business constraints; shared server sessions; CSRF; flash messages; 303 Post Redirect Get. | forms and domain validators; session settings; invalid input and cookie inspection; repeat POST demonstration. | T005 T006 T009 T013 T054 |
| Code Quality and Organization | 10 | Small views; domain services; explicit transaction ownership; typed naming conventions; Ruff and reviewed migrations. | Module boundaries; review checklist; lint output; readable service implementation and no duplicated layouts. | T057 |
| Functionality and Testing | 10 | Complete described release; PostgreSQL integration and concurrency tests; browser workflow and operational checks. | docs/08_Test_Plan.md; requirements traceability; test results; documented defects and full demo transcript. | T001 T016 T022 T033 T059 T060 T061 T062 |
| Documentation | 5 | Purpose setup environment variables migrations seed data run commands role guide test guide and known limitations. | This specification; developer pack README and planned application README contract; fresh teammate setup. | T056 T061 |

## Submission checks

- Selected release tables and ORM classes match the implemented feature inventory and exceed the 40-model minimum.
- All related business screens demonstrate permitted CRUD with validated forms and correct methods.
- Jinja inheritance macros loops and conditionals are shown with actual records.
- Successful forms use flash feedback and Post Redirect Get; CSRF and session behavior are demonstrated.
- The application runs from a clean setup using accurate dependency environment migration and seed instructions.
- Meaningful tests run against the actual database behavior and the full recall workflow.
- README identifies supported features configured integrations limitations and acknowledgements.
- Protected-history CRUD interpretation and the separately issued submission rules are recorded.

The documentation criterion can be prepared now; setup functionality security and testing criteria require implementation and actual verification. Tables above describe that work precisely so later evidence can be attached.

# 3 Technical stack and architecture

## Selected baseline

The baseline below is an engineering decision for this project. It is not a claim that every selected major or minor release is the newest. At bootstrap, resolve compatible current maintenance patches, run the acceptance checks, review dependency advisories and licenses, and commit an accurate pinned requirements.txt. The dependency proposal included here is not that tested lock file. Sources S02 to S14 support the selected framework and security patterns.

| Layer | Selection | Purpose |
| --- | --- | --- |
| Language | Python 3.13 | Supported baseline; select the current maintenance patch and test all dependencies. |
| Web framework | Flask 3.1 family | Application factory and domain blueprints; server rendered requests remain central. |
| Templates and interface | Jinja2 Bootstrap 5.3 vanilla JavaScript | Shared layouts and macros; assets pinned and served locally; keyboard and narrow screen support. |
| Database | PostgreSQL 17 | Transactions constraints row locking and recursive queries; use a supported maintenance release. |
| ORM and migrations | Flask SQLAlchemy 3.1 SQLAlchemy 2.0 Alembic through Flask Migrate | Typed SQLAlchemy 2 style models; reviewed forward migrations; no db.create_all in production. |
| Driver | Psycopg 3 | PostgreSQL connection adapter with explicit pool limits. |
| Forms | Flask WTF WTForms email validator | CSRF field validation and domain validation beyond browser attributes. |
| Authentication | Flask Login Flask Session argon2 cffi PyOTP | Server session rotation revocation Argon2id password hashing and privileged TOTP checks. |
| Shared state and tasks | Redis compatible shared service Celery 5.6 Flask Limiter redis extras | Shared sessions rate counters and task broker; authoritative intent and business state remain in PostgreSQL. |
| Trace graph | PostgreSQL recursive CTE Cytoscape.js | Company scoped traversal on the server; graph is a presentation of authorized results. |
| Evidence storage | Private object storage adapter | Private shared storage in deployment; isolated private local storage for development. |
| Deployment | Linux containers Gunicorn HTTPS reverse proxy | Non root runtime; explicit trusted proxy counts and allowed hosts. |
| Verification | pytest Playwright Ruff pip audit Locust | PostgreSQL integration and concurrency browser checks formatting dependency review and measured workload tests. |

## Application structure

Use a modular Flask application with blueprints for auth, company, catalog, receiving, inventory, production, quality, tracing, recalls, partners and reports. Routes translate HTTP into form and service calls. Services enforce permissions, company boundaries, state transitions and transaction ownership. Models express persistence and constraints. Jobs call the same scoped services; they do not bypass rules.

The planned application package contains app/__init__.py, app/extensions.py, app/config.py, app/models, app/blueprints, app/services, app/policies, app/jobs, app/templates and app/static. The repository also contains migrations, tests/unit, tests/integration, tests/concurrency, tests/browser, tests/operational, requirements.txt, requirements-dev.txt, .env.example, Dockerfile and README.md. This documentation package contains no runnable application package yet.

Each blueprint owns its views, forms and templates. Shared Jinja macros handle fields, error summaries, pagination, confirmation forms and tables. A shared base template owns navigation, document structure and flash messages. Domain services never import view functions. Views do not call commit in the middle of a service operation. One reviewed service owns each business transaction [S07].

## Request and trust boundaries

The browser connects over HTTPS to the reverse proxy and production WSGI workers. The application validates identity, active company membership, action permission, object ownership, CSRF and request limits before performing a mutation. PostgreSQL stores business state and the session registry. Shared Redis state supports server sessions, rate limits and the task broker. Private storage holds evidence bytes. Background workers process durable outbox intentions after commit and recheck the relevant authorization.

The company UUID in a URL is untrusted input. It must match an active membership and every related object must belong to that company. UUIDs reduce accidental collisions; they do not replace authorization. A partner restriction is applied in addition to company scope and action permissions. Hidden navigation is only a usability choice.

## Jobs and delivery

The business transaction creates an outbox row with a unique deduplication key. A publisher claims committed pending rows and submits work to Celery. PostgreSQL remains the source for job progress. Workers use bounded retries and idempotent service operations. Redis redelivery can occur; the workflow must tolerate it [S12]. A worker revalidates current company and requester access before generating or delivering sensitive content.

For notice delivery, use provider idempotency where available and retain the provider reference. If a send times out after the provider may have accepted it, mark the attempt ambiguous and reconcile it; do not claim exactly once email delivery or blindly repeat it. Domain stock posting remains idempotent independently of external delivery.

## Growth and performance

Scale web and worker processes independently behind shared state. Use company scoped composite indexes and stable paginated lists. Eager load bounded related data rather than issuing one query per row. Keep graph computation separate from graph display and move large exports and trace computations to workers. Invalidate any cached trace using the company trace revision and access scope. Measure before adding infrastructure.

PostgreSQL 17 is a supported selected major; deployments must use its current maintenance release [S06]. Flask production deployment uses a dedicated WSGI server with the development debugger disabled [S04]. Database migrations and object storage backups require a controlled deployment procedure rather than execution from a web request.

## Architecture decisions

ADR01 uses one modular application so the team can share transactions and deployment while preserving domain boundaries. ADR02 keeps Jinja rendering central to satisfy the template rubric. ADR03 uses PostgreSQL for both testing and deployment of relational and concurrency behavior. ADR04 uses a relational genealogy instead of adding a graph database before measurements justify it. ADR05 uses server sessions with explicit revocation. ADR06 uses durable outbox delivery. ADR07 supports immutable posted history through controlled correction workflows. Each later change must record its rationale and effect on tests and migrations.

# 4 Requirements and acceptance

| ID | Requirement | Phase | Acceptance |
| --- | --- | --- | --- |
| FR01 | Company and partner scope | Core | Company A cannot read or change any Company B object or job result; partner users see only approved information for their partner. |
| FR02 | Authentication lifecycle | Core | Invalid expired and reused tokens fail; password reset and membership removal invalidate relevant active access. |
| FR03 | Permission management | Core | Changing navigation cannot bypass a denied server action; last active owner is protected. |
| FR04 | Privileged multifactor verification | Core | A reused time step or recovery code fails and a revoked factor cannot authorize an action. |
| FR05 | Catalog and counterparties | Core | Related CRUD works with server validation; referenced master records archive instead of breaking history. |
| FR06 | Locations and lots | Core | Duplicate internal lot codes and cross company parent relationships are rejected. |
| FR07 | Receipt posting | Core | A receipt posts journal and balance changes once; invalid rows or overreceipt roll back the entire transaction. |
| FR08 | Production posting | Core | Posting atomically consumes and produces stock; rejects unavailable stock held lots and cyclic ancestry. |
| FR09 | Inventory transfer | Core | The transfer preserves total quantity and cannot release held stock. |
| FR10 | Inspection records | Core | Completed inspections retain their criterion version; invalid observation types fail validation. |
| FR11 | Quality holds | Core | Held lots cannot be consumed dispatched or transferred to evade a hold; release checks reviewer independence. |
| FR12 | Case creation | Core | Draft cases support CRUD; root lots and evidence belong to the same company and refer to consistent records. |
| FR13 | Bidirectional tracing | Core | The trace reports direction algorithm version data revision and completeness; repeated paths do not duplicate affected lot identities. |
| FR14 | Trace presentation | Core | Both views contain the same authorized lot set; truncated display is clearly separated from computation completeness. |
| FR15 | Case approval | Core | Approval revalidates revision and exposure applies holds atomically and requires an independent approver. |
| FR16 | Recall communication | Core | No unapproved stale or cross partner content is delivered; failed and ambiguous deliveries remain visible. |
| FR17 | Acknowledgements and recovery | Core | Duplicate acknowledgements are harmless; quantity and return allocations cannot be counted twice. |
| FR18 | Case closure | Core | Mandatory tasks are verified trace is current and complete and remaining exposure has a recorded disposition. |
| FR19 | Private evidence | Core | Quarantined unsupported oversized and unauthorized files cannot be downloaded; URLs do not bypass checks. |
| FR20 | CSV import | Core | All rows pass validation before atomic commit; duplicate submission is idempotent; imports never write posted tables directly. |
| FR21 | Exports | Core | Authorization is checked at execution and download; formula like cell values are rendered safely for spreadsheets. |
| FR22 | Search and dashboards | Core | Totals reconcile to the same filtered data and no unbounded list query is used. |
| FR23 | Audit history | Core | Business users cannot rewrite audit events or recover credentials from audit details. |
| FR24 | Background delivery | Core | A rollback creates no external work; retries do not duplicate stock events and ambiguous email delivery is reconciled. |
| FR25 | Advanced production mapping | Expanded | Expanded mappings preserve ancestry and applicable quantity rules; unknown allocations remain conservative. |
| FR26 | Serial and count operations | Expanded | Serial identities are unique; stock count adjustments remain journaled and reservations cannot exceed available quantity. |
| FR27 | Sample testing | Expanded | Sample and result evidence stays associated with the correct lot and method revision. |
| FR28 | Return workflows | Expanded | Return quantities remain bounded by original received or shipped quantities; returned customer stock enters quarantine. |
| FR29 | Usable forms and feedback | Core | Valid POST redirects to GET; invalid input preserves safe submitted values with field errors and no database change. |
| FR30 | Controlled record lifecycle | Core | The per model CRUD matrix identifies owner screen permitted operations and immutable record handling. |

## Nonfunctional acceptance targets

| ID | Area | Target and verification |
| --- | --- | --- |
| NFR01 | Isolation | Every company and partner boundary applies equally to synchronous and queued operations. T001 to T004 T045 T062 |
| NFR02 | Integrity | Posted journal reconciles to balances; no invalid negative stock or cyclic genealogy commits. T014 to T022 T050 |
| NFR03 | Security verification | Applicable ASVS controls have implementation and test evidence with recorded gaps. Security checklist and T005 to T010 T040 to T048 |
| NFR04 | Performance target | On a recorded 4 vCPU 8 GiB benchmark environment: p95 common list GET below 1 second at 25 concurrent users and trace of 5000 lots 25000 edges below 5 seconds of worker compute. T059; targets are unverified until measured; report queue time separately |
| NFR05 | Bounded processing | Initial page size 25 maximum 100; evidence 10 MiB; CSV 10000 rows and 10 MiB; graph display 500 nodes; compute limit 10000 lots. T029 T040 T042 T046 |
| NFR06 | Recovery target | Initial deployment planning targets RPO 24 hours and RTO 4 hours; actual restore exercise establishes achieved values. T060 |
| NFR07 | Accessibility | Labeled controls keyboard navigation visible focus error association meaningful table headers and graph alternative. T031 T055 |
| NFR08 | Maintainability | Focused blueprints services typed interfaces consistent formatting reviewed migrations and a dependency lock. Ruff review migration and clean setup output |
| NFR09 | Observability | Structured redacted logs correlation IDs job failure visibility queue age and stock reconciliation checks. T035 T048 T049 |
| NFR10 | Reproducibility | A teammate can install migrate seed run and demonstrate the selected release from documented steps. T056 T061 |

# 5 Database design and inventory

## Model conventions

The model inventory defines 100 distinct SQLAlchemy ORM classes, including association objects. Core has 72 models and Expanded adds 28. Application migration tables are not counted as product models. Each included model must participate in a working feature. The schema.json file provides columns, nullability, foreign key targets, lifecycle and business constraints for every model; it is a logical design, not an executable migration.

Primary keys use UUID. Company owned tables include organization_id and UNIQUE (organization_id, id). For foreign keys between two company owned records, use composite organization_id plus target_id foreign keys to the corresponding organization_id plus id key. A plain UUID foreign key alone does not enforce company consistency. Users, permissions and user authentication records intentionally have global identity; company access still requires membership. Protect membership and role associations with same company constraints.

All times are timezone aware UTC timestamps. User interfaces may display local time explicitly. Quantities use NUMERIC(20,6) and the SKU base unit. Timestamps include created_at and updated_at; version supports optimistic concurrency. Master records include archived_at. Immutable records retain initial metadata without enabling arbitrary edits. Bounded text fields have length validation in forms and services.

Column nullability is documented in schema.json. Foreign key nullability follows that file. Other columns are required unless marked nullable. Database defaults such as timestamps version=1 and safe status values must be added and verified in migration review. Server defaults must not silently approve workflows. Foreign key identifiers require appropriate indexes; prioritize company plus status/date and company plus lot keys for measured access paths.

Unique constraints must explicitly handle optional values. For example, one effective acknowledgement per notice is unique on notice_id; optional evidence parents use partial unique indexes and exactly one parent checks. Do not assume a nullable UNIQUE key prevents all duplicate null combinations. Case insensitive email identity uses a unique lower(email) index.

## Relationships and record lifecycles

Partner records describe counterparties and do not authorize access. Restricted memberships explicitly connect external users to a partner. A variant identifies the SKU and base unit. A lot identifies a stable internal batch. Production inputs and outputs connect lots through a posted production run. Split merge or repack events add another explicit input/output path in Expanded. Posted shipments connect lot quantities to recorded customer orders.

Stock transactions and their signed lines are the authoritative movement history. Stock balances are a transactional projection, not an editable stock field. Holds are checked at every stock release path. Inspections preserve their template revision. Cases refer to root lots, versioned trace computations, shipment exposure, work tasks and recipient notices. Acknowledgements and recovery records retain the relevant notice and shipment identity.

Master data supports create read update and delete when unused. Referenced master data archives. Draft business documents and their children support full CRUD. Posted business fields are protected; reversals or new revisions correct historical events. Cases and holds permit only their explicitly defined later state transitions. Security tokens expire are consumed or are revoked. Derived and operational data is generated and maintained by scoped workflows.

The course wording requires CRUD across the schema. Confirm with the instructor whether protected system records and posted history may use documented lifecycle operations instead of arbitrary update/delete forms. This interpretation remains a submission clarification, not a reason to make audit or stock history editable. The CRUD coverage file accounts for every model and the application will demonstrate all four operations across eligible business entities.

## Company constraints and deletion

Use RESTRICT for posted business parents and evidence references. Use owned-child deletion only when the parent is still eligible for deletion. Association rows may cascade with an unused parent; never cascade posted genealogy shipment or audit history away through an ordinary delete. A database migration account has separate privileges from the runtime account. Runtime privileges and triggers must prevent unauthorized mutation of protected history while permitting documented service transitions.

Core migrations must not require Expanded tables. Optional foreign keys from a Core model to an Expanded entity are deferred until the Expanded migration. The Core service ignores those optional features. Before adding an expansion, migrate and test both the clean full installation and the upgrade from the completed Core release.

## Module inventory

| Module | Core | Expanded | Total |
| --- | --- | --- | --- |
| Company identity and access | 14 | 0 | 14 |
| Partners and catalog | 10 | 2 | 12 |
| Facilities and inventory | 8 | 4 | 12 |
| Receiving and purchasing | 5 | 5 | 10 |
| Production and genealogy | 3 | 9 | 12 |
| Quality and holds | 8 | 4 | 12 |
| Shipping and distribution | 6 | 4 | 10 |
| Recall investigations | 12 | 0 | 12 |
| Shared operations | 6 | 0 | 6 |

## Full model inventory

Purposes fields nullability constraints and parent relationships for every model are in docs/03_Database_Design.md and source/schema.json.

| Number | Model table | Phase |
| --- | --- | --- |
| 1 | organizations | Core |
| 2 | sites | Core |
| 3 | users | Core |
| 4 | memberships | Core |
| 5 | roles | Core |
| 6 | permissions | Core |
| 7 | role_permissions | Core |
| 8 | membership_roles | Core |
| 9 | invitations | Core |
| 10 | auth_sessions | Core |
| 11 | password_reset_tokens | Core |
| 12 | email_verification_tokens | Core |
| 13 | mfa_factors | Core |
| 14 | audit_events | Core |
| 15 | partners | Core |
| 16 | partner_role_assignments | Core |
| 17 | partner_contacts | Core |
| 18 | partner_addresses | Core |
| 19 | partner_qualifications | Expanded |
| 20 | items | Core |
| 21 | item_variants | Core |
| 22 | item_categories | Core |
| 23 | item_category_assignments | Core |
| 24 | units_of_measure | Core |
| 25 | unit_conversions | Expanded |
| 26 | supplier_items | Core |
| 27 | warehouses | Core |
| 28 | storage_locations | Core |
| 29 | lots | Core |
| 30 | serial_units | Expanded |
| 31 | stock_transactions | Core |
| 32 | stock_transaction_lines | Core |
| 33 | stock_balances | Core |
| 34 | stock_reservations | Expanded |
| 35 | stock_transfers | Core |
| 36 | stock_transfer_lines | Core |
| 37 | stock_counts | Expanded |
| 38 | stock_count_lines | Expanded |
| 39 | purchase_orders | Core |
| 40 | purchase_order_lines | Core |
| 41 | supplier_deliveries | Expanded |
| 42 | supplier_delivery_lines | Expanded |
| 43 | goods_receipts | Core |
| 44 | goods_receipt_lines | Core |
| 45 | receipt_documents | Core |
| 46 | supplier_returns | Expanded |
| 47 | supplier_return_lines | Expanded |
| 48 | supplier_return_shipments | Expanded |
| 49 | bills_of_materials | Expanded |
| 50 | bom_lines | Expanded |
| 51 | production_runs | Core |
| 52 | production_run_steps | Expanded |
| 53 | production_inputs | Core |
| 54 | production_outputs | Core |
| 55 | production_allocations | Expanded |
| 56 | lot_transformations | Expanded |
| 57 | lot_transformation_inputs | Expanded |
| 58 | lot_transformation_outputs | Expanded |
| 59 | production_deviations | Expanded |
| 60 | production_documents | Expanded |
| 61 | inspection_templates | Core |
| 62 | inspection_checks | Core |
| 63 | inspections | Core |
| 64 | inspection_results | Core |
| 65 | test_methods | Expanded |
| 66 | test_samples | Expanded |
| 67 | test_results | Expanded |
| 68 | nonconformances | Core |
| 69 | nonconformance_actions | Expanded |
| 70 | quality_holds | Core |
| 71 | hold_reviews | Core |
| 72 | quality_documents | Core |
| 73 | sales_orders | Core |
| 74 | sales_order_lines | Core |
| 75 | shipments | Core |
| 76 | shipment_lines | Core |
| 77 | shipment_serial_assignments | Expanded |
| 78 | carriers | Core |
| 79 | shipment_events | Core |
| 80 | delivery_confirmations | Expanded |
| 81 | customer_returns | Expanded |
| 82 | customer_return_lines | Expanded |
| 83 | recall_cases | Core |
| 84 | case_sources | Core |
| 85 | trace_runs | Core |
| 86 | trace_results | Core |
| 87 | case_affected_shipments | Core |
| 88 | case_tasks | Core |
| 89 | case_comments | Core |
| 90 | case_documents | Core |
| 91 | recall_notices | Core |
| 92 | notice_deliveries | Core |
| 93 | notice_acknowledgements | Core |
| 94 | recovery_records | Core |
| 95 | documents | Core |
| 96 | notifications | Core |
| 97 | notification_preferences | Core |
| 98 | job_outbox | Core |
| 99 | import_jobs | Core |
| 100 | export_jobs | Core |

# 6 Trace algorithm and business rules

## Trace meaning

The default trace is conservative. If an input lot participates in a posted production run, all outputs of that run are potentially related unless an approved explicit allocation proves a narrower recorded mapping. The application must label conservative scope and distinguish recorded evidence from assumptions. It cannot infer unrecorded physical movements. Imported unresolved references and incomplete genealogy are visible data quality issues.

Build directed edges from production_inputs joined to production_outputs by their posted production run. Expanded adds transformation inputs joined to outputs. Restrict both sides to the authenticated company and permitted object scope. Reverse those edges for upstream traversal. A warehouse transfer changes location, not lot ancestry.

## Traversal procedure

1. Validate root lots company permissions and requested direction. Record the company trace_revision and algorithm version.
2. Start a bounded recursive query from the unique root IDs. Track visited IDs and path membership to avoid cycling. PostgreSQL recursive queries and cycle facilities support this pattern [S13].
3. Traverse only posted events. Deduplicate reached lots independently of path multiplicity. Preserve at least one reproducible evidence path and the underlying event IDs for each result.
4. Join the resulting lot set to posted shipment lines once per unique shipment line. Do not count a shipment again because two roots or two paths reach it.
5. Store the result in a new trace_run with its direction revision limits scope basis and completeness. Limit or data consistency failures produce an explicit incomplete result.
6. Present an authorized graph and a table. A graph display cap never changes the computed exposure set. A large full trace can run in a background job; a capped computation cannot authorize operational decisions.

Bound execution time depth and node count, and record which limit was reached. The initial proposed display limit is 500 nodes and the compute limit 10000 lots; the benchmark workload and actual deployment determine whether these defaults need adjustment. Keep accessible table pagination and authorized exports available. Never silently label a partial result complete.

## Quantity accounting

Report quantities by variant and its base unit. Do not sum switches and finished lamps or combine different units. Trace reachability alone does not give a proven defective unit count. Distinguish potential related quantity from verified recovered quantity. In Core, consuming any suspect input makes every output lot of that run potentially related.

Shipment exposure is keyed by shipment_line_id. Multiple paths do not multiply it. Physical returns, confirmed destruction and other dispositions are separate categories. quantity_recovered counts verified physical recovery; quantity_resolved counts all permitted verified dispositions. Neither may exceed eligible dispatched quantity, and the same physical return allocation must not resolve units twice. Returned goods do not become available stock without a separate warehouse receipt into quarantine.

Stock reconciliation groups posted signed journal lines by lot and location and compares the sum with stock_balances. A transfer conserves quantity for the same SKU. A production run may convert different component quantities into output units; never enforce equality between unlike units. A same variant split/merge transformation conserves base quantity unless a separately approved loss event records a difference.

## Posting transaction and competing requests

A posting service validates the active membership and permission, begins one database transaction, checks its unique idempotency key and payload digest, locks relevant lots and balance rows in stable UUID order, refreshes ORM state under the locks, checks holds and available quantities, writes the document journal and projection, records audit/outbox intent, and commits once. Exceptions roll back the whole operation. A retry with the same key and payload returns the original result; a changed payload with the same key returns 409.

Genealogy-changing operations and recall approval acquire the company's trace guard before their lot locks. They increment trace_revision on committed genealogy changes. No service acquires this guard after holding a lot lock. Other stock services lock the same relevant lot records so a concurrent hold and dispatch cannot both proceed on stale checks. This conservative company genealogy guard is an initial consistency tradeoff; measure its contention before redesigning it.

Approval acquires the trace guard and lot locks, verifies that the completed trace revision is still current, refreshes shipment exposure, validates independent authorization, creates the required holds and outbox intentions, and commits the case transition atomically. If lineage changed, recompute instead of approving stale scope. Shipping rechecks holds after acquiring the lot lock. A draft preview never creates holds or sends notices.

## Workflow states

Cases move through draft, submitted, approved, active, pending_closure and closed, with rejected or cancelled branches before operational approval. Submission records submitted_by_id. Approval requires a different eligible membership and recent MFA. Active scope changes require a new trace and approval. A closed case can reopen only through an explicit authorized event with a reason.

Receipts production and shipment documents move from draft to posted through a validated service; rejection preserves the draft with errors. Reversals create compensating events and link to the original. Holds are active until an independent review authorizes release. Notice revisions move through draft, approved, queued and delivery states. Acknowledgement concerns one notice revision and does not by itself prove physical recovery.

Closure requires a current complete trace, verified mandatory tasks, reviewed acknowledgement exceptions, reconciled recovery quantities and a recorded disposition for remaining exposure. The quality manager decides whether the evidence meets company policy. No status automatically certifies product safety or legal compliance.

# 7 Security and permission plan

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

# 8 Routes screens forms and templates

## HTTP conventions

The following route patterns are a design inventory. The <resource> notation describes separate explicit blueprint routes; it is not permission to create an unvalidated generic model editor. UUID converters demonstrate typed variable path handling. GET is read only. Form mutations use POST with CSRF; REST PUT or DELETE is not required to demonstrate correct HTML form handling.

Return 303 after a successful form mutation. Invalid forms render 200 or a documented 422 with field errors and unchanged business data. Return 404 for an inaccessible company/object, 403 for a known object with a forbidden action when disclosure is permitted, 405 for unsupported methods, 409 for stale versions/state/idempotency conflicts, 413 for oversized uploads and 429 for rate limits. Render safe 500 pages with a correlation ID while logging redacted details.

| Action | Methods | Suffix after company prefix |
| --- | --- | --- |
| List and create | GET POST | lots |
| Detail | GET | lots/<uuid:lot_id> |
| Edit | GET POST | lots/<uuid:lot_id>/edit |
| Delete eligible draft | POST | lots/<uuid:lot_id>/delete |
| Post receipt | POST | receipts/<uuid:receipt_id>/post |
| Run trace | POST | cases/<uuid:case_id>/traces |
| View trace | GET | traces/<uuid:trace_id> |
| Approve case | POST | cases/<uuid:case_id>/approve |
| Dispatch shipment | POST | shipments/<uuid:shipment_id>/dispatch |
| Download evidence | GET | documents/<uuid:document_id>/download |

Every company business route uses the prefix /o/<uuid:organization_id>. Authentication routes use /auth. The complete guarded inventory is in docs/04_Routes_and_Screens.md.

## Main screens

The dashboard summarizes scoped open cases active holds awaiting approvals pending acknowledgements and operational failures. Catalog screens manage partners SKUs units categories sites warehouses and lots. Transaction screens manage draft orders receipts production runs transfers and shipments with their owned lines. Quality screens show inspection versions observations holds and release review. The investigation workspace combines case details root lots graph and table evidence tasks impacted shipments notices recovery and audit events. Partner screens expose only approved recipient information. Administration screens manage invitations roles sessions MFA and configuration.

Use a Jinja base.html with named title navigation content and scripts blocks. Shared macros provide field errors CSRF hidden fields pagination lifecycle action buttons and confirmation forms. Pages must demonstrate extends block loops and conditionals with real data. Use an accessible table as an alternative to the graph. Server-rendered empty states explain the next permitted action. Disabled or hidden controls do not replace service permission checks.

## Server validation examples

Validate required bounded strings email addresses UUID identity date ordering positive decimal quantities supported unit precision same company parents and allowed state transitions. Reject negative zero excessive precision unavailable stock duplicate internal lot codes cycles self-approval stale versions and invalid notice recipients. A field can pass HTML validation while still failing these business rules.

Keep safe submitted values when a form fails; never repopulate password or secret enrollment fields. Flash success and failure messages must accurately reflect the committed result. Include a version hidden field for optimistic editing and a server-issued idempotency key for stock posting. Tests must demonstrate a successful redirect and a rejected mutation that leaves the database unchanged.

# 9 Testing and release evidence

This plan defines 62 acceptance scenarios. All software test results start as Not executed. A defined case is not an automated test implementation and a completed specification is not a passing application.

## Test environments

Use isolated PostgreSQL for relational integrity transaction and concurrency tests. SQLite-only tests cannot establish PostgreSQL row lock or constraint behavior. Each test has independent fixtures. Browser tests use seeded fictional company and partner accounts and a local email sink. Security test configurations explicitly enable CSRF rate limits and production cookie/header behavior for the relevant checks. Convenience fixtures may disable a control only in unrelated tests and must never be cited as verification of that control.

Unit cases cover permitted state transitions traversal result normalization unit precision and rule decisions. Integration cases exercise database services and authenticated requests. Concurrency cases use separate committed database connections and synchronization barriers rather than two calls within one session. Browser cases verify the complete Jinja workflow. Operational cases exercise real migration configuration and recovery procedures.

## Representative acceptance cases

The complete 62-case inventory and requirement mapping are in docs/08_Test_Plan.md and source/specification.json. All cases remain Not executed until the application exists.

| ID | Scenario | Expected result |
| --- | --- | --- |
| T001 | Read a foreign company lot using its UUID | 404 and no foreign record metadata |
| T004 | Partner A requests Partner B notice case view or acknowledgement | 404 and no partner B content |
| T006 | Reset password or revoke a session then reuse old cookies | Old session rejected on the next authenticated request |
| T009 | Submit mutating forms with missing or incorrect CSRF token | 400 or documented CSRF failure response; no write |
| T016 | Post the same receipt concurrently with one idempotency key | One posting; repeated request resolves to the original result |
| T018 | Consume the same available stock from two production runs | Only valid total consumption commits; balances never become negative |
| T022 | Dispatch or consume stock while a hold is being approved | Serialized result honors the committed hold and preserves valid history |
| T026 | Trace A to B and C then both to D | D appears once with valid path evidence |
| T029 | Trace reaches a configured node or time limit | is_complete false with reason; approval cannot proceed |
| T030 | Post new genealogy after trace completion before case approval | Stale revision rejected and a fresh trace is required |
| T033 | Approve a case while a relevant shipment is dispatched | Latest committed eligible exposure is included and future release is held |
| T037 | Allocate the same returned quantity to two recovery entries | Second over allocation rejected; recovery stays bounded |
| T040 | Upload executable disguised as PDF HTML SVG and oversized evidence | Unsupported or mismatched content quarantined or rejected |
| T049 | Crash after business commit before queue publication | Outbox publisher recovers pending intent without another stock posting |
| T056 | Upgrade a clean PostgreSQL database and inspect ORM metadata | Selected release model inventory matches migrated tables and constraints |
| T060 | Restore PostgreSQL and file metadata to a fresh environment | Record counts journal reconciliation and evidence references validate |
| T061 | Run the fictional defective switch recall scenario | Receipt production trace approval notice acknowledgement recovery and closure complete |
| T062 | Run the same scenario with foreign company and partner identities | Forbidden records and evidence remain inaccessible |

## Release evidence

Keep a dated result record for each implemented case with software commit environment selected release fixture version command outcome and failure reference. Record successful and failed runs. The release must have no unresolved authorization stock integrity trace completeness or destructive migration defect. A percentage coverage target alone is not a release criterion.

Run formatting and static checks once the implementation exists, then meaningful unit and PostgreSQL integration/concurrency tests, then browser end-to-end checks, dependency and secret scans, workload measurement and a restore exercise. New failures or changed code determine what needs rerunning. Do not report benchmark or security results that were not measured.

## Demonstration script

Use the C10 L1 L2 L3 fixture defined in the project proposal. Demonstrate master record CRUD and server validation first. Post receipt and production show journal reconciliation and dispatch S1/S2. Create a case run a trace inspect path evidence and exclude unrelated S3. Attempt a forbidden cross-company lookup and an invalid self approval. Approve using the independent quality account show held-stock dispatch rejection queue notices to the local email sink record acknowledgement and recovery evidence and complete closure checks. Refresh a successful POST destination to demonstrate PRG. Show the selected model inventory Jinja inheritance route converters and README setup.

# 10 Setup deployment and operations

## Repository and dependency setup

This is the setup contract for the implementation phase. The companion pack contains specifications and a dependency proposal; it does not contain the application or runnable Flask commands yet. When bootstrap is complete, replace this contract in the application README with commands verified from a clean checkout.

Create a Python 3.13 virtual environment. On Linux/macOS use python3 -m venv .venv and activate .venv/bin/activate. On Windows use py -3.13 -m venv .venv and activate .venv/Scripts/Activate.ps1 in PowerShell. Resolve the dependency proposal in an isolated environment, test it, and commit exact production and development dependency versions with reproducible hashes where supported.

The planned local service set is PostgreSQL shared Redis a private development evidence volume and an email sink. Docker Compose is the preferred repeatable development option; a documented direct Python option remains available. Secrets are generated locally and never committed. Use fictional seed data and reserved .test email addresses. No default administrator password is shipped; the bootstrap administrator is created through a one-time local command.

The Linux image must include libmagic for content inspection. Production evidence scanning needs a configured malware scanner adapter and endpoint; ClamAV is the initial integration candidate. SCAN_MODE and SCANNER_ENDPOINT select it. Scanner outage leaves evidence quarantined. The direct Windows development guide must document the corresponding native file-inspection dependency or use the container path.

## Planned application commands

After the application package and service files exist, the README must verify: pip install -r requirements.txt; flask --app wsgi:app db upgrade; flask --app wsgi:app seed-demo; flask --app wsgi:app create-owner; flask --app wsgi:app run --debug for local development; python -m pytest for the appropriate suites; and a Celery worker invocation for app.jobs.celery_app. Production uses Gunicorn wsgi:app with explicit workers timeouts and graceful shutdown behind HTTPS. These command names are an implementation contract, not commands validated in this documentation delivery.

## Environment variables

APP_ENV selects development testing or production. SECRET_KEY is a generated signing/CSRF secret. DATABASE_URL uses the configured PostgreSQL driver. SESSION_REDIS_URL RATELIMIT_STORAGE_URI and CELERY_BROKER_URL select authenticated shared services. Their separate logical Redis databases are a local convenience rather than a security boundary. MFA_ENCRYPTION_KEY is supplied through a secret manager or protected deployment environment. ALLOWED_HOSTS and TRUSTED_PROXY_HOPS configure the known ingress. STORAGE_BACKEND and its private bucket/credentials configure evidence storage. MAIL_MODE and mail credentials select the local sink or approved external service. LOG_LEVEL controls redacted logs. No environment value is printed by a failure page.

Production startup rejects missing or placeholder secrets debug mode SQLite process-local sessions/rate limits publicly readable evidence and incomplete required endpoints. Development relaxations require explicit configuration; production never inherits a development fallback key. Keep database broker and storage services private to the application network. Apply least privilege credentials and do not expose development email or database consoles publicly.

## Deploy and recover

Build a non-root Linux image from the reviewed source commit and lock file. Validate configuration before changing live state. Back up the database and evidence manifest before reviewed migrations, apply migrations once through the deployment job, start web/workers, verify readiness and perform smoke tests. Liveness exposes only process state; readiness verifies required services without revealing credentials or company data. A rollback plan considers database compatibility and may require a forward fix rather than destructive downgrade.

Back up PostgreSQL evidence objects and encryption-key recovery material through separate protected channels. The initial recovery planning targets are a 24-hour RPO and 4-hour RTO, subject to a measured restore exercise. Test restoration to a fresh environment using inventory counts journal reconciliation trace fixtures and file checksums. Record achieved timings and any missing objects. A database dump alone does not restore missing evidence files or keys.

## Monitoring and retention

Monitor error rates request latency queue age retry/ambiguous deliveries trace failures stale approvals active hold dispatch attempts and stock reconciliation differences. Alert the designated operator with redacted identifiers. Configure retention by data category and approved company policy; do not invent legal retention periods. Expire temporary exports and tokens and remove abandoned quarantined files through scoped maintenance jobs. Retain posted operational history until an authorized retention procedure permits disposition.

## Cost and external services

The classroom demonstration can use local containers a local email sink and synthetic records without a paid AI API. Hosting email storage monitoring and backup costs depend on the selected provider and workload; no price estimate is asserted here. Choose providers after the deployment requirements and budget are known.

# 11 Delivery plan and responsibilities

The team has at least four active builders and more than four weeks before submission. Use dependency-based milestones below and assign actual dates after confirming the calendar deadline weekly availability and skills. A complete 100-model release is an ambitious target; milestone completion is demonstrated by evidence rather than an assumed weekly table count. Reserve a final verification period instead of treating it as spare feature time.

| Milestone | Outcome | Work | Completion evidence |
| --- | --- | --- | --- |
| M1 | Foundation and design review | Confirm instructor CRUD interpretation; finalize ERDs permissions lifecycle; bootstrap factory PostgreSQL migrations and shared templates. | Fresh install and one protected Jinja CRUD slice |
| M2 | Company access and master records | Implement invitations sessions MFA roles partners SKUs units sites warehouses and lots. | Cross company tests and related master CRUD |
| M3 | Journal receipts and production | Implement atomic posting idempotency genealogy and stock projection. | Receipt rollback competing consumption and acyclic trace fixtures |
| M4 | Quality and investigation | Implement inspections holds traces case approval and graph/table views. | Stale scope self approval and concurrent hold tests |
| M5 | Communication and complete Core | Implement notices acknowledgement recovery jobs private evidence imports exports and documentation. | Complete 72 model Core inventory and end-to-end demonstration |
| M6 | Expanded modules | Add 28 expansion models only with their screens services migrations and tests. | Complete 100 model inventory and regression evidence |
| M7 | Verification and submission | Freeze features fix defects measure workload restore backups rehearse viva and finish actual run instructions. | Reproducible release evidence and documented limitations |

## Ownership

Builder One owns company access authentication permissions shared configuration and deployment. Builder Two owns partners catalog purchasing receipt forms and private evidence associations. Builder Three owns production stock journal transfers holds and transaction/concurrency behavior. Builder Four owns tracing recall cases notices recovery and the graph/table investigation interface. Quality inspection and test fixtures are reviewed jointly by Builders Three and Four. Additional builders can own imports exports notifications browser accessibility and the operational verification suite.

Each owner delivers the UI forms services migrations and tests for their module. One rotating schema maintainer sequences migrations and reviews cross-module constraints. Another owner reviews every sensitive authorization or stock-posting change. Merge small working increments; do not create separate applications that only integrate near submission.

## Definition of done

A feature has a documented actor permission and state transition; usable Jinja screens; server and database validation; meaningful fixtures; permitted CRUD/lifecycle behavior; negative and positive checks; and updated documentation. It has no placeholder success response for an unavailable integration. A release adds clean installation migrations seed data a complete demonstration operational configuration checks and an actual test report.

## Rubric interpretation to confirm

Ask the instructor whether supporting associations can be managed through parent forms and whether append-only audit/history and consumed security tokens may use documented lifecycle operations. Retain the answer in the project log. All mutable business entities still need create read update and delete demonstrations. The instructor also communicates deadline submission format and group-work policy separately, as noted in the rubric.

## Academic integrity and viva

The team must review and understand all submitted code and acknowledge reused libraries boilerplate and assistive tools according to instructor policy. Each member should explain a route converter Jinja inheritance a model relationship a server validator CSRF/session behavior a database transaction an isolation test and the complete recall demonstration. Do not present these planning documents as evidence that software is implemented or secure.

Suggested viva questions include why a lot differs from a SKU; why graph reachability is not a proven defect count; how duplicate trace paths are handled; why a hold and shipment use the same lock boundary; how a partner is scoped; how an old trace becomes stale; why posted stock uses reversals; and what a clean setup and restore exercise actually verified.

# 12 Sources and design basis

Official references checked on 31 October 2026. The selected baseline must be reviewed again when dependencies are locked. External sources guide design; they do not validate the resulting implementation.

## S01 Course provided Flask Project Rubric

Flask_Project_Rubric(1).pdf

Pages 2 to 4; course CSE601330; 100 marks; minimum 40 related SQLAlchemy tables.

## S02 Flask installation

https://flask.palletsprojects.com/en/stable/installation/

Virtual environments and supported Python versions.

## S03 Flask security considerations

https://flask.palletsprojects.com/en/stable/web-security/

CSRF cookies headers host validation and bounded requests.

## S04 Flask production deployment

https://flask.palletsprojects.com/en/stable/deploying/

Dedicated production WSGI server and proxy configuration.

## S05 Flask SQLAlchemy quick start

https://flask-sqlalchemy.palletsprojects.com/en/stable/quickstart/

SQLAlchemy 2 style model and session usage.

## S06 PostgreSQL versioning policy

https://www.postgresql.org/support/versioning/

Use current maintenance release of a supported major.

## S07 SQLAlchemy transactions

https://docs.sqlalchemy.org/en/20/orm/session_transaction.html

Explicit transaction boundaries and rollback.

## S08 OWASP ASVS

https://asvs.owasp.org/

Applicable security requirements and verification evidence.

## S09 GS1 retail traceability guideline

https://ref.gs1.org/guidelines/2d-in-retail/

Batch and serial identifiers support targeted recall workflows.

## S10 Flask Limiter storage configuration

https://flask-limiter.readthedocs.io/en/stable/configuration.html

Shared persistent counters instead of process local rate limits.

## S11 Flask Session security

https://flask-session.readthedocs.io/en/latest/security.html

Server session identifier regeneration.

## S12 Celery Redis broker

https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html

Worker delivery retry and Redis broker configuration.

## S13 PostgreSQL recursive queries

https://www.postgresql.org/docs/17/queries-with.html

Recursive traversal and cycle handling.

## S14 OWASP password storage

https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

Argon2id password hashing guidance.
