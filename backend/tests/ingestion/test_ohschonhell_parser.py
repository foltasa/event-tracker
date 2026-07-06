import re
from pathlib import Path

from app.ingestion.scrapers.ohschonhell import parse_event

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _read(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8", errors="replace")


def test_parses_full_event_all_fields():
    parsed = parse_event(_read("ohschonhell_event_full.html"))
    assert parsed is not None
    assert parsed["event_id"].isdigit()
    assert parsed["name"]
    assert parsed["date"]  # ISO date string YYYY-MM-DD
    assert parsed["time"]  # HH:MM string
    assert parsed["description"]
    assert parsed["venue_name"]
    assert parsed["street"]
    assert parsed["postal_code"]
    assert parsed["city"]


def test_parses_minimal_event_short_description():
    parsed = parse_event(_read("ohschonhell_event_minimal.html"))
    assert parsed is not None
    # Minimal events have very short descriptions but MUST still parse.
    assert parsed["event_id"]
    assert parsed["name"]
    assert parsed["date"]
    assert parsed["venue_name"]


def test_missing_time_returns_none():
    # Take the full page and strip the time from the display text.
    html = _read("ohschonhell_event_full.html")
    # Remove any 'HH:MM' substrings inside itemprop=startDate elements.
    stripped = re.sub(
        r'(itemprop=startDate[^>]*>)[^<]*',
        r'\1' + "no-time-here",
        html,
    )
    assert parse_event(stripped) is None


def test_missing_event_id_returns_none():
    html = _read("ohschonhell_event_full.html")
    stripped = re.sub(r"eventId=\d+", "eventId=", html)
    assert parse_event(stripped) is None


def test_umlauts_decoded_correctly():
    parsed = parse_event(_read("ohschonhell_event_full.html"))
    assert parsed is not None
    combined = " ".join([parsed["name"], parsed["description"] or "", parsed["venue_name"] or ""])
    assert "�" not in combined  # no U+FFFD replacement char


def test_street_excludes_nested_postal_and_city():
    """ohschonhell nests postalCode/addressLocality spans inside the street
    paragraph. The parser must extract only the street text, not the
    concatenation of the entire address."""
    parsed = parse_event(_read("ohschonhell_event_full.html"))
    assert parsed is not None
    assert parsed["postal_code"] not in parsed["street"]
    assert parsed["city"] not in parsed["street"]
