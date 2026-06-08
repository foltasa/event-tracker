from sqlalchemy import text

from app.db.base import Base
from app.db.session import SessionLocal, engine


def test_engine_is_sqlite_by_default():
    assert engine.url.get_backend_name() == "sqlite"


def test_session_executes_simple_query():
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_base_metadata_registers_models():
    # Importing models populates Base.metadata. Sanity check that the wiring works.
    # (Other test modules will have imported models already.)
    from app.db import models as _models  # noqa: F401
    assert set(Base.metadata.tables) >= {
        "users", "events", "feedback", "saved_events", "chat_messages", "digest_cache",
    }
