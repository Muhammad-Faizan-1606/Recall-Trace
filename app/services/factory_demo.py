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
        machine(
            f"CUT-PK-{number:02d}", "Lectra Vector iX6 with spreader", "CUT-CNC", cut_park, 4000
        )
    for number in range(1, 3):
        machine(f"CUT-QE-{number:02d}", "Lectra Vector iX6 with spreader", "CUT-CNC", cut_qie, 3500)
    for number in range(1, 7):
        machine(f"PRT-{number:02d}", "M&R Gauntlet oval screen printer", "PRINT-OVAL", prt, 600)
    for number in range(1, 5):
        machine(f"EMB-{number:02d}", "Tajima TMAR-K1512C (12 heads)", "EMB-12H", emb, 120)
    for number in range(1, 5):
        machine(f"WSH-{number:02d}", "Stainless steel tumbler 100 kg", "WASH-TMB", wash, 100)
    for number in range(1, 13):
        machine(f"PCK-{number:02d}", "Packing table with needle detector", "PACK", pack, 600)

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


# ---------- Step 2: fictional buyers, styles, fabric and work content ----------

BUYERS = [
    ("NPA", "Northpeak Athletics (demo)"),
    ("HPA", "Harbour & Pine Apparel (demo)"),
    ("VLS", "Velo Sportswear (demo)"),
]
OL, FL, LS, MAN = "SEW-OL", "SEW-FL", "SEW-LS", None
# style code, name, product type, buyer, fabrics [(component, type, composition, gsm, width,
# c/cm, kg per garment, relax hours)], operations [(name, class, basic minutes)]
STYLES = [
    (
        "NP-TEE-101",
        "Crew neck essential tee",
        "tee",
        "NPA",
        [
            ("Body", "single_jersey", "100% combed cotton", "160", "1.80", "16", "0.190", 24),
            ("Neck rib", "rib", "95% cotton 5% elastane", "220", "0.90", None, "0.012", 24),
        ],
        [
            ("Shoulder join", OL, "0.35"),
            ("Neck rib close", OL, "0.18"),
            ("Neck rib attach", OL, "0.45"),
            ("Back neck tape", LS, "0.40"),
            ("Care label attach", LS, "0.30"),
            ("Sleeve attach", OL, "0.70"),
            ("Side seam and sleeve close", OL, "0.85"),
            ("Sleeve hem", FL, "0.55"),
            ("Bottom hem", FL, "0.50"),
            ("Neck topstitch", FL, "0.45"),
            ("Trim threads", MAN, "0.40"),
            ("Inspect and fold", MAN, "0.45"),
        ],
    ),
    (
        "NP-LS-150",
        "Long-sleeve base layer",
        "long_sleeve",
        "NPA",
        [
            ("Body", "single_jersey", "100% combed cotton", "180", "1.80", "17", "0.260", 24),
            (
                "Cuff and neck rib",
                "rib",
                "95% cotton 5% elastane",
                "220",
                "0.90",
                None,
                "0.020",
                24,
            ),
        ],
        [
            ("Shoulder join", OL, "0.35"),
            ("Neck rib attach", OL, "0.48"),
            ("Back neck tape", LS, "0.40"),
            ("Label attach", LS, "0.30"),
            ("Sleeve attach", OL, "0.75"),
            ("Side seam and sleeve close", OL, "1.05"),
            ("Cuff close", OL, "0.30"),
            ("Cuff attach", OL, "0.70"),
            ("Bottom hem", FL, "0.50"),
            ("Neck topstitch", FL, "0.45"),
            ("Trim threads", MAN, "0.45"),
            ("Inspect and fold", MAN, "0.50"),
        ],
    ),
    (
        "NP-POLO-220",
        "Piqué polo with placket",
        "polo",
        "NPA",
        [
            ("Body", "pique", "100% cotton", "210", "1.85", "15", "0.300", 24),
            ("Collar and cuff", "rib", "100% cotton flat knit", "250", "0.80", None, "0.030", 24),
        ],
        [
            ("Placket fuse and fold", LS, "0.80"),
            ("Placket attach", LS, "1.40"),
            ("Placket box stitch", LS, "0.90"),
            ("Shoulder join", OL, "0.38"),
            ("Collar attach", LS, "1.20"),
            ("Neck tape and topstitch", LS, "0.90"),
            ("Sleeve attach", OL, "0.80"),
            ("Cuff attach", OL, "0.70"),
            ("Side seam with vents", OL, "1.10"),
            ("Bottom hem", FL, "0.55"),
            ("Buttonhole", LS, "0.60"),
            ("Button sew", LS, "0.55"),
            ("Trim threads", MAN, "0.60"),
            ("Inspect and fold", MAN, "0.65"),
        ],
    ),
    (
        "VL-TANK-120",
        "Training tank",
        "tank",
        "VLS",
        [("Body", "single_jersey", "92% polyester 8% elastane", "150", "1.70", "20", "0.140", 48)],
        [
            ("Shoulder join", OL, "0.30"),
            ("Armhole binding", FL, "0.90"),
            ("Neck binding", FL, "0.70"),
            ("Side seam", OL, "0.55"),
            ("Bottom hem", FL, "0.45"),
            ("Heat transfer logo", MAN, "0.50"),
            ("Trim and inspect", MAN, "0.55"),
        ],
    ),
    (
        "VL-LEG-410",
        "Performance leggings",
        "leggings",
        "VLS",
        [("Body", "interlock", "78% polyester 22% elastane", "260", "1.60", "22", "0.230", 48)],
        [
            ("Gusset attach", FL, "0.80"),
            ("Inseam", FL, "1.10"),
            ("Crotch seam", FL, "0.90"),
            ("Waistband close", OL, "0.35"),
            ("Waistband elastic insert", OL, "0.70"),
            ("Waistband attach", FL, "1.20"),
            ("Leg hem", FL, "0.80"),
            ("Label attach", LS, "0.30"),
            ("Trim and inspect", MAN, "0.70"),
        ],
    ),
    (
        "HP-SWT-500",
        "Crewneck sweatshirt",
        "sweatshirt",
        "HPA",
        [
            ("Body", "fleece", "80% cotton 20% polyester", "300", "1.90", "14", "0.480", 24),
            ("Rib", "rib", "95% cotton 5% elastane", "300", "0.90", None, "0.060", 24),
        ],
        [
            ("Shoulder join", OL, "0.40"),
            ("Neck rib attach", OL, "0.55"),
            ("Back neck tape", LS, "0.45"),
            ("Label attach", LS, "0.30"),
            ("Sleeve attach", OL, "0.90"),
            ("Side seam and sleeve close", OL, "1.20"),
            ("Cuff close", OL, "0.30"),
            ("Cuff attach", OL, "0.80"),
            ("Waistband close", OL, "0.30"),
            ("Waistband attach", OL, "0.90"),
            ("Coverstitch neck and seams", FL, "1.30"),
            ("Trim threads", MAN, "0.60"),
            ("Inspect and fold", MAN, "0.70"),
        ],
    ),
    (
        "NP-HOOD-805",
        "Fleece pullover hoodie",
        "hoodie",
        "NPA",
        [
            ("Body", "fleece", "80% cotton 20% polyester", "320", "1.90", "14", "0.620", 24),
            ("Hood lining", "single_jersey", "100% cotton", "180", "1.80", "16", "0.070", 24),
            ("Rib", "rib", "95% cotton 5% elastane", "300", "0.90", None, "0.060", 24),
        ],
        [
            ("Hood centre seam", OL, "0.60"),
            ("Hood lining seam", OL, "0.55"),
            ("Hood join and topstitch", FL, "1.20"),
            ("Eyelets", LS, "0.50"),
            ("Drawcord insert", MAN, "0.60"),
            ("Kangaroo pocket hem", FL, "0.70"),
            ("Pocket attach", LS, "1.60"),
            ("Shoulder join", OL, "0.42"),
            ("Hood attach", OL, "1.10"),
            ("Neck tape", LS, "0.70"),
            ("Sleeve attach", OL, "0.95"),
            ("Side seam and sleeve close", OL, "1.25"),
            ("Cuff attach", OL, "0.85"),
            ("Waistband attach", OL, "0.95"),
            ("Coverstitch seams", FL, "1.40"),
            ("Label attach", LS, "0.35"),
            ("Trim threads", MAN, "0.80"),
            ("Inspect and fold", MAN, "0.85"),
        ],
    ),
    (
        "HP-JOG-310",
        "Fleece jogger",
        "jogger",
        "HPA",
        [
            ("Body", "fleece", "80% cotton 20% polyester", "300", "1.90", "14", "0.520", 24),
            ("Rib cuff", "rib", "95% cotton 5% elastane", "300", "0.90", None, "0.040", 24),
        ],
        [
            ("Side pocket bags", OL, "0.90"),
            ("Pocket attach", LS, "1.30"),
            ("Back pocket", LS, "1.10"),
            ("Outseam", OL, "0.80"),
            ("Inseam", OL, "0.90"),
            ("Crotch seam", OL, "0.70"),
            ("Waistband elastic and cord", OL, "1.10"),
            ("Waistband attach", OL, "0.95"),
            ("Cuff attach", OL, "0.80"),
            ("Coverstitch waistband", FL, "0.70"),
            ("Label attach", LS, "0.30"),
            ("Trim threads", MAN, "0.70"),
            ("Inspect and fold", MAN, "0.70"),
        ],
    ),
]


