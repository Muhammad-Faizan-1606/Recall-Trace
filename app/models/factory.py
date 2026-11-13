"""Factory model for Machine Capacity Management: where work happens and what it can do.

Capacity is never stored; it is calculated from these records (see app/services/capacity.py)
so every planning number can be traced back to a machine rating, an efficiency and a shift.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint
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


# ---------- Step 4: line balancing ----------

BALANCE_STATUSES = ("draft", "published")


class LineBalance(Owned, db.Model):
    """How one style's published bulletin is laid out on one sewing line.

    Drafts are edited freely; published revisions are frozen by the draft guards. The
    latest published revision of a line is what the line is running now.
    """

    __tablename__ = "line_balances"
    work_center_id: Mapped[uuid.UUID] = mapped_column()
    bulletin_id: Mapped[uuid.UUID] = mapped_column()
    revision: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(db.String(20), default="draft", server_default="draft")
    # Planned efficiency for this style on this line, in percent.
    target_efficiency: Mapped[Decimal] = mapped_column(db.Numeric(5, 2))
    note: Mapped[str | None] = mapped_column(db.String(200))
    published_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("work_center_id", "revision"),
        tenant_fk("work_center_id", "work_centers"),
        tenant_fk("bulletin_id", "operation_bulletins"),
        _in("status", BALANCE_STATUSES),
        CheckConstraint("revision > 0", name="revision"),
        CheckConstraint(
            "target_efficiency > 0 AND target_efficiency <= 100", name="target_efficiency"
        ),
        CheckConstraint("(status = 'published') = (published_at IS NOT NULL)", name="published_at"),
    )


class LineStation(Owned, db.Model):
    """One operator's workplace on the line, optionally tied to a physical machine."""

    __tablename__ = "line_stations"
    balance_id: Mapped[uuid.UUID] = mapped_column()
    number: Mapped[int] = mapped_column()
    machine_id: Mapped[uuid.UUID | None] = mapped_column()
    __table_args__ = (
        *identity("balance_id", "number"),
        # Lets assignments prove they belong to a station of the same balance.
        UniqueConstraint("organization_id", "balance_id", "id"),
        # A machine serves at most one station of a balance (empty for manual stations).
        UniqueConstraint("organization_id", "balance_id", "machine_id"),
        tenant_fk("balance_id", "line_balances"),
        tenant_fk("machine_id", "machines"),
        CheckConstraint("number BETWEEN 1 AND 200", name="number"),
    )


class StationOperation(Owned, db.Model):
    """A share of one bulletin operation done at one station (1 = all of it)."""

    __tablename__ = "station_operations"
    balance_id: Mapped[uuid.UUID] = mapped_column()
    station_id: Mapped[uuid.UUID] = mapped_column()
    bulletin_operation_id: Mapped[uuid.UUID] = mapped_column()
    share: Mapped[Decimal] = mapped_column(db.Numeric(5, 4))
    __table_args__ = (
        *identity("station_id", "bulletin_operation_id"),
        tenant_fk("balance_id", "line_balances"),
        ForeignKeyConstraint(
            ["organization_id", "balance_id", "station_id"],
            ["line_stations.organization_id", "line_stations.balance_id", "line_stations.id"],
        ),
        tenant_fk("bulletin_operation_id", "bulletin_operations"),
        CheckConstraint("share > 0 AND share <= 1", name="share"),
    )


# ---------- Step 5: shop floor execution ----------

DOWNTIME_CATEGORIES = (
    "breakdown",
    "power",
    "no_feeding",
    "changeover",
    "needle_bobbin",
    "quality",
    "meeting",
    "other",
)
# off_standard: approved lost time, left out of the efficiency denominator.
# operator: time the line still answers for, so it lowers achieved efficiency.
EFFICIENCY_RULES = ("off_standard", "operator")
ROLL_GRADES = ("A", "B", "C")
DYE_STATUSES = ("loaded", "dyeing", "passed", "re_dye", "rejected")
BUNDLE_STATUSES = ("cut", "issued", "sewn")


class DowntimeReason(Owned, db.Model):
    """Why a line or machine stopped, and whether that time counts against the line."""

    __tablename__ = "downtime_reasons"
    code: Mapped[str] = mapped_column(db.String(40))
    name: Mapped[str] = mapped_column(db.String(120))
    category: Mapped[str] = mapped_column(db.String(20))
    efficiency_rule: Mapped[str] = mapped_column(db.String(20))
    archived_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("code"),
        _in("category", DOWNTIME_CATEGORIES),
        _in("efficiency_rule", EFFICIENCY_RULES),
    )


