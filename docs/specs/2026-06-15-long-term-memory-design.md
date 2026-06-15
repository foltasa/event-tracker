# Long-Term Memory — Design

Status: draft
Date: 2026-06-15
Scope: backend (`app/agent`, `app/api`, `app/db`)

## 1. Motivation

The agent today has three forms of persistence:

- `User.interest_tags` and `User.about_me`: structured profile fields, user-typed via the Profile UI.
- `User.taste_summary`: an LLM-generated 80-word paragraph regenerated lazily from the last 30 feedbacks and 10 saves whenever `taste_summary_dirty` is set.
- `User.taste_centroid`: the mean embedding of liked events, used to bias RAG ranking in `get_recommendations`.

Plus `chat_messages` as a write-only audit mirror and the LangGraph SQLite checkpointer for in-session ReAct state. None of these let the agent persist user-stated facts across sessions (e.g. "I'm vegan", "my friend Tom likes techno"), and the auto-regenerated `taste_summary` cannot be corrected by the agent when it drifts.

This spec adds an agent-managed factual memory and converts the existing behavioural summary into the same edit-pattern so both blobs share one mechanism. Episodic memory (recall of past conversations) is explicitly out of scope.

## 2. Scope and Data Model

In scope:

- New text blob `User.facts_md` (Markdown-style freetext, max 200 lines).
- `User.taste_summary` becomes a second agent-editable blob (max 20 lines).
- The auto-regeneration pipeline (`refresh_taste_summary`, `SUMMARY_PROMPT`, `taste_summary_dirty` flag) is removed entirely.
- Two new LangChain tools: `edit_facts` and `edit_taste_summary`.

Out of scope (left untouched):

- `User.taste_centroid` and its synchronous refresh on every like (`tools.py:267`) — keeps influencing RAG ranking exactly as today.
- `User.interest_tags` and `User.about_me` — remain structured, UI-editable profile fields, not memory.
- `chat_messages` table, LangGraph SQLite checkpointer.
- Episodic memory (recall of dated past conversations).

Schema changes on `users`:

| Column                  | Before                       | After                                       |
|-------------------------|------------------------------|---------------------------------------------|
| `taste_summary`         | String (LLM-generated)       | String (agent-managed, max 20 lines)        |
| `taste_summary_dirty`   | Boolean                      | dropped                                     |
| `facts_md`              | —                            | new: String NOT NULL, default `""`, max 200 lines |
| `taste_centroid`        | JSON vector                  | unchanged                                   |
| `interest_tags`, `about_me` | as today                 | unchanged                                   |

Caps are enforced **at edit time only**, never at read time. A pre-existing value exceeding its cap is rendered into the prompt as-is; the next edit attempt forces the agent to shrink it first.

## 3. Agent Tools

Two tools registered in `app/agent/tools.py` and added to `select_tools()`.

### `edit_facts(old_string: str, new_string: str) -> dict`

Semantics:

| `old_string` | `new_string` | Effect                                                                                       |
|--------------|--------------|----------------------------------------------------------------------------------------------|
| non-empty    | non-empty    | Replace the unique occurrence of `old_string` with `new_string`. Error if not unique or not found. |
| `""`         | non-empty    | Append `new_string` as a new line at the end.                                                |
| non-empty    | `""`         | Remove the unique occurrence of `old_string`.                                                |
| `""`         | `""`         | Error: no-op.                                                                                |

Validation errors (returned as `ToolError`, blob left unchanged):

- `"no-op: both strings empty"`
- `"old_string matches N locations; provide more context"`
- `"old_string not found in current blob"`
- `"facts_md would exceed cap: N lines vs. limit 200; compress first"`
- `"user not found"` (defensive; matches existing pattern in `tools.py:166`)
- `"storage unavailable"` if the SQLAlchemy session cannot be opened

On success: `{"status": "ok", "lines": <new_line_count>}`.

Whitespace rules:

- Append inserts exactly one `\n` between existing content and the new content when the existing content is non-empty and does not already end with `\n`.
- Line count is `len(blob.splitlines())` — a trailing newline does not count.
- Removal of a substring that does not span a full line may leave a blank line; the agent is responsible for picking a clean `old_string`.

### `edit_taste_summary(old_string: str, new_string: str) -> dict`

Identical semantics, cap 20 lines, error texts adjusted accordingly.

### Code removed alongside

- `refresh_taste_summary` (`app/agent/memory.py:67-109`).
- `SUMMARY_PROMPT` (`app/agent/prompts.py:3-18`).
- All `taste_summary_dirty = True` setters: `app/agent/tools.py:171`, `app/agent/tools.py:264`, `app/api/routes_feedback.py:38`, `app/api/routes_profile.py:41`, `app/api/routes_profile.py:56`.
- The `refresh_taste_summary` calls in `app/api/routes_chat.py:44` and `app/api/routes_digest.py:87`.

