# Factory Suite (MCM) — module plan

Status: approved by the owner on 13 November 2026. Steps 1 (factory model and machine register) and 2 (styles and SAM) are implemented; see STATUS.md. Later steps are not started.

## 1. Purpose and decisions

The owner wants RecallTrace to grow from a quality and recall tool into a general factory management product for vertically integrated knitwear exporters. Its centre is a **Machine Capacity Management (MCM)** engine. The first prospect is Style Textile (Pvt) Limited, Lahore.

Decisions confirmed by the owner on 13 November 2026:

1. The suite is built as new modules inside this application. RecallTrace (lots, quality, holds, trace, recall) stays intact and becomes the traceability module of the larger product.
2. Demo data uses an invented company, **Lahore Knit Mills (demo)**, modelled on the public site structure of a large Lahore knitwear exporter. The real Style Textile name, logo or data appear only on a private copy, and only with their agreement. This follows the existing fictional-data rule in AGENTS.md.

The owner-supplied blueprint (`style-textile-mcm-operational-architecture.docx`) was checked against public sources. Findings:

- **Sound:** its process flow, inter-site transit times, fabric relaxation rule and capacity formulas.
- **Unverified:** export value, headcount, ERP vendor, and machine makes and counts. These are treated as sample, editable data.
- **Wrong:** the "15 MW solar" figure belongs to another company.
- **Possible ownership change:** a May 2026 Accord disclosure describes the Manga site as "formerly operating as Style Textile". Confirm with the factory before presenting Manga as theirs.

## 2. Design principles

- **One system of record per fact.** Reuse existing Organization, Site, Warehouse, StorageLocation, Item/ItemVariant, Partner, Lot, SalesOrder, ProductionRun, Shipment, Inspection, Nonconformance and QualityHold instead of duplicating them.
- **Deterministic, explainable capacity.** Every number on a planning screen can be expanded to show the formula and inputs that produced it (viva-friendly and auditor-friendly).
- **Process-specific models.** Knitting is continuous (length to weight). Dyeing is batch (vessel load and cycle time). Sewing is earned minutes (SAM, pitch time, balance). They are not forced into one generic "machine hours" model.
- **Multi-site aware.** Inter-site transit times and the mandatory 24–48 hour fabric relaxation are hard constraints in scheduling.
- **Same invariants as the core.**
  - Company-scoped composite keys, permissions on every read and write, and audit events for plan changes, downtime and efficiency logs.
  - Decimal quantities in stated units, never mixing units.
- **Integrations stay visibly unconfigured until real.** ERP, GSD and machine-counter feeds start as CSV import plus a documented API, and are labelled as such.

## 3. Modules

### 3.1 Factory model (foundation)
- **Work centres** per site and department: knitting, dyeing, finishing (stenter/compactor), relaxation bay, cutting, embellishment (print/embroidery), sewing line, washing, finishing and packing.
- **Machine classes** with the capacity type they use:
  - knitting: RPM × feeders
  - dyeing: kg per batch
  - stenter: m/min
  - cutter: plies and panels per hour
  - printer: impressions per hour
  - embroidery: stitches per minute (SPM) and heads
  - sewing: machine type
  - washing: kg per batch
- **Machine register**: asset tag, class, work centre, make/model, rated value and unit, class-specific attributes (diameter, gauge, feeders; vessel kg; chamber count), status, commissioning date.
- **Shift patterns and calendars**: shifts per day, hours, breaks, holidays and planned shutdowns per site.
- **Site transit matrix**: hours between sites, used by the scheduler.

### 3.2 Styles and engineering
- **Buyer styles** linked to Item/ItemVariant (sizes and colours), buyer, season.
- **Fabric specification** per style: fabric type, GSM, width, course density, composition, relaxation hours (24 for cotton, 48 for high-spandex).
- **Operation bulletin (routing)**: sequence, operation, machine type, basic time, allowance factor. Operation SAM and garment SAM are calculated and frozen in versioned revisions, so a planned order keeps the SAM it was planned with.
- **CSV import** of operation bulletins in GSD export shape. Their IE team already uses GSD, per job ads.

