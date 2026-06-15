"""user memory blobs

Revision ID: 0003_user_memory_blobs
Revises: 0002_user_taste_fields
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_user_memory_blobs"
down_revision: Union[str, Sequence[str], None] = "0002_user_taste_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("facts_md", sa.String(), nullable=False, server_default=""),
    )
    op.drop_column("users", "taste_summary_dirty")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_summary_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_column("users", "facts_md")