def seed_styles(organization, member):
    """Add the fictional buyers and styles once (also to a demo seeded before step 2)."""
    from app.models import now as current_time
    from app.models.factory import (
        BulletinOperation,
        FabricSpec,
        OperationBulletin,
        Style,
    )
    from app.models.master import Partner, PartnerRoleAssignment
    from app.services.engineering import operation_sam

    company_id = organization.id
    if db.session.scalar(select(Style.id).where(Style.organization_id == company_id)):
        return []
    classes = {
        row.code: row.id
        for row in db.session.scalars(
            select(MachineClass).where(MachineClass.organization_id == company_id)
        )
    }
    if not {OL, FL, LS} <= set(classes):
        return ["Sewing machine classes missing; styles not added."]
    buyers = {}
    for code, name in BUYERS:
        partner = db.session.scalar(
            select(Partner).where(Partner.organization_id == company_id, Partner.code == code)
        )
        if partner is None:
            partner = Partner(organization_id=company_id, code=code, name=name)
            db.session.add(partner)
            db.session.flush()
            db.session.add(
                PartnerRoleAssignment(
                    organization_id=company_id, partner_id=partner.id, role_code="customer"
                )
            )
        buyers[code] = partner
    allowance = D("0.250")
    total_operations = 0
    for code, name, product_type, buyer, fabrics, steps in STYLES:
        style = Style(
            organization_id=company_id,
            code=code,
            name=name,
            product_type=product_type,
            season="SS27",
            buyer_id=buyers[buyer].id,
        )
        db.session.add(style)
        db.session.flush()
        for component, fabric_type, composition, gsm, width, cpc, kg, relax in fabrics:
            db.session.add(
                FabricSpec(
                    organization_id=company_id,
                    style_id=style.id,
                    component=component,
                    fabric_type=fabric_type,
                    composition=composition,
                    gsm=D(gsm),
                    width_m=D(width),
                    courses_per_cm=D(cpc) if cpc else None,
                    consumption_kg=D(kg),
                    relaxation_hours=relax,
                )
            )
        bulletin = OperationBulletin(
            organization_id=company_id,
            style_id=style.id,
            revision=1,
            allowance_factor=allowance,
            source="Fictional GSD study",
        )
        db.session.add(bulletin)
        db.session.flush()
        for index, (operation, class_code, basic) in enumerate(steps, 1):
            db.session.add(
                BulletinOperation(
                    organization_id=company_id,
                    bulletin_id=bulletin.id,
                    sequence=index * 10,
                    name=operation,
                    machine_class_id=classes[class_code] if class_code else None,
                    basic_minutes=D(basic),
                    allowance_factor=allowance,
                    sam=operation_sam(D(basic), allowance),
                )
            )
            total_operations += 1
        db.session.flush()
        bulletin.status = "published"
        bulletin.published_at = current_time()
    db.session.flush()
    audit(company_id, "factory.demo_styles_seeded", "styles", None, {"count": len(STYLES)})
    return [
        f"{len(BUYERS)} fictional buyers and {len(STYLES)} styles with published operation "
        f"bulletins ({total_operations} operations)."
    ]


