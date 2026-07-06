# ohschonhell.de Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `OhschonhellScraper` that ingests Hamburg party events via a sitemap-delta strategy backed by a new generic `ingestion_state` table, plus scheduler cross-cut logging so long runs are observable.

**Architecture:** Ten tasks in dependency order. State store (model + migration + helpers) comes first because the adapter depends on it. Then a one-line-per-adapter Protocol signature change to thread the session into `.fetch()`. Then TDD-style bottom-up: fixtures → parser → sitemap filter → retry helper → adapter integration → registration → scheduler logging.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Alembic, httpx, BeautifulSoup 4, pytest. Existing patterns in `backend/app/ingestion/scrapers/hamburg.py` and `theater_hamburg.py` are the reference style.

**Spec:** `docs/specs/2026-07-06-ohschonhell-scraper-design.md`

**Working directory for all pytest/git commands:** `C:\Users\alexf\projects\event-tracker\backend\` unless noted otherwise.

---

## Task 1: `IngestionState` Model + Alembic Migration

**Files:**
- Create: `backend/app/db/models/ingestion_state.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/app/db/migrations/versions/0008_ingestion_state.py`

- [ ] **Step 1: Write the model**

Create `backend/app/db/models/ingestion_state.py`:

```python
from sqlalchemy import Column, DateTime, String

from app.db.base import Base


class IngestionState(Base):
    """Per-source cursor used by scrapers with sitemap-delta or feed-poll
    discovery. `last_seen_lastmod` is the highest source-side modification
    timestamp the scraper has successfully processed."""

    __tablename__ = "ingestion_state"

    source = Column(String, primary_key=True)
    last_seen_lastmod = Column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 2: Register the model in `__init__.py`**

Modify `backend/app/db/models/__init__.py`. Add the import and export:

```python
"""SQLAlchemy ORM models. Re-exports for convenience."""
from app.db.models.appointment import Appointment
from app.db.models.chat_message import ChatMessage
from app.db.models.digest_cache import DigestCache
from app.db.models.event import Event
from app.db.models.event_category_cache import EventCategoryCache  # noqa: F401
from app.db.models.feedback import Feedback
from app.db.models.ingestion_state import IngestionState
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User

__all__ = ["Appointment", "ChatMessage", "DigestCache", "Event", "EventCategoryCache", "Feedback", "IngestionState", "SavedEvent", "User"]
```

- [ ] **Step 3: Write the Alembic migration**

Create `backend/app/db/migrations/versions/0008_ingestion_state.py`:

```python
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
```

- [ ] **Step 4: Verify the migration graph is consistent**

Run from `backend/`:

```
python -m alembic heads
```

Expected: exactly one head, `0008_ingestion_state`.

- [ ] **Step 5: Verify the migration applies against a fresh DB**

Run from `backend/`:

```
python -m pytest tests/db -v
```

Expected: PASS. The existing test suite creates tables via `Base.metadata.create_all` and does not fail even when a new model is added.

- [ ] **Step 6: Commit**

```
git add backend/app/db/models/ingestion_state.py backend/app/db/models/__init__.py backend/app/db/migrations/versions/0008_ingestion_state.py
git commit -m "feat(db): add ingestion_state table for scraper cursors"
```

---

## Task 2: State Helper Module + Tests

**Files:**
- Create: `backend/app/ingestion/state.py`
- Create: `backend/tests/ingestion/test_state.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ingestion/test_state.py`:

```python
from datetime import datetime, timezone

from app.ingestion.state import get_last_seen, set_last_seen


def test_get_last_seen_returns_none_when_absent(db_session):
    assert get_last_seen(db_session, "ohschonhell") is None


def test_set_then_get_roundtrip(db_session):
    ts = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    set_last_seen(db_session, "ohschonhell", ts)
    db_session.flush()
    got = get_last_seen(db_session, "ohschonhell")
    assert got == ts
    assert got.tzinfo is not None


def test_set_last_seen_overwrites_unconditionally(db_session):
    newer = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    older = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    set_last_seen(db_session, "ohschonhell", newer)
    db_session.flush()
    set_last_seen(db_session, "ohschonhell", older)
    db_session.flush()
    assert get_last_seen(db_session, "ohschonhell") == older


def test_set_last_seen_two_sources_independent(db_session):
    ts_a = datetime(2026, 7, 1, tzinfo=timezone.utc)
    ts_b = datetime(2026, 7, 6, tzinfo=timezone.utc)
    set_last_seen(db_session, "source_a", ts_a)
    set_last_seen(db_session, "source_b", ts_b)
    db_session.flush()
    assert get_last_seen(db_session, "source_a") == ts_a
    assert get_last_seen(db_session, "source_b") == ts_b
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_state.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.ingestion.state'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/ingestion/state.py`:

```python
"""Per-source cursor for scrapers that need to remember `last_seen_lastmod`.

Both helpers operate on the caller's session without committing. Callers are
responsible for their own transaction boundary. `set_last_seen` overwrites
unconditionally — the calling adapter owns the semantics of what the
timestamp means."""
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.ingestion_state import IngestionState


def get_last_seen(session: Session, source: str) -> datetime | None:
    row = session.get(IngestionState, source)
    if row is None:
        return None
    ts = row.last_seen_lastmod
    # SQLite drops tzinfo on read; re-attach as UTC so callers get an aware datetime.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def set_last_seen(session: Session, source: str, ts: datetime) -> None:
    row = session.get(IngestionState, source)
    if row is None:
        row = IngestionState(source=source, last_seen_lastmod=ts)
        session.add(row)
    else:
        row.last_seen_lastmod = ts
```

- [ ] **Step 4: Run test to verify it passes**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_state.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/state.py backend/tests/ingestion/test_state.py
git commit -m "feat(ingestion): add per-source last_seen cursor helpers"
```

---

## Task 3: `SourceAdapter.fetch(session)` Signature Change

**Files:**
- Modify: `backend/app/ingestion/base.py`
- Modify: `backend/app/ingestion/scrapers/hamburg.py:71`
- Modify: `backend/app/ingestion/scrapers/theater_hamburg.py` (`fetch` method)
- Modify: `backend/app/ingestion/ticketmaster.py:68`
- Modify: `backend/app/ingestion/eventbrite.py` (`fetch` method — if present, else skip)
- Modify: `backend/app/ingestion/scheduler.py:102`
- Modify: `backend/tests/ingestion/test_scheduler.py` (adapters used inline)

- [ ] **Step 1: Update the Protocol**

Modify `backend/app/ingestion/base.py`:

```python
from typing import Iterator, Protocol

from sqlalchemy.orm import Session

from app.ingestion.normalize import NormalizedEvent


class SourceAdapter(Protocol):
    name: str

    def fetch(self, session: Session) -> Iterator[NormalizedEvent]: ...
```

- [ ] **Step 2: Update `HamburgScraper.fetch`**

Modify `backend/app/ingestion/scrapers/hamburg.py`, method signature at line 71:

```python
    def fetch(self, session) -> Iterator[NormalizedEvent]:
```

The rest of the method body is unchanged. Do NOT add `from sqlalchemy.orm import Session` — the parameter is untyped-locally, we just accept and ignore.

- [ ] **Step 3: Update `TheaterHamburgAdapter.fetch`**

Modify `backend/app/ingestion/scrapers/theater_hamburg.py`, the `fetch` method's signature:

Change:
```python
    def fetch(self) -> Iterator[NormalizedEvent]:
```
To:
```python
    def fetch(self, session) -> Iterator[NormalizedEvent]:
```

Body unchanged.

- [ ] **Step 4: Update `TicketmasterAdapter.fetch`**

Modify `backend/app/ingestion/ticketmaster.py:68`:

```python
    def fetch(self, session) -> Iterator[NormalizedEvent]:
```

Body unchanged.

- [ ] **Step 5: Update `EventbriteAdapter.fetch` (if the file exists)**

Check `backend/app/ingestion/eventbrite.py`. If it defines a `fetch` method, update its signature the same way (`def fetch(self, session) -> …`). If the file is unused/stub, skip this step.

- [ ] **Step 6: Update scheduler call site**

Modify `backend/app/ingestion/scheduler.py:102`. Change:

```python
                batch = list(adapter.fetch())
```

To:

```python
                batch = list(adapter.fetch(session))
