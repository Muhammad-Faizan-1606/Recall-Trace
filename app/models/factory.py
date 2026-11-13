"""Factory model for Machine Capacity Management: where work happens and what it can do.

Capacity is never stored; it is calculated from these records (see app/services/capacity.py)
so every planning number can be traced back to a machine rating, an efficiency and a shift.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.models import Owned, now
from app.models.master import identity, tenant_fk

# Departments of a vertically integrated knitwear factory, in process order.
DEPARTMENTS = (
    "knitting",
    "dyeing",
    "finishing",
    "relaxation",
    "cutting",
    "embellishment",
    "sewing",
    "washing",
    "packing",
)
# How a machine class expresses capacity. Each basis has its own formula.
CAPACITY_BASES = ("knit", "batch", "continuous", "rate", "sewing")
MACHINE_STATUSES = ("active", "idle", "maintenance", "decommissioned")
CALENDAR_KINDS = ("holiday", "shutdown", "short_day", "overtime")


def _in(field, values):
    return CheckConstraint(f"{field} IN ({', '.join(repr(value) for value in values)})", name=field)


class ShiftPattern(Owned, db.Model):
    """How many hours a work centre can run on a normal working day."""

    __tablename__ = "shift_patterns"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    shifts_per_day: Mapped[int] = mapped_column()
    hours_per_shift: Mapped[Decimal] = mapped_column(db.Numeric(4, 2))
    break_minutes_per_shift: Mapped[int] = mapped_column(default=0, server_default="0")
    # Seven characters, Monday first: "1111110" works Monday to Saturday.
    working_days: Mapped[str] = mapped_column(
        db.String(7), default="1111110", server_default="1111110"
    )
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        CheckConstraint("shifts_per_day BETWEEN 1 AND 3", name="shifts_per_day"),
        CheckConstraint("hours_per_shift > 0 AND hours_per_shift <= 12", name="hours_per_shift"),
        CheckConstraint(
            "break_minutes_per_shift >= 0 AND break_minutes_per_shift < hours_per_shift * 60",
            name="break_minutes",
        ),
        CheckConstraint("working_days ~ '^[01]{7}$'", name="working_days"),
    )


class WorkCenter(Owned, db.Model):
    """A department at one site, such as the dye house at Manga or sewing line 4 at QIE-2."""

    __tablename__ = "work_centers"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    department: Mapped[str] = mapped_column(db.String(20))
    site_id: Mapped[uuid.UUID] = mapped_column()
    shift_pattern_id: Mapped[uuid.UUID] = mapped_column()
    # Planned share of rated output actually achieved, in percent (e.g. 75.00).
    target_efficiency: Mapped[Decimal] = mapped_column(
        db.Numeric(5, 2), default=Decimal("75"), server_default="75"
    )
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        tenant_fk("site_id", "sites"),
        tenant_fk("shift_pattern_id", "shift_patterns"),
        _in("department", DEPARTMENTS),
        CheckConstraint(
            "target_efficiency > 0 AND target_efficiency <= 100", name="target_efficiency"
        ),
    )


class MachineClass(Owned, db.Model):
    """A kind of machine and the formula used for its capacity.

    knit:       rated value is cylinder RPM; output uses feeders and a reference fabric.
    batch:      rated value is kg per batch; output uses fill factor and cycle + setup hours.
    continuous: rated value is metres per minute (stenter, compactor).
    rate:       rated value is units per hour (cut panels, print impressions, embroidered pieces).
    sewing:     one operator station; capacity is earned standard minutes.
    """

    __tablename__ = "machine_classes"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    department: Mapped[str] = mapped_column(db.String(20))
    capacity_basis: Mapped[str] = mapped_column(db.String(20))
    output_unit: Mapped[str] = mapped_column(db.String(20))
    # Knitting reference fabric, used until a style supplies its own fabric spec.
    feeders_per_course: Mapped[int | None] = mapped_column()
    courses_per_cm: Mapped[Decimal | None] = mapped_column(db.Numeric(6, 2))
    fabric_width_m: Mapped[Decimal | None] = mapped_column(db.Numeric(5, 2))
    fabric_gsm: Mapped[Decimal | None] = mapped_column(db.Numeric(6, 1))
    # Batch processing defaults.
    fill_factor: Mapped[Decimal | None] = mapped_column(db.Numeric(4, 3))
    cycle_hours: Mapped[Decimal | None] = mapped_column(db.Numeric(5, 2))
    setup_hours: Mapped[Decimal | None] = mapped_column(db.Numeric(5, 2))
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        _in("department", DEPARTMENTS),
        _in("capacity_basis", CAPACITY_BASES),
        CheckConstraint(
            "capacity_basis <> 'knit' OR (feeders_per_course > 0 AND courses_per_cm > 0 "
            "AND fabric_width_m > 0 AND fabric_gsm > 0)",
            name="knit_reference",
        ),
        CheckConstraint(
            "capacity_basis <> 'batch' OR (fill_factor > 0 AND fill_factor <= 1 "
            "AND cycle_hours > 0 AND setup_hours >= 0)",
            name="batch_reference",
        ),
    )


class Machine(Owned, db.Model):
    """One physical asset with its rating; status changes are recorded as events."""

    __tablename__ = "machines"
    asset_tag: Mapped[str] = mapped_column(db.String(40))
    make_model: Mapped[str] = mapped_column(db.String(120))
    machine_class_id: Mapped[uuid.UUID] = mapped_column()
    work_center_id: Mapped[uuid.UUID] = mapped_column()
    rated_value: Mapped[Decimal] = mapped_column(db.Numeric(12, 3))
    # Knitting frames only.
    feeders: Mapped[int | None] = mapped_column()
    gauge: Mapped[int | None] = mapped_column()
    diameter_in: Mapped[Decimal | None] = mapped_column(db.Numeric(5, 1))
    # Optional machine efficiency in percent; the work centre target applies when empty.
    efficiency: Mapped[Decimal | None] = mapped_column(db.Numeric(5, 2))
    status: Mapped[str] = mapped_column(db.String(20), default="active", server_default="active")
    commissioned_on: Mapped[date | None] = mapped_column(db.Date)
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("asset_tag"),
        tenant_fk("machine_class_id", "machine_classes"),
        tenant_fk("work_center_id", "work_centers"),
        _in("status", MACHINE_STATUSES),
        CheckConstraint("rated_value > 0", name="rated_value"),
        CheckConstraint("feeders IS NULL OR feeders > 0", name="feeders"),
        CheckConstraint("gauge IS NULL OR gauge BETWEEN 3 AND 60", name="gauge"),
        CheckConstraint(
            "efficiency IS NULL OR (efficiency > 0 AND efficiency <= 100)", name="efficiency"
        ),
    )


class MachineStatusEvent(Owned, db.Model):
    """Append-only record of every machine status change (immutable in the database)."""

    __tablename__ = "machine_status_events"
    machine_id: Mapped[uuid.UUID] = mapped_column()
    from_status: Mapped[str | None] = mapped_column(db.String(20))
    to_status: Mapped[str] = mapped_column(db.String(20))
    reason: Mapped[str] = mapped_column(db.String(500))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("machine_id", "machines"),
        tenant_fk("actor_id", "memberships"),
        _in("to_status", MACHINE_STATUSES),
    )


class CalendarException(Owned, db.Model):
    """A day at one site that differs from the shift pattern: holiday, shutdown or overtime."""

    __tablename__ = "calendar_exceptions"
    site_id: Mapped[uuid.UUID] = mapped_column()
    day: Mapped[date] = mapped_column(db.Date)
    kind: Mapped[str] = mapped_column(db.String(20))
    # Hours each shift can run that day (0 for a holiday).
    hours_per_shift: Mapped[Decimal] = mapped_column(db.Numeric(4, 2))
    note: Mapped[str] = mapped_column(db.String(200))
    __table_args__ = (
        *identity("site_id", "day"),
        tenant_fk("site_id", "sites"),
        _in("kind", CALENDAR_KINDS),
        CheckConstraint("hours_per_shift >= 0 AND hours_per_shift <= 12", name="hours_per_shift"),
    )


class SiteTransitTime(Owned, db.Model):
    """Hours to move material from one site to another, used by the scheduler."""

    __tablename__ = "site_transit_times"
    from_site_id: Mapped[uuid.UUID] = mapped_column()
    to_site_id: Mapped[uuid.UUID] = mapped_column()
    hours: Mapped[Decimal] = mapped_column(db.Numeric(5, 2))
    note: Mapped[str | None] = mapped_column(db.String(200))
    __table_args__ = (
        *identity("from_site_id", "to_site_id"),
        tenant_fk("from_site_id", "sites"),
        tenant_fk("to_site_id", "sites"),
        CheckConstraint("from_site_id <> to_site_id", name="different_sites"),
        CheckConstraint("hours >= 0 AND hours <= 240", name="hours"),
    )


# ---------- Step 2: styles and work content ----------

PRODUCT_TYPES = (
    "tee",
    "polo",
    "tank",
    "long_sleeve",
    "hoodie",
    "sweatshirt",
    "jogger",
    "shorts",
    "leggings",
    "other",
)
FABRIC_TYPES = ("single_jersey", "interlock", "pique", "rib", "fleece", "french_terry", "other")
STYLE_STATUSES = ("active", "archived")
BULLETIN_STATUSES = ("draft", "published")


class Style(Owned, db.Model):
    """A buyer's garment style: the unit that orders, fabric and work content refer to."""

    __tablename__ = "styles"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(160))
    product_type: Mapped[str] = mapped_column(db.String(20))
    season: Mapped[str | None] = mapped_column(db.String(20))
    buyer_id: Mapped[uuid.UUID | None] = mapped_column()
    item_id: Mapped[uuid.UUID | None] = mapped_column()
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        tenant_fk("buyer_id", "partners"),
        tenant_fk("item_id", "items"),
        _in("product_type", PRODUCT_TYPES),
    )


