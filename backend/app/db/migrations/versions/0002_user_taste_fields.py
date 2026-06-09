"""user taste fields

Revision ID: 0002_user_taste_fields
Revises: 0001_initial
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_user_taste_fields"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_summary_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "users",
        sa.Column("taste_centroid", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "taste_centroid")
    op.drop_column("users", "taste_summary_dirty")
