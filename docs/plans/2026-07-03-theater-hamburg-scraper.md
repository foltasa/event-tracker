# Theater-Hamburg Scraper + Post-Ingest Dedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `TheaterHamburgAdapter` (imxplatform GraphQL) as a new event source (~2000 upcoming Hamburg cultural events, ~100 % description coverage) and a `dedup_events()` post-ingest pass that merges cross-source duplicates in favour of theater-hamburg. `saved_events` foreign keys migrated before delete. Idempotent.

**Architecture:** New adapter in `backend/app/ingestion/scrapers/theater_hamburg.py`, structured like `TicketmasterAdapter`: init scrapes JWT from public widget.js, `fetch()` paginates a GraphQL list query, per-permaLink detail query (cached per run) yields `shortDescription`. Expansion: one node × N `eventDates` → N `NormalizedEvent`s. New `dedup_events(session)` in `backend/app/ingestion/dedup.py` groups active rows by (normalized venue, ±60min time, title-Jaccard ≥ 0.5), picks highest `_SOURCE_PRIORITY` winner, migrates `saved_events` FKs, deletes losers. Called from `run_ingestion` between `deactivate_past_events` and `embed_new_events`.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup 4, SQLAlchemy 2.x, pytest — no new dependencies.

**Spec:** `docs/specs/2026-07-03-theater-hamburg-scraper-design.md`.

---

## File Map

| Action | File | Responsibility |
|---|---|---|
| Create | `backend/app/ingestion/dedup.py` | Venue norm, title Jaccard, `dedup_events()` |
| Create | `backend/app/ingestion/scrapers/theater_hamburg.py` | JWT scrape, GraphQL list + detail, mapping |
| Modify | `backend/app/ingestion/scheduler.py` | Register adapter, call dedup |
| Create | `backend/tests/ingestion/test_dedup.py` | Unit tests for helpers + dedup_events |
| Create | `backend/tests/ingestion/test_theater_hamburg.py` | Unit tests for adapter |
| Modify | `backend/tests/ingestion/test_scheduler.py` | Integration test for wiring |
| Create | `backend/tests/fixtures/theater_hamburg_widget_sample.js` | Real widget.js excerpt (JWT extractable) |
| Create | `backend/tests/fixtures/theater_hamburg_search_sample.json` | Real EventSearch response, ≤5 events |
| Create | `backend/tests/fixtures/theater_hamburg_details_sample.json` | Real EventDetails response with `shortDescription` |

---

## Task 0 — Capture live fixtures (recon-preserve)

**Files:**
- Create: `backend/tests/fixtures/theater_hamburg_widget_sample.js`
- Create: `backend/tests/fixtures/theater_hamburg_search_sample.json`
- Create: `backend/tests/fixtures/theater_hamburg_details_sample.json`

We need real API responses as test fixtures — parsers only work against real strings. If the fixture directory or `__init__.py` doesn't exist yet, create them.

- [ ] **Step 0.1: Ensure fixtures directory exists**

Check `backend/tests/fixtures/` exists (created in the Wikipedia-fallback plan). If not, create `backend/tests/fixtures/__init__.py` as an empty file.

- [ ] **Step 0.2: Capture widget.js**

Run from `backend/`:

```bash
python -c "
import httpx, pathlib
r = httpx.get('https://hht.whitelabel.imxplatform.de/widget/widget.js', timeout=15)
r.raise_for_status()
# Save a small excerpt containing the JWT (JWTs are three base64url segments separated by dots, starting 'ey').
# Grep for the token, then save ~200 chars around it as fixture.
import re
m = re.search(r'ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}', r.text)
assert m, 'JWT not found in widget.js — the extraction regex or the URL is stale'
start = max(0, m.start() - 100); end = min(len(r.text), m.end() + 100)
pathlib.Path('tests/fixtures/theater_hamburg_widget_sample.js').write_text(
    r.text[start:end], encoding='utf-8'
)
print('JWT captured, length:', m.end() - m.start())
"
```

Expected: prints `JWT captured, length: 200-400` and creates a small text file. If the assertion fails, the regex needs adjusting to match the real JWT shape before proceeding.

- [ ] **Step 0.3: Extract the JWT for the next steps**

```bash
python -c "
import re, pathlib
text = pathlib.Path('tests/fixtures/theater_hamburg_widget_sample.js').read_text(encoding='utf-8')
m = re.search(r'ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}', text)
print(m.group(0))
" > /tmp/th_jwt.txt
```

On Windows PowerShell replace `> /tmp/th_jwt.txt` with `| Out-File -Encoding ascii $env:TEMP\th_jwt.txt`. Keep the JWT for the next two commands.

- [ ] **Step 0.4: Capture EventSearch response**

Substitute `<JWT>` with the string from step 0.3:

```bash
python -c "
import httpx, json, pathlib
JWT = '<JWT>'
QUERY = '''
query EventSearch(\$filter: EventFilter!, \$pagination: PaginationInput!, \$appearance: AppearanceInput!) {
  events(filter: \$filter, pagination: \$pagination, appearance: \$appearance) {
    nodes {
      id title permaLink
      categories { title }
      contact { location { id title } }
      eventDates { date startTime duration }
      geoInfo { latitude longitude }
      image { deeplink }
      bookingLink
    }
    pagination { totalPages totalRecords }
  }
}'''
FILTER = {'and': [
  {'or': [
    {'eventLocation': {'id': {'oneOf': [6306,99,423,236,121387,1965,494,5359,101488,944,947,117,119,375,248,313,124,100862,1854,767,769,833,898,771,97227,109323,5327,9359,5399,12695,217,92,95,351]}}},
    {'eventLocation': {'group': {'oneOf': [2,3,36,164,171,108,143,175,112,176,17,114,178,19,61]}}}
  ]},
  {'fromDate': '2026-07-03'}
]}
body = {'query': QUERY, 'variables': {'filter': FILTER, 'pagination': {'page': 1, 'pageSize': 5}, 'appearance': {'deliveryChannel': 76}}}
r = httpx.post('https://content-delivery.imxplatform.de/hht/imxplatform',
               json=body, headers={'Authorization': f'Bearer {JWT}'}, timeout=15)
r.raise_for_status()
data = r.json()
pathlib.Path('tests/fixtures/theater_hamburg_search_sample.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
# Grab a permaLink for step 0.5:
permas = [n['permaLink'] for n in data['data']['events']['nodes']]
print('sample permaLinks:', permas)
"
```