class FabricSpec(Owned, db.Model):
    """One fabric used by a style (body, rib or trim) and how much a garment consumes."""

    __tablename__ = "fabric_specs"
    style_id: Mapped[uuid.UUID] = mapped_column()
    component: Mapped[str] = mapped_column(db.String(40))
    fabric_type: Mapped[str] = mapped_column(db.String(20))
    composition: Mapped[str] = mapped_column(db.String(120))
    gsm: Mapped[Decimal] = mapped_column(db.Numeric(6, 1))
    width_m: Mapped[Decimal] = mapped_column(db.Numeric(5, 2))
    courses_per_cm: Mapped[Decimal | None] = mapped_column(db.Numeric(6, 2))
    # Finished fabric per garment including cutting waste, in kilograms.
    consumption_kg: Mapped[Decimal] = mapped_column(db.Numeric(8, 4))
    # Hours the rolls must rest flat after finishing before they may be cut.
    relaxation_hours: Mapped[int] = mapped_column(default=24, server_default="24")
    __table_args__ = (
        *identity("style_id", "component"),
        tenant_fk("style_id", "styles"),
        _in("fabric_type", FABRIC_TYPES),
        CheckConstraint("gsm > 0", name="gsm"),
        CheckConstraint("width_m > 0", name="width_m"),
        CheckConstraint("courses_per_cm IS NULL OR courses_per_cm > 0", name="courses_per_cm"),
        CheckConstraint("consumption_kg > 0", name="consumption_kg"),
        CheckConstraint("relaxation_hours BETWEEN 0 AND 168", name="relaxation_hours"),
    )


