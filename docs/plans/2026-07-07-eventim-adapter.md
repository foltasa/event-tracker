# Eventim Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a new source adapter that ingests ~7,100 Hamburg events from Eventim's public JSON API, with a manual-reset circuit breaker to prevent auto-recovery from compounding into a permanent ban.

**Architecture:** New API adapter at `backend/app/ingestion/eventim.py` implementing the `SourceAdapter` Protocol. Paginates four top-level Eventim categories (Konzerte, Musical & Show, Kultur, Sport) for city Hamburg, transforms each product JSON into a `NormalizedEvent`, yields to the caller. Retries on 403/429/503 with exponential backoff. Sustained failure trips a persistent circuit breaker (columns on `IngestionState`) that requires a manual CLI reset. New Alembic migration `0009_ingestion_state_circuit_breaker` adds three columns and makes `last_seen_lastmod` nullable (Eventim never sets it). New reset script `backend/scripts/reset_adapter_lock.py` clears trip state.

**Tech Stack:** Python 3.11+, httpx, SQLAlchemy 2.x, Alembic, pytest, existing `NormalizedEvent`/`SourceAdapter`/`IngestionState` infrastructure.

**Spec:** `docs/specs/2026-07-07-eventim-adapter-design.md`

**Design context:** `backend/app/ingestion/CLAUDE.md` — read this first if unfamiliar with the pipeline.

---

## File Structure

| Action | Path | Responsibility |
|---|---|---|
| Create | `backend/app/db/migrations/versions/0009_ingestion_state_circuit_breaker.py` | Adds three columns; makes `last_seen_lastmod` nullable |
| Modify | `backend/app/db/models/ingestion_state.py` | Three new mapped columns |
| Create | `backend/app/ingestion/eventim.py` | Retry helper, parser, category map, adapter class, circuit-breaker logic |
| Create | `backend/tests/ingestion/fixtures/eventim/full_konzert.json` | Full-featured Konzerte product |
| Create | `backend/tests/ingestion/fixtures/eventim/no_description.json` | Konzerte product missing `description` |
| Create | `backend/tests/ingestion/fixtures/eventim/klassik.json` | Kultur → Klassische Konzerte product |
| Create | `backend/tests/ingestion/fixtures/eventim/freizeit_leak.json` | `type != "LiveEntertainment"` — should be rejected |
| Create | `backend/tests/ingestion/test_eventim_retry.py` | `get_json_with_retry` + `RetryStats` |
| Create | `backend/tests/ingestion/test_eventim_parser.py` | `parse_product` + category map |
| Create | `backend/tests/ingestion/test_eventim_adapter.py` | Happy-path pagination via `fetch()` |
| Create | `backend/tests/ingestion/test_eventim_circuit_breaker.py` | Trip conditions + banner logging |
| Create | `backend/scripts/reset_adapter_lock.py` | CLI to clear circuit-breaker state |
| Create | `backend/tests/scripts/test_reset_adapter_lock.py` | Reset script tests |
| Modify | `backend/app/ingestion/scheduler.py` | Register `EventimAdapter`; `*** SKIPPED ***` summary line |
| Modify | `backend/tests/ingestion/test_scheduler.py` | Add tripped-summary test |

---

## Task 1: DB migration + model update

Add three nullable/defaulted columns to `ingestion_state` for the persistent circuit breaker. Also relax `last_seen_lastmod` to nullable — Eventim never writes a cursor but may still get a row solely to hold trip state.

**Files:**
- Create: `backend/app/db/migrations/versions/0009_ingestion_state_circuit_breaker.py`
- Modify: `backend/app/db/models/ingestion_state.py`
- Test: `backend/tests/ingestion/test_state.py` (extend existing)

- [ ] **Step 1: Write the failing model test**

Add to `backend/tests/ingestion/test_state.py`:

```python
from datetime import datetime, timezone

from app.db.models.ingestion_state import IngestionState


def test_ingestion_state_row_holds_circuit_breaker_fields(db_session):
    row = IngestionState(
        source="eventim",
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="total_403_budget_exceeded: 15",
        runs_while_disabled=3,
    )
    db_session.add(row)
    db_session.flush()
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched.disabled_at.replace(tzinfo=timezone.utc) == datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc)
    assert fetched.disabled_reason == "total_403_budget_exceeded: 15"
    assert fetched.runs_while_disabled == 3
    assert fetched.last_seen_lastmod is None
```

- [ ] **Step 2: Run test — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_state.py::test_ingestion_state_row_holds_circuit_breaker_fields -v`
Expected: `AttributeError` on `disabled_at` (column doesn't exist yet).

- [ ] **Step 3: Update the model**

Replace `backend/app/db/models/ingestion_state.py` with:

```python
from sqlalchemy import Column, DateTime, Integer, String

from app.db.base import Base


class IngestionState(Base):
    """Per-source state row.

    Two roles: (1) cursor for sitemap-delta scrapers via `last_seen_lastmod`,
    (2) circuit-breaker for adapters that guard against sustained anti-bot
    responses. Sources may use one, both, or neither. `last_seen_lastmod` is
    nullable because circuit-breaker-only sources (e.g. eventim) never set it."""

    __tablename__ = "ingestion_state"

    source = Column(String, primary_key=True)
    last_seen_lastmod = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_reason = Column(String, nullable=True)
    runs_while_disabled = Column(Integer, nullable=False, default=0, server_default="0")
```

- [ ] **Step 4: Write the migration**

Create `backend/app/db/migrations/versions/0009_ingestion_state_circuit_breaker.py`:

```python
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
```

- [ ] **Step 5: Verify migration applies clean**

Run: `cd backend && python -c "from app.db import run_migrations; run_migrations()"`
Expected: no error, no output.

- [ ] **Step 6: Run test — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_state.py -v`
Expected: all tests pass, including the new one.

- [ ] **Step 7: Run full test suite baseline**

Run: `cd backend && python -m pytest -x -q`
Expected: All existing tests continue to pass.

- [ ] **Step 8: Commit**

```bash
cd backend/..
git add backend/app/db/migrations/versions/0009_ingestion_state_circuit_breaker.py backend/app/db/models/ingestion_state.py backend/tests/ingestion/test_state.py
git commit -m "feat(ingestion): circuit-breaker columns on ingestion_state"
```

---

## Task 2: Retry helper `get_json_with_retry` + `RetryStats`

Retry helper local to `eventim.py`. Retriable = {403, 429, 503}, 4 attempts, 2s base sleep. Extracts Akamai Reference IDs from 403 bodies for diagnostics. Returns parsed JSON dict.

**Files:**
- Create: `backend/app/ingestion/eventim.py`
- Test: `backend/tests/ingestion/test_eventim_retry.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/ingestion/test_eventim_retry.py`:

```python
import httpx

from app.ingestion.eventim import RetryStats, get_json_with_retry


class _FakeClient:
    def __init__(self, responses: list[tuple[int, str]]):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        status, body = self._responses.pop(0) if self._responses else (200, "{}")
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def test_returns_json_on_first_success():
    stats = RetryStats()
    client = _FakeClient(responses=[(200, '{"totalPages": 3, "products": []}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body == {"totalPages": 3, "products": []}
    assert stats.total_retries == 0


def test_retries_on_403_then_succeeds():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(responses=[(403, ""), (200, '{"ok": true}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=sleeps.append)
    assert body == {"ok": True}
    assert client.calls == 2
    assert stats.total_retries == 1
    assert stats.akamai_403s == 1
    assert sleeps == [2.0]


def test_retries_on_429_and_503_mixed():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(responses=[(429, ""), (503, ""), (200, '{"ok": true}')])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=sleeps.append)
    assert body == {"ok": True}
    assert stats.total_retries == 2
    assert sleeps == [2.0, 4.0]


def test_exhausted_after_four_attempts():
    stats = RetryStats()
    client = _FakeClient(responses=[(403, ""), (403, ""), (403, ""), (403, "")])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body is None
    assert client.calls == 4
    assert stats.total_retries == 4
    assert stats.exhausted == 1
    assert stats.akamai_403s == 4


def test_non_retry_status_returns_none_without_retry():
    stats = RetryStats()
    client = _FakeClient(responses=[(404, "")])
    body = get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert body is None
    assert client.calls == 1
    assert stats.total_retries == 0


def test_akamai_reference_captured_from_403_body():
    stats = RetryStats()
    body_403 = "<html>Access Denied. Reference #18.abcd1234.1720350000.deadbeef</html>"
    client = _FakeClient(responses=[(403, body_403), (200, '{"ok": true}')])
    get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert stats.akamai_refs == ["18.abcd1234.1720350000.deadbeef"]


def test_akamai_refs_capped_at_five():
    stats = RetryStats()
    body_403 = "<html>Ref #aa.bb.cc.dd</html>"
    client = _FakeClient(responses=[(403, body_403)] * 6)
    for _ in range(2):
        get_json_with_retry(client, "https://example.com/x", params={}, stats=stats, sleep_fn=lambda _s: None)
    assert len(stats.akamai_refs) <= 5


def test_json_get_passes_params():
    """Verify params argument is forwarded to the client."""
    stats = RetryStats()
    captured = {}

    class _Capture:
        def get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            return httpx.Response(200, text="{}", request=httpx.Request("GET", url))

    get_json_with_retry(_Capture(), "https://example.com/x", params={"page": 2, "top": 50}, stats=stats, sleep_fn=lambda _s: None)
    assert captured["params"] == {"page": 2, "top": 50}
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_retry.py -v`
Expected: `ModuleNotFoundError: No module named 'app.ingestion.eventim'`.

- [ ] **Step 3: Create `eventim.py` with retry helper only**

Create `backend/app/ingestion/eventim.py`:

```python
"""Eventim public-search-API adapter.

Fetches Hamburg events from Eventim's undocumented public JSON endpoint
(see docs/specs/2026-07-07-eventim-adapter-design.md). Paginates four
top-level categories, transforms products into NormalizedEvent, yields to
the caller. Anti-bot: 403/429/503 retry + persistent circuit breaker."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

logger = logging.getLogger(__name__)


_RETRY_STATUS_CODES = {403, 429, 503}
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BASE_SLEEP = 2.0  # exponential: 2s, 4s, 8s
_AKAMAI_REF_MAX = 5
_AKAMAI_REF_RE = re.compile(r"Ref(?:erence)?\s*#\s*([0-9a-fA-F.]+)")


class _HttpGetter(Protocol):
    def get(self, url: str, **kwargs) -> httpx.Response: ...


@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0
    akamai_403s: int = 0
    akamai_refs: list[str] = field(default_factory=list)


def _extract_akamai_ref(body: str) -> str | None:
    m = _AKAMAI_REF_RE.search(body)
    return m.group(1) if m else None


def get_json_with_retry(
    client: _HttpGetter,
    url: str,
    *,
    params: dict[str, Any],
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
) -> dict | None:
    """GET a JSON endpoint with exponential backoff on 403/429/503.

    Returns parsed JSON dict on 2xx, or None if all attempts exhausted or the
    status is non-retriable. On 403, extracts the Akamai Reference ID from
    the body (capped at _AKAMAI_REF_MAX in stats). Network exceptions
    propagate — callers handle them at the pagination level."""
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url, params=params)
        if 200 <= resp.status_code < 300:
            return resp.json()
        if resp.status_code == 403:
            stats.akamai_403s += 1
            ref = _extract_akamai_ref(resp.text or "")
            if ref and len(stats.akamai_refs) < _AKAMAI_REF_MAX:
                stats.akamai_refs.append(ref)
        if resp.status_code not in _RETRY_STATUS_CODES:
            logger.warning("eventim: unexpected status %d for %s — skipping", resp.status_code, url)
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            logger.warning(
                "eventim: %d from %s — sleeping %.1fs (attempt %d/%d)",
                resp.status_code, url, backoff, attempt, _RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            logger.warning(
                "eventim: giving up on %s after %d attempts",
                url, _RETRY_MAX_ATTEMPTS,
            )
    return None
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_retry.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/test_eventim_retry.py
git commit -m "feat(eventim): get_json_with_retry helper with Akamai 403 handling"
```

---

## Task 3: Category map + pure parser `parse_product`

Static leaf-category → `EventCategory` dict. Pure `parse_product(dict) → NormalizedEvent | None`. Fixture JSON files for tests.

**Files:**
- Modify: `backend/app/ingestion/eventim.py`
- Create: `backend/tests/ingestion/fixtures/eventim/full_konzert.json`
- Create: `backend/tests/ingestion/fixtures/eventim/no_description.json`
- Create: `backend/tests/ingestion/fixtures/eventim/klassik.json`
- Create: `backend/tests/ingestion/fixtures/eventim/freizeit_leak.json`
- Create: `backend/tests/ingestion/test_eventim_parser.py`

- [ ] **Step 1: Write the fixtures**

Create `backend/tests/ingestion/fixtures/eventim/full_konzert.json`:

```json
{
  "attractions": [{"name": "Beirut"}],
  "categories": [
    {"name": "Konzerte"},
    {"name": "Rock & Pop", "parentCategory": {"name": "Konzerte"}}
  ],
  "currency": "EUR",
  "description": "Mit A Study of Losses im Gepack geht Beirut nun erneut auf Tour",
  "imageUrl": "https://www.eventim.de/obj/media/DE-eventim/teaser/222x222/2025/beirut.jpg",
  "link": "https://www.eventim.de/event/beirut-stadtpark-open-air-20925654/",
  "name": "Beirut",
  "price": 60.4,
  "productGroupId": "4028322",
  "productId": "20925654",
  "type": "LiveEntertainment",
  "typeAttributes": {
    "liveEntertainment": {
      "location": {
        "city": "Hamburg",
        "geoLocation": {"latitude": 53.596, "longitude": 10.051},
        "name": "Stadtpark Open Air",
        "postalCode": "22303"
      },
      "startDate": "2026-07-07T19:00:00+02:00"
    }
  }
}
```

Create `backend/tests/ingestion/fixtures/eventim/no_description.json`:

```json
{
  "attractions": [{"name": "Wade Black"}],
  "categories": [
    {"name": "Konzerte"},
    {"name": "Metal & Hardrock", "parentCategory": {"name": "Konzerte"}}
  ],
  "currency": "EUR",
  "imageUrl": "https://www.eventim.de/obj/media/wade.jpg",
  "link": "https://www.eventim.de/event/wade-blacks-35-years-of-metal-marx-21340085/",
  "name": "Wade Black's 35 Years Of Metal",
  "price": 35.0,
  "productGroupId": "5001",
  "productId": "21340085",
  "type": "LiveEntertainment",
  "typeAttributes": {
    "liveEntertainment": {
      "location": {"city": "Hamburg", "name": "Marx", "postalCode": "22765"},
      "startDate": "2026-10-12T20:00:00+02:00"
    }
  }
}
```

Create `backend/tests/ingestion/fixtures/eventim/klassik.json`:

```json
{
  "attractions": [{"name": "NDR Elbphilharmonie Orchester"}],
  "categories": [
    {"name": "Kultur"},
    {"name": "Klassische Konzerte", "parentCategory": {"name": "Kultur"}}
  ],
  "currency": "EUR",
  "description": "Ein Abend mit Mahlers 5. Symphonie",
  "link": "https://www.eventim.de/event/ndr-elphi-12345/",
  "name": "Mahler: Symphonie Nr. 5",
  "price": 45.0,
  "productGroupId": "9001",
  "productId": "12345",
  "type": "LiveEntertainment",
  "typeAttributes": {
    "liveEntertainment": {
      "location": {"city": "Hamburg", "name": "Elbphilharmonie", "postalCode": "20457"},
      "startDate": "2026-09-14T20:00:00+02:00"
    }
  }
}
```

