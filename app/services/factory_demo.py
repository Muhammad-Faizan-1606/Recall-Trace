"""Fictional "Lahore Knit Mills (demo)" factory for the Factory Suite demonstration.

The layout resembles a large vertically integrated Lahore knitwear exporter (knitting at
Kot Lakhpat, wet processing at Manga, cutting and embellishment at an apparel park, and
stitching units at Raiwind and Sundar), but the company, plots, machine counts and
figures are invented. Machine makes are typical industry equipment, not a claim about
any real factory.

The register is inserted in one transaction (about a thousand machines) with one
summary audit event. That is quicker over a remote database than one locked transaction
per row, and it is safe because the company is new and private to the seeding owner.
"""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models import Membership, MembershipRole, Organization, Role
from app.models.factory import (
    CalendarException,
    Machine,
    MachineClass,
    MachineStatusEvent,
    ShiftPattern,
    SiteTransitTime,
    WorkCenter,
)
from app.models.master import Site
from app.services.audit import record as audit

SLUG = "lahore-knit-mills-demo"
NAME = "Lahore Knit Mills (demo)"

SITES = [
    (
        "QIE1",
        "QIE Unit 1 — Kot Lakhpat (HQ)",
        "Fictional plot, Quaid-e-Azam Industrial Estate, Kot Lakhpat, Lahore",
    ),
    ("QIE2", "QIE Unit 2 — Kot Lakhpat", "Fictional plot, Quaid-e-Azam Industrial Estate, Lahore"),
    (
        "MANGA",
        "Manga wet-processing campus",
        "Fictional plot off Manga–Raiwind Road, District Kasur",
    ),
    (
        "PARK",
        "Apparel Park — Kasur",
        "Fictional plot off Manga–Raiwind Road, Tehsil Kot Radha Kishan",
    ),
    ("RWD", "Raiwind stitching unit", "Fictional plot, Manga–Raiwind Road, District Kasur"),
    ("SUN", "Sundar stitching unit", "Fictional plot, Sundar Industrial Estate, Lahore"),
]
PATTERNS = [
    ("CONT-3X8", "Continuous, three 8-hour shifts", 3, "8", 30, "1111111"),
    ("DAY-2X10", "Two 10-hour shifts, Monday to Saturday", 2, "10", 60, "1111110"),
    ("DAY-1X10", "One 10-hour shift, Monday to Saturday", 1, "10", 60, "1111110"),
]
D = Decimal
CLASSES = [
    # code, name, department, basis, unit, knit (fpc, c/cm, width, gsm), batch (fill, cycle, setup)
    (
        "KNIT-SJ",
        "Single jersey circular knitting",
        "knitting",
        "knit",
        None,
        (1, D("16"), D("1.80"), D("160")),
        None,
    ),
    (
        "KNIT-INT",
        "Interlock circular knitting",
        "knitting",
        "knit",
        None,
        (2, D("18"), D("1.70"), D("220")),
        None,
    ),
    (
        "KNIT-FLC",
        "Fleece circular knitting",
        "knitting",
        "knit",
        None,
        (3, D("14"), D("1.90"), D("300")),
        None,
    ),
    (
        "DYE-JET",
        "Soft-flow jet dyeing vessel",
        "dyeing",
        "batch",
        None,
        None,
        (D("0.90"), D("7.0"), D("1.0")),
    ),
    ("STENTER", "Stenter frame", "finishing", "continuous", None, None, None),
    ("COMPACT", "Open-width compactor", "finishing", "continuous", None, None, None),
    ("CUT-CNC", "Automatic spreading and CNC cutting", "cutting", "rate", "panels", None, None),
    ("PRINT-OVAL", "Oval screen printer", "embellishment", "rate", "impressions", None, None),
    ("EMB-12H", "12-head embroidery", "embellishment", "rate", "pieces", None, None),
    ("SEW-OL", "Overlock 4-thread station", "sewing", "sewing", None, None, None),
    ("SEW-FL", "Flatlock 5-thread station", "sewing", "sewing", None, None, None),
    ("SEW-LS", "Lockstitch station", "sewing", "sewing", None, None, None),
    (
        "WASH-TMB",
        "Garment washing tumbler",
        "washing",
        "batch",
        None,
        None,
        (D("0.85"), D("1.5"), D("0.5")),
    ),
    ("PACK", "Packing and needle-detection table", "packing", "rate", "pieces", None, None),
]
# Sewing lines per site, and stations per line by machine class.
LINES = {"QIE1": 6, "QIE2": 8, "PARK": 10, "RWD": 8, "SUN": 6}
LINE_MIX = (
    ("SEW-OL", "Juki MO-6814S", 11),
    ("SEW-FL", "Juki MF-7923", 8),
    ("SEW-LS", "Juki DDL-9000C", 9),
)
TRANSIT = [
    ("QIE1", "MANGA", "5", "Greige fabric to dyeing: loading, 40 km road, unloading"),
    ("MANGA", "PARK", "4", "Finished rolls to cutting"),
    ("MANGA", "QIE2", "6", "Finished rolls to QIE cutting bay"),
    ("PARK", "RWD", "3", "Cut and printed panels to stitching"),
    ("PARK", "SUN", "4", "Cut panels to Sundar lines"),
    ("RWD", "PARK", "3", "Return of garments for washing or packing"),
    ("QIE2", "RWD", "5", "Overflow bundles to Raiwind"),
]


