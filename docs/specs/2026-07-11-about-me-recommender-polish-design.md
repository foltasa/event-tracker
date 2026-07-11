# About Me + Recommender Polish — Design

**Status:** Draft v1 · **Date:** 2026-07-11 · **Author:** Alexander Foltas
**Predecessor:** `docs/specs/2026-07-10-recommender-phase1-design.md` (Phase 1)
**Scope:** Corrective follow-up to Phase 1 based on first manual-test findings.

---

## 1. Motivation

First hands-on run of Phase 1 surfaced four problems:

1. **Recommendations return empty across the board.** Root cause is not the taste model — it's that the Chroma vector index has 0 documents while the SQL DB has 7,433 events. `get_category_candidates` queries Chroma → 0 hits → the tool returns `[]` for every category. Ops problem, not code problem.
2. **Facet inputs can't accept spaces or commas.** Confirmed: `concerts.genres` was saved as `{"indie;jazz": 0.9}` after the user typed `indie, jazz`. The comma-split input parser destroys anything with a space or a comma.
3. **The "What the assistant has learned about you" section is confusing.** It renders LLM-inferred content next to user-entered content in the same UI slot. The user wants a single, direct, free-text area for anything not category-specific.
4. **The agent's answer to "what do you know about me" mixes two sources of truth.** `get_user_profile` still returns `interest_tags` (old field) and `taste_summary` (LLM-editable) alongside the new `active_categories` / `taste_facets`. The About Me page is meant to be *the* source of truth but the agent can't tell.

This spec fixes all four. It is a corrective pass on Phase 1, not a rewrite.

---

## 2. Goals and non-goals

### Goals

1. About Me facet inputs accept any text the user wants to type (spaces, commas, arbitrary characters).
2. About Me exposes a free-text "General" area that flows into the agent's context verbatim.
3. `get_user_profile`, the digest curation prompt, and the chat agent all treat About Me as the sole source of user-declared knowledge.
4. Recommendations return non-empty results even when the user has zero saves/likes and only a category checkbox — as long as any candidate events exist.
5. Recommendations *always* privilege user-typed terms over inferred taste, even after a centroid exists.
6. The Chroma index is populated so the semantic-add path actually contributes candidates once a centroid exists.

### Non-goals

- Fuzzy/typo tolerance on user-typed terms.
- Umlaut folding at query time (deferred to a later ingestion-side normalization pass).
- Genre-tagging events (`tags` column stays as-is; genres match against title/description).
- Bringing dislikes back into the About Me UI.
- Reworking Phase 1 schema. All changes are additive or behaviour-only.
- Retiring `interest_tags` / `taste_summary` columns. They stay in the DB; only their user-facing consumers change.

---

## 3. Summary of changes

| Area | Change |
|---|---|
| About Me — facet inputs | Chip/tag input component. Each chip is one discrete term. Case-sensitive as stored; matching is case-insensitive. |
| About Me — general area | New free-text `<textarea>` → `users.about_me` column (already exists). |
| About Me — "what the assistant learned" | Removed. |
| Retrieval — cold-start seed | Replaced with keyword-first SQL match per pill. |
| Retrieval — centroid path | Runs *in addition to* keyword hits (not instead), capped at +15 new events. |
| Retrieval — generic fill | New fallback: upcoming events in that category, ordered by `start_datetime`, to reach floor of 30 events. |
| Retrieval — dislike hard-filter | Disabled (short-circuit to pass-through). |
| Comment extractor | Disabled behind a config flag (default off). Module and tests preserved. |
| Curation prompt | Drops `interest_tags` and `taste_summary`. Adds `about_me` prose + compact facets (no weights). |
| `get_user_profile` | Returns `about_me`, `active_categories`, `taste_facets` only. Drops `interest_tags`, `taste_summary`. |
| Chroma | One-shot backfill (script + operator instruction). No code change to embedding stage. |

---

## 4. About Me page redesign

### 4.1 Layout

```
[Category checkboxes]  concerts ☑  party ☑  comedy ☐  theater ☑  arts ☐ …

── General ────────────────────────────────────────
Anything you want the assistant to know that isn't
category-specific? (multi-line free text)
[ textarea, 6 rows                              ]

── Concerts ──────────────────────────────────────
Favourite artists     [ chip ] [ chip ] [ + type here ]
Favourite genres      [ chip ] [ chip ] [ + type here ]
Favourite venues      [ chip ] [ + type here ]
Notes                 [ textarea, 3 rows           ]

── Party ─────────────────────────────────────────
… same structure …

[ Save ]
```

The old "What the assistant has learned about you" section is deleted. There is one source of truth per field: what the user typed.

### 4.2 Chip input component

A single new component `ChipInput.tsx`:

