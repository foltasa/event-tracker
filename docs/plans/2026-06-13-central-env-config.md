# Central .env Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two per-app `.env.example` files with a single `.env` / `.env.example` at the repo root, and drop `OPENAI_API_KEY` so embeddings route through OpenRouter alongside the LLM.

**Architecture:** One `.env` lives at the repo root. The backend resolves its path from `config.py`'s location via `pathlib`. The frontend loads it from `next.config.mjs` using the `dotenv` package before Next.js inlines `NEXT_PUBLIC_*` variables. `OPENAI_API_KEY` is removed from the Settings model; `app/rag/embeddings.py` points the OpenAI SDK at OpenRouter's base URL using `OPENROUTER_API_KEY`.

**Tech Stack:** Python 3.11, FastAPI, pydantic-settings, OpenAI SDK 1.x, Next.js 14, dotenv (npm).

**Spec:** `docs/specs/2026-06-13-central-env-config-design.md`

**Pre-flight audit (already done at plan time):**
- `app/agent/llm.py` already points at OpenRouter — no agent-layer changes needed.
- `schemas/common.py` references `"openai"` as an `LLMProvider` literal (UI provider toggle), not the API key — leave untouched.
- `.gitignore` line 30 (`*.env`) already covers the root-level `.env` — no change needed, but verified in Task 8.

---

### Task 1: Create the central `.env.example` at the repo root

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Write the file**

Create `.env.example` at the repo root with the following content (exact):

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

- [ ] **Step 2: Verify file presence**

Run: `Test-Path .env.example` (PowerShell) — expected `True`.

- [ ] **Step 3: Commit**

```powershell
git add .env.example
git commit -m "chore(config): add root-level .env.example template"
```

---

### Task 2: Point backend Settings at the root-level `.env`

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_config.py`:

```python
from pathlib import Path
from app.config import Settings


def test_settings_env_file_points_to_repo_root():
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).name == ".env"
    # config.py → app → backend → repo  (3 levels up from app/config.py)
    expected_root = Path(__file__).resolve().parents[2]
    assert Path(env_file).parent == expected_root
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_config.py::test_settings_env_file_points_to_repo_root -v`
Expected: FAIL — `env_file` is the bare string `".env"`, not an absolute path under the repo root.

- [ ] **Step 3: Update `backend/app/config.py` to resolve the repo root**

Replace the file's contents with:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # config.py -> app -> backend -> repo


class Settings(BaseSettings):
    """Backend runtime configuration sourced from env / .env file."""

    database_url: str = "sqlite:///./event_tracker.db"
    default_user_id: str = "local"
    eventbrite_token: str | None = None
    ticketmaster_api_key: str | None = None

    # Agent / LLM
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None  # retained until Task 3 removes it
    agent_model: str = "openai/gpt-4o-mini"
    agent_temperature: float = 0.7
    summary_model: str = "openai/gpt-4o-mini"

    # RAG
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    chroma_path: str = "./data/chroma"

    # LangGraph checkpointer
    checkpointer_path: str = "./data/agent.sqlite"

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_config.py -v`
Expected: all tests in this file PASS (including pre-existing ones).

- [ ] **Step 5: Commit**

```powershell
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat(config): load backend settings from repo-root .env"
```

---

### Task 3: Drop `OPENAI_API_KEY` from Settings

**Files:**
- Modify: `backend/app/config.py:14`
- Modify: `backend/tests/test_config.py:13`

- [ ] **Step 1: Flip the failing assertion**

In `backend/tests/test_config.py`, replace the body of `test_agent_settings_optional_keys` so it asserts the inverse — `openai_api_key` must NOT exist on Settings:

```python
def test_agent_settings_optional_keys():
    assert hasattr(settings, "openrouter_api_key")
    assert not hasattr(settings, "openai_api_key")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_config.py::test_agent_settings_optional_keys -v`
Expected: FAIL — `openai_api_key` still exists on the model.

- [ ] **Step 3: Remove the field from `backend/app/config.py`**

Delete the line:

```python
    openai_api_key: str | None = None  # retained until Task 3 removes it
```

- [ ] **Step 4: Run the full config test file**

Run: `pytest backend/tests/test_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/config.py backend/tests/test_config.py
git commit -m "refactor(config): drop OPENAI_API_KEY in favor of OPENROUTER_API_KEY"
```

---

### Task 4: Route embeddings through OpenRouter

**Files:**
- Modify: `backend/app/rag/embeddings.py`
- Modify: `backend/tests/rag/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/rag/test_embeddings.py`:

```python
@patch("app.rag.embeddings.OpenAI")
def test_embeddings_client_targets_openrouter(mock_openai):
    # Re-import the module to trigger client construction with the patched OpenAI.
    import importlib

    import app.rag.embeddings as embeddings_module

    importlib.reload(embeddings_module)

    kwargs = mock_openai.call_args.kwargs
    assert kwargs["base_url"] == "https://openrouter.ai/api/v1"
```

