# RecallTrace handoff

## Decision already made

The user selected RecallTrace after comparing procurement, paper trading, recall investigation and dataset review projects. They want a distinctive, substantial web development course project rather than a familiar inventory application. Keep the product centered on investigation, traceability evidence and an approved recall response.

The team has four or more active builders and more than four weeks before submission. The exact deadline, weekly availability, team names and production hosting budget have not been specified. Use the dependency-based milestones and avoid inventing commitments. These details do not block local implementation.

## What exists

- A visually reviewed 26-page project specification, copied under references.
- The original four-page course rubric, copied byte-for-byte as references/Flask_Project_Rubric.pdf. Its original upload name was Flask_Project_Rubric(1).pdf.
- Thirteen detailed implementation guides under documentation/docs.
- A logical field dictionary with 100 distinct model definitions and 297 foreign-key relationships, split into 72 Core and 28 Expanded models.
- Thirty functional requirements, ten nonfunctional targets, and 62 planned acceptance scenarios.
- CRUD/lifecycle coverage for every model, nine module ERD source files, architecture/genealogy diagrams, dependency and environment proposals.
- Documentation consistency checks. These did not execute application software.

The application, executable migrations, finalized lock files, implemented tests and deployment do not exist yet. Do not import or build Meridian or ProcureFlow; those were alternative project ideas, not source for this selected implementation.

## The product demonstration

Incoming switch lot C10 contains 200 switches. Run A consumes 100 and creates 100 lamps in L1; Run B consumes 50 and creates 50 lamps in L2. S1 dispatches 60 L1 lamps and S2 dispatches 50 L2 lamps. Forty L1 lamps and fifty unused switches remain. An unrelated source C11 produces L3 and shipment S3.

Reporting C10 as suspect must trace L1/L2 and S1/S2 while excluding unrelated L3/S3. Report 150 potentially affected finished lamps, of which 110 were dispatched and 40 remain; report the 50 unused switches separately. An independent reviewer approves a complete current trace, places relevant holds, authorizes recipient-specific notices, and reviews acknowledgement, recovery and closure evidence.

This fixture is synthetic and its expected results are explicitly defined. A trace establishes recorded relationships and potential exposure, not physical proof that every related unit is defective.

## Rubric priorities

The rubric totals 100 marks: setup 10; routing 15; templates/Jinja 15; database/CRUD 20; forms/validation/cookies/sessions 15; code quality 10; functionality/testing 10; documentation 5. The 40-related-model minimum is mandatory. The 100-model product target exceeds the numerical minimum but does not create a separate bonus.

Maintain real UI CRUD for mutable business records; document supporting associations and protected-system lifecycles. Preserve Jinja inheritance, loops, conditionals, server-side validation, sessions, flash feedback and Post-Redirect-Get. The final README must contain verified installation, environment, migration, seed and run instructions for the actual application.

## Next action

Read AGENTS.md and PLAN.md, inspect the toolchain, and implement the foundation plus a complete company-scoped catalog CRUD slice. Establish configuration, database transactions, shared templates and meaningful negative authorization tests before broad schema expansion. Continue through the roadmap in working increments and record actual progress.
