# RecallTrace handoff

## Decision already made

The user selected RecallTrace after comparing procurement, paper trading, recall investigation and dataset review projects. They want a distinctive, substantial web development course project rather than a familiar inventory application. Keep the product centered on investigation, traceability evidence and an approved recall response.

The team has four or more active builders and more than four weeks before submission. The exact deadline, weekly availability, team names and production hosting budget have not been specified. Use the dependency-based milestones and avoid inventing commitments. These details do not block local implementation.

## Current scope and implementation

The user confirmed the final release contains 72 Core models, no Expanded phase. This is a university project with business-quality controls and no hosting budget. Flask/Jinja/PostgreSQL/Redis remain the chosen stack. Local application, migrations, hashed dependencies and meaningful integration/browser tests exist; the earlier documentation-only starting state is historical.

Read README.md, STATUS.md, documentation/CORE_GUIDE.md and documentation/DEPLOYMENT.md for current setup, verification and external requirements. Do not infer production readiness from the model count. No public provider accounts, external credentials or production database were created; the connected database is the private local PostgreSQL development service. Retain the original rubric and logical schema references.

## The product demonstration

Incoming switch lot C10 contains 200 switches. Run A consumes 100 and creates 100 lamps in L1; Run B consumes 50 and creates 50 lamps in L2. S1 dispatches 60 L1 lamps and S2 dispatches 50 L2 lamps. Forty L1 lamps and fifty unused switches remain. An unrelated source C11 produces L3 and shipment S3.

Reporting C10 as suspect must trace L1/L2 and S1/S2 while excluding unrelated L3/S3. Report 150 potentially affected finished lamps, of which 110 were dispatched and 40 remain; report the 50 unused switches separately. An independent reviewer approves a complete current trace, places relevant holds, authorizes recipient-specific notices, and reviews acknowledgement, recovery and closure evidence.

This fixture is synthetic and its expected results are explicitly defined. A trace establishes recorded relationships and potential exposure, not physical proof that every related unit is defective.

## Rubric priorities

The rubric totals 100 marks: setup 10; routing 15; templates/Jinja 15; database/CRUD 20; forms/validation/cookies/sessions 15; code quality 10; functionality/testing 10; documentation 5. The 40-related-model minimum is mandatory. The 100-model product target exceeds the numerical minimum but does not create a separate bonus.

Maintain real UI CRUD for mutable business records; document supporting associations and protected-system lifecycles. Preserve Jinja inheritance, loops, conditionals, server-side validation, sessions, flash feedback and Post-Redirect-Get. The final README must contain verified installation, environment, migration, seed and run instructions for the actual application.

## Next action

Use the existing checkout, restart services using the saved setup/start instructions and inspect actual health. Review current verification and external hosting limitations in STATUS.md. Finish provider account/resource configuration and validate live TLS, storage, scanning, mail, worker supervision, least-privilege database roles and recovery before treating a deployment as business ready. Keep secret values out of chat/source and do not send real recall messages during development.
