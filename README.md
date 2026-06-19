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

Hamburg is the first (and currently the only) supported city, but the
architecture is single-user-by-design with `user_id` as a first-class concept
from day one, so multi-user and additional cities are an additive change.

---

## Implementation Status

The MVP covers the foundation for the vision above. Pieces below are grouped
into **implemented**, **partially implemented**, and **not yet implemented**.

## Implemented

### Event database

- SQLite + SQLAlchemy + Alembic with a normalised `Event` schema.
- Ingestion adapters for **Eventbrite** and **Ticketmaster**, plus a
  **Hamburg-specific scraper**. Adapters skip themselves when their API key is
  missing, so the app stays usable on partial credentials. Additional sources
  — and broader scraper coverage in particular — are a planned next step to
  improve catalogue depth for small and indie venues.
- **APScheduler** runs ingestion daily at 04:00 Europe/Berlin; a manual
  `POST /ingestion/run` endpoint is available for on-demand refreshes.
- Event descriptions are embedded and upserted into a local **Chroma** vector
  store for retrieval.

### AI agent

- **LangGraph** ReAct loop, one graph serving two entry points:
  - **Curation mode** (the daily digest) — picks 3–5 events with per-event
    justifications and caches the result for the day.
  - **Conversational mode** — chat panel with **SSE streaming**.
- LLM access goes through **OpenRouter** (default model
  `deepseek/deepseek-v4-pro`, configurable via `AGENT_MODEL`).
- Tools currently registered:
  `search_events`, `get_recommendations`, `record_feedback`,
  `save_to_calendar`, `get_calendar`, `get_user_profile`,
  `update_user_profile`, `edit_facts`, `edit_taste_summary`.
- An optional **web search** path (`web_search` + `ingest_event_from_url`
  via Tavily) exists but is **disabled by default** (`WEB_SEARCH_ENABLED=false`)
  while it is being reworked.

### Agentic Memory

Three persistent surfaces in addition to the relational store:

- **`facts_md`** — durable facts the user has stated about themselves
  (cap: 200 lines). The agent maintains this via `edit_facts` with
  string-replace semantics.
- **`taste_summary`** — the agent's inferred behavioural picture of the
  user (cap: 20 lines), edited via `edit_taste_summary`.
- **How the agent sees memory.** On every turn both blocks are rendered
  directly into the agent's system prompt, so the agent always has them in
  context without having to call a tool first. 

Short-term chat state is held in LangGraph's SQLite checkpointer; chat
messages are also mirrored into the relational DB for inspection.

### Frontend

- Next.js 14 (App Router, TypeScript) frontend.
- Weekly grid (`WeekView`) that shows the user's **saved events** alongside
  their **appointments** (`/appointments` API), with a modal for creating
  and editing appointments.
- Saved events appear automatically once the agent (or the user) calls
  `save_to_calendar`.
- An **Explore page** combines the day's curated digest at the top with a
  filterable, paginated feed of upcoming events below it. Each card exposes
  👍 / 👎 feedback and a save-to-calendar action, with optimistic UI updates
  so reactions feel instant.
- A persistent **chat panel** runs alongside every page so the user can ask
  the agent to refine picks, search, or save events without leaving the
  current view.

## Partially implemented

### Personalised recommendations

The RAG plumbing is implemented, but the personalisation signal it operates
on is still narrow, and the agent is not forced to use it.

**What is done:**

- A RAG path exists end-to-end: events are embedded into a local
  **Chroma** collection on ingestion; `get_recommendations` runs a cosine
  query against the user's **taste centroid** (mean of liked-event
  embeddings, recomputed on every 👍) or, as cold-start, an embedding of the
  user's interest tags.
- The agent justifies every digest pick in natural language, grounded in the
  user profile and memory blocks.

**Where it falls short today:**

- **Likes are the only personalisation signal.** Dislikes, free-text comments
  on feedback, and events the user saves to the calendar are stored but do
  **not** move the taste vector or filter results.
- **Comments are not embedded.** The PRD calls for comment text to enrich
  liked-event embeddings; current code embeds title/description/category/venue
  only.
- **`get_recommendations` is optional.** The curation and chat prompts both
  treat it as "use if helpful." The digest in particular often gets produced
  from a plain time-ordered SQL slice without any RAG call.
