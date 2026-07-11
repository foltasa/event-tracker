from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import LLMDigestPick, LLMDigestResponse
from app.api.routes_digest import _parse_picks_fallback
from app.db.models import DigestCache, Event, User


@pytest.fixture
def setup(db_session):
    db_session.add(User(
        id="local",
        interest_tags=["music"],
        taste_summary="loves jazz",
        facts_md="",
        active_categories=["concerts"],
    ))
    for i in range(5):
        db_session.add(Event(
            id=f"e{i}", external_id=f"x{i}", source="eventbrite",
            title=f"Event {i}", description=f"desc {i}", category="concerts",
            source_url="http://x",
            start_datetime=datetime(2026, 6, 10 + i, tzinfo=timezone.utc),
        ))
    db_session.commit()


def _fake_hits(event_ids):
    return [SimpleNamespace(event_id=eid, similarity_score=0.9) for eid in event_ids]


def _fake_agent_with_picks(picks):
    agent = MagicMock()
    response = LLMDigestResponse(picks=[LLMDigestPick(event_id=p, justification="because " + p + " is great") for p in picks])
    agent.invoke.return_value = {"structured_response": response}
    return agent


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.retrieval.get_category_candidates",
       side_effect=lambda *a, **k: _fake_hits(["e0", "e1", "e2", "e3", "e4"]))
@patch("app.api.routes_digest.get_agent")
def test_digest_generates_on_miss_and_caches(mock_agent, _retr, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    r = client.get("/digest")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-06-09"
    assert len(body["picks"]) == 3
    assert body["picks"][0]["event"]["id"] == "e0"
    assert body["is_cached"] is False
    assert db_session.query(DigestCache).filter_by(user_id="local").count() == 1


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.retrieval.get_category_candidates",
       side_effect=lambda *a, **k: _fake_hits(["e0", "e1", "e2", "e3", "e4"]))
@patch("app.api.routes_digest.get_agent")
def test_digest_returns_cache_without_invoking_llm(mock_agent, _retr, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")  # populate cache
    mock_agent.reset_mock()
    r = client.get("/digest")
    body = r.json()
    assert body["is_cached"] is True
    mock_agent.return_value.invoke.assert_not_called()


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.retrieval.get_category_candidates",
       side_effect=lambda *a, **k: _fake_hits(["e0", "e1", "e2", "e3", "e4"]))
@patch("app.api.routes_digest.get_agent")
def test_digest_refresh_overwrites_cache(mock_agent, _retr, _today, client, setup, db_session):
    mock_agent.return_value = _fake_agent_with_picks(["e0", "e1", "e2"])
    client.get("/digest")

    mock_agent.return_value = _fake_agent_with_picks(["e3", "e4", "e0"])
    r = client.post("/digest/refresh")
    body = r.json()
    assert {p["event"]["id"] for p in body["picks"]} == {"e3", "e4", "e0"}


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.retrieval.get_category_candidates",
       side_effect=lambda *a, **k: _fake_hits(["e0", "e1", "e2", "e3", "e4"]))
@patch("app.api.routes_digest.get_agent")
def test_digest_502_when_agent_returns_too_few_picks(mock_agent, _retr, _today, client, setup):
    agent = MagicMock()
    agent.invoke.return_value = {"structured_response": None}
    mock_agent.return_value = agent
    r = client.get("/digest")
    assert r.status_code == 502


def _msg(content):
    return SimpleNamespace(content=content)


def test_fallback_parses_code_fenced_json_with_id_remap():
    content = (
        '```json\n'
        '{"picks": ['
        '{"id": "e0", "justification": "this one looks great"},'
        '{"id": "e1", "justification": "this one looks great"},'
        '{"id": "e2", "justification": "this one looks great"}'
        ']}\n'
        '```'
    )
    parsed = _parse_picks_fallback([_msg(content)])
    assert parsed is not None
    assert [p.event_id for p in parsed.picks] == ["e0", "e1", "e2"]


def test_fallback_parses_fenced_json_with_prose_prefix():
    """DeepSeek prefixes its fenced JSON with explanatory prose."""
    content = (
        "Since you have no saved preferences yet, I've picked a diverse set.\n\n"
        '```json\n'
        '{"picks": ['
        '{"id": "e0", "justification": "great choice for jazz fans"},'
        '{"id": "e1", "justification": "great choice for jazz fans"},'
        '{"id": "e2", "justification": "great choice for jazz fans"}'
        ']}\n'
        '```'
    )
    parsed = _parse_picks_fallback([_msg(content)])
    assert parsed is not None
    assert [p.event_id for p in parsed.picks] == ["e0", "e1", "e2"]


def test_fallback_parses_bare_json():
    content = (
        '{"picks": ['
        '{"event_id": "e0", "justification": "this one looks great"},'
        '{"event_id": "e1", "justification": "this one looks great"},'
        '{"event_id": "e2", "justification": "this one looks great"}'
        ']}'
    )
    parsed = _parse_picks_fallback([_msg(content)])
    assert parsed is not None
    assert len(parsed.picks) == 3


def test_fallback_returns_none_on_garbage():
    assert _parse_picks_fallback([_msg("I cannot help with that.")]) is None
    assert _parse_picks_fallback([]) is None
    assert _parse_picks_fallback([_msg(None)]) is None


def test_fallback_returns_none_on_too_few_picks():
    content = '{"picks": [{"event_id": "e0", "justification": "only one pick here"}]}'
    assert _parse_picks_fallback([_msg(content)]) is None


@patch("app.api.routes_digest._get_today", return_value=date(2026, 6, 9))
@patch("app.api.routes_digest.retrieval.get_category_candidates",
       side_effect=lambda *a, **k: _fake_hits(["e0", "e1", "e2", "e3", "e4"]))