Expected: file written with 5 `nodes`, prints their permaLinks. If it errors with 401 or malformed response, the JWT or query shape needs adjustment — halt and report.

- [ ] **Step 0.5: Capture EventDetails response for one of the permaLinks**

Substitute both `<JWT>` and `<PERMALINK>`:

```bash
python -c "
import httpx, json, pathlib
JWT = '<JWT>'
QUERY = 'query EventDetails(\$permalink: String!) { events(filter: {permaLink: {eq: \$permalink}}) { nodes { shortDescription } } }'
body = {'query': QUERY, 'variables': {'permalink': '<PERMALINK>'}}
r = httpx.post('https://content-delivery.imxplatform.de/hht/imxplatform',
               json=body, headers={'Authorization': f'Bearer {JWT}'}, timeout=15)
r.raise_for_status()
data = r.json()
pathlib.Path('tests/fixtures/theater_hamburg_details_sample.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
short = data['data']['events']['nodes'][0].get('shortDescription') or ''
print('shortDescription length:', len(short))
"
```

Expected: `shortDescription length: >200`. If empty, try a different permaLink.

- [ ] **Step 0.6: Sanity-check + commit**

```bash
ls -la tests/fixtures/theater_hamburg_*
git add tests/fixtures/theater_hamburg_widget_sample.js tests/fixtures/theater_hamburg_search_sample.json tests/fixtures/theater_hamburg_details_sample.json
git commit -m "test(fixtures): capture theater-hamburg widget.js + GraphQL samples"
```

---

## Task 1 — Dedup helpers: `_normalize_venue`, `_title_jaccard`

**Files:**
- Create: `backend/app/ingestion/dedup.py`
- Create: `backend/tests/ingestion/test_dedup.py`

Pure functions, no DB. TDD.

- [ ] **Step 1.1: Write the failing tests**

Create `backend/tests/ingestion/test_dedup.py`:

```python
import pytest

from app.ingestion.dedup import _normalize_venue, _title_jaccard


class TestNormalizeVenue:
    def test_lowercase_and_strip(self):
        assert _normalize_venue("  Laeiszhalle  ") == "laeiszhalle"

    def test_strips_parenthesized_hall_suffix(self):
        assert _normalize_venue("Laeiszhalle (Großer Saal)") == "laeiszhalle"
        assert _normalize_venue("Elbphilharmonie (Kleiner Saal)") == "elbphilharmonie"

    def test_splits_camelcase(self):
        assert _normalize_venue("DeutschesSchauSpielHausHamburg") == "deutsches schau spiel haus hamburg"

    def test_collapses_whitespace_runs(self):
        assert _normalize_venue("Thalia   Theater\tHamburg") == "thalia theater hamburg"

    def test_none_and_empty(self):
        assert _normalize_venue(None) == ""
        assert _normalize_venue("") == ""
        assert _normalize_venue("   ") == ""

    def test_combined_camelcase_and_paren(self):
        assert _normalize_venue("JungesSchauSpielHaus (Malersaal)") == "junges schau spiel haus"


class TestTitleJaccard:
    def test_identical_titles_return_one(self):
        assert _title_jaccard("Hamlet", "Hamlet") == 1.0

    def test_case_insensitive(self):
        assert _title_jaccard("Hamlet", "hamlet") == 1.0

    def test_punctuation_stripped(self):
        assert _title_jaccard("Hamlet!", "Hamlet.") == 1.0

    def test_hamlet_with_subtitle(self):
        # {"hamlet"} vs {"hamlet", "premiere"} → 1/2
        assert _title_jaccard("Hamlet", "Hamlet (Premiere)") == pytest.approx(0.5)

    def test_disjoint_titles(self):
        assert _title_jaccard("Batman", "Barbie") == 0.0

    def test_none_or_empty(self):
        assert _title_jaccard(None, "Hamlet") == 0.0
        assert _title_jaccard("Hamlet", None) == 0.0
        assert _title_jaccard("", "") == 0.0

    def test_multi_word_overlap(self):
        # {"der", "kirschgarten"} vs {"kirschgarten"} → 1/2
        assert _title_jaccard("Der Kirschgarten", "Kirschgarten") == pytest.approx(0.5)
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd backend
python -m pytest tests/ingestion/test_dedup.py -v
```

Expected: FAIL — `app.ingestion.dedup` module missing.

- [ ] **Step 1.3: Implement the helpers**

Create `backend/app/ingestion/dedup.py`:

```python
"""Post-ingest deduplication across event sources.

Groups active events by (normalized venue, ±60min start_datetime, title-Jaccard >= 0.5),
picks the highest _SOURCE_PRIORITY winner, migrates saved_events FKs, deletes losers.
Idempotent — a second run finds no cross-source clusters."""
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


_SOURCE_PRIORITY: dict[str, int] = {
    "theater_hamburg": 10,
    "hamburg_scraper": 0,
    "ticketmaster": 0,
}

_TIME_TOLERANCE_MINUTES = 60
_TITLE_JACCARD_MIN = 0.5


def _normalize_venue(name: str | None) -> str:
    """Casefold, strip parenthesized hall suffix, split CamelCase, collapse whitespace."""
    if not name:
        return ""
    # Strip trailing " (Anything)" suffix (hall / room designations).
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Insert space before uppercase runs so "DeutschesSchauSpielHaus" -> "Deutsches Schau Spiel Haus".
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stripped)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    # Collapse any whitespace to single spaces.
    collapsed = re.sub(r"\s+", " ", spaced).strip().lower()
    return collapsed


def _title_jaccard(a: str | None, b: str | None) -> float:
    """Token-set Jaccard on lower-cased, punctuation-stripped titles."""
    def tokens(s: str | None) -> set[str]:
        if not s:
            return set()
        cleaned = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE).lower()
        return {t for t in cleaned.split() if t}

    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    inter = ta & tb
    return len(inter) / len(union)
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
python -m pytest tests/ingestion/test_dedup.py -v
```

Expected: 13 PASS.

- [ ] **Step 1.5: Commit**

```bash
git add backend/app/ingestion/dedup.py backend/tests/ingestion/test_dedup.py
git commit -m "feat(dedup): pure helpers _normalize_venue + _title_jaccard"
```

---

