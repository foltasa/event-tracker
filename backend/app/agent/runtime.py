"""Build the LangGraph agent (a single compiled graph reused for all requests)."""
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import create_react_agent

from app.agent.llm import build_llm
from app.agent.tools import select_tools
from app.config import settings


def build_agent(tools_enabled: list[str] | None = None):
    """Compile a ReAct agent. Reused across requests; per-request state is
    keyed by thread_id passed at invocation time."""
    llm = build_llm()
    tools = select_tools(tools_enabled)
    saver_ctx = SqliteSaver.from_conn_string(settings.checkpointer_path)
    checkpointer = saver_ctx.__enter__()
    # Note: The SqliteSaver context is kept open for the lifetime of the app.
    # FastAPI startup creates it; shutdown does not need to release it since
    # the process exits.
    return create_react_agent(model=llm, tools=tools, checkpointer=checkpointer)
