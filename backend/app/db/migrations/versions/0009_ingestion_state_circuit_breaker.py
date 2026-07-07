"""Add circuit-breaker columns to ingestion_state; relax last_seen_lastmod.

Revision ID: 0009_ingestion_state_circuit_breaker
Revises: 0008_ingestion_state
Create Date: 2026-07-07 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009_ingestion_state_circuit_breaker"
down_revision: Union[str, Sequence[str], None] = "0008_ingestion_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ingestion_state") as batch:
        batch.alter_column("last_seen_lastmod", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("disabled_reason", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("runs_while_disabled", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    with op.batch_alter_table("ingestion_state") as batch:
        batch.drop_column("runs_while_disabled")
        batch.drop_column("disabled_reason")
        batch.drop_column("disabled_at")
        batch.alter_column("last_seen_lastmod", existing_type=sa.DateTime(timezone=True), nullable=False)
