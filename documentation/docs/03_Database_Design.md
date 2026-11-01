# Database design and dictionary

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

| Number | Model table | Phase | Purpose |
| --- | --- | --- | --- |
| 1 | organizations | Core | Company workspace and trace revision guard |
| 2 | sites | Core | Factory office or operating site |
| 3 | users | Core | Login identity shared through explicit memberships |
| 4 | memberships | Core | User participation and optional partner restriction |
| 5 | roles | Core | Company permission bundles |
| 6 | permissions | Core | Application defined authorization actions |
| 7 | role_permissions | Core | Permission assignments to company roles |
| 8 | membership_roles | Core | Role assignments to company memberships |
| 9 | invitations | Core | Expiring employee or partner invitations |
| 10 | auth_sessions | Core | Revocable server session registry |
| 11 | password_reset_tokens | Core | Single use password recovery challenges |
| 12 | email_verification_tokens | Core | Single use email ownership challenges |
| 13 | mfa_factors | Core | Encrypted TOTP factors and hashed recovery codes |
| 14 | audit_events | Core | Application append only event history |
| 15 | partners | Core | Local supplier customer or distributor record |
| 16 | partner_role_assignments | Core | Supplier customer and distributor classification |
| 17 | partner_contacts | Core | Authorized operational contact details |
| 18 | partner_addresses | Core | Delivery or business address records |
| 19 | partner_qualifications | Expanded | Supplier certificates and review dates |
| 20 | items | Core | Product component or packaging family |
| 21 | item_variants | Core | Traceable stock keeping unit |
| 22 | item_categories | Core | Company catalog taxonomy |
| 23 | item_category_assignments | Core | Catalog classification associations |
| 24 | units_of_measure | Core | Quantity units for company SKUs |
| 25 | unit_conversions | Expanded | Approved same dimension unit conversions |
| 26 | supplier_items | Core | Supplier item codes and lead time records |
| 27 | warehouses | Core | Company stock facilities |
| 28 | storage_locations | Core | Warehouse bins or holding areas |
| 29 | lots | Core | Stable internal identity for a traceable batch |
| 30 | serial_units | Expanded | Individual units tracked inside a lot |
| 31 | stock_transactions | Core | Receipt consumption output transfer return or reversal posting |
| 32 | stock_transaction_lines | Core | Signed quantity changes by lot and location |
| 33 | stock_balances | Core | Transactional projection of the stock journal |
| 34 | stock_reservations | Expanded | Stock earmarked for production or dispatch |
| 35 | stock_transfers | Core | Controlled movement between warehouses |
| 36 | stock_transfer_lines | Core | Transfer quantities and bin selection |
| 37 | stock_counts | Expanded | Physical inventory counting session |
| 38 | stock_count_lines | Expanded | Expected and counted lot quantities |
| 39 | purchase_orders | Core | Supplier order for traceable inputs |
| 40 | purchase_order_lines | Core | Ordered variant quantities in base units |
| 41 | supplier_deliveries | Expanded | Supplier advance shipment notification |
| 42 | supplier_delivery_lines | Expanded | Announced quantities against purchase lines |
| 43 | goods_receipts | Core | Goods accepted into a warehouse |
| 44 | goods_receipt_lines | Core | Received purchase quantities with lot identity |
| 45 | receipt_documents | Core | Receipt evidence attachments |
| 46 | supplier_returns | Expanded | Return of received goods to their supplier |
| 47 | supplier_return_lines | Expanded | Return quantities against received lots |
| 48 | supplier_return_shipments | Expanded | One dispatch record for an approved supplier return |
| 49 | bills_of_materials | Expanded | Versioned planned component recipe |
| 50 | bom_lines | Expanded | Planned component requirements |
| 51 | production_runs | Core | Recorded conversion of input lots into output lots |
| 52 | production_run_steps | Expanded | Execution and signoff of production steps |
| 53 | production_inputs | Core | Lot quantities consumed by a production run |
| 54 | production_outputs | Core | New lot quantities produced by a production run |
| 55 | production_allocations | Expanded | Explicit partial input to output mapping |
| 56 | lot_transformations | Expanded | Split merge or repack outside manufacturing |
| 57 | lot_transformation_inputs | Expanded | Input lots in a split merge or repack |
| 58 | lot_transformation_outputs | Expanded | Resulting lots in a split merge or repack |
| 59 | production_deviations | Expanded | Recorded departure from a production procedure |
| 60 | production_documents | Expanded | Production evidence attachments |
| 61 | inspection_templates | Core | Versioned lot inspection definitions |
| 62 | inspection_checks | Core | Recorded criteria inside a template |
| 63 | inspections | Core | Inspection of an identified lot |
| 64 | inspection_results | Core | Observations and decisions for inspection checks |
| 65 | test_methods | Expanded | Versioned sample test procedures |
| 66 | test_samples | Expanded | Sample custody and collection from a lot |
| 67 | test_results | Expanded | Reviewed results for a sample and test method |
| 68 | nonconformances | Core | Quality issue recorded against a lot |
| 69 | nonconformance_actions | Expanded | Corrective and preventive work on a quality issue |
| 70 | quality_holds | Core | Restriction on consuming or shipping a lot |
| 71 | hold_reviews | Core | Independent decision to retain or release a hold |
| 72 | quality_documents | Core | Inspection or nonconformance evidence attachments |
| 73 | sales_orders | Core | Customer demand and destination |
| 74 | sales_order_lines | Core | Ordered variant quantities |
| 75 | shipments | Core | Dispatch workflow against one customer order |
| 76 | shipment_lines | Core | Exact lot quantities sent against an order line |
| 77 | shipment_serial_assignments | Expanded | Serialized units included in a shipment line |
| 78 | carriers | Core | Company carrier directory |
| 79 | shipment_events | Core | Dispatch transit delivery and correction timeline |
| 80 | delivery_confirmations | Expanded | Evidence of receipt at destination |
| 81 | customer_returns | Expanded | Customer goods returned from a prior shipment |
| 82 | customer_return_lines | Expanded | Returned quantities from specific shipment lines |
| 83 | recall_cases | Core | Investigation approval recovery and closure workflow |
| 84 | case_sources | Core | Root lots and evidence starting an investigation |
| 85 | trace_runs | Core | Versioned trace computation at a recorded data revision |
| 86 | trace_results | Core | Deduplicated affected lots and recorded path evidence |
| 87 | case_affected_shipments | Core | Frozen shipment exposure associated with a trace |
| 88 | case_tasks | Core | Assigned investigation and recovery work |
| 89 | case_comments | Core | Attributed investigation discussion |
| 90 | case_documents | Core | Evidence attached to an investigation |
| 91 | recall_notices | Core | Reviewed recipient specific recall communication |
| 92 | notice_deliveries | Core | Delivery attempts for an approved notice |
| 93 | notice_acknowledgements | Core | Verified acknowledgement of a notice revision |
| 94 | recovery_records | Core | Verified quantities recovered or otherwise resolved |
| 95 | documents | Core | Private uploaded evidence and generated exports |
| 96 | notifications | Core | In application user notifications |
| 97 | notification_preferences | Core | Membership event and channel choices |
| 98 | job_outbox | Core | Durable intent to perform work after commit |
| 99 | import_jobs | Core | Validated atomic CSV import lifecycle |
| 100 | export_jobs | Core | Authorized export generation and expiry |

## Detailed field dictionary

