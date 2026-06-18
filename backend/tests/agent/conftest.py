"""Shared fixtures for agent tests."""
from dataclasses import dataclass, field

import pytest


@dataclass
class FakeMessage:
    content: str


@dataclass
class FakeLLM:
    """Minimal stand-in that records calls and returns scripted responses."""
    responses: list[str] = field(default_factory=list)
    calls: list[list] = field(default_factory=list)

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        text = self.responses.pop(0) if self.responses else "ok"
        return FakeMessage(content=text)


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture(autouse=True)
def _reset_turn_budget():
    """Restore default web/ingest budgets before each agent test.

    The budget counter is held in a module-level mutable cell so that
    LangChain's per-call contextvars copy can still see decrements. That
    sharing means cross-test pollution unless every test starts from a
    fresh cell."""
    from app.agent import turn_budget
    turn_budget._reset()
    yield
    turn_budget._reset()
