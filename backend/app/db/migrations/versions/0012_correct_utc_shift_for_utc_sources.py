"""correct UTC shift for UTC-shipping sources

Revision ID: 0012_correct_utc_shift_for_utc_sources
Revises: 0011_events_utc_datetime
Create Date: 2026-07-12 00:00:00.000000

Corrective for migration 0011. That migration shifted **every** event row
by the Berlin offset, treating stored wall-clock as Europe/Berlin. That is
correct for adapters that ship Berlin-local time (eventim, ohschonhell,
hamburg_scraper, theater_hamburg) but wrong for adapters that already ship
UTC (ticketmaster, eventbrite): their pre-0011 stored value was already
the UTC wall-clock, so 0011 shifted them one Berlin-offset too far.

Symptom before this migration: Ticketmaster rows displayed 1h (winter) or
2h (summer) too early in the calendar.

Fix: shift ticketmaster and eventbrite rows back by the same Berlin offset
that 0011 subtracted, i.e. apply the inverse conversion (`_utc_to_berlin_naive`)
to those rows only. After this migration all sources are stored as the UTC
instant and the `UTCDateTime` column type keeps future writes consistent.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db.migrations.migration_0011_helpers import (
    _localize_berlin_to_utc,
    _utc_to_berlin_naive,
)


revision: str = "0012_correct_utc_shift_for_utc_sources"
down_revision: Union[str, Sequence[str], None] = "0011_events_utc_datetime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sources that ship dates as UTC (or offset-tagged UTC) — 0011 shouldn't
# have touched their storage, but did. Keep this list narrow: adding a
# new adapter here means "0011 wrongly shifted its rows"; anything else
# is a Berlin-shipping adapter that 0011 handled correctly.
_UTC_SHIPPING_SOURCES = ("ticketmaster", "eventbrite")


def _shift_utc_sources(shift):
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, start_datetime, end_datetime FROM events "
            "WHERE source IN :sources"
        ).bindparams(sa.bindparam("sources", expanding=True)),
        {"sources": list(_UTC_SHIPPING_SOURCES)},
    ).fetchall()
    for row_id, start_raw, end_raw in rows:
        bind.execute(
            sa.text(
                "UPDATE events SET start_datetime = :s, end_datetime = :e "
                "WHERE id = :id"
            ),
            {"s": shift(start_raw), "e": shift(end_raw), "id": row_id},
        )


def upgrade() -> None:
    # Undo the wrong shift 0011 applied: values are currently `UTC - offset`,
    # taking them back to plain UTC by applying the inverse of 0011.
    _shift_utc_sources(_utc_to_berlin_naive)


def downgrade() -> None:
    # Re-apply the wrong 0011 shift on UTC-shipping rows, restoring the
    # damaged post-0011 state.
    _shift_utc_sources(_localize_berlin_to_utc)