The shared constraints above apply in addition to each record below. Business invariants that depend on multiple rows require an atomic service and concurrency tests as well as available database constraints.

### 1 Organization

Table `organizations`. Module Company identity and access. Release Core.

Company workspace and trace revision guard.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| name | VARCHAR(120) | No | name |
| slug | VARCHAR(80) | No | slug |
| status | VARCHAR(20) | No | status |
| trace_revision | BIGINT | No | trace revision |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: No parent foreign key; referenced by related models.

Constraints and invariants: Unique slug; trace_revision >= 0; organizations cannot be deleted while business records exist.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 2 Site

Table `sites`. Module Company identity and access. Release Core.

Factory office or operating site.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(120) | No | name |
| address_text | TEXT | No | address text |
| country_code | CHAR(2) | No | country code |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 3 User

Table `users`. Module Company identity and access. Release Core.

Login identity shared through explicit memberships.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| email | VARCHAR(254) | No | email |
| display_name | VARCHAR(120) | No | display name |
| password_hash | TEXT | No | password hash |
| active | BOOLEAN | No | active |
| email_verified_at | TIMESTAMPTZ | Yes | email verified at |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |
| auth_version | INTEGER | No | Incremented on password reset or global session revocation |

Foreign keys: No parent foreign key; referenced by related models.

Constraints and invariants: Unique lower(email); password hash and security details excluded from ordinary serializers.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 4 Membership

Table `memberships`. Module Company identity and access. Release Core.

User participation and optional partner restriction.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| status | VARCHAR(20) | No | status |
| joined_at | TIMESTAMPTZ | Yes | joined at |
| user_id | UUID | No | Reference to users |
| partner_id | UUID | Yes | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); user_id -> users.id (required); partner_id -> partners.id (optional).

Constraints and invariants: Unique organization and user; partner membership always restricts the object scope.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 5 Role

Table `roles`. Module Company identity and access. Release Core.

Company permission bundles.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(50) | No | code |
| name | VARCHAR(80) | No | name |
| protected | BOOLEAN | No | protected |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code; protected owner role cannot be removed from the last active owner.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 6 Permission

Table `permissions`. Module Company identity and access. Release Core.

Application defined authorization actions.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| code | VARCHAR(100) | No | code |
| description | VARCHAR(240) | No | description |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: No parent foreign key; referenced by related models.

Constraints and invariants: Unique code; application managed definitions.

Lifecycle: Application migrations and seed process maintain definitions; company users read and assign existing permissions through role forms.

### 7 RolePermission

Table `role_permissions`. Module Company identity and access. Release Core.

Permission assignments to company roles.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| role_id | UUID | No | Reference to roles |
| permission_id | UUID | No | Reference to permissions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); role_id -> roles.id (required); permission_id -> permissions.id (required).

Constraints and invariants: Unique role and permission.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 8 MembershipRole

Table `membership_roles`. Module Company identity and access. Release Core.

Role assignments to company memberships.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| membership_id | UUID | No | Reference to memberships |
| role_id | UUID | No | Reference to roles |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); membership_id -> memberships.id (required); role_id -> roles.id (required).

Constraints and invariants: Unique membership and role; both belong to the same organization.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 9 Invitation

Table `invitations`. Module Company identity and access. Release Core.

Expiring employee or partner invitations.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| email | VARCHAR(254) | No | email |
| token_digest | CHAR(64) | No | token digest |
| expires_at | TIMESTAMPTZ | No | expires at |
| accepted_at | TIMESTAMPTZ | Yes | accepted at |
| invited_by_id | UUID | No | Reference to memberships |
| partner_id | UUID | Yes | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); invited_by_id -> memberships.id (required); partner_id -> partners.id (optional).

Constraints and invariants: Unique token_digest; invitation cannot grant roles above the issuer authority.

Lifecycle: Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed.

### 10 AuthSession

Table `auth_sessions`. Module Company identity and access. Release Core.

Revocable server session registry.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| token_digest | CHAR(64) | No | token digest |
| expires_at | TIMESTAMPTZ | No | expires at |
| last_seen_at | TIMESTAMPTZ | No | last seen at |
| revoked_at | TIMESTAMPTZ | Yes | revoked at |
| auth_version | INTEGER | No | auth version |
| user_id | UUID | No | Reference to users |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| last_mfa_at | TIMESTAMPTZ | Yes | Last successful step up verification |

Foreign keys: user_id -> users.id (required).

Constraints and invariants: Unique token_digest; session reference required by authenticated request validation.

Lifecycle: Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed.

### 11 PasswordResetToken

Table `password_reset_tokens`. Module Company identity and access. Release Core.

Single use password recovery challenges.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| token_digest | CHAR(64) | No | token digest |
| expires_at | TIMESTAMPTZ | No | expires at |
| used_at | TIMESTAMPTZ | Yes | used at |
| user_id | UUID | No | Reference to users |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: user_id -> users.id (required).

Constraints and invariants: Unique token_digest; consume once in a transaction; reset revokes existing sessions.

Lifecycle: Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed.

### 12 EmailVerificationToken

Table `email_verification_tokens`. Module Company identity and access. Release Core.

Single use email ownership challenges.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| token_digest | CHAR(64) | No | token digest |
| expires_at | TIMESTAMPTZ | No | expires at |
| used_at | TIMESTAMPTZ | Yes | used at |
| user_id | UUID | No | Reference to users |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: user_id -> users.id (required).

Constraints and invariants: Unique token_digest; no token plaintext in logs or database.

Lifecycle: Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed.

### 13 MfaFactor

Table `mfa_factors`. Module Company identity and access. Release Core.

Encrypted TOTP factors and hashed recovery codes.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| kind | VARCHAR(20) | No | kind |
| secret_ciphertext | TEXT | No | secret ciphertext |
| key_version | VARCHAR(20) | No | key version |
| recovery_code_hashes | JSONB | No | recovery code hashes |
| last_used_step | BIGINT | Yes | last used step |
| verified_at | TIMESTAMPTZ | Yes | verified at |
| user_id | UUID | No | Reference to users |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: user_id -> users.id (required).

Constraints and invariants: Reject reused TOTP step; consume recovery hashes atomically; expose enrollment secret only during setup.

Lifecycle: Security workflow creates; owner or administrator may inspect safe metadata and revoke or consume; secrets never displayed.

### 14 AuditEvent

Table `audit_events`. Module Company identity and access. Release Core.

Application append only event history.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| action | VARCHAR(100) | No | action |
| entity_kind | VARCHAR(60) | No | entity kind |
| entity_id | UUID | Yes | entity id |
| safe_details | JSONB | No | safe details |
| correlation_id | UUID | No | correlation id |
| actor_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); actor_id -> memberships.id (optional).

Constraints and invariants: Actor may be null for system events; no credentials or document contents in details.

Lifecycle: System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance.

### 15 Partner

Table `partners`. Module Partners and catalog. Release Core.

Local supplier customer or distributor record.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(160) | No | name |
| status | VARCHAR(20) | No | status |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code; partner records do not grant external access.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 16 PartnerRoleAssignment

Table `partner_role_assignments`. Module Partners and catalog. Release Core.

Supplier customer and distributor classification.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| role_code | VARCHAR(20) | No | role code |
| partner_id | UUID | No | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); partner_id -> partners.id (required).

Constraints and invariants: Unique partner and role_code; allowed values supplier customer distributor.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 17 PartnerContact

Table `partner_contacts`. Module Partners and catalog. Release Core.

