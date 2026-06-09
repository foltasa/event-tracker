"""Test-suite-wide fixtures for ingestion tests.

Auto-mocks `chroma_upsert_events` so that the no-longer-stub `embed_new_events`
doesn't hit real Chroma / OpenAI during scheduler tests. Tests that want to
verify the upsert call (Task 5's new test) explicitly patch the same name in
their own scope - that takes precedence.
"""
import pytest


@pytest.fixture(autouse=True)
def _no_real_chroma(monkeypatch):
    """Default-mock Chroma upsert so generic run_ingestion tests stay hermetic."""
    monkeypatch.setattr("app.ingestion.scheduler.chroma_upsert_events", lambda payload: None)
    yield
