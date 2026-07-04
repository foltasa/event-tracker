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


from app.ingestion.categorize import LLMClassifier, refine_category


class _FakeClassifier:
    """Test double that returns preconfigured decisions or raises."""

    def __init__(self, decisions=None, exception=None, invalid=False):
        self.decisions = decisions or []
        self.exception = exception
        self.invalid = invalid
        self.calls = []

    def classify(self, event) -> CategoryDecision:
        self.calls.append(event.title)
        if self.exception:
            raise self.exception
        if self.invalid:
            # Simulate what happens when structured output validation succeeds
            # but the caller decides the payload is unusable — we raise here.
            raise ValueError("invalid enum value")
        if not self.decisions:
            raise AssertionError("Fake had no decision configured")
        return self.decisions.pop(0)


def test_refine_cache_miss_calls_llm_and_writes_cache(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(decisions=[CategoryDecision(category="theater")])

    result = refine_category(ev, cache, llm)

    assert result == "theater"
    assert len(llm.calls) == 1
    db_session.commit()
    assert cache.get(content_hash(ev)) == "theater"


def test_refine_cache_hit_skips_llm(db_session):
    ev = _ev()
    cache = CategoryCache(db_session, model_name="m")
    cache.set(content_hash(ev), "arts")
    db_session.commit()
    llm = _FakeClassifier()  # no decisions configured

    result = refine_category(ev, cache, llm)

    assert result == "arts"
    assert llm.calls == []  # LLM was not called


def test_refine_llm_error_falls_back_to_provider_hint(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(exception=RuntimeError("openrouter down"))

    result = refine_category(ev, cache, llm)

    assert result == "music"  # fallback to event.category
    db_session.commit()
    # No cache write on error — next run should retry
    assert cache.get(content_hash(ev)) is None


def test_refine_llm_unknown_falls_back_but_caches(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(decisions=[CategoryDecision(category="unknown")])

    result = refine_category(ev, cache, llm)

    assert result == "music"  # fallback to event.category
    db_session.commit()
    # Cache write with 'unknown' sentinel — avoids re-asking a model that already said "unsure"
    assert cache.get(content_hash(ev)) == "unknown"


def test_refine_unknown_cache_hit_still_uses_provider_hint(db_session):
    ev = _ev()  # provider hint: "music"
    cache = CategoryCache(db_session, model_name="m")
    cache.set(content_hash(ev), "unknown")
    db_session.commit()
    llm = _FakeClassifier()  # not called

    result = refine_category(ev, cache, llm)

    assert result == "music"  # cached 'unknown' still resolves to event.category
    assert llm.calls == []


def test_refine_llm_invalid_response_falls_back(db_session):
    ev = _ev()
    cache = CategoryCache(db_session, model_name="m")
    llm = _FakeClassifier(invalid=True)

    result = refine_category(ev, cache, llm)

    assert result == "music"
    db_session.commit()
    assert cache.get(content_hash(ev)) is None  # invalid = same as error, no cache write


from unittest.mock import MagicMock

from app.ingestion.categorize import LangchainClassifier, build_categorization_llm


def test_langchain_classifier_calls_structured_llm_and_returns_decision():
    """Structured output invocation → CategoryDecision passthrough."""
    fake_structured = MagicMock()
    fake_structured.invoke.return_value = CategoryDecision(category="theater")

    fake_llm = MagicMock()
    fake_llm.with_structured_output.return_value = fake_structured

    classifier = LangchainClassifier(llm=fake_llm)
    result = classifier.classify(_ev())

    assert isinstance(result, CategoryDecision)
    assert result.category == "theater"
    fake_llm.with_structured_output.assert_called_once_with(CategoryDecision)
    invoke_arg = fake_structured.invoke.call_args[0][0]
    assert isinstance(invoke_arg, list)
    assert len(invoke_arg) == 2  # system + user
    assert "classify" in invoke_arg[0].content.lower() or "categor" in invoke_arg[0].content.lower()
    assert _ev().title in invoke_arg[1].content


def test_build_categorization_llm_uses_settings(monkeypatch):
    """Factory should read categorization_model and use OpenRouter base URL."""
    from app.ingestion import categorize as cat_module

    captured = {}
    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(cat_module, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(cat_module.settings, "categorization_model", "test/model")
    monkeypatch.setattr(cat_module.settings, "categorization_timeout_seconds", 7.5)
    monkeypatch.setattr(cat_module.settings, "openrouter_api_key", "sk-test")

    build_categorization_llm()

    assert captured["model"] == "test/model"
    assert captured["api_key"] == "sk-test"
    assert captured["temperature"] == 0
    assert captured["timeout"] == 7.5
    assert "openrouter.ai" in captured["base_url"]