```

- [ ] **Step 7: Update inline test adapters in `test_scheduler.py`**

Modify `backend/tests/ingestion/test_scheduler.py`. Every inline adapter class that defines `fetch`. Search for `def fetch(self)` in the file — change every occurrence to `def fetch(self, session)`. This covers `_OkAdapter`, `_FailAdapter`, `_OkAdapter2` (in `test_aggregates_across_adapters`), and any others defined further down.

- [ ] **Step 8: Run the full ingestion test suite to verify no regressions**

Run from `backend/`:

```
python -m pytest tests/ingestion -v
```

Expected: all existing tests PASS. New `test_state.py` tests PASS. No test refers to the old zero-arg `fetch()`.

- [ ] **Step 9: Commit**

```
git add backend/app/ingestion/base.py backend/app/ingestion/scrapers/hamburg.py backend/app/ingestion/scrapers/theater_hamburg.py backend/app/ingestion/ticketmaster.py backend/app/ingestion/eventbrite.py backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "refactor(ingestion): thread session into SourceAdapter.fetch()"
```

If `eventbrite.py` was unchanged in step 5, drop it from the `git add` line.

---

## Task 4: Ohschonhell Test Fixtures

**Files:**
- Create: `backend/tests/fixtures/ohschonhell_sitemap_sample.xml`
- Create: `backend/tests/fixtures/ohschonhell_event_full.html`
- Create: `backend/tests/fixtures/ohschonhell_event_minimal.html`

- [ ] **Step 1: Fetch the sitemap fixture**

From project root (`C:\Users\alexf\projects\event-tracker`), run:

```
curl -s -A "Mozilla/5.0" https://ohschonhell.de/post-sitemap26.xml -o backend/tests/fixtures/ohschonhell_sitemap_sample.xml
```

Trim the file to keep only the first ~5 `<url>` entries plus the closing `</urlset>` tag. Open the file in an editor and delete inner entries until 5 remain — the entries are self-contained blocks between `<url>` and `</url>`.

Verify with:

```
grep -c "<url>" backend/tests/fixtures/ohschonhell_sitemap_sample.xml
```

Expected: `5`.

- [ ] **Step 2: Fetch the full-event fixture**

```
curl -s -A "Mozilla/5.0" https://ohschonhell.de/date/rote-flora-hamburg-10-07-2026-vira-lata-caramelo-rave -o backend/tests/fixtures/ohschonhell_event_full.html
```

Verify the file contains the microdata:

```
grep -c "itemprop=startDate" backend/tests/fixtures/ohschonhell_event_full.html
```

Expected: at least `1`. If the specific URL returns 404 (event was removed by the site), pick another URL from `backend/tests/fixtures/ohschonhell_sitemap_sample.xml` and fetch that instead.

- [ ] **Step 3: Fetch the minimal-event fixture**

Choose an event with a very short description (line-up only). Candidates from earlier probe: URLs matching `hamburg-\d\d-\d\d-2026-lehar`, `sven-vaeth`, or similar single-name events. Or run the probe script (`python -m scripts.probe_ohschonhell --limit 20` from `backend/`) again to find current ones.

Once identified:

```
curl -s -A "Mozilla/5.0" "<URL>" -o backend/tests/fixtures/ohschonhell_event_minimal.html
```

- [ ] **Step 4: Commit fixtures**

```
git add backend/tests/fixtures/ohschonhell_sitemap_sample.xml backend/tests/fixtures/ohschonhell_event_full.html backend/tests/fixtures/ohschonhell_event_minimal.html
git commit -m "test(fixtures): add ohschonhell.de sitemap + event HTML snapshots"
```

---

## Task 5: Ohschonhell Parser (Pure Function) + Tests

**Files:**
- Create: `backend/app/ingestion/scrapers/ohschonhell.py` (initial version with parser only)
- Create: `backend/tests/ingestion/test_ohschonhell_parser.py`

- [ ] **Step 1: Write the failing parser tests**

Create `backend/tests/ingestion/test_ohschonhell_parser.py`:

```python
from pathlib import Path

import pytest

