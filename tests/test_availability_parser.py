from datetime import date
from pathlib import Path

import pytest

from app.services.availability_parser import (
    AvailabilityParser,
    AvailabilityParsingError,
)


FIXTURE = Path(__file__).parent / "fixtures" / "available_page.html"


def test_parser_finds_only_unbooked_and_unblocked_dates():
    snapshot = AvailabilityParser().parse(
        FIXTURE.read_text(encoding="utf-8"), "https://example.test/booking"
    )

    assert snapshot.service_active is True
    assert snapshot.candidate_dates == [
        date(2026, 8, 11),
        date(2026, 8, 12),
        date(2026, 8, 13),
        date(2026, 8, 14),
    ]
    assert snapshot.available_dates == [date(2026, 8, 13), date(2026, 8, 14)]
    assert snapshot.availability_key


def test_parser_treats_explicitly_inactive_service_as_valid_closed_state():
    snapshot = AvailabilityParser().parse(
        "<html>இந்த ஆன்லைன் சேவையை தற்பொழுது கோயில் செயல்படுத்தவில்லை</html>",
        "https://example.test/booking",
    )
    assert snapshot.service_active is False
    assert snapshot.available_dates == []
    assert snapshot.availability_key == ""


def test_parser_rejects_unknown_markup_instead_of_reporting_false_closure():
    with pytest.raises(AvailabilityParsingError):
        AvailabilityParser().parse(
            "<html><h1>Temporary maintenance page</h1></html>",
            "https://example.test/booking",
        )


def test_parser_rejects_service_page_without_calendar_arrays():
    with pytest.raises(AvailabilityParsingError):
        AvailabilityParser().parse(
            "<html>63716 சுவாமி அம்மன் சிறப்பு அபிஷேகம்</html>",
            "https://example.test/booking",
        )