def _owner_membership(organization, user):
    role = db.session.scalar(
        select(Role).where(Role.organization_id == organization.id, Role.code == "owner")
    )
    if role is None:
        role = Role(organization_id=organization.id, code="owner", name="Owner", protected=True)
        db.session.add(role)
        db.session.flush()
    member = db.session.scalar(
        select(Membership).where(
            Membership.organization_id == organization.id, Membership.user_id == user.id
        )
    )
    if member is None:
        member = Membership(organization_id=organization.id, user_id=user.id, status="active")
        db.session.add(member)
        db.session.flush()
    if not db.session.scalar(
        select(MembershipRole.id).where(
            MembershipRole.membership_id == member.id, MembershipRole.role_id == role.id
        )
    ):
        db.session.add(
            MembershipRole(
                organization_id=organization.id, membership_id=member.id, role_id=role.id
            )
        )
    db.session.flush()
    return member


def ensure_company(user):
    """The demo company with `user` as its owner; returns (organization, membership, created)."""
    organization = db.session.scalar(select(Organization).where(Organization.slug == SLUG))
    created = organization is None
    if created:
        organization = Organization(name=NAME, slug=SLUG)
        db.session.add(organization)
        db.session.flush()
    member = _owner_membership(organization, user)
    return organization, member, created


