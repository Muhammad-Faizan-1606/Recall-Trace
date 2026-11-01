# Project proposal and scope

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