@patch("app.api.routes_digest.get_agent")
def test_digest_recovers_via_fallback_when_structured_response_missing(
    mock_agent, _retr, _today, client, setup, db_session
):
    agent = MagicMock()
    fenced_json = (
        '```json\n'
        '{"picks": ['
        '{"id": "e0", "justification": "great choice for jazz fans"},'
        '{"id": "e1", "justification": "great choice for jazz fans"},'
        '{"id": "e2", "justification": "great choice for jazz fans"}'
        ']}\n'
        '```'
    )
    agent.invoke.return_value = {
        "structured_response": None,
        "messages": [SimpleNamespace(content=fenced_json)],
    }
    mock_agent.return_value = agent

    r = client.get("/digest")
    assert r.status_code == 200
    body = r.json()
    assert {p["event"]["id"] for p in body["picks"]} == {"e0", "e1", "e2"}


def test_digest_agent_tool_set_excludes_edit_tools():
    """The digest agent must be read-only with respect to long-term memory:
    its tool list must NOT contain edit_facts or edit_taste_summary, matching
    the read-only marker in the curation prompt."""
    from app.agent.tools import select_tools
    from app.api.routes_digest import DIGEST_TOOLS

    digest_tools = select_tools(DIGEST_TOOLS)
    names = {t.name for t in digest_tools}
    assert "edit_facts" not in names
    assert "edit_taste_summary" not in names
    assert {
        "search_events",
        "get_recommendations",
        "record_feedback",
        "save_to_calendar",
        "get_calendar",
        "get_user_profile",
        "update_user_profile",
    } <= names


# ---------------------------------------------------------------------------
# Task 14: Per-category retrieval + 409 hints for missing/empty active_categories
# ---------------------------------------------------------------------------


def _seed_events(db):
    for i, cat in enumerate(["concerts", "party", "theater"]):
        db.add(Event(
            id=f"e{i}", external_id=f"e{i}", source="test",
            title=f"{cat} event", description="d",
            start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
            category=cat, tags=[], source_url="http://e", raw_data={},
        ))


def test_digest_pool_is_built_per_active_category(client, db_session):
    _seed_events(db_session)
    db_session.add(User(
        id="local",
        active_categories=["concerts", "party"],
        taste_centroids={"concerts": [1.0, 0.0], "party": [0.0, 1.0]},
    ))
    db_session.commit()

    called_categories: list[str] = []

    def fake_candidates(session, user, category, **kwargs):
        called_categories.append(category)
        return [type("H", (), {"event_id": f"e{['concerts','party','theater'].index(category)}", "similarity_score": 0.9})()]

    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {
        "structured_response": type("R", (), {"picks": [
            type("P", (), {"event_id": "e0", "justification": "great match"})(),
            type("P", (), {"event_id": "e1", "justification": "great match"})(),
            type("P", (), {"event_id": "e0", "justification": "again"})(),
        ]})(),
        "messages": [],
    }
    with patch("app.api.routes_digest.retrieval.get_category_candidates", side_effect=fake_candidates), \
         patch("app.api.routes_digest.get_agent", return_value=fake_agent):
        res = client.get("/digest")
    assert res.status_code == 200
    assert set(called_categories) == {"concerts", "party"}


def test_digest_returns_hint_when_no_active_categories(client, db_session):
    db_session.add(User(id="local", active_categories=[]))
    db_session.commit()
    res = client.get("/digest")
    assert res.status_code == 409
    assert "no_active_categories" in res.json().get("detail", "")


def test_digest_redirects_new_user(client, db_session):
    db_session.add(User(id="local"))  # active_categories = None
    db_session.commit()
    res = client.get("/digest")
    assert res.status_code == 409
    assert "about_me_required" in res.json().get("detail", "")


def test_format_taste_prose_dumps_active_categories_only():
    from app.agent.facets import format_taste_prose as _format_taste_prose

    user = User(
        id="local",
        active_categories=["concerts", "party"],
        taste_facets={
            "concerts": {"artists": {"Nils Frahm": 1.0}, "genres": {"indie": 1.0}, "venues": {}, "notes": "Piano over guitars"},
            "party":    {"venues":  {"Südpol": 1.0}},
            "theater":  {"venues":  {"Thalia": 1.0}},  # inactive → excluded
        },
    )
    prose = _format_taste_prose(user)
    assert "concerts" in prose
    assert "Nils Frahm" in prose
    assert "Piano over guitars" in prose
    assert "Südpol" in prose
    # Inactive-category facets must not leak in.
    assert "Thalia" not in prose


def test_format_taste_prose_handles_empty_active_categories():
    from app.agent.facets import format_taste_prose as _format_taste_prose
    assert _format_taste_prose(User(id="u", active_categories=[])) == "(no active categories)"


def test_format_taste_prose_marks_category_with_no_facets():
    from app.agent.facets import format_taste_prose as _format_taste_prose
    out = _format_taste_prose(User(id="u", active_categories=["concerts"], taste_facets={}))
    assert "(nothing listed)" in out


def test_format_taste_prose_ignores_non_string_notes():
    from app.agent.facets import format_taste_prose as _format_taste_prose
    out = _format_taste_prose(User(
        id="u", active_categories=["concerts"],
        taste_facets={"concerts": {"notes": 42}},
    ))
    assert "42" not in out
    assert "(nothing listed)" in out


def test_format_taste_prose_indents_multiline_notes():
    from app.agent.facets import format_taste_prose as _format_taste_prose
    out = _format_taste_prose(User(
        id="u", active_categories=["concerts"],
        taste_facets={"concerts": {"notes": "line 1\nline 2"}},
    ))
    # Continuation lines are indented so they visually belong under `notes:`.
    assert "notes: line 1\n      line 2" in out
