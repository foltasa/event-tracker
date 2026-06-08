# Event Tracker — Data Format Design

**Status:** Draft v1 · **Date:** 2026-06-08
**Companion documents:** `docs/PRD.md` (product scope), `docs/specs/2026-06-08-event-tracker-tech-design.md` (architecture).

---

## 1. Scope

This spec fills the gap called out in §11 of the tech design: concrete schemas for `User`, `Event`, `Feedback`, `SavedEvent`, `ChatMessage`, plus the API request/response shapes that connect the FastAPI backend to the Next.js frontend, plus the intermediate format the ingestion pipeline produces.

The goal is to unblock parallel work on:

1. **Ingestion pipeline** — knows exactly what shape to normalize Eventbrite, Ticketmaster, and the Hamburg scraper into.
2. **Frontend** — has stable JSON fixtures to develop against before the backend is ready.

---

## 2. Decisions summary

| Decision | Choice |
|---|---|
| Schema layering | Separate SQLAlchemy (DB) and Pydantic (API) models |
| Source-specific fields | Common columns + `raw_data` JSON blob on `Event` |
| Mock data strategy | Static JSON fixtures in `frontend/fixtures/`, switched via `NEXT_PUBLIC_MOCK_MODE` |
| Schema philosophy | Domain model first → derive API shapes from it |
| User identity | `X-User-Id` header on every route, defaults to `"local"` |
| Time zone | All datetimes ISO 8601 with `Europe/Berlin` |
| Currency | EUR (MVP is Hamburg-only) |

---

## 3. SQLAlchemy DB models

Six tables. Every table has a string UUID primary key. Every user-scoped table includes `user_id` for multi-user readiness (tech design §7).

### 3.1 `User`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | defaults to `"local"` in MVP |
| `city` | `str` | `"Hamburg"` |
| `interest_tags` | `JSON` | `list[str]` |
| `about_me` | `str \| None` | free-text from onboarding |
| `taste_summary` | `str \| None` | LLM-distilled, refreshed periodically |
| `settings` | `JSON` | see `UserSettings` shape (§4) |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |

### 3.2 `Event`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | UUID |
| `external_id` | `str` | source's stable ID |
| `source` | `str` | `"eventbrite"` \| `"ticketmaster"` \| `"hamburg_scraper"` |
| `title` | `str` | |
| `description` | `str \| None` | full text; also used for embedding |
| `summary` | `str \| None` | short summary if source provides one |
| `start_datetime` | `datetime` | timezone-aware |
| `end_datetime` | `datetime \| None` | |
| `venue_name` | `str \| None` | |
| `venue_address` | `str \| None` | |
| `latitude` | `float \| None` | for future geo filtering |
| `longitude` | `float \| None` | |
| `category` | `str` | normalized taxonomy (see §3.7) |
| `tags` | `JSON` | `list[str]`, source-provided tags |
| `price_min` | `float \| None` | `None` = unknown |
| `price_max` | `float \| None` | `None` = unknown |
| `is_free` | `bool` | |
| `currency` | `str` | `"EUR"` |
| `image_url` | `str \| None` | |
| `source_url` | `str` | link to original listing |
| `raw_data` | `JSON` | source-specific fields preserved verbatim |
| `is_active` | `bool` | soft-delete for expired/removed events |
| `ingested_at` | `datetime` | |
| `updated_at` | `datetime` | |

**Unique constraint:** `(external_id, source)` — deduplication across ingestion runs.

### 3.3 `Feedback`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | |
| `user_id` | `str` FK → `User` | |
| `event_id` | `str` FK → `Event` | |
| `sentiment` | `str` | `"like"` \| `"dislike"` |
| `comment` | `str \| None` | free-text from card |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | bumped when sentiment/comment changes |

**Unique constraint:** `(user_id, event_id)` — one feedback per event. Updates overwrite in place.

### 3.4 `SavedEvent`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | |
| `user_id` | `str` FK → `User` | |
| `event_id` | `str` FK → `Event` | |
| `saved_at` | `datetime` | |

**Unique constraint:** `(user_id, event_id)`.

