# Event Tracker — Technical Design

**Status:** Draft v1 · **Date:** 2026-06-08
**Companion document:** `docs/PRD.md` defines product scope; this document covers stack, architecture, and high-level implementation design.

---

## 1. Scope of this document

This is the high-level technical design that follows from the PRD. It locks down stack choices, repo layout, the agent's tool surface and memory architecture, data flow, and multi-user readiness. Detailed schemas, prompt templates, retrieval tuning, and node-level LangGraph design will follow in a more detailed spec when implementation begins (see §11).

---

## 2. Architecture overview

Two local services in one monorepo:

- **Frontend.** Next.js 14 (App Router, TypeScript) on `localhost:3000`. Dashboard, onboarding, calendar, settings, chat panel.
- **Backend.** FastAPI (Python 3.11+) on `localhost:8000`. Hosts the LangGraph agent, all tools, the ingestion pipeline, the scheduler, and persistence.

The frontend is a pure client of the backend's REST + SSE API. The agent runs entirely server-side.

---

## 3. Repo layout

```
event-tracker/
  frontend/                       # Next.js 14 (App Router, TypeScript)
    app/(dashboard)/              # main app shell
    app/onboarding/
    app/calendar/
    app/settings/
    components/                   # EventCard, DigestSection, ChatPanel, ...
    lib/api.ts                    # typed client for FastAPI
  backend/                        # FastAPI + LangGraph (Python 3.11+)
    app/
      agent/
        graph.py                  # LangGraph definition (ReAct loop)
        tools.py
        prompts.py
        memory.py
      api/
        routes_chat.py            # POST /chat (SSE streaming)
        routes_events.py          # GET /events, GET /digest
        routes_feedback.py
        routes_calendar.py
        routes_profile.py
      ingestion/
        eventbrite.py
        ticketmaster.py
        scrapers/hamburg.py
        normalize.py
        scheduler.py              # APScheduler daily job
      db/
        models.py                 # SQLAlchemy
        session.py
        migrations/               # Alembic
      rag/
        embeddings.py
        chroma_store.py
      observability/
        langsmith.py
      config.py
      main.py
    pyproject.toml
  docker-compose.yml              # convenience for both services
  README.md
  docs/
    PRD.md
    specs/
    plans/
```

---

## 4. Stack decisions

| Layer                   | Choice                                                                                 | Rationale                                                 |
| ----------------------- | -------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Frontend framework      | Next.js 14, App Router, TypeScript                                                     | Portfolio polish; preferred stack.                        |
| UI components           | Tailwind CSS + shadcn/ui                                                               | Fast, modern, accessible defaults.                        |
| Calendar UI             | `react-big-calendar` or `fullcalendar-react` (decision deferred to implementation) | Both mature; pick when integrating.                       |
| Backend framework       | FastAPI                                                                                | Async, type hints, OpenAPI auto-docs.                     |
| Agent framework         | LangGraph + LangChain (Python)                                                         | Course requirement; mature ecosystem.                     |
| LLM (default)           | Undeceided / GEMMA                                                                     | Course default; cheap on -mi                              |
|                         |                                                                                        |                                                           |
| Database                | SQLite + SQLAlchemy + Alembic                                                          | Zero ops; swap to Postgres is a connection-string change. |
| Vector store            | Chroma (local, embedded)                                                               | No infra; pgvector swap is straightforward later.         |
| Embeddings              | OpenAI `text-embedding-3-small`                                                      | Cheap, good quality, same provider.                       |
| Scheduler               | APScheduler (in-process)                                                               | Sufficient for one daily job.                             |
| Observability           | LangSmith                                                                              | Drop-in for LangGraph (H2).                               |
| Inter-service transport | REST + Server-Sent Events for chat                                                     | Simple, no WebSocket infra.                               |
| Dev runtime             | `uvicorn` + `next dev`, or `docker compose up`                                   | Local-only.                                               |

---

## 5. Agent design

### 5.1 Graph and modes

A single LangGraph ReAct-style loop with two entry points sharing tools, memory, and the underlying graph. Only the entry prompt differs.

- **Curation mode.** Triggered once per day on first open (or via a manual refresh). Inputs: profile, recent feedback (including comments), today's event pool. Output: 3–5 ranked picks with per-event natural-language justifications.
- **Conversational mode.** Triggered on every chat message. Inputs: user message, chat history, memory. Output: streamed agent reply, possibly after tool use, with structured event cards rendered inline.

### 5.2 Function tools

Seven tools, exposed through a settings panel with per-tool enable/disable toggles (M8).

| # | Tool                                               | Purpose                                                                       |
| - | -------------------------------------------------- | ----------------------------------------------------------------------------- |
| 1 | `search_events(filters)`                         | Query the event DB by date, category, text, price, location.                  |
| 2 | `get_recommendations(date_range, n)`             | RAG over liked-event embeddings, scored against profile (H1).                 |
| 3 | `record_feedback(event_id, sentiment, comment?)` | Persist thumbs-up/down with optional free-text comment; update taste profile. |
| 4 | `save_to_calendar(event_id)`                     | Add an event to the user's calendar.                                          |
| 5 | `get_calendar(date_range)`                       | Read saved events.                                                            |
| 6 | `get_user_profile()`                             | Read interests, "about me", and the distilled taste summary.                  |
| 7 | `update_user_profile(changes)`                   | Persist preferences the agent learns mid-conversation.                        |