Authorized operational contact details.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| name | VARCHAR(120) | No | name |
| email | VARCHAR(254) | Yes | email |
| phone | VARCHAR(40) | Yes | phone |
| purpose | VARCHAR(80) | No | purpose |
| partner_id | UUID | No | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); partner_id -> partners.id (required).

Constraints and invariants: At least one permitted contact channel; contact fields have restricted visibility.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 18 PartnerAddresse

Table `partner_addresses`. Module Partners and catalog. Release Core.

Delivery or business address records.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| label | VARCHAR(80) | No | label |
| address_text | TEXT | No | address text |
| country_code | CHAR(2) | No | country code |
| partner_id | UUID | No | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); partner_id -> partners.id (required).

Constraints and invariants: Address snapshot retained by posted documents.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 19 PartnerQualification

Table `partner_qualifications`. Module Partners and catalog. Release Expanded.

Supplier certificates and review dates.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(60) | No | kind |
| reference | VARCHAR(100) | No | reference |
| valid_until | DATE | Yes | valid until |
| review_status | VARCHAR(20) | No | review status |
| partner_id | UUID | No | Reference to partners |
| document_id | UUID | Yes | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); partner_id -> partners.id (required); document_id -> documents.id (optional).

Constraints and invariants: Qualification status reflects recorded review and does not claim certification by RecallTrace.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 20 Item

Table `items`. Module Partners and catalog. Release Core.

Product component or packaging family.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(160) | No | name |
| kind | VARCHAR(20) | No | kind |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code; allowed kinds component finished packaging.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 21 ItemVariant

Table `item_variants`. Module Partners and catalog. Release Core.

Traceable stock keeping unit.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| sku | VARCHAR(80) | No | sku |
| revision | VARCHAR(40) | No | revision |
| description | TEXT | Yes | description |
| item_id | UUID | No | Reference to items |
| base_unit_id | UUID | No | Reference to units_of_measure |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); item_id -> items.id (required); base_unit_id -> units_of_measure.id (required).

Constraints and invariants: Unique organization and sku; base unit cannot change after stock posting.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 22 ItemCategory

Table `item_categories`. Module Partners and catalog. Release Core.

Company catalog taxonomy.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(100) | No | name |
| parent_id | UUID | Yes | Reference to item_categories |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); parent_id -> item_categories.id (optional).

Constraints and invariants: Unique organization and code; category tree must be acyclic.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 23 ItemCategoryAssignment

Table `item_category_assignments`. Module Partners and catalog. Release Core.

Catalog classification associations.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| item_id | UUID | No | Reference to items |
| category_id | UUID | No | Reference to item_categories |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); item_id -> items.id (required); category_id -> item_categories.id (required).

Constraints and invariants: Unique item and category.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 24 UnitsOfMeasure

Table `units_of_measure`. Module Partners and catalog. Release Core.

Quantity units for company SKUs.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(20) | No | code |
| name | VARCHAR(80) | No | name |
| dimension | VARCHAR(30) | No | dimension |
| decimal_places | SMALLINT | No | decimal places |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code; decimal_places between 0 and 6.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 25 UnitConversion

Table `unit_conversions`. Module Partners and catalog. Release Expanded.

Approved same dimension unit conversions.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| factor | NUMERIC(20,8) | No | factor |
| from_unit_id | UUID | No | Reference to units_of_measure |
| to_unit_id | UUID | No | Reference to units_of_measure |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); from_unit_id -> units_of_measure.id (required); to_unit_id -> units_of_measure.id (required).

Constraints and invariants: Factor > 0; units differ and share a dimension; unique organization from and to units.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 26 SupplierItem

Table `supplier_items`. Module Partners and catalog. Release Core.

Supplier item codes and lead time records.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| supplier_sku | VARCHAR(80) | No | supplier sku |
| lead_time_days | INTEGER | Yes | lead time days |
| partner_id | UUID | No | Reference to partners |
| variant_id | UUID | No | Reference to item_variants |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); partner_id -> partners.id (required); variant_id -> item_variants.id (required).

Constraints and invariants: Unique partner and variant; supplier role required; lead time >= 0.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 27 Warehouse

Table `warehouses`. Module Facilities and inventory. Release Core.

Company stock facilities.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(120) | No | name |
| site_id | UUID | No | Reference to sites |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); site_id -> sites.id (required).

Constraints and invariants: Unique organization and code.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 28 StorageLocation

Table `storage_locations`. Module Facilities and inventory. Release Core.

Warehouse bins or holding areas.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(100) | No | name |
| kind | VARCHAR(20) | No | kind |
| warehouse_id | UUID | No | Reference to warehouses |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); warehouse_id -> warehouses.id (required).

Constraints and invariants: Unique warehouse and code; quarantine locations remain blocked until authorized release.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 29 Lot

Table `lots`. Module Facilities and inventory. Release Core.

Stable internal identity for a traceable batch.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| lot_code | VARCHAR(80) | No | lot code |
| supplier_lot_code | VARCHAR(100) | Yes | supplier lot code |
| manufactured_at | TIMESTAMPTZ | Yes | manufactured at |
| expires_on | DATE | Yes | expires on |
| variant_id | UUID | No | Reference to item_variants |
| supplier_id | UUID | Yes | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); variant_id -> item_variants.id (required); supplier_id -> partners.id (optional).

Constraints and invariants: Unique organization and lot_code; posted identifying fields cannot be silently rewritten.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 30 SerialUnit

Table `serial_units`. Module Facilities and inventory. Release Expanded.

Individual units tracked inside a lot.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| serial_code | VARCHAR(120) | No | serial code |
| status | VARCHAR(20) | No | status |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | Yes | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (optional).

Constraints and invariants: Unique organization and serial_code; serial quantity represents one indivisible unit.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 31 StockTransaction

Table `stock_transactions`. Module Facilities and inventory. Release Core.

Receipt consumption output transfer return or reversal posting.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(30) | No | kind |
| status | VARCHAR(20) | No | status |
| idempotency_key | VARCHAR(100) | No | idempotency key |
| payload_digest | CHAR(64) | No | payload digest |
| posted_at | TIMESTAMPTZ | Yes | posted at |
| posted_by_id | UUID | Yes | Reference to memberships |
| reverses_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); posted_by_id -> memberships.id (optional); reverses_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and idempotency_key; reversal references one original posting; source link must be present on its business record.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 32 StockTransactionLine

Table `stock_transaction_lines`. Module Facilities and inventory. Release Core.

Signed quantity changes by lot and location.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity_delta | NUMERIC(20,6) | No | quantity delta |
| transaction_id | UUID | No | Reference to stock_transactions |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); transaction_id -> stock_transactions.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Nonzero delta; unit is the lot variant base unit; posted lines immutable.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 33 StockBalance

Table `stock_balances`. Module Facilities and inventory. Release Core.

Transactional projection of the stock journal.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Unique organization lot and location; quantity >= 0; reconciliation equals sum of posted journal deltas.

Lifecycle: System generates or refreshes; scoped reading; supersede results rather than manual editing.

### 34 StockReservation

Table `stock_reservations`. Module Facilities and inventory. Release Expanded.

Stock earmarked for production or dispatch.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| status | VARCHAR(20) | No | status |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| production_input_id | UUID | Yes | Reference to production_inputs |
| shipment_line_id | UUID | Yes | Reference to shipment_lines |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required); production_input_id -> production_inputs.id (optional); shipment_line_id -> shipment_lines.id (optional).