# ---------- Step 3: fictional production orders ----------

# reference, style, pieces, colour, ex-factory in days, priority, sewing lines, prints
ORDERS = [
    ("PO-27001", "NP-TEE-101", 72000, "Black", 24, 2, 5, 1),
    ("PO-27002", "NP-HOOD-805", 27000, "Heather grey", 30, 2, 6, 1),
    ("PO-27003", "VL-LEG-410", 45000, "Navy", 26, 3, 4, 0),
    ("PO-27004", "HP-SWT-500", 24000, "Oatmeal", 30, 3, 4, 0),
    ("PO-27005", "NP-POLO-220", 36000, "White", 28, 3, 5, 0),
    ("PO-27006", "VL-TANK-120", 54000, "Volt green", 20, 2, 4, 1),
    ("PO-27007", "HP-JOG-310", 30000, "Charcoal", 34, 3, 4, 0),
    ("PO-27008", "NP-LS-150", 42000, "Bone", 36, 4, 4, 0),
    ("PO-27009", "NP-TEE-101", 90000, "White", 30, 4, 5, 1),
    ("PO-27010", "NP-HOOD-805", 18000, "Black", 16, 1, 5, 1),
    ("PO-27011", "VL-LEG-410", 27000, "Black", 40, 4, 3, 0),
    ("PO-27012", "HP-SWT-500", 21000, "Forest", 14, 1, 4, 0),
    ("PO-27013", "NP-POLO-220", 24000, "Navy", 44, 5, 3, 0),
    ("PO-27014", "HP-JOG-310", 36000, "Heather grey", 31, 5, 4, 0),
]
RELEASED = ("PO-27010", "PO-27012", "PO-27006")


