"""Build the LangGraph agent (a single compiled graph reused for all requests)."""
import sqlite3

import aiosqlite
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import ToolNode, create_react_agent

from app.agent.llm import build_llm
from app.agent.tools import select_tools
from app.config import settings

_ORPHAN_TOOL_MESSAGE = (
    "Tool execution was interrupted before completion; treat as no result."
)


def _handle_tool_errors(e: Exception) -> str:
    """Convert any tool exception into a string so ToolNode emits a ToolMessage
    instead of re-raising.

    langgraph 1.x ships a default handler that only catches ToolInvocationError
    and re-raises everything else — including our ToolError. When the graph
    crashes mid-step, the AIMessage(tool_calls=...) is already checkpointed but
    no matching ToolMessage gets appended, so every subsequent turn fails with
    INVALID_CHAT_HISTORY. This handler catches all exceptions and lets the
    agent decide what to do with the resulting error ToolMessage."""
    return f"Tool error: {e}"

# Process-wide connection for the checkpointer. SqliteSaver.from_conn_string
# wraps the connection in a contextmanager that closes on GC — using it via
# __enter__() leaks the close path and corrupted earlier builds. Owning the
# connection at module scope keeps it alive for the process lifetime.
_checkpointer_conn: sqlite3.Connection | None = None
_async_checkpointer_conn: aiosqlite.Connection | None = None


def _get_checkpointer() -> SqliteSaver:
    global _checkpointer_conn
    if _checkpointer_conn is None:
        _checkpointer_conn = sqlite3.connect(
            settings.checkpointer_path, check_same_thread=False
        )
    return SqliteSaver(_checkpointer_conn)


async def _get_async_checkpointer() -> AsyncSqliteSaver:
    global _async_checkpointer_conn
    if _async_checkpointer_conn is None:
        _async_checkpointer_conn = await aiosqlite.connect(
            settings.checkpointer_path, check_same_thread=False
        )
    return AsyncSqliteSaver(_async_checkpointer_conn)


def build_agent(tools_enabled: list[str] | None = None):
    """Compile a ReAct agent. Reused across requests; per-request state is
    keyed by thread_id passed at invocation time."""
    llm = build_llm()
    tools = select_tools(tools_enabled)
    tool_node = ToolNode(tools, handle_tool_errors=_handle_tool_errors)
    return create_react_agent(model=llm, tools=tool_node, checkpointer=_get_checkpointer())


async def build_async_agent(tools_enabled: list[str] | None = None):
    """Compile a ReAct agent with an async-compatible checkpointer. Required
    for callers that drive the agent via `astream` / `ainvoke` — SqliteSaver
    rejects async checkpoint calls."""
    llm = build_llm()
    tools = select_tools(tools_enabled)
    tool_node = ToolNode(tools, handle_tool_errors=_handle_tool_errors)
    return create_react_agent(model=llm, tools=tool_node, checkpointer=await _get_async_checkpointer())


async def heal_orphan_tool_calls(agent, thread_id: str) -> int:
    """Inject synthetic ToolMessages for any orphan tool_calls the prior turn
    left in the checkpoint. Returns the number of healed calls.

    SqliteSaver checkpoints between the LLM step and the ToolNode step. If the
    ToolNode is interrupted from outside the tool body — asyncio cancellation
    on client disconnect, watchfiles reload, process kill — the AIMessage
    persists with no matching ToolMessages and every subsequent turn dies
    with INVALID_CHAT_HISTORY. Run this once at the start of each turn.

    Only the *latest* AIMessage with tool_calls is inspected: any earlier such
    message is by construction inside a valid prefix (otherwise prior turns
    would already have failed), and re-patching it could shadow real tool
    results."""
    config = {"configurable": {"thread_id": thread_id}}
    state = await agent.aget_state(config)
    messages = state.values.get("messages", []) if state and state.values else []
    if not messages:
        return 0

    answered: set[str] = {
        m.tool_call_id for m in messages
        if isinstance(m, ToolMessage) and m.tool_call_id
    }

    synthetic: list[ToolMessage] = []
    for m in reversed(messages):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for call in m.tool_calls:
                cid = call.get("id")
                if cid and cid not in answered:
                    synthetic.append(ToolMessage(
                        content=_ORPHAN_TOOL_MESSAGE,
                        tool_call_id=cid,
                        name=call.get("name", "unknown"),
                    ))
            break

    if synthetic:
        await agent.aupdate_state(config, {"messages": synthetic})
    return len(synthetic)

async def clear_session_checkpoint(thread_id: str) -> None:
    """Wipe every persisted checkpoint for a LangGraph thread so the next turn
    starts with an empty message history.

    Falls back to a `RemoveMessage`-based reset if the checkpointer doesn't
    expose `adelete_thread` (older langgraph versions)."""
    from langchain_core.messages import RemoveMessage

    checkpointer = await _get_async_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    delete_thread = getattr(checkpointer, "adelete_thread", None)
    if callable(delete_thread):
        await delete_thread(thread_id)
        return

    agent = await build_async_agent()
    snapshot = await agent.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot and snapshot.values else []
    if not messages:
        return
    await agent.aupdate_state(
        config,
        {"messages": [RemoveMessage(id=m.id) for m in messages if getattr(m, "id", None)]},
    )