Constraints and invariants: Quantity > 0; exactly one demand owner; no reservation exceeding available stock.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 35 StockTransfer

Table `stock_transfers`. Module Facilities and inventory. Release Core.

Controlled movement between warehouses.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| status | VARCHAR(20) | No | status |
| reference | VARCHAR(80) | No | reference |
| source_warehouse_id | UUID | No | Reference to warehouses |
| destination_warehouse_id | UUID | No | Reference to warehouses |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); source_warehouse_id -> warehouses.id (required); destination_warehouse_id -> warehouses.id (required); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Source and destination differ; posting is atomic.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 36 StockTransferLine

Table `stock_transfer_lines`. Module Facilities and inventory. Release Core.

Transfer quantities and bin selection.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| transfer_id | UUID | No | Reference to stock_transfers |
| lot_id | UUID | No | Reference to lots |
| source_location_id | UUID | No | Reference to storage_locations |
| destination_location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); transfer_id -> stock_transfers.id (required); lot_id -> lots.id (required); source_location_id -> storage_locations.id (required); destination_location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; bins belong to the transfer warehouses.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 37 StockCount

Table `stock_counts`. Module Facilities and inventory. Release Expanded.

Physical inventory counting session.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| counted_at | TIMESTAMPTZ | Yes | counted at |
| warehouse_id | UUID | No | Reference to warehouses |
| reviewer_id | UUID | Yes | Reference to memberships |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); warehouse_id -> warehouses.id (required); reviewer_id -> memberships.id (optional); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; adjustment requires independent review.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 38 StockCountLine

Table `stock_count_lines`. Module Facilities and inventory. Release Expanded.

Expected and counted lot quantities.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| expected_quantity | NUMERIC(20,6) | No | expected quantity |
| counted_quantity | NUMERIC(20,6) | No | counted quantity |
| count_id | UUID | No | Reference to stock_counts |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); count_id -> stock_counts.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Counted quantity >= 0; unique count lot and location.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 39 PurchaseOrder

Table `purchase_orders`. Module Receiving and purchasing. Release Core.

Supplier order for traceable inputs.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| ordered_on | DATE | No | ordered on |
| supplier_id | UUID | No | Reference to partners |
| delivery_site_id | UUID | No | Reference to sites |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); supplier_id -> partners.id (required); delivery_site_id -> sites.id (required).

Constraints and invariants: Unique organization and reference; supplier role required.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 40 PurchaseOrderLine

Table `purchase_order_lines`. Module Receiving and purchasing. Release Core.

Ordered variant quantities in base units.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| purchase_order_id | UUID | No | Reference to purchase_orders |
| variant_id | UUID | No | Reference to item_variants |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); purchase_order_id -> purchase_orders.id (required); variant_id -> item_variants.id (required).

Constraints and invariants: Quantity > 0; posted referenced lines cannot be removed.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 41 SupplierDelivery

Table `supplier_deliveries`. Module Receiving and purchasing. Release Expanded.

Supplier advance shipment notification.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| expected_at | TIMESTAMPTZ | Yes | expected at |
| status | VARCHAR(20) | No | status |
| supplier_id | UUID | No | Reference to partners |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); supplier_id -> partners.id (required).

Constraints and invariants: Unique organization supplier and reference.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 42 SupplierDeliveryLine

Table `supplier_delivery_lines`. Module Receiving and purchasing. Release Expanded.

Announced quantities against purchase lines.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| supplier_lot_code | VARCHAR(100) | Yes | supplier lot code |
| delivery_id | UUID | No | Reference to supplier_deliveries |
| purchase_order_line_id | UUID | No | Reference to purchase_order_lines |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); delivery_id -> supplier_deliveries.id (required); purchase_order_line_id -> purchase_order_lines.id (required).

Constraints and invariants: Quantity > 0; order supplier matches delivery supplier.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 43 GoodsReceipt

Table `goods_receipts`. Module Receiving and purchasing. Release Core.

Goods accepted into a warehouse.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| received_at | TIMESTAMPTZ | No | received at |
| supplier_id | UUID | No | Reference to partners |
| warehouse_id | UUID | No | Reference to warehouses |
| received_by_id | UUID | No | Reference to memberships |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); supplier_id -> partners.id (required); warehouse_id -> warehouses.id (required); received_by_id -> memberships.id (required); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; posting links exactly one stock transaction.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 44 GoodsReceiptLine

Table `goods_receipt_lines`. Module Receiving and purchasing. Release Core.

Received purchase quantities with lot identity.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| receipt_id | UUID | No | Reference to goods_receipts |
| purchase_order_line_id | UUID | No | Reference to purchase_order_lines |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| supplier_delivery_line_id | UUID | Yes | Reference to supplier_delivery_lines |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); receipt_id -> goods_receipts.id (required); purchase_order_line_id -> purchase_order_lines.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required); supplier_delivery_line_id -> supplier_delivery_lines.id (optional).

Constraints and invariants: Quantity > 0; same supplier and variant as purchase line; no overreceipt unless a documented override is approved.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 45 ReceiptDocument

Table `receipt_documents`. Module Receiving and purchasing. Release Core.

Receipt evidence attachments.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| receipt_id | UUID | No | Reference to goods_receipts |
| document_id | UUID | No | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); receipt_id -> goods_receipts.id (required); document_id -> documents.id (required).

Constraints and invariants: Unique receipt and document; private access follows receipt permissions.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 46 SupplierReturn

Table `supplier_returns`. Module Receiving and purchasing. Release Expanded.

Return of received goods to their supplier.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| reason | TEXT | No | reason |
| status | VARCHAR(20) | No | status |
| receipt_id | UUID | No | Reference to goods_receipts |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); receipt_id -> goods_receipts.id (required); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; returned quantity cannot exceed received quantity less previous returns.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 47 SupplierReturnLine

Table `supplier_return_lines`. Module Receiving and purchasing. Release Expanded.

Return quantities against received lots.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| return_id | UUID | No | Reference to supplier_returns |
| receipt_line_id | UUID | No | Reference to goods_receipt_lines |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); return_id -> supplier_returns.id (required); receipt_line_id -> goods_receipt_lines.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; receipt line belongs to return receipt.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 48 SupplierReturnShipment

Table `supplier_return_shipments`. Module Receiving and purchasing. Release Expanded.

One dispatch record for an approved supplier return.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| tracking_reference | VARCHAR(120) | Yes | tracking reference |
| dispatched_at | TIMESTAMPTZ | No | dispatched at |
| status | VARCHAR(20) | No | status |
| return_id | UUID | No | Reference to supplier_returns |
| carrier_id | UUID | Yes | Reference to carriers |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); return_id -> supplier_returns.id (required); carrier_id -> carriers.id (optional).

Constraints and invariants: Unique return_id; first expanded release dispatches a return as one shipment.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 49 BillOfMaterials

Table `bills_of_materials`. Module Production and genealogy. Release Expanded.

Versioned planned component recipe.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(60) | No | code |
| revision | INTEGER | No | revision |
| status | VARCHAR(20) | No | status |
| output_variant_id | UUID | No | Reference to item_variants |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); output_variant_id -> item_variants.id (required).

Constraints and invariants: Unique organization code and revision; released recipes immutable.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 50 BomLine

Table `bom_lines`. Module Production and genealogy. Release Expanded.