### 3.3 Orders and capacity planning (the MCM engine)
- **Production order** per sales order line: style, colour, size breakdown, quantity, ex-factory date.
- **Stage plan** is generated from the style: yarn kg → knit kg → dye batches → finished metres → relaxation → cut panels → embellishment → sew pieces → wash → pack.
- **Capacity engine** using the formulas from the blueprint (section 5), with every result traceable to its inputs:
  - knitting length `L = (rpm × feeders × η × 60 × T) / (feeders_per_course × courses_per_cm × 100)` and weight `W = L × width × GSM / 1000`
  - dyehouse `C = Σ 24 × V × fill / (cycle + setup) × OEE`
  - sewing target `Q = operators × minutes × η / SAM`, pitch time, balance efficiency
- **Load vs capacity board**: work centre × day/week heat map (green under 85%, amber 85–100%, red over 100%), with drill-down to the bookings causing the load.
- **Finite forward scheduler**:
  - It places stage bookings in order, respecting capacity, transit time between sites, and the relaxation dwell.
  - It reports the earliest feasible ex-factory date and flags late orders.
  - Deterministic and explainable, with no black-box optimisation.
- **What-if**: change operators, efficiency, shifts or move an order to another site, and see the new completion date before committing.

### 3.4 Sewing lines and line balancing
- **Sewing lines** with operators, machines by type, and a current style.
- **Balancing screen**: assign bulletin operations to stations. It shows each station's load against pitch time, the bottleneck station, balance efficiency and the expected hourly output, and suggests moving a floating operator to the bottleneck.

### 3.5 Shop floor execution (tablet-friendly)
- **Hourly output entry** per line (good pieces, rejects) and **downtime/off-standard minutes** with reasons: machine breakdown, power cut, no feeding, style changeover, needle/bobbin.
- **Batch cards**:
  - knitting rolls: machine, kg, roll number
  - dye batches: vessel, kg, recipe reference, start/end
  - stenter runs
- **Cut bundles** with QR bundle tickets (bundle → panels → cut lot). This links the floor to the existing lot genealogy.
- **Achieved efficiency** is calculated per shift: `(good pcs × SAM) / (clock minutes − approved off-standard minutes)`.

### 3.6 Alerts and dashboards
- **Alerts**:
  - achieved efficiency outside ±5% of plan
  - machine down more than 30 minutes
  - order forecast past its ex-factory date
  - bottleneck starvation (work in progress below one hour of downstream need)
  - fabric released to cutting before its relaxation time
  - Each alert has an owner, acknowledgement and resolution note.
- **Management dashboard**: capacity utilisation by site and department, line efficiency trends, OEE by machine class, on-time delivery forecast, top downtime reasons.

### 3.7 Maintenance
- **Preventive maintenance plans** per machine class (interval in hours or days).
- **Breakdown tickets** with response and repair times; MTBF and MTTR per machine.
- Machines under maintenance are removed from capacity automatically.

### 3.8 Quality and traceability (existing RecallTrace, connected)
- Inline and end-line checks per line, and DHU (defects per hundred units).
- Final AQL audits reuse the existing inspection templates. Defects link to line, operation and operator.
- Traceability spans the whole chain: yarn lot → knit roll → dye lot → cut bundle → carton → shipment. The existing recall investigation works on this chain unchanged.

### Out of scope for this phase
HR/payroll, accounting, costing and merchandising budgets, a live ERP connector, live machine-counter (IoT) feeds, Urdu translation. Each can be added later. ERP, GSD and counters start as CSV plus a documented API.

## 4. Data model additions (planned)

About 25 new company-owned tables. All use same-company composite foreign keys and Alembic migrations, and get real screens and tests:

