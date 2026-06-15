import pytest

from app.agent import tools
from app.agent.schemas import ToolError
from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], facts_md="")
    db_session.add(u)
    db_session.commit()
    return u


def test_edit_facts_appends_when_old_empty(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    result = tools.edit_facts.invoke({"old_string": "", "new_string": "User lives in Eimsbüttel"})

    assert result == {"status": "ok", "lines": 1}
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "User lives in Eimsbüttel"


def test_edit_facts_replaces_unique_match(db_session, user, monkeypatch):
    user.facts_md = "lives in Eimsbüttel\nlikes jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_facts.invoke({"old_string": "likes jazz", "new_string": "likes indie"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "lives in Eimsbüttel\nlikes indie"


def test_edit_facts_removes_line(db_session, user, monkeypatch):
    user.facts_md = "a\nb\nc"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_facts.invoke({"old_string": "b\n", "new_string": ""})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "a\nc"


def test_edit_facts_both_empty_raises_toolerror(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="no-op"):
        tools.edit_facts.invoke({"old_string": "", "new_string": ""})


def test_edit_facts_cap_overflow_raises_toolerror_and_does_not_persist(db_session, user, monkeypatch):
    user.facts_md = "\n".join(str(i) for i in range(199))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="would exceed cap"):
        tools.edit_facts.invoke({"old_string": "", "new_string": "x\ny"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "\n".join(str(i) for i in range(199))


def test_edit_facts_ambiguous_raises_toolerror(db_session, user, monkeypatch):
    user.facts_md = "a\na\nb"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="matches 2 locations"):
        tools.edit_facts.invoke({"old_string": "a", "new_string": "c"})


def test_edit_facts_user_missing_raises_toolerror(db_session, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "nope")

    with pytest.raises(ToolError, match="user not found"):
        tools.edit_facts.invoke({"old_string": "", "new_string": "anything"})