Planned component requirements.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity_per_output | NUMERIC(20,6) | No | quantity per output |
| bom_id | UUID | No | Reference to bills_of_materials |
| component_variant_id | UUID | No | Reference to item_variants |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); bom_id -> bills_of_materials.id (required); component_variant_id -> item_variants.id (required).

Constraints and invariants: Quantity > 0; base unit belongs to component variant.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 51 ProductionRun

Table `production_runs`. Module Production and genealogy. Release Core.

Recorded conversion of input lots into output lots.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| started_at | TIMESTAMPTZ | No | started at |
| finished_at | TIMESTAMPTZ | Yes | finished at |
| site_id | UUID | No | Reference to sites |
| bom_id | UUID | Yes | Reference to bills_of_materials |
| posted_by_id | UUID | Yes | Reference to memberships |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); site_id -> sites.id (required); bom_id -> bills_of_materials.id (optional); posted_by_id -> memberships.id (optional); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; posting locks input stock and validates an acyclic genealogy.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 52 ProductionRunStep

Table `production_run_steps`. Module Production and genealogy. Release Expanded.

Execution and signoff of production steps.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| sequence | INTEGER | No | sequence |
| name | VARCHAR(120) | No | name |
| status | VARCHAR(20) | No | status |
| completed_at | TIMESTAMPTZ | Yes | completed at |
| production_run_id | UUID | No | Reference to production_runs |
| assignee_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); production_run_id -> production_runs.id (required); assignee_id -> memberships.id (optional).

Constraints and invariants: Unique run and sequence; completed steps retain the original signoff.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 53 ProductionInput

Table `production_inputs`. Module Production and genealogy. Release Core.

Lot quantities consumed by a production run.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| production_run_id | UUID | No | Reference to production_runs |
| lot_id | UUID | No | Reference to lots |
| source_location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); production_run_id -> production_runs.id (required); lot_id -> lots.id (required); source_location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; unique run lot and location; consume only available unheld stock.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 54 ProductionOutput

Table `production_outputs`. Module Production and genealogy. Release Core.

New lot quantities produced by a production run.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| production_run_id | UUID | No | Reference to production_runs |
| lot_id | UUID | No | Reference to lots |
| destination_location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); production_run_id -> production_runs.id (required); lot_id -> lots.id (required); destination_location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; output lot cannot be an input or ancestor of an input.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 55 ProductionAllocation

Table `production_allocations`. Module Production and genealogy. Release Expanded.

Explicit partial input to output mapping.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| input_quantity | NUMERIC(20,6) | No | input quantity |
| basis | VARCHAR(30) | No | basis |
| input_id | UUID | No | Reference to production_inputs |
| output_id | UUID | No | Reference to production_outputs |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); input_id -> production_inputs.id (required); output_id -> production_outputs.id (required).

Constraints and invariants: Quantity > 0 in input base units; same run; allocation totals cannot exceed input quantity; unallocated relationships remain conservatively included.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 56 LotTransformation

Table `lot_transformations`. Module Production and genealogy. Release Expanded.

Split merge or repack outside manufacturing.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(20) | No | kind |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| site_id | UUID | No | Reference to sites |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); site_id -> sites.id (required); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; same variant operations conserve base quantity; genealogy remains acyclic.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 57 LotTransformationInput

Table `lot_transformation_inputs`. Module Production and genealogy. Release Expanded.

Input lots in a split merge or repack.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| transformation_id | UUID | No | Reference to lot_transformations |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); transformation_id -> lot_transformations.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; no source lot also appears as an output.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 58 LotTransformationOutput

Table `lot_transformation_outputs`. Module Production and genealogy. Release Expanded.

Resulting lots in a split merge or repack.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| transformation_id | UUID | No | Reference to lot_transformations |
| lot_id | UUID | No | Reference to lots |
| location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); transformation_id -> lot_transformations.id (required); lot_id -> lots.id (required); location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; totals match permitted transformation rules.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 59 ProductionDeviation

Table `production_deviations`. Module Production and genealogy. Release Expanded.

Recorded departure from a production procedure.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| description | TEXT | No | description |
| status | VARCHAR(20) | No | status |
| disposition | TEXT | Yes | disposition |
| production_run_id | UUID | No | Reference to production_runs |
| nonconformance_id | UUID | Yes | Reference to nonconformances |
| owner_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); production_run_id -> production_runs.id (required); nonconformance_id -> nonconformances.id (optional); owner_id -> memberships.id (required).

Constraints and invariants: Disposition requires authorized review.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 60 ProductionDocument

Table `production_documents`. Module Production and genealogy. Release Expanded.

Production evidence attachments.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| production_run_id | UUID | No | Reference to production_runs |
| document_id | UUID | No | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); production_run_id -> production_runs.id (required); document_id -> documents.id (required).

Constraints and invariants: Unique production run and document.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 61 InspectionTemplate

Table `inspection_templates`. Module Quality and holds. Release Core.

Versioned lot inspection definitions.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(60) | No | code |
| revision | INTEGER | No | revision |
| status | VARCHAR(20) | No | status |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization code and revision; referenced versions immutable.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 62 InspectionCheck

Table `inspection_checks`. Module Quality and holds. Release Core.

Recorded criteria inside a template.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| sequence | INTEGER | No | sequence |
| label | VARCHAR(160) | No | label |
| value_type | VARCHAR(20) | No | value type |
| rule_definition | JSONB | No | rule definition |
| template_id | UUID | No | Reference to inspection_templates |
| unit_id | UUID | Yes | Reference to units_of_measure |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); template_id -> inspection_templates.id (required); unit_id -> units_of_measure.id (optional).

Constraints and invariants: Unique template and sequence; allowlisted rule operations only.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 63 Inspection

Table `inspections`. Module Quality and holds. Release Core.

Inspection of an identified lot.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| inspected_at | TIMESTAMPTZ | Yes | inspected at |
| lot_id | UUID | No | Reference to lots |
| template_id | UUID | No | Reference to inspection_templates |
| inspector_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); template_id -> inspection_templates.id (required); inspector_id -> memberships.id (required).

Constraints and invariants: Unique organization and reference; completion freezes the criterion version.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 64 InspectionResult

Table `inspection_results`. Module Quality and holds. Release Core.

Observations and decisions for inspection checks.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| numeric_value | NUMERIC(20,6) | Yes | numeric value |
| text_value | TEXT | Yes | text value |
| outcome | VARCHAR(20) | No | outcome |
| comment | TEXT | Yes | comment |
| inspection_id | UUID | No | Reference to inspections |
| check_id | UUID | No | Reference to inspection_checks |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); inspection_id -> inspections.id (required); check_id -> inspection_checks.id (required).

Constraints and invariants: Unique inspection and check; check belongs to the inspection template.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 65 TestMethod

Table `test_methods`. Module Quality and holds. Release Expanded.

Versioned sample test procedures.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(60) | No | code |
| revision | INTEGER | No | revision |
| procedure_text | TEXT | No | procedure text |
| acceptance_rule | JSONB | No | acceptance rule |
| unit_id | UUID | Yes | Reference to units_of_measure |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); unit_id -> units_of_measure.id (optional).

Constraints and invariants: Unique organization code and revision; referenced procedure revisions immutable.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 66 TestSample

Table `test_samples`. Module Quality and holds. Release Expanded.