### 5.3 Memory

**Short-term.** LangGraph state holds the current chat thread. Wiped on session end.

**Long-term, persistent across sessions:**

- **Structured store (SQLite).** User profile, all feedback events (including comments), saved events, calendar entries.
- **Vector store (Chroma, local).** Embeddings of liked events. Powers `get_recommendations` (Agentic RAG). Liked-event comments are concatenated into the embedded text so taste nuance ("loved the venue, hated the lineup") influences retrieval.
- **Distilled taste summary.** A short natural-language profile (e.g., *"prefers small intimate venues, dislikes EDM, neutral on outdoor events, weekday late-evening OK"*) regenerated periodically from recent feedback and comments, stored in the user table, and injected into curation prompts.

### 5.4 Cold-start behaviour

On day one, with no feedback yet, the agent recommends purely from stated interests by embedding the interest tags themselves and retrieving the most similar events in the pool. The feedback loop then takes over.

---

## 6. Data flow

1. **Daily ingestion (APScheduler, 04:00 local).** Scraper + API clients → normalise to the `Event` table → embed event descriptions → upsert into Chroma.
2. **App open.** Frontend calls `GET /digest`. Backend checks whether today's digest is cached; if not, runs the agent in curation mode and caches the result. Returns picks + justifications.
3. **Feedback.** `POST /feedback` writes to the DB (including the optional comment), refreshes the user's taste centroid in Chroma, and queues a distilled-summary refresh when a threshold is reached.
4. **Chat.** `POST /chat` opens an SSE stream. The LangGraph conversational mode runs, calls tools through internal services, and streams tokens to the UI.

---

## 7. Multi-user readiness (designed for, not built)

- Every DB table includes a `user_id` column (defaulted to `"local"` in MVP).
- Every API route accepts a user identity (`X-User-Id` header in MVP, JWT later).
- LangGraph state is keyed by `user_id`.
- Settings, profile, calendar, feedback, and the vector namespace are user-scoped from day one.

Phase 2 multi-user becomes additive: drop in `next-auth` on the frontend, JWT middleware in FastAPI, and the rest of the code is untouched.

---

## 8. Secrets and configuration

Per-service `.env` files (gitignored), with an `.env.example` checked in. Required keys:

- `OPENROUTER_API_KEY`
- `EVENTBRITE_TOKEN`
- `TICKETMASTER_API_KEY`
- `LANGSMITH_API_KEY` (optional, enables H2)

---

## 9. Rubric implementation notes

| Rubric item                                      | Implementation summary                                                        | Marginal cost over MVP |
| ------------------------------------------------ | ----------------------------------------------------------------------------- | ---------------------- |
| **M1** Token / cost display                | Footer in chat panel + settings rollup, sourced from LangSmith / OpenAI usage | ~1 h                   |
| **M3** Memory                              | Short-term: LangGraph state. Long-term: SQLite + Chroma + distilled summary   | Built into MVP         |
| **M4** External API tool                   | Eventbrite + Ticketmaster ingestion clients                                   | Built into MVP         |
| **M8** ≥5 function tools w/ plugin toggle | 7 tools + settings toggle panel                                               | ~2 h                   |
| **M9** Multi-model support                 | LangChain abstraction; settings dropdown                                      | ~1–2 h                |
| **H1** Agentic RAG                         | `get_recommendations` retrieves over Chroma index of liked events           | ~3–4 h                |
| **H2** LLM observability                   | LangSmith tracing on all agent runs                                           | ~1–2 h                |
| **H4** Agent learns from feedback          | Vector index + distilled summary update on feedback                           | Built into MVP         |
| **H5** External data integration           | Two APIs + Hamburg scraper                                                    | Built into MVP         |

---

## 10. Open implementation questions

To resolve when starting implementation:

- Which specific Hamburg scraper target (hamburg.de, Szene Hamburg, ASK Helmut, …) offers the best coverage-to-fragility ratio.
- Default daily digest size (3 vs 5 vs configurable).
- Exact thresholds for distilled-summary refresh (every N feedbacks? time-based?).
- Whether to expose temperature / model parameters in the settings panel (small additional course-bonus territory).
- Specific Anthropic model to ship for M9 (Claude Sonnet 4.6 likely default).

---

## 11. What this document does not yet cover

The next iteration of this spec, before implementation, should add:

- Concrete SQLAlchemy / Pydantic schemas for `User`, `Event`, `Feedback`, `SavedEvent`, `ChatMessage`.
- FastAPI route signatures with request / response models.
- LangGraph node-level diagram (which node decides curation vs. conversation, when retrieval fires, how memory is loaded).
- Prompt templates for curation mode, conversational mode, and the distilled-summary refresh.
- Retrieval tuning: K, scoring weights, recency decay, diversification.
- Error handling, retry policy, and rate-limit behaviour per external service.