- Renders existing chips as pills, plus one inline `<input>` for the next chip.
- Commit triggers: `Enter`, `Tab`, blur.
- `Backspace` on empty input removes the last chip.
- Deduplicates on commit (case-insensitive compare of trimmed values). Duplicate = silent no-op.
- Empty / whitespace-only commits are ignored.
- No comma/space splitting inside the input — a chip's content is whatever the user typed until they committed it.
- Props: `value: string[]`, `onChange: (v: string[]) => void`, `placeholder?: string`.

Used in three places per active category: `artists`, `genres`, `venues`.

### 4.3 Data flow

`AboutMeUpdate` schema gains one field: `about_me: str | None`. Category form still ships `artists`, `genres`, `venues` inside `taste_facets[cat]` and a per-category `notes: str | None` inside the same dict — same shape as today (verified in `frontend/lib/aboutMeCategories.ts` and `routes_about_me.py`). The only structural change on the wire is that chip fields become arrays of exactly what the user typed instead of the current comma-split parse.

Backend `PUT /about-me`:

- Writes `u.about_me = payload.about_me` when provided (nullable, replaces on write). `users.about_me` column already exists; no migration.
- Rebuilds `u.taste_facets` from the payload the same way as today — one entry per chip. A fixed weight of `1.0` is written so the on-disk JSON stays a `{term: weight}` dict, but no consumer reads the weight anymore (see §6). Existing entries with other weights are left untouched on merge.
- Triggers `refresh_taste_centroids` (unchanged from Phase 1).

Removed from `PUT /about-me`: the background comment-extractor invocation on per-category notes (see §7). The `notes` string still stores verbatim and flows into the curator prompt.

