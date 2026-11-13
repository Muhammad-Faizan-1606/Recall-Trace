"""Display helpers shared by templates: readable quantities and status tags."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from markupsafe import Markup

# Tag colours follow physical quality tags: green for done or released, amber for
# waiting or held, red for failed or severe, grey for everything neutral.
GOOD = {
    "accepted",
    "acknowledged",
    "active",
    "approved",
    "clean",
    "completed",
    "delivered",
    "local_written",
    "pass",
    "posted",
    "published",
    "ready",
    "released",
    "resolved",
    "sent",
    "verified",
}
WAITING = {
    "ambiguous",
    "held",
    "hold",
    "issued",
    "maintenance",
    "medium",
    "open",
    "pending",
    "pending_closure",
    "queued",
    "quarantined",
    "submitted",
    "unavailable",
}
BAD = {
    "critical",
    "error",
    "expired",
    "fail",
    "failed",
    "high",
    "infected",
    "decommissioned",
    "rejected",
    "revoked",
}


def quantity_text(value):
    """Decimal quantities without storage padding: 50.000000 -> 50, 2.500 -> 2.5."""
    if isinstance(value, bool) or value is None:
        return value
    try:
        number = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, TypeError, ValueError):
        return value
    if not number.is_finite():
        return value
    normalized = number.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, ",f")


def status_tag(value):
    """A small coloured tag; the text stays the readable status itself."""
    if value is None or value == "":
        return ""
    key = str(value).strip().lower()
    tone = "good" if key in GOOD else "waiting" if key in WAITING else "bad" if key in BAD else ""
    # Keep the stored wording; CSS capitalises the first letter for display.
    text = str(value).strip().replace("_", " ")
    tone_class = f" tag-{tone}" if tone else ""
    # Markup.format escapes every inserted value; the template string is a constant.
    return Markup('<span class="tag{}">{}</span>').format(tone_class, text)


def when_text(value):
    """'4 Nov 2026, 22:06 UTC' instead of '2026-11-04 22:06:37.221724+00:00'."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return f"{value.day} {value:%b %Y, %H:%M} UTC"


def day_text(value):
    """'4 Nov 2026' for date-only columns."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return f"{value.day} {value:%b %Y}"


def clock_text(value):
    """'22:06' (UTC) for times shown under a day heading."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return f"{value:%H:%M}"


def today_text():
    """'Tuesday, 11 November 2026' for the top bar (UTC date)."""
    today = datetime.now(UTC)
    return f"{today:%A}, {today.day} {today:%B %Y}"


def register(app):
    app.add_template_filter(quantity_text, "qty")
    app.add_template_filter(status_tag, "tag")
    app.add_template_filter(when_text, "when")
    app.add_template_filter(day_text, "day")
    app.add_template_filter(clock_text, "clock")
    app.add_template_global(today_text, "today_text")
