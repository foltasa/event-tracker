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

from app.agent.memory import get_current_user_id, record_message
from app.agent.prompts import build_conversational_prompt
from app.agent.runtime import heal_orphan_tool_calls
from app.agent.turn_budget import set_turn_budget
from app.api.deps import DbSession
from app.db.models import ChatMessage, User
from app.schemas.chat import ChatMessageResponse, ChatRequest
from app.schemas.common import ChatTokenUsage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_agent_singleton = None


async def get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        from app.agent.runtime import build_async_agent
        _agent_singleton = await build_async_agent()
    return _agent_singleton


async def _stream_chat(payload: ChatRequest, db) -> AsyncIterator[dict]:
    user_id = get_current_user_id()
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        yield {"event": "message", "data": json.dumps({"type": "error", "message": "user not onboarded"})}
        return

    record_message(db, payload.session_id, user_id, "user", payload.message)
    db.commit()

    # Reset per-turn web-tool budget so a prior turn's exhaustion does not leak.
    set_turn_budget(web_search=4, ingest=6)

    system = build_conversational_prompt(
        today=date.today().isoformat(),
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        facts_md=user.facts_md or "(empty)",
        taste_summary=user.taste_summary or "(empty)",
    )

    assistant_buffer: list[str] = []
    # stream_mode="messages" yields one AIMessageChunk per LLM token. Tool
    # calls are assembled incrementally — the name lands on the first chunk
    # and arg fragments dribble across continuation chunks. Dedupe by id so
    # we emit exactly one tool_start per logical call.
    seen_tool_ids: set[str] = set()
    try:
        agent = await get_agent()
        healed = await heal_orphan_tool_calls(agent, payload.session_id)
        if healed:
            logger.warning(
                "chat: healed %d orphan tool_call(s) left by a prior interrupted turn (session=%s)",
                healed, payload.session_id,
            )
        async for message, _meta in agent.astream(
            {"messages": [SystemMessage(content=system), HumanMessage(content=payload.message)]},
            config={"configurable": {"thread_id": payload.session_id}},
            stream_mode="messages",
        ):
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
                    name = call.get("name") or ""
                    call_id = call.get("id") or ""
                    if not name or not call_id or call_id in seen_tool_ids:
                        continue
                    seen_tool_ids.add(call_id)
                    yield {
                        "event": "message",
                        "data": json.dumps({"type": "tool_start", "tool_name": name}),
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


@router.get("/chat/history", response_model=list[ChatMessageResponse])
def chat_history(session_id: str, db: DbSession) -> list[ChatMessageResponse]:
    """Return the persisted turns for one session, in order."""
    user_id = get_current_user_id()
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id, ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .all()
    )
    out: list[ChatMessageResponse] = []
    for r in rows:
        usage = None
        if r.role == "assistant":
            usage = ChatTokenUsage(
                input_tokens=r.input_tokens or 0,
                output_tokens=r.output_tokens or 0,
                estimated_cost_usd=r.estimated_cost_usd or 0.0,
            )
        out.append(ChatMessageResponse(
            id=r.id,
            session_id=r.session_id,
            role=r.role,
            content=r.content,
            tool_name=r.tool_name,
            token_usage=usage,
            created_at=r.created_at,
        ))
    return out
