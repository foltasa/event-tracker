# Agent Layer — Detailed Design

**Status:** Draft v1 · **Date:** 2026-06-09
**Companion documents:** `docs/PRD.md` (product scope), `docs/specs/2026-06-08-event-tracker-tech-design.md` (high-level tech design).

---

## 1. Scope

This document specifies the agent layer: the LangGraph runtime, the 7 function tools, memory (chat history + distilled taste summary + RAG centroid), the RAG retrieval layer over Chroma, and the FastAPI routes that expose all of the above.

**In scope:** graph construction, tool surface, memory layout, RAG retrieval, API surface, error handling, testing strategy.

**Deferred to follow-up specs:**
- M1 token / cost display (data plumbing only — UI later).
- M8 plugin toggle UI (the tool-filtering seam is in place; the settings page is later).
- M9 multi-model UI (one provider for MVP).
- H2 LangSmith observability wiring (env-var enabled, no code coupling for MVP).
- Settings page in the frontend.

---

## 2. Architecture overview

The agent layer lives entirely inside the existing FastAPI process. No separate worker; no microservices.

```
backend/app/
  agent/
    runtime.py       # build_agent() — wires LLM, tools, checkpointer
    prompts.py       # CURATION_PROMPT, CONVERSATIONAL_PROMPT, SUMMARY_PROMPT
    tools.py         # 7 @tool functions
    memory.py        # checkpointer factory + taste-summary read/refresh helpers
    schemas.py       # DigestResponse, DigestPick, EventSummary
    llm.py           # build_llm() — ChatOpenAI -> OpenRouter base URL
  rag/
    embeddings.py    # OpenAI text-embedding-3-small client (already used by ingestion)
    chroma_store.py  # events collection, upsert/query helpers (already used by ingestion)
  api/
    routes_chat.py
    routes_digest.py
    routes_events.py
    routes_feedback.py
    routes_calendar.py
    routes_profile.py
```

**Boundary rules:**
- `agent/runtime.py` is the only module that imports LangGraph. Routes call `agent.invoke(...)` / `agent.astream(...)` and never import langgraph directly.
- `tools.py` is the contract between agent and backend; each tool is a thin function that delegates to a DB session helper or the `rag/` module.
- `rag/` has no LangGraph dependency — it is reused by tools, by the digest route, and by ingestion (already wired).

**Data flow per request type:**

| Request | Flow |
|---|---|
| `GET /digest` | check `digest_cache` for today → on miss: refresh taste summary if dirty → invoke agent in curation mode → cache result → return |
| `POST /chat` | open SSE stream → invoke agent in conversational mode with `thread_id=session_id` → mirror new messages to `chat_messages` → stream tokens/tool events to client |
| `POST /feedback` | write `feedback` row → if sentiment='up', refresh user's `taste_centroid` → mark `users.taste_summary_dirty=true` → return 204 |

---

## 3. LLM client

Single provider for MVP: OpenRouter, accessed via LangChain's `ChatOpenAI` pointed at OpenRouter's OpenAI-compatible endpoint.

```python
# agent/llm.py
def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.AGENT_MODEL,                    # default: "openai/gpt-4o-mini"
        api_key=settings.OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=0.7,
        streaming=True,
    ).with_retry(
        stop_after_attempt=2,
        wait_exponential_jitter=True,
    )
```

`AGENT_MODEL` is a config setting so the model can be changed without code edits. Multi-model UI (M9) plugs in here later.

---

## 4. Graph & prompts

### 4.1 Construction

```python
# agent/runtime.py
def build_agent(tools_enabled: list[str] | None = None) -> CompiledGraph:
    llm = build_llm()
    tools = select_tools(tools_enabled)            # all 7 by default
    checkpointer = SqliteSaver.from_conn_string("backend/data/agent.sqlite")
    return create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
    )
```

One compiled agent is built at FastAPI startup and reused for all requests. The `tools_enabled` parameter is unused for MVP but provides the seam that the future settings UI will hook into.

### 4.2 Invocation

Curation and conversational modes share the same compiled graph; they differ only in system prompt, the `response_format`, and the `thread_id` scheme.

```python
# Curation
result = agent.invoke(
    {"messages": [
        SystemMessage(CURATION_PROMPT.format(
            profile=profile, taste_summary=summary, event_pool=pool_json,
        )),
        HumanMessage("Pick today's events."),
    ]},
    config={"configurable": {"thread_id": f"digest:{user_id}:{date}"}},
    response_format=DigestResponse,
)
picks = result["structured_response"].picks

# Conversational
async for chunk in agent.astream(
    {"messages": [
        SystemMessage(CONVERSATIONAL_PROMPT.format(
            profile=profile, taste_summary=summary, today=date,
        )),
        HumanMessage(user_msg),
    ]},
    config={"configurable": {"thread_id": session_id}},
    stream_mode="messages",
):
    ...  # forward to SSE
```

