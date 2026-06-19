"""Per-turn budget for outbound web tools.

The chat route calls `set_turn_budget(...)` at the start of each user turn.
Tools call `consume_web_search()` / `consume_ingest()` as their first line and
raise ToolError when the counter hits zero. This is hard server-side enforcement
on top of the prompt-level advisory in `_WEB_SEARCH_STRATEGY`.

Hard default budgets (used when no `set_turn_budget` has been called this turn,
e.g. during unit tests) match the prompt advisory: 4 web_search, 6 ingest.

Implementation note: counters live in a mutable list inside each ContextVar
because LangChain's `BaseTool.run` executes the tool body inside a copied
contextvars context (`context.run(self._run, ...)`). Calling `ContextVar.set()`
inside the tool would only mutate the copied context — the outer caller's
counter would never decrement, breaking enforcement across multiple tool
calls in the same turn. Holding the counter in a shared mutable object means
both contexts reference the same cell, so `_remaining[0] -= 1` is visible
everywhere within the chat turn.
"""
from contextvars import ContextVar

from app.agent.schemas import ToolError

_DEFAULT_WEB_SEARCH = 4
_DEFAULT_INGEST = 6

# Each ContextVar holds a single-element list whose [0] entry is the live counter.
# See module docstring for why this indirection is required.
_web_search_remaining: ContextVar[list[int]] = ContextVar(
    "web_search_remaining", default=[_DEFAULT_WEB_SEARCH]
)
_ingest_remaining: ContextVar[list[int]] = ContextVar(
    "ingest_remaining", default=[_DEFAULT_INGEST]
)


def set_turn_budget(*, web_search: int, ingest: int) -> None:
    """Reset the per-turn counters. Call once at the start of each agent turn.

    Installs a fresh mutable cell in the current context so that the new turn's
    counter is fully isolated from any prior turn's cell (which may still be
    referenced by an in-flight task)."""
    _web_search_remaining.set([web_search])
    _ingest_remaining.set([ingest])


def consume_web_search() -> None:
    cell = _web_search_remaining.get()
    if cell[0] <= 0:
        raise ToolError("web_search budget exhausted for this turn")
    cell[0] -= 1


def consume_ingest() -> None:
    cell = _ingest_remaining.get()
    if cell[0] <= 0:
        raise ToolError("ingest budget exhausted for this turn")
    cell[0] -= 1


def _reset() -> None:
    """Test helper — restore defaults between tests."""
    _web_search_remaining.set([_DEFAULT_WEB_SEARCH])
    _ingest_remaining.set([_DEFAULT_INGEST])
