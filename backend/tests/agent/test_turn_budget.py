import pytest

from app.agent.schemas import ToolError
from app.agent import turn_budget


def setup_function():
    turn_budget._reset()


def test_consume_without_set_uses_default_budget():
    """Outside a chat turn (no set_turn_budget called), the consumers behave
    permissively up to their hard defaults so unit tests don't have to set the
    budget every time."""
    for _ in range(4):
        turn_budget.consume_web_search()
    with pytest.raises(ToolError) as ei:
        turn_budget.consume_web_search()
    assert "web_search" in str(ei.value)


def test_set_turn_budget_resets_counters():
    turn_budget.set_turn_budget(web_search=2, ingest=1)
    turn_budget.consume_web_search()
    turn_budget.consume_web_search()
    with pytest.raises(ToolError):
        turn_budget.consume_web_search()

    turn_budget.set_turn_budget(web_search=2, ingest=1)
    turn_budget.consume_web_search()  # fresh budget, should not raise


def test_ingest_budget_independent_of_web_search():
    turn_budget.set_turn_budget(web_search=4, ingest=2)
    turn_budget.consume_ingest()
    turn_budget.consume_ingest()
    with pytest.raises(ToolError) as ei:
        turn_budget.consume_ingest()
    assert "ingest" in str(ei.value)
    # web_search budget unaffected
    turn_budget.consume_web_search()


def test_error_message_names_the_tool():
    turn_budget.set_turn_budget(web_search=0, ingest=0)
    with pytest.raises(ToolError, match="web_search budget exhausted"):
        turn_budget.consume_web_search()
    with pytest.raises(ToolError, match="ingest budget exhausted"):
        turn_budget.consume_ingest()
