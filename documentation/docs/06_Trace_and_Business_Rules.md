# Trace algorithm and business rules

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
