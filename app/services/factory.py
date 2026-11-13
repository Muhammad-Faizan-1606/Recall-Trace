"""Factory register operations: work centres, machines, shifts, calendar and transit.

Same rules as master data: every mutation re-checks permission under the company lock,
validates on the server, uses optimistic versions, writes an audit event and either
deletes an unused record or archives a referenced one. Machine status is never edited
directly; it changes through `change_status`, which appends an immutable history row.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import g
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.extensions import db
from app.models import Item, now
from app.models.factory import (
    CALENDAR_KINDS,
    CAPACITY_BASES,
    DEPARTMENTS,
    FABRIC_TYPES,
    MACHINE_STATUSES,
    PRODUCT_TYPES,
    CalendarException,
    FabricSpec,
    Machine,
    MachineClass,
    MachineStatusEvent,
    ShiftPattern,
    SiteTransitTime,
    Style,
    WorkCenter,
)
from app.models.master import Partner, PartnerRoleAssignment, Site
from app.policies import membership_for, require
from app.services.audit import record as audit
from app.services.business import DomainError, company_lock, scoped
from app.services.master import references


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"  # text, int, decimal, choice, parent, date, days
    required: bool = True
    choices: tuple = ()
    parent: type | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    help: str = ""


def dec(value):
    return Decimal(str(value))


RESOURCES = {
    "shift-patterns": (
        ShiftPattern,
        "Shift patterns",
        (
            Field("code", "Code"),
            Field("name", "Name"),
            Field("shifts_per_day", "Shifts per day", "int", minimum=dec(1), maximum=dec(3)),
            Field(
                "hours_per_shift", "Hours per shift", "decimal", minimum=dec("0.5"), maximum=dec(12)
            ),
            Field(
                "break_minutes_per_shift",
                "Break minutes per shift",
                "int",
                minimum=dec(0),
                maximum=dec(240),
            ),
            Field(
                "working_days",
                "Working days",
                "days",
                help="Tick the days this pattern normally works.",
            ),
        ),
    ),
    "work-centers": (
        WorkCenter,
        "Work centres",
        (
            Field("code", "Code", help="Short and unique, e.g. MANGA-DYE or QIE2-L04."),
            Field("name", "Name"),
            Field("department", "Department", "choice", choices=DEPARTMENTS),
            Field("site_id", "Site", "parent", parent=Site),
            Field("shift_pattern_id", "Shift pattern", "parent", parent=ShiftPattern),
            Field(
                "target_efficiency",
                "Target efficiency (%)",
                "decimal",
                minimum=dec(1),
                maximum=dec(100),
                help="Planned share of rated output, e.g. 75.",
            ),
        ),
    ),
    "machine-classes": (
        MachineClass,
        "Machine classes",
        (
            Field("code", "Code"),
            Field("name", "Name"),
            Field("department", "Department", "choice", choices=DEPARTMENTS),
            Field(
                "capacity_basis",
                "Capacity formula",
                "choice",
                choices=CAPACITY_BASES,
                help="knit: RPM and feeders · batch: kg per batch · continuous: metres per "
                "minute · rate: units per hour · sewing: one operator station.",
            ),
            Field(
                "output_unit",
                "Output unit (rate machines)",
                required=False,
                help="For rate machines, e.g. panels, impressions or pieces.",
            ),
            Field(
                "feeders_per_course",
                "Feeders per course (knit)",
                "int",
                False,
                minimum=dec(1),
                maximum=dec(4),
                help="1 for single jersey, 2 for interlock.",
            ),
            Field(
                "courses_per_cm",
                "Courses per cm (knit)",
                "decimal",
                False,
                minimum=dec("0.1"),
                maximum=dec(100),
            ),
            Field(
                "fabric_width_m",
                "Reference fabric width m (knit)",
                "decimal",
                False,
                minimum=dec("0.1"),
                maximum=dec(10),
            ),
            Field(
                "fabric_gsm",
                "Reference GSM (knit)",
                "decimal",
                False,
                minimum=dec(20),
                maximum=dec(1000),
            ),
            Field(
                "fill_factor",
                "Fill factor (batch)",
                "decimal",
                False,
                minimum=dec("0.1"),
                maximum=dec(1),
                help="Safe load share, e.g. 0.90.",
            ),
            Field(
                "cycle_hours",
                "Cycle hours (batch)",
                "decimal",
                False,
                minimum=dec("0.1"),
                maximum=dec(48),
            ),
            Field(
                "setup_hours",
                "Setup hours (batch)",
                "decimal",
                False,
                minimum=dec(0),
                maximum=dec(24),
            ),
        ),
    ),
    "machines": (
        Machine,
        "Machines",
        (
            Field("asset_tag", "Asset tag", help="The label on the machine, e.g. KNT-042."),
            Field("make_model", "Make and model"),
            Field("machine_class_id", "Machine class", "parent", parent=MachineClass),
            Field("work_center_id", "Work centre", "parent", parent=WorkCenter),
            Field(
                "rated_value",
                "Rated value",
                "decimal",
                minimum=dec("0.001"),
                maximum=dec(1000000),
                help="RPM for knitting, kg per batch for dyeing, m/min for stenters, "
                "units per hour for rate machines, 1 for a sewing station.",
            ),
            Field("feeders", "Feeders (knitting)", "int", False, minimum=dec(1), maximum=dec(400)),
            Field("gauge", "Gauge E (knitting)", "int", False, minimum=dec(3), maximum=dec(60)),
            Field(
                "diameter_in",
                "Diameter inches (knitting)",
                "decimal",
                False,
                minimum=dec(1),
                maximum=dec(60),
            ),
            Field(
                "efficiency",
                "Own efficiency (%)",
                "decimal",
                False,
                minimum=dec(1),
                maximum=dec(100),
                help="Leave empty to use the work centre target.",
            ),
            Field("commissioned_on", "Commissioned on", "date", False),
        ),
    ),
    "calendar": (
        CalendarException,
        "Calendar exceptions",
        (
            Field("site_id", "Site", "parent", parent=Site),
            Field("day", "Date", "date"),
            Field("kind", "Kind", "choice", choices=CALENDAR_KINDS),
            Field(
                "hours_per_shift",
                "Hours per shift that day",
                "decimal",
                minimum=dec(0),
                maximum=dec(12),
                help="0 for a holiday or shutdown.",
            ),
            Field("note", "Note", help="e.g. Eid ul-Fitr, boiler inspection."),
        ),
    ),
    "transit": (
        SiteTransitTime,
        "Transit times",
        (
            Field("from_site_id", "From site", "parent", parent=Site),
            Field("to_site_id", "To site", "parent", parent=Site),
            Field(
                "hours",
                "Hours",
                "decimal",
                minimum=dec(0),
                maximum=dec(240),
                help="Loading, travel and unloading.",
            ),
            Field("note", "Note", required=False),
        ),
    ),
    "styles": (
        Style,
        "Styles",
        (
            Field("code", "Style number", help="The buyer's style number, e.g. NP-TEE-101."),
            Field("name", "Name"),
            Field("product_type", "Product type", "choice", choices=PRODUCT_TYPES),
            Field("season", "Season", required=False, help="e.g. SS27 or FW26."),
            Field(
                "buyer_id",
                "Buyer",
                "parent",
                False,
                parent=Partner,
                help="A partner with the customer role.",
            ),
            Field(
                "item_id",
                "Catalog item",
                "parent",
                False,
                parent=Item,
                help="Links the style to the finished-goods item used in stock and trace.",
            ),
        ),
    ),
    "fabric-specs": (
        FabricSpec,
        "Fabric specs",
        (
            Field("style_id", "Style", "parent", parent=Style),
            Field("component", "Component", help="Body, rib, hood lining…"),
            Field("fabric_type", "Fabric type", "choice", choices=FABRIC_TYPES),
            Field("composition", "Composition", help="e.g. 100% cotton or 88% PES 12% EA."),
            Field("gsm", "GSM (g/m²)", "decimal", minimum=dec(20), maximum=dec(1000)),
            Field("width_m", "Finished width (m)", "decimal", minimum=dec("0.1"), maximum=dec(10)),
            Field(
                "courses_per_cm",
                "Courses per cm",
                "decimal",
                False,
                minimum=dec("0.1"),
                maximum=dec(100),
                help="Used for knitting time; optional.",
            ),
            Field(
                "consumption_kg",
                "Fabric per garment (kg)",
                "decimal",
                minimum=dec("0.001"),
                maximum=dec(10),
                help="Finished fabric per piece including cutting waste.",
            ),
            Field(
                "relaxation_hours",
                "Relaxation before cutting (hours)",
                "int",
                minimum=dec(0),
                maximum=dec(168),
                help="24 for cotton; up to 48 for high-spandex fabric.",
            ),
        ),
    ),
}
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# Identity that history depends on cannot change once something refers to the record.
FROZEN = {
    "machines": ("machine_class_id", "work_center_id"),
    "machine-classes": ("capacity_basis", "department"),
    "work-centers": ("site_id", "department"),
    "fabric-specs": ("style_id",),
}


def spec(resource):
    model, title, fields = RESOURCES[resource]
    return model, title, fields


def label(row):
    if row is None:
        return "—"
    if isinstance(row, Machine):
        return f"{row.asset_tag} — {row.make_model}"
    if isinstance(row, FabricSpec):
        return f"{row.component} — {row.fabric_type.replace('_', ' ')} {row.gsm} g/m²"
    if isinstance(row, CalendarException):
        return f"{row.day:%d %b %Y} — {row.note}"
    if isinstance(row, SiteTransitTime):
        names = g.setdefault("_site_names", {})
        for site_id in (row.from_site_id, row.to_site_id):
            if site_id not in names:
                names[site_id] = db.session.get(Site, site_id).name
        return f"{names[row.from_site_id]} → {names[row.to_site_id]}"
    code, name = getattr(row, "code", None), getattr(row, "name", None)
    return f"{code} — {name}" if code and name and code != name else str(code or name or row.id)


def lookup(company_id, resource, record_id, lock=False):
    require(company_id, "factory.read")
    return scoped(RESOURCES[resource][0], company_id, record_id, lock=lock)


def _number(item, value):
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(f"{item.label} must be a number.") from exc
    if not number.is_finite():
        raise DomainError(f"{item.label} must be a number.")
    if item.kind == "int":
        if number != number.to_integral_value():
            raise DomainError(f"{item.label} must be a whole number.")
        number = int(number)
    if item.minimum is not None and number < item.minimum:
        raise DomainError(f"{item.label} must be at least {item.minimum}.")
    if item.maximum is not None and number > item.maximum:
        raise DomainError(f"{item.label} must be at most {item.maximum}.")
    return number


def _values(company_id, resource, values):
    model, _, fields = spec(resource)
    clean = {}
    for item in fields:
        value = values.get(item.name)
        if isinstance(value, str):
            if "\x00" in value:
                raise DomainError("Text cannot contain NUL characters.")
            value = value.strip()
        if item.kind == "days":
            days = value if isinstance(value, (list, tuple)) else []
            mask = "".join(
                "1" if str(index) in {str(d) for d in days} else "0" for index in range(7)
            )
            if mask == "0000000":
                raise DomainError("Choose at least one working day.")
            clean[item.name] = mask
            continue
        if value in ("", None):
            if item.required:
                raise DomainError(f"{item.label} is required.")
            clean[item.name] = None
            continue
        if item.kind in ("int", "decimal"):
            value = _number(item, value)
        elif item.kind == "choice":
            if value not in item.choices:
                raise DomainError(f"Choose a permitted {item.label.lower()}.")
        elif item.kind == "date":
            if not isinstance(value, date):
                try:
                    value = date.fromisoformat(str(value))
                except ValueError as exc:
                    raise DomainError(f"Enter {item.label.lower()} as YYYY-MM-DD.") from exc
        elif item.kind == "parent":
            try:
                value = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
            except (TypeError, ValueError) as exc:
                raise DomainError("Choose a valid related record.") from exc
            parent = scoped(item.parent, company_id, value, lock=True)
            if getattr(parent, "archived_at", None):
                raise DomainError(f"Choose an active {item.label.lower()}.")
        else:
            maximum = getattr(model.__table__.c[item.name].type, "length", None) or 4000
            if len(value) > maximum:
                raise DomainError(f"{item.label} is too long.")
        clean[item.name] = value
    _rules(company_id, resource, clean)
    return clean


def _rules(company_id, resource, clean):
    """Cross-field rules a form cannot express."""
    if resource == "shift-patterns":
        if clean["break_minutes_per_shift"] >= clean["hours_per_shift"] * 60:
            raise DomainError("Breaks must be shorter than the shift.")
    if resource == "machine-classes":
        basis = clean["capacity_basis"]
        knit = ("feeders_per_course", "courses_per_cm", "fabric_width_m", "fabric_gsm")
        batch = ("fill_factor", "cycle_hours", "setup_hours")
        needed = {"knit": knit, "batch": batch}.get(basis, ())
        missing = [name for name in needed if clean[name] is None]
        if missing:
            labels = {f.name: f.label for f in spec(resource)[2]}
            raise DomainError(
                f"The {basis} formula needs: " + ", ".join(labels[n] for n in missing) + "."
            )
        for name in knit + batch:
            if name not in needed:
                clean[name] = None
        if basis == "rate":
            if not clean["output_unit"]:
                raise DomainError("Name the output unit for a rate machine, e.g. panels.")
        else:
            clean["output_unit"] = {"knit": "kg", "batch": "kg", "continuous": "m"}.get(
                basis, "SAM min"
            )
    if resource == "machines":
        machine_class = scoped(MachineClass, company_id, clean["machine_class_id"])
        center = scoped(WorkCenter, company_id, clean["work_center_id"])
        if machine_class.department != center.department:
            raise DomainError(
                f"A {machine_class.department} machine cannot be placed in a "
                f"{center.department} work centre."
            )
        if machine_class.capacity_basis == "knit":
            if not clean["feeders"]:
                raise DomainError("Knitting machines need their number of feeders.")
        else:
            clean.update(feeders=None, gauge=None, diameter_in=None)
    if resource == "styles" and clean["buyer_id"]:
        if not db.session.scalar(
            select(PartnerRoleAssignment.id).where(
                PartnerRoleAssignment.organization_id == company_id,
                PartnerRoleAssignment.partner_id == clean["buyer_id"],
                PartnerRoleAssignment.role_code == "customer",
            )
        ):
            raise DomainError("The buyer must be a partner with the customer role.")
    if resource == "transit" and clean["from_site_id"] == clean["to_site_id"]:
        raise DomainError("Choose two different sites.")


def save(company_id, resource, values, record_id=None, version=None):
    require(company_id, "factory.manage")
    model = spec(resource)[0]
    try:
        company_lock(company_id)
        require(company_id, "factory.manage")
        row = (
            lookup(company_id, resource, record_id, lock=True)
            if record_id
            else model(organization_id=company_id)
        )
        if record_id and (row.version != version or getattr(row, "archived_at", None)):
            raise DomainError("This record changed or was archived; reload before editing.")
        clean = _values(company_id, resource, values)
        if record_id and resource in FROZEN and references(row):
            if any(getattr(row, name) != clean[name] for name in FROZEN[resource]):
                raise DomainError(
                    "Records already in use keep their site, department, class and formula; "
                    "create a new record instead."
                )
        for name, value in clean.items():
            setattr(row, name, value)
        db.session.add(row)
        db.session.flush()
        if resource == "machines" and not record_id:
            db.session.add(
                MachineStatusEvent(
                    organization_id=company_id,
                    machine_id=row.id,
                    from_status=None,
                    to_status=row.status,
                    reason="Registered",
                    actor_id=_actor(company_id),
                )
            )
        audit(
            company_id,
            "factory.updated" if record_id else "factory.created",
            row.__tablename__,
            row.id,
            {"version": row.version},
        )
        db.session.commit()
        return row
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError(
            "A duplicate code, date or route, or a concurrent change, prevented saving."
        ) from exc
    except Exception:
        db.session.rollback()
        raise


def _actor(company_id):
    member = membership_for(company_id)
    return member.id if member else None


def change_status(company_id, machine_id, to_status, reason, version):
    """Move a machine between active, idle, maintenance and decommissioned, with a reason."""
    require(company_id, "factory.manage")
    reason = (reason or "").strip()
    if to_status not in MACHINE_STATUSES:
        raise DomainError("Choose a permitted machine status.")
    if not reason or len(reason) > 500 or "\x00" in reason:
        raise DomainError("Give a short reason (up to 500 characters).")
    try:
        company_lock(company_id)
        require(company_id, "factory.manage")
        machine = lookup(company_id, "machines", machine_id, lock=True)
        if machine.version != version or machine.archived_at:
            raise DomainError("This machine changed or was archived; reload and try again.")
        if machine.status == to_status:
            raise DomainError(f"The machine is already {to_status}.")
        if machine.status == "decommissioned":
            raise DomainError("Decommissioned machines stay out of service; register a new one.")
        previous = machine.status
        machine.status = to_status
        db.session.add(
            MachineStatusEvent(
                organization_id=company_id,
                machine_id=machine.id,
                from_status=previous,
                to_status=to_status,
                reason=reason,
                actor_id=_actor(company_id),
                occurred_at=now(),
            )
        )
        db.session.flush()
        audit(
            company_id,
            "factory.machine_status",
            "machines",
            machine.id,
            {"from_status": previous, "to_status": to_status},
        )
        db.session.commit()
        return machine
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError("A concurrent change prevented the status update.") from exc
    except Exception:
        db.session.rollback()
        raise


def remove(company_id, resource, record_id, version):
    require(company_id, "factory.manage")
    try:
        company_lock(company_id)
        require(company_id, "factory.manage")
        row = lookup(company_id, resource, record_id, lock=True)
        if row.version != version:
            raise DomainError("This record changed; reload before removing it.")
        if references(row):
            if not hasattr(row, "archived_at"):
                raise DomainError("Referenced records cannot be removed.")
            row.archived_at = now()
            message = "Record is in use, so it was archived; its history is kept."
        else:
            db.session.delete(row)
            message = "Unused record deleted."
        audit(
            company_id,
            "factory.archived" if getattr(row, "archived_at", None) else "factory.deleted",
            row.__tablename__,
            row.id,
        )
        db.session.commit()
        return message
    except (IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        raise DomainError("A related record or concurrent change prevented removal.") from exc
    except Exception:
        db.session.rollback()
        raise


def machines_by_center(company_id, center_ids=None):
    """{work_center_id: [(machine, machine_class)]} for live (unarchived) machines."""
    query = (
        select(Machine, MachineClass)
        .join(
            MachineClass,
            (MachineClass.id == Machine.machine_class_id)
            & (MachineClass.organization_id == Machine.organization_id),
        )
        .where(Machine.organization_id == company_id, Machine.archived_at.is_(None))
        .order_by(Machine.asset_tag)
    )
    if center_ids is not None:
        query = query.where(Machine.work_center_id.in_(center_ids))
    grouped = {}
    for machine, machine_class in db.session.execute(query).all():
        grouped.setdefault(machine.work_center_id, []).append((machine, machine_class))
    return grouped


def exceptions_by_site(company_id, start, end):
    rows = db.session.scalars(
        select(CalendarException).where(
            CalendarException.organization_id == company_id,
            CalendarException.day >= start,
            CalendarException.day <= end,
        )
    ).all()
    grouped = {}
    for row in rows:
        grouped.setdefault(row.site_id, {})[row.day] = row
    return grouped
