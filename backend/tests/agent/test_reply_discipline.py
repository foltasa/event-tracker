"""Regression suite for the 2026-06-18 punk-concert failure.

The bad reply pasted a long markdown blob of scraped venue program content into
the assistant message. The defenses against that failure mode are:
  1. web_search snippets are plain-text, capped at 160 chars (no markdown to paste).
  2. ingest_event_from_url returns a small dict (no raw page text to paste).
  3. Per-turn budgets stop runaway loops.
  4. The prompt's answering rule binds the final reply to search_events output.

This test exercises 1-3 directly (the structural defenses) and 4 indirectly
(it would have to be re-asserted in an LLM-level integration test, which is
deferred). The point is: even a maximally undisciplined model cannot pull
markdown program-card text out of any tool response after these changes.
"""
from unittest.mock import patch

import pytest

from app.agent import turn_budget
from app.agent.schemas import ToolError


HAFENKLANG_BAD_PAYLOAD = (
    "[![Foto - Event - O.R.B + Pult]"
    "(https://www.hafenklang.com/wp-content/themes/bgtoolbox/images/px.png)]"
    "(/programm?cpnr=69652)\n\n"
    "Sa 11.07.26\n\nGoldener Salon\n\nKonzert\n\n"
    "[O.R.B + Support: Pult](/programm?cpnr=69652)\n\n"
) * 20  # imitate the dump scale


def setup_function():
    turn_budget._reset()


def test_web_search_strips_hafenklang_dump_to_plain_text():
    from app.agent.tools import web_search
    fake_hits = [
        {"url": "https://hafenklang.com/programm", "title": "Programm",
         "content": HAFENKLANG_BAD_PAYLOAD},
    ]
    with patch("app.agent.tools.web_research_client.search", return_value=fake_hits):
        out = web_search.invoke({"query": "punk Hamburg 2026-06-19"})
    assert len(out) == 1
    snippet = out[0]["content"]
    assert len(snippet) <= 160
    assert "![Foto" not in snippet
    assert "wp-content" not in snippet
    assert "<" not in snippet
    assert "\n" not in snippet


def test_ingest_tool_does_not_return_raw_text(db_session, monkeypatch):
    """The tool surface must only return the count dict — never the raw HTML
    text that web_research_client.extract produces internally."""
    from app.agent.tools import ingest_event_from_url

    monkeypatch.setattr("app.agent.tools.SessionLocal", lambda: db_session)
    fake_report = {"ingested": 0, "updated": 0, "skipped": 0, "event_ids": []}
    with patch("app.agent.tools.web_research_ingest.ingest_event_from_url", return_value=fake_report):
        out = ingest_event_from_url.invoke({"url": "https://hafenklang.com/programm"})
    assert set(out.keys()) == {"ingested", "updated", "skipped", "event_ids"}
    assert isinstance(out["ingested"], int)
    # Belt-and-braces: nothing in the returned shape carries free-form text.
    for v in out.values():
        if isinstance(v, str):
            pytest.fail(f"Unexpected free-form string in ingest output: {v!r}")


def test_web_search_loop_terminates_at_budget():
    """A model that keeps calling web_search hoping for better results will hit
    the budget and start receiving ToolError instead of more Tavily traffic."""
    from app.agent.tools import web_search

    turn_budget.set_turn_budget(web_search=4, ingest=6)
    with patch("app.agent.tools.web_research_client.search", return_value=[]):
        for _ in range(4):
            web_search.invoke({"query": "q"})
        with pytest.raises(ToolError, match="web_search budget exhausted"):
            web_search.invoke({"query": "q"})
