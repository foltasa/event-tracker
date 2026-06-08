"""Shared pytest fixtures for the backend test suite."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db import models  # noqa: F401 - imports all models for metadata registration


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite DB with all current model tables created."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session, future=True)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
