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