Sample custody and collection from a lot.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| sample_code | VARCHAR(80) | No | sample code |
| collected_at | TIMESTAMPTZ | No | collected at |
| quantity | NUMERIC(20,6) | No | quantity |
| lot_id | UUID | No | Reference to lots |
| collector_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); collector_id -> memberships.id (required).

Constraints and invariants: Unique organization and sample_code; quantity > 0.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 67 TestResult

Table `test_results`. Module Quality and holds. Release Expanded.

Reviewed results for a sample and test method.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| numeric_value | NUMERIC(20,6) | Yes | numeric value |
| text_value | TEXT | Yes | text value |
| outcome | VARCHAR(20) | No | outcome |
| reviewed_at | TIMESTAMPTZ | Yes | reviewed at |
| sample_id | UUID | No | Reference to test_samples |
| method_id | UUID | No | Reference to test_methods |
| reviewer_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); sample_id -> test_samples.id (required); method_id -> test_methods.id (required); reviewer_id -> memberships.id (optional).

Constraints and invariants: Exactly one observation type; record method revision and evidence before signoff.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 68 Nonconformance

Table `nonconformances`. Module Quality and holds. Release Core.

Quality issue recorded against a lot.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| description | TEXT | No | description |
| severity | VARCHAR(20) | No | severity |
| status | VARCHAR(20) | No | status |
| lot_id | UUID | No | Reference to lots |
| inspection_id | UUID | Yes | Reference to inspections |
| test_result_id | UUID | Yes | Reference to test_results |
| owner_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); inspection_id -> inspections.id (optional); test_result_id -> test_results.id (optional); owner_id -> memberships.id (required).

Constraints and invariants: Unique organization and reference; linked evidence belongs to the same lot.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 69 NonconformanceAction

Table `nonconformance_actions`. Module Quality and holds. Release Expanded.

Corrective and preventive work on a quality issue.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| description | TEXT | No | description |
| due_at | TIMESTAMPTZ | Yes | due at |
| status | VARCHAR(20) | No | status |
| verification_note | TEXT | Yes | verification note |
| nonconformance_id | UUID | No | Reference to nonconformances |
| assignee_id | UUID | No | Reference to memberships |
| verifier_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); nonconformance_id -> nonconformances.id (required); assignee_id -> memberships.id (required); verifier_id -> memberships.id (optional).

Constraints and invariants: Closure requires recorded verification.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 70 QualityHold

Table `quality_holds`. Module Quality and holds. Release Core.

Restriction on consuming or shipping a lot.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reason | TEXT | No | reason |
| placed_at | TIMESTAMPTZ | No | placed at |
| released_at | TIMESTAMPTZ | Yes | released at |
| lot_id | UUID | No | Reference to lots |
| placed_by_id | UUID | No | Reference to memberships |
| case_id | UUID | Yes | Reference to recall_cases |
| nonconformance_id | UUID | Yes | Reference to nonconformances |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); lot_id -> lots.id (required); placed_by_id -> memberships.id (required); case_id -> recall_cases.id (optional); nonconformance_id -> nonconformances.id (optional).

Constraints and invariants: Active hold blocks all stock release paths; release requires independent review.

Lifecycle: Authorized workflow creates and reads; active hold reason is preserved; independent review releases the hold and appends its decision; active history is not deleted.

### 71 HoldReview

Table `hold_reviews`. Module Quality and holds. Release Core.

Independent decision to retain or release a hold.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| decision | VARCHAR(20) | No | decision |
| reason | TEXT | No | reason |
| reviewed_at | TIMESTAMPTZ | No | reviewed at |
| hold_id | UUID | No | Reference to quality_holds |
| reviewer_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); hold_id -> quality_holds.id (required); reviewer_id -> memberships.id (required).

Constraints and invariants: Reviewer differs from the placing actor; release and hold state update in one transaction.

Lifecycle: System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance.

### 72 QualityDocument

Table `quality_documents`. Module Quality and holds. Release Core.

Inspection or nonconformance evidence attachments.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| inspection_id | UUID | Yes | Reference to inspections |
| nonconformance_id | UUID | Yes | Reference to nonconformances |
| document_id | UUID | No | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); inspection_id -> inspections.id (optional); nonconformance_id -> nonconformances.id (optional); document_id -> documents.id (required).

Constraints and invariants: Exactly one parent; unique parent and document.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 73 SalesOrder

Table `sales_orders`. Module Shipping and distribution. Release Core.

Customer demand and destination.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| destination_snapshot | JSONB | No | destination snapshot |
| customer_id | UUID | No | Reference to partners |
| address_id | UUID | Yes | Reference to partner_addresses |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); customer_id -> partners.id (required); address_id -> partner_addresses.id (optional).

Constraints and invariants: Unique organization and reference; customer role required; posted address snapshot stable.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 74 SalesOrderLine

Table `sales_order_lines`. Module Shipping and distribution. Release Core.

Ordered variant quantities.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| sales_order_id | UUID | No | Reference to sales_orders |
| variant_id | UUID | No | Reference to item_variants |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); sales_order_id -> sales_orders.id (required); variant_id -> item_variants.id (required).

Constraints and invariants: Quantity > 0.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 75 Shipment

Table `shipments`. Module Shipping and distribution. Release Core.

Dispatch workflow against one customer order.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| dispatched_at | TIMESTAMPTZ | Yes | dispatched at |
| tracking_reference | VARCHAR(120) | Yes | tracking reference |
| sales_order_id | UUID | No | Reference to sales_orders |
| warehouse_id | UUID | No | Reference to warehouses |
| carrier_id | UUID | Yes | Reference to carriers |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); sales_order_id -> sales_orders.id (required); warehouse_id -> warehouses.id (required); carrier_id -> carriers.id (optional); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; dispatch rechecks holds and locks relevant lots.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 76 ShipmentLine

Table `shipment_lines`. Module Shipping and distribution. Release Core.

Exact lot quantities sent against an order line.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| shipment_id | UUID | No | Reference to shipments |
| sales_order_line_id | UUID | No | Reference to sales_order_lines |
| lot_id | UUID | No | Reference to lots |
| source_location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); shipment_id -> shipments.id (required); sales_order_line_id -> sales_order_lines.id (required); lot_id -> lots.id (required); source_location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; same variant as order line; dispatch cannot exceed available stock.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 77 ShipmentSerialAssignment

Table `shipment_serial_assignments`. Module Shipping and distribution. Release Expanded.

Serialized units included in a shipment line.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| shipment_line_id | UUID | No | Reference to shipment_lines |
| serial_unit_id | UUID | No | Reference to serial_units |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); shipment_line_id -> shipment_lines.id (required); serial_unit_id -> serial_units.id (required).

Constraints and invariants: Unique shipment line and serial unit; serial belongs to line lot and is not already dispatched.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 78 Carrier

Table `carriers`. Module Shipping and distribution. Release Core.

Company carrier directory.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| code | VARCHAR(40) | No | code |
| name | VARCHAR(120) | No | name |
| tracking_url_template | TEXT | Yes | tracking url template |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required).

Constraints and invariants: Unique organization and code; validated HTTPS URL templates only.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 79 ShipmentEvent

Table `shipment_events`. Module Shipping and distribution. Release Core.

Dispatch transit delivery and correction timeline.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| event_type | VARCHAR(30) | No | event type |
| occurred_at | TIMESTAMPTZ | No | occurred at |
| note | TEXT | Yes | note |
| shipment_id | UUID | No | Reference to shipments |
| recorded_by_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); shipment_id -> shipments.id (required); recorded_by_id -> memberships.id (optional).