(Top-of-file imports `patch`, `MagicMock`, and the module — already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/rag/test_embeddings.py::test_embeddings_client_targets_openrouter -v`
Expected: FAIL — current client is built without `base_url`.

- [ ] **Step 3: Update `backend/app/rag/embeddings.py`**

Replace the file's contents with:

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

- [ ] **Step 4: Run the full embeddings test file**

Run: `pytest backend/tests/rag/test_embeddings.py -v`
Expected: all PASS (the two pre-existing tests patch `_client` directly, so they remain unaffected).

- [ ] **Step 5: Commit**

```powershell
git add backend/app/rag/embeddings.py backend/tests/rag/test_embeddings.py
git commit -m "feat(rag): route embeddings through OpenRouter base URL"
```

---

### Task 5: Wire the root `.env` into Next.js

**Files:**
- Modify: `frontend/next.config.mjs`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add `dotenv` as a devDependency**

From the `frontend/` directory:

```powershell
cd frontend
npm install --save-dev dotenv
cd ..
```

- [ ] **Step 2: Update `frontend/next.config.mjs`**

Replace the file's contents with:

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

- [ ] **Step 3: Manual verification — config loads at build time**

Create a temporary root `.env` containing only:

```env
NEXT_PUBLIC_API_URL=http://verification.local
```

Then from `frontend/`:

```powershell
npm run build
```

Expected: build succeeds. Inspect any built `.next/static/chunks/*.js` for the literal string `http://verification.local` — confirms `NEXT_PUBLIC_API_URL` was inlined from the root `.env`. (PowerShell: `Select-String -Path .next/static/chunks/*.js -Pattern "verification.local"`.)

Delete the temporary `.env` afterward (`Remove-Item .env`).

- [ ] **Step 4: Commit**

```powershell
git add frontend/next.config.mjs frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): load env vars from repo-root .env via dotenv"
```

---

### Task 6: Delete the per-app `.env.example` files

**Files:**
- Delete: `backend/.env.example`
- Delete: `frontend/.env.example`

- [ ] **Step 1: Remove both files**

```powershell
git rm backend/.env.example frontend/.env.example
```

- [ ] **Step 2: Verify deletion**

Run: `git status` — expected to show both files as `deleted`.

- [ ] **Step 3: Commit**

```powershell
git commit -m "chore(config): remove per-app .env.example files"
```

---

### Task 7: Update README setup instructions

**Files:**
- Modify: `README.md:37-56`

- [ ] **Step 1: Replace the two-step env-setup section**

In `README.md`, replace lines 37–56 (the entire "### 2. Configure environment" section, both the Backend and Frontend subsections) with:

```markdown
### 2. Configure environment

Copy the template at the repo root and fill in the values you need:

```powershell
Copy-Item .env.example .env
```

The file lives at the repo root and is consumed by both backend and frontend. All keys (with comments) are listed inside `.env.example`. For a local-scraper-only setup you only need `OPENROUTER_API_KEY`; `EVENTBRITE_TOKEN` and `TICKETMASTER_API_KEY` can be left blank and those adapters will skip themselves.
```

(Note the closing triple-backtick belongs to the code block inside the markdown — preserve exactly as shown.)

- [ ] **Step 2: Search-and-replace any other stale references**

Run: `Select-String -Path README.md -Pattern "backend/.env|frontend/.env.local"` — expected no matches after the edit. If any remain, update them to refer to the root `.env`.

- [ ] **Step 3: Commit**

```powershell
git add README.md
git commit -m "docs(readme): describe central .env setup"
```

---

### Task 8: Full verification

- [ ] **Step 1: Confirm `.gitignore` already covers root `.env`**

Run: `Select-String -Path .gitignore -Pattern "^\*?\.env$|^\*\.env$"` — expected at least one match (line `*.env` already present at line 30, which covers root-level `.env`).

If somehow no match exists, append `.env` on its own line to `.gitignore` and commit as a separate fix.

- [ ] **Step 2: Run the full backend test suite**

```powershell
cd backend
pytest
cd ..
```

Expected: all tests PASS. No collection errors related to `openai_api_key` or `OPENAI_API_KEY`.

- [ ] **Step 3: Create a real working `.env` for the smoke test**

```powershell
Copy-Item .env.example .env
```

Open `.env` and set `OPENROUTER_API_KEY` to a valid key (the user provides this).

- [ ] **Step 4: Smoke-test backend config loading**

```powershell
cd backend
python -c "from app.config import settings; print('openrouter_api_key set:', bool(settings.openrouter_api_key)); print('agent_model:', settings.agent_model)"
cd ..
```

Expected output:
```
openrouter_api_key set: True
agent_model: openai/gpt-4o-mini
```

- [ ] **Step 5: Smoke-test frontend env propagation**

```powershell
cd frontend
npm run build
cd ..
```

Expected: build succeeds and the value of `NEXT_PUBLIC_API_URL` from the root `.env` appears in `frontend/.next/static/chunks/*.js`. Verify:

```powershell
Select-String -Path frontend/.next/static/chunks/*.js -Pattern "localhost:8000" | Select-Object -First 1
```

Expected: at least one match (the default value `http://localhost:8000` from the template).

- [ ] **Step 6: Confirm `.env` is untracked**

Run: `git status` — `.env` MUST NOT appear under "Untracked files" or any other section. If it does, `.gitignore` is misconfigured.

- [ ] **Step 7: No new commit for this task**

Task 8 is verification-only. Nothing to commit. If any step fails, return to the relevant earlier task and fix forward, then re-run Task 8.

---

## Self-review notes (resolved)

- **Spec coverage:** All seven code-change subsections of the spec map to tasks above (1 → root `.env.example`; 2,3 → Task 2+3; 4 → Task 4; pre-flight audit covers spec item 3; 5,6 → Task 5; 7 → Task 8 step 1; 8 → Task 6; 9 → Task 7). All verification items from the spec are exercised in Task 8.
- **Placeholders:** None. Every code block is complete; no "TBD" / "TODO" / "similar to" references.
- **Type/name consistency:** `_REPO_ROOT` used in Task 2 matches Task 3 reuse. `openrouter_api_key` field name matches across config.py, embeddings.py, and tests. `base_url` value `https://openrouter.ai/api/v1` matches the existing pattern in `app/agent/llm.py:12`.
