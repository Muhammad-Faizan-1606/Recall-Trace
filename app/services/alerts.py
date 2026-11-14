"""Factory checks: find conditions that need someone's attention and keep them as alerts.

Rules (blueprint section 3.6):

    efficiency      over its last three logged hours of the day (at least two), a line is more
                    than 5 points below (warning) or above (info: check SAM or counting) its
                    plan; a recent window shows how the line is running now, not its warm-up
    machine down    a machine in maintenance for more than 30 minutes, or a stop longer than
                    30 minutes against one machine today (critical after 24 hours)
    order late      a planned or released order whose planned finish is after ex-factory
    line starving   a line sewing today that works from bundle tickets, whose work in
                    progress (bundles issued and not sewn) is below one hour of planned output
    relaxation      bundles cut from a dye batch before the fabric's relaxation time passed
    quality         a line whose end-line DHU today is above the limit (7.5) over at least
                    50 checked pieces (critical above twice the limit)
    maintenance     preventive jobs past their due date with no ticket opened, one alert per
                    plan carrying the count (critical once any is two weeks overdue)

`scan` is idempotent: one unresolved alert per condition, refreshed while it persists and
marked cleared when it goes away. People acknowledge, assign and resolve alerts.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from werkzeug.exceptions import HTTPException

from app.extensions import db
from app.models import Membership, now
from app.models.factory import (
    CutBundle,
    DowntimeEvent,
    DyeBatch,
    FabricSpec,
    FactoryAlert,
    Machine,
    MachineStatusEvent,
    ProductionOrder,
)
from app.policies import allowed, membership_for, require
from app.services import balancing, shopfloor
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

EFFICIENCY_BAND = Decimal(5)
DOWN_MINUTES = 30
CRITICAL_DOWN_HOURS = 24
WINDOW_HOURS = 3


@dataclass
class Finding:
    kind: str
    severity: str
    key: str
    title: str
    detail: str
    work_center_id: object = None
    machine_id: object = None
    production_order_id: object = None
    dye_batch_id: object = None


# ---------- Rules ----------


def efficiency_findings(company_id, day):
    lines = balancing.sewing_lines(company_id)
    days = shopfloor.floor(company_id, day, [line.id for line in lines])
    targets = shopfloor.line_targets(company_id, lines)
    found = []
    for line in lines:
        figures = days[line.id]
        if len(figures.hours) < 2:
            continue
        recent = [row for _, row, _ in figures.hours][-WINDOW_HOURS:]
        earned = sum(row.good_pieces * row.sam for row in recent)
        clock = sum(Decimal(row.operators * row.minutes) for row in recent)
        hours = {row.hour for row in recent}
        off = sum(
            Decimal(event.minutes * event.operators_affected)
            for _, event, reason, _ in figures.downtime
            if event.hour in hours
            and reason is not None
            and reason.efficiency_rule == "off_standard"
        )
        if clock - off <= 0:
            continue
        planned = Decimal(targets[line.id][3])
        achieved = earned / (clock - off) * 100
        gap = achieved - planned
        if abs(gap) <= EFFICIENCY_BAND:
            continue
        low = gap < 0
        found.append(
            Finding(
                "efficiency_low" if low else "efficiency_high",
                "warning" if low else "info",
                f"eff:{line.id}:{day.isoformat()}",
                f"{line.code} at {achieved:.1f}% against a plan of {planned:.1f}%",
                (
                    f"Hours {min(hours)}–{max(hours)} on {day:%d %b}; {figures.good:,} good "
                    "pieces so far today. "
                    + (
                        "Check the bottleneck station, absent operators and unrecorded stops."
                        if low
                        else "Output is above what the SAM allows; check the count and the "
                        "bulletin's SAM."
                    )
                ),
                work_center_id=line.id,
            )
        )
    return found


def machine_findings(company_id, moment, day):
    found = []
    limit = moment - timedelta(minutes=DOWN_MINUTES)
    down = db.session.scalars(
        select(Machine).where(
            Machine.organization_id == company_id,
            Machine.status == "maintenance",
            Machine.archived_at.is_(None),
        )
    ).all()
    since = {}
    if down:
        since = dict(
            db.session.execute(
                select(MachineStatusEvent.machine_id, func.max(MachineStatusEvent.occurred_at))
                .where(
                    MachineStatusEvent.organization_id == company_id,
                    MachineStatusEvent.machine_id.in_([m.id for m in down]),
                    MachineStatusEvent.to_status == "maintenance",
                )
                .group_by(MachineStatusEvent.machine_id)
            ).all()
        )
    for machine in down:
        started = since.get(machine.id) or machine.updated_at
        if started > limit:
            continue
        hours = (moment - started).total_seconds() / 3600
        found.append(
            Finding(
                "machine_down",
                "critical" if hours >= CRITICAL_DOWN_HOURS else "warning",
                f"down:{machine.id}:{started.date().isoformat()}",
                f"{machine.asset_tag} has been in maintenance for "
                + (f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"),
                f"{machine.make_model}. Its capacity is left out of planning until it is "
                "active again.",
                work_center_id=machine.work_center_id,
                machine_id=machine.id,
            )
        )
    events = shopfloor.effective(
        db.session.scalars(
            select(DowntimeEvent).where(
                DowntimeEvent.organization_id == company_id,
                DowntimeEvent.day == day,
                DowntimeEvent.machine_id.is_not(None),
            )
        ).all()
    )
    for original, event in events.items():
        if event.minutes <= DOWN_MINUTES or event.machine_id in {m.id for m in down}:
            continue
        machine = db.session.get(Machine, event.machine_id)
        found.append(
            Finding(
                "machine_down",
                "critical" if event.minutes >= CRITICAL_DOWN_HOURS * 60 else "warning",
                f"stop:{original}",
                f"{machine.asset_tag} stopped {event.minutes} minutes in hour {event.hour}",
                f"Recorded on {day:%d %b}{': ' + event.note if event.note else ''}.",
                work_center_id=event.work_center_id,
                machine_id=machine.id,
            )
        )
    return found


def order_findings(company_id):
    found = []
    for order in db.session.scalars(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.status.in_(("planned", "released")),
            ProductionOrder.planned_finish_on > ProductionOrder.ex_factory_on,
        )
    ):
        days = (order.planned_finish_on - order.ex_factory_on).days
        found.append(
            Finding(
                "order_late",
                "critical" if order.status == "released" else "warning",
                f"late:{order.id}:{order.ex_factory_on.isoformat()}",
                f"{order.reference} finishes {days} day{'s' if days != 1 else ''} after ex-factory",
                f"Planned finish {order.planned_finish_on:%d %b}, ex-factory "
                f"{order.ex_factory_on:%d %b}. Try more sewing lines or a higher priority "
                "on the order page.",
                production_order_id=order.id,
            )
        )
    return found


def starving_findings(company_id, day):
    lines = balancing.sewing_lines(company_id)
    days = shopfloor.floor(company_id, day, [line.id for line in lines])
    targets = shopfloor.line_targets(company_id, lines)
    wip = dict(
        db.session.execute(
            select(CutBundle.issued_line_id, func.sum(CutBundle.pieces))
            .where(CutBundle.organization_id == company_id, CutBundle.status == "issued")
            .group_by(CutBundle.issued_line_id)
        ).all()
    )
    ticketed = set(
        db.session.scalars(
            select(CutBundle.issued_line_id)
            .where(CutBundle.organization_id == company_id, CutBundle.issued_line_id.is_not(None))
            .distinct()
        )
    )
    found = []
    for line in lines:
        per_hour = targets[line.id][2]
        if line.id not in ticketed or not days[line.id].hours or not per_hour:
            continue
        waiting = Decimal(wip.get(line.id) or 0)
        if waiting >= per_hour:
            continue
        found.append(
            Finding(
                "line_starving",
                "warning",
                f"wip:{line.id}:{day.isoformat()}",
                f"{line.code} has {waiting:.0f} pieces waiting, under one hour of work",
                f"The line sews about {per_hour:.0f} pieces an hour. Issue more cut bundles "
                "before it stops for lack of feeding.",
                work_center_id=line.id,
            )
        )
    return found


def relaxation_findings(company_id):
    found = []
    rows = db.session.execute(
        select(DyeBatch, func.min(CutBundle.created_at), ProductionOrder)
        .join(
            CutBundle,
            (CutBundle.dye_batch_id == DyeBatch.id)
            & (CutBundle.organization_id == DyeBatch.organization_id),
        )
        .join(
            ProductionOrder,
            (ProductionOrder.id == CutBundle.production_order_id)
            & (ProductionOrder.organization_id == CutBundle.organization_id),
        )
        .where(DyeBatch.organization_id == company_id, DyeBatch.finished_at.is_not(None))
        .group_by(DyeBatch.id, ProductionOrder.id)
    ).all()
    if not rows:
        return found
    relax = dict(
        db.session.execute(
            select(FabricSpec.style_id, func.max(FabricSpec.relaxation_hours))
            .where(FabricSpec.organization_id == company_id)
            .group_by(FabricSpec.style_id)
        ).all()
    )
    for batch, first_cut, order in rows:
        hours = relax.get(order.style_id) or 0
        ready = batch.finished_at + timedelta(hours=hours)
        if first_cut >= ready:
            continue
        early = (ready - first_cut).total_seconds() / 3600
        found.append(
            Finding(
                "relaxation_breach",
                "critical",
                f"relax:{batch.id}:{order.id}",
                f"{order.reference} cut {early:.0f} h before batch {batch.batch_number} relaxed",
                f"The fabric needs {hours} h flat after finishing; cutting early risks "
                "shrinkage and size complaints. Hold the bundles for a measurement check.",
                production_order_id=order.id,
                dye_batch_id=batch.id,
            )
        )
    return found


def maintenance_findings(company_id, day):
    from app.services import maintenance

    overdue = {}
    for item in maintenance.schedule(company_id, today=day, horizon_days=0):
        if item.due_on < day and item.open_ticket is None:
            overdue.setdefault(item.plan.id, []).append(item)
    found = []
    for items in overdue.values():
        plan = items[0].plan
        worst = max(item.days_left(day) * -1 for item in items)
        tags = ", ".join(item.machine.asset_tag for item in items[:6])
        more = f" and {len(items) - 6} more" if len(items) > 6 else ""
        found.append(
            Finding(
                "maintenance_overdue",
                "critical" if worst >= 14 else "warning",
                f"pm:{plan.id}",
                f"{len(items)} machine{'s' if len(items) != 1 else ''} overdue for {plan.name}",
                f"Up to {worst} days late: {tags}{more}. Plan the jobs from the maintenance "
                "page; overdue servicing raises breakdown risk.",
            )
        )
    return found


def quality_findings(company_id, day):
    from app.services import linequality

    lines = balancing.sewing_lines(company_id)
    days = linequality.floor(company_id, day, [line.id for line in lines])
    found = []
    for line in lines:
        quality = days[line.id]
        dhu = quality.dhu("endline")
        if dhu is None or quality.pieces["endline"] < 50 or dhu <= linequality.DHU_LIMIT:
            continue
        # Most frequent defect; ties go to the alphabetically first so the text is stable.
        ranked = sorted(quality.by_code.items(), key=lambda pair: (-pair[1], pair[0]))
        worst = ranked[0][0] if ranked else None
        found.append(
            Finding(
                "quality_dhu",
                "critical" if dhu > linequality.DHU_LIMIT * 2 else "warning",
                f"dhu:{line.id}:{day.isoformat()}",
                f"{line.code} end-line DHU {dhu:.1f}, above {linequality.DHU_LIMIT}",
                f"{quality.defects['endline']} defects in {quality.pieces['endline']} pieces "
                f"checked on {day:%d %b}"
                + (f"; most often {worst.replace('_', ' ')}" if worst else "")
                + ". Check the operations named on the line page.",
                work_center_id=line.id,
            )
        )
    return found


def findings(company_id, day, moment):
    return (
        quality_findings(company_id, day)
        + maintenance_findings(company_id, day)
        + order_findings(company_id)
        + relaxation_findings(company_id)
        + machine_findings(company_id, moment, day)
        + efficiency_findings(company_id, day)
        + starving_findings(company_id, day)
    )


# ---------- Keeping alerts ----------


def _transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError("Alerts changed at the same time; reload and try again.") from exc
    except Exception:
        db.session.rollback()
        raise


def scan(company_id, day=None, moment=None):
    """Run every check and reconcile the results with the stored alerts."""
    require(company_id, "factory.read")
    day = day or date.today()
    moment = moment or now()

    def action():
        company_lock(company_id)
        require(company_id, "factory.read")
        current = {f.key: f for f in findings(company_id, day, moment)}
        unresolved = {
            row.dedupe_key: row
            for row in db.session.scalars(
                select(FactoryAlert)
                .where(
                    FactoryAlert.organization_id == company_id,
                    FactoryAlert.status != "resolved",
                )
                .with_for_update()
            )
        }
        raised = 0
        for key, finding in current.items():
            row = unresolved.get(key)
            if row is None:
                db.session.add(
                    FactoryAlert(
                        organization_id=company_id,
                        kind=finding.kind,
                        severity=finding.severity,
                        dedupe_key=key,
                        title=finding.title[:160],
                        detail=finding.detail[:400],
                        work_center_id=finding.work_center_id,
                        machine_id=finding.machine_id,
                        production_order_id=finding.production_order_id,
                        dye_batch_id=finding.dye_batch_id,
                        first_seen_at=moment,
                        last_seen_at=moment,
                    )
                )
                raised += 1
            else:
                row.last_seen_at = max(moment, row.first_seen_at)
                row.cleared_at = None
                row.kind, row.severity = finding.kind, finding.severity
                row.title, row.detail = finding.title[:160], finding.detail[:400]
        cleared = 0
        for key, row in unresolved.items():
            if key not in current and row.cleared_at is None:
                row.cleared_at = moment
                cleared += 1
        db.session.flush()
        audit(
            company_id,
            "factory.alerts_checked",
            "factory_alerts",
            None,
            {"count": raised, "quantity": cleared},
        )
        return raised, cleared, len(current)

    return _transaction(action)


def scan_quietly(company_id):
    """Re-check after a floor or planning change; a failed check never undoes that change."""
    if not allowed(company_id, "factory.read"):
        return None
    try:
        return scan(company_id)
    except (DomainError, HTTPException):
        db.session.rollback()
        return None


def _locked(company_id, alert_id, version):
    company_lock(company_id)
    require(company_id, "factory.record")
    alert = scoped(FactoryAlert, company_id, alert_id, lock=True)
    if alert.version != version:
        raise DomainError("This alert changed; reload before continuing.")
    if alert.status == "resolved":
        raise DomainError("This alert is already resolved.")
    return alert


def acknowledge(company_id, alert_id, version, owner_id=None):
    """Mark an alert seen, optionally giving it an owner (who is notified in the app)."""
    require(company_id, "factory.record")

    def action():
        alert = _locked(company_id, alert_id, version)
        member = membership_for(company_id)
        if owner_id:
            owner = scoped(Membership, company_id, owner_id)
            if owner.status != "active" or owner.archived_at:
                raise DomainError("Choose an active member as owner.")
            if owner.id != alert.owner_id:
                alert.owner_id = owner.id
                from app.services.evidence import notify

                notify(
                    company_id,
                    owner.id,
                    "factory_alert",
                    {"message": f"Factory alert assigned to you: {alert.title}"[:200]},
                )
        if alert.status == "open":
            alert.status = "acknowledged"
            alert.acknowledged_at = now()
            alert.acknowledged_by_id = member.id if member else None
        db.session.flush()
        audit(
            company_id,
            "factory.alert_acknowledged",
            "factory_alerts",
            alert.id,
            {"to_status": alert.status},
        )
        return alert

    return _transaction(action)


def resolve(company_id, alert_id, version, note):
    require(company_id, "factory.record")
    note = str(note or "").strip()
    if not note or len(note) > 400 or "\x00" in note:
        raise DomainError("Say what was done, in up to 400 characters.")

    def action():
        alert = _locked(company_id, alert_id, version)
        member = membership_for(company_id)
        alert.status = "resolved"
        alert.resolved_at = now()
        alert.resolved_by_id = member.id if member else None
        alert.resolution_note = note
        db.session.flush()
        audit(
            company_id,
            "factory.alert_resolved",
            "factory_alerts",
            alert.id,
            {"from_status": "open", "to_status": "resolved"},
        )
        return alert

    return _transaction(action)


def open_counts(company_id):
    """{severity: unresolved count} for the navigation badge and dashboard."""
    return dict(
        db.session.execute(
            select(FactoryAlert.severity, func.count(FactoryAlert.id))
            .where(FactoryAlert.organization_id == company_id, FactoryAlert.status != "resolved")
            .group_by(FactoryAlert.severity)
        ).all()
    )


def age_text(moment: datetime, reference: datetime):
    minutes = max(0, int((reference - moment).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // 1440} days"
