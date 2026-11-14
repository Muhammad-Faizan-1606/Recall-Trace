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

from sqlalchemy import func, select

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


# ---------- Step 5: fictional shop-floor history ----------

DOWNTIME_REASONS = [
    ("BRK", "Machine breakdown", "breakdown", "off_standard"),
    ("PWR", "Power cut", "power", "off_standard"),
    ("FEED", "No feeding (waiting for bundles)", "no_feeding", "off_standard"),
    ("CHG", "Style changeover", "changeover", "off_standard"),
    ("NDL", "Needle or bobbin change", "needle_bobbin", "operator"),
    ("RWK", "Quality rework", "quality", "operator"),
    ("MTG", "Line meeting", "meeting", "off_standard"),
    ("OTH", "Other", "other", "operator"),
]
# How each line performs against its plan in the fictional history (1.00 = on plan).
LINE_FORM = {"QIE2-L03": 0.78, "PARK-L06": 0.86, "PARK-L05": 1.04, "SUN-L02": 0.93}


def _pace(code, hour, day_index):
    """A deterministic hourly rhythm: slow first hour, a dip after lunch, steady otherwise."""
    shape = {1: 0.74, 2: 0.92, 5: 0.88}.get(hour, 1.0)
    wobble = ((sum(map(ord, code)) * 7 + hour * 13 + day_index * 29) % 11 - 5) / 100
    return shape + wobble