- **Single mean vector.** A user with diverse interests (music + tech + food
  + outdoors) collapses to one centroid that may match none of those clusters
    well.
- **No de-duplication.** Already-saved, already-disliked, or
  already-seen-in-yesterday's-digest events can re-appear.

## Not yet implemented

* Proactive Recommendations
* User Onboarding
* User Accounts
* Guardrails
* Token cost control

## Tech stack

| Layer        | Choice                                                      |
| ------------ | ----------------------------------------------------------- |
| Frontend     | Next.js 14 (App Router, TypeScript), Tailwind CSS, SWR      |
| Backend      | FastAPI (Python 3.11+), Uvicorn                             |
| Agent        | LangGraph + LangChain, OpenRouter                           |
| Database     | SQLite + SQLAlchemy + Alembic                               |
| Vector store | Chroma (local, embedded)                                    |
| Embeddings   | OpenAI `text-embedding-3-small` (via OpenRouter / OpenAI) |
| Scheduling   | APScheduler                                                 |
| Transport    | REST + Server-Sent Events for chat                          |
| Tests        | pytest (backend), Vitest + Testing Library (frontend)       |

---

## Repository layout

```
event-tracker/
├── backend/                  # FastAPI + LangGraph
│   ├── app/
│   │   ├── agent/            # LangGraph runtime, tools, prompts, memory
│   │   ├── api/              # FastAPI routers (chat, digest, events, ...)
│   │   ├── db/               # SQLAlchemy models, Alembic migrations
│   │   ├── ingestion/        # Eventbrite, Ticketmaster, Hamburg scraper
│   │   ├── rag/              # Chroma store + embeddings
│   │   ├── schemas/          # Pydantic API schemas
│   │   ├── web_research/     # Tavily-backed web search (feature-flagged)
│   │   ├── config.py
│   │   └── main.py
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── tests/
├── frontend/                 # Next.js 14
│   ├── app/                  # App Router pages (calendar, explore)
│   ├── components/           # AppShell, ChatPanel, calendar, EventCard, ...
│   ├── lib/                  # API client, types, calendar layout helpers
│   └── package.json
├── docs/                     # PRD, tech design, specs, plans
├── .env.example
└── README.md
```

---

## Getting started

### Prerequisites

- **Python 3.11+**
- **Node.js 18+** and **npm**
- An **OpenRouter** API key (required for the agent and embeddings)
- Optional: **Eventbrite** token, **Ticketmaster** API key, **Tavily** key

### 1. Clone and configure

```bash
git clone <repo-url> event-tracker
cd event-tracker
cp .env.example .env
# edit .env and fill in OPENROUTER_API_KEY, plus any ingestion tokens you have
```

Required environment variables (full list in `.env.example`):

| Variable                 | Purpose                                                          |
| ------------------------ | ---------------------------------------------------------------- |
| `OPENROUTER_API_KEY`   | LLM + embeddings access (required)                               |
| `AGENT_MODEL`          | OpenRouter model id (default `openai/gpt-4o-mini`)             |
| `DATABASE_URL`         | SQLAlchemy URL (default `sqlite:///./event_tracker.db`)        |
| `DEFAULT_USER_ID`      | Single-user MVP identity (default `local`)                     |
| `EVENTBRITE_TOKEN`     | Optional — enables Eventbrite ingestion                         |
| `TICKETMASTER_API_KEY` | Optional — enables Ticketmaster ingestion                       |
| `WEB_SEARCH_ENABLED`   | Off by default;`true` registers the web-search tools           |
| `TAVILY_API_KEY`       | Required only if web search is enabled                           |
| `NEXT_PUBLIC_API_URL`  | Frontend → backend base URL (default `http://localhost:8000`) |
| `NEXT_PUBLIC_USER_ID`  | Frontend identity header (default `local`)                     |

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
cron and the `POST /ingestion/run` endpoint, without needing the backend
process to be up. Run it from `backend/`:

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

- `docs/idea.md` — original product idea
- `docs/PRD.md` — product requirements
- `docs/specs/` — technical design + per-feature specs
- `docs/plans/` — implementation plans

---

## Status

This is a portfolio / coursework project. The MVP is single-user, local-only,
and scoped to Hamburg. The architecture is intentionally written so that
multi-user support, additional cities, and the proactive-suggestion layer can
be added without a rewrite.
