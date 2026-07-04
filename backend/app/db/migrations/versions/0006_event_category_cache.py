"""Add event_category_cache table and backfill categories via LLM.

Revision ID: 0006_event_category_cache
Revises: 0005_saved_event_kind
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session


revision: str = "0006_event_category_cache"
down_revision: Union[str, Sequence[str], None] = "0005_saved_event_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_category_cache",
        sa.Column("content_hash", sa.String(), primary_key=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )

    # Lazy imports: `LangchainClassifier` pulls in `langchain_openai`, which
    # is expensive and unnecessary for `alembic heads/history/current`.
    from app.config import settings
    from app.db.migrations.migration_0006_helpers import backfill_categories
    from app.ingestion.categorize import LangchainClassifier

    bind = op.get_bind()
    session = Session(bind=bind)
    try:
        classifier = LangchainClassifier()
        backfill_categories(session, classifier=classifier, model_name=settings.categorization_model)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def downgrade() -> None:
    op.drop_table("event_category_cache")
