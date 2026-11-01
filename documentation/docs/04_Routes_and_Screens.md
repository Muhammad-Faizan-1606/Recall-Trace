# Routes screens forms and templates

## HTTP conventions

The following route patterns are a design inventory. The <resource> notation describes separate explicit blueprint routes; it is not permission to create an unvalidated generic model editor. UUID converters demonstrate typed variable path handling. GET is read only. Form mutations use POST with CSRF; REST PUT or DELETE is not required to demonstrate correct HTML form handling.

Return 303 after a successful form mutation. Invalid forms render 200 or a documented 422 with field errors and unchanged business data. Return 404 for an inaccessible company/object, 403 for a known object with a forbidden action when disclosure is permitted, 405 for unsupported methods, 409 for stale versions/state/idempotency conflicts, 413 for oversized uploads and 429 for rate limits. Render safe 500 pages with a correlation ID while logging redacted details.

| Area | Route pattern | Methods | Guard |
| --- | --- | --- | --- |
| Authentication | /auth/register /auth/login /auth/reset /auth/verify /auth/mfa | GET POST | Public forms with limits CSRF and safe errors |
| Session management | /auth/logout /auth/sessions/<uuid:session_id>/revoke | POST | Authenticated user and session ownership |
| Company administration | /o/<uuid:organization_id>/memberships | GET POST | Owner and company scope |
| Master record list and create | /o/<uuid:organization_id>/<resource> | GET POST | Resource-specific action and company scope |
| Master detail | /o/<uuid:organization_id>/<resource>/<uuid:record_id> | GET | Scoped object read |
| Edit form | /o/<uuid:organization_id>/<resource>/<uuid:record_id>/edit | GET POST | Edit permission optimistic version and server validation |
| Delete or archive | /o/<uuid:organization_id>/<resource>/<uuid:record_id>/delete | POST | Lifecycle eligibility and CSRF; explicit confirmation |
| Business posting | /o/<uuid:organization_id>/receipts/<uuid:receipt_id>/post | POST | Receive permission idempotency stock locks and whole transaction |
| Production posting | /o/<uuid:organization_id>/production-runs/<uuid:run_id>/post | POST | Production permission genealogy and stock validation |
| Shipment dispatch | /o/<uuid:organization_id>/shipments/<uuid:shipment_id>/dispatch | POST | Dispatch permission available quantity and hold recheck |
| Case submit | /o/<uuid:organization_id>/cases/<uuid:case_id>/submit | POST | Coordinator state validation |
| Trace computation | /o/<uuid:organization_id>/cases/<uuid:case_id>/traces | POST | Trace permission; creates computation record; redirects to status |
| Trace graph and table | /o/<uuid:organization_id>/traces/<uuid:trace_id> | GET | Scoped result read; graph and table from same authorized result |
| Case approval and closure | /o/<uuid:organization_id>/cases/<uuid:case_id>/approve or /close | POST | Independent eligible quality manager recent MFA current trace |
| Notice approval and delivery | /o/<uuid:organization_id>/notices/<uuid:notice_id>/approve or /send | POST | Current case scope explicit approval and deduplicated delivery intent |
| Acknowledgement | /o/<uuid:organization_id>/notices/<uuid:notice_id>/acknowledge | POST | Own recipient scope or authorized recorded acknowledgement |
| Private evidence | /o/<uuid:organization_id>/documents/<uuid:document_id>/download | GET | Live object authorization and clean scan status |
| Imports | /o/<uuid:organization_id>/imports and /imports/<uuid:job_id>/commit | GET POST | Allowed import kind dry run all rows validation and idempotency |
| Exports | /o/<uuid:organization_id>/exports | GET POST | Scoped request and execution; private expiring result |
| Audit and reports | /o/<uuid:organization_id>/audit and /reports | GET | Read permission redacted fields pagination |

## Main screens

The dashboard summarizes scoped open cases active holds awaiting approvals pending acknowledgements and operational failures. Catalog screens manage partners SKUs units categories sites warehouses and lots. Transaction screens manage draft orders receipts production runs transfers and shipments with their owned lines. Quality screens show inspection versions observations holds and release review. The investigation workspace combines case details root lots graph and table evidence tasks impacted shipments notices recovery and audit events. Partner screens expose only approved recipient information. Administration screens manage invitations roles sessions MFA and configuration.

Use a Jinja base.html with named title navigation content and scripts blocks. Shared macros provide field errors CSRF hidden fields pagination lifecycle action buttons and confirmation forms. Pages must demonstrate extends block loops and conditionals with real data. Use an accessible table as an alternative to the graph. Server-rendered empty states explain the next permitted action. Disabled or hidden controls do not replace service permission checks.

## Server validation examples

Validate required bounded strings email addresses UUID identity date ordering positive decimal quantities supported unit precision same company parents and allowed state transitions. Reject negative zero excessive precision unavailable stock duplicate internal lot codes cycles self-approval stale versions and invalid notice recipients. A field can pass HTML validation while still failing these business rules.

Keep safe submitted values when a form fails; never repopulate password or secret enrollment fields. Flash success and failure messages must accurately reflect the committed result. Include a version hidden field for optimistic editing and a server-issued idempotency key for stock posting. Tests must demonstrate a successful redirect and a rejected mutation that leaves the database unchanged.