Create `backend/tests/ingestion/fixtures/eventim/freizeit_leak.json`:

```json
{
  "categories": [
    {"name": "Freizeit"},
    {"name": "Fuhrungen & Rundfahrten", "parentCategory": {"name": "Freizeit"}}
  ],
  "currency": "EUR",
  "link": "https://www.eventim.de/event/hafen-tour-99999/",
  "name": "Grosse Hafenrundfahrt",
  "price": 25.0,
  "productGroupId": "7001",
  "productId": "99999",
  "type": "Package",
  "typeAttributes": {}
}
```

- [ ] **Step 2: Write the failing parser tests**

Create `backend/tests/ingestion/test_eventim_parser.py`:

```python
import json
import logging
from pathlib import Path

import pytest

from app.ingestion.eventim import _CATEGORY_MAP, parse_product

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_full_konzert_all_fields():
    ev = parse_product(_load("full_konzert.json"))
    assert ev is not None
    assert ev.external_id == "20925654"
    assert ev.source == "eventim"
    assert ev.title == "Beirut"
    assert ev.description.startswith("Mit A Study of Losses")
    assert ev.summary is None
    assert ev.start_datetime.isoformat() == "2026-07-07T19:00:00+02:00"
    assert ev.end_datetime is None
    assert ev.venue_name == "Stadtpark Open Air"
    assert ev.venue_address == "22303 Hamburg"
    assert ev.latitude == 53.596
    assert ev.longitude == 10.051
    assert ev.category == "concerts"
    assert "Konzerte" in ev.tags
    assert "Rock & Pop" in ev.tags
    assert "Beirut" in ev.tags
    assert ev.price_min == 60.4
    assert ev.price_max is None
    assert ev.is_free is False
    assert ev.currency == "EUR"
    assert ev.image_url == "https://www.eventim.de/obj/media/DE-eventim/teaser/222x222/2025/beirut.jpg"
    assert ev.source_url == "https://www.eventim.de/event/beirut-stadtpark-open-air-20925654/"
    assert ev.raw_data["productId"] == "20925654"
    assert ev.raw_data["productGroupId"] == "4028322"


def test_parse_missing_description_returns_none_field():
    ev = parse_product(_load("no_description.json"))
    assert ev is not None
    assert ev.description is None
    assert ev.title == "Wade Black's 35 Years Of Metal"


def test_parse_klassik_maps_to_concerts_category():
    ev = parse_product(_load("klassik.json"))
    assert ev is not None
    assert ev.category == "concerts"


def test_parse_rejects_freizeit_leak_by_type():
    assert parse_product(_load("freizeit_leak.json")) is None


def test_parse_rejects_missing_product_id():
    p = _load("full_konzert.json")
    del p["productId"]
    assert parse_product(p) is None


def test_parse_rejects_missing_name():
    p = _load("full_konzert.json")
    del p["name"]
    assert parse_product(p) is None


def test_parse_rejects_missing_start_date():
    p = _load("full_konzert.json")
    del p["typeAttributes"]["liveEntertainment"]["startDate"]
    assert parse_product(p) is None


def test_parse_rejects_non_hamburg_city():
    p = _load("full_konzert.json")
    p["typeAttributes"]["liveEntertainment"]["location"]["city"] = "Berlin"
    assert parse_product(p) is None


def test_parse_no_geo_leaves_lat_lng_none():
    p = _load("full_konzert.json")
    del p["typeAttributes"]["liveEntertainment"]["location"]["geoLocation"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.latitude is None
    assert ev.longitude is None


def test_parse_zero_price_is_free():
    p = _load("full_konzert.json")
    p["price"] = 0
    ev = parse_product(p)
    assert ev is not None
    assert ev.is_free is True
    assert ev.price_min == 0


def test_parse_missing_price_leaves_price_min_none():
    p = _load("full_konzert.json")
    del p["price"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.price_min is None
    assert ev.price_max is None
    assert ev.is_free is False


def test_parse_missing_image_url_ok():
    p = _load("full_konzert.json")
    del p["imageUrl"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.image_url is None


def test_category_map_covers_all_known_leaves():
    expected = {
        "Rock & Pop": "concerts",
        "HipHop & R'n'B": "concerts",
        "Schlager & Volksmusik": "concerts",
        "Jazz & Blues": "concerts",
        "Elektronische Musik": "concerts",
        "Metal & Hardrock": "concerts",
        "Weitere Konzerte": "concerts",
        "Klassische Konzerte": "concerts",
        "Oper": "theater",
        "Ballett & Tanz": "theater",
        "Theater": "theater",
        "Musical": "theater",
        "Show": "other",
        "Fußball": "sports",
        "Handball": "sports",
        "Weitere Sportarten": "sports",
    }
    for leaf, cat in expected.items():
        assert _CATEGORY_MAP[leaf] == cat


def test_unknown_leaf_falls_back_to_other_and_warns(caplog):
    p = _load("full_konzert.json")
    p["categories"] = [
        {"name": "Konzerte"},
        {"name": "Nu-Weirdcore", "parentCategory": {"name": "Konzerte"}},
    ]
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        ev = parse_product(p)
    assert ev is not None
    assert ev.category == "other"
    assert any("Nu-Weirdcore" in rec.message for rec in caplog.records)


def test_no_leaf_category_falls_back_to_other():
    p = _load("full_konzert.json")
    p["categories"] = [{"name": "Konzerte"}]
    ev = parse_product(p)
    assert ev is not None
    assert ev.category == "other"
```

- [ ] **Step 3: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_parser.py -v`
Expected: `ImportError: cannot import name '_CATEGORY_MAP' from 'app.ingestion.eventim'`.

- [ ] **Step 4: Add category map and parser to `eventim.py`**

Append to `backend/app/ingestion/eventim.py`:

```python
from datetime import datetime
from typing import cast

from app.ingestion.normalize import NormalizedEvent
from app.schemas.common import EventCategory


_CATEGORY_MAP: dict[str, EventCategory] = {
    # Konzerte subcategories
    "Rock & Pop": "concerts",
    "HipHop & R'n'B": "concerts",
    "Schlager & Volksmusik": "concerts",
    "Jazz & Blues": "concerts",
    "Elektronische Musik": "concerts",
    "Metal & Hardrock": "concerts",
    "Weitere Konzerte": "concerts",
    # Kultur subcategories
    "Klassische Konzerte": "concerts",
    "Oper": "theater",
    "Ballett & Tanz": "theater",
    "Theater": "theater",
    # Musical & Show subcategories
    "Musical": "theater",
    "Show": "other",
    # Sport subcategories
    "Fußball": "sports",
    "Handball": "sports",
    "Weitere Sportarten": "sports",
}

_SOURCE_NAME = "eventim"
_TARGET_CITY = "Hamburg"


def _category_for(product: dict) -> EventCategory:
    """Map the leaf (sub-level) Eventim category to our EventCategory.

    Unknown leaves fall back to 'other' with a WARNING log so operators
    notice drift in Eventim's taxonomy."""
    for cat in product.get("categories", []):
        parent = cat.get("parentCategory")
        if not parent:
            continue
        name = cat.get("name")
        mapped = _CATEGORY_MAP.get(name)
        if mapped is not None:
            return mapped
        logger.warning(
            "eventim: unknown leaf category '%s' → falling back to 'other'",
            name,
        )
        return "other"
    return "other"


def _tags_for(product: dict) -> list[str]:
    tags: list[str] = []
    for cat in product.get("categories", []):
        name = cat.get("name")
        if name and name not in tags:
            tags.append(name)
    for attr in product.get("attractions", []):
        name = attr.get("name")
        if name and name not in tags:
            tags.append(name)
    return tags


