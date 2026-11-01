# Technical stack and architecture

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