def seed_orders(organization, member, today=None):
    """Add fictional orders once, plan them, and release the most urgent three."""
    from app.models.factory import ProductionOrder, Style
    from app.services import engineering, planning

    company_id = organization.id
    if db.session.scalar(
        select(ProductionOrder.id).where(ProductionOrder.organization_id == company_id)
    ):
        return []
    today = today or date.today()
    styles = {
        row.code: row
        for row in db.session.scalars(select(Style).where(Style.organization_id == company_id))
    }
    current = engineering.current_bulletins(company_id)
    # Demos seeded before step 3 rated the cutters at 900/800 panels an hour, far below a
    # multi-ply CNC cutter; correct them in this fictional company only.
    for machine in db.session.scalars(
        select(Machine).where(
            Machine.organization_id == company_id,
            Machine.asset_tag.like("CUT-%"),
            Machine.rated_value < 1000,
        )
    ):
        machine.rated_value = D(4000) if machine.asset_tag.startswith("CUT-PK") else D(3500)
    # The same applies to packing tables first rated at 180 pieces an hour (one packer).
    for machine in db.session.scalars(
        select(Machine).where(
            Machine.organization_id == company_id,
            Machine.asset_tag.like("PCK-%"),
            Machine.rated_value < 600,
        )
    ):
        machine.rated_value = D(600)
    added = 0
    for reference, code, pieces, colour, days, priority, lines, prints in ORDERS:
        style = styles.get(code)
        if style is None or style.id not in current:
            continue
        db.session.add(
            ProductionOrder(
                organization_id=company_id,
                reference=reference,
                style_id=style.id,
                bulletin_id=current[style.id].id,
                quantity=pieces,
                colour=colour,
                ex_factory_on=today + timedelta(days=days),
                priority=priority,
                sewing_lines=lines,
                prints_per_piece=prints,
            )
        )
        added += 1
    db.session.flush()
    planning.replan(company_id, today)
    for order in db.session.scalars(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.reference.in_(RELEASED),
            ProductionOrder.status == "planned",
        )
    ):
        order.status = "released"
    db.session.flush()
    plans = planning.replan(company_id, today)
    late = sum(
        1
        for order in db.session.scalars(
            select(ProductionOrder).where(ProductionOrder.organization_id == company_id)
        )
        if order.planned_finish_on and order.planned_finish_on > order.ex_factory_on
    )
    return [
        f"{added} fictional production orders planned ({len(RELEASED)} released, "
        f"{len(plans)} re-planned); {late} finish after their ex-factory date."
    ]


# ---------- Step 4: fictional line balances ----------

