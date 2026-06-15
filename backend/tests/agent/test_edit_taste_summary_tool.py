import pytest

from app.agent import tools
from app.agent.schemas import ToolError
from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], facts_md="", taste_summary="")
    db_session.add(u)
    db_session.commit()
    return u


def test_edit_taste_summary_appends(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    result = tools.edit_taste_summary.invoke({"old_string": "", "new_string": "Leans indie."})

    assert result == {"status": "ok", "lines": 1}
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.taste_summary == "Leans indie."


def test_edit_taste_summary_uses_20_line_cap(db_session, user, monkeypatch):
    user.taste_summary = "\n".join(str(i) for i in range(19))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    # Append 2 lines onto 19 lines -> 21 > 20 -> reject
    with pytest.raises(ToolError, match="would exceed cap: 21 lines vs. limit 20"):
        tools.edit_taste_summary.invoke({"old_string": "", "new_string": "x\ny"})


def test_edit_taste_summary_replaces(db_session, user, monkeypatch):
    user.taste_summary = "loves jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_taste_summary.invoke({"old_string": "jazz", "new_string": "indie"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.taste_summary == "loves indie"


def test_edit_taste_summary_user_missing_raises(db_session, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "nope")

    with pytest.raises(ToolError, match="user not found"):
        tools.edit_taste_summary.invoke({"old_string": "", "new_string": "x"})