class OperationBulletin(Owned, db.Model):
    """A revision of a style's operation breakdown. Published revisions are frozen."""

    __tablename__ = "operation_bulletins"
    style_id: Mapped[uuid.UUID] = mapped_column()
    revision: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    # Default allowance for new operations (0.250 means 25%).
    allowance_factor: Mapped[Decimal] = mapped_column(
        db.Numeric(4, 3), default=Decimal("0.250"), server_default="0.250"
    )
    source: Mapped[str] = mapped_column(db.String(120), default="Manual", server_default="Manual")
    published_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("style_id", "revision"),
        tenant_fk("style_id", "styles"),
        _in("status", BULLETIN_STATUSES),
        CheckConstraint("revision > 0", name="revision"),
        CheckConstraint("allowance_factor >= 0 AND allowance_factor <= 1", name="allowance"),
        CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="published_at"),
    )


class BulletinOperation(Owned, db.Model):
    """One sewing or manual operation: SAM = basic minutes × (1 + allowance)."""

    __tablename__ = "bulletin_operations"
    bulletin_id: Mapped[uuid.UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column()
    name: Mapped[str] = mapped_column(db.String(120))
    # Empty for manual work (trimming, folding, inspection by hand).
    machine_class_id: Mapped[uuid.UUID | None] = mapped_column()
    basic_minutes: Mapped[Decimal] = mapped_column(db.Numeric(8, 4))
    allowance_factor: Mapped[Decimal] = mapped_column(db.Numeric(4, 3))
    sam: Mapped[Decimal] = mapped_column(db.Numeric(8, 4))
    __table_args__ = (
        *identity("bulletin_id", "sequence"),
        tenant_fk("bulletin_id", "operation_bulletins"),
        tenant_fk("machine_class_id", "machine_classes"),
        CheckConstraint("sequence > 0", name="sequence"),
        CheckConstraint("basic_minutes > 0 AND basic_minutes <= 120", name="basic_minutes"),
        CheckConstraint("allowance_factor >= 0 AND allowance_factor <= 1", name="allowance"),
        CheckConstraint(
            "sam = round(basic_minutes * (1 + allowance_factor), 4)", name="sam_formula"
        ),
    )


# ---------- Step 3: production orders and capacity bookings ----------

ORDER_STATUSES = ("draft", "planned", "released", "completed", "cancelled")
STAGES = ("knitting", "dyeing", "finishing", "cutting", "embellishment", "sewing", "packing")


class ProductionOrder(Owned, db.Model):
    """A quantity of one style to make by an ex-factory date, planned stage by stage."""

    __tablename__ = "production_orders"
    reference: Mapped[str] = mapped_column(db.String(40))
    style_id: Mapped[uuid.UUID] = mapped_column()
    # The published bulletin whose SAM this order is planned with (frozen).
    bulletin_id: Mapped[uuid.UUID] = mapped_column()
    quantity: Mapped[int] = mapped_column()
    colour: Mapped[str] = mapped_column(db.String(60))
    ex_factory_on: Mapped[date] = mapped_column(db.Date)
    # 1 is most urgent; orders are scheduled by priority, then ex-factory date.
    priority: Mapped[int] = mapped_column(default=3, server_default="3")
    sewing_lines: Mapped[int] = mapped_column(default=2, server_default="2")
    prints_per_piece: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    planned_start_on: Mapped[date | None] = mapped_column(db.Date)
    planned_finish_on: Mapped[date | None] = mapped_column(db.Date)
    planned_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("reference"),
        tenant_fk("style_id", "styles"),
        tenant_fk("bulletin_id", "operation_bulletins"),
        _in("status", ORDER_STATUSES),
        CheckConstraint("quantity BETWEEN 1 AND 10000000", name="quantity"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority"),
        CheckConstraint("sewing_lines BETWEEN 1 AND 20", name="sewing_lines"),
        CheckConstraint("prints_per_piece BETWEEN 0 AND 10", name="prints_per_piece"),
        CheckConstraint(
            "planned_finish_on IS NULL OR planned_start_on <= planned_finish_on",
            name="planned_dates",
        ),
    )


class CapacityBooking(Owned, db.Model):
    """One day of one stage of an order on one work centre: the finite-capacity ledger."""

    __tablename__ = "capacity_bookings"
    production_order_id: Mapped[uuid.UUID] = mapped_column()
    stage: Mapped[str] = mapped_column(db.String(20))
    work_center_id: Mapped[uuid.UUID] = mapped_column()
    day: Mapped[date] = mapped_column(db.Date)
    quantity: Mapped[Decimal] = mapped_column(db.Numeric(16, 3))
    unit: Mapped[str] = mapped_column(db.String(20))
    __table_args__ = (
        *identity("production_order_id", "stage", "work_center_id", "day"),
        tenant_fk("production_order_id", "production_orders"),
        tenant_fk("work_center_id", "work_centers"),
        _in("stage", STAGES),
        CheckConstraint("quantity > 0", name="quantity"),
        db.Index("ix_capacity_bookings_center_day", "organization_id", "work_center_id", "day"),
    )
