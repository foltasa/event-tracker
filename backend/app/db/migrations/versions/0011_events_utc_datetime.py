"""events datetimes to UTC

Revision ID: 0011_events_utc_datetime
Revises: 0010_taste_per_category
Create Date: 2026-07-12 00:00:00.000000

Data-only migration that shifts existing rows in `events` so their
start_datetime and end_datetime are stored as the UTC instant rather than
the source's local wall-clock time. See docs / commit message for context.

Every producing adapter targets Hamburg venues (Europe/Berlin). Existing
rows currently hold naive wall-clock local time because SQLAlchemy on
SQLite silently strips tzinfo from tz-aware datetimes without converting
to UTC. Downstream code (`schemas/common.py::_ensure_aware_datetimes`)
then labels the naive value as UTC, producing a +1h or +2h drift on
display depending on DST.

The forward migration reinterprets each stored naive value as
Europe/Berlin wall-clock and rewrites it as the corresponding UTC
instant (DST-aware via ZoneInfo). After this migration, the
`UTCDateTime` column type enforces the invariant on new writes.

The downgrade reverses the shift so the pre-migration semantic is
recoverable if this change is rolled back.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migrations.migration_0011_helpers import (
    _localize_berlin_to_utc,
    _utc_to_berlin_naive,
)


revision: str = "0011_events_utc_datetime"
down_revision: Union[str, Sequence[str], None] = "0010_taste_per_category"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _shift_events(shift):
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, start_datetime, end_datetime FROM events")
    ).fetchall()
    for row_id, start_raw, end_raw in rows:
        new_start = shift(start_raw)
        new_end = shift(end_raw)
        bind.execute(
            sa.text(
                "UPDATE events SET start_datetime = :s, end_datetime = :e "
                "WHERE id = :id"
            ),
            {"s": new_start, "e": new_end, "id": row_id},
        )


def upgrade() -> None:
    _shift_events(_localize_berlin_to_utc)


def downgrade() -> None:
    _shift_events(_utc_to_berlin_naive)
