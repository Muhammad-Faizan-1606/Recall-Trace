# RecallTrace project instructions

## Product and current state

Build RecallTrace, a batch traceability and product recall investigation application for Web Engineering CSE601330. The selected product connects supplier component lots to production outputs, stock locations, shipments, quality evidence and controlled recall workflows. Its defining experience is an evidence-backed trace graph and investigation workspace.

This folder starts with documentation only. There is no application, database migration, tested dependency lock, passing software suite or deployment yet. The 62 scenarios are planned acceptance cases. Documentation validation is not application verification. Read STATUS.md and inspect the live files before reporting progress; update those records as real implementation replaces this starting state.

The full design targets 100 related ORM models: 72 Core and 28 Expanded. Complete connected workflows in increments and keep the actual schema inventory honest. Do not manufacture empty tables or routes to claim completion. The original rubric requires at least 40 meaningful related SQLAlchemy models and functional CRUD across the schema.

## Read before implementation

1. HANDOFF.md and PLAN.md for decisions, scope and the next deliverable.
2. references/Flask_Project_Rubric.pdf as the authoritative grading source.
3. documentation/docs/01_Project_Proposal.md and 02_Tech_Stack_and_Architecture.md.
4. documentation/source/schema.json and documentation/docs/03_Database_Design.md for the logical model design. Read the relevant model entries before each migration.
5. documentation/docs/06_Trace_and_Business_Rules.md and 07_Security_and_Permissions.md.
6. documentation/docs/11_Rubric_Alignment.md and 12_Requirements_and_Acceptance.md.
7. documentation/docs/04_Routes_and_Screens.md, 05_CRUD_Coverage.md and 08_Test_Plan.md for the current implementation slice.

The Word report is the human-readable overview. Markdown and JSON are the implementation references. If the original rubric and a generated document conflict, record the conflict and follow the rubric while preserving data integrity. Resolve routine design details, record material changes and continue independent work.

## Stack and structure

Use Python, Flask application factory and blueprints, Jinja inheritance/macros, PostgreSQL, SQLAlchemy 2 style models and Alembic migrations through Flask-Migrate. Use Bootstrap with locally served pinned assets and selective vanilla JavaScript. The planned trace presentation uses Cytoscape.js. Shared Redis supports sessions, rate limits and Celery background work. Production runs behind HTTPS using a dedicated WSGI server and private evidence storage.

The documentation proposes Python 3.13, Flask 3.1, Flask-SQLAlchemy 3.1, SQLAlchemy 2.0, PostgreSQL 17 and Celery 5.6 families. Check current support and compatibility, resolve maintained patches, test the result and create accurate pinned requirements.txt and development dependencies. The dependencies.plan.in file is a proposal, not a verified lock. Document any justified version-family change. Do not replace the graded Flask/Jinja application with a frontend-only mockup.

Organize routes, forms, domain services, policies, models, jobs, templates, static assets, migrations and tests clearly. Keep business transactions in services. Preserve the supplied references and distinguish original specifications from subsequent implementation updates.

## Invariants

- Enforce authenticated membership, action permission, company ownership and partner restriction in all reads, writes, files, exports and jobs. UUIDs are identifiers, not access controls.
- Use same-company composite foreign keys between company-owned records. Core migrations must not require Expanded tables; defer their optional foreign keys until expansion.
- Record quantities as Decimal-backed NUMERIC in the SKU base unit. Do not sum unlike SKUs or units.
- Post stock changes atomically with the journal and balance projection. Use stable row-lock order, current state under locks and durable idempotency keys with payload checks.
- Block held stock in every release path. Case approval, genealogy changes and dispatch must obey the documented locking and trace-revision rules.
- Trace only recorded posted genealogy. Deduplicate lots and shipment lines, preserve evidence paths, mark conservative scope and explicitly reject stale or incomplete operational approvals.
- Require independent approval for submitted cases and hold release. Acknowledgement is not proof of physical recovery.
- Keep posted history protected through reversal/version workflows. System tokens, audit rows and derived records follow documented lifecycles rather than arbitrary edit/delete buttons.
- Use real server-side validation, global CSRF, appropriate cookie flags, rotating/revocable server sessions, secure password hashing and shared rate counters. Test the controls with them enabled.
- Keep evidence private, validated and quarantined until accepted. Keep credentials, raw tokens and MFA secrets out of source control, logs and browser output.
- Emit external work through committed durable intent. Record retries and ambiguous deliveries honestly; do not claim exactly-once email delivery.

## Implementation and verification

The requested direction is implementation of the selected design. Briefly inspect the current state and then make the necessary local changes; do not end at another high-level plan. Deliver complete vertical slices with working Jinja screens, domain rules, migrations and meaningful tests. Track completion against PLAN.md and the rubric matrix. Keep STATUS.md and DECISIONS.md current so later sessions can resume without the original chat.

Run relevant tests and fix failures. Use PostgreSQL integration and competing-transaction tests for database claims; SQLite alone cannot verify the target locking behavior. Validate actual setup commands on a clean database. Report exact executed commands and outcomes, unexecuted checks and genuine blockers. Do not claim production readiness or full security based on planned controls.

The instructor's interpretation of CRUD for protected history remains an open grading clarification. Maintain protected records and continue independent foundation/CRUD work while that clarification is pending. Do not invent an instructor answer or silently weaken history integrity.

Use fictional sample companies and .test contact addresses. Do not send real recall communications while developing. Keep external integrations visibly unconfigured until their real behavior has been verified. Explain the code clearly enough for the student team to understand and defend it in a viva.