## Task 2 — `dedup_events()` core algorithm

**Files:**
- Modify: `backend/app/ingestion/dedup.py`
- Modify: `backend/tests/ingestion/test_dedup.py`

DB-level test with in-memory sqlite. Uses the existing `db_session` fixture.

- [ ] **Step 2.1: Write the failing tests**

Append to `backend/tests/ingestion/test_dedup.py`:

```python
from datetime import datetime, timedelta, timezone

from app.db.models import Event
from app.db.models.saved_event import SavedEvent
from app.db.models.user import User
from app.ingestion.dedup import DedupReport, dedup_events


def _make_event(
    session,
    *,
    id_: str,
    external_id: str,
    source: str,
    title: str,
    venue_name: str | None,
    start: datetime,
    description: str = "Description.",
    is_active: bool = True,
    created_at: datetime | None = None,
) -> Event:
    ev = Event(
        id=id_,
        external_id=external_id,
        source=source,
        title=title,
        description=description,
        start_datetime=start,
        venue_name=venue_name,
        category="theater",
        tags=[],
        is_free=False,
        currency="EUR",
        source_url=f"https://x/{id_}",
        raw_data={},
        is_active=is_active,
    )
    if created_at is not None:
        ev.ingested_at = created_at
    session.add(ev)
    session.commit()
    return ev


def _make_user(session, id_: str = "u1") -> User:
    u = User(id=id_)
    session.add(u)
    session.commit()
    return u


_NOW = datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc)


class TestDedupEvents:
    def test_no_events_no_ops(self, db_session):
        report = dedup_events(db_session)
        assert report == DedupReport(groups_found=0, rows_merged=0, saved_events_migrated=0)

    def test_theater_hamburg_wins_over_ticketmaster(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle (Großer Saal)", start=_NOW)

        report = dedup_events(db_session)
        assert report.rows_merged == 1
        remaining = {e.id for e in db_session.query(Event).all()}
        assert remaining == {"th"}

    def test_saved_events_fk_migrated_before_delete(self, db_session):
        u = _make_user(db_session)
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        db_session.add(SavedEvent(id="s1", user_id=u.id, event_id="tm"))
        db_session.commit()

        dedup_events(db_session)
        remaining_save = db_session.query(SavedEvent).one()
        assert remaining_save.event_id == "th"

    def test_title_jaccard_below_threshold_prevents_multi_screen_dedup(self, db_session):
        _make_event(db_session, id_="ev1", external_id="e1", source="theater_hamburg",
                    title="Batman", venue_name="CinemaxX Dammtor", start=_NOW)
        _make_event(db_session, id_="ev2", external_id="e2", source="ticketmaster",
                    title="Barbie", venue_name="CinemaxX Dammtor", start=_NOW)

        report = dedup_events(db_session)
        assert report.rows_merged == 0
        assert {e.id for e in db_session.query(Event).all()} == {"ev1", "ev2"}

    def test_time_tolerance_across_bucket_boundaries(self, db_session):
        _make_event(db_session, id_="a", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW.replace(minute=59))
        _make_event(db_session, id_="b", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW.replace(hour=_NOW.hour + 1, minute=0))
        report = dedup_events(db_session)
        assert report.rows_merged == 1

    def test_time_over_tolerance_not_deduped(self, db_session):
        _make_event(db_session, id_="a", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia Theater", start=_NOW)
        _make_event(db_session, id_="b", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Thalia Theater",
                    start=_NOW + timedelta(minutes=90))
        report = dedup_events(db_session)
        assert report.rows_merged == 0

    def test_camelcase_venue_normalization(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Faust", venue_name="Deutsches Schauspielhaus Hamburg", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Faust", venue_name="DeutschesSchauSpielHausHamburg", start=_NOW)
        report = dedup_events(db_session)
        assert report.rows_merged == 1
        assert {e.id for e in db_session.query(Event).all()} == {"th"}

    def test_ties_by_priority_broken_by_older_created_at(self, db_session):
        older = datetime(2026, 6, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 6, 2, tzinfo=timezone.utc)
        _make_event(db_session, id_="old_tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia", start=_NOW, created_at=older)
        _make_event(db_session, id_="new_tm", external_id="e2", source="ticketmaster",
                    title="Hamlet", venue_name="Thalia", start=_NOW, created_at=newer)
        dedup_events(db_session)
        assert {e.id for e in db_session.query(Event).all()} == {"old_tm"}

    def test_idempotent_second_run_is_no_op(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        first = dedup_events(db_session)
        second = dedup_events(db_session)
        assert first.rows_merged == 1
        assert second.rows_merged == 0

    def test_inactive_events_ignored(self, db_session):
        _make_event(db_session, id_="tm", external_id="e1", source="ticketmaster",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW, is_active=False)
        _make_event(db_session, id_="th", external_id="e2", source="theater_hamburg",
                    title="Hamlet", venue_name="Laeiszhalle", start=_NOW)
        report = dedup_events(db_session)
        assert report.rows_merged == 0
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
python -m pytest tests/ingestion/test_dedup.py -v
```

Expected: helper tests still pass; new dedup tests FAIL with ImportError.

- [ ] **Step 2.3: Implement `dedup_events()`**

Append to `backend/app/ingestion/dedup.py`:

