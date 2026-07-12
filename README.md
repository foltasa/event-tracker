# Slot In

A personal AI event concierge for Hamburg: a calendar ("timetable") wired
into an event database and an AI agent that learns your taste over time.

---

## The Vision

The product is a **timetable** that is more than a calendar. Three pieces work
together:

1. **A timetable / calendar.** A weekly view where you see your own appointments
   alongside the events you decide to attend.
2. **An event database.** A continuously refreshed catalogue of events in your
   city, ingested from public APIs and city-specific sources.
3. **An AI agent.** A conversational concierge that knows the catalogue, knows
   your, your schedule and makes proactive event recommendations.

The agent's job is **personalised event recommendations**. It learns what you
like through lightweight feedback (👍 / 👎, optional comments, what you save to
your calendar) and explains every suggestion in plain language grounded in your
profile.

The longer-term vision goes one step further: when the agent spots an event
with a strong fit to the user's taste, it should **proactively notify the
user** and **drop the event straight into the calendar as a suggestion**, so
the user only has to accept or reject it — discovery without active search.

Hamburg is currently the only supported city, but the
architecture is single-user-by-design with `user_id` as a first-class concept
from day one, so multi-user and additional cities are an additive change.

---

## Implementation Status

The MVP covers the foundation for the vision above. Pieces below are grouped
into **implemented**, **partially implemented**, and **not yet implemented**.

## Implemented

### Event database

- SQLite + SQLAlchemy + Alembic with a normalised `Event` schema.
- Five ingestion sources currently registered — one API adapter and four
  HTML/GraphQL scrapers:

  - **Ticketmaster** (API, with Wikipedia lookups to enrich thin descriptions)
  - **Eventim** (API)
  - **Theater Hamburg** (widget-JWT + GraphQL)
  - **Oh, schon hell!** (sitemap-delta HTML scraper)
  - **Hamburg city portal** (HTML scraper)

  Live catalogue as of 2026-07-12: **6,677 active events** across all sources
  (7,433 total including past events).

  | Source          | Active events | Total |
  | --------------- | ------------: | ----: |
  | theater_hamburg |         6,107 | 6,188 |
  | ticketmaster    |           325 |   341 |
  | eventim         |           148 |   187 |
  | ohschonhell     |            88 |   675 |
  | hamburg_scraper |             9 |    42 |
- **LLM-driven categorisation.** Every event is classified with an LLM
  (default `google/gemini-2.5-flash`) into a fixed taxonomy. Results are
  cached by content hash, so re-runs cost nothing when the source content
  hasn't changed.
- **Description enrichment, no LLM generation.** When a source ships a thin
  or missing description, the pipeline falls back to a real reference source
  (Wikipedia for Ticketmaster attractions). Events without a real description
  are hidden by default — LLM-generated descriptions are explicitly
  disallowed.
- **Per-source circuit breaker.** Persistent fetch failures trip a flag in
  the `IngestionState` table; a tripped source is skipped until an operator
  manually resets it.
- **APScheduler** runs the full pipeline daily at 04:00 Europe/Berlin; the
  same pipeline can be triggered manually via `python -m scripts.ingest` or
  the `POST /ingestion/run` endpoint on the running backend.
- Visible events are embedded and upserted into a local **Chroma** vector
  store on every run; stale vectors are purged in the same pass.

### AI agent

- **LangGraph** ReAct loop, one graph serving two entry points:
  - **Curation mode** (the daily digest) — picks 3–5 events with per-event
    justifications and caches the result for the day.
  - **Conversational mode** — chat panel with **SSE streaming**.
- LLM access goes through **OpenRouter** (default model
  `openai/gpt-4o-mini`, configurable via `AGENT_MODEL`).
- Tools currently registered:
  `search_events`, `get_recommendations`, `record_feedback`,
  `save_to_calendar`, `get_calendar`, `get_user_profile`,
  `update_user_profile`, `edit_facts`, `edit_taste_summary`.
- An optional **web search** path (`web_search` + `ingest_event_from_url`
  via Tavily) exists but is **disabled by default** (`WEB_SEARCH_ENABLED=false`)
  while it is being reworked.

