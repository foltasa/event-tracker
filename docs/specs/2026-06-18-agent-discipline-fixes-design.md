# Agent Discipline Fixes Design

**Date:** 2026-06-18
**Branch:** feat/agent-discipline-fixes
**Status:** Draft

---

## Overview

After the web-event-search feature shipped, the agent's reply to a real user request ("punk concerts this Friday") was a verbatim markdown dump of a scraped venue program page, with events ranging from 2026-07-11 through September — none on the requested date, none filtered for "punk". The user shut down the backend mid-stream.

This spec defines a tightly-scoped set of fixes — partly structural, partly prompt-level — that make this class of failure improbable for a competent model and impossible past certain hard limits, without removing the agent's ability to refine its own searches.

The model swap (`AGENT_MODEL=deepseek/deepseek-v4-pro`) was applied to `.env` before this spec was written and is treated here as an environmental change, not a code change.

---

## Motivation

Six failure modes contributed to the bad reply (see chat thread `dashboard`, attempt at 2026-06-18 12:21):

1. The model pasted raw web/tool content into the final answer instead of synthesising one.
2. The model was too weak (`deepseek-v4-flash`) for the multi-step ReAct flow. *(Resolved by env swap.)*
3. The Friday date filter never made it into a successful `search_events` call.
4. The chat route streams intermediate AI narration as if it were the final reply. *(Out of scope; tracked separately.)*
5. The `text="punk"` category filter was never applied.
6. `map_to_normalized_event`'s origin filter uses exact-host match, which silently drops events on `www.` vs apex-host mismatches.

This spec addresses 1, 3, 5, 6 — plus two new guards (per-turn tool budgets, ingest-zero handling) that prevent credit-drain loops when the new web tools misbehave.

---

## Out of Scope

- **Failure #4** (chat route streaming intermediate AI narration). Real bug, tracked separately. Touching `routes_chat._stream_chat` here would balloon the change set.
- **Evaluation harness.** Discussed and deferred — too early in the product lifecycle.
- **Curated domain allowlist for ingest.** Explicitly rejected during brainstorming: the existing `WEB_SEARCH_ALLOWED_DOMAINS` setting stays in config as an ops-level kill-switch (default empty = allow-all), but is not populated.
- **Background scheduler / cross-request races on freshly-ingested rows.** The single-turn flow is race-free (see Section 6); cross-turn behaviour is unchanged.

---

## Section 1 — Per-Turn Tool Budgets (A1)

**Problem.** The current `_WEB_SEARCH_STRATEGY` prompt block tells the agent "max 4 web_search calls, max 6 ingest_event_from_url calls per turn." This is advisory; a misbehaving model can burn Tavily credits and DB cycles by ignoring it.

**Design.** Enforce the limits in the tools themselves, the same way `get_current_user_id` is enforced via contextvar.

- New module `app/agent/turn_budget.py` exposes:
  - `set_turn_budget(web_search: int, ingest: int) -> None` — sets a fresh budget for the current request (resets the contextvar).
  - `consume_web_search() -> None` — decrements; raises `ToolError("web_search budget exhausted for this turn")` on zero.
  - `consume_ingest() -> None` — symmetric for ingest.
- `routes_chat._stream_chat` calls `set_turn_budget(web_search=4, ingest=6)` before invoking the agent for each turn.
- `tools.web_search` calls `consume_web_search()` as its first line.
- `tools.ingest_event_from_url` calls `consume_ingest()` as its first line.

The agent sees the budget-exhausted `ToolError` as a `ToolMessage` (the existing `_handle_tool_errors` wrapper, runtime.py:15-25, routes that path). It is then free to answer or stop.

Defaults are fixed constants; they are not user-tunable. The values match the current prompt advisory so behaviour is unchanged for well-behaved models.

**Test surface:**
- `consume_web_search` raises after the 4th call within one budget; resets independently per turn.
- `web_search` integration test: call the tool 5× in one turn, assert the 5th raises `ToolError`.

---

## Section 2 — Snippet Shaping (A revised)