class OutputLog(Owned, db.Model):
    """One hour of one sewing line: good pieces, rejects and the people who made them.

    Append-only (immutable in the database). A correction is a new row that restates the
    whole hour and points at the original; the newest row for an hour is the one that counts.
    """

    __tablename__ = "output_logs"
    work_center_id: Mapped[uuid.UUID] = mapped_column()
    production_order_id: Mapped[uuid.UUID] = mapped_column()
    day: Mapped[date] = mapped_column(db.Date)
    hour: Mapped[int] = mapped_column()  # 1 = first hour of the production day
    good_pieces: Mapped[int] = mapped_column()
    rejects: Mapped[int] = mapped_column()
    operators: Mapped[int] = mapped_column()
    minutes: Mapped[int] = mapped_column(default=60, server_default="60")
    # The garment SAM the pieces earn, copied from the order's bulletin when recorded.
    sam: Mapped[Decimal] = mapped_column(db.Numeric(8, 4))
    corrects_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(db.String(200))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column()
    recorded_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("work_center_id", "work_centers"),
        tenant_fk("production_order_id", "production_orders"),
        tenant_fk("corrects_id", "output_logs"),
        tenant_fk("recorded_by_id", "memberships"),
        CheckConstraint("hour BETWEEN 1 AND 24", name="hour"),
        CheckConstraint("good_pieces BETWEEN 0 AND 100000", name="good_pieces"),
        CheckConstraint("rejects BETWEEN 0 AND 100000", name="rejects"),
        CheckConstraint("operators BETWEEN 0 AND 500", name="operators"),
        CheckConstraint("minutes BETWEEN 0 AND 60", name="minutes"),
        CheckConstraint("sam > 0", name="sam"),
        db.Index(
            "uq_output_logs_original_hour",
            "organization_id",
            "work_center_id",
            "day",
            "hour",
            unique=True,
            postgresql_where=db.text("corrects_id IS NULL"),
        ),
        db.Index("ix_output_logs_center_day", "organization_id", "work_center_id", "day"),
    )


class DowntimeEvent(Owned, db.Model):
    """Lost minutes on a line (or one machine of it), with a reason. Append-only like output."""

    __tablename__ = "downtime_events"
    work_center_id: Mapped[uuid.UUID] = mapped_column()
    machine_id: Mapped[uuid.UUID | None] = mapped_column()
    reason_id: Mapped[uuid.UUID] = mapped_column()
    day: Mapped[date] = mapped_column(db.Date)
    hour: Mapped[int] = mapped_column()
    minutes: Mapped[int] = mapped_column()
    # People idled by the stop: 1 for one machine, the whole line for a power cut.
    operators_affected: Mapped[int] = mapped_column()
    corrects_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(db.String(200))
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column()
    recorded_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("work_center_id", "work_centers"),
        tenant_fk("machine_id", "machines"),
        tenant_fk("reason_id", "downtime_reasons"),
        tenant_fk("corrects_id", "downtime_events"),
        tenant_fk("recorded_by_id", "memberships"),
        CheckConstraint("hour BETWEEN 1 AND 24", name="hour"),
        CheckConstraint("minutes BETWEEN 0 AND 1440", name="minutes"),
        CheckConstraint("operators_affected BETWEEN 0 AND 500", name="operators_affected"),
        db.Index("ix_downtime_events_center_day", "organization_id", "work_center_id", "day"),
    )


class DyeBatch(Owned, db.Model):
    """One load of a dyeing vessel: which rolls, which colour and recipe, and the result."""

    __tablename__ = "dye_batches"
    batch_number: Mapped[str] = mapped_column(db.String(40))
    machine_id: Mapped[uuid.UUID] = mapped_column()
    production_order_id: Mapped[uuid.UUID | None] = mapped_column()
    colour: Mapped[str] = mapped_column(db.String(60))
    recipe_reference: Mapped[str] = mapped_column(db.String(60))
    status: Mapped[str] = mapped_column(db.String(20), default="loaded", server_default="loaded")
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(db.String(200))
    __table_args__ = (
        *identity("batch_number"),
        tenant_fk("machine_id", "machines"),
        tenant_fk("production_order_id", "production_orders"),
        _in("status", DYE_STATUSES),
        CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name="batch_times",
        ),
        CheckConstraint(
            "(status IN ('passed', 're_dye', 'rejected')) = (finished_at IS NOT NULL)",
            name="finished_status",
        ),
    )


class KnitRoll(Owned, db.Model):
    """One greige roll off a knitting machine; loaded into a dye batch later."""

    __tablename__ = "knit_rolls"
    roll_number: Mapped[str] = mapped_column(db.String(40))
    machine_id: Mapped[uuid.UUID] = mapped_column()
    production_order_id: Mapped[uuid.UUID | None] = mapped_column()
    knitted_on: Mapped[date] = mapped_column(db.Date)
    kg: Mapped[Decimal] = mapped_column(db.Numeric(8, 3))
    grade: Mapped[str] = mapped_column(db.String(1), default="A", server_default="A")
    dye_batch_id: Mapped[uuid.UUID | None] = mapped_column()
    __table_args__ = (
        *identity("roll_number"),
        tenant_fk("machine_id", "machines"),
        tenant_fk("production_order_id", "production_orders"),
        tenant_fk("dye_batch_id", "dye_batches"),
        _in("grade", ROLL_GRADES),
        CheckConstraint("kg > 0 AND kg <= 100", name="kg"),
    )


