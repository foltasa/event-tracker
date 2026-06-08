# Event Tracker — Ingestion Pipeline Design

**Status:** Draft v1 · **Date:** 2026-06-08
**Companion documents:** `docs/PRD.md`, `docs/specs/2026-06-08-event-tracker-tech-design.md`, `docs/specs/2026-06-08-data-format-design.md`

---

## 1. Scope

This spec covers the ingestion pipeline: the components that fetch events from external sources, normalise them to the shared schema, persist them to SQLite, and schedule daily runs. It does **not** cover the Chroma embedding pipeline (deferred to the RAG feature), any FastAPI routes beyond the manual-trigger endpoint, or the LangGraph agent.

**Builds on:**
- `NormalizedEvent` Pydantic model — already in `backend/app/ingestion/normalize.py`
- `Event` SQLAlchemy model — already in `backend/app/db/models/event.py`
- `EventCategory` enum — already in `backend/app/schemas/common.py`

---

## 2. Decisions summary

| Decision | Choice |
|---|---|
| HTTP client | `httpx` (sync), injected into adapters for testability |
| HTML parsing | `BeautifulSoup4` (Hamburg scraper only) |
| Scheduler | APScheduler `BackgroundScheduler`, Europe/Berlin, 04:00 daily |
| Embedding step | Stubbed — logs "embedding deferred", no Chroma setup yet |
| Hamburg source | heuteinhamburg.de |
| Error isolation | Per-adapter: one failing source does not abort the run |
| Transaction boundary | One `session.commit()` per full run (after all adapters) |
| Test strategy | Injected fake `httpx.Client`; no network required for tests |

---

## 3. File layout

New files added to the existing skeleton:

```
backend/app/ingestion/
  normalize.py          (exists — ADD upsert_events, deactivate_past_events)
  base.py               (NEW — SourceAdapter Protocol)
  eventbrite.py         (NEW — Eventbrite API adapter)
  ticketmaster.py       (NEW — Ticketmaster Discovery API adapter)
  scrapers/
    __init__.py         (NEW)
    hamburg.py          (NEW — heuteinhamburg.de scraper)
  scheduler.py          (NEW — run_ingestion() + create_scheduler())

backend/app/
  main.py               (NEW — FastAPI app, lifespan, POST /ingestion/run)

backend/tests/ingestion/
  test_normalize.py     (exists — ADD upsert + deactivate tests)
  test_eventbrite.py    (NEW)
  test_ticketmaster.py  (NEW)
  test_hamburg_scraper.py (NEW)
  test_scheduler.py     (NEW)
```

---

## 4. SourceAdapter Protocol

`backend/app/ingestion/base.py`:

```python
from typing import Iterator, Protocol
from app.ingestion.normalize import NormalizedEvent

class SourceAdapter(Protocol):
    name: str
    def fetch(self) -> Iterator[NormalizedEvent]: ...
```

Every adapter satisfies this protocol. The scheduler and `run_ingestion()` depend only on this interface.

---

## 5. Adapters

### 5.1 Common injection pattern

Every adapter accepts an optional `httpx.Client` — defaults to a real client in production, receives a fake in tests:

```python
class EventbriteAdapter:
    name = "eventbrite"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=10)
        self._token = settings.EVENTBRITE_TOKEN
```

Each adapter owns internally:
1. **HTTP / scraping logic** — pagination, request construction, error handling
2. **Field mapping** — raw response fields → `NormalizedEvent` fields
3. **Category mapping** — source taxonomy → 10-value normalized taxonomy (unknown → `"other"`)

### 5.2 Eventbrite (`eventbrite.py`)

- **API:** Eventbrite v3, `GET /v3/events/search/`
- **Key params:** `location.address=Hamburg,DE`, `expand=venue,category`, `token=EVENTBRITE_TOKEN`
- **Pagination:** cursor-based via `continuation` token in response
- **Category map:** Eventbrite category names → normalized taxonomy

### 5.3 Ticketmaster (`ticketmaster.py`)

- **API:** Ticketmaster Discovery v2, `GET /discovery/v2/events.json`
- **Key params:** `city=Hamburg`, `countryCode=DE`, `apikey=TICKETMASTER_API_KEY`
- **Pagination:** page-based (`page`, `size`), up to `page.totalPages`
- **Category map:** Ticketmaster `segment.name` / `genre.name` → normalized taxonomy

### 5.4 Hamburg scraper (`scrapers/hamburg.py`)

- **Source:** heuteinhamburg.de
- **Method:** `httpx.Client.get(url)` → HTML → `BeautifulSoup4` parsing
- **Note:** Exact CSS selectors and pagination strategy to be determined by inspecting the live site at implementation time. The adapter exposes the same `fetch()` interface regardless.
- **Injection:** fake client returns fixture HTML string in tests

---

