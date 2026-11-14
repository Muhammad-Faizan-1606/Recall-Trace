"""Maintenance: breakdown and preventive tickets, the preventive schedule, MTBF and MTTR.

A ticket moves open → in progress → closed. Reporting a breakdown puts the machine into
maintenance at once (so planning stops counting it); a preventive job does so when work
starts. Closing a ticket returns the machine to service. Every status change is recorded
as an immutable machine status event, exactly as a manual status change would be.

Reliability over a window (calendar hours, 90 days by default):

    MTTR  = average repair time of closed breakdowns (finished − reported)
    MTBF  = (hours in service in the window − breakdown down-hours) ÷ number of breakdowns
    response = average time from report to work starting

A preventive plan is due `interval_days` after its last closed job on that machine, or after
the machine was commissioned (or registered) when it has never been done.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import now
from app.models.factory import (
    Machine,
    MachineClass,
    MachineStatusEvent,
    MaintenancePlan,
    MaintenanceTicket,
)
from app.policies import membership_for, require
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped

PERMISSION = "factory.record"
WINDOW_DAYS = 90
DUE_SOON_DAYS = 14


# ---------- Writing ----------


def _transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "This machine already has an unfinished ticket, or something changed at the same "
            "time; reload and try again."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def _start(company_id):
    company_lock(company_id)
    require(company_id, PERMISSION)
    member = membership_for(company_id)
    return member.id if member else None


def _text(value, label, maximum, required=True):
    text = str(value or "").strip()
    if "\x00" in text or len(text) > maximum:
        raise DomainError(f"{label} must be at most {maximum} characters.")
    if required and not text:
        raise DomainError(f"{label} is required.")
    return text or None


def set_status(company_id, machine, to_status, reason, actor_id, moment=None):
    """Change a machine's status inside the caller's transaction, with its history event."""
    if machine.status == to_status:
        return
    if machine.status == "decommissioned":
        raise DomainError("Decommissioned machines stay out of service.")
    db.session.add(
        MachineStatusEvent(
            organization_id=company_id,
            machine_id=machine.id,
            from_status=machine.status,
            to_status=to_status,
            reason=reason[:500],
            actor_id=actor_id,
            occurred_at=moment or now(),
        )
    )
    previous, machine.status = machine.status, to_status
    audit(
        company_id,
        "factory.machine_status",
        "machines",
        machine.id,
        {"from_status": previous, "to_status": to_status},
    )


def _next_number(company_id):
    count = db.session.scalar(
        select(func.count(MaintenanceTicket.id)).where(
            MaintenanceTicket.organization_id == company_id
        )
    )
    return f"MT-{count + 1:05d}"


def _machine(company_id, machine_id=None, asset_tag=None):
    if asset_tag:
        machine = db.session.scalar(
            select(Machine).where(
                Machine.organization_id == company_id,
                func.upper(Machine.asset_tag) == str(asset_tag).strip().upper(),
            )
        )
        if machine is None:
            raise DomainError(f"No machine with asset tag {str(asset_tag).strip()[:40]}.")
    else:
        try:
            machine_id = uuid.UUID(str(machine_id))
        except (TypeError, ValueError) as exc:
            raise DomainError("Choose a machine.") from exc
        machine = scoped(Machine, company_id, machine_id)
    db.session.refresh(machine, with_for_update=True)
    if machine.archived_at or machine.status == "decommissioned":
        raise DomainError("That machine is no longer in service.")
    return machine


def report_breakdown(company_id, values):
    """Open a breakdown ticket; the machine goes into maintenance immediately."""
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        machine = _machine(company_id, values.get("machine_id"), values.get("asset_tag"))
        description = _text(values.get("description"), "What is wrong", 400)
        ticket = MaintenanceTicket(
            organization_id=company_id,
            number=_next_number(company_id),
            machine_id=machine.id,
            kind="breakdown",
            description=description,
            reported_by_id=member_id,
            reported_at=now(),
        )
        db.session.add(ticket)
        db.session.flush()
        set_status(
            company_id,
            machine,
            "maintenance",
            f"Breakdown {ticket.number}: {description}",
            member_id,
        )
        db.session.flush()
        audit(
            company_id,
            "factory.ticket_opened",
            "maintenance_tickets",
            ticket.id,
            {"operation": "breakdown"},
        )
        return ticket

    return _transaction(action)


def plan_job(company_id, plan_id, machine_id):
    """Open a preventive ticket for a due plan; the machine keeps running until work starts."""
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        plan = scoped(MaintenancePlan, company_id, plan_id)
        if plan.archived_at:
            raise DomainError("That plan is archived.")
        machine = _machine(company_id, machine_id)
        if machine.machine_class_id != plan.machine_class_id:
            raise DomainError("That plan is for a different kind of machine.")
        ticket = MaintenanceTicket(
            organization_id=company_id,
            number=_next_number(company_id),
            machine_id=machine.id,
            kind="preventive",
            plan_id=plan.id,
            description=f"{plan.name}: {plan.tasks}"[:400],
            reported_by_id=member_id,
            reported_at=now(),
        )
        db.session.add(ticket)
        db.session.flush()
        audit(
            company_id,
            "factory.ticket_opened",
            "maintenance_tickets",
            ticket.id,
            {"operation": "preventive"},
        )
        return ticket

    return _transaction(action)


def start(company_id, ticket_id, version):
    require(company_id, PERMISSION)

    def action():
        member_id = _start(company_id)
        ticket = scoped(MaintenanceTicket, company_id, ticket_id, lock=True)
        if ticket.version != version:
            raise DomainError("This ticket changed; reload before continuing.")
        if ticket.status != "open":
            raise DomainError("Only open tickets can be started.")
        machine = scoped(Machine, company_id, ticket.machine_id, lock=True)
        ticket.status, ticket.started_at = "in_progress", max(now(), ticket.reported_at)
        set_status(
            company_id, machine, "maintenance", f"Work started on {ticket.number}", member_id
        )
        db.session.flush()
        audit(
            company_id,
            "factory.ticket_started",
            "maintenance_tickets",
            ticket.id,
            {"to_status": "in_progress"},
        )
        return ticket

    return _transaction(action)


def close(company_id, ticket_id, version, work_done, parts_used=None):
    """Finish a ticket and return the machine to service."""
    require(company_id, PERMISSION)
    work_done = _text(work_done, "Work done", 400)
    parts_used = _text(parts_used, "Parts used", 200, required=False)

    def action():
        member_id = _start(company_id)
        ticket = scoped(MaintenanceTicket, company_id, ticket_id, lock=True)
        if ticket.version != version:
            raise DomainError("This ticket changed; reload before continuing.")
        if ticket.status != "in_progress":
            raise DomainError("Start work on the ticket before closing it.")
        machine = scoped(Machine, company_id, ticket.machine_id, lock=True)
        ticket.status = "closed"
        ticket.finished_at = max(now(), ticket.started_at)
        ticket.work_done, ticket.parts_used, ticket.closed_by_id = work_done, parts_used, member_id
        if machine.status == "maintenance":
            set_status(company_id, machine, "active", f"{ticket.number} closed", member_id)
        db.session.flush()
        audit(
            company_id,
            "factory.ticket_closed",
            "maintenance_tickets",
            ticket.id,
            {"to_status": "closed"},
        )
        return ticket

    return _transaction(action)


# ---------- Reading ----------


def hours(delta):
    return delta.total_seconds() / 3600


@dataclass
class Reliability:
    machine: Machine
    breakdowns: int
    down_hours: float
    mttr: float | None
    mtbf: float | None
    response: float | None


def reliability(company_id, moment=None, window_days=WINDOW_DAYS, machine_ids=None):
    """{machine id: Reliability} for machines with breakdowns in the window."""
    moment = moment or now()
    start = moment - timedelta(days=window_days)
    query = select(MaintenanceTicket).where(
        MaintenanceTicket.organization_id == company_id,
        MaintenanceTicket.kind == "breakdown",
        MaintenanceTicket.reported_at >= start,
    )
    if machine_ids is not None:
        query = query.where(MaintenanceTicket.machine_id.in_(machine_ids))
    tickets = db.session.scalars(query).all()
    grouped = {}
    for ticket in tickets:
        grouped.setdefault(ticket.machine_id, []).append(ticket)
    if not grouped:
        return {}
    machines = {
        m.id: m
        for m in db.session.scalars(
            select(Machine).where(Machine.organization_id == company_id, Machine.id.in_(grouped))
        )
    }
    result = {}
    for machine_id, rows in grouped.items():
        machine = machines[machine_id]
        # In service since commissioning when known, otherwise since it was registered.
        if machine.commissioned_on:
            began = datetime.combine(machine.commissioned_on, time(), start.tzinfo)
        else:
            began = min(machine.created_at, moment)
        since = max(start, began)
        down = sum(hours((t.finished_at or moment) - t.reported_at) for t in rows)
        closed = [t for t in rows if t.finished_at]
        started = [t for t in rows if t.started_at]
        in_service = max(hours(moment - since) - down, 0)
        result[machine_id] = Reliability(
            machine=machine,
            breakdowns=len(rows),
            down_hours=down,
            mttr=(sum(hours(t.finished_at - t.reported_at) for t in closed) / len(closed))
            if closed
            else None,
            mtbf=in_service / len(rows),
            response=(sum(hours(t.started_at - t.reported_at) for t in started) / len(started))
            if started
            else None,
        )
    return result


@dataclass
class Due:
    plan: MaintenancePlan
    machine: Machine
    last_done: date | None
    due_on: date
    open_ticket: MaintenanceTicket | None

    def days_left(self, today):
        return (self.due_on - today).days


def schedule(company_id, today=None, horizon_days=DUE_SOON_DAYS):
    """Preventive jobs overdue or due within the horizon, most overdue first."""
    today = today or date.today()
    plans = db.session.scalars(
        select(MaintenancePlan).where(
            MaintenancePlan.organization_id == company_id, MaintenancePlan.archived_at.is_(None)
        )
    ).all()
    if not plans:
        return []
    class_ids = {plan.machine_class_id for plan in plans}
    machines = db.session.scalars(
        select(Machine).where(
            Machine.organization_id == company_id,
            Machine.machine_class_id.in_(class_ids),
            Machine.archived_at.is_(None),
            Machine.status != "decommissioned",
        )
    ).all()
    last = {
        (machine_id, plan_id): finished
        for machine_id, plan_id, finished in db.session.execute(
            select(
                MaintenanceTicket.machine_id,
                MaintenanceTicket.plan_id,
                func.max(MaintenanceTicket.finished_at),
            )
            .where(
                MaintenanceTicket.organization_id == company_id,
                MaintenanceTicket.kind == "preventive",
                MaintenanceTicket.status == "closed",
            )
            .group_by(MaintenanceTicket.machine_id, MaintenanceTicket.plan_id)
        )
    }
    unfinished = {
        t.machine_id: t
        for t in db.session.scalars(
            select(MaintenanceTicket).where(
                MaintenanceTicket.organization_id == company_id,
                MaintenanceTicket.status != "closed",
            )
        )
    }
    by_class = {}
    for machine in machines:
        by_class.setdefault(machine.machine_class_id, []).append(machine)
    due = []
    for plan in plans:
        for machine in by_class.get(plan.machine_class_id, []):
            done = last.get((machine.id, plan.id))
            base = done.date() if done else (machine.commissioned_on or machine.created_at.date())
            due_on = base + timedelta(days=plan.interval_days)
            if due_on <= today + timedelta(days=horizon_days):
                due.append(
                    Due(
                        plan,
                        machine,
                        done.date() if done else None,
                        due_on,
                        unfinished.get(machine.id),
                    )
                )
    due.sort(key=lambda d: (d.due_on, d.machine.asset_tag))
    return due


def unfinished_tickets(company_id):
    return db.session.scalars(
        select(MaintenanceTicket)
        .where(
            MaintenanceTicket.organization_id == company_id, MaintenanceTicket.status != "closed"
        )
        .order_by(MaintenanceTicket.kind, MaintenanceTicket.reported_at)
    ).all()


def class_names(company_id):
    return {
        c.id: c.name
        for c in db.session.scalars(
            select(MachineClass).where(MachineClass.organization_id == company_id)
        )
    }