Constraints and invariants: Manual or imported event source identified; unsupported carrier integrations are not claimed.

Lifecycle: System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance.

### 80 DeliveryConfirmation

Table `delivery_confirmations`. Module Shipping and distribution. Release Expanded.

Evidence of receipt at destination.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| received_at | TIMESTAMPTZ | No | received at |
| recipient_label | VARCHAR(120) | No | recipient label |
| note | TEXT | Yes | note |
| shipment_id | UUID | No | Reference to shipments |
| document_id | UUID | Yes | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); shipment_id -> shipments.id (required); document_id -> documents.id (optional).

Constraints and invariants: Unique shipment; recipient data minimized.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 81 CustomerReturn

Table `customer_returns`. Module Shipping and distribution. Release Expanded.

Customer goods returned from a prior shipment.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| status | VARCHAR(20) | No | status |
| reason | TEXT | No | reason |
| shipment_id | UUID | No | Reference to shipments |
| stock_transaction_id | UUID | Yes | Reference to stock_transactions |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); shipment_id -> shipments.id (required); stock_transaction_id -> stock_transactions.id (optional).

Constraints and invariants: Unique organization and reference; returned goods enter quarantine.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 82 CustomerReturnLine

Table `customer_return_lines`. Module Shipping and distribution. Release Expanded.

Returned quantities from specific shipment lines.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| return_id | UUID | No | Reference to customer_returns |
| shipment_line_id | UUID | No | Reference to shipment_lines |
| destination_location_id | UUID | No | Reference to storage_locations |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); return_id -> customer_returns.id (required); shipment_line_id -> shipment_lines.id (required); destination_location_id -> storage_locations.id (required).

Constraints and invariants: Quantity > 0; cumulative returned amount cannot exceed dispatched amount.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 83 RecallCase

Table `recall_cases`. Module Recall investigations. Release Core.

Investigation approval recovery and closure workflow.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| reference | VARCHAR(80) | No | reference |
| title | VARCHAR(160) | No | title |
| reason | TEXT | No | reason |
| severity | VARCHAR(20) | No | severity |
| status | VARCHAR(20) | No | status |
| approved_at | TIMESTAMPTZ | Yes | approved at |
| closed_at | TIMESTAMPTZ | Yes | closed at |
| owner_id | UUID | No | Reference to memberships |
| approver_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| submitted_at | TIMESTAMPTZ | Yes | Time the case was submitted for independent review |
| submitted_by_id | UUID | Yes | Recorded actor for independent approval checks |

Foreign keys: organization_id -> organizations.id (required); owner_id -> memberships.id (required); approver_id -> memberships.id (optional); submitted_by_id -> memberships.id (optional).

Constraints and invariants: Unique organization and reference; approver differs from submitting actor; closure requires current trace and completed mandatory tasks.

Lifecycle: Full CRUD in draft; active case changes use explicit authorized transitions; approved scope is revised through a fresh trace and approval; closed cases retain history.

### 84 CaseSource

Table `case_sources`. Module Recall investigations. Release Core.

Root lots and evidence starting an investigation.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| source_note | TEXT | No | source note |
| case_id | UUID | No | Reference to recall_cases |
| lot_id | UUID | No | Reference to lots |
| nonconformance_id | UUID | Yes | Reference to nonconformances |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); lot_id -> lots.id (required); nonconformance_id -> nonconformances.id (optional).

Constraints and invariants: Unique case and root lot; evidence matches the root lot.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 85 TraceRun

Table `trace_runs`. Module Recall investigations. Release Core.

Versioned trace computation at a recorded data revision.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| direction | VARCHAR(20) | No | direction |
| status | VARCHAR(20) | No | status |
| trace_revision | BIGINT | No | trace revision |
| algorithm_version | VARCHAR(30) | No | algorithm version |
| limits | JSONB | No | limits |
| completed_at | TIMESTAMPTZ | Yes | completed at |
| is_complete | BOOLEAN | No | is complete |
| case_id | UUID | No | Reference to recall_cases |
| requested_by_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); requested_by_id -> memberships.id (required).

Constraints and invariants: Preview is read only; partial or stale traces cannot authorize notices or close a case.

Lifecycle: System generates or refreshes; scoped reading; supersede results rather than manual editing.

### 86 TraceResult

Table `trace_results`. Module Recall investigations. Release Core.

Deduplicated affected lots and recorded path evidence.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| depth | INTEGER | No | depth |
| evidence_path | JSONB | No | evidence path |
| scope_basis | VARCHAR(30) | No | scope basis |
| trace_run_id | UUID | No | Reference to trace_runs |
| lot_id | UUID | No | Reference to lots |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); trace_run_id -> trace_runs.id (required); lot_id -> lots.id (required).

Constraints and invariants: Unique trace run and lot; scope_basis identifies conservative or explicit mapping.

Lifecycle: System generates or refreshes; scoped reading; supersede results rather than manual editing.

### 87 CaseAffectedShipment

Table `case_affected_shipments`. Module Recall investigations. Release Core.

Frozen shipment exposure associated with a trace.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity_dispatched | NUMERIC(20,6) | No | quantity dispatched |
| quantity_recovered | NUMERIC(20,6) | No | quantity recovered |
| case_id | UUID | No | Reference to recall_cases |
| trace_run_id | UUID | No | Reference to trace_runs |
| shipment_line_id | UUID | No | Reference to shipment_lines |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| quantity_resolved | NUMERIC(20,6) | No | Quantity with a verified return destruction or other resolution disposition |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); trace_run_id -> trace_runs.id (required); shipment_line_id -> shipment_lines.id (required).

Constraints and invariants: Unique case trace and shipment line; no double counting across multiple paths; recovery projection reconciles with recovery_records.

Lifecycle: System generates or refreshes; scoped reading; supersede results rather than manual editing.

### 88 CaseTask

Table `case_tasks`. Module Recall investigations. Release Core.

Assigned investigation and recovery work.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| title | VARCHAR(160) | No | title |
| description | TEXT | Yes | description |
| status | VARCHAR(20) | No | status |
| mandatory | BOOLEAN | No | mandatory |
| due_at | TIMESTAMPTZ | Yes | due at |
| case_id | UUID | No | Reference to recall_cases |
| assignee_id | UUID | No | Reference to memberships |
| verifier_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); assignee_id -> memberships.id (required); verifier_id -> memberships.id (optional).

Constraints and invariants: Completed mandatory work requires evidence or a recorded verification note.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 89 CaseComment

Table `case_comments`. Module Recall investigations. Release Core.

Attributed investigation discussion.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| body | TEXT | No | body |
| case_id | UUID | No | Reference to recall_cases |
| author_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); author_id -> memberships.id (required).

Constraints and invariants: Escaped text; amendments preserve original text in audit history.

Lifecycle: Authorized authors create and amend comments while a case permits discussion; edits and removals preserve prior content in protected history.

### 90 CaseDocument

Table `case_documents`. Module Recall investigations. Release Core.

Evidence attached to an investigation.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| case_id | UUID | No | Reference to recall_cases |
| document_id | UUID | No | Reference to documents |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); document_id -> documents.id (required).

Constraints and invariants: Unique case and document; access follows case scope.

Lifecycle: Create update and delete through the owning parent form while the parent is editable.

### 91 RecallNotice

Table `recall_notices`. Module Recall investigations. Release Core.