Deliberately not added:

- No `read_facts()` / `read_taste_summary()` tools — both blobs are always in the system prompt, so the agent does not need a read tool.
- No `read_recent_behavior()` tool — YAGNI until prompt-only behaviour proves insufficient.

## 4. Prompt Integration

Both prompts in `app/agent/prompts.py` that today contain `Distilled taste: {taste_summary}` get the same memory block at that position.

Shared memory block (used in `CONVERSATIONAL_PROMPT` and `CURATION_PROMPT`):

```
USER MEMORY

  Facts (stated by user, you maintain — max 200 lines):
  {facts_md or "(empty)"}

  Behavioural summary (you maintain — max 20 lines, your inferred picture from saves/feedback):
  {taste_summary or "(empty)"}
```

`CONVERSATIONAL_PROMPT` additionally gains an instruction directly after the block:

```
You may edit either block via edit_facts / edit_taste_summary. When the
user states something durable about themselves or their world (diet,
constraints, neighbourhood, companions, taste claims), add it to Facts.
When you notice from the conversation that your behavioural summary is
wrong or outdated, edit it. Do not duplicate between the two blocks. Do
not store ephemeral or sensitive details the user did not intend to be
remembered.
```

`CURATION_PROMPT` (digest, cron context) uses the same memory block, but marks it as read-only:

```
USER MEMORY (read-only in this context)
```

The digest endpoint registers `select_tools()` without `edit_facts` / `edit_taste_summary`, so the read-only marker matches the actual tool availability.

If both blobs are empty, the memory block still renders with `(empty)` placeholders so the agent sees the feature exists.

## 5. Data Flow

### Read path (every chat turn)

```
Client -> POST /chat
  routes_chat.py:
    user = load User
    prompt = CONVERSATIONAL_PROMPT.format(
        today=..., interests=user.interest_tags, about_me=user.about_me,
        facts_md=user.facts_md or "(empty)",
        taste_summary=user.taste_summary or "(empty)",
    )
    agent.invoke(prompt, thread_id=session_id)
  LangGraph ReAct loop: model may call edit_facts / edit_taste_summary
```

No `refresh_taste_summary` call.

### Write path (agent-driven, inside a turn)

```
Model calls edit_facts(old, new):
  with _session_factory() as session:
      user = load User
      blob = user.facts_md or ""
      new_blob = apply_edit(blob, old, new)   # replace / append / remove
      if line_count(new_blob) > 200: raise ToolError(...)
      if old != "" and blob.count(old) != 1: raise ToolError(...)
      user.facts_md = new_blob
      session.commit()
      return {"status": "ok", "lines": line_count(new_blob)}
```

`edit_taste_summary` is identical, writes `user.taste_summary`, cap 20.

### Write path (UI / feedback / profile)

- `POST /feedback`: writes Feedback row, calls `refresh_taste_centroid` on `like` (unchanged). Does **not** touch `taste_summary` or `facts_md`.
- `PUT /profile`: updates `interest_tags` / `about_me`. Does **not** touch `taste_summary` or `facts_md`.
- `saved_events` endpoint: unchanged.

`facts_md` and `taste_summary` are written exclusively by the two new tools.

### Digest path

```
GET /digest:
  user = load User
  prompt = CURATION_PROMPT.format(
      ..., facts_md=user.facts_md or "(empty)",
      taste_summary=user.taste_summary or "(empty)",
  )
  digest_agent.invoke(prompt)   # tools registered without edit_*
```

No `refresh_taste_summary` call.

### Concurrency

Within one chat turn the two tools share one SQLAlchemy session; no race. Across parallel sessions (e.g. two devices), the resolution is last-write-wins at row level. Acceptable for the single-user app; revisit only if multi-device write conflicts become observable.

## 6. Migration and Rollout

A new Alembic revision under `app/db/migrations/versions/`:

```python
def upgrade():
    op.add_column(
        "users",
        sa.Column("facts_md", sa.String(), nullable=False, server_default=""),
    )
    op.drop_column("users", "taste_summary_dirty")

def downgrade():
    op.add_column(
        "users",
        sa.Column("taste_summary_dirty", sa.Boolean(),
                  nullable=False, server_default=sa.true()),
    )
    op.drop_column("users", "facts_md")
```

Data preservation:

- Existing `taste_summary` content is kept as the seed value for the now agent-managed blob. If a pre-existing row exceeds 20 lines (unlikely under the old 80-word cap), it remains; the next `edit_taste_summary` call will refuse until the agent compresses.
- `facts_md` defaults to empty for existing users. The agent fills it on the first relevant chat turn.
- `taste_centroid` untouched.