### 3.5 `ChatMessage`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | |
| `user_id` | `str` FK → `User` | |
| `session_id` | `str` | UUID grouping a conversation |
| `role` | `str` | `"user"` \| `"assistant"` \| `"tool"` |
| `content` | `str` | |
| `tool_name` | `str \| None` | populated when `role = "tool"` |
| `input_tokens` | `int \| None` | populated on `assistant` messages |
| `output_tokens` | `int \| None` | populated on `assistant` messages |
| `estimated_cost_usd` | `float \| None` | populated on `assistant` messages |
| `created_at` | `datetime` | |

System prompts are not persisted as `ChatMessage` rows (they live in `prompts.py`).

### 3.6 `DigestCache`

| column | type | notes |
|---|---|---|
| `id` | `str` PK | |
| `user_id` | `str` FK → `User` | |
| `date` | `date` | the day this digest covers |
| `picks` | `JSON` | `list[{event_id: str, justification: str}]` |
| `generated_at` | `datetime` | |

**Unique constraint:** `(user_id, date)`. A `POST /digest/refresh` overwrites the cached row for today.

### 3.7 Normalized category taxonomy

Exactly ten values. Used by `Event.category` and the ingestion category mappers:

```
music | arts | food | sports | tech | outdoor | film | theater | family | other
```

Unknown source categories map to `"other"`.

### 3.8 Soft-delete handling

