# Long-Term Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-managed factual memory blob (`User.facts_md`) and convert the existing `User.taste_summary` to the same edit-pattern, removing the auto-regeneration pipeline.

**Architecture:** Two TEXT columns on `User` (`facts_md` max 200 lines, `taste_summary` max 20 lines), both always injected into the system prompt, both edited exclusively by the agent through `edit_facts(old, new)` / `edit_taste_summary(old, new)` tools. A pure helper function `apply_edit` carries all the logic and is unit-tested in isolation; the tools are thin wrappers that handle the DB session. `User.taste_centroid` and its synchronous refresh on like-feedback stay untouched.

**Tech Stack:** SQLAlchemy 2 (Mapped[] style), Alembic, FastAPI, LangChain `@tool`, LangGraph ReAct, pytest with in-memory SQLite fixtures.

**Reference spec:** `docs/specs/2026-06-15-long-term-memory-design.md`

---

## Task 1: Schema migration

**Files:**
- Modify: `backend/app/db/models/user.py`
- Create: `backend/app/db/migrations/versions/0003_user_memory_blobs.py`
- Modify: `backend/tests/db/test_user.py:40`

- [ ] **Step 1: Update the User model**

In `backend/app/db/models/user.py`, replace the `taste_summary_dirty` column with a new `facts_md` column. Final relevant portion of the model:

```python
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    city: Mapped[str] = mapped_column(String, nullable=False, default="Hamburg")
    interest_tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    about_me: Mapped[str | None] = mapped_column(String, nullable=True)
    taste_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    facts_md: Mapped[str] = mapped_column(String, nullable=False, default="")
    taste_centroid: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)
```

Concretely: delete the `taste_summary_dirty` line; add `facts_md` between `taste_summary` and `taste_centroid`.

- [ ] **Step 2: Update the existing User unit test**

In `backend/tests/db/test_user.py`, line ~40 contains:

```python
assert fresh.taste_summary_dirty is True  # default true => first read triggers initial summary
```

Replace with:

```python
assert fresh.facts_md == ""  # default empty for agent-managed memory blob
```

Run: `cd backend && pytest tests/db/test_user.py -v`
Expected: this test passes against the new model; other tests in the file may still fail because `taste_summary_dirty` is referenced elsewhere — that is fine, fixed in Task 5.

- [ ] **Step 3: Create the Alembic migration**

Create `backend/app/db/migrations/versions/0003_user_memory_blobs.py`:

```python
"""user memory blobs

Revision ID: 0003_user_memory_blobs
Revises: 0002_user_taste_fields
Create Date: 2026-06-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_user_memory_blobs"
down_revision: Union[str, Sequence[str], None] = "0002_user_taste_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("facts_md", sa.String(), nullable=False, server_default=""),
    )
    op.drop_column("users", "taste_summary_dirty")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_summary_dirty", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.drop_column("users", "facts_md")
```

- [ ] **Step 4: Apply the migration to the local DB**

Run: `cd backend && alembic upgrade head`
Expected: `INFO  [alembic.runtime.migration] Running upgrade 0002_user_taste_fields -> 0003_user_memory_blobs`. No errors.

- [ ] **Step 5: Verify schema change**

Run: `cd backend && python -c "from sqlalchemy import create_engine, inspect; e = create_engine('sqlite:///event_tracker.db'); cols = {c['name'] for c in inspect(e).get_columns('users')}; print('facts_md' in cols, 'taste_summary_dirty' not in cols)"`
Expected: `True True`

- [ ] **Step 6: Commit**

```bash
git add backend/app/db/models/user.py backend/app/db/migrations/versions/0003_user_memory_blobs.py backend/tests/db/test_user.py
git commit -m "feat(db): add facts_md column, drop taste_summary_dirty"
```

---

## Task 2: Pure `apply_edit` helper

**Files:**
- Create: `backend/app/agent/memory_blob.py`
- Create: `backend/tests/agent/test_memory_blob.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/agent/test_memory_blob.py`:

```python
import pytest

from app.agent.memory_blob import EditError, apply_edit


def test_append_into_empty():
    new = apply_edit("", "", "User lives in Eimsbüttel", cap=200, label="facts_md")
    assert new == "User lives in Eimsbüttel"


def test_append_onto_existing_adds_single_newline():
    new = apply_edit("a", "", "b", cap=200, label="facts_md")
    assert new == "a\nb"


def test_append_onto_blob_ending_in_newline_no_double():
    new = apply_edit("a\n", "", "b", cap=200, label="facts_md")
    assert new == "a\nb"


def test_replace_unique():
    new = apply_edit("x\ny\nz", "y", "Y", cap=200, label="facts_md")
    assert new == "x\nY\nz"


def test_replace_ambiguous_raises():
    with pytest.raises(EditError, match="matches 2 locations"):
        apply_edit("a\na\nb", "a", "c", cap=200, label="facts_md")


def test_replace_not_found_raises():
    with pytest.raises(EditError, match="not found"):
        apply_edit("a", "xyz", "c", cap=200, label="facts_md")


def test_remove_full_line():
    new = apply_edit("a\nb\nc", "b\n", "", cap=200, label="facts_md")
    assert new == "a\nc"


def test_both_empty_raises():
    with pytest.raises(EditError, match="no-op"):
        apply_edit("anything", "", "", cap=200, label="facts_md")


def test_cap_overflow_on_append_raises():
    blob = "\n".join(str(i) for i in range(199))  # 199 lines
    with pytest.raises(EditError, match="would exceed cap"):
        apply_edit(blob, "", "x\ny", cap=200, label="facts_md")  # would be 201


def test_cap_edge_exactly_at_limit():
    blob = "\n".join(str(i) for i in range(199))  # 199 lines
    new = apply_edit(blob, "", "x", cap=200, label="facts_md")  # exactly 200
    assert len(new.splitlines()) == 200


def test_pre_existing_over_cap_blob_first_edit_raises():
    blob = "\n".join(str(i) for i in range(250))  # already over cap
    with pytest.raises(EditError, match="would exceed cap"):
        apply_edit(blob, "", "extra", cap=200, label="facts_md")


def test_label_appears_in_error_message():
    with pytest.raises(EditError, match="taste_summary"):
        apply_edit("foo", "", "", cap=20, label="taste_summary")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_memory_blob.py -v`
Expected: all tests fail with `ModuleNotFoundError: No module named 'app.agent.memory_blob'`.

- [ ] **Step 3: Implement `apply_edit`**

Create `backend/app/agent/memory_blob.py`:

```python
"""Pure helpers for the agent-managed memory blobs (facts_md, taste_summary).

Single function `apply_edit` implements replace / append / remove with cap
enforcement. Tools in app.agent.tools wrap this with a DB session.
"""


class EditError(Exception):
    """Raised when an edit cannot be applied. Tools translate this to ToolError."""


def apply_edit(blob: str, old_string: str, new_string: str, *, cap: int, label: str) -> str:
    """Return the new blob after the edit. Never mutates input.

    Rules:
    - old="" and new!="" -> append new as a line at the end (one '\\n' separator
      if blob is non-empty and does not already end with '\\n').
    - old!="" and new!="" -> replace the unique occurrence of old with new.
    - old!="" and new=="" -> remove the unique occurrence of old.
    - old=="" and new=="" -> error (no-op).
    - If old!="" must appear exactly once (else error).
    - Resulting line count (via splitlines) must be <= cap.
    """
    if old_string == "" and new_string == "":
        raise EditError(f"{label}: no-op (both strings empty)")

    if old_string == "":
        # Append path
        if blob == "":
            candidate = new_string
        elif blob.endswith("\n"):
            candidate = blob + new_string
        else:
            candidate = blob + "\n" + new_string
    else:
        count = blob.count(old_string)
        if count == 0:
            raise EditError(f"{label}: old_string not found in current blob")
        if count > 1:
            raise EditError(f"{label}: old_string matches {count} locations; provide more context")
        candidate = blob.replace(old_string, new_string, 1)

    lines = len(candidate.splitlines())
    if lines > cap:
        raise EditError(f"{label} would exceed cap: {lines} lines vs. limit {cap}; compress first")

    return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_memory_blob.py -v`
Expected: all 12 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/memory_blob.py backend/tests/agent/test_memory_blob.py
git commit -m "feat(agent): add apply_edit helper for memory blobs"
```

---

## Task 3: `edit_facts` tool

**Files:**
- Modify: `backend/app/agent/tools.py` (imports, new tool, ALL_TOOLS list)
- Create: `backend/tests/agent/test_edit_facts_tool.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/agent/test_edit_facts_tool.py`:

```python
import pytest