The curation `thread_id` is per-day-per-user so its history does not pollute the user's chat session.

### 4.3 Prompts

All three prompts live in `agent/prompts.py`. Sketch contents:

- **CURATION_PROMPT** — inputs: profile (interests, about-me), distilled taste summary, candidate event pool serialized as JSON. Instruction: pick 3-5 events from the pool, justify each in 1-2 sentences grounded in profile/summary. May call `get_recommendations` to rank by taste similarity if helpful.
- **CONVERSATIONAL_PROMPT** — inputs: profile, distilled taste summary, today's date. Instruction: act as a Hamburg event concierge; use tools to search, recommend, save, record feedback. Cite event IDs with `[event:ID]` markers so the UI can render inline cards.
- **SUMMARY_PROMPT** — used by `memory.refresh_taste_summary()`, not by the agent itself. Inputs: profile, last 30 feedback rows with comments, last 10 saved events. Output: ≤80-word natural-language summary.

### 4.4 Candidate event pool

The curation pool is pre-filtered before being injected into the prompt:
- Date range: today through today + 7 days.
- Dedupe by `(source, source_id)`.
- Cap: 150 events. If more, truncate by `start_time` ascending. The agent may call `get_recommendations` to surface anything past the cap.

### 4.5 Digest output schema

```python
# agent/schemas.py
class DigestPick(BaseModel):
    event_id: str
    justification: str

class DigestResponse(BaseModel):
    picks: list[DigestPick] = Field(min_length=3, max_length=5)
```

Returned by `response_format` on the agent invocation. The route asserts `len(picks) >= 3` defensively and returns 502 on violation.

---

## 5. Tools

All seven live in `agent/tools.py` as `@tool`-decorated functions with Pydantic argument schemas. Each tool resolves the current `user_id` via a `contextvar` set by FastAPI middleware (`get_current_user_id()` helper) — no need to thread `user_id` through every signature.

| # | Tool | Args | Returns | Backing call |
|---|---|---|---|---|
| 1 | `search_events` | `date_from?`, `date_to?`, `categories?`, `text?`, `max_price?`, `location?`, `limit=20` | `list[EventSummary]` | `SELECT` on `events` with filters |
| 2 | `get_recommendations` | `date_from?`, `date_to?`, `n=10` | `list[EventSummary]` with `similarity_score` | embed taste centroid (or interests fallback) → Chroma `query` → join with `events` |
| 3 | `record_feedback` | `event_id`, `sentiment` ('up' \| 'down'), `comment?` | `{status: 'ok'}` | insert `feedback`; if 'up', refresh `taste_centroid`; mark `taste_summary_dirty=true` |
| 4 | `save_to_calendar` | `event_id` | `{status: 'ok'}` | insert into `saved_events` (idempotent on `(user_id, event_id)`) |
| 5 | `get_calendar` | `date_from?`, `date_to?` | `list[EventSummary]` | `SELECT` joining `saved_events` and `events` |
| 6 | `get_user_profile` | none | `{interests, about_me, taste_summary}` | read `users`; lazy summary refresh if dirty |
| 7 | `update_user_profile` | `interests?`, `about_me?` | `{status: 'ok'}` | update `users`; mark `taste_summary_dirty=true` |

### 5.1 Conventions

- Tools return JSON-serializable dicts / lists, never ORM objects.
- `EventSummary` is defined once in `agent/schemas.py` and shared across tools.
- Errors raise `ToolError(message)`. The prebuilt agent catches and surfaces them back to the LLM as tool messages so the model can recover or apologise gracefully.
- Tools that write to long-term state: `record_feedback` (insert + centroid refresh + dirty flag), `update_user_profile` (users row + dirty flag), `save_to_calendar` (saved_events insert). `get_user_profile` may trigger a lazy `taste_summary` refresh on read. All other tools are read-only.

### 5.2 Cold start

`get_recommendations` when the user has zero "up" feedback: the centroid is null, so the tool embeds the user's interest tags joined by `", "` and uses that as the query vector. If interest tags are also empty (defensive — should not happen post-onboarding), the tool returns an empty list and the agent is expected to fall back to `search_events`.

---

## 6. Memory

Three layers, each with a single owner.

### 6.1 Short-term chat history — LangGraph `SqliteSaver` checkpointer

- File: `backend/data/agent.sqlite` (separate from the app DB so checkpoint blobs do not collide with Alembic migrations).
- Keyed by `thread_id`:
  - Conversational: `session_id` (frontend-generated UUID, stable across the chat session).
  - Curation: `digest:{user_id}:{YYYY-MM-DD}` (ephemeral by day).
- LangGraph handles message append, tool-call persistence, and reload on next turn.

