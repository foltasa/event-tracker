from datetime import datetime
from zoneinfo import ZoneInfo

from app.ingestion.categorize_prompts import SYSTEM_PROMPT, render_user_prompt
from app.ingestion.normalize import NormalizedEvent

_BERLIN = ZoneInfo("Europe/Berlin")


def _ev(**overrides) -> NormalizedEvent:
    base = dict(
        external_id="ev1",
        source="theater_hamburg",
        title="The 27 Club",
        description="A Tribute to Jimi Hendrix, Amy Winehouse, Janis Joplin...",
        start_datetime=datetime(2026, 7, 4, 20, 0, tzinfo=_BERLIN),
        venue_name="St. Pauli Theater",
        category="concerts",
        tags=["weitere konzerte"],
        is_free=False,
        source_url="https://example.com/the-27-club",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_system_prompt_lists_all_categories():
    for cat in ("concerts", "party", "comedy", "theater", "arts", "literature", "film", "family", "food", "sports", "outdoor", "other"):
        assert cat in SYSTEM_PROMPT
    assert "unknown" in SYSTEM_PROMPT


def test_system_prompt_distinguishes_categories():
    """Should explicitly cover concerts/party split, comedy as its own bucket, and family precedence."""
    lowered = SYSTEM_PROMPT.lower()
    # concerts vs party split is called out
    assert "concerts" in lowered
    assert "party" in lowered
    # comedy is called out as its own category
    assert "comedy" in lowered
    # family precedence references children / Kinder
    assert "family" in lowered
    assert "children" in lowered or "kinder" in lowered


def test_render_user_prompt_includes_all_signals():
    prompt = render_user_prompt(_ev())
    assert "The 27 Club" in prompt
    assert "St. Pauli Theater" in prompt
    assert "weitere konzerte" in prompt
    assert "theater_hamburg" in prompt
    # Provider hint appears verbatim
    assert "concerts" in prompt


def test_render_user_prompt_handles_missing_optional_fields():
    prompt = render_user_prompt(_ev(description=None, venue_name=None, tags=[]))
    assert "The 27 Club" in prompt
    # No exception, no "None" string leaked
    assert "None" not in prompt


def test_render_user_prompt_truncates_long_description():
    long_desc = "x" * 5000
    prompt = render_user_prompt(_ev(description=long_desc))
    # Body of prompt shouldn't contain the full 5000-char blob
    assert len(prompt) < 3000
