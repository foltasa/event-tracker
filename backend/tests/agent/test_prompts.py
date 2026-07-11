def test_conversational_prompt_includes_web_search_section_when_enabled(monkeypatch):
    monkeypatch.setattr("app.agent.prompts.settings.web_search_enabled", True)
    # Re-import to re-evaluate; or call the builder directly.
    from app.agent.prompts import build_conversational_prompt
    out = build_conversational_prompt(
        today="2026-06-18", about_me="", taste_prose="",
    )
    assert "web_search" in out
    assert "AGGREGATOR-FIRST" in out
    assert "Max 4 web_search calls" in out


def test_conversational_prompt_omits_web_search_section_when_disabled(monkeypatch):
    monkeypatch.setattr("app.agent.prompts.settings.web_search_enabled", False)
    from app.agent.prompts import build_conversational_prompt
    out = build_conversational_prompt(
        today="2026-06-18", about_me="", taste_prose="",
    )
    assert "web_search" not in out
    assert "AGGREGATOR-FIRST" not in out


def test_conversational_prompt_includes_answering_rule():
    from app.agent.prompts import CONVERSATIONAL_PROMPT
    assert "only mention events that were returned" in CONVERSATIONAL_PROMPT
    assert "[event:ID]" in CONVERSATIONAL_PROMPT
    assert "do not paste" in CONVERSATIONAL_PROMPT.lower() or "never paste" in CONVERSATIONAL_PROMPT.lower()


def test_web_search_strategy_warns_against_retrying_empty_ingest(monkeypatch):
    monkeypatch.setattr("app.agent.prompts.settings.web_search_enabled", True)
    from app.agent.prompts import build_conversational_prompt
    out = build_conversational_prompt(
        today="2026-06-18", about_me="", taste_prose="",
    )
    assert "ingested=0" in out
    assert "do not retry" in out.lower()


def test_conversational_prompt_new_placeholders():
    from app.agent.prompts import CONVERSATIONAL_PROMPT
    for token in ("{about_me}", "{taste_prose}", "{today}"):
        assert token in CONVERSATIONAL_PROMPT, f"missing placeholder: {token}"
    for token in ("{interests}", "{facts_md}", "{taste_summary}"):
        assert token not in CONVERSATIONAL_PROMPT, f"legacy placeholder must be removed: {token}"


def test_curation_prompt_new_placeholders():
    from app.agent.prompts import CURATION_PROMPT

    required = [
        "{about_me}", "{active_categories}", "{inactive_categories}",
        "{taste_prose}", "{event_pool}",
    ]
    for token in required:
        assert token in CURATION_PROMPT, f"missing placeholder: {token}"

    for token in ("{interests}", "{taste_summary}", "{taste_facets_json}", "{disliked_json}"):
        assert token not in CURATION_PROMPT, f"legacy placeholder must be removed: {token}"


def test_curation_prompt_formats_cleanly():
    from app.agent.prompts import CURATION_PROMPT
    # Guard against dangling {something} placeholders left in the template.
    CURATION_PROMPT.format(
        about_me="x", active_categories="y", inactive_categories="z",
        taste_prose="p", event_pool="[]",
    )
