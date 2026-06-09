"""POST /chat — SSE streaming endpoint backed by the LangGraph agent.

Streams `token`, `tool_start`, `tool_end`, `done`, and `error` events as
sse-starlette SSE frames. Mirrors the user prompt and final assistant text
to the `chat_messages` table for history.
"""
import json
import logging
from datetime import date
from typing import AsyncIterator

from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.memory import get_current_user_id, record_message, refresh_taste_summary
from app.agent.prompts import CONVERSATIONAL_PROMPT
from app.api.deps import DbSession
from app.db.models import User
from app.schemas.chat import ChatRequest
from app.schemas.common import ChatTokenUsage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_agent_singleton = None


def get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        from app.agent.runtime import build_agent
        _agent_singleton = build_agent()
    return _agent_singleton


async def _stream_chat(payload: ChatRequest, db) -> AsyncIterator[dict]:
    user_id = get_current_user_id()
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        yield {"event": "message", "data": json.dumps({"type": "error", "message": "user not onboarded"})}
        return

    refresh_taste_summary(db, user_id)
    db.commit()
    db.refresh(user)

    record_message(db, payload.session_id, user_id, "user", payload.message)
    db.commit()

    system = CONVERSATIONAL_PROMPT.format(
        today=date.today().isoformat(),
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        taste_summary=user.taste_summary or "(not yet generated)",
    )

    assistant_buffer: list[str] = []
    try:
        agent = get_agent()
        async for mode, item in agent.astream(
            {"messages": [SystemMessage(content=system), HumanMessage(content=payload.message)]},
            config={"configurable": {"thread_id": payload.session_id}},
            stream_mode="messages",
        ):
            if mode != "messages":
                continue
            message, _meta = item
            if isinstance(message, ToolMessage):
                status = "error" if str(message.content).lower().startswith("error") else "ok"
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "tool_end", "tool_name": message.name or "unknown", "status": status}),
                }
            elif isinstance(message, AIMessage):
                if isinstance(message.content, str) and message.content:
                    assistant_buffer.append(message.content)
                    yield {"event": "message", "data": json.dumps({"type": "token", "content": message.content})}
                for call in getattr(message, "tool_calls", []) or []:
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "tool_start", "tool_name": call["name"]}),
                    }
    except Exception as exc:
        logger.exception("chat stream failed")
        yield {"event": "message", "data": json.dumps({"type": "error", "message": f"agent error: {exc}"})}
        return

    full_text = "".join(assistant_buffer)
    if full_text:
        record_message(db, payload.session_id, user_id, "assistant", full_text)
        db.commit()

    yield {
        "event": "message",
        "data": json.dumps({
            "type": "done",
            "token_usage": ChatTokenUsage(input_tokens=0, output_tokens=0, estimated_cost_usd=0.0).model_dump(),
        }),
    }


@router.post("/chat")
async def chat(payload: ChatRequest, db: DbSession):
    return EventSourceResponse(_stream_chat(payload, db))