```python
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.models import Event
from app.db.models.saved_event import SavedEvent


@dataclass
class DedupReport:
    groups_found: int = 0
    rows_merged: int = 0
    saved_events_migrated: int = 0


def _time_bucket(dt: datetime) -> int:
    """60-min bucket key from a UTC datetime."""
    epoch_minutes = int(dt.timestamp()) // 60
    return epoch_minutes // _TIME_TOLERANCE_MINUTES


def _match(a: Event, b: Event) -> bool:
    """Two active events are the same show iff normalized venue + time + title match."""
    if _normalize_venue(a.venue_name) != _normalize_venue(b.venue_name):
        return False
    delta = abs((a.start_datetime - b.start_datetime).total_seconds()) / 60
    if delta > _TIME_TOLERANCE_MINUTES:
        return False
    if _title_jaccard(a.title, b.title) < _TITLE_JACCARD_MIN:
        return False
    return True


def _winner_key(ev: Event) -> tuple[int, float]:
    """Higher priority wins; on ties, the older row wins (stability)."""
    priority = _SOURCE_PRIORITY.get(ev.source, 0)
    # Negate timestamp so max() picks the smallest (oldest).
    return (priority, -ev.ingested_at.timestamp())


def dedup_events(session: Session) -> DedupReport:
    """Deduplicate active events across sources. Idempotent. Runs in the caller's transaction."""
    active = session.query(Event).filter(Event.is_active.is_(True)).all()

    # Coarse bucket: (normalized venue, time bucket). Compare against bucket and bucket+1
    # so the ±60min window is preserved across bucket boundaries.
    buckets: dict[tuple[str, int], list[Event]] = {}
    for ev in active:
        key = (_normalize_venue(ev.venue_name), _time_bucket(ev.start_datetime))
        buckets.setdefault(key, []).append(ev)

    # Union-find over matches.
    parent: dict[str, str] = {ev.id: ev.id for ev in active}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for (venue, bucket), evs in buckets.items():
        neighbours = buckets.get((venue, bucket + 1), [])
        candidates = evs + neighbours
        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if a.id == b.id:
                    continue
                if _match(a, b):
                    union(a.id, b.id)

    # Group by root.
    clusters: dict[str, list[Event]] = {}
    for ev in active:
        clusters.setdefault(find(ev.id), []).append(ev)

    report = DedupReport()
    for cluster in clusters.values():
        if len(cluster) < 2:
            continue
        report.groups_found += 1
        winner = max(cluster, key=_winner_key)
        losers = [e for e in cluster if e.id != winner.id]

        loser_ids = [e.id for e in losers]
        migrated = (
            session.query(SavedEvent)
            .filter(SavedEvent.event_id.in_(loser_ids))
            .update({"event_id": winner.id}, synchronize_session="fetch")
        )
        report.saved_events_migrated += migrated

        for loser in losers:
            session.delete(loser)
        report.rows_merged += len(losers)

    session.flush()
    logger.info(
        "dedup_events: groups=%d merged=%d saved_migrated=%d",
        report.groups_found,
        report.rows_merged,
        report.saved_events_migrated,
    )
    return report
```

- [ ] **Step 2.4: Run tests**

```bash
python -m pytest tests/ingestion/test_dedup.py -v
```

Expected: all 23 PASS (13 helper + 10 dedup).

- [ ] **Step 2.5: Commit**

```bash
git add backend/app/ingestion/dedup.py backend/tests/ingestion/test_dedup.py
git commit -m "feat(dedup): dedup_events with union-find and saved_events FK migration"
```

---

## Task 3 — Theater-Hamburg: JWT extraction helper

**Files:**
- Create: `backend/app/ingestion/scrapers/theater_hamburg.py`
- Create: `backend/tests/ingestion/test_theater_hamburg.py`

Pure regex extraction. Testable in isolation before we touch httpx.

- [ ] **Step 3.1: Write the failing tests**

Create `backend/tests/ingestion/test_theater_hamburg.py`:

```python
from pathlib import Path

import pytest

from app.ingestion.scrapers.theater_hamburg import _extract_jwt


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


class TestExtractJwt:
    def test_extracts_from_real_widget_js_fixture(self):
        js = (_FIXTURE_DIR / "theater_hamburg_widget_sample.js").read_text(encoding="utf-8")
        token = _extract_jwt(js)
        assert token is not None
        assert token.startswith("ey")
        assert token.count(".") == 2

    def test_returns_none_when_no_jwt_present(self):
        assert _extract_jwt("var x = 1;") is None

    def test_picks_the_first_jwt_when_multiple_present(self):
        js = "prefix eyAAA.BBB.CCC middle eyXXX.YYY.ZZZ end"
        # Both look valid to the regex; the first wins.
        assert _extract_jwt(js) == "eyAAA.BBB.CCC"

    def test_ignores_short_ey_prefixed_strings(self):
        # 'eyabc' isn't three-part base64url and shouldn't match.
        assert _extract_jwt("some var eyabc = 1;") is None
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
python -m pytest tests/ingestion/test_theater_hamburg.py -v
```

Expected: FAIL — module missing.

- [ ] **Step 3.3: Implement `_extract_jwt` in a new module**

Create `backend/app/ingestion/scrapers/theater_hamburg.py`:

```python
"""Theater-Hamburg adapter — imxplatform GraphQL over httpx.

The whitelabel widget's data endpoint requires a Bearer JWT that is baked
into the public widget.js bundle. We scrape it on init and re-scrape once
on 401. All events are Hamburg cultural venues (theater, opera, concert
halls) with editorial shortDescription populated in the detail query."""
import logging
import re

logger = logging.getLogger(__name__)

_WIDGET_JS_URL = "https://hht.whitelabel.imxplatform.de/widget/widget.js"
_JWT_RE = re.compile(r"ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")


def _extract_jwt(js_body: str) -> str | None:
    """Return the first JWT-shaped token in the JS bundle, or None."""
    m = _JWT_RE.search(js_body)
    return m.group(0) if m else None
```

- [ ] **Step 3.4: Run tests to verify they pass**

```bash
python -m pytest tests/ingestion/test_theater_hamburg.py -v
```

Expected: 4 PASS.

- [ ] **Step 3.5: Commit**

```bash
git add backend/app/ingestion/scrapers/theater_hamburg.py backend/tests/ingestion/test_theater_hamburg.py
git commit -m "feat(theater_hamburg): JWT regex extractor"
```

---

## Task 4 — Theater-Hamburg: adapter shell + list query

**Files:**
- Modify: `backend/app/ingestion/scrapers/theater_hamburg.py`
- Modify: `backend/tests/ingestion/test_theater_hamburg.py`

Adapter constructor + JWT bootstrap + paginated GraphQL list. No detail-query yet.

- [ ] **Step 4.1: Add failing tests**

Append to `backend/tests/ingestion/test_theater_hamburg.py`:

```python
from unittest.mock import MagicMock

import httpx

from app.ingestion.scrapers.theater_hamburg import (
    TheaterHamburgAdapter,
    _WIDGET_JS_URL,
    _API_URL,
)


class _FakeClient:
    """Records GET and POST calls; returns queued responses by URL prefix.

    - GET URLs match `get_map` (prefix → text body).
    - POST URLs match `post_map` (prefix → callable(body_json) -> response_json)
      so tests can inspect the GraphQL body and return per-request data.
    """

    def __init__(self, get_map: dict[str, str] | None = None, post_map: dict | None = None):
        self.get_map = get_map or {}
        self.post_map = post_map or {}
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append(url)
        for prefix, text in self.get_map.items():
            if url.startswith(prefix):
                return httpx.Response(200, text=text, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    def post(self, url: str, *, json: dict, headers: dict, **kwargs):
        self.post_calls.append((url, json, headers))
        for prefix, handler in self.post_map.items():
            if url.startswith(prefix):
                body = handler(json) if callable(handler) else handler
                return httpx.Response(200, json=body, request=httpx.Request("POST", url))
        return httpx.Response(404, request=httpx.Request("POST", url))


_WIDGET_JS_WITH_JWT = "var TOKEN='eyAAA.BBB.CCC'; init();"


def _list_response(nodes: list[dict], total_pages: int = 1, page: int = 1) -> dict:
    return {
        "data": {
            "events": {
                "nodes": nodes,
                "pagination": {"totalPages": total_pages, "totalRecords": len(nodes)},
            }
        }
    }


def _make_node(
    permalink: str = "hamlet-thalia",
    title: str = "Hamlet",
    venue_id: int = 99,
    venue_title: str = "Thalia Theater",
    dates: list[dict] | None = None,
    categories: list[str] | None = None,
) -> dict:
    return {
        "id": 12345,
        "title": title,
        "permaLink": permalink,
        "categories": [{"title": c} for c in (categories or ["Theater"])],
        "contact": {"location": {"id": venue_id, "title": venue_title}},
        "eventDates": dates or [{"date": "2026-07-20", "startTime": "20:00", "duration": 120}],
        "geoInfo": {"latitude": 53.55, "longitude": 10.0},
        "image": {"deeplink": "https://cdn.example/hamlet.jpg"},
        "bookingLink": "https://tix.example/hamlet",
    }


class TestAdapterInit:
    def test_scrapes_jwt_from_widget_js_on_first_use(self):
        client = _FakeClient(get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT})
        adapter = TheaterHamburgAdapter(client=client)
        assert adapter._get_jwt() == "eyAAA.BBB.CCC"
        assert client.get_calls == [_WIDGET_JS_URL]

    def test_jwt_env_override_skips_scrape(self, monkeypatch):
        monkeypatch.setenv("THEATER_HAMBURG_JWT", "eyOVERRIDE.PART.SIG")
        client = _FakeClient()
        adapter = TheaterHamburgAdapter(client=client)
        assert adapter._get_jwt() == "eyOVERRIDE.PART.SIG"
        assert client.get_calls == []

    def test_raises_when_widget_js_has_no_jwt(self):
        client = _FakeClient(get_map={_WIDGET_JS_URL: "no token here"})
        adapter = TheaterHamburgAdapter(client=client)
        with pytest.raises(RuntimeError, match="JWT"):
            adapter._get_jwt()


class TestListFetch:
    def test_single_page_yields_one_event_per_date(self):
        node = _make_node(dates=[
            {"date": "2026-07-20", "startTime": "20:00", "duration": 120},
            {"date": "2026-07-21", "startTime": "20:00", "duration": 120},
        ])
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: (
                _list_response([node], total_pages=1)
                if "EventSearch" in body["query"]
                else {"data": {"events": {"nodes": [{"shortDescription": "<p>Nice show.</p>"}]}}}
            )},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert len(events) == 2
        assert events[0].title == "Hamlet"
        assert events[0].description == "Nice show."
        # external_id is stable per (permalink, date, time).
        assert events[0].external_id == "hamlet-thalia#2026-07-20T20:00"
        assert events[1].external_id == "hamlet-thalia#2026-07-21T20:00"

    def test_paginates_until_last_page(self):
        node_a = _make_node(permalink="a", title="A")
        node_b = _make_node(permalink="b", title="B")

        def handler(body):
            if "EventDetails" in body["query"]:
                return {"data": {"events": {"nodes": [{"shortDescription": "d"}]}}}
            page = body["variables"]["pagination"]["page"]
            if page == 1:
                return _list_response([node_a], total_pages=2, page=1)
            return _list_response([node_b], total_pages=2, page=2)

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert {e.title for e in events} == {"A", "B"}

    def test_401_triggers_one_rescrape_and_retry(self):
        # Widget.js returns two different JWTs across two GETs (rotate).
        widget_calls = {"count": 0}

        def widget_handler():
            widget_calls["count"] += 1
            return _WIDGET_JS_WITH_JWT if widget_calls["count"] == 1 else "var T='eyNEW.NEW.NEW';"

        class _RotatingClient(_FakeClient):
            def get(self, url, **kwargs):
                self.get_calls.append(url)
                return httpx.Response(200, text=widget_handler(), request=httpx.Request("GET", url))

            def post(self, url, *, json, headers, **kwargs):
                self.post_calls.append((url, json, headers))
                # First request is 401; subsequent OK.
                if len([c for c in self.post_calls if c[2].get("Authorization") == "Bearer eyAAA.BBB.CCC"]) == 1:
                    return httpx.Response(401, request=httpx.Request("POST", url))
                node = _make_node()
                if "EventSearch" in json["query"]:
                    return httpx.Response(200, json=_list_response([node]), request=httpx.Request("POST", url))
                return httpx.Response(200, json={"data": {"events": {"nodes": [{"shortDescription": "d"}]}}}, request=httpx.Request("POST", url))

        client = _RotatingClient()
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert widget_calls["count"] == 2  # first scrape + one rescrape after 401
```

- [ ] **Step 4.2: Run to confirm failures**

```bash
python -m pytest tests/ingestion/test_theater_hamburg.py -v
```

