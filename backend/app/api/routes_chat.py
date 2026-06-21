"""POST /chat — SSE streaming endpoint backed by the LangGraph agent.

Streams `token`, `tool_start`, `tool_end`, `done`, and `error` events as
sse-starlette SSE frames. Mirrors the user prompt and final assistant text
to the `chat_messages` table for history.
"""
import json
import logging
import re
import uuid
from datetime import date
from typing import AsyncIterator

from fastapi import APIRouter
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from sse_starlette.sse import EventSourceResponse

from app.agent.memory import get_current_user_id, record_message
from app.agent.prompts import build_conversational_prompt
from app.agent.runtime import clear_session_checkpoint, heal_orphan_tool_calls
from app.agent.turn_budget import set_turn_budget
from app.api.deps import DbSession
from app.db.models import ChatMessage, Event, SavedEvent, User
from app.schemas.chat import ChatMessageResponse, ChatRequest
from app.schemas.common import ChatTokenUsage

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_EVENT_REF_RE = re.compile(r"\[event:([^\]]+)\]")


def _persist_recommendations(db, user_id: str, full_text: str) -> None:
    """Scrape [event:ID] refs from the assistant's final answer and insert
    a recommendation row for each. Idempotent: skips events already in the
    calendar (saved or recommendation), skips unknown IDs, no-ops when the
    user disabled the feature."""
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        return
    if not (user.settings or {}).get("auto_recommendations_enabled", True):
        return
    ids = list(dict.fromkeys(_EVENT_REF_RE.findall(full_text)))
    if not ids:
        return
    existing_event_ids = {
        row.id for row in db.query(Event.id).filter(Event.id.in_(ids)).all()
    }
    already_in_calendar = {
        row.event_id for row in db.query(SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id, SavedEvent.event_id.in_(ids))
        .all()
    }
    added = False
    for eid in ids:
        if eid not in existing_event_ids or eid in already_in_calendar:
            continue
        db.add(SavedEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=eid,
            kind="recommendation",
        ))
        added = True
    if added:
        db.commit()


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

    # Per-message-id buffer so the agent's internal monologue (the AIMessage
    # whose content accompanies a tool_call) never leaks into the user-facing
    # reply. OpenAI-style streaming emits content tokens BEFORE the tool_call
    # chunks, so a per-chunk "does this chunk have tool_calls?" check would be
    # too late. Instead we accumulate content per id and decide whether to
    # flush only once we have enough signal: a finish_reason marker, the
    # presence of tool_call_chunks/tool_calls anywhere on the message, or
    # end-of-stream as a safety fallback. Final answers stream as one larger
    # token event rather than token-by-token — UX downgrade, but a correctness
    # win versus glued-together messages like "...generell gibtLeider...".
    msg_buf: dict[str, str] = {}
    msg_intermediate: set[str] = set()
    msg_emitted: set[str] = set()

    def _finish_reason(m) -> str | None:
        meta = getattr(m, "response_metadata", None)
        if isinstance(meta, dict):
            return meta.get("finish_reason")
        return None

    def _has_tool_call_signal(m) -> bool:
        if getattr(m, "tool_calls", None):
            return True
        if getattr(m, "tool_call_chunks", None):
            return True
        return False

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

                msg_id = getattr(message, "id", None) or "_anon"

                if _has_tool_call_signal(message):
                    msg_intermediate.add(msg_id)
                    msg_buf.pop(msg_id, None)

                if (
                    msg_id not in msg_intermediate
                    and isinstance(message.content, str)
                    and message.content
                ):
                    msg_buf[msg_id] = msg_buf.get(msg_id, "") + message.content

                fr = _finish_reason(message)
                if fr in ("tool_calls", "function_call"):
                    msg_intermediate.add(msg_id)
                    msg_buf.pop(msg_id, None)
                elif fr == "stop":
                    buffered = msg_buf.pop(msg_id, "")
                    if buffered and msg_id not in msg_intermediate and msg_id not in msg_emitted:
                        assistant_buffer.append(buffered)
                        msg_emitted.add(msg_id)
                        yield {"event": "message", "data": json.dumps({"type": "token", "content": buffered})}
    except Exception as exc:
        logger.exception("chat stream failed")
        yield {"event": "message", "data": json.dumps({"type": "error", "message": f"agent error: {exc}"})}
        return

    # Safety net: flush any buffer whose owning message never carried a
    # finish_reason (mocks, providers that omit the field) and was not marked
    # intermediate. Discard intermediate buffers silently — they were the
    # agent's internal reasoning.
    for msg_id, buffered in msg_buf.items():
        if msg_id in msg_intermediate or msg_id in msg_emitted or not buffered:
            continue
        assistant_buffer.append(buffered)
        msg_emitted.add(msg_id)
        yield {"event": "message", "data": json.dumps({"type": "token", "content": buffered})}

    full_text = "".join(assistant_buffer)
    if full_text:
        record_message(db, payload.session_id, user_id, "assistant", full_text)
        db.commit()
        try:
            _persist_recommendations(db, user_id, full_text)
        except Exception:
            logger.exception("failed to persist recommendations")

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


@router.delete("/chat/history", status_code=204)
async def delete_chat_history(session_id: str, db: DbSession) -> None:
    """Wipe persisted chat for one session: ChatMessage rows + LangGraph checkpoint."""
    user_id = get_current_user_id()
    db.query(ChatMessage).filter(
        ChatMessage.user_id == user_id,
        ChatMessage.session_id == session_id,
    ).delete(synchronize_session=False)
    db.commit()
    await clear_session_checkpoint(session_id)