def seed(organization, member, today=None):
    """Insert the fictional factory once. Returns report lines; does nothing if present."""
    company_id = organization.id
    if db.session.scalar(select(WorkCenter.id).where(WorkCenter.organization_id == company_id)):
        return []
    today = today or date.today()
    add = db.session.add

    sites = {}
    for code, name, address in SITES:
        site = Site(
            organization_id=company_id,
            code=code,
            name=name,
            address_text=address,
            country_code="PK",
        )
        add(site)
        sites[code] = site
    patterns = {}
    for code, name, shifts, hours, breaks, days in PATTERNS:
        pattern = ShiftPattern(
            organization_id=company_id,
            code=code,
            name=name,
            shifts_per_day=shifts,
            hours_per_shift=D(hours),
            break_minutes_per_shift=breaks,
            working_days=days,
        )
        add(pattern)
        patterns[code] = pattern
    classes = {}
    for code, name, department, basis, unit, knit, batch in CLASSES:
        row = MachineClass(
            organization_id=company_id,
            code=code,
            name=name,
            department=department,
            capacity_basis=basis,
            output_unit=unit
            or {"knit": "kg", "batch": "kg", "continuous": "m"}.get(basis, "SAM min"),
        )
        if knit:
            (row.feeders_per_course, row.courses_per_cm, row.fabric_width_m, row.fabric_gsm) = knit
        if batch:
            row.fill_factor, row.cycle_hours, row.setup_hours = batch
        add(row)
        classes[code] = row
    db.session.flush()

    centers = []
    machines = []

    def center(code, name, department, site, pattern, target):
        row = WorkCenter(
            organization_id=company_id,
            code=code,
            name=name,
            department=department,
            site_id=sites[site].id,
            shift_pattern_id=patterns[pattern].id,
            target_efficiency=D(target),
        )
        add(row)
        centers.append(row)
        return row

    def machine(tag, make, class_code, work_center, rated, **extra):
        row = Machine(
            organization_id=company_id,
            asset_tag=tag,
            make_model=make,
            machine_class_id=classes[class_code].id,
            work_center_id=work_center.id,
            rated_value=D(str(rated)),
            **extra,
        )
        machines.append(row)
        return row

    knit = center("QIE1-KNIT", "Circular knitting hall", "knitting", "QIE1", "CONT-3X8", "85")
    dye = center("MANGA-DYE", "Dye house", "dyeing", "MANGA", "CONT-3X8", "80")
    fin = center("MANGA-FIN", "Stenter and compacting", "finishing", "MANGA", "CONT-3X8", "80")
    cut_park = center("PARK-CUT", "Automatic cutting room", "cutting", "PARK", "DAY-2X10", "75")
    cut_qie = center("QIE2-CUT", "QIE cutting bay", "cutting", "QIE2", "DAY-1X10", "75")
    prt = center("PARK-PRINT", "Screen printing", "embellishment", "PARK", "DAY-2X10", "70")
    emb = center("PARK-EMB", "Embroidery", "embellishment", "PARK", "DAY-2X10", "70")
    wash = center("RWD-WASH", "Garment washing", "washing", "RWD", "DAY-1X10", "75")
    pack = center("RWD-PACK", "Finishing and packing hub", "packing", "RWD", "DAY-1X10", "80")
    db.session.flush()

    for number in range(1, 25):
        machine(
            f"KNT-SJ-{number:02d}",
            "Mayer & Cie Relanit 3.2 II",
            "KNIT-SJ",
            knit,
            30,
            feeders=96,
            gauge=28,
            diameter_in=D("30"),
        )
    for number in range(1, 11):
        machine(
            f"KNT-IN-{number:02d}",
            "Terrot I3P 272",
            "KNIT-INT",
            knit,
            25,
            feeders=72,
            gauge=24,
            diameter_in=D("30"),
        )
    for number in range(1, 7):
        machine(
            f"KNT-FL-{number:02d}",
            "Mayer & Cie MCPE 2.4",
            "KNIT-FLC",
            knit,
            28,
            feeders=90,
            gauge=20,
            diameter_in=D("30"),
        )
    vessels = [250, 250, 500, 500, 500, 500] + [1000] * 6 + [1500] * 4
    for number, kg in enumerate(vessels, 1):
        make = "Thies iMaster H2O" if number % 2 else "Fong's ALLFIT"
        machine(f"DYE-JET-{number:02d}", make, "DYE-JET", dye, kg)
    for number, make in enumerate(
        ("Monforts Montex 6500", "Monforts Montex 6500", "Brückner Power-Frame"), 1
    ):
        machine(f"STN-{number:02d}", make, "STENTER", fin, 40)
    for number in range(1, 3):
        machine(f"CMP-{number:02d}", "Lafer open-width compactor", "COMPACT", fin, 30)
    for number in range(1, 4):
        machine(f"CUT-PK-{number:02d}", "Lectra Vector iX6 with spreader", "CUT-CNC", cut_park, 900)
    for number in range(1, 3):
        machine(f"CUT-QE-{number:02d}", "Lectra Vector iX6 with spreader", "CUT-CNC", cut_qie, 800)
    for number in range(1, 7):
        machine(f"PRT-{number:02d}", "M&R Gauntlet oval screen printer", "PRINT-OVAL", prt, 600)
    for number in range(1, 5):
        machine(f"EMB-{number:02d}", "Tajima TMAR-K1512C (12 heads)", "EMB-12H", emb, 120)
    for number in range(1, 5):
        machine(f"WSH-{number:02d}", "Stainless steel tumbler 100 kg", "WASH-TMB", wash, 100)
    for number in range(1, 13):
        machine(f"PCK-{number:02d}", "Packing table with needle detector", "PACK", pack, 180)

    for site, count in LINES.items():
        pattern = "DAY-2X10" if site in ("PARK", "QIE2") else "DAY-1X10"
        for line in range(1, count + 1):
            work_center = center(
                f"{site}-L{line:02d}", f"Sewing line {line}", "sewing", site, pattern, "70"
            )
            db.session.flush()
            station = 0
            for class_code, make, quantity in LINE_MIX:
                for _ in range(quantity):
                    station += 1
                    machine(f"{site}-L{line:02d}-S{station:02d}", make, class_code, work_center, 1)

    # A realistic floor: some machines are down or idle today.
    down = {
        "KNT-SJ-07": ("maintenance", "Needle bed replacement"),
        "KNT-IN-03": ("maintenance", "Yarn feeder motor fault"),
        "DYE-JET-09": ("maintenance", "Main circulation pump seal leaking"),
        "STN-03": ("idle", "No fabric released for heat setting"),
        "PARK-L04-S05": ("maintenance", "Looper timing"),
        "QIE2-L02-S14": ("maintenance", "Differential feed repair"),
        "RWD-L06-S20": ("maintenance", "Thread trimmer solenoid"),
    }
    for row in machines:
        if row.asset_tag in down:
            row.status = down[row.asset_tag][0]
        add(row)
    db.session.flush()
    for row in machines:
        add(
            MachineStatusEvent(
                organization_id=company_id,
                machine_id=row.id,
                from_status=None,
                to_status="active",
                reason="Registered",
                actor_id=member.id,
            )
        )
        if row.asset_tag in down:
            status, reason = down[row.asset_tag]
            add(
                MachineStatusEvent(
                    organization_id=company_id,
                    machine_id=row.id,
                    from_status="active",
                    to_status=status,
                    reason=reason,
                    actor_id=member.id,
                )
            )

    # Calendar relative to the seeding day so the next two weeks always show something.
    next_sunday = today + timedelta(days=(6 - today.weekday()) or 7)
    for site, day, kind, hours, note in [
        ("MANGA", next_sunday, "shutdown", "0", "Boiler annual inspection (fictional)"),
        ("PARK", today + timedelta(days=5), "short_day", "6", "Power line maintenance"),
        ("QIE1", today + timedelta(days=9), "overtime", "10", "Overtime for a late order"),
    ] + [
        (code, date(today.year, 12, 25), "holiday", "0", "Quaid-e-Azam Day")
        for code, _, _ in SITES
        if date(today.year, 12, 25) >= today
    ]:
        add(
            CalendarException(
                organization_id=company_id,
                site_id=sites[site].id,
                day=day,
                kind=kind,
                hours_per_shift=D(hours),
                note=note,
            )
        )
    for start, end, hours, note in TRANSIT:
        add(
            SiteTransitTime(
                organization_id=company_id,
                from_site_id=sites[start].id,
                to_site_id=sites[end].id,
                hours=D(hours),
                note=note,
            )
        )
    db.session.flush()
    audit(
        company_id, "factory.demo_seeded", "work_centers", centers[0].id, {"count": len(machines)}
    )
    return [
        f"{len(SITES)} sites, {len(centers)} work centres and {len(machines)} machines created "
        f"for {NAME}.",
        f"{len(down)} machines start in maintenance or idle, so capacity shows real gaps.",
    ]