def parse_product(product: dict) -> NormalizedEvent | None:
    """Convert one Eventim product dict to a NormalizedEvent.

    Returns None when required fields are missing, type is not
    LiveEntertainment, or city is not the target. Pure — no I/O."""
    if product.get("type") != "LiveEntertainment":
        return None

    product_id = product.get("productId")
    name = product.get("name")
    live = (product.get("typeAttributes") or {}).get("liveEntertainment") or {}
    start_raw = live.get("startDate")
    location = live.get("location") or {}

    if not product_id or not name or not start_raw:
        return None
    if location.get("city") != _TARGET_CITY:
        return None

    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        return None

    venue_name = location.get("name") or ""
    if not venue_name:
        return None

    postal = (location.get("postalCode") or "").strip()
    city = (location.get("city") or "").strip()
    venue_address = f"{postal} {city}".strip() or None

    geo = location.get("geoLocation") or {}
    lat = geo.get("latitude")
    lng = geo.get("longitude")

    price = product.get("price")
    price_min = float(price) if price is not None else None
    is_free = price_min == 0

    description = product.get("description") or None

    return NormalizedEvent(
        external_id=str(product_id),
        source=_SOURCE_NAME,
        title=name,
        description=description,
        start_datetime=start_dt,
        venue_name=venue_name,
        venue_address=venue_address,
        latitude=lat,
        longitude=lng,
        category=_category_for(product),
        tags=_tags_for(product),
        price_min=price_min,
        price_max=None,
        is_free=is_free,
        currency=product.get("currency") or "EUR",
        image_url=product.get("imageUrl") or None,
        source_url=product.get("link") or "",
        raw_data={
            "productId": str(product_id),
            "productGroupId": product.get("productGroupId"),
            "eventim_categories": product.get("categories", []),
            "startDate_raw": start_raw,
        },
    )
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_parser.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/fixtures/eventim/ backend/tests/ingestion/test_eventim_parser.py
git commit -m "feat(eventim): parse_product + category map"
```

---

## Task 4: `EventimAdapter` class — happy-path pagination

Adapter class implementing `SourceAdapter`. Iterates four categories, paginates 1..`totalPages` per category (page 1 provides the count), yields `NormalizedEvent` per product. No circuit breaker yet — added in Task 5–6.

**Files:**
- Modify: `backend/app/ingestion/eventim.py`
- Create: `backend/tests/ingestion/test_eventim_adapter.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/ingestion/test_eventim_adapter.py`:

```python
import json
from pathlib import Path

import httpx

from app.ingestion.eventim import EventimAdapter

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _search_response(products: list[dict], total_pages: int, page: int) -> str:
    return json.dumps({
        "products": products,
        "page": page,
        "totalPages": total_pages,
        "totalResults": total_pages * max(len(products), 1),
    })


class _FakeClient:
    """Routes: (category, page) -> (status, body). Any (cat, page) miss returns 200 empty page."""

    def __init__(self, routes: dict[tuple[str, int], tuple[int, str]] | None = None):
        self._routes = dict(routes or {})
        self.calls: list[tuple[str, int]] = []

    def get(self, url: str, *, params: dict, **kwargs) -> httpx.Response:
        cat = params["categories"]
        page = params["page"]
        self.calls.append((cat, page))
        status, body = self._routes.get((cat, page), (200, _search_response([], 1, page)))
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def _one_of(fixture: str, overrides: dict | None = None) -> dict:
    p = _load(fixture)
    if overrides:
        p.update(overrides)
    return p


def test_happy_path_yields_events_across_all_categories(db_session):
    konzert = _one_of("full_konzert.json")
    klassik = _one_of("klassik.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=1, page=1)),
        ("Musical & Show", 1): (200, _search_response([], total_pages=1, page=1)),
        ("Kultur", 1): (200, _search_response([klassik], total_pages=1, page=1)),
        ("Sport", 1): (200, _search_response([], total_pages=1, page=1)),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    ids = sorted(e.external_id for e in events)
    assert ids == ["12345", "20925654"]


def test_paginates_full_range_per_category(db_session):
    konzert = _one_of("full_konzert.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=3, page=1)),
        ("Konzerte", 2): (200, _search_response([_one_of("full_konzert.json", {"productId": "aaa"})], total_pages=3, page=2)),
        ("Konzerte", 3): (200, _search_response([_one_of("full_konzert.json", {"productId": "bbb"})], total_pages=3, page=3)),
    }
    client = _FakeClient(routes)
    adapter = EventimAdapter(client=client, sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    konzerte_ids = sorted(e.external_id for e in events if e.raw_data.get("productId") in {"20925654", "aaa", "bbb"})
    assert konzerte_ids == ["20925654", "aaa", "bbb"]
    # Verify pages 1, 2, 3 were requested (in order) for Konzerte
    konzert_pages = [p for (c, p) in client.calls if c == "Konzerte"]
    assert konzert_pages == [1, 2, 3]


def test_mid_page_failure_is_logged_and_skipped(db_session, caplog):
    konzert_p1 = _one_of("full_konzert.json")
    konzert_p3 = _one_of("full_konzert.json", {"productId": "ccc"})
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert_p1], total_pages=3, page=1)),
        ("Konzerte", 2): (403, ""),
        ("Konzerte", 3): (200, _search_response([konzert_p3], total_pages=3, page=3)),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    ids = sorted(e.external_id for e in events)
    # Page 2 fails after retries; pages 1 and 3 still processed.
    assert "20925654" in ids
    assert "ccc" in ids


def test_sleep_between_pages(db_session):
    konzert = _one_of("full_konzert.json")
    routes = {
        ("Konzerte", 1): (200, _search_response([konzert], total_pages=2, page=1)),
        ("Konzerte", 2): (200, _search_response([_one_of("full_konzert.json", {"productId": "ddd"})], total_pages=2, page=2)),
    }
    sleeps: list[float] = []
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=sleeps.append)
    list(adapter.fetch(db_session))
    # At least one 0.2s inter-page sleep is expected.
    assert any(abs(s - 0.2) < 1e-6 for s in sleeps)


def test_query_params_are_correct(db_session):
    captured: list[dict] = []

    class _Capturing:
        def get(self, url, *, params, **kwargs):
            captured.append(dict(params))
            return httpx.Response(200, text=_search_response([], 1, params["page"]), request=httpx.Request("GET", url))

    adapter = EventimAdapter(client=_Capturing(), sleep_fn=lambda _s: None)
    list(adapter.fetch(db_session))
    p = captured[0]
    assert p["city_names"] == "Hamburg"
    assert p["webId"] == "web__eventim-de"
    assert p["language"] == "de"
    assert p["sort"] == "DateAsc"
    assert p["top"] == 50
    assert p["categories"] in {"Konzerte", "Musical & Show", "Kultur", "Sport"}