**Problem.** `web_search` currently returns hits with `content` up to 300 chars of whatever Tavily provided — typically HTML/markdown rich text with embedded image links. This is the surface the model copy-pasted from in the bad reply.

**Design.** Keep snippets visible to the agent (it needs them to judge URL relevance), but reduce both their *length* and their *formatting* so a verbatim paste is no longer a credible answer.

- In `tools.web_search`:
  - Lower `_SNIPPET_MAX` from 300 to **160** characters.
  - Pipe content through a new helper `_plain_text_snippet(s)` that strips:
    - markdown image refs `![alt](url)` and link refs `[text](url)` (keep `text`, drop the URL),
    - HTML tags via a single conservative regex (`<[^>]+>`),
    - collapses runs of whitespace (including newlines) to single spaces,
    - then truncates to the cap.
  - Truncate *after* stripping, so the cap reflects readable characters.

This is a pure-Python transformation, no new dependency. Test fixtures use real Tavily-shaped payloads (HTML soup, markdown image cards) and assert the output is plain prose <= 160 chars.

---

## Section 3 — Default Date Window in `search_events` (B)

**Problem.** When the agent forgets to pass `date_from` / `date_to`, `search_events` returns the next 20 events ordered by `start_datetime` — potentially events months out. This made the "Friday" filter trivially droppable: the tool happily returns far-future events with no signal that the user asked for "this Friday".

**Design.** When *both* `date_from` and `date_to` are omitted, apply a server-side default of `today..today+3d` (inclusive, in `Europe/Berlin`).

- If the caller passes only one bound, leave the other unbounded — the agent can deliberately ask for an open-ended search if it wants.
- If the caller passes both, no change.
- The default is computed inside the tool body so a long-lived agent process still picks up "today" correctly per call.

Docstring updated to describe the default. The 3-day window is chosen as a sensible "this week-ish" frame for the digest's daily-use pattern; longer windows reintroduce the problem.

**Test surface:**
- `search_events()` with no date args returns only events with `start_datetime` between today 00:00 and today+3d 23:59:59 (`Europe/Berlin`).
- `search_events(date_from='2026-07-01')` leaves `date_to` open as before.
- `search_events(date_from='2026-06-19', date_to='2026-06-19')` continues to honour both bounds.

---

## Section 4 — Prompt Discipline (C)

**Problem.** `CONVERSATIONAL_PROMPT` says "Be concise" and "Do not invent events that are not in the database", but offers no rule binding the *final answer* to the *events returned by tools this turn*. A model under time pressure paraphrases context.

**Design.** Add an explicit post-search answer rule to `CONVERSATIONAL_PROMPT` (prompts.py:54-72) and refine `_WEB_SEARCH_STRATEGY` (prompts.py:74-98) with a "don't retry empty ingest" line. Approximate wording (final wording landed in the implementation plan):

> **Answering rule.** Your final reply to the user must only mention events that were returned by `search_events` or `get_recommendations` *in this turn*. For each event you mention, include `[event:ID]` immediately after the title so the UI can render the card inline. If no events were returned for the user's filters, say so plainly in one sentence — do not paste search snippets, do not list venues, do not improvise events.

And appended to `_WEB_SEARCH_STRATEGY`:

> If `ingest_event_from_url` returns `ingested=0`, do not retry it on the same URL. Pick a different URL or stop.

The aggregator-first numbered steps are kept; only the post-flow answering and retry guards are added.

**No test for prompt text per se.** Behavioural assertion lives in Section 7's integration test.

---

## Section 5 — Origin Filter Softening (D)

**Problem.** `schemas._origin_match` (web_research/schemas.py:62-63) compares hostnames exactly:

```python
def _origin_match(a: str, b: str) -> bool:
    return urlparse(a).hostname == urlparse(b).hostname
```

`www.hafenklang.com` and `hafenklang.com` are different strings; every extracted event with the apex-host `source_url` gets silently dropped via `skipped_origin`.

**Design.** Compare on registrable domain (eTLD+1) instead of full hostname.

