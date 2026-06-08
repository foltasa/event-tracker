from sqlalchemy import text

from app.db.base import Base
from app.db.session import SessionLocal, engine


def test_engine_is_sqlite_by_default():
    assert engine.url.get_backend_name() == "sqlite"


def test_session_executes_simple_query():
    with SessionLocal() as session:
        result = session.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_base_metadata_is_empty_initially():
    # No models registered yet — sanity check that Base wires up.
    assert Base.metadata.tables == {}