def seed_floor(organization, member, today=None):
    """Two days of hourly output, stops, rolls, dye batches and bundles, once."""
    from app.models import now as current_time
    from app.models.factory import (
        CutBundle,
        DowntimeEvent,
        DowntimeReason,
        DyeBatch,
        KnitRoll,
        OutputLog,
        ProductionOrder,
    )
    from app.services import balancing, engineering

    company_id = organization.id
    if db.session.scalar(
        select(DowntimeReason.id).where(DowntimeReason.organization_id == company_id)
    ):
        return []
    today = today or date.today()
    reasons = {}
    for code, name, category, rule in DOWNTIME_REASONS:
        reason = DowntimeReason(
            organization_id=company_id,
            code=code,
            name=name,
            category=category,
            efficiency_rule=rule,
        )
        db.session.add(reason)
        reasons[code] = reason
    db.session.flush()

    released = db.session.scalars(
        select(ProductionOrder).where(
            ProductionOrder.organization_id == company_id,
            ProductionOrder.status == "released",
        )
    ).all()
    by_style = {order.style_id: order for order in released}
    sams = engineering.bulletin_sams(company_id, [o.bulletin_id for o in released])
    current = balancing.current_balances(company_id)
    figures = balancing.summaries(company_id, list(current.values()))
    from app.models.factory import OperationBulletin, ShiftPattern

    bulletins = {
        b.id: b
        for b in db.session.scalars(
            select(OperationBulletin).where(OperationBulletin.organization_id == company_id)
        )
    }
    patterns = {
        p.id: p
        for p in db.session.scalars(
            select(ShiftPattern).where(ShiftPattern.organization_id == company_id)
        )
    }
    lines = {line.id: line for line in balancing.sewing_lines(company_id)}
    logs = stops = 0
    first_log = None
    for line_id, balance in current.items():
        line = lines.get(line_id)
        bulletin = bulletins.get(balance.bulletin_id)
        order = by_style.get(bulletin.style_id) if bulletin else None
        if line is None or order is None or balance.id not in figures:
            continue
        stations, _, per_day = figures[balance.id]
        minutes = balancing.productive_minutes(patterns[line.shift_pattern_id])
        hours = int(minutes // 60)
        per_hour = per_day / minutes * 60
        form = Decimal(str(LINE_FORM.get(line.code, 0.97)))
        for day_index, day in enumerate((today - timedelta(days=1), today)):
            last_hour = hours if day_index == 0 else min(5, hours)
            for hour in range(1, last_hour + 1):
                pace = Decimal(str(_pace(line.code, hour, day_index)))
                good = int(per_hour * form * pace)
                rejects = max(0, int(good * Decimal("0.018") * pace) + (hour % 3 == 0))
                row = OutputLog(
                    organization_id=company_id,
                    work_center_id=line.id,
                    production_order_id=order.id,
                    day=day,
                    hour=hour,
                    good_pieces=good,
                    rejects=rejects,
                    operators=stations - (1 if hour == 1 and line.code.endswith("3") else 0),
                    minutes=60,
                    sam=Decimal(sams[order.bulletin_id]),
                    recorded_by_id=member.id,
                    recorded_at=current_time() - timedelta(days=1 - day_index, hours=12 - hour),
                )
                db.session.add(row)
                logs += 1
                if first_log is None and day_index == 0 and hour == 3:
                    first_log = row
        yesterday = today - timedelta(days=1)
        if line.code.startswith("PARK"):
            db.session.add(
                DowntimeEvent(
                    organization_id=company_id,
                    work_center_id=line.id,
                    reason_id=reasons["PWR"].id,
                    day=yesterday,
                    hour=4,
                    minutes=25,
                    operators_affected=stations,
                    note="Grid outage before the generator took over",
                    recorded_by_id=member.id,
                )
            )
            stops += 1
        if line.code in LINE_FORM:
            db.session.add(
                DowntimeEvent(
                    organization_id=company_id,
                    work_center_id=line.id,
                    reason_id=reasons["NDL"].id,
                    day=yesterday,
                    hour=6,
                    minutes=18,
                    operators_affected=2,
                    recorded_by_id=member.id,
                )
            )
            db.session.add(
                DowntimeEvent(
                    organization_id=company_id,
                    work_center_id=line.id,
                    reason_id=reasons["FEED"].id,
                    day=today,
                    hour=2,
                    minutes=20,
                    operators_affected=max(1, stations // 3),
                    note="Waiting for cut bundles from the cutting bay",
                    recorded_by_id=member.id,
                )
            )
            stops += 2
    db.session.flush()
    if first_log is not None:
        db.session.add(
            OutputLog(
                organization_id=company_id,
                work_center_id=first_log.work_center_id,
                production_order_id=first_log.production_order_id,
                day=first_log.day,
                hour=first_log.hour,
                good_pieces=first_log.good_pieces + 12,
                rejects=first_log.rejects,
                operators=first_log.operators,
                minutes=60,
                sam=first_log.sam,
                corrects_id=first_log.id,
                note="One bundle was counted on the next hour's sheet",
                recorded_by_id=member.id,
            )
        )

    # Batch cards for the released orders: rolls, dye batches and bundles.
    knitters = db.session.scalars(
        select(Machine)
        .where(Machine.organization_id == company_id, Machine.asset_tag.like("KNT-%"))
        .order_by(Machine.asset_tag)
    ).all()
    vessels = db.session.scalars(
        select(Machine)
        .where(
            Machine.organization_id == company_id,
            Machine.asset_tag.like("DYE-JET-%"),
            Machine.status == "active",
        )
        .order_by(Machine.rated_value.desc(), Machine.asset_tag)
    ).all()
    rolls = batches = bundles = 0
    sizes = (("S", 0.2), ("M", 0.3), ("L", 0.3), ("XL", 0.2))
    for index, order in enumerate(sorted(released, key=lambda o: o.reference)):
        prefix = order.reference.replace("PO-", "")
        vessel = vessels[index % len(vessels)] if vessels else None
        batch_rolls = []
        for number in range(1, 13):
            roll = KnitRoll(
                organization_id=company_id,
                roll_number=f"R{prefix}-{number:03d}",
                machine_id=knitters[(index * 12 + number) % len(knitters)].id,
                production_order_id=order.id,
                knitted_on=today - timedelta(days=4 - (number % 3)),
                kg=Decimal("22.5") + Decimal(number % 4),
                grade="B" if number == 7 else "A",
            )
            db.session.add(roll)
            batch_rolls.append(roll)
            rolls += 1
        db.session.flush()
        if vessel is None:
            continue
        status = "passed" if index < 2 else "dyeing"
        started = current_time() - timedelta(days=2, hours=index * 3)
        loaded = []
        for roll in batch_rolls[:10]:
            if sum(r.kg for r in loaded) + roll.kg > vessel.rated_value:
                break
            loaded.append(roll)
        batch = DyeBatch(
            organization_id=company_id,
            batch_number=f"DB-{prefix}-1",
            machine_id=vessel.id,
            production_order_id=order.id,
            colour=order.colour,
            recipe_reference=f"RCP-{prefix[-3:]}-{order.colour[:3].upper()}",
            status=status,
            started_at=started,
            finished_at=started + timedelta(hours=7) if status == "passed" else None,
        )
        db.session.add(batch)
        db.session.flush()
        for roll in loaded:
            roll.dye_batch_id = batch.id
        batches += 1
        if status != "passed":
            continue
        count = 0
        for lay in (1, 2):
            for size, share in sizes:
                pieces = int(360 * share)
                for chunk in range(0, pieces, 30):
                    count += 1
                    state = "sewn" if lay == 1 and count % 4 else ("issued" if lay == 1 else "cut")
                    line = next(
                        (
                            lines[lid]
                            for lid, b in current.items()
                            if lid in lines
                            and bulletins.get(b.bulletin_id)
                            and bulletins[b.bulletin_id].style_id == order.style_id
                        ),
                        None,
                    )
                    if line is None:
                        state = "cut"
                    issued_at = current_time() - timedelta(hours=20) if state != "cut" else None
                    db.session.add(
                        CutBundle(
                            organization_id=company_id,
                            bundle_number=f"{order.reference}-{count:04d}",
                            production_order_id=order.id,
                            dye_batch_id=batch.id,
                            lay_number=f"L{prefix}-{lay:02d}",
                            size=size,
                            pieces=min(30, pieces - chunk),
                            status=state,
                            issued_line_id=line.id if state != "cut" else None,
                            issued_at=issued_at,
                            sewn_at=current_time() - timedelta(hours=6)
                            if state == "sewn"
                            else None,
                        )
                    )
                    bundles += 1
    db.session.flush()
    audit(company_id, "factory.demo_floor_seeded", "output_logs", None, {"count": logs})
    return [
        f"Shop floor history: {logs} hourly entries over two days (one corrected), {stops} stops, "
        f"{rolls} knit rolls, {batches} dye batches and {bundles} cut bundles."
    ]


# ---------- Step 6: first run of the factory checks ----------


def seed_alerts(organization, member):
    """Run the checks once on the fictional history, acknowledge one and keep one resolved."""
    from app.models import now as current_time
    from app.models.factory import FactoryAlert, WorkCenter
    from app.services import alerts

    company_id = organization.id
    if db.session.scalar(select(FactoryAlert.id).where(FactoryAlert.organization_id == company_id)):
        return []
    park = db.session.scalar(
        select(WorkCenter).where(
            WorkCenter.organization_id == company_id, WorkCenter.code == "PARK-L01"
        )
    )
    moment = current_time()
    if park is not None:
        db.session.add(
            FactoryAlert(
                organization_id=company_id,
                kind="line_starving",
                severity="warning",
                dedupe_key=f"wip:{park.id}:demo-history",
                title="PARK-L01 ran short of cut bundles",
                detail="Fictional earlier alert: the line had under one hour of work waiting.",
                work_center_id=park.id,
                first_seen_at=moment - timedelta(days=2, hours=3),
                last_seen_at=moment - timedelta(days=2, hours=2),
                cleared_at=moment - timedelta(days=2, hours=1),
                status="resolved",
                acknowledged_at=moment - timedelta(days=2, hours=2, minutes=40),
                acknowledged_by_id=member.id,
                resolved_at=moment - timedelta(days=2, hours=1),
                resolved_by_id=member.id,
                resolution_note="Cutting bay issued lay 2 early; line fed again within 40 min.",
            )
        )
    db.session.flush()
    raised, cleared, active = alerts.scan(company_id)
    first = db.session.scalar(
        select(FactoryAlert).where(
            FactoryAlert.organization_id == company_id,
            FactoryAlert.status == "open",
            FactoryAlert.kind == "efficiency_low",
        )
    )
    if first is not None:
        alerts.acknowledge(company_id, first.id, first.version, member.id)
    return [f"Factory checks run: {raised} alerts raised from the fictional history."]


# ---------- Step 7: fictional maintenance history ----------

# plan code, name, machine class, every (days), minutes, tasks
PLANS = [
    (
        "PM-KSJ-30",
        "Single jersey frame service",
        "KNIT-SJ",
        30,
        120,
        "Clean feeders and sinkers, oil cylinder, replace worn needles, check yarn tension",
    ),
    (
        "PM-KIN-30",
        "Interlock frame service",
        "KNIT-INT",
        30,
        120,
        "Clean feeders and sinkers, oil cylinder, replace worn needles, check yarn tension",
    ),
    (
        "PM-KFL-30",
        "Fleece frame service",
        "KNIT-FLC",
        30,
        150,
        "Clean loop-raising zone, oil cylinder, check sinker cams and needles",
    ),
    (
        "PM-JET-14",
        "Jet vessel service",
        "DYE-JET",
        14,
        180,
        "Check pump seal and nozzle, clean filters and heat exchanger, calibrate temperature probe",
    ),
    (
        "PM-STN-30",
        "Stenter service",
        "STENTER",
        30,
        240,
        "Clean burners and chain, lubricate chain rails, check pins and clips",
    ),
    (
        "PM-CUT-60",
        "CNC cutter service",
        "CUT-CNC",
        60,
        180,
        "Sharpen and check blade, clean vacuum bed, check bristle blocks",
    ),
    (
        "PM-SOL-90",
        "Overlock station service",
        "SEW-OL",
        90,
        30,
        "Clean and oil, check loopers and knives, replace needle plate if worn",
    ),
    (
        "PM-SFL-90",
        "Flatlock station service",
        "SEW-FL",
        90,
        30,
        "Clean and oil, check spreader and loopers, check differential feed",
    ),
    (
        "PM-SLS-90",
        "Lockstitch station service",
        "SEW-LS",
        90,
        30,
        "Clean and oil, check hook timing and thread trimmer",
    ),
]
# (machine asset tag, days ago, response minutes, repair hours, problem, work done)
BREAKDOWNS = [
    ("KNT-SJ-03", 81, 25, 3.5, "Dropped stitches across the tube", "Replaced 14 broken needles"),
    ("KNT-SJ-03", 47, 15, 2.0, "Dropped stitches again", "Replaced needles, adjusted cam"),
    ("KNT-SJ-03", 12, 30, 5.0, "Holes in fabric, needle breakage", "Replaced needle bed section"),
    ("KNT-SJ-11", 66, 20, 1.5, "Yarn feeder not storing", "Replaced feeder belt"),
    ("KNT-IN-05", 58, 40, 6.0, "Cylinder drive overheating", "Replaced drive belt, cleaned fan"),
    ("KNT-FL-02", 33, 10, 1.0, "Fabric take-down slipping", "Adjusted take-down tension"),
    ("DYE-JET-04", 74, 45, 8.0, "Pump cavitation, uneven shade", "Replaced impeller"),
    ("DYE-JET-04", 21, 35, 4.5, "Temperature overshoot", "Replaced steam valve actuator"),
    ("DYE-JET-11", 40, 20, 2.5, "Door seal leaking", "Replaced door gasket"),
    ("STN-02", 52, 30, 3.0, "Chain jumping at the entry", "Replaced worn chain links"),
    ("CUT-PK-02", 29, 15, 1.5, "Blade sensor fault", "Replaced blade sensor"),
    ("PARK-L02-S03", 18, 10, 0.75, "Skipped stitches", "Retimed looper"),
    ("PARK-L02-S03", 5, 8, 0.5, "Skipped stitches", "Replaced needle plate"),
    ("QIE2-L03-S07", 26, 12, 1.0, "Knife not cutting cleanly", "Replaced upper knife"),
    ("QIE2-L03-S16", 9, 15, 0.75, "Differential feed noisy", "Replaced feed dog spring"),
    ("RWD-L02-S21", 44, 20, 1.25, "Thread trimmer not firing", "Replaced trimmer solenoid"),
    ("SUN-L04-S02", 15, 6, 0.5, "Needle breaking repeatedly", "Reset needle bar height"),
]
COMMISSIONED = date(2024, 3, 1)


def seed_maintenance(organization, member, today=None):
    """Plans, a year of preventive history and 90 days of breakdowns, once."""
    from datetime import datetime, time

    from app.models import now as current_time
    from app.models.factory import MaintenancePlan, MaintenanceTicket

    company_id = organization.id
    if db.session.scalar(
        select(MaintenancePlan.id).where(MaintenancePlan.organization_id == company_id)
    ):
        return []
    today = today or date.today()
    moment = current_time()
    zone = moment.tzinfo
    classes = {
        c.code: c
        for c in db.session.scalars(
            select(MachineClass).where(MachineClass.organization_id == company_id)
        )
    }
    machines = db.session.scalars(
        select(Machine).where(Machine.organization_id == company_id).order_by(Machine.asset_tag)
    ).all()
    by_tag = {m.asset_tag: m for m in machines}
    # The fictional floor has been running since early 2024.
    for machine in machines:
        if machine.commissioned_on is None:
            machine.commissioned_on = COMMISSIONED
    tickets = []
    plans = []
    for code, name, class_code, every, minutes, tasks in PLANS:
        if class_code not in classes:
            continue
        plan = MaintenancePlan(
            organization_id=company_id,
            code=code,
            name=name,
            machine_class_id=classes[class_code].id,
            interval_days=every,
            duration_minutes=minutes,
            tasks=tasks,
        )
        db.session.add(plan)
        plans.append(plan)
    db.session.flush()
    for plan in plans:
        for index, machine in enumerate(
            m for m in machines if m.machine_class_id == plan.machine_class_id
        ):
            # Spread last jobs over a little more than one interval: about 5% overdue.
            days_ago = (index * 37 + len(plan.code)) % int(plan.interval_days * 1.05 + 1)
            done = datetime.combine(today - timedelta(days=days_ago), time(14, 0), zone)
            done = min(done, moment - timedelta(hours=2))
            started = done - timedelta(minutes=plan.duration_minutes)
            tickets.append(
                dict(
                    machine_id=machine.id,
                    kind="preventive",
                    plan_id=plan.id,
                    description=f"{plan.name}: {plan.tasks}"[:400],
                    reported_at=started - timedelta(days=1),
                    started_at=started,
                    finished_at=done,
                    status="closed",
                    work_done="Done as per plan",
                )
            )
    events = []
    for tag, days_ago, response, repair, problem, work in BREAKDOWNS:
        machine = by_tag.get(tag)
        if machine is None:
            continue
        reported = datetime.combine(today - timedelta(days=days_ago), time(10, 30), zone)
        finished = reported + timedelta(hours=repair)
        tickets.append(
            dict(
                machine_id=machine.id,
                kind="breakdown",
                description=problem,
                reported_at=reported,
                started_at=reported + timedelta(minutes=response),
                finished_at=finished,
                status="closed",
                work_done=work,
                parts_used=None,
            )
        )
        events += [
            (machine.id, "active", "maintenance", f"Breakdown: {problem}", reported),
            (machine.id, "maintenance", "active", "Repaired", finished),
        ]
    # Machines already in maintenance get the breakdown tickets they would have had.
    down_since = dict(
        db.session.execute(
            select(MachineStatusEvent.machine_id, func.max(MachineStatusEvent.occurred_at))
            .where(
                MachineStatusEvent.organization_id == company_id,
                MachineStatusEvent.to_status == "maintenance",
            )
            .group_by(MachineStatusEvent.machine_id)
        ).all()
    )
    for machine in machines:
        if machine.status != "maintenance":
            continue
        reported = down_since.get(machine.id) or (moment - timedelta(hours=3))
        reason = db.session.scalar(
            select(MachineStatusEvent.reason)
            .where(
                MachineStatusEvent.organization_id == company_id,
                MachineStatusEvent.machine_id == machine.id,
            )
            .order_by(MachineStatusEvent.occurred_at.desc())
            .limit(1)
        )
        tickets.append(
            dict(
                machine_id=machine.id,
                kind="breakdown",
                description=reason or "Out of service",
                reported_at=reported,
                started_at=min(reported + timedelta(minutes=20), moment),
                status="in_progress",
            )
        )
    tickets.sort(key=lambda t: t["reported_at"])
    for number, values in enumerate(tickets, 1):
        db.session.add(
            MaintenanceTicket(
                organization_id=company_id,
                number=f"MT-{number:05d}",
                reported_by_id=member.id,
                closed_by_id=member.id if values["status"] == "closed" else None,
                **values,
            )
        )
    for machine_id, before, after, reason, at in events:
        db.session.add(
            MachineStatusEvent(
                organization_id=company_id,
                machine_id=machine_id,
                from_status=before,
                to_status=after,
                reason=reason,
                actor_id=member.id,
                occurred_at=at,
            )
        )
    db.session.flush()
    audit(
        company_id,
        "factory.demo_maintenance_seeded",
        "maintenance_tickets",
        None,
        {"count": len(tickets)},
    )
    return [
        f"Maintenance: {len(plans)} preventive plans, {len(tickets)} fictional tickets "
        f"({len(BREAKDOWNS)} past breakdowns, open tickets for machines already down)."
    ]


# ---------- Step 8a: fictional line quality checks ----------

# Lines whose end-line quality is poor in the fictional history (defects per 100 checked).
QUALITY_FORM = {"QIE2-L03": 11, "PARK-L06": 6}
DEMO_DEFECTS = ("skip_stitch", "open_seam", "puckering", "uneven_hem", "needle_hole", "oil_stain")


def seed_quality(organization, member, today=None):
    """End-line checks every hour and in-line checks every other hour, once."""
    from app.models.factory import (
        BulletinOperation,
        LineCheckDefect,
        LineQualityCheck,
        OutputLog,
        ProductionOrder,
    )

    company_id = organization.id
    if db.session.scalar(
        select(LineQualityCheck.id).where(LineQualityCheck.organization_id == company_id)
    ):
        return []
    logs = db.session.scalars(
        select(OutputLog).where(
            OutputLog.organization_id == company_id, OutputLog.corrects_id.is_(None)
        )
    ).all()
    if not logs:
        return []
    orders = {
        o.id: o
        for o in db.session.scalars(
            select(ProductionOrder).where(ProductionOrder.organization_id == company_id)
        )
    }
    operations = {}
    for op in db.session.scalars(
        select(BulletinOperation)
        .where(BulletinOperation.organization_id == company_id)
        .order_by(BulletinOperation.sequence)
    ):
        operations.setdefault(op.bulletin_id, []).append(op)
    codes = {
        w.id: w.code
        for w in db.session.scalars(
            select(WorkCenter).where(WorkCenter.organization_id == company_id)
        )
    }
    checks = defects_total = 0
    for log in logs:
        code = codes.get(log.work_center_id, "")
        rate = QUALITY_FORM.get(code, 3 + (log.hour + len(code)) % 3)
        ops = operations.get(orders[log.production_order_id].bulletin_id, [])
        for stage, pieces in (("endline", 30), ("inline", 15)):
            if stage == "inline" and log.hour % 2:
                continue
            found = max(0, round(pieces * rate / 100 + ((log.hour * 7) % 3 - 1) * 0.4))
            rows = []
            if found:
                first = found - found // 3
                for index, count in enumerate((first, found - first)):
                    if count <= 0:
                        continue
                    op = ops[(log.hour + index * 3) % len(ops)] if ops else None
                    rows.append(
                        (
                            DEMO_DEFECTS[(log.hour + index + len(code)) % len(DEMO_DEFECTS)],
                            op,
                            count,
                        )
                    )
            if len({(c, o.id if o else None) for c, o, _ in rows}) != len(rows):
                rows = rows[:1]
            check = LineQualityCheck(
                organization_id=company_id,
                work_center_id=log.work_center_id,
                production_order_id=log.production_order_id,
                day=log.day,
                hour=log.hour,
                stage=stage,
                pieces_checked=pieces,
                defective_pieces=max(0, sum(c for *_, c in rows) - (1 if found > 3 else 0)),
                defects=sum(c for *_, c in rows),
                recorded_by_id=member.id,
                recorded_at=log.recorded_at,
            )
            db.session.add(check)
            db.session.flush()
            for defect_code, op, count in rows:
                db.session.add(
                    LineCheckDefect(
                        organization_id=company_id,
                        check_id=check.id,
                        defect_code=defect_code,
                        bulletin_operation_id=op.id if op else None,
                        count=count,
                    )
                )
            checks += 1
            defects_total += check.defects
    db.session.flush()
    audit(company_id, "factory.demo_quality_seeded", "line_quality_checks", None, {"count": checks})
    return [f"Line quality: {checks} fictional checks with {defects_total} defects recorded."]


# ---------- Step 8b: fictional yarn-to-carton trace chain ----------

SPINNER = ("SSM", "Sutlej Spinning Mills (demo)")
YARN_LOTS = (("YRN-2611-A", "SSM-77A1", "1500"), ("YRN-2611-B", "SSM-77B4", "1500"))


def seed_trace(organization, member):
    """Receive yarn, record it on rolls, post fabric, lays and packing, ship one carton lot and
    open a draft investigation on a yarn lot, all through the ordinary posting services."""
    from app.models.factory import DyeBatch, KnitRoll, ProductionOrder, Style
    from app.models.master import Lot, Partner, PartnerRoleAssignment
    from app.services import factory_trace, recall
    from app.services import operations as op
    from app.services.business import DomainError

    company_id = organization.id
    if db.session.scalar(
        select(Lot.id).where(Lot.organization_id == company_id, Lot.lot_code == YARN_LOTS[0][0])
    ):
        return []
    master = factory_trace.ensure_master(company_id)
    yarn_variant = factory_trace.variant(
        company_id, "YARN-30S-CMB", "30/1 combed cotton yarn", "component", master.kg
    )
    spinner = db.session.scalar(
        select(Partner).where(Partner.organization_id == company_id, Partner.code == SPINNER[0])
    )
    if spinner is None:
        spinner = Partner(organization_id=company_id, code=SPINNER[0], name=SPINNER[1])
        db.session.add(spinner)
        db.session.flush()
        db.session.add(
            PartnerRoleAssignment(
                organization_id=company_id, partner_id=spinner.id, role_code="supplier"
            )
        )
    lots = []
    for code, spinner_lot, _ in YARN_LOTS:
        lot = Lot(
            organization_id=company_id,
            lot_code=code,
            supplier_lot_code=spinner_lot,
            variant_id=yarn_variant.id,
            supplier_id=spinner.id,
        )
        db.session.add(lot)
        lots.append(lot)
    db.session.commit()
    report = []
    purchase = op.create_document(
        company_id,
        "purchase-orders",
        {
            "reference": "PO-YARN-2611",
            "supplier_id": spinner.id,
            "delivery_site_id": master.site.id,
        },
    )
    line = op.add_line(
        company_id,
        "purchase-orders",
        purchase.id,
        {"variant_id": yarn_variant.id, "quantity": str(sum(int(kg) for *_, kg in YARN_LOTS))},
    )
    op.post_document(company_id, "purchase-orders", purchase.id, "demo-yarn-po")
    receipt = op.create_document(
        company_id,
        "receipts",
        {
            "reference": "GR-YARN-2611",
            "supplier_id": spinner.id,
            "warehouse_id": master.warehouse.id,
        },
    )
    for lot, (_, _, kg) in zip(lots, YARN_LOTS, strict=True):
        op.add_line(
            company_id,
            "receipts",
            receipt.id,
            {
                "purchase_order_line_id": line.id,
                "lot_id": lot.id,
                "location_id": master.location.id,
                "quantity": kg,
            },
        )
    op.post_document(company_id, "receipts", receipt.id, "demo-yarn-receipt")
    report.append(f"Yarn: {len(lots)} lots received from the fictional spinner into factory WIP.")

    # Every demo roll was knitted from one of the two yarn lots.
    rolls = db.session.scalars(
        select(KnitRoll)
        .where(KnitRoll.organization_id == company_id)
        .order_by(KnitRoll.roll_number)
    ).all()
    for index, roll in enumerate(rolls):
        roll.yarn_lot_id = lots[0].id if index % 12 < 6 else lots[1].id
    db.session.commit()

    batches = db.session.scalars(
        select(DyeBatch).where(DyeBatch.organization_id == company_id, DyeBatch.status == "passed")
    ).all()
    for batch in batches:
        lot = factory_trace.post_batch(company_id, batch.id)
        report.append(f"Fabric {lot.lot_code} posted from batch {batch.batch_number}.")
    orders = {
        o.id: o
        for o in db.session.scalars(
            select(ProductionOrder).where(ProductionOrder.organization_id == company_id)
        )
    }
    traced = None
    for batch in batches:
        order = orders.get(batch.production_order_id)
        if order is None:
            continue
        try:
            factory_trace.post_lays(company_id, order.id)
            factory_trace.post_packing(company_id, order.id)
            traced = traced or order
            report.append(f"{order.reference}: cut lays and packed garments posted.")
        except DomainError as exc:
            db.session.rollback()
            report.append(f"{order.reference}: {exc}")
    if traced is not None:
        chain = factory_trace.chain(company_id, traced.id)
        garment_lot, pieces = chain.garments[0]
        style = db.session.get(Style, traced.style_id)
        sale = op.create_document(
            company_id,
            "sales-orders",
            {
                "reference": f"SO-{traced.reference}",
                "customer_id": style.buyer_id,
                "destination": "Buyer distribution centre (fictional)",
            },
        )
        sale_line = op.add_line(
            company_id,
            "sales-orders",
            sale.id,
            {"variant_id": garment_lot.variant_id, "quantity": str(pieces)},
        )
        op.post_document(company_id, "sales-orders", sale.id, f"demo-so-{traced.reference}")
        shipment = op.create_document(
            company_id,
            "shipments",
            {
                "reference": f"SH-{traced.reference}-1",
                "sales_order_id": sale.id,
                "warehouse_id": master.warehouse.id,
                "tracking_reference": f"CTN-{traced.reference}-001..{max(1, pieces // 40):03d}",
            },
        )
        op.add_line(
            company_id,
            "shipments",
            shipment.id,
            {
                "sales_order_line_id": sale_line.id,
                "lot_id": garment_lot.id,
                "source_location_id": master.location.id,
                "quantity": str(pieces),
            },
        )
        op.post_document(company_id, "shipments", shipment.id, f"demo-ship-{traced.reference}")
        report.append(
            f"Shipment SH-{traced.reference}-1 dispatched: {pieces} pieces of {garment_lot.lot_code}."
        )
        case = recall.save_case(
            company_id,
            "RC-YARN-2611-A",
            "Yarn lot YRN-2611-A: spinner reports a failed restricted-substance test (fictional)",
            "The fictional spinner flagged lot SSM-77A1. Trace which fabric, garments and "
            "shipments contain it before deciding on any action.",
            "high",
        )
        recall.source(company_id, case.id, lots[0].id, "Reported by the spinner")
        report.append("Draft investigation RC-YARN-2611-A opened on yarn lot YRN-2611-A.")
    return report