Expected: JWT-extractor tests still pass; init + list tests FAIL (class doesn't exist / no init contract).

- [ ] **Step 4.3: Implement adapter shell + list**

Replace the entire content of `backend/app/ingestion/scrapers/theater_hamburg.py` with:

```python
"""Theater-Hamburg adapter — imxplatform GraphQL over httpx.

The whitelabel widget's data endpoint requires a Bearer JWT that is baked
into the public widget.js bundle. We scrape it on init and re-scrape once
on 401. All events are Hamburg cultural venues (theater, opera, concert
halls) with editorial shortDescription populated in the detail query."""
import logging
import os
import re
import time
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_WIDGET_JS_URL = "https://hht.whitelabel.imxplatform.de/widget/widget.js"
_API_URL = "https://content-delivery.imxplatform.de/hht/imxplatform"
_JWT_RE = re.compile(r"ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}")
_BERLIN = ZoneInfo("Europe/Berlin")
_PAGE_SIZE = 1000
_DEFAULT_DETAIL_DELAY = 0.2

_LOCATION_IDS = [
    6306, 99, 423, 236, 121387, 1965, 494, 5359, 101488, 944, 947, 117, 119,
    375, 248, 313, 124, 100862, 1854, 767, 769, 833, 898, 771, 97227, 109323,
    5327, 9359, 5399, 12695, 217, 92, 95, 351,
]
_GROUP_IDS = [2, 3, 36, 164, 171, 108, 143, 175, 112, 176, 17, 114, 178, 19, 61]

_LIST_QUERY = """
query EventSearch($filter: EventFilter!, $pagination: PaginationInput!, $appearance: AppearanceInput!) {
  events(filter: $filter, pagination: $pagination, appearance: $appearance) {
    nodes {
      id
      title
      permaLink
      categories { title }
      contact { location { id title } }
      eventDates { date startTime duration }
      geoInfo { latitude longitude }
      image { deeplink }
      bookingLink
    }
    pagination { totalPages totalRecords }
  }
}
"""

_DETAIL_QUERY = """
query EventDetails($permalink: String!) {
  events(filter: {permaLink: {eq: $permalink}}) {
    nodes { shortDescription }
  }
}
"""

_CATEGORY_MAP: dict[str, str] = {
    "theater": "theater",
    "schauspiel": "theater",
    "oper": "theater",
    "musical": "theater",
    "kabarett": "theater",
    "comedy": "theater",
    "ballett": "arts",
    "tanz": "arts",
    "konzert": "music",
    "musik": "music",
    "klassik": "music",
    "jazz": "music",
    "kino": "film",
    "film": "film",
    "ausstellung": "arts",
    "lesung": "arts",
    "kinder": "family",
    "familie": "family",
}


def _extract_jwt(js_body: str) -> str | None:
    m = _JWT_RE.search(js_body)
    return m.group(0) if m else None


def _map_category(raw_titles: list[str]) -> tuple[str, list[str]]:
    """Return (primary category, remaining lowercase tags)."""
    lowered = [t.lower().strip() for t in raw_titles if t]
    for t in lowered:
        for key, mapped in _CATEGORY_MAP.items():
            if key in t:
                tags = [x for x in lowered if x != t]
                return mapped, tags
    return "other", lowered


def _parse_start(date_str: str, time_str: str | None) -> datetime:
    t = time_str or "00:00"
    naive = datetime.fromisoformat(f"{date_str}T{t}:00")
    return naive.replace(tzinfo=_BERLIN)


def _strip_html(html: str | None) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text or None


class TheaterHamburgAdapter:
    """Ingests upcoming Hamburg events from theater-hamburg.org's imxplatform widget."""

    name = "theater_hamburg"

    def __init__(
        self,
        client: httpx.Client | None = None,
        detail_delay_seconds: float = _DEFAULT_DETAIL_DELAY,
    ):
        self._client = client or httpx.Client(timeout=15)
        self._detail_delay = detail_delay_seconds
        self._jwt: str | None = None
        self._detail_cache: dict[str, str | None] = {}

    def _get_jwt(self) -> str:
        if self._jwt is not None:
            return self._jwt
        override = os.environ.get("THEATER_HAMBURG_JWT")
        if override:
            self._jwt = override
            return override
        return self._rescrape_jwt()

    def _rescrape_jwt(self) -> str:
        resp = self._client.get(_WIDGET_JS_URL)
        resp.raise_for_status()
        token = _extract_jwt(resp.text)
        if not token:
            raise RuntimeError("No JWT found in theater-hamburg widget.js")
        self._jwt = token
        return token

    def _post(self, body: dict) -> dict:
        """POST to GraphQL, transparently re-scraping JWT once on 401."""
        jwt = self._get_jwt()
        resp = self._client.post(
            _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
        )
        if resp.status_code == 401:
            logger.info("theater_hamburg: 401 — re-scraping widget JWT")
            self._jwt = None
            self._detail_cache.clear()
            jwt = self._rescrape_jwt()
            resp = self._client.post(
                _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
            )
        resp.raise_for_status()
        return resp.json()

    def _list_page(self, page: int, from_date: str) -> dict:
        variables = {
            "filter": {
                "and": [
                    {"or": [
                        {"eventLocation": {"id": {"oneOf": _LOCATION_IDS}}},
                        {"eventLocation": {"group": {"oneOf": _GROUP_IDS}}},
                    ]},
                    {"fromDate": from_date},
                ]
            },
            "pagination": {"page": page, "pageSize": _PAGE_SIZE},
            "appearance": {"deliveryChannel": 76},
        }
        body = {"query": _LIST_QUERY, "variables": variables}
        return self._post(body)

    def fetch(self) -> Iterator[NormalizedEvent]:
        today = datetime.now(tz=_BERLIN).date().isoformat()
        page = 1
        while True:
            data = self._list_page(page, today)
            events_root = data.get("data", {}).get("events", {}) or {}
            nodes = events_root.get("nodes") or []
            pagination = events_root.get("pagination") or {}
            total_pages = pagination.get("totalPages", 1)

            for node in nodes:
                description = self._fetch_description(node.get("permaLink"))
                for parsed in self._expand_node(node, description):
                    yield parsed

            if page >= total_pages or not nodes:
                break
            page += 1

    def _fetch_description(self, permalink: str | None) -> str | None:
        if not permalink:
            return None
        if permalink in self._detail_cache:
            return self._detail_cache[permalink]
        body = {"query": _DETAIL_QUERY, "variables": {"permalink": permalink}}
        try:
            data = self._post(body)
        except Exception:
            logger.warning("theater_hamburg: detail fetch failed for %s", permalink)
            self._detail_cache[permalink] = None
            return None
        nodes = (data.get("data") or {}).get("events", {}).get("nodes") or []
        html = nodes[0].get("shortDescription") if nodes else None
        text = _strip_html(html)
        self._detail_cache[permalink] = text
        if self._detail_delay:
            time.sleep(self._detail_delay)
        return text

    def _expand_node(self, node: dict, description: str | None) -> Iterator[NormalizedEvent]:
        """One list node yields one NormalizedEvent per entry in eventDates."""
        permalink = node.get("permaLink") or ""
        title = node.get("title") or ""
        contact = node.get("contact") or {}
        venue = ((contact.get("location") or {}).get("title")) or None
        geo = node.get("geoInfo") or {}
        image = (node.get("image") or {}).get("deeplink")
        cat_titles = [c.get("title") or "" for c in node.get("categories") or []]
        category, tags = _map_category(cat_titles)
        source_url = f"https://theater-hamburg.org/theater-hamburg/veranstaltung/{permalink}/"

        for ed in node.get("eventDates") or []:
            date = ed.get("date")
            start_time = ed.get("startTime")
            if not date:
                continue
            try:
                start = _parse_start(date, start_time)
                external_id = f"{permalink}#{date}T{start_time or '00:00'}"
                yield NormalizedEvent(
                    external_id=external_id,
                    source=self.name,
                    title=title,
                    description=description,
                    start_datetime=start,
                    venue_name=venue,
                    latitude=geo.get("latitude"),
                    longitude=geo.get("longitude"),
                    category=category,
                    tags=tags,
                    is_free=False,
                    currency="EUR",
                    image_url=image,
                    source_url=source_url,
                    raw_data={"node": node, "eventDate": ed},
                )
            except (KeyError, ValueError, TypeError):
                logger.exception("theater_hamburg: skipping malformed date on %s", permalink)
```

- [ ] **Step 4.4: Run tests**

```bash
python -m pytest tests/ingestion/test_theater_hamburg.py -v
```

Expected: all 11 PASS (4 JWT + 3 init + 3 list + 1 rescrape retry).

- [ ] **Step 4.5: Commit**

```bash
git add backend/app/ingestion/scrapers/theater_hamburg.py backend/tests/ingestion/test_theater_hamburg.py
git commit -m "feat(theater_hamburg): adapter with paginated GraphQL list + JWT rescrape"
```

---

## Task 5 — Theater-Hamburg: detail caching + malformed-row resilience

**Files:**
- Modify: `backend/tests/ingestion/test_theater_hamburg.py`

Additional coverage for behaviors that were baked into Task 4 but not tested there.

- [ ] **Step 5.1: Add tests**

Append to `backend/tests/ingestion/test_theater_hamburg.py`:

```python
class TestDetailCaching:
    def test_detail_called_once_per_permalink_across_multiple_events(self):
        node = _make_node(dates=[
            {"date": "2026-07-20", "startTime": "20:00", "duration": 120},
            {"date": "2026-07-21", "startTime": "20:00", "duration": 120},
            {"date": "2026-07-22", "startTime": "20:00", "duration": 120},
        ])
        detail_calls = {"count": 0}

        def handler(body):
            if "EventSearch" in body["query"]:
                return _list_response([node])
            detail_calls["count"] += 1
            return {"data": {"events": {"nodes": [{"shortDescription": "cached"}]}}}

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert len(events) == 3
        assert all(e.description == "cached" for e in events)
        assert detail_calls["count"] == 1


class TestDescriptionParsing:
    def test_short_description_html_stripped(self):
        node = _make_node()

        def handler(body):
            if "EventSearch" in body["query"]:
                return _list_response([node])
            return {"data": {"events": {"nodes": [{
                "shortDescription": "<p>Line one.</p><br><em>Line two.</em>"
            }]}}}

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert events[0].description == "Line one. Line two."

    def test_missing_short_description_leaves_none(self):
        node = _make_node()

        def handler(body):
            if "EventSearch" in body["query"]:
                return _list_response([node])
            return {"data": {"events": {"nodes": [{"shortDescription": None}]}}}

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert events[0].description is None

    def test_real_fixture_end_to_end(self):
        """Parses the captured EventSearch + EventDetails JSON files without erroring."""
        import json
        search = json.loads((_FIXTURE_DIR / "theater_hamburg_search_sample.json").read_text(encoding="utf-8"))
        details = json.loads((_FIXTURE_DIR / "theater_hamburg_details_sample.json").read_text(encoding="utf-8"))

        def handler(body):
            if "EventSearch" in body["query"]:
                return search
            return details

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert len(events) > 0
        # At least one event picked up a description from the details fixture.
        assert any(e.description for e in events)


class TestMalformedResilience:
    def test_node_without_permalink_skipped_at_expansion(self):
        # Missing eventDates entry (empty list) → no events emitted; no exception.
        node = _make_node()
        node["eventDates"] = []

        def handler(body):
            if "EventSearch" in body["query"]:
                return _list_response([node])
            return {"data": {"events": {"nodes": []}}}

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert events == []

    def test_date_entry_without_date_field_skipped(self):
        node = _make_node(dates=[
            {"startTime": "20:00", "duration": 120},  # missing 'date'
            {"date": "2026-07-20", "startTime": "20:00", "duration": 120},
        ])

        def handler(body):
            if "EventSearch" in body["query"]:
                return _list_response([node])
            return {"data": {"events": {"nodes": [{"shortDescription": "ok"}]}}}

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client, detail_delay_seconds=0)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert events[0].start_datetime.date().isoformat() == "2026-07-20"
```

- [ ] **Step 5.2: Run tests**

```bash
python -m pytest tests/ingestion/test_theater_hamburg.py -v
```

Expected: all PASS (6 additional tests). If `test_real_fixture_end_to_end` fails, inspect the captured fixture files from Task 0 for missing top-level keys.

- [ ] **Step 5.3: Commit**

```bash
git add backend/tests/ingestion/test_theater_hamburg.py
git commit -m "test(theater_hamburg): detail caching + description parsing + malformed rows"
```

---

## Task 6 — Scheduler wiring

**Files:**
- Modify: `backend/app/ingestion/scheduler.py`
- Modify: `backend/tests/ingestion/test_scheduler.py`

Register the adapter and invoke `dedup_events()` between `deactivate_past_events` and `embed_new_events`.

- [ ] **Step 6.1: Inspect the existing scheduler tests**

```bash
cd backend
python -m pytest tests/ingestion/test_scheduler.py -v --collect-only
```

Note the mocking pattern in the existing scheduler tests (`chroma_upsert_events` and `chroma_store` are typically monkey-patched).

- [ ] **Step 6.2: Add failing tests**

Append to `backend/tests/ingestion/test_scheduler.py`:

```python
def test_run_ingestion_registers_theater_hamburg_adapter(monkeypatch):
    """The default adapter list contains a TheaterHamburgAdapter."""
    from app.ingestion.scheduler import _default_adapters
    from app.ingestion.scrapers.theater_hamburg import TheaterHamburgAdapter

    adapters = _default_adapters(wiki_client=None)
    assert any(isinstance(a, TheaterHamburgAdapter) for a in adapters)


def test_run_ingestion_calls_dedup_between_deactivate_and_embed(db_session, monkeypatch):
    from app.ingestion import scheduler

    call_order: list[str] = []

    def fake_deactivate(session):
        call_order.append("deactivate")
        return 0

    def fake_dedup(session):
        from app.ingestion.dedup import DedupReport
        call_order.append("dedup")
        return DedupReport()

    def fake_embed(session):
        call_order.append("embed")

    monkeypatch.setattr(scheduler, "deactivate_past_events", fake_deactivate)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", fake_embed)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self):
            return iter([])

    scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session)
    assert call_order == ["deactivate", "dedup", "embed"]


def test_run_ingestion_propagates_dedup_error(db_session, monkeypatch):
    from app.ingestion import scheduler

    def fake_dedup(session):
        raise RuntimeError("dedup blew up")

    monkeypatch.setattr(scheduler, "deactivate_past_events", lambda s: 0)
    monkeypatch.setattr(scheduler, "dedup_events", fake_dedup)
    monkeypatch.setattr(scheduler, "embed_new_events", lambda s: None)

    class _NoOpAdapter:
        name = "noop"
        def fetch(self):
            return iter([])

    with pytest.raises(RuntimeError, match="dedup blew up"):
        scheduler.run_ingestion(adapters=[_NoOpAdapter()], session=db_session)
```

Add `import pytest` at the top of the file if not present.

- [ ] **Step 6.3: Run tests to confirm they fail**

```bash
python -m pytest tests/ingestion/test_scheduler.py -v -k "theater or dedup"
```

Expected: FAIL — `TheaterHamburgAdapter` not registered, `dedup_events` not imported / not called.

- [ ] **Step 6.4: Wire the scheduler**

In `backend/app/ingestion/scheduler.py`:

Add imports at the top:

```python
from app.ingestion.dedup import dedup_events
from app.ingestion.scrapers.theater_hamburg import TheaterHamburgAdapter
```

Change `_default_adapters` to include the new adapter:

```python
def _default_adapters(wiki_client: httpx.Client | None = None) -> list[SourceAdapter]:
    return [
        TicketmasterAdapter(wiki_client=wiki_client),
        HamburgScraper(),
        TheaterHamburgAdapter(),
    ]
```

Change the ingestion order in `run_ingestion`. Replace:

```python
        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        embed_new_events(session)
```

with:

```python
        report = upsert_events(session, all_events)
        deactivate_past_events(session)
        dedup_report = dedup_events(session)
        logger.info(
            "dedup: groups=%d merged=%d saved_migrated=%d",
            dedup_report.groups_found,
            dedup_report.rows_merged,
            dedup_report.saved_events_migrated,
        )
        embed_new_events(session)
```

- [ ] **Step 6.5: Run tests**

```bash
python -m pytest tests/ingestion/test_scheduler.py -v
```

Expected: all PASS. If a pre-existing scheduler test fails because `_default_adapters` now has three adapters instead of two, adjust the assertion (`len == 2` → `len == 3`) or make it type-based.

- [ ] **Step 6.6: Commit**

```bash
git add backend/app/ingestion/scheduler.py backend/tests/ingestion/test_scheduler.py
git commit -m "feat(scheduler): register TheaterHamburgAdapter + call dedup_events"
```

---

## Task 7 — Full suite verification

- [ ] **Step 7.1: Run every backend test**

```bash
cd backend
python -m pytest -v
```

Expected: all pass. If a pre-existing test fails because of a new-adapter side effect (e.g. an ingestion integration test that seeded events at a Hamburg venue that now match theater-hamburg naming), diagnose and fix — don't skip.

- [ ] **Step 7.2: Commit any test fixes**

```bash
git add -p
git commit -m "test: adjust for TheaterHamburgAdapter registration"
```

If nothing needed fixing, skip this step.

---

## Task 8 — Manual live ingest (operator step)

Do this in a fresh terminal against the actual production DB. Not part of automated test runs.

- [ ] **Step 8.1: Snapshot DB**

```bash
cp backend/event_tracker.db backend/event_tracker.db.bak-theater-hamburg-$(date +%Y%m%d)
```

- [ ] **Step 8.2: Coverage before**

```bash
python -c "
import sqlite3
c = sqlite3.connect('backend/event_tracker.db').cursor()
c.execute(\"SELECT source, COUNT(*), SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) FROM events GROUP BY source\")
for row in c.fetchall(): print(row)
"
```

- [ ] **Step 8.3: Run one full ingest**

```bash
cd backend
python -c "
from app.ingestion.scheduler import run_ingestion
r = run_ingestion()
print(r)
"
```

Expected runtime: ~5–10 min (theater-hamburg detail queries dominate). Watch the log for `theater_hamburg: fetched N events` and `dedup_events: groups=X merged=Y`.

- [ ] **Step 8.4: Coverage after**

Same query as 8.2. Expected: `theater_hamburg` at ~1500-2000 rows with ~100 % description coverage. Aggregate description coverage across all sources jumps to > 90 %.

---

## Notes for the executor

- Follow the task order strictly — Task 2 depends on Task 1's dedup module existing; Task 4 depends on Task 3's module skeleton.
- **Commit per task.** No batched task-spanning commits.
- **If a fixture-based test fails after Task 0** because the captured response shape differs from the code's expectations, prefer adjusting the code over reshaping the fixture — the fixture is the source of truth for what real responses look like.
- **If Task 0's live capture is impossible** (offline environment, network policy), you may hand-craft minimal fixtures that satisfy the parsers, but `test_real_fixture_end_to_end` (Task 5) will then only exercise those minimal shapes — flag this in the completion report.
- If `_default_adapters` gains a `wiki_client` inconsistency because `TheaterHamburgAdapter` doesn't accept one, that's expected — theater-hamburg has its own JWT auth flow and doesn't use the Wikipedia client.
