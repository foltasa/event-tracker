"""saved_events.kind column

Revision ID: 0005_saved_event_kind
Revises: 0004_appointments
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_saved_event_kind"
down_revision: Union[str, Sequence[str], None] = "0004_appointments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "saved_events",
        sa.Column("kind", sa.String(), nullable=False, server_default="saved"),
    )


def downgrade() -> None:
    op.drop_column("saved_events", "kind")