Code change order (each intermediate state is runnable):

1. Run the Alembic migration.
2. Add `edit_facts` and `edit_taste_summary` in `app/agent/tools.py`; register in `select_tools()`.
3. Update `CONVERSATIONAL_PROMPT` and `CURATION_PROMPT` with the memory block; remove `SUMMARY_PROMPT`.
4. Update callers: `routes_chat.py` and `routes_digest.py` add `facts_md` to `prompt.format(...)`, drop the `refresh_taste_summary` call.
5. Delete pipeline code: `refresh_taste_summary` from `memory.py`; the five dirty-flag setters listed in Section 3.
6. Update tests (Section 7).

No feature flag — single-user local app. Roll forward; if broken, downgrade migration plus a git revert.

## 7. Error Handling and Edge Cases

Tool errors are surfaced to the model via `ToolError`. All errors leave the blob unchanged so the agent can retry with corrected arguments.

Cap overflow on legacy data: caps apply only at edit time. A pre-existing `taste_summary` larger than 20 lines is rendered into the prompt unchanged; the next edit attempt errors with the current line count so the agent compresses first.

Whitespace:

- Append: insert exactly one `\n` between blob and new content if blob is non-empty and does not end with `\n`.
- Line count: `len(blob.splitlines())`.
- Remove: substring removal; cleanly removing a full line requires the agent to include its trailing `\n` in `old_string`.

Agent behaviour that the spec deliberately does **not** technically prevent:

- Storing sensitive data: addressed via the prompt-level instruction. No regex denylist in V1. Revisit if it becomes a problem.
- Duplicating content across the two blocks: prompt instructs against it. No hard validation; the agent sees both blobs every turn and can reconcile.
- Refusing to write when the user asks: a prompt-engineering issue, not a data-model issue.

Not in V1:

- No audit/versioning table for memory edits. The `chat_messages` mirror already records tool calls, which suffices for traceability.
- No rollback tool. The user can ask conversationally for corrections.
- No idempotency guarantee across LangGraph tool retries. A duplicate append duplicates content; a duplicate replace or remove returns "not found" on the second call, which the agent will ignore.

## 8. Testing

New unit-test file `tests/agent/test_memory_tools.py`, parallel suites for both tools:

- Append into empty blob → blob equals the line, `lines == 1`.
- Append onto existing blob → `"a"` + `("", "b")` → `"a\nb"`.
- Replace unique → `"x\ny\nz"` + `("y", "Y")` → `"x\nY\nz"`.
- Replace ambiguous → `"a\na\nb"` + `("a", "c")` → `ToolError("matches N locations")`; blob unchanged.
- Replace not found → `"a"` + `("xyz", "c")` → `ToolError("not found")`; blob unchanged.
- Remove → `"a\nb\nc"` + `("b\n", "")` → `"a\nc"`.
- Both empty → `("", "")` → `ToolError("no-op")`.
- Cap overflow on append → 199-line blob + two-line append → `ToolError("would exceed cap")`; blob unchanged.
- Cap edge → 199-line blob + one-line append → ok, `lines == 200`.
- Pre-existing over-cap blob: read does not raise; first edit attempt does.
- Whitespace normalisation: append inserts exactly one `\n`.

Integration tests:

- `tests/api/test_routes_chat.py`: drop `taste_summary_dirty` fixture setup; assert `facts_md` and `taste_summary` appear verbatim in the rendered prompt; assert empty blobs render as `(empty)`.
- `tests/api/test_routes_digest.py`: same prompt-rendering assertions; verify `edit_*` tools are not registered for digest runtime.
- `tests/integration/test_chat_sse.py`: drop `taste_summary_dirty=False` setup; add `facts_md=""` fixture value.

Tests removed or trimmed:

- `tests/agent/test_memory.py`: delete `refresh_taste_summary` tests; keep `refresh_taste_centroid` tests if present.
- `tests/api/test_routes_profile.py` and `tests/api/test_routes_feedback.py`: drop `taste_summary_dirty is True` assertions.
- `tests/db/test_user.py:40`: drop the `taste_summary_dirty` default assertion; add a `facts_md` default-`""` assertion.

Migration test (only if the test suite already runs Alembic migrations): verify `facts_md` exists with empty default and `taste_summary_dirty` is gone. Otherwise relying on the SQLAlchemy model definitions is sufficient.

Not tested:

- End-to-end with a live LLM. Whether the model uses the tools sensibly is prompt-engineering work, not unit-test scope.
- Concurrent multi-session writes (last-write-wins is the documented behaviour).
- Property/fuzz tests for the edit operations — the case list above covers them.