### Agentic memory

The user-facing memory model is the **About Me** page, which stores three
things on the `User` row and renders into the agent's system prompt on every
turn:

- **`about_me`** — free-text self-description the user maintains directly.
- **`active_categories`** — the set of event categories the user wants
  proactively suggested (everything else is de-prioritised in the digest).
- **`taste_facets`** — per-category preferences (artists, genres, venues,
  free-text notes), editable from the About Me form and also refined
  in the background from feedback comments when
  `COMMENT_EXTRACTOR_ENABLED=true`.

Legacy `facts_md` / `taste_summary` blobs still exist on the `User` row and
the agent still has `edit_facts` / `edit_taste_summary` tools for them, but
they are no longer injected into the prompt — the About Me surface has
superseded them for the runtime.

Short-term chat state is held in LangGraph's SQLite checkpointer; chat
messages are also mirrored into the relational DB for inspection.

### Frontend

- Next.js 14 (App Router, TypeScript) frontend.
- Weekly grid (`WeekView`) that shows the user's **saved events** alongside
  their **appointments** (`/appointments` API), with a modal for creating
  and editing appointments. Blocks and all-day chips are colour-coded by
  event category.
- The calendar also renders **recommendations** (dimmed) inline for each day
  so the user can accept or dismiss them without leaving the timetable.
- Saved events appear automatically once the agent (or the user) calls
  `save_to_calendar`.
- An **Explore page** combines the day's curated digest at the top with a
  filterable, paginated feed of upcoming events below it. Each card exposes
  👍 / 👎 feedback and a save-to-calendar action, with optimistic UI updates
  so reactions feel instant.
- An **About Me page** where the user edits their free-text profile, toggles
  active categories, and manages per-category taste facets (artists,
  genres, venues, notes).
- A persistent **chat panel** runs alongside every page so the user can ask
  the agent to refine picks, search, or save events without leaving the
  current view.

## Personalised recommendations

The recommender was reworked in Phase 1 to be **per-category** with a
tiered ranking

**What is done:**

- Retrieval runs per active category. For each category the recommender
  fetches candidates from three sources and merges them into a ranked list:
  1. **Keyword** — direct matches on the user's facet terms (artists,
     genres, venues).
  2. **Semantic** — cosine search in Chroma against a per-category
     taste vector, kept up to date by `refresh_taste_centroids` on every
     save / like / dislike.
  3. **Fill** — time-ordered SQL fallback when the above return too few.
     Duplicates across sources are collapsed and ranked by
     `(source_tier, similarity)`.
- Feedback comments can be mined by a background **comment extractor**
  (opt-in via `COMMENT_EXTRACTOR_ENABLED=true`) that promotes recurring
  terms into `taste_facets`, closing the loop between free-text feedback
  and future recommendations.
- The agent justifies every digest pick in natural language, grounded in the
  user's About Me and per-category facets.

## Not yet implemented

* Proactive Recommendations
* User Onboarding
* User Accounts
* Guardrails
* Token cost control

## Tech stack

| Layer        | Choice                                                     |
| ------------ | ---------------------------------------------------------- |
| Frontend     | Next.js 14 (App Router, TypeScript), Tailwind CSS, SWR     |
| Backend      | FastAPI (Python 3.11+), Uvicorn                            |
| Agent        | LangGraph + LangChain, OpenRouter                          |
| Database     | SQLite + SQLAlchemy + Alembic                              |
| Vector store | Chroma (local, embedded)                                   |
| Embeddings   | OpenAI`text-embedding-3-small` (via OpenRouter / OpenAI) |
| Scheduling   | APScheduler                                                |
| Transport    | REST + Server-Sent Events for chat                         |
| Tests        | pytest (backend), Vitest + Testing Library (frontend)      |

---

## Repository layout

