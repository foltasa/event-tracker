# Central .env Configuration — Design

**Date:** 2026-06-13
**Status:** Approved

## Problem

The repo currently has two environment templates: `backend/.env.example` and `frontend/.env.example`. Variables must be maintained in two places, and the backend template is already out of sync with `backend/app/config.py` (missing `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `AGENT_MODEL`, etc.).

Additionally, the codebase carries an outdated assumption that embeddings must hit OpenAI directly — the user has confirmed that OpenRouter does proxy `text-embedding-3-small`, so the OpenAI direct-access path is no longer required.

## Goals

1. Single source of truth for runtime configuration: one `.env` and one `.env.example` at the repo root, consumed by both backend and frontend.
2. Drop the `OPENAI_API_KEY` configuration variable. All LLM and embedding traffic routes through OpenRouter using a single `OPENROUTER_API_KEY`.

## Non-Goals

- Changing the agent or RAG behavior beyond the embeddings-client base URL switch.
- Replacing `python-dotenv` / `pydantic-settings` / `dotenv` with a different config framework.
- Migrating existing local `.env` files (none exist yet — verified at design time).

## Architecture

```
event-tracker/
├── .env                  # real, gitignored
├── .env.example          # committed, documents every variable
├── backend/
│   └── app/config.py     # env_file = <repo-root>/.env (path resolved from __file__)
└── frontend/
    └── next.config.mjs   # dotenv.config({ path: '../.env' }) before Next.js inlines vars
```

Both apps read the same file. Variable namespaces don't collide:

- Backend variables (`DATABASE_URL`, `OPENROUTER_API_KEY`, etc.) are ignored by Next.js because they don't carry the `NEXT_PUBLIC_` prefix.
- Frontend variables (`NEXT_PUBLIC_*`) are ignored by Pydantic because `Settings.model_config` already sets `extra="ignore"`.

## Central `.env.example` content

```env
# --- Backend ---
DATABASE_URL=sqlite:///./event_tracker.db
DEFAULT_USER_ID=local

# Ingestion (optional — adapter skips itself when token is missing)
EVENTBRITE_TOKEN=
TICKETMASTER_API_KEY=

# Agent / LLM / Embeddings — everything routes via OpenRouter
OPENROUTER_API_KEY=
AGENT_MODEL=openai/gpt-4o-mini

# --- Frontend (NEXT_PUBLIC_* are inlined into the client bundle) ---
NEXT_PUBLIC_MOCK_MODE=false
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_USER_ID=local
```

Variables present in `backend/app/config.py` but omitted from the template (e.g. `agent_temperature`, `summary_model`, `embedding_model`, `embedding_dim`, `chroma_path`, `checkpointer_path`) keep their code defaults and are not surfaced to the user — they are tuning knobs, not setup steps.

## Code changes

### 1. `backend/app/config.py`

Resolve the repo root from this file's location and drop `openai_api_key`:

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # config.py → app → backend → repo


class Settings(BaseSettings):
    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    openrouter_api_key: str | None = None
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7
    summary_model: str = "openai/gpt-4o-mini"

    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    checkpointer_path: str = "./data/agent.sqlite"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
```

### 2. `backend/app/rag/embeddings.py`

Point the OpenAI SDK at OpenRouter and remove the outdated comment:

```python
"""Embeddings client. Routes via OpenRouter using the OpenAI SDK
(OpenRouter is OpenAI-API-compatible)."""
from openai import OpenAI

from app.config import settings

_client = OpenAI(
    api_key=settings.openrouter_api_key or "missing",
    base_url="https://openrouter.ai/api/v1",
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = _client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in resp.data]


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
```

`embedding_model` stays `text-embedding-3-small` and `embedding_dim` stays `1536` — no Chroma reindex required.

### 3. Audit other OpenAI references in the agent layer

Before merging, grep `backend/app/agent/` for any direct OpenAI-client construction or references to `settings.openai_api_key`. Anything found gets the same OpenRouter-base-URL treatment. If the agent already routes through OpenRouter (the `AGENT_MODEL=openai/gpt-4o-mini` default suggests it does), no further change is needed.

### 4. `frontend/next.config.mjs`

Load the root `.env` before Next.js evaluates `NEXT_PUBLIC_*` inlining:

```js
import { config } from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
config({ path: path.resolve(__dirname, '../.env') });

/** @type {import('next').NextConfig} */
const nextConfig = {};
export default nextConfig;
```

### 5. `frontend/package.json`

Add `dotenv` (~5 KB, zero-dep, widely used) as a `devDependency`. It is only invoked from `next.config.mjs`, which runs at build/dev time, not in the browser bundle.

### 6. `.gitignore`

Ensure the root-level `.env` is ignored. The existing entries for `backend/.env` and `frontend/.env.local` can stay (no harm), but they are no longer the documented setup path.

### 7. File deletions

- `backend/.env.example`
- `frontend/.env.example`

### 8. `README.md`

Collapse the two-step "Configure environment" section into one:

> Copy `.env.example` to `.env` in the repo root and fill in the values you need.

Remove the separate backend/frontend environment subsections. Anywhere the README references `backend/.env` or `frontend/.env.local` as the configuration location, replace with `.env` in the repo root.

## Verification

- **Backend smoke test:** from `backend/`, run `python -c "from app.config import settings; print(bool(settings.openrouter_api_key))"`. Returns `True` when the root `.env` contains a value.
- **Existing test suite:** `pytest backend/tests` continues to pass. Embedding tests patch `_client` directly, so the base-URL change is invisible to them.
- **Frontend dev server:** `npm run dev` from `frontend/` starts cleanly, and `process.env.NEXT_PUBLIC_API_URL` resolves to the value in `/.env` (verifiable via browser DevTools).
- **End-to-end:** with a real `OPENROUTER_API_KEY` set, trigger a small ingestion run plus one `/digest` request — confirms both the embedding path and the LLM path against OpenRouter in one shot.

## Rollback

Single commit. Reverting restores the per-app `.env.example` files and the OpenAI-direct embeddings client; no data migrations to undo.