Reviewed recipient specific recall communication.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| revision | INTEGER | No | revision |
| subject | VARCHAR(160) | No | subject |
| body | TEXT | No | body |
| status | VARCHAR(20) | No | status |
| approved_at | TIMESTAMPTZ | Yes | approved at |
| case_id | UUID | No | Reference to recall_cases |
| contact_id | UUID | No | Reference to partner_contacts |
| approved_by_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| created_by_id | UUID | Yes | Recorded actor for independent approval checks |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); contact_id -> partner_contacts.id (required); approved_by_id -> memberships.id (optional); created_by_id -> memberships.id (optional).

Constraints and invariants: Unique case contact and revision; only approved current notices enter delivery queue; each recipient sees its own exposure.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 92 NoticeDelivery

Table `notice_deliveries`. Module Recall investigations. Release Core.

Delivery attempts for an approved notice.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| idempotency_key | VARCHAR(120) | No | idempotency key |
| attempt | INTEGER | No | attempt |
| status | VARCHAR(20) | No | status |
| provider_reference | VARCHAR(160) | Yes | provider reference |
| sent_at | TIMESTAMPTZ | Yes | sent at |
| error_code | VARCHAR(80) | Yes | error code |
| notice_id | UUID | No | Reference to recall_notices |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); notice_id -> recall_notices.id (required).

Constraints and invariants: Unique notice and attempt; provider idempotency used where supported; ambiguous deliveries require reconciliation.

Lifecycle: System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing.

### 93 NoticeAcknowledgement

Table `notice_acknowledgements`. Module Recall investigations. Release Core.

Verified acknowledgement of a notice revision.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| acknowledged_at | TIMESTAMPTZ | No | acknowledged at |
| method | VARCHAR(30) | No | method |
| safe_note | TEXT | Yes | safe note |
| notice_id | UUID | No | Reference to recall_notices |
| recorded_by_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); notice_id -> recall_notices.id (required); recorded_by_id -> memberships.id (required).

Constraints and invariants: One effective acknowledgement per notice revision; external record requires restricted partner membership.

Lifecycle: System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance.

### 94 RecoveryRecord

Table `recovery_records`. Module Recall investigations. Release Core.

Verified quantities recovered or otherwise resolved.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| quantity | NUMERIC(20,6) | No | quantity |
| disposition | VARCHAR(30) | No | disposition |
| verified_at | TIMESTAMPTZ | No | verified at |
| evidence_note | TEXT | No | evidence note |
| case_id | UUID | No | Reference to recall_cases |
| shipment_line_id | UUID | No | Reference to shipment_lines |
| verified_by_id | UUID | No | Reference to memberships |
| notice_id | UUID | Yes | Reference to recall_notices |
| customer_return_line_id | UUID | Yes | Reference to customer_return_lines |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); case_id -> recall_cases.id (required); shipment_line_id -> shipment_lines.id (required); verified_by_id -> memberships.id (required); notice_id -> recall_notices.id (optional); customer_return_line_id -> customer_return_lines.id (optional).

Constraints and invariants: Quantity > 0; cumulative physical recovery cannot exceed eligible dispatched units; one physical return allocation is not counted twice.

Lifecycle: System or authorized workflow creates; scoped reading; immutable history; retention handled by approved maintenance.

### 95 Document

Table `documents`. Module Shared operations. Release Core.

Private uploaded evidence and generated exports.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| object_key | TEXT | No | object key |
| original_name | VARCHAR(240) | No | original name |
| media_type | VARCHAR(120) | No | media type |
| size_bytes | BIGINT | No | size bytes |
| sha256 | CHAR(64) | No | sha256 |
| scan_status | VARCHAR(20) | No | scan status |
| state | VARCHAR(20) | No | state |
| uploaded_by_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); uploaded_by_id -> memberships.id (required).

Constraints and invariants: Unique organization and object_key; downloads require authorization; quarantined objects cannot be served.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 96 Notification

Table `notifications`. Module Shared operations. Release Core.

In application user notifications.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| event_type | VARCHAR(60) | No | event type |
| safe_payload | JSONB | No | safe payload |
| read_at | TIMESTAMPTZ | Yes | read at |
| membership_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); membership_id -> memberships.id (required).

Constraints and invariants: Target object authorization is checked again on navigation; read state may change through a dedicated endpoint.

Lifecycle: System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing.

### 97 NotificationPreference

Table `notification_preferences`. Module Shared operations. Release Core.

Membership event and channel choices.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| event_type | VARCHAR(60) | No | event type |
| channel | VARCHAR(20) | No | channel |
| enabled | BOOLEAN | No | enabled |
| membership_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |
| archived_at | TIMESTAMPTZ | Yes | Archive timestamp for referenced records |

Foreign keys: organization_id -> organizations.id (required); membership_id -> memberships.id (required).

Constraints and invariants: Unique membership event_type and channel.

Lifecycle: Create and edit through authorized forms; delete unused records; archive referenced records.

### 98 JobOutbox

Table `job_outbox`. Module Shared operations. Release Core.

Durable intent to perform work after commit.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(60) | No | kind |
| payload | JSONB | No | payload |
| deduplication_key | VARCHAR(140) | No | deduplication key |
| status | VARCHAR(20) | No | status |
| attempts | INTEGER | No | attempts |
| available_at | TIMESTAMPTZ | No | available at |
| created_by_id | UUID | Yes | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); created_by_id -> memberships.id (optional).

Constraints and invariants: Unique organization and deduplication_key; payload contains identifiers rather than secrets; retries revalidate scope.

Lifecycle: System creates; dedicated authorized actions update read delivery retry or job state; history retained; no arbitrary business payload editing.

### 99 ImportJob

Table `import_jobs`. Module Shared operations. Release Core.

Validated atomic CSV import lifecycle.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(40) | No | kind |
| status | VARCHAR(20) | No | status |
| idempotency_key | VARCHAR(100) | No | idempotency key |
| row_count | INTEGER | Yes | row count |
| safe_error_summary | JSONB | Yes | safe error summary |
| source_document_id | UUID | No | Reference to documents |
| requested_by_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); source_document_id -> documents.id (required); requested_by_id -> memberships.id (required).

Constraints and invariants: Unique organization and idempotency_key; dry run before commit; all rows validated before atomic apply.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.

### 100 ExportJob

Table `export_jobs`. Module Shared operations. Release Core.

Authorized export generation and expiry.

| Column | Type | Nullable | Meaning |
| --- | --- | --- | --- |
| id | UUID | No | Primary key generated by the application |
| organization_id | UUID | No | Owning company workspace |
| kind | VARCHAR(40) | No | kind |
| filters | JSONB | No | filters |
| status | VARCHAR(20) | No | status |
| expires_at | TIMESTAMPTZ | Yes | expires at |
| output_document_id | UUID | Yes | Reference to documents |
| requested_by_id | UUID | No | Reference to memberships |
| created_at | TIMESTAMPTZ | No | UTC creation time |
| updated_at | TIMESTAMPTZ | No | UTC last permitted change |
| version | INTEGER | No | Optimistic concurrency version initially 1 |

Foreign keys: organization_id -> organizations.id (required); output_document_id -> documents.id (optional); requested_by_id -> memberships.id (required).

Constraints and invariants: Export is company scoped at request and execution; expiring private download; spreadsheet formula injection mitigated.

Lifecycle: Full CRUD in draft; freeze posted business fields; correct using reversal or superseding event; only documented later status transitions are allowed.
