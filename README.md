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

**Backend** — copy `backend/.env.example` to `backend/.env`:

```env
DATABASE_URL=sqlite:///./event_tracker.db
DEFAULT_USER_ID=local
EVENTBRITE_TOKEN=your_eventbrite_token_here
TICKETMASTER_API_KEY=your_ticketmaster_api_key_here
OPENAI_API_KEY=your_openai_api_key        # for embeddings
AGENT_MODEL=openai/gpt-4o-mini            # LLM for the agent
```

**Frontend** — copy `frontend/.env.example` to `frontend/.env.local`:

```env
NEXT_PUBLIC_MOCK_MODE=true               # set to false to use the real backend
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USER_ID=local
```

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

Set `NEXT_PUBLIC_MOCK_MODE=true` in `frontend/.env.local` to run the frontend with fixture data — no backend required. This is the default for new setups.