| Area | Tables |
|---|---|
| Factory model | `work_centers`, `machine_classes`, `machines`, `machine_status_events`, `shift_patterns`, `calendar_exceptions`, `site_transit_times` |
| Engineering | `styles`, `fabric_specs`, `operation_bulletins`, `bulletin_operations` |
| Planning | `production_orders`, `stage_bookings`, `plan_scenarios` |
| Lines | `sewing_lines`, `line_stations` |
| Execution | `knit_rolls`, `dye_batches`, `cut_bundles`, `output_logs`, `downtime_events`, `downtime_reasons` |
| Alerts | `alerts` |
| Maintenance | `maintenance_plans`, `maintenance_tickets` |

This expands the documented 72-model release. The decision and the new inventory will be recorded in DECISIONS.md and STATUS.md when implementation starts. The rubric minimum of 40 meaningful related models is unaffected.

## 5. Screens (new sidebar group "Factory")

Planning board (load heat map and schedule timeline) · Production orders · Styles and SAM · Line balancing · Shop floor (tablet) · Machines · Maintenance · Alerts · Factory dashboard.

The design follows the existing interface: pill buttons, soft badges, navy feature cards and motion that respects the reduced-motion setting.

## 6. Demo dataset: "Lahore Knit Mills (demo)"

| Site | Role | Sample equipment |
|---|---|---|
| QIE Unit 1 (Kot Lakhpat) | Knitting, sampling, central CMT | 40 circular knitting machines (E18–E32), 6 sewing lines |
| QIE Unit 2 | High-volume CMT | 8 sewing lines, cut-panel buffer |
| Manga | Dyeing and finishing | 16 jet vessels (250–1,500 kg), 3 stenters, 2 compactors, relaxation bays |
| Apparel Park | Cutting, printing, embroidery, CMT | 3 auto spreaders and CNC cutters, 6 oval screen printers, 4 multi-head embroidery machines, 10 lines |
| Raiwind | Flexible CMT and packing | 8 lines, washing tumblers, packing hub |
| Sundar | Dedicated athletic programme lines | 6 modular lines |

- **Buyers** are fictional, with `.test` contacts.
- **Styles**: about 8 (fleece hoodie, jersey tee, polo, leggings, joggers), each with an operation bulletin.
- **Orders**: about 20 at different stages, so every screen has real-looking data.
- **History**: some lines underperform and one dye vessel breaks down, so alerts and dashboards show live behaviour.

## 7. Delivery order

Each step is a working vertical slice with screens, rules, migrations and tests, deployed so it can be demonstrated:

1. **Factory model and machine register.** Sites, work centres and machines with live capacity per work centre.
2. **Styles and SAM.** Operation bulletins, GSD-shaped CSV import, calculated SAMs.
3. **Orders and the capacity engine.** Production orders, stage plans, load heat map, finite scheduler with transit and relaxation, what-if. *This is the core of the pitch.*
4. **Line balancing.**
5. **Shop floor execution and efficiency.** Output and downtime entry, batch cards, bundle tickets.
6. **Alerts and factory dashboard.**
7. **Maintenance.**
8. **Quality and trace connection** across the full yarn-to-carton chain.

Steps 1–3 already make a convincing first demo for the factory. Steps 4–6 complete the "live factory" story.

## 8. Verification

- **Formula tests:** unit tests for each capacity formula use the worked examples from the blueprint (for example 50 operators × 480 min × 70% / 20 SAM = 840 pieces).
- **Scheduler tests** cover relaxation dwell, transit time, overload and late-order detection.
- **Database tests:** PostgreSQL integration tests for company isolation and concurrent output logging.
- **Browser checks** at desktop and phone widths.
- **Reporting:** results recorded in STATUS.md with the exact commands run.

## 9. Open items to confirm with the factory (not blocking)

- Which ERP they use, and whether an order export is available.
- Whether their operation bulletins come from GSD, and in what export format.
- Actual machine counts per site, shifts and target efficiencies.
- Current status of the Manga site.
- Who would use the system first: planning, industrial engineering or production.