### 6.2 Chat message mirror — `chat_messages` table

- Written by `routes_chat.py` after each agent step yields.
- Used by the UI (chat history list) and by future M1 token tracking.
- Not read by the agent itself — the checkpointer is the agent's source of truth.
- Helper: `record_message(session_id, role, content, tool_name?, tokens?, cost?)` in `agent/memory.py`.

### 6.3 Long-term taste — `users` row + Chroma events collection

New columns on `users`:
- `taste_summary: str | None` — natural-language summary (≤80 words).
- `taste_summary_dirty: bool` — default `true` so first read triggers initial generation.
- `taste_centroid: bytes | None` — numpy `float32` array serialized; 1536 dims × 4 bytes ≈ 6 KB.

Helpers in `agent/memory.py`:
- `refresh_taste_summary(user_id)` — if dirty, load profile + last 30 feedback rows + last 10 saved events → LLM call with `SUMMARY_PROMPT` → write back, clear dirty flag.
- `refresh_taste_centroid(user_id)` — called from `record_feedback` on 'up'. Pull all 'up' feedback event_ids → fetch their embeddings from Chroma via `get_embeddings_for_ids` → mean → write back. If no likes remain, set to null.

**Schema migration:** one Alembic revision adds the three columns to `users`. No new tables.

**Lazy refresh timing:** taste summary refresh is called explicitly from two places: top of `routes_digest.py` (before agent invocation) and inside the `get_user_profile` tool. Worst case: a digest open after new feedback takes ~1 s extra.

---

## 7. RAG layer

A thin wrapper around Chroma. Two operations matter: write events at ingest time, query at recommend time.

### 7.1 Interface (`rag/chroma_store.py`)

```python
def upsert_events(events: list[Event]) -> None:
    """Called by ingestion. Embeds title + description + category + venue.
    Metadata: event_id, start_time (epoch), category, source."""

def query_by_vector(
    vector: list[float],
    n: int,
    where: dict | None = None,
) -> list[QueryHit]:
    """where supports: {"start_time": {"$gte": ..., "$lte": ...}},
    {"category": {"$in": [...]}}."""

def get_embeddings_for_ids(event_ids: list[str]) -> dict[str, list[float]]:
    """Used by refresh_taste_centroid()."""
```

One collection: `events`. Metric: cosine. Embedding: `text-embedding-3-small` (1536-dim). Ingestion is the only writer.

### 7.2 Embedded text per event

```
{title}

{description}

Category: {category}
Venue: {venue_name}, {neighborhood}
```

Deterministic and stable. Re-embedding only happens if the source event changes.

### 7.3 Retrieval flow in `get_recommendations`

1. Load `taste_centroid` from `users`. If null, embed the user's interest tags joined by `", "`.
2. Build `where` from tool args (date range → epoch range; optional category filter).
3. `query_by_vector(centroid, n=tool_arg_n, where=filter)`.
4. Join hits back to `events` rows for full data; return `EventSummary` shape with `similarity_score` attached so the agent can reason about match strength.

### 7.4 Tuning defaults

- `n` default 10; max 30.
- No recency decay in the vector query (time window is a hard filter; sufficient for MVP).
- No MMR diversification for MVP. If the digest ends up monotone in practice, add MMR.

### 7.5 Explicitly out of scope for MVP

- Hybrid vector + keyword search. `search_events` covers keyword; agent can call both tools if needed.
- Reranking with a second model. Latency and cost not justified at this stage.

---

## 8. API surface

Six route modules. All routes accept `X-User-Id` (defaults to `"local"` if missing). All responses are JSON except `/chat` which is SSE.

```
POST   /chat                       SSE stream
GET    /digest                     today's cached digest, generates on miss
POST   /digest/refresh             force regenerate today's digest
GET    /events                     paginated browse with filters
POST   /feedback                   record thumbs + optional comment
GET    /calendar                   saved events in date range
POST   /calendar                   save event to calendar
DELETE /calendar/{event_id}        unsave
GET    /profile                    profile + taste_summary
PUT    /profile                    update interests / about_me
POST   /profile/onboard            first-time setup (idempotent)
```

### 8.1 `POST /chat` (SSE)

Request:
```json
{ "session_id": "uuid", "message": "what's on Friday?" }
```

Stream event types (each emitted as `data: <json>\n\n`):

| `type` | Payload | Purpose |
|---|---|---|
| `token` | `{content: "..."}` | assistant text chunk |
| `tool_call` | `{name, args, id}` | tool invocation announced to the UI |
| `tool_result` | `{id, ok}` | tool completion (results not streamed; UI fetches event cards by ID) |
| `event_ref` | `{event_ids: [...]}` | extracted from `[event:ID]` markers in assistant text; tells UI which cards to render inline |
| `error` | `{message}` | recoverable agent failure mid-stream |
| `done` | `{}` | terminal |

