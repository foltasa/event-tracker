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
        category="music",
        tags=["weitere konzerte"],
        is_free=False,
        source_url="https://example.com/the-27-club",
    )
    base.update(overrides)
    return NormalizedEvent(**base)


def test_system_prompt_lists_all_categories():
    for cat in ("music", "arts", "theater", "film", "family", "food", "sports", "tech", "outdoor", "other"):
        assert cat in SYSTEM_PROMPT
    assert "unknown" in SYSTEM_PROMPT


def test_system_prompt_distinguishes_theater_from_music():
    """Should explicitly cover tribute shows / musicals as theater."""
    lowered = SYSTEM_PROMPT.lower()
    assert "musical" in lowered or "tribute" in lowered
    assert "theater" in lowered
    assert "konzert" in lowered or "concert" in lowered


def test_render_user_prompt_includes_all_signals():
    prompt = render_user_prompt(_ev())
    assert "The 27 Club" in prompt
    assert "St. Pauli Theater" in prompt
    assert "weitere konzerte" in prompt
    assert "theater_hamburg" in prompt
    # Provider hint appears verbatim
    assert "music" in prompt


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
