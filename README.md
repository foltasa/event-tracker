# Event Tracker

A personalized AI agent for discovering events in Hamburg. The app ingests events from multiple sources daily, curates a digest using a LangGraph ReAct agent, and lets you refine recommendations through a conversational chat interface.

## Architecture

| Layer | Tech | Port |
|---|---|---|
| Frontend | Next.js 14 (App Router, TypeScript) | 3000 |
| Backend | FastAPI + LangGraph agent | 8000 |
| Database | SQLite (via SQLAlchemy + Alembic) | — |
| Vector store | ChromaDB | — |
| Ingestion | APScheduler (daily 04:00 Berlin time) | — |

## Prerequisites

- Node.js 18+
- Python 3.11+
- An activated Python virtual environment (`.venv`)

## Setup

### 1. Clone and install

```powershell
git clone <repo-url>
cd event-tracker

# Backend
pip install -e ".\backend[dev]"

# Frontend
cd frontend
npm install
```

### 2. Configure environment

Copy the template at the repo root and fill in the values you need:

```powershell
Copy-Item .env.example .env
```

The file lives at the repo root and is consumed by both backend and frontend. All keys (with comments) are listed inside `.env.example`. For a local-scraper-only setup you only need `OPENROUTER_API_KEY`; `EVENTBRITE_TOKEN` and `TICKETMASTER_API_KEY` can be left blank and those adapters will skip themselves.

### 3. Apply database migrations

```powershell
cd backend
alembic upgrade head
```

## Entry Points

### Frontend dev server

```powershell
cd frontend
npm run dev          # http://localhost:3000
```

### Frontend production build

```powershell
cd frontend
npm run build
npm run start        # http://localhost:3000
```

### Backend server

```powershell
cd backend
python -m uvicorn app.main:app --reload   # http://localhost:8000
```

Interactive API docs are available at `http://localhost:8000/docs` once the server is running.

### Tests

```powershell
# Backend
cd backend
pytest

# Frontend
cd frontend
npm run test          # single run
npm run test:watch    # watch mode
```

### Database migrations (Alembic)

```powershell
cd backend
alembic upgrade head                                  # apply all migrations
alembic revision --autogenerate -m "description"      # generate a new migration
alembic downgrade -1                                  # roll back one step
```

## API Overview

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check |
| GET | `/digest` | Today's AI-curated digest (cached) |
| POST | `/digest/refresh` | Force-regenerate the digest |
| POST | `/chat` | Streaming agent chat (SSE) |
| GET | `/events` | Paginated event feed with filters |
| GET | `/events/{id}` | Single event detail |
| POST | `/feedback` | Record thumbs-up / thumbs-down |
| DELETE | `/feedback/{id}` | Remove feedback |
| GET | `/calendar` | Saved events |
| POST | `/calendar/{id}` | Save an event |
| DELETE | `/calendar/{id}` | Remove a saved event |
| GET | `/profile` | User profile and preferences |
| PUT | `/profile` | Update user preferences |
| POST | `/ingestion/run` | Manually trigger ingestion pipeline |

## Project Structure

```
event-tracker/
├── frontend/               # Next.js dashboard
│   ├── app/                # App Router pages and layout
│   ├── components/         # UI components (DigestSection, FeedSection, ChatPanel, EventDetailOverlay)
│   ├── hooks/              # React hooks (useChat)
│   ├── lib/                # API client, TypeScript types, SWR provider
│   └── fixtures/           # JSON fixtures for mock mode
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI application entry point
│   │   ├── config.py       # Environment/settings via Pydantic
│   │   ├── agent/          # LangGraph ReAct agent (runtime, tools, memory, prompts)
│   │   ├── api/            # Route handlers (digest, chat, events, feedback, calendar, profile)
│   │   ├── db/             # SQLAlchemy models and session management
│   │   ├── ingestion/      # Eventbrite, Ticketmaster, Hamburg scraper adapters
│   │   ├── rag/            # ChromaDB vector store and OpenAI embeddings
│   │   └── schemas/        # Pydantic request/response models
│   └── tests/              # pytest test suite
└── docs/
    ├── PRD.md
    ├── requirements.md
    ├── specs/              # Detailed design documents
    └── plans/              # Implementation plans
```

## Mock Mode

Set `NEXT_PUBLIC_MOCK_MODE=true` in `.env` to run the frontend with fixture data — no backend required. This is the default for new setups.
