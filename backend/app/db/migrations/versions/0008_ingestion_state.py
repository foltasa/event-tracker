"""Add ingestion_state table for scraper cursors.

Revision ID: 0008_ingestion_state
Revises: 0007_categories_v2
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0008_ingestion_state"
down_revision: Union[str, Sequence[str], None] = "0007_categories_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_state",
        sa.Column("source", sa.String(), primary_key=True),
        sa.Column("last_seen_lastmod", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("ingestion_state")
