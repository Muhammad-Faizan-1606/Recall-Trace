# CRUD coverage and lifecycle evidence

This matrix accounts for all 100 models. Each planned screen is owned by an explicit domain blueprint. Managed child rows are edited through parent forms. No generic unrestricted table editor is required. System records use documented workflows and the instructor interpretation described in the database design must be confirmed before grading claims.

| Model | Phase | Owning screen | Permitted lifecycle |
| --- | --- | --- | --- |
| organizations | Core | Company administration and account security | Create and edit through authorized forms; delete unused records; archive referenced records |
| sites | Core | Company administration and account security | Create and edit through authorized forms; delete unused records; archive referenced records |
| users | Core | Company administration and account security | Create and edit through authorized forms; delete unused records; archive referenced records |
| memberships | Core | Company administration and account security | Create and edit through authorized forms; delete unused records; archive referenced records |
| roles | Core | Company administration and account security | Create and edit through authorized forms; delete unused records; archive referenced records |
| permissions | Core | Company administration and account security | Application migrations and seed process maintain definitions; company users read and assign existing permissions through role forms |
| role_permissions | Core | Company administration and account security | Create update and delete through the owning parent form while the parent is editable |
| membership_roles | Core | Company administration and account security | Create update and delete through the owning parent form while the parent is editable |
| invitations | Core | Company administration and account security | Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed |
| auth_sessions | Core | Company administration and account security | Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed |
| password_reset_tokens | Core | Company administration and account security | Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed |
| email_verification_tokens | Core | Company administration and account security | Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed |
| mfa_factors | Core | Company administration and account security | Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed |
| audit_events | Core | Company administration and account security | System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance |
| partners | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| partner_role_assignments | Core | Partner and catalog forms | Create update and delete through the owning parent form while the parent is editable |
| partner_contacts | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| partner_addresses | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| partner_qualifications | Expanded | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| items | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| item_variants | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| item_categories | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| item_category_assignments | Core | Partner and catalog forms | Create update and delete through the owning parent form while the parent is editable |
| units_of_measure | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| unit_conversions | Expanded | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| supplier_items | Core | Partner and catalog forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| warehouses | Core | Warehouse lot and stock workflow screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| storage_locations | Core | Warehouse lot and stock workflow screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| lots | Core | Warehouse lot and stock workflow screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| serial_units | Expanded | Warehouse lot and stock workflow screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| stock_transactions | Core | Warehouse lot and stock workflow screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| stock_transaction_lines | Core | Warehouse lot and stock workflow screens | Create update and delete through the owning parent form while the parent is editable |
| stock_balances | Core | Warehouse lot and stock workflow screens | System generates or refreshes; scoped reading; supersede results rather than manual editing |
| stock_reservations | Expanded | Warehouse lot and stock workflow screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| stock_transfers | Core | Warehouse lot and stock workflow screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| stock_transfer_lines | Core | Warehouse lot and stock workflow screens | Create update and delete through the owning parent form while the parent is editable |
| stock_counts | Expanded | Warehouse lot and stock workflow screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| stock_count_lines | Expanded | Warehouse lot and stock workflow screens | Create update and delete through the owning parent form while the parent is editable |
| purchase_orders | Core | Purchase and receipt detail forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| purchase_order_lines | Core | Purchase and receipt detail forms | Create update and delete through the owning parent form while the parent is editable |
| supplier_deliveries | Expanded | Purchase and receipt detail forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| supplier_delivery_lines | Expanded | Purchase and receipt detail forms | Create update and delete through the owning parent form while the parent is editable |
| goods_receipts | Core | Purchase and receipt detail forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| goods_receipt_lines | Core | Purchase and receipt detail forms | Create update and delete through the owning parent form while the parent is editable |
| receipt_documents | Core | Purchase and receipt detail forms | Create update and delete through the owning parent form while the parent is editable |
| supplier_returns | Expanded | Purchase and receipt detail forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| supplier_return_lines | Expanded | Purchase and receipt detail forms | Create update and delete through the owning parent form while the parent is editable |
| supplier_return_shipments | Expanded | Purchase and receipt detail forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| bills_of_materials | Expanded | Production and transformation forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| bom_lines | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| production_runs | Core | Production and transformation forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| production_run_steps | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| production_inputs | Core | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| production_outputs | Core | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| production_allocations | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| lot_transformations | Expanded | Production and transformation forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| lot_transformation_inputs | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| lot_transformation_outputs | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| production_deviations | Expanded | Production and transformation forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| production_documents | Expanded | Production and transformation forms | Create update and delete through the owning parent form while the parent is editable |
| inspection_templates | Core | Inspection quality issue and hold review screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| inspection_checks | Core | Inspection quality issue and hold review screens | Create update and delete through the owning parent form while the parent is editable |
| inspections | Core | Inspection quality issue and hold review screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| inspection_results | Core | Inspection quality issue and hold review screens | Create update and delete through the owning parent form while the parent is editable |
| test_methods | Expanded | Inspection quality issue and hold review screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| test_samples | Expanded | Inspection quality issue and hold review screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| test_results | Expanded | Inspection quality issue and hold review screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| nonconformances | Core | Inspection quality issue and hold review screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| nonconformance_actions | Expanded | Inspection quality issue and hold review screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| quality_holds | Core | Inspection quality issue and hold review screens | Authorized workflow creates and reads; active hold reason is preserved; independent review releases the hold and appends its decision; active history is not deleted |
| hold_reviews | Core | Inspection quality issue and hold review screens | System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance |
| quality_documents | Core | Inspection quality issue and hold review screens | Create update and delete through the owning parent form while the parent is editable |
| sales_orders | Core | Sales dispatch and return forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| sales_order_lines | Core | Sales dispatch and return forms | Create update and delete through the owning parent form while the parent is editable |
| shipments | Core | Sales dispatch and return forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| shipment_lines | Core | Sales dispatch and return forms | Create update and delete through the owning parent form while the parent is editable |
| shipment_serial_assignments | Expanded | Sales dispatch and return forms | Create update and delete through the owning parent form while the parent is editable |
| carriers | Core | Sales dispatch and return forms | Create and edit through authorized forms; delete unused records; archive referenced records |
| shipment_events | Core | Sales dispatch and return forms | System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance |
| delivery_confirmations | Expanded | Sales dispatch and return forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| customer_returns | Expanded | Sales dispatch and return forms | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| customer_return_lines | Expanded | Sales dispatch and return forms | Create update and delete through the owning parent form while the parent is editable |
| recall_cases | Core | Investigation workspace | Full CRUD in draft; active case changes use explicit authorized transitions; approved scope is revised through a fresh trace and approval; closed cases retain history |
| case_sources | Core | Investigation workspace | Create update and delete through the owning parent form while the parent is editable |
| trace_runs | Core | Investigation workspace | System generates or refreshes; scoped reading; supersede results rather than manual editing |
| trace_results | Core | Investigation workspace | System generates or refreshes; scoped reading; supersede results rather than manual editing |
| case_affected_shipments | Core | Investigation workspace | System generates or refreshes; scoped reading; supersede results rather than manual editing |
| case_tasks | Core | Investigation workspace | Create and edit through authorized forms; delete unused records; archive referenced records |
| case_comments | Core | Investigation workspace | Authorized authors create and amend comments while a case permits discussion; edits and removals preserve prior content in protected history |
| case_documents | Core | Investigation workspace | Create update and delete through the owning parent form while the parent is editable |
| recall_notices | Core | Investigation workspace | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| notice_deliveries | Core | Investigation workspace | System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing |
| notice_acknowledgements | Core | Investigation workspace | System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance |
| recovery_records | Core | Investigation workspace | System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance |
| documents | Core | Evidence inbox preferences import and export screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| notifications | Core | Evidence inbox preferences import and export screens | System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing |
| notification_preferences | Core | Evidence inbox preferences import and export screens | Create and edit through authorized forms; delete unused records; archive referenced records |
| job_outbox | Core | Evidence inbox preferences import and export screens | System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing |
| import_jobs | Core | Evidence inbox preferences import and export screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
| export_jobs | Core | Evidence inbox preferences import and export screens | Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed |
