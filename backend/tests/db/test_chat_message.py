from datetime import datetime, timezone

from app.db.models import chat_message as _cm, user as _user  # noqa: F401
from app.db.models.chat_message import ChatMessage
from app.db.models.user import User


def _seed(db_session):
    db_session.add(User(id="local", interest_tags=[], settings={}))
    db_session.commit()


def test_chat_message_user_role(db_session):
    _seed(db_session)
    m = ChatMessage(id="msg_1", user_id="local", session_id="sess_a", role="user", content="hi")
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.role == "user"
    assert m.tool_name is None
    assert m.input_tokens is None
    assert m.output_tokens is None
    assert m.estimated_cost_usd is None
    assert isinstance(m.created_at, datetime)


def test_chat_message_assistant_with_token_usage(db_session):
    _seed(db_session)
    m = ChatMessage(
        id="msg_2", user_id="local", session_id="sess_a", role="assistant",
        content="hello", input_tokens=420, output_tokens=88, estimated_cost_usd=0.0012,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.input_tokens == 420
    assert m.output_tokens == 88
    assert m.estimated_cost_usd == 0.0012


def test_chat_message_tool_role(db_session):
    _seed(db_session)
    m = ChatMessage(
        id="msg_3", user_id="local", session_id="sess_a", role="tool",
        content='{"events":[]}', tool_name="search_events",
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    assert m.tool_name == "search_events"