from app.ingestion.scrapers.ohschonhell import parse_event

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _read(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8", errors="replace")


def test_parses_full_event_all_fields():
    parsed = parse_event(_read("ohschonhell_event_full.html"))
    assert parsed is not None
    assert parsed["event_id"].isdigit()
    assert parsed["name"]
    assert parsed["date"]  # ISO date string YYYY-MM-DD
    assert parsed["time"]  # HH:MM string
    assert parsed["description"]
    assert parsed["venue_name"]
    assert parsed["street"]
    assert parsed["postal_code"]
    assert parsed["city"]


def test_parses_minimal_event_short_description():
    parsed = parse_event(_read("ohschonhell_event_minimal.html"))
    assert parsed is not None
    # Minimal events have very short descriptions but MUST still parse.
    assert parsed["event_id"]
    assert parsed["name"]
    assert parsed["date"]
    assert parsed["venue_name"]


def test_missing_time_returns_none():
    # Take the full page and strip the time from the display text.
    html = _read("ohschonhell_event_full.html")
    # Remove any 'HH:MM' substrings inside itemprop=startDate elements.
    import re
    stripped = re.sub(
        r'(itemprop=startDate[^>]*>)[^<]*',
        r'\1' + "no-time-here",
        html,
    )
    assert parse_event(stripped) is None


def test_missing_event_id_returns_none():
    html = _read("ohschonhell_event_full.html")
    import re
    stripped = re.sub(r"eventId=\d+", "eventId=", html)
    assert parse_event(stripped) is None


def test_umlauts_decoded_correctly():
    parsed = parse_event(_read("ohschonhell_event_full.html"))
    assert parsed is not None
    combined = " ".join([parsed["name"], parsed["description"] or "", parsed["venue_name"] or ""])
    assert "�" not in combined  # no U+FFFD replacement char
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_parser.py -v
```

Expected: FAIL with `ImportError: cannot import name 'parse_event' from 'app.ingestion.scrapers.ohschonhell'` (or file not found).

- [ ] **Step 3: Create the parser module**

Create `backend/app/ingestion/scrapers/ohschonhell.py`:

```python
"""ohschonhell.de party-event adapter.

Fetches upcoming Hamburg parties from ohschonhell.de using a
sitemap-delta strategy (see docs/specs/2026-07-06-ohschonhell-scraper-design.md).
Detail pages carry schema.org/Event microdata that we parse for
name, start, venue, and address."""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

_EVENT_ID_RE = re.compile(r"eventId=(\d+)")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


def _direct_prop(scope: Tag, name: str) -> Tag | None:
    """Return the itemprop element whose nearest itemscope ancestor is `scope`.

    Schema.org microdata nests scopes (Event → Place → PostalAddress), so
    plain find_all(attrs={"itemprop": name}) returns matches inside nested
    scopes too. This helper enforces direct-child semantics."""
    for el in scope.find_all(attrs={"itemprop": name}):
        parent = el.find_parent(attrs={"itemscope": True})
        if parent is scope:
            return el
    return None


def _val(el: Tag | None) -> str:
    if el is None:
        return ""
    if el.has_attr("content") and el["content"].strip():
        return el["content"].strip()
    return el.get_text(separator=" ", strip=True)


def parse_event(html: str) -> dict[str, Any] | None:
    """Extract a party event from a `/date/{slug}` page's HTML.

    Returns a dict with keys: event_id, name, date (YYYY-MM-DD), time (HH:MM),
    description, venue_name, street, postal_code, city, image_url.
    Returns None if any required field is missing (event_id, name, date,
    time, venue_name)."""
    soup = BeautifulSoup(html, "html.parser")

    event = soup.find(attrs={"itemtype": "http://schema.org/Event"})
    if not isinstance(event, Tag):
        return None

    m = _EVENT_ID_RE.search(html)
    if not m:
        return None
    event_id = m.group(1)

    name = _val(_direct_prop(event, "name"))
    if not name:
        return None

    start_el = _direct_prop(event, "startDate")
    date = start_el["content"].strip() if start_el and start_el.has_attr("content") else ""
    display_text = start_el.get_text(strip=True) if start_el else ""
    time_match = _TIME_RE.search(display_text) if display_text else None
    if not date or not time_match:
        return None
    time_str = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"

    place = event.find(attrs={"itemtype": "http://schema.org/Place"})
    venue_name = _val(_direct_prop(place, "name")) if isinstance(place, Tag) else ""
    if not venue_name:
        return None

    addr = event.find(attrs={"itemtype": "http://schema.org/PostalAddress"})
    street = _val(_direct_prop(addr, "streetAddress")) if isinstance(addr, Tag) else ""
    postal_code = _val(_direct_prop(addr, "postalCode")) if isinstance(addr, Tag) else ""
    city = _val(_direct_prop(addr, "addressLocality")) if isinstance(addr, Tag) else ""

    description = _val(_direct_prop(event, "description")) or None

    og_image_el = soup.find("meta", attrs={"property": "og:image"})
    image_url = og_image_el["content"].strip() if og_image_el and og_image_el.has_attr("content") else None

    return {
        "event_id": event_id,
        "name": name,
        "date": date,
        "time": time_str,
        "description": description,
        "venue_name": venue_name,
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "image_url": image_url,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_parser.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/scrapers/ohschonhell.py backend/tests/ingestion/test_ohschonhell_parser.py
git commit -m "feat(ohschonhell): schema.org microdata parser for detail pages"
```

---

## Task 6: Sitemap Filter (Pure Function) + Tests

**Files:**
- Modify: `backend/app/ingestion/scrapers/ohschonhell.py` (append)
- Create: `backend/tests/ingestion/test_ohschonhell_sitemap.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/ingestion/test_ohschonhell_sitemap.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.scrapers.ohschonhell import filter_sitemap

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _read_sitemap() -> str:
    return (_FIXTURE_DIR / "ohschonhell_sitemap_sample.xml").read_text(encoding="utf-8")


def test_filter_returns_only_date_urls_after_cutoff():
    xml = _read_sitemap()
    # Cutoff old enough that everything in the fixture qualifies.
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert all("/date/" in url for url, _ in entries)
    assert len(entries) >= 1


def test_filter_excludes_entries_before_cutoff():
    xml = _read_sitemap()
    # Cutoff in the future — nothing should qualify.
    cutoff = datetime(2100, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert entries == []


def test_filter_result_sorted_ascending_by_lastmod():
    xml = _read_sitemap()
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    lastmods = [lastmod for _, lastmod in entries]
    assert lastmods == sorted(lastmods)


def test_filter_returns_tz_aware_datetimes():
    xml = _read_sitemap()
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert entries, "fixture must yield entries"
    _, lastmod = entries[0]
    assert lastmod.tzinfo is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_sitemap.py -v
```

Expected: FAIL with `ImportError: cannot import name 'filter_sitemap'`.

- [ ] **Step 3: Append the sitemap filter to ohschonhell.py**

Append to `backend/app/ingestion/scrapers/ohschonhell.py` (after the existing `parse_event` function):

```python
import xml.etree.ElementTree as ET
from datetime import datetime

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def filter_sitemap(xml_body: str, cutoff: datetime) -> list[tuple[str, datetime]]:
    """Return (url, lastmod) tuples for /date/ entries with lastmod > cutoff,
    sorted ascending by lastmod. Callers ensure `cutoff` is tz-aware."""
    root = ET.fromstring(xml_body)
    entries: list[tuple[str, datetime]] = []
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc = (url_el.findtext("sm:loc", "", _SITEMAP_NS) or "").strip()
        lastmod_str = (url_el.findtext("sm:lastmod", "", _SITEMAP_NS) or "").strip()
        if "/date/" not in loc or not lastmod_str:
            continue
        try:
            lastmod = datetime.fromisoformat(lastmod_str)
        except ValueError:
            continue
        if lastmod > cutoff:
            entries.append((loc, lastmod))
    entries.sort(key=lambda x: x[1])
    return entries
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_sitemap.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/scrapers/ohschonhell.py backend/tests/ingestion/test_ohschonhell_sitemap.py
git commit -m "feat(ohschonhell): sitemap delta filter"
```

---

## Task 7: HTTP GET with Retry-Backoff + Tests

**Files:**
- Modify: `backend/app/ingestion/scrapers/ohschonhell.py` (append)
- Create: `backend/tests/ingestion/test_ohschonhell_retry.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/ingestion/test_ohschonhell_retry.py`:

```python
import httpx

from app.ingestion.scrapers.ohschonhell import RetryStats, get_with_retry


class _FakeClient:
    def __init__(self, statuses: list[int], body: str = "<html></html>"):
        self._statuses = list(statuses)
        self._body = body
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        status = self._statuses.pop(0) if self._statuses else 200
        return httpx.Response(status, text=self._body, request=httpx.Request("GET", url))


def test_returns_body_on_first_success():
    stats = RetryStats()
    client = _FakeClient(statuses=[200])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=lambda _s: None)
    assert body == "<html></html>"
    assert stats.total_retries == 0


def test_retries_on_429_then_succeeds():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[429, 200])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is not None
    assert client.calls == 2
    assert stats.total_retries == 1
    assert sleeps == [1.0]


def test_retries_up_to_three_attempts_then_gives_up():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[429, 503, 429])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is None
    assert client.calls == 3
    assert stats.total_retries == 3
    assert stats.exhausted == 1
    assert sleeps == [1.0, 2.0]  # sleeps before attempts 2 and 3; no sleep after final