The legacy `taste_summary` field remains accepted in `AboutMeUpdate` (no schema migration and existing clients won't break) but the frontend stops sending or rendering it — see §4.4.

### 4.4 Removed UI

The "What the assistant has learned about you" section — which today renders `taste_summary` — is deleted from the About Me page. `AboutMeResponse.taste_summary` still exists on the wire; the frontend simply stops consuming it. No backend or DB change.

### 4.5 First-visit redirect

Unchanged from Phase 1. `active_categories === null` still redirects to `/about-me`.

---

## 5. Retrieval redesign

### 5.1 New per-category flow

Replaces `retrieval.get_category_candidates` for one category call:

```
pool = []
1. Keyword pass (always):
   for each pill in taste_facets[cat].{venues, artists, genres}:
       hits = keyword_query(cat, pill, date_from, date_to, limit=per_pill_cap)
       pool.extend(hits)
   pool = dedup_by_event_id(pool)

2. Semantic add (only if centroid exists):
   centroid = taste_centroids.get(cat)
   if centroid:
       sem_hits = chroma.query_by_vector(
           centroid, n=15, where={"category": cat, date range})
       pool.extend(h for h in sem_hits if h.event_id not in pool_ids)

3. Generic fill (if pool < 30):
   more = SQL: category=cat AND date range AND NOT already-in-pool
                ORDER BY start_datetime ASC
                LIMIT (30 - len(pool))
   pool.extend(more)

return pool
```

### 5.2 Keyword matcher

Per pill type:

- `venues.*` → `LOWER(venue_name) LIKE LOWER('%<pill>%')`
- `artists.*` → `LOWER(title) LIKE LOWER('%<pill>%') OR LOWER(description) LIKE LOWER('%<pill>%')`
- `genres.*` → same as `artists.*` (the `tags` column does not contain musical subgenres — verified against production data)

All within the category and date range: `AND category = <cat> AND start_datetime BETWEEN date_from AND date_to`.

Order per pill query: `start_datetime ASC`, `LIMIT per_pill_cap`.

No umlaut folding, no fuzzy matching. Deferred to a future ingestion-side pass.

### 5.3 Per-pill cap

```
per_pill_cap = max(1, ceil(50 / n_pills_in_category))
```

where `n_pills_in_category` counts non-empty entries across venues + artists + genres for that category. Guarantees ≥1 event per pill up to 50 pills; degrades gracefully beyond that (still 1 per pill, pool just grows).

Rationale: with 5 pills the pool is dense (~50); with 30 pills each contributes ~2. Pills with zero matches contribute nothing — no wasted budget.

### 5.4 Semantic add cap

Fixed constant `SEMANTIC_TOP_UP = 15`. Only queried if a centroid exists for that category. Deduplicated against keyword pool by `event_id`.

### 5.5 Generic fill floor

`GENERIC_FLOOR = 30`. Applied only if the union of keyword + semantic is below 30 events for that category. Orders by `start_datetime ASC`.

### 5.6 Dislike hard-filter

`retrieval.filter_out_disliked` becomes a pass-through returning the input `event_ids` list unchanged. `_iter_disliked_terms` retained so re-enabling is one line.

---

## 6. Curation prompt and agent profile

### 6.1 `CURATION_PROMPT` (in `app/agent/prompts.py`)

Removed placeholders: `interests`, `taste_summary`.

Kept placeholders: `about_me`, `active_categories`, `inactive_categories`, `event_pool`.

Renamed / reshaped: `taste_facets_json` → a compact prose block, e.g.:

```
About the user:
- General: {about_me or "(nothing written)"}
- Active categories: {active_categories}
- Inactive categories: {inactive_categories}
- Per-category preferences:
  concerts:
    artists: Nils Frahm, Radiohead
    genres:  indie, jazz
    venues:  Elbphilharmonie
    notes:   (any free text from the notes field)
  party:
    venues:  Südpol
```

Weights are dropped from the prompt entirely. The disliked block is dropped.

Formatting is built server-side from `taste_facets` (each chip = one item in the comma-separated list). `notes` is included verbatim as free text.

### 6.2 `get_user_profile` tool

Returns:

```python
{
    "about_me": user.about_me,
    "active_categories": list(user.active_categories) if user.active_categories is not None else None,
    "taste_facets": <same compact shape as above, no weights>,
}
```

`interest_tags` and `taste_summary` are dropped from the response. The columns stay in the DB.

### 6.3 Chat system prompt

If the chat system prompt references "interests" or "taste summary" placeholders they are updated to reference "About Me" and "per-category preferences". Concrete strings determined during implementation.

---

## 7. Disabling the extractor and dislike filter

### 7.1 Feature flag

New settings entry:

```python
comment_extractor_enabled: bool = False
```

in `app/config.py`. Default False in code; overrideable via env `COMMENT_EXTRACTOR_ENABLED`.

Gates two call sites:

- `routes_feedback.py` — the `background.add_task(...)` on `POST /feedback` skips when the flag is False.
- `routes_about_me.py` — the loop that schedules `_extract_notes_bg` for each per-category `notes` string skips when the flag is False.

Both check `settings.comment_extractor_enabled` and no-op when False. The module `app/agent/comment_extractor.py` and its tests remain intact; the extractor is still importable and unit-testable.

### 7.2 Dislike filter

`retrieval.filter_out_disliked` short-circuits to `return list(event_ids)`. Existing tests updated to reflect the pass-through behaviour; the underlying `_iter_disliked_terms` helper retains its tests.

Re-enabling either feature is a one-line change.

---

## 8. Chroma backfill

Not a code change. Operator action:

```
cd backend
python -c "from app.db.session import SessionLocal; from app.ingestion.scheduler import embed_new_events; s = SessionLocal(); embed_new_events(s); s.commit(); s.close()"
```

runs the existing `embed_new_events` stage against the current visible-events pool. After it completes, `chroma_store._get_collection().count()` should be non-zero.

The plan will document this as the first manual step in the verification phase. A small operator script `backend/scripts/embed_events.py` mirroring `backfill_taste_centroids.py` is nice-to-have and cheap; the plan includes it.

---

## 9. Migration and compatibility

Zero schema changes. `users.about_me` and `users.taste_facets` already exist.

Backwards behaviour:

- Existing users with populated `interest_tags` / `taste_summary` are unaffected in the DB — the columns keep their values. Only the agent-facing consumers stop reading them.
- Existing `taste_facets` entries with weights other than 1.0 keep working — the retrieval keyword matcher reads only keys, and the curator prompt renders only keys.
- Existing `disliked.*` entries in `taste_facets` are ignored by retrieval (filter is a pass-through) and dropped from the curator prompt. Data is retained on disk.

---

## 10. Testing

Backend:

- `test_retrieval.py` — update: assert keyword-first behaviour with mock DB rows; assert semantic-add caps at 15; assert generic fill kicks in below 30; assert dislike pass-through.
- `test_routes_about_me.py` — extend: `general` field roundtrip; chip inputs preserve spaces/commas within a single value.
- `test_routes_feedback_extractor.py` — extend: assert background task is NOT scheduled when `comment_extractor_enabled=False`.
- `test_prompts.py` (new or extend): assert `CURATION_PROMPT` renders without `interest_tags` / `taste_summary` and includes new prose block.
- `test_tools.py` — extend: `get_user_profile` returns the reduced field set.

Frontend:

- `ChipInput` unit test: commit triggers, dedup, backspace behaviour.
- About Me page: `general` field roundtrip.
- Snapshot / integration test for the removed "learned about you" section.

Manual verification (Task 20-equivalent in the plan): the browser walkthrough from Phase 1 plus:

1. Fill Südpol into `party.venues`, save, ask agent for party recommendations for next week. Expect ≥1 event at Südpol in the results.
2. Type "the beatles, later years" as an artist chip — verify it's saved as a single chip, not split.
3. Ask agent "what do you know about me". Expect the reply to reflect only About Me content (no `interest_tags` echo, no `taste_summary` echo).
4. Confirm empty Chroma after backfill: `col.count() > 0`.

---

## 11. Open questions

None currently open — the four questions raised during brainstorming have all been resolved:

- Free-text vs structured per-category → keep structured, chip input, drop weights, add free-text notes + general.
- Multi-fact union semantics → union across pills, not intersection.
- Comment extractor scope → disabled for now behind a flag.
- Umlaut normalization → deferred; addressed later at the ingestion layer.