from app.agent import tools
from app.agent.schemas import ToolError
from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], facts_md="")
    db_session.add(u)
    db_session.commit()
    return u


def test_edit_facts_appends_when_old_empty(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    result = tools.edit_facts.invoke({"old_string": "", "new_string": "User lives in Eimsbüttel"})

    assert result == {"status": "ok", "lines": 1}
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "User lives in Eimsbüttel"


def test_edit_facts_replaces_unique_match(db_session, user, monkeypatch):
    user.facts_md = "lives in Eimsbüttel\nlikes jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_facts.invoke({"old_string": "likes jazz", "new_string": "likes indie"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "lives in Eimsbüttel\nlikes indie"


def test_edit_facts_removes_line(db_session, user, monkeypatch):
    user.facts_md = "a\nb\nc"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_facts.invoke({"old_string": "b\n", "new_string": ""})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "a\nc"


def test_edit_facts_both_empty_raises_toolerror(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="no-op"):
        tools.edit_facts.invoke({"old_string": "", "new_string": ""})


def test_edit_facts_cap_overflow_raises_toolerror_and_does_not_persist(db_session, user, monkeypatch):
    user.facts_md = "\n".join(str(i) for i in range(199))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="would exceed cap"):
        tools.edit_facts.invoke({"old_string": "", "new_string": "x\ny"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.facts_md == "\n".join(str(i) for i in range(199))


def test_edit_facts_ambiguous_raises_toolerror(db_session, user, monkeypatch):
    user.facts_md = "a\na\nb"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    with pytest.raises(ToolError, match="matches 2 locations"):
        tools.edit_facts.invoke({"old_string": "a", "new_string": "c"})


def test_edit_facts_user_missing_raises_toolerror(db_session, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "nope")

    with pytest.raises(ToolError, match="user not found"):
        tools.edit_facts.invoke({"old_string": "", "new_string": "anything"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_edit_facts_tool.py -v`
Expected: all tests fail with `AttributeError: module 'app.agent.tools' has no attribute 'edit_facts'`.

- [ ] **Step 3: Add `edit_facts` to `tools.py`**

In `backend/app/agent/tools.py`, add to the imports near the top:

```python
from app.agent.memory_blob import EditError, apply_edit
```

Add the new tool above the `ALL_TOOLS` list (around line 273):

```python
@tool
def edit_facts(old_string: str, new_string: str) -> dict:
    """Edit the user's facts blob (durable user-stated facts).

    Semantics:
    - old_string="" and new_string!="" appends new_string as a new line.
    - both non-empty replaces the unique occurrence of old_string.
    - old_string!="" and new_string="" removes the unique occurrence.
    - Both empty is an error (no-op).
    - old_string must match exactly once when non-empty.
    - Resulting blob must be at most 200 lines; otherwise the edit is refused.

    Returns {"status": "ok", "lines": <new line count>} on success.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        try:
            new_blob = apply_edit(
                user.facts_md or "",
                old_string,
                new_string,
                cap=200,
                label="facts_md",
            )
        except EditError as e:
            raise ToolError(str(e))
        user.facts_md = new_blob
        session.commit()
        return {"status": "ok", "lines": len(new_blob.splitlines())}
    finally:
        session.close()
```

Then update the `ALL_TOOLS` list to include the new tool:

```python
ALL_TOOLS = [
    search_events,
    get_recommendations,
    record_feedback,
    save_to_calendar,
    get_calendar,
    get_user_profile,
    update_user_profile,
    edit_facts,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_edit_facts_tool.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/agent/test_edit_facts_tool.py
git commit -m "feat(agent): add edit_facts tool"
```

---

## Task 4: `edit_taste_summary` tool

**Files:**
- Modify: `backend/app/agent/tools.py` (new tool, ALL_TOOLS list)
- Create: `backend/tests/agent/test_edit_taste_summary_tool.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/agent/test_edit_taste_summary_tool.py`:

```python
import pytest

from app.agent import tools
from app.agent.schemas import ToolError
from app.db.models import User


@pytest.fixture
def user(db_session):
    u = User(id="local", interest_tags=["music"], facts_md="", taste_summary="")
    db_session.add(u)
    db_session.commit()
    return u


def test_edit_taste_summary_appends(db_session, user, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    result = tools.edit_taste_summary.invoke({"old_string": "", "new_string": "Leans indie."})

    assert result == {"status": "ok", "lines": 1}
    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.taste_summary == "Leans indie."


def test_edit_taste_summary_uses_20_line_cap(db_session, user, monkeypatch):
    user.taste_summary = "\n".join(str(i) for i in range(19))
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    # Append 2 lines onto 19 lines -> 21 > 20 -> reject
    with pytest.raises(ToolError, match="would exceed cap: 21 lines vs. limit 20"):
        tools.edit_taste_summary.invoke({"old_string": "", "new_string": "x\ny"})


def test_edit_taste_summary_replaces(db_session, user, monkeypatch):
    user.taste_summary = "loves jazz"
    db_session.commit()
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "local")

    tools.edit_taste_summary.invoke({"old_string": "jazz", "new_string": "indie"})

    fresh = db_session.query(User).filter_by(id="local").one()
    assert fresh.taste_summary == "loves indie"


def test_edit_taste_summary_user_missing_raises(db_session, monkeypatch):
    monkeypatch.setattr(tools, "_session_factory", lambda: db_session)
    monkeypatch.setattr(tools, "get_current_user_id", lambda: "nope")

    with pytest.raises(ToolError, match="user not found"):
        tools.edit_taste_summary.invoke({"old_string": "", "new_string": "x"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/agent/test_edit_taste_summary_tool.py -v`
Expected: tests fail with `AttributeError: module 'app.agent.tools' has no attribute 'edit_taste_summary'`.

- [ ] **Step 3: Add `edit_taste_summary` to `tools.py`**

In `backend/app/agent/tools.py`, add immediately after `edit_facts`:

```python
@tool
def edit_taste_summary(old_string: str, new_string: str) -> dict:
    """Edit your behavioural summary (your inferred picture of the user from
    saves/feedback).

    Same semantics as edit_facts. Cap is 20 lines. Returns
    {"status": "ok", "lines": <new line count>} on success.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        try:
            new_blob = apply_edit(
                user.taste_summary or "",
                old_string,
                new_string,
                cap=20,
                label="taste_summary",
            )
        except EditError as e:
            raise ToolError(str(e))
        user.taste_summary = new_blob
        session.commit()
        return {"status": "ok", "lines": len(new_blob.splitlines())}
    finally:
        session.close()
```

Update `ALL_TOOLS`:

```python
ALL_TOOLS = [
    search_events,
    get_recommendations,
    record_feedback,
    save_to_calendar,
    get_calendar,
    get_user_profile,
    update_user_profile,
    edit_facts,
    edit_taste_summary,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/agent/test_edit_taste_summary_tool.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agent/tools.py backend/tests/agent/test_edit_taste_summary_tool.py
git commit -m "feat(agent): add edit_taste_summary tool"
```

---

## Task 5: Replace prompts with memory block

**Files:**
- Modify: `backend/app/agent/prompts.py`

- [ ] **Step 1: Rewrite `prompts.py`**

Replace the entire content of `backend/app/agent/prompts.py` with:

```python
"""Agent prompt templates."""

_MEMORY_BLOCK_EDITABLE = """\
USER MEMORY

  Facts (stated by user, you maintain - max 200 lines):
  {facts_md}

  Behavioural summary (you maintain - max 20 lines, your inferred picture from saves/feedback):
  {taste_summary}

You may edit either block via edit_facts / edit_taste_summary. When the
user states something durable about themselves or their world (diet,
constraints, neighbourhood, companions, taste claims), add it to Facts.
When you notice from the conversation that your behavioural summary is
wrong or outdated, edit it. Do not duplicate between the two blocks. Do
not store ephemeral or sensitive details the user did not intend to be
remembered."""

_MEMORY_BLOCK_READONLY = """\
USER MEMORY (read-only in this context)

  Facts (stated by user - max 200 lines):
  {facts_md}

  Behavioural summary (max 20 lines, inferred picture from saves/feedback):
  {taste_summary}"""


CURATION_PROMPT = """\
You are a Hamburg event concierge picking today's digest for a user.

USER PROFILE
  Interests: {interests}
  About-me: {about_me}

""" + _MEMORY_BLOCK_READONLY + """

TODAY'S CANDIDATE POOL (next 7 days, JSON):
{event_pool}

Your job: pick 3 to 5 events from the pool that this specific user is most
likely to love today. For each pick, write a 1-2 sentence justification
grounded in the user's interests, taste summary, or stated about-me - not
generic praise of the event.

If helpful, you MAY call get_recommendations to surface events ranked by
taste-vector similarity. You do not need to use every tool.

Return your final answer in the structured output format.
"""

CONVERSATIONAL_PROMPT = """\
You are a Hamburg event concierge for one specific user. Today is {today}.

USER PROFILE
  Interests: {interests}
  About-me: {about_me}

""" + _MEMORY_BLOCK_EDITABLE + """

You have tools for searching events, getting personalised recommendations,
recording feedback, saving to the calendar, reading/updating the user's
profile, and editing your memory blocks above. Use them when they will
help.

Be concise. When you refer to a specific event by name, also mention its
ID in the form [event:ID] so the UI can render the card inline.
Do not invent events that are not in the database. If a tool returns no
results, say so honestly.
"""
```

Notes for the engineer:
- `SUMMARY_PROMPT` is deleted entirely.
- The two memory-block constants are private (leading underscore) and only used by the templates here.
- `CURATION_PROMPT` keeps the `{event_pool}` placeholder; `CONVERSATIONAL_PROMPT` keeps `{today}`.
- Both prompts retain `{interests}`, `{about_me}` and now also expect `{facts_md}` and `{taste_summary}` in `.format()`.

- [ ] **Step 2: Quick smoke check**

Run: `cd backend && python -c "from app.agent.prompts import CONVERSATIONAL_PROMPT, CURATION_PROMPT; print(CONVERSATIONAL_PROMPT.format(today='2026-06-15', interests='a', about_me='b', facts_md='c', taste_summary='d')[:200])"`
Expected: prints the first 200 chars of the rendered prompt with all placeholders substituted, no `KeyError`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/agent/prompts.py
git commit -m "feat(prompts): replace taste line with memory block; drop SUMMARY_PROMPT"
```

(Note: at this point the test suite is broken because callers still pass the old kwargs and reference deleted symbols. Task 6 fixes that. Do not run the full suite until Task 6 is done.)

---

## Task 6: Remove auto-regen pipeline and rewire callers

This is one logical refactor split into atomic file edits. All changes must land together for the test suite to be runnable again.

**Files:**
- Modify: `backend/app/agent/memory.py`
- Modify: `backend/app/api/routes_chat.py`
- Modify: `backend/app/api/routes_digest.py`
- Modify: `backend/app/api/routes_feedback.py:36-39`
- Modify: `backend/app/api/routes_profile.py:35-44, 47-59`
- Modify: `backend/app/agent/tools.py` (drop dirty-flag setters and refresh call inside the 3 affected tools)
- Modify: `backend/tests/agent/test_memory.py`
- Modify: `backend/tests/agent/test_tools.py`
- Modify: `backend/tests/api/test_routes_profile.py`
- Modify: `backend/tests/api/test_routes_feedback.py`
- Modify: `backend/tests/api/test_routes_chat.py`
- Modify: `backend/tests/api/test_routes_digest.py`
- Modify: `backend/tests/integration/test_chat_sse.py`
- Modify: `backend/tests/integration/test_digest_cycle.py`

- [ ] **Step 1: Delete `refresh_taste_summary` from `memory.py`**

In `backend/app/agent/memory.py`:
- Remove the function `refresh_taste_summary` (lines 67-109 of the current file).
- Remove the helper `_invoke_summary_llm` (lines 62-64) — it had no other caller.
- Remove the import `from app.agent.prompts import SUMMARY_PROMPT` (line 17).
- Remove the import `from app.agent.llm import build_llm` (line 16) **only if** `_invoke_summary_llm` was its sole user; verify by grepping. If `build_llm` is used elsewhere in the file, leave it.
- Update the module docstring to drop the `refresh_taste_summary` line.

The file should still expose: `get_current_user_id`, `set_current_user_id`, `record_message`, `refresh_taste_centroid`, `_current_user_id` (private).

- [ ] **Step 2: Update `routes_chat.py`**

In `backend/app/api/routes_chat.py`:
- Change line 16 from `from app.agent.memory import get_current_user_id, record_message, refresh_taste_summary` to `from app.agent.memory import get_current_user_id, record_message`.
- Delete lines 44-46 (`refresh_taste_summary(db, user_id); db.commit(); db.refresh(user)`).
- Update the `CONVERSATIONAL_PROMPT.format(...)` call (lines 51-56) to:

```python
    system = CONVERSATIONAL_PROMPT.format(
        today=date.today().isoformat(),
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        facts_md=user.facts_md or "(empty)",
        taste_summary=user.taste_summary or "(empty)",
    )
```

- [ ] **Step 3: Update `routes_digest.py`**

In `backend/app/api/routes_digest.py`:
- Change the import line 9 from `from app.agent.memory import get_current_user_id, refresh_taste_summary` to `from app.agent.memory import get_current_user_id`.
- Delete lines 87-89 (`refresh_taste_summary(db, user.id); db.commit(); db.refresh(user)`).
- Update the `CURATION_PROMPT.format(...)` call (lines 95-100) to:

```python
    prompt = CURATION_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        facts_md=user.facts_md or "(empty)",
        taste_summary=user.taste_summary or "(empty)",
        event_pool=json.dumps([_serialise_event_for_prompt(e) for e in pool], indent=2),
    )
```

- [ ] **Step 4: Update `routes_feedback.py`**

In `backend/app/api/routes_feedback.py` around line 36-39, delete the three lines that read:

```python
    user = db.query(User).filter_by(id=user_id).one_or_none()
    if user is not None:
        user.taste_summary_dirty = True
```

Keep everything else: the Feedback row insert, the conditional `refresh_taste_centroid` on `like`, the response. The `User` import in this file may become unused — if `User` is not referenced anywhere else in the file, remove it from the import line.

- [ ] **Step 5: Update `routes_profile.py`**

In `backend/app/api/routes_profile.py`:
- Line 41: delete `u.taste_summary_dirty = True`
- Line 56: delete `u.taste_summary_dirty = True`

Everything else in those handlers stays.

- [ ] **Step 6: Update `tools.py`**

In `backend/app/agent/tools.py`:

In the `get_user_profile` tool (around line 135 and 142): delete the local import line `from app.agent.memory import refresh_taste_summary` (line 135) **and** delete the two body lines:

```python
        refresh_taste_summary(session, user_id)
        session.commit()
```

In the `update_user_profile` tool (around line 171): delete the line `user.taste_summary_dirty = True`. Update the docstring to drop the sentence "Marks the taste summary dirty so it regenerates on next read." — replace with "Any field omitted is left unchanged." only (keep the existing leading sentence).

In the `record_feedback` tool (around line 264): delete the three lines:

```python
        user = session.query(User).filter_by(id=user_id).one()
        user.taste_summary_dirty = True
```

(The line `user = ...` above the dirty flag is fetched solely for the dirty assignment.) After removing, the centroid refresh that follows for `like` no longer depends on `user`; verify the file still imports `User` for other uses (it should: search_events / get_recommendations / get_user_profile all use it).

Also remove `refresh_taste_summary` from the import line near the top of `tools.py` if present (it imports from `app.agent.memory`).

- [ ] **Step 7: Update `tests/agent/test_memory.py`**

Delete tests `test_refresh_taste_summary_skips_when_clean` (lines 47-54) and `test_refresh_taste_summary_regenerates_when_dirty` (lines 57-65). Also delete the now-unused import line `from unittest.mock import patch` if no remaining test uses it (the centroid test below uses `patch`, so leave the import).

- [ ] **Step 8: Update `tests/agent/test_tools.py`**

- In `test_get_user_profile_returns_profile` (line 95): delete `user.taste_summary_dirty = False` (line 96).
- In `test_update_user_profile_marks_dirty` (line 109):
  - Rename to `test_update_user_profile_updates_fields`.
  - Delete `user.taste_summary_dirty = False` (line 110).
  - Delete the final assertion `assert fresh.taste_summary_dirty is True` (line 120).
- In `test_record_feedback_inserts_and_marks_dirty` (line 166):
  - Rename to `test_record_feedback_inserts_row`.
  - Delete the last two assertion lines (the user query and `assert user.taste_summary_dirty is True`).

- [ ] **Step 9: Update `tests/api/test_routes_profile.py`**

- Line 9: change `taste_summary_dirty=False` in the User fixture setup to remove that kwarg (the column does not exist anymore).
- Line 30: delete the assertion `assert fresh.taste_summary_dirty is True` — replace with a positive assertion that the field actually got updated, e.g. `assert fresh.about_me == payload.about_me`. If the test already asserts the updated value, just delete the dirty assertion.

- [ ] **Step 10: Update `tests/api/test_routes_feedback.py`**

Line 28: delete `assert user.taste_summary_dirty is True`. If this was the last assertion in that test, replace it with `assert user is not None` (just to keep the lookup meaningful), or assert that a Feedback row was created — whichever the surrounding code naturally supports without further setup.

- [ ] **Step 11: Update `tests/api/test_routes_chat.py`**

- Line 14: in the User fixture, change `taste_summary="loves jazz", taste_summary_dirty=False` to `taste_summary="loves indie", facts_md="lives in Eimsbüttel"`.

Then add this test at the bottom of the file, matching the project's existing `@patch("app.api.routes_chat.get_agent")` pattern (verbatim — copy/paste; do not adapt):

```python
@patch("app.api.routes_chat.get_agent")
def test_chat_prompt_includes_memory_blocks(mock_get_agent, client, user):
    fake_agent = MagicMock()
    captured = {}

    async def fake_astream(payload, *args, **kwargs):
        captured["system"] = payload["messages"][0].content
        yield ("messages", (AIMessage(content="ok"), {"langgraph_node": "agent"}))

    fake_agent.astream = fake_astream
    mock_get_agent.return_value = fake_agent

    with client.stream("POST", "/chat", json={"session_id": "s1", "message": "hi"}) as r:
        b"".join(r.iter_bytes())

    assert "USER MEMORY" in captured["system"]
    assert "lives in Eimsbüttel" in captured["system"]
    assert "loves indie" in captured["system"]
```

This relies on the existing `user` fixture (the one with `facts_md="lives in Eimsbüttel"` after the kwarg swap above) and on `MagicMock`, `AIMessage`, `patch` already imported at the top of the file.

- [ ] **Step 12: Update `tests/api/test_routes_digest.py`**

Line 13: change `taste_summary="loves jazz", taste_summary_dirty=False` to `taste_summary="loves jazz", facts_md=""`.

- [ ] **Step 13: Update integration test fixtures**

- `tests/integration/test_chat_sse.py:13`: change `taste_summary="loves jazz", taste_summary_dirty=False` to `taste_summary="loves jazz", facts_md=""`.
- `tests/integration/test_digest_cycle.py:13`: same change.

- [ ] **Step 14: Run the entire backend test suite**

Run: `cd backend && pytest -v`
Expected: all tests pass. If any test still references `taste_summary_dirty` or `refresh_taste_summary`, fix the offending lines following the same patterns above.

- [ ] **Step 15: Commit**

```bash
git add backend/app/agent/memory.py backend/app/agent/tools.py backend/app/api/routes_chat.py backend/app/api/routes_digest.py backend/app/api/routes_feedback.py backend/app/api/routes_profile.py backend/tests/agent/test_memory.py backend/tests/agent/test_tools.py backend/tests/api/test_routes_profile.py backend/tests/api/test_routes_feedback.py backend/tests/api/test_routes_chat.py backend/tests/api/test_routes_digest.py backend/tests/integration/test_chat_sse.py backend/tests/integration/test_digest_cycle.py
git commit -m "refactor(agent): remove taste_summary auto-regen, wire facts_md into prompts"
```

---

## Task 7: Final verification

**Files:** none modified.

- [ ] **Step 1: Full test suite**

Run: `cd backend && pytest -v`
Expected: all tests pass; no `taste_summary_dirty` or `refresh_taste_summary` reference remains.

- [ ] **Step 2: Quick grep sweep**

Run: `cd backend && grep -rn "taste_summary_dirty\|refresh_taste_summary\|SUMMARY_PROMPT" app tests`
Expected: no matches (the strings only appear in the dropped migration column drop in 0002, which is fine — that file is historical).

- [ ] **Step 3: Run the application manually for a smoke check**

Run: `cd backend && uvicorn app.main:app --reload` and in another shell:

```bash
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"session_id": "smoke", "message": "remember that I live in Eimsbüttel and have tinnitus"}'
```

Expected: the SSE stream yields tokens, the agent calls `edit_facts` at least once with content matching "Eimsbüttel" and "tinnitus", and a follow-up query returns the same facts. If the agent does not call the tool, refine `CONVERSATIONAL_PROMPT` instructions.

This step is manual and not strictly required for the plan to be "done", but is the closest thing to an end-to-end check before merging.

- [ ] **Step 4: Push (optional)**

Per project CLAUDE.md, Option 4 (push without PR) is `git push -u origin <branch>` only. No `gh pr create`. Confirm with the user before pushing.