def test_non_retry_status_returns_none_without_retry():
    stats = RetryStats()
    sleeps: list[float] = []
    client = _FakeClient(statuses=[404])
    body = get_with_retry(client, "https://example.com/x", stats=stats, sleep_fn=sleeps.append)
    assert body is None
    assert client.calls == 1
    assert sleeps == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_retry.py -v
```

Expected: FAIL with `ImportError: cannot import name 'RetryStats'`.

- [ ] **Step 3: Append retry helper to ohschonhell.py**

Append to `backend/app/ingestion/scrapers/ohschonhell.py`:

```python
import logging
from dataclasses import dataclass
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 503}
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_SLEEP = 1.0  # exponential: 1s, 2s, 4s


@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
) -> str | None:
    """GET `url` with exponential backoff on 429/503. Returns body text or None.

    Non-retriable error statuses (e.g. 404) return None without retrying.
    Network exceptions propagate — callers handle them at the sitemap level.
    """
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.content.decode("utf-8", errors="replace")
        if resp.status_code not in _RETRY_STATUS_CODES:
            logger.warning(
                "ohschonhell: unexpected status %d for %s — skipping",
                resp.status_code, url,
            )
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            logger.warning(
                "ohschonhell: %d from %s — sleeping %.1fs (attempt %d/%d)",
                resp.status_code, url, backoff, attempt, _RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            logger.warning(
                "ohschonhell: giving up on %s after %d attempts",
                url, _RETRY_MAX_ATTEMPTS,
            )
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_retry.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/ingestion/scrapers/ohschonhell.py backend/tests/ingestion/test_ohschonhell_retry.py
git commit -m "feat(ohschonhell): HTTP retry-backoff with stats"
```

---

## Task 8: `OhschonhellScraper` Adapter Integration + Tests

**Files:**
- Modify: `backend/app/ingestion/scrapers/ohschonhell.py` (append the class)
- Create: `backend/tests/ingestion/test_ohschonhell_adapter.py`

- [ ] **Step 1: Write the failing adapter tests**

Create `backend/tests/ingestion/test_ohschonhell_adapter.py`:

```python
"""End-to-end adapter tests using a fake httpx client.

Uses hand-rolled minimal sitemap and event HTML — self-contained so tests
don't depend on the exact contents of the on-disk fixtures."""
from datetime import datetime, timezone

import httpx
import pytest

from app.ingestion.scrapers.ohschonhell import OhschonhellScraper
from app.ingestion.state import get_last_seen, set_last_seen


_SITEMAP_TWO = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a</loc>
    <lastmod>2026-07-01T10:00:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://ohschonhell.de/date/venue-b-hamburg-11-07-2026-party-b</loc>
    <lastmod>2026-07-02T11:00:00+00:00</lastmod>
  </url>
</urlset>"""


def _event_html(event_id: str, name: str) -> str:
    return f"""<!doctype html>
<html><head><meta property="og:image" content="https://cdn/{event_id}.jpg"></head>
<body>
<a href="/ajax/ical.php?eventId={event_id}&osh_page=hamburg">cal</a>
<div itemscope itemtype="http://schema.org/Event">
  <span itemprop=name>{name}</span>
  <time itemprop=startDate content="2026-07-10">10.07.2026, 23:00</time>
  <div itemprop=description>Great party</div>
  <div itemprop=location itemscope itemtype="http://schema.org/Place">
    <span itemprop=name>Venue X</span>
    <div itemprop=address itemscope itemtype="http://schema.org/PostalAddress">
      <span itemprop=streetAddress>Beispielstraße 1</span>
      <span itemprop=postalCode>20000</span>
      <span itemprop=addressLocality>Hamburg</span>
    </div>
  </div>
</div>
</body></html>"""


class _FakeClient:
    """Maps URL to sequence of (status, body) responses."""

    def __init__(self, routes: dict[str, list[tuple[int, str]]]):
        self._routes = {u: list(rs) for u, rs in routes.items()}

    def get(self, url: str, **kwargs) -> httpx.Response:
        seq = self._routes.get(url)
        if not seq:
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        status, body = seq.pop(0)
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


@pytest.fixture
def routes_two_events():
    sitemap_url = "https://ohschonhell.de/post-sitemap26.xml"
    url_a = "https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a"
    url_b = "https://ohschonhell.de/date/venue-b-hamburg-11-07-2026-party-b"
    return {
        sitemap_url: [(200, _SITEMAP_TWO)],
        url_a: [(200, _event_html("111", "Party A"))],
        url_b: [(200, _event_html("222", "Party B"))],
    }, url_a, url_b


def test_bootstrap_yields_both_events_and_sets_state(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)

    events = list(scraper.fetch(db_session))
    db_session.flush()

    assert len(events) == 2
    ids = sorted(e.external_id for e in events)
    assert ids == ["111", "222"]
    assert all(e.source == "ohschonhell" for e in events)
    assert all(e.start_datetime.tzinfo is not None for e in events)
    # State advanced to the highest processed lastmod (2026-07-02T11:00Z).
    ts = get_last_seen(db_session, "ohschonhell")
    assert ts == datetime(2026, 7, 2, 11, 0, tzinfo=timezone.utc)


def test_delta_yields_only_new_events(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    # Pre-seed state so entry A (lastmod 2026-07-01T10:00Z) is skipped.
    set_last_seen(
        db_session, "ohschonhell", datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    )
    db_session.flush()

    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))

    assert [e.external_id for e in events] == ["222"]


def test_retry_exhausted_skips_event_and_does_not_advance_state(db_session):
    sitemap_url = "https://ohschonhell.de/post-sitemap26.xml"
    url_a = "https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a"
    routes = {
        sitemap_url: [(200, _SITEMAP_TWO.split("<url>")[0] + "<url>" + _SITEMAP_TWO.split("<url>")[1] + "</urlset>")],
        # only URL A, always 429 -> retry exhausted
        url_a: [(429, ""), (429, ""), (429, "")],
    }
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)

    events = list(scraper.fetch(db_session))
    db_session.flush()

    assert events == []
    # No successful events -> state remains None.
    assert get_last_seen(db_session, "ohschonhell") is None


def test_parse_failure_skips_event_but_continues_batch(db_session, routes_two_events):
    routes, url_a, _ = routes_two_events
    # Overwrite URL A with malformed HTML (no Event microdata).
    routes[url_a] = [(200, "<html><body>nothing here</body></html>")]

    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))

    assert [e.external_id for e in events] == ["222"]
    # State advanced to entry B (only entry that succeeded).
    ts = get_last_seen(db_session, "ohschonhell")
    assert ts == datetime(2026, 7, 2, 11, 0, tzinfo=timezone.utc)


def test_start_datetime_uses_berlin_timezone(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))
    assert events
    # 23:00 Berlin on 10 July 2026 (CEST, UTC+2) = 21:00 UTC.
    for ev in events:
        assert ev.start_datetime.year == 2026
        assert ev.start_datetime.hour == 23
        assert str(ev.start_datetime.tzinfo) == "Europe/Berlin"


def test_venue_address_is_combined_string(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))
    assert events[0].venue_address == "Beispielstraße 1, 20000 Hamburg"
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_adapter.py -v
```

Expected: FAIL with `ImportError: cannot import name 'OhschonhellScraper'`.

- [ ] **Step 3: Append the adapter class to ohschonhell.py**

Append to `backend/app/ingestion/scrapers/ohschonhell.py`:

```python
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Protocol
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.ingestion.normalize import NormalizedEvent
from app.ingestion.state import get_last_seen, set_last_seen

_SITEMAP_URL = "https://ohschonhell.de/post-sitemap26.xml"
_BERLIN = ZoneInfo("Europe/Berlin")
_UA = "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"
_BOOTSTRAP_WINDOW_DAYS = 90
_REQUEST_DELAY_SECONDS = 0.15
_PROGRESS_INTERVAL_SECONDS = 30


class _HttpGetter(Protocol):
    def get(self, url: str, **kwargs) -> httpx.Response: ...


class OhschonhellScraper:
    """Ingest Hamburg party events from ohschonhell.de via sitemap-delta."""

    name = "ohschonhell"

    def __init__(
        self,
        client: _HttpGetter | None = None,
        sleep_fn=time.sleep,
    ):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": _UA}
        )
        self._sleep_fn = sleep_fn

    def fetch(self, session: Session) -> Iterator[NormalizedEvent]:
        last_seen = get_last_seen(session, self.name)
        if last_seen is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_BOOTSTRAP_WINDOW_DAYS)
            logger.info(
                "ohschonhell: bootstrap window %s → %s (%dd, no prior state)",
                cutoff.date(), datetime.now(timezone.utc).date(), _BOOTSTRAP_WINDOW_DAYS,
            )
        else:
            cutoff = last_seen
            logger.info("ohschonhell: delta since %s", cutoff.isoformat())

        sitemap_body = self._client.get(_SITEMAP_URL).text
        candidates = filter_sitemap(sitemap_body, cutoff)
        logger.info("ohschonhell: sitemap yielded %d candidate URL(s)", len(candidates))

        stats = RetryStats()
        skipped_parse = 0
        skipped_retry = 0
        parsed_count = 0
        max_lastmod: datetime | None = None
        last_log_at = time.monotonic()
        n_total = len(candidates)

        for i, (url, lastmod) in enumerate(candidates):
            if i > 0:
                self._sleep_fn(_REQUEST_DELAY_SECONDS)

            body = get_with_retry(self._client, url, stats=stats, sleep_fn=self._sleep_fn)
            if body is None:
                skipped_retry += 1
                continue

            parsed = parse_event(body)
            if parsed is None:
                skipped_parse += 1
                logger.warning("ohschonhell: parse failed for %s — skipping", url)
                continue

            try:
                naive = datetime.fromisoformat(f"{parsed['date']}T{parsed['time']}")
                start_dt = naive.replace(tzinfo=_BERLIN)
            except ValueError:
                skipped_parse += 1
                logger.warning("ohschonhell: bad date/time on %s — skipping", url)
                continue

            slug = url.rsplit("/date/", 1)[-1]
            venue_address = ", ".join(
                p for p in [parsed["street"], f"{parsed['postal_code']} {parsed['city']}".strip()] if p
            ).strip(", ")

            yield NormalizedEvent(
                external_id=parsed["event_id"],
                source=self.name,
                title=parsed["name"],
                description=parsed["description"],
                start_datetime=start_dt,
                venue_name=parsed["venue_name"],
                venue_address=venue_address or None,
                category="party",
                tags=["party"],
                is_free=False,
                currency="EUR",
                image_url=parsed["image_url"],
                source_url=url,
                raw_data={
                    "event_id": parsed["event_id"],
                    "slug": slug,
                    "sitemap_lastmod": lastmod.isoformat(),
                },
            )
            parsed_count += 1
            if max_lastmod is None or lastmod > max_lastmod:
                max_lastmod = lastmod

            now = time.monotonic()
            if now - last_log_at >= _PROGRESS_INTERVAL_SECONDS:
                logger.info(
                    "ohschonhell: progress %d/%d fetched (%d%%)",
                    i + 1, n_total, int((i + 1) * 100 / max(n_total, 1)),
                )
                last_log_at = now

        if max_lastmod is not None:
            set_last_seen(session, self.name, max_lastmod)

        if stats.total_retries > 0:
            avg = stats.total_backoff_seconds / stats.total_retries
            logger.info(
                "ohschonhell: %d retries encountered (avg backoff: %.1fs, exhausted: %d)",
                stats.total_retries, avg, stats.exhausted,
            )
        logger.info(
            "ohschonhell: %d candidates → %d parsed, %d skipped (parse error: %d, retries exhausted: %d)",
            n_total, parsed_count, skipped_parse + skipped_retry, skipped_parse, skipped_retry,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_ohschonhell_adapter.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Run the full ingestion test suite for regressions**

Run from `backend/`:

```
python -m pytest tests/ingestion -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/ingestion/scrapers/ohschonhell.py backend/tests/ingestion/test_ohschonhell_adapter.py
git commit -m "feat(ohschonhell): sitemap-delta adapter with retry + state"
```

---

## Task 9: Register Adapter in Scheduler

**Files:**
- Modify: `backend/app/ingestion/scheduler.py` (imports + `_default_adapters`)

- [ ] **Step 1: Add import and registration**

Modify `backend/app/ingestion/scheduler.py`. Add after the existing scraper imports (around line 22):

```python
from app.ingestion.scrapers.ohschonhell import OhschonhellScraper
```

Then modify `_default_adapters` (around lines 66-71):

```python
def _default_adapters(wiki_client: httpx.Client | None = None) -> list[SourceAdapter]:
    return [
        TicketmasterAdapter(wiki_client=wiki_client),
        HamburgScraper(),
        TheaterHamburgAdapter(),
        OhschonhellScraper(),
    ]
```

- [ ] **Step 2: Run scheduler tests to verify integration**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_scheduler.py -v
```

Expected: all existing PASS (no new tests added here — the adapter's own tests cover its behavior; the scheduler integration is trivial one-line registration).

- [ ] **Step 3: Commit**

```
git add backend/app/ingestion/scheduler.py
git commit -m "feat(scheduler): register OhschonhellScraper in default adapters"
```

---

## Task 10: Scheduler Cross-Cut Logging + Test

**Files:**
- Modify: `backend/app/ingestion/scheduler.py` (`run_ingestion` body)
- Modify: `backend/tests/ingestion/test_scheduler.py` (add a log-assertion test)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
def test_run_ingestion_emits_stage_and_adapter_logs(db_session, fake_classifier, caplog):
    """Ensures the observability-focused log lines fire for every stage
    and per adapter, so long runs are diagnosable from `tail -f`."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="app.ingestion.scheduler")

    run_ingestion(adapters=[_OkAdapter()], session=db_session, classifier=fake_classifier)

    messages = [r.getMessage() for r in caplog.records]
    joined = " || ".join(messages)

    assert "stage: fetch" in joined
    assert "[ok] fetch starting" in joined
    assert "[ok] fetched 1 events" in joined
    assert "stage: categorization" in joined
    assert "stage: upsert" in joined
    assert "stage: dedup" in joined
    assert "stage: embedding" in joined
```

- [ ] **Step 2: Run the test to verify it fails**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_scheduler.py::test_run_ingestion_emits_stage_and_adapter_logs -v
```

Expected: FAIL with assertion errors on missing log strings.

- [ ] **Step 3: Update the scheduler**

Modify `backend/app/ingestion/scheduler.py`. Add `import time` at the top if not already imported. Replace the body of `run_ingestion` (from the try block down to just before `report = upsert_events(...)`) so that the per-adapter loop and the surrounding stage markers look like this:

Replace the block currently at lines 96-113 (approximately):

```python
    try:
        cache = CategoryCache(session, model_name=settings.categorization_model)
        all_events = []
        logger.info("stage: fetch (%d sources)", len(adapters))
        for adapter in adapters:
            logger.info("[%s] fetch starting", adapter.name)
            t0 = time.monotonic()
            try:
                batch = list(adapter.fetch(session))
                logger.info(
                    "[%s] fetched %d events in %.1fs",
                    adapter.name, len(batch), time.monotonic() - t0,
                )
            except Exception:
                logger.exception(
                    "[%s] fetch failed after %.1fs — skipping",
                    adapter.name, time.monotonic() - t0,
                )
                continue
            all_events.extend(batch)

        logger.info("stage: categorization (%d events)", len(all_events))
        for ev in all_events:
            ev.category = refine_category(ev, cache, classifier)

        logger.info("stage: upsert")
        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        logger.info("stage: dedup")
        dedup_events(session)  # logs its own summary
        logger.info("stage: embedding")
        embed_new_events(session)
```

Note two intentional restructurings vs. the current code:
1. Categorization was inside the per-adapter loop; it's moved into its own stage so the log flow matches the actual pipeline shape.
2. The per-adapter INFO line `"%s: fetched %d events"` is replaced by the new bracketed `[name]` format with duration.

- [ ] **Step 4: Run the new test to verify it passes**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_scheduler.py::test_run_ingestion_emits_stage_and_adapter_logs -v
```

Expected: PASS.

- [ ] **Step 5: Run the full scheduler suite for regressions**

Run from `backend/`:

```
python -m pytest tests/ingestion/test_scheduler.py -v
```

Expected: all tests PASS. If any existing test relied on the old `"%s: fetched %d events"` log string, update the assertion to the new bracketed format.

- [ ] **Step 6: Run the entire ingestion test suite for regressions**

Run from `backend/`:

```
python -m pytest tests/ingestion -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): per-adapter and stage lifecycle logs"
```

---

## Final Verification

- [ ] **Run all backend tests**

Run from `backend/`:

```
python -m pytest -v
```

Expected: all tests PASS.

- [ ] **Optional: dry-run against live ohschonhell.de**

Run from `backend/`:

```
python -m scripts.ingest
```

Expected: scheduler runs to completion. Watch for `ohschonhell` progress logs, `stage:` markers, and final `N candidates → M parsed` summary. First run performs the 90-day bootstrap (~600 detail requests, ~90 seconds).

---

## Spec Coverage Checklist

Cross-check against `docs/specs/2026-07-06-ohschonhell-scraper-design.md`:

| Spec section | Implemented in |
|---|---|
| Part A: `ingestion_state` table + `state.py` | Tasks 1, 2 |
| Part B: `OhschonhellScraper` | Tasks 4, 5, 6, 7, 8, 9 |
| Part C: Scheduler cross-cut logging | Task 10 |
| Part D: Tests | Tasks 1, 2, 5, 6, 7, 8, 10 |
| Signature change `fetch(session)` | Task 3 |
| 150 ms delay | Task 8 (`_REQUEST_DELAY_SECONDS`) |
| 90-day bootstrap window | Task 8 (`_BOOTSTRAP_WINDOW_DAYS`) |
| Retry exponential 1s/2s/4s | Task 7 (`_RETRY_BASE_SLEEP`) |
| 30 s progress heartbeat | Task 8 (`_PROGRESS_INTERVAL_SECONDS`) |
| WordPress event_id as external_id | Task 5 (`parse_event`) + Task 8 (adapter mapping) |
| Skip events without time | Task 5 (`parse_event` returns None) + Task 8 |
| Fixture-based parser tests | Tasks 4, 5 |
| Adapter e2e tests with `_FakeClient` | Task 8 |
| State helper tests | Task 2 |
| Scheduler log tests | Task 10 |