def test_all_categories_fail_page_1_raises(db_session):
    import pytest
    routes = {
        ("Konzerte", 1): (403, ""),
        ("Musical & Show", 1): (403, ""),
        ("Kultur", 1): (403, ""),
        ("Sport", 1): (403, ""),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    with pytest.raises(RuntimeError, match="all categories failed page 1"):
        list(adapter.fetch(db_session))
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_adapter.py -v`
Expected: `ImportError: cannot import name 'EventimAdapter'`.

- [ ] **Step 3: Add `EventimAdapter` to `eventim.py`**

Append to `backend/app/ingestion/eventim.py`:

```python
import time
from typing import Iterator

from sqlalchemy.orm import Session


_API = "https://public-api.eventim.com/websearch/search/api/exploration/v1/products"
_CATEGORIES = ["Konzerte", "Musical & Show", "Kultur", "Sport"]
_TOP = 50
_REQUEST_DELAY_SECONDS = 0.2

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Origin": "https://www.eventim.de",
    "Referer": "https://www.eventim.de/city/hamburg-72/",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not:A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


class EventimAdapter:
    """Ingest Hamburg events from Eventim's public JSON search API.

    Full-crawl every run across four top-level categories; idempotent via
    upsert on (external_id, source). Circuit breaker (Task 5–6) gates the
    entire run when Akamai flags us."""

    name = "eventim"

    def __init__(
        self,
        client: _HttpGetter | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._client = client or httpx.Client(timeout=20, headers=_DEFAULT_HEADERS)
        self._sleep_fn = sleep_fn

    def fetch(self, session: Session) -> Iterator[NormalizedEvent]:
        stats = RetryStats()
        categories_failed_page_1 = 0
        for category in _CATEGORIES:
            first = get_json_with_retry(
                self._client, _API,
                params=self._params(category, page=1),
                stats=stats, sleep_fn=self._sleep_fn,
            )
            if first is None:
                logger.warning("eventim: page 1 of category '%s' failed after retries — skipping category", category)
                categories_failed_page_1 += 1
                continue

            yield from self._products(first)
            total_pages = int(first.get("totalPages") or 1)

            for page in range(2, total_pages + 1):
                self._sleep_fn(_REQUEST_DELAY_SECONDS)
                body = get_json_with_retry(
                    self._client, _API,
                    params=self._params(category, page=page),
                    stats=stats, sleep_fn=self._sleep_fn,
                )
                if body is None:
                    logger.warning(
                        "eventim: page %d of category '%s' failed after retries — skipping page",
                        page, category,
                    )
                    continue
                yield from self._products(body)

        if categories_failed_page_1 == len(_CATEGORIES):
            raise RuntimeError("eventim: all categories failed page 1")

    def _params(self, category: str, *, page: int) -> dict:
        return {
            "city_names": _TARGET_CITY,
            "categories": category,
            "webId": "web__eventim-de",
            "language": "de",
            "page": page,
            "top": _TOP,
            "sort": "DateAsc",
        }

    def _products(self, body: dict) -> Iterator[NormalizedEvent]:
        for product in body.get("products", []) or []:
            ev = parse_product(product)
            if ev is not None:
                yield ev
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_adapter.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/test_eventim_adapter.py
git commit -m "feat(eventim): EventimAdapter pagination across four categories"
```

---

## Task 5: Circuit breaker — check on entry

If `IngestionState(source="eventim").disabled_at` is set, `fetch()` emits the disabled banner, increments `runs_while_disabled`, and returns without any HTTP call. Persist the counter bump via a fresh short-lived session so it survives even if the caller's transaction rolls back.

**Files:**
- Modify: `backend/app/ingestion/eventim.py`
- Create: `backend/tests/ingestion/test_eventim_circuit_breaker.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/ingestion/test_eventim_circuit_breaker.py`:

```python
import logging
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models.ingestion_state import IngestionState
from app.ingestion.eventim import EventimAdapter


class _RaisingClient:
    """Any HTTP call raises — proves fetch() short-circuits when tripped."""

    def get(self, url, **kwargs):
        raise AssertionError(f"unexpected HTTP call to {url}")


def _seed_tripped(session, source: str = "eventim", *,
                  reason: str = "total_403_budget_exceeded: 15",
                  runs: int = 0) -> None:
    row = IngestionState(
        source=source,
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason=reason,
        runs_while_disabled=runs,
    )
    session.add(row)
    session.flush()


def test_fetch_returns_empty_when_tripped(db_session):
    _seed_tripped(db_session)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    events = list(adapter.fetch(db_session))
    assert events == []


def test_banner_logged_when_tripped(db_session, caplog):
    _seed_tripped(db_session, runs=3)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        list(adapter.fetch(db_session))
    msg = "\n".join(rec.message for rec in caplog.records)
    assert "EVENTIM ADAPTER DISABLED" in msg
    assert "total_403_budget_exceeded: 15" in msg
    assert "python -m scripts.reset_adapter_lock eventim" in msg


def test_runs_while_disabled_counter_increments(db_session):
    _seed_tripped(db_session, runs=0)
    adapter = EventimAdapter(client=_RaisingClient(), sleep_fn=lambda _s: None)
    # Adapter uses its own session to persist the counter bump; patch SessionLocal
    # to hand back the test session so the write is visible.
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched.runs_while_disabled == 2
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_circuit_breaker.py::test_fetch_returns_empty_when_tripped -v`
Expected: `AssertionError: unexpected HTTP call to ...` — adapter doesn't short-circuit yet.

- [ ] **Step 3: Add circuit-breaker check to `EventimAdapter`**

At the top of `backend/app/ingestion/eventim.py` add:

```python
from app.db.session import SessionLocal
```

Modify `EventimAdapter.fetch` to check trip state at the top:

```python
    def fetch(self, session: Session) -> Iterator[NormalizedEvent]:
        state = session.get(IngestionState, self.name)
        if state is not None and state.disabled_at is not None:
            self._log_disabled_banner(state)
            self._bump_runs_while_disabled()
            return

        # ... existing pagination code ...
```

Add helper methods to the class:

```python
    def _log_disabled_banner(self, state: IngestionState) -> None:
        logger.warning(
            "\n!! ============================================================\n"
            "!! EVENTIM ADAPTER DISABLED\n"
            "!!   Tripped at:  %s\n"
            "!!   Reason:      %s\n"
            "!!   Runs since:  %d\n"
            "!!   To re-enable: python -m scripts.reset_adapter_lock eventim\n"
            "!! ============================================================",
            state.disabled_at.isoformat(),
            state.disabled_reason,
            state.runs_while_disabled,
        )

    def _bump_runs_while_disabled(self) -> None:
        """Persist counter bump in its own transaction so it survives even
        if the caller's ingestion transaction later rolls back."""
        own_session = SessionLocal()
        try:
            row = own_session.get(IngestionState, self.name)
            if row is not None and row.disabled_at is not None:
                row.runs_while_disabled = (row.runs_while_disabled or 0) + 1
                own_session.commit()
        finally:
            own_session.close()
```

Also add the import at the top of the file:

```python
from app.db.models.ingestion_state import IngestionState
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_circuit_breaker.py -v`
Expected: all three tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/test_eventim_circuit_breaker.py
git commit -m "feat(eventim): circuit-breaker check + disabled banner"
```

---

## Task 6: Circuit breaker — trip conditions during a run

Three trip conditions checked during pagination:

1. **Consecutive per-page retry-exhaustion**: 3 in a row.
2. **All 4 categories fail page 1**: replaces the raw `RuntimeError` from Task 4.
3. **Total 403 budget**: 15 total 403 events across the whole run.

On trip: persist trip state via its own session, log the mid-run banner, stop the fetch by returning normally. Anything yielded before the trip has been consumed by the caller.

**Files:**
- Modify: `backend/app/ingestion/eventim.py`
- Modify: `backend/tests/ingestion/test_eventim_circuit_breaker.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/ingestion/test_eventim_circuit_breaker.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch

import httpx

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _search_response(products, total_pages: int, page: int) -> str:
    return json.dumps({"products": products, "page": page, "totalPages": total_pages, "totalResults": 1})


class _RoutedClient:
    def __init__(self, routes: dict[tuple[str, int], list[tuple[int, str]]]):
        self._routes = {k: list(v) for k, v in routes.items()}

    def get(self, url, *, params, **kwargs):
        cat = params["categories"]
        page = params["page"]
        seq = self._routes.get((cat, page), [(200, _search_response([], 1, page))])
        status, body = seq.pop(0) if seq else (200, _search_response([], 1, page))
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


def test_trip_on_three_consecutive_page_exhaustions(db_session):
    konzert = _load("full_konzert.json")
    # Page 1: success (need it to know totalPages)
    # Pages 2, 3, 4: exhaust retries with 403 each
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=6, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(403, "")] * 4,
        ("Konzerte", 4): [(403, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert "consecutive_retry_exhaustion" in fetched.disabled_reason


def test_trip_on_all_categories_page_1_exhausted(db_session):
    # Use 503 (retriable but not 403) so we don't accidentally hit the total-403 budget first.
    routes = {
        ("Konzerte", 1): [(503, "")] * 4,
        ("Musical & Show", 1): [(503, "")] * 4,
        ("Kultur", 1): [(503, "")] * 4,
        ("Sport", 1): [(503, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert fetched.disabled_reason == "all_categories_failed_page_1"


def test_trip_on_total_403_budget_exceeded(db_session):
    konzert = _load("full_konzert.json")
    # Alternate failing pages with successful pages so the consecutive-exhaustion
    # trip never fires (consecutive resets on each success). Failing pages
    # accumulate 4×403 each; we need > 15 total, so 4 failing pages = 16 403s.
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=10, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(200, _search_response([], total_pages=10, page=3))],
        ("Konzerte", 4): [(403, "")] * 4,
        ("Konzerte", 5): [(200, _search_response([], total_pages=10, page=5))],
        ("Konzerte", 6): [(403, "")] * 4,
        ("Konzerte", 7): [(200, _search_response([], total_pages=10, page=7))],
        ("Konzerte", 8): [(403, "")] * 4,
        ("Konzerte", 9): [(200, _search_response([], total_pages=10, page=9))],
        ("Konzerte", 10): [(200, _search_response([], total_pages=10, page=10))],
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        list(adapter.fetch(db_session))
    fetched = db_session.get(IngestionState, "eventim")
    assert fetched is not None
    assert fetched.disabled_at is not None
    assert "total_403_budget_exceeded" in fetched.disabled_reason


def test_partial_ingest_before_trip(db_session):
    konzert = _load("full_konzert.json")
    routes = {
        ("Konzerte", 1): [(200, _search_response([konzert], total_pages=6, page=1))],
        ("Konzerte", 2): [(403, "")] * 4,
        ("Konzerte", 3): [(403, "")] * 4,
        ("Konzerte", 4): [(403, "")] * 4,
    }
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        events = list(adapter.fetch(db_session))
    assert any(e.external_id == "20925654" for e in events)


def test_mid_run_trip_banner_logged(db_session, caplog):
    routes = {("Konzerte", 1): [(503, "")] * 4,
              ("Musical & Show", 1): [(503, "")] * 4,
              ("Kultur", 1): [(503, "")] * 4,
              ("Sport", 1): [(503, "")] * 4}
    adapter = EventimAdapter(client=_RoutedClient(routes), sleep_fn=lambda _s: None)
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
            list(adapter.fetch(db_session))
    msg = "\n".join(rec.message for rec in caplog.records)
    assert "EVENTIM CIRCUIT BREAKER TRIPPED THIS RUN" in msg
    assert "all_categories_failed_page_1" in msg
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_circuit_breaker.py -v`
Expected: the four new tests fail (existing three continue to pass).

- [ ] **Step 3: Add trip logic to `EventimAdapter`**

Design intent: category-level page-1 failures count only toward the `categories_failed_page_1` tally (checked once at end of loop). Only **mid-category page failures** (page 2..N of a given category) feed the consecutive-exhaustion counter. Total-403-budget check runs continuously.

Replace the body of `EventimAdapter.fetch` with the trip-aware version:

```python
    _TRIP_CONSECUTIVE_EXHAUSTIONS = 3
    _TRIP_TOTAL_403_BUDGET = 15

    def fetch(self, session: Session) -> Iterator[NormalizedEvent]:
        state = session.get(IngestionState, self.name)
        if state is not None and state.disabled_at is not None:
            self._log_disabled_banner(state)
            self._bump_runs_while_disabled()
            return

        stats = RetryStats()
        categories_failed_page_1 = 0
        consecutive_exhaustions = 0
        events_yielded_this_run = 0

        for i, category in enumerate(_CATEGORIES):
            first = get_json_with_retry(
                self._client, _API,
                params=self._params(category, page=1),
                stats=stats, sleep_fn=self._sleep_fn,
            )
            if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                           events_yielded_this_run, category, i)
                return
            if first is None:
                logger.warning(
                    "eventim: page 1 of category '%s' failed after retries — skipping category",
                    category,
                )
                categories_failed_page_1 += 1
                # Category-level failures do NOT feed consecutive_exhaustions.
                continue

            for ev in self._products(first):
                events_yielded_this_run += 1
                yield ev

            total_pages = int(first.get("totalPages") or 1)
            for page in range(2, total_pages + 1):
                self._sleep_fn(_REQUEST_DELAY_SECONDS)
                body = get_json_with_retry(
                    self._client, _API,
                    params=self._params(category, page=page),
                    stats=stats, sleep_fn=self._sleep_fn,
                )
                if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                    self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                               events_yielded_this_run, category, i)
                    return
                if body is None:
                    logger.warning(
                        "eventim: page %d of category '%s' failed after retries — skipping page",
                        page, category,
                    )
                    consecutive_exhaustions += 1
                    if consecutive_exhaustions >= self._TRIP_CONSECUTIVE_EXHAUSTIONS:
                        self._trip(
                            f"consecutive_retry_exhaustion: {consecutive_exhaustions} pages",
                            events_yielded_this_run, category, i,
                        )
                        return
                    continue
                consecutive_exhaustions = 0
                for ev in self._products(body):
                    events_yielded_this_run += 1
                    yield ev

        # Post-loop: if every category's page 1 failed, trip.
        if categories_failed_page_1 == len(_CATEGORIES):
            self._trip("all_categories_failed_page_1",
                       events_yielded_this_run,
                       _CATEGORIES[-1], len(_CATEGORIES) - 1)
            return

    def _trip(self, reason: str, events_before: int, at_category: str, category_index: int) -> None:
        now = datetime.now(timezone.utc)
        # Persist trip in its own transaction so it survives a caller rollback.
        own_session = SessionLocal()
        try:
            row = own_session.get(IngestionState, self.name)
            if row is None:
                row = IngestionState(
                    source=self.name,
                    last_seen_lastmod=None,
                    disabled_at=now,
                    disabled_reason=reason,
                    runs_while_disabled=0,
                )
                own_session.add(row)
            else:
                row.disabled_at = now
                row.disabled_reason = reason
                row.runs_while_disabled = 0
            own_session.commit()
        finally:
            own_session.close()

        skipped = [c for c in _CATEGORIES[category_index + 1:]]
        skipped_str = ", ".join(skipped) if skipped else "(none)"
        logger.warning(
            "\n!! ============================================================\n"
            "!! EVENTIM CIRCUIT BREAKER TRIPPED THIS RUN\n"
            "!!   At:       %s\n"
            "!!   Reason:   %s\n"
            "!!   Partial:  ingested %d events from %s before trip\n"
            "!!   Skipped:  %s\n"
            "!!   Reset:    python -m scripts.reset_adapter_lock eventim\n"
            "!! ============================================================",
            now.isoformat(), reason, events_before, at_category, skipped_str,
        )
```

Update the `datetime` import at the top of the module:

```python
from datetime import datetime, timezone
```

Remove the earlier `raise RuntimeError("eventim: all categories failed page 1")` (Task 4) — its role is now covered by the `all_categories_failed_page_1` trip.

- [ ] **Step 4: Update the Task 4 test that expected `RuntimeError`**

In `backend/tests/ingestion/test_eventim_adapter.py`, replace `test_all_categories_fail_page_1_raises` with:

```python
def test_all_categories_fail_page_1_trips_breaker(db_session):
    from unittest.mock import patch
    from app.db.models.ingestion_state import IngestionState
    # 503 (retriable, non-403) so we hit the all-cats trip rather than the 403 budget.
    routes = {
        ("Konzerte", 1): (503, ""),
        ("Musical & Show", 1): (503, ""),
        ("Kultur", 1): (503, ""),
        ("Sport", 1): (503, ""),
    }
    adapter = EventimAdapter(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    with patch("app.ingestion.eventim.SessionLocal", return_value=db_session):
        events = list(adapter.fetch(db_session))
    assert events == []
    row = db_session.get(IngestionState, "eventim")
    assert row is not None
    assert row.disabled_at is not None
    assert row.disabled_reason == "all_categories_failed_page_1"
```

**Note:** the previous version of `_FakeClient` returns a single tuple per (cat, page) — but the retry helper calls up to 4 times per page. Update `_FakeClient` to return the same tuple on every call to a route (simpler than a sequence for happy-path tests):

Replace the `_FakeClient.get` in `test_eventim_adapter.py` with:

```python
    def get(self, url: str, *, params: dict, **kwargs) -> httpx.Response:
        cat = params["categories"]
        page = params["page"]
        self.calls.append((cat, page))
        status, body = self._routes.get((cat, page), (200, _search_response([], 1, page)))
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))
```

(This is the already-shown implementation; it returns the same (status, body) on repeat calls to the same route, so a 403 gets returned 4× in a row until retries exhaust.)

- [ ] **Step 5: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_circuit_breaker.py tests/ingestion/test_eventim_adapter.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/test_eventim_circuit_breaker.py backend/tests/ingestion/test_eventim_adapter.py
git commit -m "feat(eventim): mid-run trip conditions (consecutive/all-cats/403-budget)"
```

---

## Task 7: Manual-reset script `reset_adapter_lock.py`

CLI to clear circuit-breaker state. Prints the current trip state and asks for confirmation (skippable with `--yes`). Generic — takes source name as arg so future adapters share it.

**Files:**
- Create: `backend/scripts/reset_adapter_lock.py`
- Create: `backend/tests/scripts/test_reset_adapter_lock.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/scripts/test_reset_adapter_lock.py`:

```python
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.db.models.ingestion_state import IngestionState
from scripts.reset_adapter_lock import main


def _seed_tripped(session, source: str = "eventim") -> None:
    session.add(IngestionState(
        source=source,
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="all_categories_failed_page_1",
        runs_while_disabled=5,
    ))
    session.flush()


def test_reset_clears_trip_state_with_yes_flag(db_session, capsys):
    _seed_tripped(db_session)
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim", "--yes"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is None
    assert row.disabled_reason is None
    assert row.runs_while_disabled == 0
    out = capsys.readouterr().out
    assert "eventim" in out
    assert "reset" in out.lower()


def test_reset_prints_current_state_before_clearing(db_session, capsys):
    _seed_tripped(db_session)
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        main(["eventim", "--yes"])
    out = capsys.readouterr().out
    assert "all_categories_failed_page_1" in out
    assert "2026-07-07" in out
    assert "5" in out  # runs_while_disabled


def test_reset_missing_source_exits_1(db_session, capsys):
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["nonexistent", "--yes"])
    assert exit_code == 1
    err_out = capsys.readouterr()
    assert "not found" in (err_out.out + err_out.err).lower()


def test_reset_untripped_row_is_a_noop(db_session, capsys):
    db_session.add(IngestionState(source="eventim", last_seen_lastmod=None))
    db_session.flush()
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim", "--yes"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no trip state" in out.lower() or "already" in out.lower()


def test_reset_prompts_confirmation_without_yes_flag(db_session, monkeypatch, capsys):
    _seed_tripped(db_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is None


def test_reset_declined_confirmation_leaves_state(db_session, monkeypatch):
    _seed_tripped(db_session)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    with patch("scripts.reset_adapter_lock.SessionLocal", return_value=db_session):
        exit_code = main(["eventim"])
    assert exit_code == 0
    row = db_session.get(IngestionState, "eventim")
    assert row.disabled_at is not None  # still tripped
```

- [ ] **Step 2: Run tests — expect fail**

Run: `cd backend && python -m pytest tests/scripts/test_reset_adapter_lock.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.reset_adapter_lock'`.

- [ ] **Step 3: Create the reset script**

Create `backend/scripts/reset_adapter_lock.py`:

```python
"""Clear a source adapter's circuit-breaker state.

Usage:
    python -m scripts.reset_adapter_lock <source> [--yes]

Prints the current trip state (timestamp, reason, runs_while_disabled) and
asks for confirmation before clearing. Use --yes to skip the prompt.

Reminder: if the trip reason was persistent (e.g. Akamai fingerprint drift),
resetting alone will re-trip on the next run. Verify HTTP headers / adapter
config before running this."""
from __future__ import annotations

import argparse
import sys

from app.db.models.ingestion_state import IngestionState
from app.db.session import SessionLocal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clear a source adapter's circuit-breaker state.")
    parser.add_argument("source", help="Adapter source name (e.g. 'eventim')")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args(argv)

    session = SessionLocal()
    try:
        row = session.get(IngestionState, args.source)
        if row is None:
            print(f"error: source '{args.source}' not found in ingestion_state", file=sys.stderr)
            return 1
        if row.disabled_at is None:
            print(f"'{args.source}' is not tripped — no trip state to clear.")
            return 0

        print(f"Current trip state for '{args.source}':")
        print(f"  disabled_at:         {row.disabled_at.isoformat()}")
        print(f"  disabled_reason:     {row.disabled_reason}")
        print(f"  runs_while_disabled: {row.runs_while_disabled}")
        print()
        print("Reminder: verify HTTP headers / adapter config before resetting,")
        print("otherwise the breaker will re-trip on the next run.")
        print()

        if not args.yes:
            resp = input(f"Reset '{args.source}' circuit breaker? [y/N]: ").strip().lower()
            if resp not in ("y", "yes"):
                print("aborted.")
                return 0

        row.disabled_at = None
        row.disabled_reason = None
        row.runs_while_disabled = 0
        session.commit()
        print(f"'{args.source}' circuit breaker reset.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Ensure `tests/scripts/__init__.py` exists**

Run: `test -f backend/tests/scripts/__init__.py || touch backend/tests/scripts/__init__.py`

- [ ] **Step 5: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/scripts/test_reset_adapter_lock.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/reset_adapter_lock.py backend/tests/scripts/test_reset_adapter_lock.py
git commit -m "feat(scripts): reset_adapter_lock CLI for circuit-breaker unlock"
```

---

## Task 8: Scheduler integration + tripped summary line

Register `EventimAdapter()` in the default adapter list. Add a per-adapter summary line at the end of `run_ingestion` that prints a distinctive `*** SKIPPED - CIRCUIT BREAKER TRIPPED ***` marker when the adapter was skipped due to trip state.

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
from datetime import datetime, timezone
from typing import Iterator

import logging

from app.db.models.ingestion_state import IngestionState
from app.ingestion.normalize import NormalizedEvent
from app.ingestion.scheduler import run_ingestion


class _TrippedAdapter:
    """Adapter that mimics an Eventim-style tripped-breaker no-op fetch."""
    name = "eventim"

    def fetch(self, session) -> Iterator[NormalizedEvent]:
        # Real adapter would log its own banner + return. We just return.
        return
        yield  # pragma: no cover


def test_scheduler_summary_marks_tripped_adapter(db_session, fake_classifier, caplog):
    db_session.add(IngestionState(
        source="eventim",
        last_seen_lastmod=None,
        disabled_at=datetime(2026, 7, 7, 14, 22, tzinfo=timezone.utc),
        disabled_reason="all_categories_failed_page_1",
        runs_while_disabled=0,
    ))
    db_session.flush()
    with caplog.at_level(logging.INFO):
        run_ingestion(
            adapters=[_TrippedAdapter(), _OkAdapter()],
            session=db_session,
            classifier=fake_classifier,
        )
    lines = [rec.message for rec in caplog.records]
    joined = "\n".join(lines)
    assert "*** SKIPPED - CIRCUIT BREAKER TRIPPED ***" in joined
    assert "eventim" in joined
```

- [ ] **Step 2: Run test — expect fail**

Run: `cd backend && python -m pytest tests/ingestion/test_scheduler.py::test_scheduler_summary_marks_tripped_adapter -v`
Expected: assertion fails — the `*** SKIPPED ***` marker isn't emitted yet.

- [ ] **Step 3: Add tripped-summary to scheduler**

In `backend/app/ingestion/scheduler.py`:

**A.** Import `IngestionState` at the top:

```python
from app.db.models.ingestion_state import IngestionState
```

**B.** Register the Eventim adapter — replace the `_default_adapters` function:

```python
def _default_adapters(wiki_client: httpx.Client | None = None) -> list[SourceAdapter]:
    from app.ingestion.eventim import EventimAdapter
    return [
        TicketmasterAdapter(wiki_client=wiki_client),
        HamburgScraper(),
        TheaterHamburgAdapter(),
        OhschonhellScraper(),
        EventimAdapter(),
    ]
```

**C.** Track per-adapter batch sizes and emit summary at end of `run_ingestion`. Inside the `try:` block, near the existing `for adapter in adapters:` loop, keep a dict of `adapter.name → len(batch)`. After the ingest completes, emit a summary block.

Replace the ingestion loop and the "Ingestion complete" log with:

```python
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events = []
        per_adapter_counts: dict[str, int | None] = {}  # None = tripped/skipped
        logger.info("stage: fetch (%d sources)", len(adapters))
        for adapter in adapters:
            state = session.get(IngestionState, adapter.name)
            tripped = state is not None and state.disabled_at is not None
            logger.info("[%s] fetch starting", adapter.name)
            t0 = time.monotonic()
            try:
                batch = list(adapter.fetch(session))
                elapsed = time.monotonic() - t0
                logger.info("[%s] fetched %d events in %.1fs", adapter.name, len(batch), elapsed)
            except Exception:
                logger.exception(
                    "[%s] fetch failed after %.1fs — skipping",
                    adapter.name, time.monotonic() - t0,
                )
                per_adapter_counts[adapter.name] = None
                continue
            all_events.extend(batch)
            # If the adapter was tripped, it returned an empty batch on purpose.
            per_adapter_counts[adapter.name] = None if (tripped and not batch) else len(batch)

        logger.info("stage: categorization (%d events)", len(all_events))
        for ev in all_events:
            ev.category = refine_category(ev, cache, classifier)

        logger.info("stage: upsert")
        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        logger.info("stage: dedup")
        dedup_events(session)
        logger.info("stage: embedding")
        embed_new_events(session)

        if own_session:
            session.commit()

        # Per-adapter summary at end of run
        logger.info("ingest summary:")
        name_w = max(len(a.name) for a in adapters)
        for adapter in adapters:
            n = per_adapter_counts.get(adapter.name)
            if n is None:
                logger.info(
                    "  %-*s : *** SKIPPED - CIRCUIT BREAKER TRIPPED *** (see WARNING above)",
                    name_w, adapter.name,
                )
            else:
                logger.info("  %-*s : %d events", name_w, adapter.name, n)

        logger.info(
            "Ingestion complete — inserted=%d updated=%d skipped=%d",
            report.inserted, report.updated, report.skipped,
        )
        return report
```

**Note:** the "skipped" marker fires when the adapter both had `disabled_at` set AND returned an empty batch — this correctly distinguishes a tripped adapter from one that legitimately found no events.

- [ ] **Step 4: Run tests — expect pass**

Run: `cd backend && python -m pytest tests/ingestion/test_scheduler.py -v`
Expected: all scheduler tests pass, including the new one.

- [ ] **Step 5: Run full suite for regressions**

Run: `cd backend && python -m pytest -x -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): register EventimAdapter; SKIPPED summary for tripped adapters"
```

---

## Task 9: Recon — fill in `_CATEGORY_MAP` gaps from live probe

Run the adapter against the live API in a short "probe" mode to log the union of encountered leaf category names. Merge any missing entries into `_CATEGORY_MAP` before considering the feature complete.

**Files:**
- Modify: `backend/app/ingestion/eventim.py` (append discovered leaves to `_CATEGORY_MAP`)

- [ ] **Step 1: Run a targeted probe to enumerate leaves**

Run this one-liner from `backend/`:

```bash
python -c "
import httpx, json
from app.ingestion.eventim import _DEFAULT_HEADERS, _API, _CATEGORIES
seen = set()
with httpx.Client(timeout=20, headers=_DEFAULT_HEADERS) as c:
    for cat in _CATEGORIES:
        r = c.get(_API, params={'city_names':'Hamburg','categories':cat,'webId':'web__eventim-de','language':'de','page':1,'top':50,'sort':'DateAsc'})
        for p in r.json().get('products', []):
            for entry in p.get('categories', []):
                if entry.get('parentCategory'):
                    seen.add(entry['name'])
print(sorted(seen))
"
```

Expected: printed list of leaf category names. Compare against `_CATEGORY_MAP` keys.

- [ ] **Step 2: Add any missing entries to `_CATEGORY_MAP`**

For each leaf **not** already in `_CATEGORY_MAP`, add an entry. Mapping heuristic:

| Parent | Sub-word contains | → EventCategory |
|---|---|---|
| Konzerte | any | `concerts` |
| Kultur | "Konzert" | `concerts` |
| Kultur | "Oper", "Theater", "Ballett", "Tanz", "Musical" | `theater` |
| Musical & Show | "Musical" | `theater` |
| Musical & Show | otherwise (Show, Ice, Zirkus, …) | `other` |
| Sport | any | `sports` |

If a leaf is genuinely ambiguous, fall back to `other` and rely on the LLM categorizer.

- [ ] **Step 3: Update the category-map test to cover new entries**

Add each new key/value to the `expected` dict in `test_category_map_covers_all_known_leaves`.

- [ ] **Step 4: Run parser tests**

Run: `cd backend && python -m pytest tests/ingestion/test_eventim_parser.py -v`
Expected: all tests pass, including the extended map coverage test.

- [ ] **Step 5: Commit (only if entries added)**

```bash
git add backend/app/ingestion/eventim.py backend/tests/ingestion/test_eventim_parser.py
git commit -m "chore(eventim): extend category map from live-probe recon"
```

If step 1's probe returned nothing new, skip this commit.

---

## Task 10: Smoke test — run adapter live, dry-run

Verify the adapter works end-to-end against the real Eventim API without polluting the DB.

- [ ] **Step 1: Run the adapter live via a small harness**

Run from `backend/`:

```bash
python -c "
import logging
logging.basicConfig(level=logging.INFO)
from app.db import run_migrations
from app.db.session import SessionLocal
from app.ingestion.eventim import EventimAdapter
run_migrations()
s = SessionLocal()
adapter = EventimAdapter()
events = list(adapter.fetch(s))
s.rollback()
s.close()
print(f'yielded {len(events)} events')
print('sample:', events[0].title if events else None, '/', events[0].category if events else None)
"
```

Expected: `yielded 6000-8000 events` (order-of-magnitude — depends on current Eventim inventory) and a sensible title/category on the sample.

- [ ] **Step 2: Verify no circuit breaker trip**

Run: `cd backend && python -c "from app.db.session import SessionLocal; from app.db.models.ingestion_state import IngestionState; s = SessionLocal(); row = s.get(IngestionState, 'eventim'); print('tripped:', row is not None and row.disabled_at is not None); s.close()"`
Expected: `tripped: False`.

- [ ] **Step 3: Full-suite sanity check**

Run: `cd backend && python -m pytest -x -q`
Expected: all tests pass.

No commit for this task — it's verification only.

---

## Summary

10 tasks, each a small self-contained commit:

1. DB migration + model update
2. Retry helper `get_json_with_retry`
3. Parser + category map + fixtures
4. `EventimAdapter` pagination (no breaker)
5. Circuit breaker — check on entry
6. Circuit breaker — mid-run trip conditions
7. `reset_adapter_lock.py` CLI
8. Scheduler wiring + tripped summary line
9. Recon to fill category-map gaps
10. Live smoke test (verification, no commit)

Tasks 1–8 are TDD in the classical sense: red → minimal green → commit. Tasks 9–10 are verification/hardening against real-world inputs and don't follow strict red-green.