class CutBundle(Owned, db.Model):
    """A tied bundle of cut panels for one size, with a QR ticket that travels with it."""

    __tablename__ = "cut_bundles"
    bundle_number: Mapped[str] = mapped_column(db.String(40))
    production_order_id: Mapped[uuid.UUID] = mapped_column()
    dye_batch_id: Mapped[uuid.UUID | None] = mapped_column()
    lay_number: Mapped[str] = mapped_column(db.String(40))
    size: Mapped[str] = mapped_column(db.String(10))
    pieces: Mapped[int] = mapped_column()
    status: Mapped[str] = mapped_column(db.String(20), default="cut", server_default="cut")
    issued_line_id: Mapped[uuid.UUID | None] = mapped_column()
    issued_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    sewn_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    __table_args__ = (
        *identity("bundle_number"),
        tenant_fk("production_order_id", "production_orders"),
        tenant_fk("dye_batch_id", "dye_batches"),
        tenant_fk("issued_line_id", "work_centers"),
        _in("status", BUNDLE_STATUSES),
        CheckConstraint("pieces BETWEEN 1 AND 500", name="pieces"),
        CheckConstraint(
            "(status = 'cut') = (issued_line_id IS NULL AND issued_at IS NULL)", name="issued"
        ),
        CheckConstraint("(status = 'sewn') = (sewn_at IS NOT NULL)", name="sewn"),
        db.Index("ix_cut_bundles_order", "organization_id", "production_order_id"),
    )


# ---------- Step 6: alerts ----------

ALERT_KINDS = (
    "efficiency_low",
    "efficiency_high",
    "machine_down",
    "order_late",
    "line_starving",
    "relaxation_breach",
)
ALERT_SEVERITIES = ("info", "warning", "critical")
ALERT_STATUSES = ("open", "acknowledged", "resolved")


class FactoryAlert(Owned, db.Model):
    """A condition the factory checks found, and what people did about it.

    The checks raise one alert per condition (`dedupe_key`) while it is unresolved, refresh
    `last_seen_at` each time they still see it, and set `cleared_at` when it goes away. A
    person acknowledges it, may assign an owner, and resolves it with a note.
    """

    __tablename__ = "factory_alerts"
    kind: Mapped[str] = mapped_column(db.String(30))
    severity: Mapped[str] = mapped_column(db.String(10))
    dedupe_key: Mapped[str] = mapped_column(db.String(160))
    title: Mapped[str] = mapped_column(db.String(160))
    detail: Mapped[str] = mapped_column(db.String(400))
    work_center_id: Mapped[uuid.UUID | None] = mapped_column()
    machine_id: Mapped[uuid.UUID | None] = mapped_column()
    production_order_id: Mapped[uuid.UUID | None] = mapped_column()
    dye_batch_id: Mapped[uuid.UUID | None] = mapped_column()
    status: Mapped[str] = mapped_column(db.String(20), default="open", server_default="open")
    first_seen_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    last_seen_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=now)
    cleared_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    owner_id: Mapped[uuid.UUID | None] = mapped_column()
    acknowledged_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column()
    resolved_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column()
    resolution_note: Mapped[str | None] = mapped_column(db.String(400))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        tenant_fk("work_center_id", "work_centers"),
        tenant_fk("machine_id", "machines"),
        tenant_fk("production_order_id", "production_orders"),
        tenant_fk("dye_batch_id", "dye_batches"),
        tenant_fk("owner_id", "memberships"),
        tenant_fk("acknowledged_by_id", "memberships"),
        tenant_fk("resolved_by_id", "memberships"),
        _in("kind", ALERT_KINDS),
        _in("severity", ALERT_SEVERITIES),
        _in("status", ALERT_STATUSES),
        CheckConstraint(
            "(status = 'resolved') = (resolved_at IS NOT NULL AND resolution_note IS NOT NULL)",
            name="resolution",
        ),
        CheckConstraint(
            "status <> 'acknowledged' OR acknowledged_at IS NOT NULL", name="acknowledgement"
        ),
        CheckConstraint("last_seen_at >= first_seen_at", name="seen_order"),
        db.Index(
            "uq_factory_alerts_unresolved",
            "organization_id",
            "dedupe_key",
            unique=True,
            postgresql_where=db.text("status <> 'resolved'"),
        ),
        db.Index("ix_factory_alerts_status", "organization_id", "status"),
    )