- Add `tldextract` as a dependency (single small package, ~100 KB, includes a public-suffix list).
- Replace the body of `_origin_match` with:
  ```python
  def _origin_match(a: str, b: str) -> bool:
      ea, eb = tldextract.extract(a), tldextract.extract(b)
      return (ea.domain, ea.suffix) == (eb.domain, eb.suffix) and ea.domain != ""
  ```
- Empty-domain guard so `mailto:` / `data:` / file URLs still get rejected.

**Test surface:**
- `_origin_match("https://www.hafenklang.com/programm", "https://hafenklang.com/programm")` is True.
- `_origin_match("https://evil.com/", "https://hafenklang.com/")` is False.
- `_origin_match("mailto:x@hafenklang.com", "https://hafenklang.com/")` is False.

---

## Section 6 — Document the SQL-Commit Invariant (A3)

**Problem.** Concern raised during brainstorming: "the agent could be faster than the ingestion pipeline" — i.e., would a subsequent `search_events` call within the same turn see the freshly-ingested rows?

**Status.** Already correct in code. `ingest.py:62-63` commits the SQL transaction before the tool returns; LangGraph ReAct runs tools sequentially within a turn; `search_events` uses SQL synchronously. The Chroma upsert is best-effort and lives on the `get_recommendations` path only, which is not in the search-then-ingest-then-search flow.

**Design.** Add a docstring note to `ingest_event_from_url` (web_research/ingest.py:35-39) stating the invariant, and a one-line module-level comment in `web_research/ingest.py` so it's visible at a glance. No behavioural change.

---

## Section 7 — Regression Test for the Bad-Reply Class

**Problem.** The discipline fixes are easy to regress by future prompt tweaks. We want one durable assertion of the user-visible contract.

**Design.** A new agent-level integration test, `backend/tests/agent/test_reply_discipline.py`, that:

1. Stubs `tools.web_search` to return a hand-crafted hit with HTML/markdown content that — pre-fix — was the exact paste pattern.
2. Stubs `tools.search_events` to return an empty list.
3. Invokes the agent with a prompt like "punk concerts this Friday".
4. Asserts the assistant's final text:
   - does **not** contain the substring `![Foto - Event`,
   - does **not** contain a Tavily content URL,
   - matches the "no events found" phrasing pattern (e.g., contains `no` and either `events` or `results`).

This test runs against the real LangGraph build but with the LLM swapped for a deterministic stub (a `FakeListChatModel` or equivalent) that emits a canned tool-call sequence followed by either compliant text or the failure-mode dump. We assert the *system-level* shape: budget enforcement + prompt rule + snippet shaping together prevent the bad pattern regardless of model whim.

---

## Implementation Order

A natural sequence for the implementation plan:

1. **Section 5** (origin filter) and **Section 6** (docstring) — smallest, mechanical, no dependencies on the others.
2. **Section 3** (default date window) — independent, isolated to `search_events`.
3. **Section 2** (snippet shaping) — independent, isolated to `web_search`.
4. **Section 1** (turn budgets) — new module + two tool entry points + one chat-route hook.
5. **Section 4** (prompt rule) — text-only.
6. **Section 7** (regression test) — depends on 1, 2, 4 landing.

Each step can be its own commit; no step requires later steps to be functional.

---

## Risks & Open Questions

- **Tavily snippet quality after stripping.** If real-world Tavily responses contain mostly markdown-link junk, the post-strip snippet may be very short. Acceptable — the URL itself is the main signal for ingest selection.
- **`tldextract` public-suffix list staleness.** The library bundles a snapshot; not auto-updating. For an event-search use case the suffix list rarely matters past `.com/.de`. Accept default behaviour; revisit only if a legitimate site is rejected.
- **Default date window vs. user explicitly asking for "next month".** Section 3's default only applies when *both* bounds are omitted; the agent is free to widen by passing explicit bounds. If the model fails to pass them when the user clearly asks for far-future events, that's a prompt-tuning problem outside this spec's scope.
- **Integration test brittleness.** A deterministic stub model is robust against real model drift but tests the *contract*, not the *model*. We accept this; the alternative is the evaluation harness deferred above.
