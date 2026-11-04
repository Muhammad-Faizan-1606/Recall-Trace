"""Display helpers: quantities without storage padding, escaped status tags."""

from decimal import Decimal

import pytest

from app.presentation import quantity_text, status_tag


@pytest.fixture(autouse=True)
def records():
    # Pure formatting checks; no database fixture needed.
    yield


@pytest.mark.parametrize(
    "value,expected",
    [
        (Decimal("50.000000"), "50"),
        (Decimal("2.500"), "2.5"),
        (Decimal("0E-6"), "0"),
        (Decimal("-10.000000"), "-10"),
        (Decimal("12500.000000"), "12,500"),
        (Decimal("0.000125"), "0.000125"),
        (7, "7"),
    ],
)
def test_quantities_drop_storage_padding_only(value, expected):
    assert quantity_text(value) == expected


def test_non_numeric_values_pass_through():
    assert quantity_text(None) is None
    assert quantity_text("not a number") == "not a number"


def test_status_tags_keep_wording_choose_tone_and_escape():
    assert status_tag("approved") == '<span class="tag tag-good">approved</span>'
    assert status_tag("pending_closure") == '<span class="tag tag-waiting">pending closure</span>'
    assert status_tag("critical") == '<span class="tag tag-bad">critical</span>'
    assert status_tag("draft") == '<span class="tag">draft</span>'
    assert "<script>" not in status_tag("<script>")
    assert status_tag(None) == ""