`Event.is_active = False` events:
- are filtered out of `GET /digest` and `GET /events`
- are still returned via `GET /calendar` (so a saved event doesn't vanish)
- are still returned via `GET /events/{id}` (so feedback history resolves)
- carry `is_active: false` in the API response so the frontend can gray them out

---

## 4. Pydantic API schemas

### 4.1 Shared building blocks

**`EventCard`** — canonical "event in a list" payload, used in digest, feed, calendar:

```json
{
  "id": "evt_a1b2c3",
  "title": "Jazz Night at Mojo Club",
  "summary": "Intimate trio set, doors 20:00",
  "start_datetime": "2026-06-14T20:00:00+02:00",
  "end_datetime": "2026-06-14T23:00:00+02:00",
  "venue_name": "Mojo Club",
  "venue_address": "Reeperbahn 1, 20359 Hamburg",
  "category": "music",
  "tags": ["jazz", "live music", "intimate"],
  "price_min": 18.0,
  "price_max": 24.0,
  "is_free": false,
  "currency": "EUR",
  "image_url": "https://images.example.com/mojo.jpg",
  "source_url": "https://www.eventbrite.de/e/jazz-night-12345",
  "source": "eventbrite",
  "is_active": true
}
```

**`EventWithContext`** extends `EventCard` with the current user's state. Used wherever the user can react:

```json
{
  "...": "all EventCard fields",
  "user_sentiment": "like",
  "user_comment": "loved the venue last time",
  "is_saved": true
}
```

**`UserSettings`** — the shape held in `User.settings`:

```json
{
  "tool_toggles": {
    "search_events": true,
    "get_recommendations": true,
    "record_feedback": true,
    "save_to_calendar": true,
    "get_calendar": true,
    "get_user_profile": true,
    "update_user_profile": true
  },
  "llm_provider": "openai",
  "llm_model": "gpt-4o-mini"
}
```

**`ChatTokenUsage`**:

```json
{ "input_tokens": 420, "output_tokens": 88, "estimated_cost_usd": 0.0012 }
```

### 4.2 Routes and shapes

| Method | Route | Request | Response |
|---|---|---|---|
| `GET` | `/digest` | — | `DigestResponse` |
| `POST` | `/digest/refresh` | — | `DigestResponse` (force regen) |
| `GET` | `/events` | query: `page, page_size, category, date_from, date_to, is_free, q` | `EventsFeedResponse` |
| `GET` | `/events/{id}` | — | `EventWithContext` |
| `POST` | `/feedback` | `FeedbackCreate` | `FeedbackResponse` |
| `DELETE` | `/feedback/{event_id}` | — | 204 |
| `GET` | `/calendar` | query: `date_from, date_to` | `CalendarResponse` |
| `POST` | `/calendar/{event_id}` | — | `CalendarEntry` |
| `DELETE` | `/calendar/{event_id}` | — | 204 |
| `GET` | `/profile` | — | `UserProfileResponse` |
| `PUT` | `/profile` | `UserProfileUpdate` | `UserProfileResponse` |
| `POST` | `/onboarding` | `OnboardingRequest` | `UserProfileResponse` |
| `GET` | `/settings` | — | `UserSettings` |
| `PUT` | `/settings` | `SettingsUpdate` (partial) | `UserSettings` |
| `POST` | `/chat` | `ChatRequest` | SSE stream of `ChatChunk` |
| `GET` | `/chat/sessions/{session_id}` | — | `list[ChatMessageResponse]` |
| `GET` | `/usage` | — | `UsageRollupResponse` |

### 4.3 Notable response shapes

**`DigestResponse`**:

```json
{
  "date": "2026-06-08",
  "picks": [
    {
      "event": { "...": "EventCard" },
      "justification": "You consistently liked small intimate jazz venues last month, and this is a trio set at one of your saved spots."
    }
  ],
  "generated_at": "2026-06-08T07:42:11+02:00",
  "is_cached": true
}
```

**`EventsFeedResponse`**:

```json
{
  "events": [ { "...": "EventWithContext" } ],
  "total": 142,
  "page": 1,
  "page_size": 20
}
```

**`FeedbackCreate`** / **`FeedbackResponse`**:

```json
// request
{ "event_id": "evt_a1b2c3", "sentiment": "like", "comment": "love this venue" }

// response
{
  "id": "fb_x1y2",
  "event_id": "evt_a1b2c3",
  "sentiment": "like",
  "comment": "love this venue",
  "created_at": "2026-06-08T19:14:22+02:00",
  "updated_at": "2026-06-08T19:14:22+02:00"
}
```

**`CalendarResponse`**:

```json
{
  "entries": [
    {
      "id": "sav_p9q8",
      "event": { "...": "EventCard" },
      "saved_at": "2026-06-07T11:02:00+02:00"
    }
  ]
}
```

**`UserProfileResponse`** / **`UserProfileUpdate`** / **`OnboardingRequest`**:

```json
// UserProfileResponse
{
  "city": "Hamburg",
  "interest_tags": ["music", "tech", "outdoor"],
  "about_me": "Backend dev, prefer small venues, hate crowds.",
  "taste_summary": "Prefers small intimate venues, dislikes EDM, weekday late-evening OK.",
  "settings": { "...": "UserSettings" }
}

// UserProfileUpdate — partial
{ "interest_tags": ["music", "art"], "about_me": "..." }

// OnboardingRequest
{ "interest_tags": ["music", "tech"], "about_me": "..." }
```

`PUT /profile` and `POST /onboarding` only touch profile fields (interests, about-me). `PUT /settings` is the separate channel for tool toggles and LLM provider.

**`SettingsUpdate`** — partial of `UserSettings`:

```json
{
  "tool_toggles": { "save_to_calendar": false },
  "llm_provider": "anthropic",
  "llm_model": "claude-sonnet-4-6"
}
```

**`ChatRequest`**:

```json
{ "message": "anything outdoorsy on Friday?", "session_id": "sess_4f2a" }
```

**`ChatChunk`** — one per SSE event, discriminated by `type`:

```json
{ "type": "token",      "content": "Looking" }
{ "type": "token",      "content": " for events..." }
{ "type": "tool_start", "tool_name": "search_events" }
{ "type": "tool_end",   "tool_name": "search_events", "status": "ok" }
{ "type": "done",       "token_usage": { "input_tokens": 420, "output_tokens": 88, "estimated_cost_usd": 0.0012 } }
{ "type": "error",      "message": "rate limited, retry in 5s" }
```

`status` is `"ok"` | `"error"`. The stream always ends with exactly one `done` or one `error` chunk.

**`ChatMessageResponse`** (for history endpoint):

```json
{
  "id": "msg_a1",
  "session_id": "sess_4f2a",
  "role": "assistant",
  "content": "Here are three picks for Friday evening...",
  "tool_name": null,
  "token_usage": { "input_tokens": 420, "output_tokens": 88, "estimated_cost_usd": 0.0012 },
  "created_at": "2026-06-08T19:14:22+02:00"
}
```

**`UsageRollupResponse`** (for M1 cost display on settings page):

```json
{
  "today": { "input_tokens": 1240, "output_tokens": 380, "estimated_cost_usd": 0.0048 },
  "last_7_days": [
    { "date": "2026-06-02", "input_tokens": 980, "output_tokens": 220, "estimated_cost_usd": 0.0032 }
  ]
}
```

### 4.4 Conventions across all routes

- Every route reads `X-User-Id` header (defaults to `"local"`).
- Datetimes are ISO 8601 with `Europe/Berlin` offset.
- Errors use FastAPI's default `{ "detail": "..." }` shape. 4xx for client errors, 5xx for server.
- `null` (not the missing key) signals "explicitly unknown" for optional fields.
- All field names are `snake_case`. The frontend passes them through verbatim.

---

## 5. Ingestion pipeline normalization format

### 5.1 `NormalizedEvent` Pydantic model

The canonical output of every source adapter. Lives in `backend/app/ingestion/normalize.py`.

```
external_id: str          # source's stable ID
source: str               # "eventbrite" | "ticketmaster" | "hamburg_scraper"
title: str
description: str | None
summary: str | None
start_datetime: datetime  # MUST be timezone-aware (Europe/Berlin)
end_datetime: datetime | None
venue_name: str | None
venue_address: str | None
latitude: float | None
longitude: float | None
category: str             # ALREADY mapped to normalized taxonomy
tags: list[str]
price_min: float | None
price_max: float | None
is_free: bool
currency: str = "EUR"
image_url: str | None
source_url: str
raw_data: dict            # full original payload, preserved
```

Deliberately excluded: `id`, `is_active`, `ingested_at`, `updated_at` — those are persistence concerns owned by the DB layer.

**Pydantic validators:**
- `start_datetime` must be timezone-aware; reject naive datetimes.
- If `is_free=True` → `price_min` and `price_max` must be `0` or `None`.
- If both `price_min` and `price_max` are set → `price_min <= price_max`.
- `external_id` and `source_url` must be non-empty.
- `category` must be one of the ten values in §3.7.

### 5.2 Source adapter contract

Each source lives in its own module and conforms to:

```python
class SourceAdapter(Protocol):
    name: str  # "eventbrite" | "ticketmaster" | "hamburg_scraper"
    def fetch(self) -> Iterator[NormalizedEvent]: ...
```

Each adapter owns three responsibilities internally:
1. **HTTP / scraping logic** — call the source.
2. **Field mapping** — pull raw fields into the normalized shape.
3. **Category mapping** — a small dict from the source's taxonomy → our 10-value normalized taxonomy. Unknown source categories map to `"other"`.

### 5.3 `normalize.py` upsert layer

```python
def upsert_events(events: list[NormalizedEvent]) -> UpsertReport:
    """
    For each event:
      look up by (external_id, source)
      if exists → UPDATE mutable fields
      else      → INSERT new row, generate UUID id
    Invalid events are logged and skipped.
    """

class UpsertReport:
    inserted: int
    updated: int
    skipped: int   # validation or other errors
```

Upsert key is `(external_id, source)` — matches the DB unique constraint from §3.2.

### 5.4 Scheduler — `scheduler.py`

APScheduler job at 04:00 Europe/Berlin daily:

```
1. For each adapter:
     try: events += adapter.fetch()
     except: log error, continue (one bad source doesn't kill the run)
2. report = upsert_events(events)
3. deactivate_past_events()        # mark is_active=False where start_datetime < now()
4. embed_new_events()              # embed into Chroma
5. log report summary
```

**Deactivation strategy:** time-based only in MVP — past events get `is_active=False`. Set-diff against the previous run (to detect source-side deletions) is deferred.

**Failure semantics:**
- Per-event validation failure → skip + log, continue with the rest.
- Per-adapter failure → log + continue with the other adapters.
- DB transaction failure → roll back that batch, log, surface in next run.

### 5.5 Embedding text format

For each new event, the text embedded into Chroma is:

```
f"{title}. {summary or description or ''}. Categories: {category}. Tags: {', '.join(tags)}"
```

Stored in Chroma with metadata:

```json
{
  "event_id": "evt_a1b2c3",
  "category": "music",
  "start_datetime_iso": "2026-06-14T20:00:00+02:00",
  "is_free": false
}
```

The metadata enables Chroma's filter-then-vector queries used by `get_recommendations`.

---

## 6. Frontend mock data

### 6.1 Folder layout

`frontend/fixtures/`:

```
fixtures/
  digest.json              # DigestResponse — 4 picks, varied categories
  events.json              # EventsFeedResponse — ~25 events
  event-detail.json        # EventWithContext — one event for /events/{id}
  calendar.json            # CalendarResponse — 3 saved entries
  profile.json             # UserProfileResponse — with default settings
  settings.json            # UserSettings only
  usage.json               # UsageRollupResponse — sample 7-day data
  chat-stream.json         # ordered list of ChatChunk events for SSE mock
```

Each fixture is a literal example of the corresponding Pydantic response. The JSON shapes are the source of truth that both frontend and backend hold themselves to.

### 6.2 Mock switching in `lib/api.ts`

```ts
const MOCK = process.env.NEXT_PUBLIC_MOCK_MODE === "true";

export async function getDigest(): Promise<DigestResponse> {
  if (MOCK) return (await import("@/fixtures/digest.json")).default;
  return fetch(`${API_URL}/digest`, ...).then(r => r.json());
}
```

One function per API route. Mutations (`POST /feedback`, `POST /calendar/{id}`, etc.) in mock mode return a plausible response and log to console — no fixture-state mutation. This is enough to develop and demo every screen end-to-end.

Env flag in `.env.local`: `NEXT_PUBLIC_MOCK_MODE=true` while backend isn't ready, flip to `false` once it is.

### 6.3 Chat SSE mocking

`chat-stream.json` holds an ordered list of `ChatChunk` events. The mock `postChat()` returns a `ReadableStream` that emits these chunks with a small delay between them, so the UI can be developed against realistic streaming behavior without a backend:

```json
[
  { "type": "token", "content": "Looking" },
  { "type": "token", "content": " for events..." },
  { "type": "tool_start", "tool_name": "search_events" },
  { "type": "tool_end",   "tool_name": "search_events", "status": "ok" },
  { "type": "token", "content": " Found 3 matches." },
  { "type": "done", "token_usage": { "input_tokens": 420, "output_tokens": 88, "estimated_cost_usd": 0.0012 } }
]
```

### 6.4 Fixture content guidelines

So the frontend gets exercised honestly:

- Mix of categories — at least one of `music`, `arts`, `food`, `tech`, `outdoor`, `theater`, `family`.
- Mix of pricing — some `is_free=true`, some with a price range, some with unknown prices (`price_min/max=null`).
- Mix of `user_sentiment` — `"like"`, `"dislike"`, `null`; some with comments.
- A few events with `is_active=false` in `calendar.json` (so the gray-out path is testable).
- Real Hamburg venue names + addresses (Elbphilharmonie, Reeperbahn, Mojo Club, Kampnagel) — keeps the demo credible.
- Image URLs from a stable source (Unsplash or a placeholder service).
- Two adjacent dates' digests to demonstrate "improves day-over-day" feel.

---

## 7. Open items

Resolved during implementation, not blocking this spec:

- **Pagination semantics on `/events`** — confirm whether `page` is 1-indexed or 0-indexed. (Recommend 1-indexed for UI clarity.)
- **`q` (full-text search) on `/events`** — backed by simple SQL `LIKE` for MVP, can move to FTS later.
- **Event ID format** — UUID4 throughout, no prefix needed; the table prefix in JSON examples (`evt_`, `fb_`, etc.) is illustrative only and can be dropped.
- **`X-User-Id` header default behavior** — middleware injects `"local"` when missing; explicit headers override.
- **Set-diff deactivation** — deferred; revisit if stale source events become a problem.

---

## 8. What this spec does not cover

- Prompt templates (curation mode, conversational mode, distilled-summary refresh).
- LangGraph node-level design.
- Retrieval tuning (K, scoring weights, recency decay).
- Per-source rate-limit and retry policies.
- Authentication (deferred to Phase 2 per PRD §11).

These will be addressed in their own specs as implementation begins.
