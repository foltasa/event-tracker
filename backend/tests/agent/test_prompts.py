def test_conversational_prompt_includes_web_search_section_when_key_set(monkeypatch):
    monkeypatch.setattr("app.agent.prompts.settings.tavily_api_key", "tvly-test")
    # Re-import to re-evaluate; or call the builder directly.
    from app.agent.prompts import build_conversational_prompt
    out = build_conversational_prompt(
        today="2026-06-18", interests="theater", about_me="", facts_md="", taste_summary="",
    )
    assert "web_search" in out
    assert "AGGREGATOR-FIRST" in out
    assert "Max 4 web_search calls" in out


def test_conversational_prompt_omits_web_search_section_when_key_missing(monkeypatch):
    monkeypatch.setattr("app.agent.prompts.settings.tavily_api_key", None)
    from app.agent.prompts import build_conversational_prompt
    out = build_conversational_prompt(
        today="2026-06-18", interests="theater", about_me="", facts_md="", taste_summary="",
    )
    assert "web_search" not in out
    assert "AGGREGATOR-FIRST" not in out
