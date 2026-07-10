"""taste per category

Revision ID: 0010_taste_per_category
Revises: 0009_ingestion_state_circuit_breaker
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_taste_per_category"
down_revision: Union[str, Sequence[str], None] = "0009_ingestion_state_circuit_breaker"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_centroids", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column("taste_facets", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column("active_categories", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "active_categories")
    op.drop_column("users", "taste_facets")
    op.drop_column("users", "taste_centroids")