## 6. Upsert layer (additions to `normalize.py`)

```python
@dataclass
class UpsertReport:
    inserted: int
    updated: int
    skipped: int  # per-event errors (logged, not raised)

def upsert_events(session: Session, events: Iterable[NormalizedEvent]) -> UpsertReport:
    """
    For each event: lookup by (external_id, source).
    EXISTS → UPDATE all mutable fields, bump updated_at.
    NEW    → INSERT with uuid4() id, set ingested_at.
    Error  → skip + log, increment skipped.
    Does NOT commit — caller owns the transaction.
    """

def deactivate_past_events(session: Session) -> int:
    """
    SET is_active=False WHERE start_datetime < now() AND is_active=True.
    Returns count of rows updated.
    Does NOT commit — caller owns the transaction.
    """
```

**Mutable fields updated on upsert:** `title`, `description`, `summary`, `end_datetime`, `venue_name`, `venue_address`, `latitude`, `longitude`, `category`, `tags`, `price_min`, `price_max`, `is_free`, `currency`, `image_url`, `source_url`, `raw_data`, `updated_at`.

**Immutable on update:** `id`, `external_id`, `source`, `ingested_at`.

---

## 7. Embedding stub

```python
def embed_new_events(session: Session) -> None:
    """Stub — Chroma embedding deferred to RAG feature."""
    logger.info("embed_new_events: deferred, skipping")
```

Lives in `backend/app/ingestion/scheduler.py` until the RAG feature replaces it.

---

## 8. Scheduler (`scheduler.py`)

### `run_ingestion()`

```python
def run_ingestion(
    adapters: list[SourceAdapter] | None = None,
    session: Session | None = None,
) -> UpsertReport:
    """
    Runs the full ingestion cycle:
    1. Fetch from each adapter (per-adapter error isolation)
    2. upsert_events()
    3. deactivate_past_events()
    4. embed_new_events()  ← stub
    5. session.commit()
    Returns aggregated UpsertReport.
    """
```

- Default adapters: `[EventbriteAdapter(), TicketmasterAdapter(), HamburgScraper()]`
- Default session: new session from `get_session()`
- Per-adapter failure: log exception, continue; that adapter contributes 0 events
- DB failure after all fetches: roll back, log, re-raise

### `create_scheduler()`

```python
def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Europe/Berlin")
    scheduler.add_job(run_ingestion, "cron", hour=4, minute=0)
    return scheduler
```

---

## 9. FastAPI wiring (`main.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post("/ingestion/run", status_code=200)
def trigger_ingestion() -> dict:
    report = run_ingestion()
    return {"inserted": report.inserted, "updated": report.updated, "skipped": report.skipped}
```

The `POST /ingestion/run` endpoint enables manual triggering for development and demos without waiting for 04:00.

---

## 10. Testing strategy

### Fake HTTP client pattern

```python
class FakeClient:
    def __init__(self, responses: dict[str, Any]):
        # responses maps URL prefix → fixture payload
        self._responses = responses

    def get(self, url: str, **kwargs) -> httpx.Response:
        for prefix, payload in self._responses.items():
            if url.startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})
```

### Coverage goals

| Test file | What it covers |
|---|---|
| `test_eventbrite.py` | Field mapping, category mapping, pagination, empty response, HTTP 429/500 handling |
| `test_ticketmaster.py` | Same as above for Ticketmaster payload shapes |
| `test_hamburg_scraper.py` | HTML parsing with fixture HTML, missing fields, malformed rows |
| `test_normalize.py` (additions) | `upsert_events` insert, update, idempotency; `deactivate_past_events` past/future split |
| `test_scheduler.py` | `run_ingestion()` with all adapters mocked; one-adapter failure doesn't abort run; DB error rolls back |

No test requires real API keys or network access.

---

## 11. Configuration (`config.py` additions)

New required env vars (already in `.env.example`):

| Key | Used by |
|---|---|
| `EVENTBRITE_TOKEN` | `EventbriteAdapter` |
| `TICKETMASTER_API_KEY` | `TicketmasterAdapter` |

Missing keys raise `ValueError` at startup (not silently ignored).

---

## 12. Dependencies (`pyproject.toml` additions)

| Package | Purpose |
|---|---|
| `httpx` | HTTP client for API adapters |
| `beautifulsoup4` | HTML parsing for Hamburg scraper |
| `apscheduler` | Daily background job |

---

## 13. Out of scope

- Chroma embedding (`embed_new_events` is a stub)
- All other FastAPI routes (events, feedback, calendar, chat, profile)
- LangGraph agent
- Rate-limit retry logic beyond logging (deferred — per tech design §10)
- Set-diff deactivation for source-side deletions (deferred — per data format spec §7)
- Multi-user (`user_id`) on ingestion — events are not user-scoped; the pipeline is user-agnostic