Implementation: iterate `agent.astream(..., stream_mode="messages")`, transform each LangChain message into one or more SSE events, and call `record_message` to mirror to `chat_messages` on the side.

### 8.2 `GET /digest`

Response:
```json
{
  "date": "2026-06-09",
  "picks": [
    { "event_id": "...", "justification": "..." }
  ],
  "generated_at": "2026-06-09T08:32:11Z"
}
```

UI hydrates the cards by calling `/events?ids=...`. Keeps the digest payload tiny and avoids serializing the same event in two places.

### 8.3 `POST /feedback`

Request:
```json
{ "event_id": "...", "sentiment": "up", "comment": "loved the venue" }
```

Response: 204. Side effects (Chroma centroid refresh, dirty flag) happen synchronously — they are fast enough not to need backgrounding.

### 8.4 Pydantic models

The existing `app/schemas/` package already covers most routes (chat, digest, feedback, profile, calendar). This spec adds only:
- SSE event-type discriminated union for documentation purposes.
- `/chat` request body.
- `/digest/refresh` response (mirrors `/digest`).

---

## 9. Error handling

### 9.1 LLM calls

- Retry: `stop_after_attempt=2`, exponential jitter on `RateLimitError` and `APIConnectionError`.
- Non-retryable (4xx auth, quota): fail fast.
- After retries exhausted: digest route returns 502; chat route emits SSE `{type: "error"}` and closes.

### 9.2 Structured output parsing (curation)

- LangGraph's `response_format` handles parsing.
- Defensive: if `structured_response` key is missing or `picks` is empty / shorter than 3, return 502 with a generic message and log the malformed response. No silent fallback to random events — digest should be honest about failing.

### 9.3 Tool failures

- All tool errors raise `ToolError(message)`. The prebuilt agent catches and feeds the message back to the LLM as a tool message; the model can apologise or retry.
- Unknown event_id in `record_feedback` / `save_to_calendar` → `ToolError("event not found")`.
- Chroma unavailable → `get_recommendations` raises `ToolError("recommendations temporarily unavailable")`; agent falls back to `search_events`.

### 9.4 External event data

The agent assumes `events` is populated by ingestion. If empty (fresh DB, ingestion not yet run), `search_events` returns `[]` and the agent should tell the user "no events ingested yet".

### 9.5 Not in MVP

- Per-user rate limiting (single-user, local).
- Per-day token budget (M1 deferred).

---

## 10. Testing

### 10.1 Unit (fast, hermetic)

- `tests/agent/test_tools.py` — each tool called directly with a fake DB session and a stubbed Chroma. Validates query construction, return shape, and `ToolError` paths.
- `tests/agent/test_memory.py` — `refresh_taste_summary` and `refresh_taste_centroid` with stubbed LLM and Chroma; dirty-flag semantics (refresh only when dirty, flag cleared after).
- `tests/rag/test_chroma_store.py` — round-trip upsert + query, filter semantics. Uses Chroma's in-memory client.
- `tests/api/test_routes_*.py` — FastAPI `TestClient` with a fake `build_agent` returning canned responses. Validates routing, status codes, header handling, request/response shapes.

### 10.2 Integration (slower, no real LLM)

- `tests/integration/test_chat_sse.py` — real FastAPI app, real test DB, fake LLM. Drives a full `/chat` request and asserts SSE event sequence.
- `tests/integration/test_digest_cycle.py` — populate events fixture → call `/digest` with a fake LLM that returns canned structured picks → assert cache row written → second call returns cached result without invoking the LLM again.

### 10.3 Eval (manual, optional)

- `tests/eval/test_curation_quality.py`, marked `@pytest.mark.eval`, skipped by default. Real LLM, hand-curated fixture; asserts properties such as no duplicates, all event_ids exist, justification references profile keywords. Run on demand, not in CI.

### 10.4 Test helpers

- `FakeLLM` in `tests/agent/conftest.py` — minimal LangChain-compatible chat model returning scripted responses (including tool-call sequences). Keeps unit tests deterministic and zero-cost.

### 10.5 Out of scope

- Snapshot tests on LLM output (too brittle).
- Coverage targets.

---

## 11. Open implementation questions

Carried forward from the tech design plus things this spec deliberately defers to the implementation plan:

- Exact prompt wording (curation, conversational, summary). Drafts go in `agent/prompts.py` and are tuned during build.
- Default `AGENT_MODEL` value — `"openai/gpt-4o-mini"` chosen as starting point; revisit after first end-to-end run.
- Whether `record_feedback` centroid refresh should be moved to a background task if it ever shows up as latency. For MVP: synchronous.
- Whether to surface `similarity_score` to the user (e.g., in the digest card) or keep it internal. Defaulting to internal.