# Which style each site's lines run (cycled over the site's lines).
LINE_STYLES = {
    "QIE1": ("NP-TEE-101", "NP-LS-150", "NP-POLO-220"),
    "QIE2": ("NP-TEE-101", "HP-SWT-500", "NP-HOOD-805", "NP-POLO-220"),
    "PARK": ("NP-HOOD-805", "NP-TEE-101", "HP-JOG-310", "HP-SWT-500", "VL-TANK-120"),
    "RWD": ("HP-JOG-310", "HP-SWT-500", "NP-LS-150"),
    "SUN": ("VL-LEG-410", "VL-TANK-120"),
}
# Lines whose published balance was edited by hand into an uneven one, so the screen has
# a real bottleneck to explain, and one line with a changeover draft in progress.
UNEVEN = ("QIE2-L03", "PARK-L02")
CHANGEOVER = ("RWD-L01", "NP-LS-150")


def _largest_crew(ops, machines):
    """Most operators (up to 32) whose machine stations this line can actually equip."""
    from app.services.balancing import operators_by_class

    working = {}
    for machine, _ in machines:
        if machine.status in ("active", "idle"):
            working[machine.machine_class_id] = working.get(machine.machine_class_id, 0) + 1
    minimum = len({op.class_id for op in ops})
    for crew in range(32, minimum - 1, -1):
        counts = operators_by_class(ops, crew)
        if all(n <= working.get(cls, 0) for cls, n in counts.items() if cls is not None):
            return crew
    return minimum


def _make_uneven(stations):
    """Hand one station's whole first operation to its neighbour of the same machine type."""
    for index, station in enumerate(stations[:-1]):
        neighbour = stations[index + 1]
        if station.class_id and station.class_id == neighbour.class_id and len(station.work) > 1:
            op, share = station.work[0]
            station.work = station.work[1:]
            neighbour.work.append((op, share))
            return


def seed_balances(organization, member):
    """Publish an automatic balance for every demo sewing line, once."""
    from app.models import now as current_time
    from app.models.factory import LineBalance, Style
    from app.services import balancing, engineering
    from app.services.factory import machines_by_center

    company_id = organization.id
    if db.session.scalar(select(LineBalance.id).where(LineBalance.organization_id == company_id)):
        return []
    styles = {
        row.code: row
        for row in db.session.scalars(select(Style).where(Style.organization_id == company_id))
    }
    current = engineering.current_bulletins(company_id)
    lines = balancing.sewing_lines(company_id)
    machines = machines_by_center(company_id, [line.id for line in lines])
    published = 0
    for line in lines:
        site = line.code.split("-L")[0]
        choices = LINE_STYLES.get(site)
        if not choices:
            continue
        number = int(line.code.rsplit("L", 1)[1])
        style = styles.get(choices[(number - 1) % len(choices)])
        if style is None or style.id not in current:
            continue
        bulletin = current[style.id]
        ops = balancing.bulletin_ops(company_id, bulletin.id)
        on_line = machines.get(line.id, [])
        stations = balancing.auto_layout(ops, _largest_crew(ops, on_line))
        if line.code in UNEVEN:
            _make_uneven(stations)
        balance = LineBalance(
            organization_id=company_id,
            work_center_id=line.id,
            bulletin_id=bulletin.id,
            revision=1,
            # Planned efficiency varies a little by line: 64% to 74%.
            target_efficiency=D(64 + (number * 7 + len(site)) % 11),
            note="Fictional demo balance",
        )
        db.session.add(balance)
        db.session.flush()
        balancing._write(company_id, balance, stations, on_line)
        balance.status = "published"
        balance.published_at = current_time()
        db.session.flush()
        published += 1
        if line.code == CHANGEOVER[0] and CHANGEOVER[1] in styles:
            next_style = styles[CHANGEOVER[1]]
            if next_style.id in current:
                next_ops = balancing.bulletin_ops(company_id, current[next_style.id].id)
                draft = LineBalance(
                    organization_id=company_id,
                    work_center_id=line.id,
                    bulletin_id=current[next_style.id].id,
                    revision=2,
                    target_efficiency=balance.target_efficiency,
                    note="Changeover planned after the current order",
                )
                db.session.add(draft)
                db.session.flush()
                balancing._write(
                    company_id,
                    draft,
                    balancing.auto_layout(next_ops, _largest_crew(next_ops, on_line)),
                    on_line,
                )
    db.session.flush()
    audit(company_id, "factory.demo_balances_seeded", "line_balances", None, {"count": published})
    return [
        f"{published} sewing lines balanced and published ({len(UNEVEN)} left uneven to show "
        "the bottleneck tools), plus one changeover draft."
    ]