```
event-tracker/
├── backend/                  # FastAPI + LangGraph
│   ├── app/
│   │   ├── agent/            # LangGraph runtime, tools, prompts, memory
│   │   ├── api/              # FastAPI routers (chat, digest, events,
│   │   │                     #   feedback, calendar, appointments,
│   │   │                     #   about_me, profile)
│   │   ├── db/               # SQLAlchemy models, Alembic migrations
│   │   ├── ingestion/        # API adapters + scrapers/ subpackage,
│   │   │                     #   LLM categorizer, dedup, embed step
│   │   ├── rag/              # Chroma store + embeddings
│   │   ├── schemas/          # Pydantic API schemas
│   │   ├── web_research/     # Tavily-backed web search (feature-flagged)
│   │   ├── config.py
│   │   └── main.py
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── tests/
├── frontend/                 # Next.js 14
│   ├── app/                  # App Router pages (calendar, explore,
│   │                         #   about-me, settings)
│   ├── components/           # AppShell, ChatPanel, calendar, EventCard,
│   │                         #   DigestSection, FeedSection, ...
│   ├── lib/                  # API client, types, calendar layout helpers
│   └── package.json
├── docs/                     # Design docs + implementation plans
│   ├── Exploration.md
│   ├── specs/
│   └── plans/
├── .env.example
└── README.md
```

---

## Getting started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** and **npm**
- An **OpenRouter** API key (required for the agent, categoriser, and
  embeddings)
- Optional: **Ticketmaster** API key (enables the Ticketmaster adapter),
  **Tavily** key (only if you flip `WEB_SEARCH_ENABLED=true`). The four
  scraper sources need no credentials.

### 1. Clone and configure

```bash
git clone <repo-url> event-tracker
cd event-tracker
cp .env.example .env
# edit .env and fill in OPENROUTER_API_KEY, plus any ingestion tokens you have
```

Required environment variables (full list in `.env.example`):

| Variable                      | Purpose                                                            |
| ----------------------------- | ------------------------------------------------------------------ |
| `OPENROUTER_API_KEY`        | LLM + embeddings access (required)                                 |
| `AGENT_MODEL`               | Conversational / curation model id (default`openai/gpt-4o-mini`) |
| `CATEGORIZATION_MODEL`      | Ingestion categoriser (default`google/gemini-2.5-flash`)         |
| `DATABASE_URL`              | SQLAlchemy URL (default`sqlite:///./event_tracker.db`)           |
| `DEFAULT_USER_ID`           | Single-user MVP identity (default`local`)                        |
| `TICKETMASTER_API_KEY`      | Optional — enables the Ticketmaster adapter                       |
| `WEB_SEARCH_ENABLED`        | Off by default;`true` registers the web-search tools             |
| `TAVILY_API_KEY`            | Required only if web search is enabled                             |
| `COMMENT_EXTRACTOR_ENABLED` | Off by default;`true` runs the LLM comment-to-facet extractor    |
| `NEXT_PUBLIC_API_URL`       | Frontend → backend base URL (default`http://localhost:8000`)    |
| `NEXT_PUBLIC_USER_ID`       | Frontend identity header (default`local`)                        |

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
uvicorn app.main:app --reload
```

On first run the app applies Alembic migrations, bootstraps the default user,
and starts the daily ingestion scheduler.

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

For a production-style run, build once and then serve the built bundle:

```bash
npm run build
npm run start
```

### 4. Trigger ingestion manually (optional)

The repo ships a standalone script that runs the same pipeline as the daily
cron, without needing the backend process to be up. Run it from `backend/`:

```bash
python -m scripts.ingest
```

---

## Testing

```bash
# Backend
cd backend
pytest

# Frontend
cd frontend
npm test
```

---

## Documentation

In-repo design and planning docs live under `docs/`:

- `docs/Exploration.md` — early exploration notes
- `docs/specs/` — technical design + per-feature specs
- `docs/plans/` — implementation plans

For invariants and gotchas inside the ingestion pipeline, see
`backend/app/ingestion/CLAUDE.md`.

---

## Status

This is a portfolio / coursework project. The MVP is single-user, local-only,
and scoped to Hamburg. The architecture is intentionally written so that
multi-user support, additional cities, and the proactive-suggestion layer can
be added without a rewrite.
