from datetime import datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

BERLIN = timezone(timedelta(hours=2))  # CEST


def test_requires_title():
    from app.web_research.schemas import WebExtractedEvent
    with pytest.raises(ValidationError):
        WebExtractedEvent(
            start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
            source_url="https://example.com/e/1",
        )


def test_requires_start_datetime():
    from app.web_research.schemas import WebExtractedEvent
    with pytest.raises(ValidationError):
        WebExtractedEvent(title="Hamlet", source_url="https://example.com/e/1")


def test_requires_source_url():
    from app.web_research.schemas import WebExtractedEvent
    with pytest.raises(ValidationError):
        WebExtractedEvent(
            title="Hamlet",
            start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        )


def test_naive_datetime_is_stamped_europe_berlin():
    from app.web_research.schemas import WebExtractedEvent
    e = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30),  # naive
        source_url="https://example.com/e/1",
    )
    assert e.start_datetime.utcoffset() is not None
    # Tolerate either CEST (+02:00) or CET (+01:00) depending on DST in test env.
    assert e.start_datetime.utcoffset() in (timedelta(hours=1), timedelta(hours=2))


def test_optional_fields_default_to_none_or_empty():
    from app.web_research.schemas import WebExtractedEvent
    e = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://example.com/e/1",
    )
    assert e.category is None
    assert e.is_free is None
    assert e.venue_name is None
    assert e.tags == []


def test_mapping_fills_defaults():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://thalia-theater.de/spielplan/2026-06-19",
    )
    ne = map_to_normalized_event(we, input_url="https://thalia-theater.de/spielplan/2026-06-19")
    assert ne is not None
    assert ne.source == "web_search"
    assert ne.category == "other"
    assert ne.is_free is False
    assert ne.currency == "EUR"
    assert ne.raw_data == {}
    assert ne.external_id  # non-empty deterministic id


def test_mapping_normalises_unknown_category_to_other():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://thalia-theater.de/x",
        category="bogus-category",
    )
    ne = map_to_normalized_event(we, input_url="https://thalia-theater.de/x")
    assert ne is not None
    assert ne.category == "other"


def test_mapping_accepts_known_category():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://thalia-theater.de/x",
        category="theater",
    )
    ne = map_to_normalized_event(we, input_url="https://thalia-theater.de/x")
    assert ne is not None
    assert ne.category == "theater"


def test_mapping_external_id_is_deterministic():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    args = dict(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://thalia-theater.de/x",
    )
    a = map_to_normalized_event(WebExtractedEvent(**args), input_url=args["source_url"])
    b = map_to_normalized_event(WebExtractedEvent(**args), input_url=args["source_url"])
    assert a.external_id == b.external_id


def test_mapping_rejects_origin_mismatch():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://attacker.example/spoof",
    )
    ne = map_to_normalized_event(we, input_url="https://thalia-theater.de/x")
    assert ne is None


def test_origin_match_accepts_apex_vs_www():
    """www and apex must be treated as the same origin."""
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="O.R.B + Pult",
        start_datetime=datetime(2026, 7, 11, 21, 0, tzinfo=BERLIN),
        source_url="https://www.hafenklang.com/programm?cpnr=1",
    )
    ne = map_to_normalized_event(we, input_url="https://hafenklang.com/programm")
    assert ne is not None
    assert ne.title == "O.R.B + Pult"


def test_origin_match_rejects_different_apex():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Spoof",
        start_datetime=datetime(2026, 7, 11, 21, 0, tzinfo=BERLIN),
        source_url="https://evil.com/programm",
    )
    ne = map_to_normalized_event(we, input_url="https://hafenklang.com/programm")
    assert ne is None


def test_origin_match_rejects_non_http_scheme():
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="x",
        start_datetime=datetime(2026, 7, 11, 21, 0, tzinfo=BERLIN),
        source_url="mailto:tickets@hafenklang.com",
    )
    ne = map_to_normalized_event(we, input_url="https://hafenklang.com/programm")
    assert ne is None


def test_mapping_returns_none_on_normalized_event_validation_failure():
    """is_free=True with non-zero price violates NormalizedEvent._price_consistency
    and should yield None rather than crash."""
    from app.web_research.schemas import WebExtractedEvent, map_to_normalized_event
    we = WebExtractedEvent(
        title="Hamlet",
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url="https://thalia-theater.de/x",
        is_free=True,
        price_min=5.0,
    )
    ne = map_to_normalized_event(we, input_url="https://thalia-theater.de/x")
    assert ne is None
