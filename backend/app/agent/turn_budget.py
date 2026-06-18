"""Per-turn budget for outbound web tools.

The chat route calls `set_turn_budget(...)` at the start of each user turn.
Tools call `consume_web_search()` / `consume_ingest()` as their first line and
raise ToolError when the counter hits zero. This is hard server-side enforcement
on top of the prompt-level advisory in `_WEB_SEARCH_STRATEGY`.

Hard default budgets (used when no `set_turn_budget` has been called this turn,
e.g. during unit tests) match the prompt advisory: 4 web_search, 6 ingest.
"""
from contextvars import ContextVar

from app.agent.schemas import ToolError

_DEFAULT_WEB_SEARCH = 4
_DEFAULT_INGEST = 6

_web_search_remaining: ContextVar[int] = ContextVar("web_search_remaining", default=_DEFAULT_WEB_SEARCH)
_ingest_remaining: ContextVar[int] = ContextVar("ingest_remaining", default=_DEFAULT_INGEST)


def set_turn_budget(*, web_search: int, ingest: int) -> None:
    """Reset the per-turn counters. Call once at the start of each agent turn."""
    _web_search_remaining.set(web_search)
    _ingest_remaining.set(ingest)


def consume_web_search() -> None:
    n = _web_search_remaining.get()
    if n <= 0:
        raise ToolError("web_search budget exhausted for this turn")
    _web_search_remaining.set(n - 1)


def consume_ingest() -> None:
    n = _ingest_remaining.get()
    if n <= 0:
        raise ToolError("ingest budget exhausted for this turn")
    _ingest_remaining.set(n - 1)


def _reset() -> None:
    """Test helper — restore defaults between tests."""
    _web_search_remaining.set(_DEFAULT_WEB_SEARCH)
    _ingest_remaining.set(_DEFAULT_INGEST)
