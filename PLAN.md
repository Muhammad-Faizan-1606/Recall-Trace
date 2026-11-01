# RecallTrace implementation plan

This plan carries the selected specification into implementation. Work in dependency order; each slice includes its UI, service rules, migrations and verification. The full target is the documented 100-model product. Core 72 must be coherent and complete before the 28-model expansion is presented as delivered.

## M1 Foundation and first working slice

Inspect the current files and available Python, PostgreSQL, Redis, browser-test and container tools. Bootstrap the Flask factory, environment configuration, extensions, domain package structure and Jinja base layout. Establish reviewed migrations and a tested dependency lock. Implement secure login and explicit company/membership/permission context sufficient for a real authorized catalog slice. Seed two fictional companies, a permitted user and a read-only user through documented development commands.

Deliver item/variant/base-unit CRUD using explicit routes with UUID converters, WTForms validation, CSRF, flash messages and successful POST redirects. Related records must belong to the same company. Unused records can be deleted and referenced records follow the documented archive policy. Validate a clean database migration and test positive CRUD, invalid form rejection, foreign-company lookup/write rejection, role denial and repeat-submit behavior. Do not generate all 100 empty models as a substitute for this slice.

Record setup commands actually run, successful and failing tests, current migration/model inventory and remaining scope in STATUS.md. If PostgreSQL or an external prerequisite is unavailable, state the exact limitation and continue work that can be verified without claiming the blocked integration passed.

## M2 Complete access and master data

Complete invitations, verification/recovery flows, rotating/revocable sessions, privileged MFA, role administration, partners, warehouses, locations and lot identity. Use the documented scope and permission matrix. Exercise control-specific tests with CSRF, rate limiting and production cookie behavior enabled.

## M3 Reliable stock and production history

Implement purchase receipts, the immutable stock journal and transactional balance projection, transfers, production inputs/outputs, idempotent posting and stable lock order. Verify rollback, competing consumption, hold checks and genealogy cycle prevention with separate PostgreSQL connections.

## M4 Quality and investigation

Implement versioned inspections, nonconformances, holds and independent release, case creation, upstream/downstream tracing, graph/table views and independent approval. Test overlapping roots/paths, missing or partial data, stale trace revisions and concurrent dispatch/hold operations.

## M5 Complete Core workflows

Implement private evidence, authorized CSV imports/exports, durable job outbox, recipient notices, acknowledgements, verified recovery/disposition and closure. Finish the selected 72-model inventory with real workflows and planned lifecycle coverage. Demonstrate the complete C10 fixture and cross-company/partner isolation.

## M6 Expanded workflows

Implement the 28 additional models with their features and tested migrations: qualifications, advance delivery records, BOM revisions, explicit allocations, split/merge/repack, serials, reservations, stock counts, sample testing, corrective actions, delivery evidence and returns. Prove clean full installation and Core-to-Expanded upgrade. Count only actual implemented model tables; keep the logical schema synchronized with justified design changes.

## M7 Verification and submission

Run relevant unit, PostgreSQL integration/concurrency and browser tests, dependency/secret checks, reproducible workload measurement and a backup/restore exercise. Fill the rubric evidence matrix using actual file paths, commands, results and screenshots. Update the application README, remaining limitations, demo guide and viva notes. Retain the distinction between target performance/security and observed evidence.

## Open grading clarification

Confirm whether the instructor accepts owned-parent editing for association rows and controlled lifecycle/reversal operations for protected history. Keep this pending item visible without blocking unrelated implementation or exposing an arbitrary audit/ledger editor.
