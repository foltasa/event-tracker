"""Categories schema v2: purge LLM cache + reclassify all events.

Revision ID: 0007_categories_v2
Revises: 0006_event_category_cache
Create Date: 2026-07-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.orm import Session


revision: str = "0007_categories_v2"
down_revision: Union[str, Sequence[str], None] = "0006_event_category_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Lazy imports keep `alembic heads/history/current` cheap.
    from app.config import settings
    from app.db.migrations.migration_0007_helpers import purge_and_reclassify
    from app.ingestion.categorize import LangchainClassifier

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        classifier = LangchainClassifier()
        purge_and_reclassify(session, classifier=classifier, model_name=settings.categorization_model)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    """Best-effort rollback. Cache is dropped; new v2 categories that don't
    exist in v1 are heuristically mapped back so existing SELECTs still work
    on the downgraded schema."""
    from sqlalchemy import text
    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        session.execute(text("DELETE FROM event_category_cache"))
        session.execute(text("UPDATE events SET category='music' WHERE category IN ('concerts','party')"))
        session.execute(text("UPDATE events SET category='theater' WHERE category='comedy'"))
        session.execute(text("UPDATE events SET category='arts' WHERE category='literature'"))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
