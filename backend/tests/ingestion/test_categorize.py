from datetime import datetime
from zoneinfo import ZoneInfo

from app.ingestion.categorize import content_hash
from app.ingestion.normalize import NormalizedEvent

_BERLIN = ZoneInfo("Europe/Berlin")


def _ev(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="ev1",
        source="test",
        title="Title",
        description="Some description",
        start_datetime=datetime(2026, 7, 1, 20, 0, tzinfo=_BERLIN),
        venue_name="Venue X",
        category="music",
        tags=["a", "b"],
        is_free=False,
        source_url="https://example.com/ev1",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_hash_is_stable_across_calls():
    a = content_hash(_ev())
    b = content_hash(_ev())
    assert a == b
    assert len(a) == 64  # sha256 hex


def test_hash_ignores_non_semantic_fields():
    """external_id, start_datetime, price, image_url must not affect hash."""
    a = content_hash(_ev())
    b = content_hash(_ev(
        external_id="ev1_other",
        start_datetime=datetime(2027, 1, 1, tzinfo=_BERLIN),
        price_min=99.0,
        price_max=199.0,
        image_url="https://cdn.example.com/x.jpg",
        source_url="https://example.com/other",
    ))
    assert a == b


def test_hash_changes_with_title():
    assert content_hash(_ev(title="A")) != content_hash(_ev(title="B"))


def test_hash_changes_with_description():
    assert content_hash(_ev(description="one")) != content_hash(_ev(description="two"))


def test_hash_changes_with_venue():
    assert content_hash(_ev(venue_name="Elbphilharmonie")) != content_hash(_ev(venue_name="Ohnsorg-Theater"))


def test_hash_changes_with_provider_category_hint():
    assert content_hash(_ev(category="music")) != content_hash(_ev(category="theater"))


def test_hash_ignores_tag_order():
    assert content_hash(_ev(tags=["a", "b"])) == content_hash(_ev(tags=["b", "a"]))


def test_hash_strips_html_from_description():
    """Provider descriptions come pre-stripped in the scraper, but if raw
    HTML sneaks in the hash should not flip on formatting changes."""
    plain = content_hash(_ev(description="Hello world"))
    html = content_hash(_ev(description="<p>Hello world</p>"))
    assert plain == html


import pytest
from pydantic import ValidationError

from app.ingestion.categorize import CategoryDecision


def test_category_decision_accepts_all_enum_values():
    for cat in ["music", "arts", "food", "sports", "tech", "outdoor", "film", "theater", "family", "other"]:
        d = CategoryDecision(category=cat)
        assert d.category == cat


def test_category_decision_accepts_unknown():
    d = CategoryDecision(category="unknown")
    assert d.category == "unknown"


def test_category_decision_rejects_invalid():
    with pytest.raises(ValidationError):
        CategoryDecision(category="music_theater")


from app.ingestion.categorize import CategoryCache


def test_cache_miss_returns_none(db_session):
    cache = CategoryCache(db_session, model_name="google/gemini-2.0-flash")
    assert cache.get("nonexistent") is None


def test_cache_write_then_read(db_session):
    cache = CategoryCache(db_session, model_name="google/gemini-2.0-flash")
    cache.set("hash123", "theater")
    db_session.commit()
    assert cache.get("hash123") == "theater"


def test_cache_set_is_idempotent(db_session):
    """Second write with same hash is a no-op (INSERT OR IGNORE semantics)."""
    cache = CategoryCache(db_session, model_name="m")
    cache.set("h", "theater")
    db_session.commit()
    cache.set("h", "music")  # should not raise, should not overwrite
    db_session.commit()
    assert cache.get("h") == "theater"


def test_cache_stores_unknown(db_session):
    cache = CategoryCache(db_session, model_name="m")
    cache.set("h_unk", "unknown")
    db_session.commit()
    assert cache.get("h_unk") == "unknown"
