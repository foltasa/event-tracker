"""Build the LangGraph agent (a single compiled graph reused for all requests)."""
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.llm import build_llm
from app.agent.tools import select_tools
from app.config import settings

# Process-wide connection for the checkpointer. SqliteSaver.from_conn_string
# wraps the connection in a contextmanager that closes on GC — using it via
# __enter__() leaks the close path and corrupted earlier builds. Owning the
# connection at module scope keeps it alive for the process lifetime.
_checkpointer_conn: sqlite3.Connection | None = None


def _get_checkpointer() -> SqliteSaver:
    global _checkpointer_conn
    if _checkpointer_conn is None:
        _checkpointer_conn = sqlite3.connect(
            settings.checkpointer_path, check_same_thread=False
        )
    return SqliteSaver(_checkpointer_conn)


def build_agent(tools_enabled: list[str] | None = None):
    """Compile a ReAct agent. Reused across requests; per-request state is
    keyed by thread_id passed at invocation time."""
    llm = build_llm()
    tools = select_tools(tools_enabled)
    return create_react_agent(model=llm, tools=tools, checkpointer=_get_checkpointer())
