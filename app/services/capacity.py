"""Deterministic machine and work-centre capacity (Machine Capacity Management).

Every result carries the formula and the inputs that produced it, so a planner, an
auditor or a viva examiner can check the arithmetic by hand. Nothing here writes to
the database; capacity is always derived from the current machine register.

Formulas (from the owner's MCM blueprint, section 5):

knit        metres/hour = RPM × feeders × η × 60 ÷ (feeders per course × courses/cm × 100)
            kg/hour     = metres/hour × fabric width (m) × GSM ÷ 1000
batch       kg/hour     = batch kg × fill factor ÷ (cycle hours + setup hours) × η
continuous  metres/hour = metres/minute × 60 × η
rate        units/hour  = rated units/hour × η
sewing      standard minutes/hour = 60 × η   (one operator station)

η is the machine's own efficiency when recorded, otherwise its work centre's target.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

AVAILABLE_STATUSES = ("active", "idle")
UNITS = {"knit": "kg", "batch": "kg", "continuous": "m", "sewing": "SAM min"}
HUNDRED = Decimal(100)


def q(value, places="0.1"):
    """Round half-up for display without losing the Decimal type."""
    return Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)


@dataclass
class Rate:
    per_hour: Decimal
    unit: str
    efficiency: Decimal
    steps: list = field(default_factory=list)
    problem: str | None = None

    @property
    def explanation(self):
        return " ; ".join(self.steps)


def unit_for(machine_class):
    if machine_class.capacity_basis == "rate":
        return machine_class.output_unit or "units"
    return UNITS[machine_class.capacity_basis]


def efficiency_for(machine, work_center):
    percent = (
        machine.efficiency if machine.efficiency is not None else work_center.target_efficiency
    )
    return Decimal(percent) / HUNDRED


def machine_rate(machine, machine_class, work_center):
    """Hourly output of one machine at planned efficiency, with its working."""
    eta = efficiency_for(machine, work_center)
    rated = Decimal(machine.rated_value)
    basis = machine_class.capacity_basis
    unit = unit_for(machine_class)
    pct = f"{q(eta * HUNDRED, '0.1')}%"
    if basis == "knit":
        if not machine.feeders:
            return Rate(Decimal(0), unit, eta, problem="Record the number of feeders.")
        denominator = (
            Decimal(machine_class.feeders_per_course) * Decimal(machine_class.courses_per_cm) * 100
        )
        metres = rated * machine.feeders * eta * 60 / denominator
        kg = (
            metres
            * Decimal(machine_class.fabric_width_m)
            * Decimal(machine_class.fabric_gsm)
            / 1000
        )
        return Rate(
            kg,
            unit,
            eta,
            [
                f"{q(rated, '0.1')} RPM × {machine.feeders} feeders × {pct} × 60 ÷ "
                f"({machine_class.feeders_per_course} feeder/course × "
                f"{q(machine_class.courses_per_cm, '0.1')} courses/cm × 100) = {q(metres)} m/h",
                f"{q(metres)} m/h × {q(machine_class.fabric_width_m, '0.01')} m × "
                f"{q(machine_class.fabric_gsm, '1')} g/m² ÷ 1000 = {q(kg)} kg/h",
            ],
        )
    if basis == "batch":
        cycle = Decimal(machine_class.cycle_hours) + Decimal(machine_class.setup_hours)
        kg = rated * Decimal(machine_class.fill_factor) / cycle * eta
        return Rate(
            kg,
            unit,
            eta,
            [
                f"{q(rated, '1')} kg × {q(machine_class.fill_factor, '0.01')} fill ÷ "
                f"({q(machine_class.cycle_hours, '0.1')} h cycle + "
                f"{q(machine_class.setup_hours, '0.1')} h setup) × {pct} = {q(kg)} kg/h",
            ],
        )
    if basis == "continuous":
        metres = rated * 60 * eta
        return Rate(metres, unit, eta, [f"{q(rated, '0.1')} m/min × 60 × {pct} = {q(metres)} m/h"])
    if basis == "rate":
        units = rated * eta
        return Rate(
            units, unit, eta, [f"{q(rated, '0.1')} {unit}/h rated × {pct} = {q(units)} {unit}/h"]
        )
    minutes = 60 * eta
    return Rate(
        minutes,
        unit,
        eta,
        [f"60 min × {pct} = {q(minutes)} standard minutes earned per hour"],
    )


def shift_hours(pattern, day, exceptions):
    """Productive hours for one work centre on one day, and why."""
    exception = exceptions.get(day)
    if exception is not None:
        per_shift = Decimal(exception.hours_per_shift)
        reason = f"{exception.kind.replace('_', ' ')}: {exception.note}"
    elif pattern.working_days[day.weekday()] == "1":
        per_shift = Decimal(pattern.hours_per_shift)
        reason = "normal day"
    else:
        return Decimal(0), "weekly day off"
    if per_shift <= 0:
        return Decimal(0), reason
    productive = per_shift - Decimal(pattern.break_minutes_per_shift) / 60
    return max(productive, Decimal(0)) * pattern.shifts_per_day, reason


@dataclass
class CenterCapacity:
    available: int = 0
    total: int = 0
    per_hour: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def per_day(self, hours):
        return {unit: value * hours for unit, value in self.per_hour.items()}


def center_capacity(work_center, machines):
    """Combine the hourly rates of available machines, grouped by output unit.

    `machines` is a list of (machine, machine_class) pairs for this work centre.
    """
    result = CenterCapacity(total=len(machines))
    for machine, machine_class in machines:
        if machine.archived_at is not None or machine.status not in AVAILABLE_STATUSES:
            continue
        result.available += 1
        rate = machine_rate(machine, machine_class, work_center)
        if rate.problem:
            result.problems.append(f"{machine.asset_tag}: {rate.problem}")
            continue
        result.per_hour[rate.unit] = result.per_hour.get(rate.unit, Decimal(0)) + rate.per_hour
    return result


def calendar(pattern, start, days, exceptions):
    """[(day, productive hours, reason)] for a run of days."""
    return [
        (day, *shift_hours(pattern, day, exceptions))
        for day in (start + timedelta(days=offset) for offset in range(days))
    ]


def week_start(today: date):
    return today - timedelta(days=today.weekday())
