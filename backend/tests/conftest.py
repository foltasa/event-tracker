"""Shared pytest fixtures for the backend test suite."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db import models  # noqa: F401 - imports all models for metadata registration


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite DB with all current model tables created.

    Uses StaticPool + check_same_thread=False so the same connection can be
    shared between the test thread and FastAPI's TestClient thread.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db_session, monkeypatch):
    """TestClient with the app's get_db dependency overridden to the in-memory session."""
    from app.main import app
    from app.api.deps import get_db

    def override_db():
        try:
            yield db_session
        finally:
            pass  # fixture controls cleanup

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
