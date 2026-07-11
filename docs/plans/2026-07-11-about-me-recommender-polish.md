# About Me + Recommender Polish — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the corrective follow-up to Phase 1 — chip inputs on About Me, free-text general section, keyword-first retrieval with semantic add + generic fill, dislike filter and comment extractor gated behind a flag, curator prompt and `get_user_profile` reduced to About Me as the single source of truth.

**Architecture:** Backend behaviour-only changes to `app/agent/retrieval.py`, `app/agent/tools.py`, `app/agent/prompts.py`, `app/api/routes_digest.py`, `app/api/routes_feedback.py`, `app/api/routes_about_me.py`, `app/schemas/about_me.py`, `app/config.py`; frontend gains a reusable `ChipInput` component and rewires `CategoryFacetsSection` + the About Me page; one operator script for Chroma backfill.

**Tech Stack:** FastAPI + SQLAlchemy + Chroma; pytest; Next.js 14 App Router + Tailwind + SWR; Vitest + @testing-library/react.

**Spec:** `docs/specs/2026-07-11-about-me-recommender-polish-design.md`

---

## File Structure

### Files created

Backend:
- `backend/scripts/embed_events.py` — one-shot operator script that repopulates Chroma from visible events.

Frontend:
- `frontend/components/ChipInput.tsx` — reusable chip/tag input component.
- `frontend/components/ChipInput.test.tsx` — Vitest + Testing Library tests for `ChipInput`.

### Files modified

Backend:
- `backend/app/config.py` — new `comment_extractor_enabled: bool = False` setting.
- `backend/app/api/routes_feedback.py` — gate the comment-extractor background task on the flag.
- `backend/app/api/routes_about_me.py` — gate the per-category notes extractor on the flag; read and write `users.about_me`.
- `backend/app/agent/retrieval.py` — dislike filter becomes pass-through; new `_keyword_hits_for_category` helper; `get_category_candidates` becomes keyword-first with semantic add + generic fill.
- `backend/app/agent/tools.py` — `get_user_profile` returns only `about_me`, `active_categories`, `taste_facets`.
- `backend/app/agent/prompts.py` — new `CURATION_PROMPT` template (drops `interests`, `taste_summary`, `disliked_json`; keeps `about_me`, `active_categories`, `inactive_categories`, `event_pool`; adds `taste_prose`).
- `backend/app/api/routes_digest.py` — build the new prompt with prose taste block; drop old placeholders.
- `backend/app/schemas/about_me.py` — `AboutMeResponse` gains `about_me: str | None`; `AboutMeUpdate` gains `about_me: str | None`.

Frontend:
- `frontend/lib/types.ts` — `AboutMeResponse.about_me` and `AboutMeUpdate.about_me` fields.
- `frontend/lib/api.ts` — `updateAboutMe` / `getAboutMe` include `about_me` in the mock path.
- `frontend/components/CategoryFacetsSection.tsx` — replace comma-string parse with `ChipInput`; artists/genres/venues values become arrays of strings.
- `frontend/app/about-me/page.tsx` — add General textarea bound to `about_me`; remove the "What the assistant has learned about you" section and its `tasteSummary` state.

### Tests modified

- `backend/tests/agent/test_retrieval.py` — rewrite expectations for the new flow; keep dislike-filter-pass-through test.
- `backend/tests/agent/test_tools.py` (or the profile-specific file) — assert new `get_user_profile` shape.
- `backend/tests/agent/test_tools_profile.py` — align with new shape.
- `backend/tests/agent/test_tools_recommendations.py` — align with new retrieval flow.
- `backend/tests/agent/test_prompts.py` — assert new `CURATION_PROMPT` placeholders.
- `backend/tests/api/test_routes_about_me.py` — cover the `about_me` roundtrip.
- `backend/tests/api/test_routes_feedback_extractor.py` — assert the background task is skipped when the flag is off.
- `backend/tests/api/test_routes_digest.py` — align with the new prompt formatting.

---

## Conventions

- Commit style: `feat(area): subject`, `fix(area): subject`, `docs(specs|plans): subject`. Match `git log --oneline -20`.
- Never chain shell commands with `&&` or `;` when each is already allowed under `Bash(git:*)` — run them as separate calls.
- All code comments in English (repo-wide rule in `CLAUDE.md`).
- Tests use existing `conftest.py` `db_session` and `client` fixtures.
- LLM calls in tests are mocked at the `llm` boundary; never make real network calls in tests.
- Working directory in commands: `backend/` unless otherwise stated.

---

## Task 1: Comment-extractor feature flag + gate at both call sites

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/routes_feedback.py`
- Modify: `backend/app/api/routes_about_me.py`
- Test: `backend/tests/api/test_routes_feedback_extractor.py`
- Test: `backend/tests/api/test_routes_about_me.py`

- [ ] **Step 1: Add the failing test in `test_routes_feedback_extractor.py`**

Add at the top of the file (near the other imports and after any existing tests):

```python
def test_feedback_does_not_schedule_extractor_when_disabled(client, db_session, monkeypatch):
    """When comment_extractor_enabled=False the POST does not schedule the background task."""
    from app.config import settings
    from app.db.models import Event, User

    monkeypatch.setattr(settings, "comment_extractor_enabled", False)

    ev = Event(
        id="e1", external_id="e1", source="test", title="X",
        description="d", start_datetime=__import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc),
        category="concerts", tags=[], source_url="http://e", raw_data={},
    )
    db_session.add(ev)
    db_session.add(User(id="local"))
    db_session.commit()

    called = {"n": 0}

    def fake_extract_and_apply(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr("app.api.routes_feedback.extract_and_apply", fake_extract_and_apply)

    r = client.post("/feedback", json={"event_id": "e1", "sentiment": "like", "comment": "loved it"})
    assert r.status_code == 200
    assert called["n"] == 0
```

- [ ] **Step 2: Run the test to verify failure**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py::test_feedback_does_not_schedule_extractor_when_disabled -v`
Expected: FAIL (either `AttributeError: 'Settings' object has no attribute 'comment_extractor_enabled'` or the extractor is called anyway).

- [ ] **Step 3: Add the failing test in `test_routes_about_me.py`**

Add:

```python
def test_about_me_notes_do_not_schedule_extractor_when_disabled(client, db_session, monkeypatch):
    from app.config import settings
    from app.db.models import User

    monkeypatch.setattr(settings, "comment_extractor_enabled", False)

    db_session.add(User(id="local", active_categories=["concerts"], taste_facets={}))
    db_session.commit()

    called = {"n": 0}

    def fake_extract_and_apply(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr("app.api.routes_about_me.extract_and_apply", fake_extract_and_apply)

    r = client.put("/about-me", json={
        "active_categories": ["concerts"],
        "taste_facets": {"concerts": {"notes": "I love late-night piano concerts"}},
    })
    assert r.status_code == 200
    assert called["n"] == 0
```

- [ ] **Step 4: Add the flag to `Settings`**

Modify `backend/app/config.py`. Add this block after the `web_search_*` group (before `cors_allowed_origins`):

```python
    # Comment extractor — when False the feedback POST and About-Me PUT do not
    # schedule the LLM-driven extractor background task. Facets remain
    # user-editable via the About Me form; behaviour signals still feed
    # taste_centroids via refresh_taste_centroids.
    comment_extractor_enabled: bool = False
```

- [ ] **Step 5: Gate the feedback POST**

Modify `backend/app/api/routes_feedback.py`. Find the block that schedules the extractor via `background.add_task(...)` on `POST /feedback` and wrap it in a settings check. If the file already imports settings, reuse the import; otherwise add:

```python
from app.config import settings
```

Then wrap the existing `background.add_task(...)` call for the comment extractor:

```python
if settings.comment_extractor_enabled:
    background.add_task(...)  # existing call, unchanged
```

If the call site currently invokes `extract_and_apply` directly rather than via `background.add_task`, gate that call the same way.

- [ ] **Step 6: Gate the About-Me PUT**

Modify `backend/app/api/routes_about_me.py` — the loop at the end of `update_about_me`:

```python
    for cat, text in notes_to_extract:
        background.add_task(_extract_notes_bg, user_id=user_id, category=cat, text=text)
```

becomes:

```python
    if settings.comment_extractor_enabled:
        for cat, text in notes_to_extract:
            background.add_task(_extract_notes_bg, user_id=user_id, category=cat, text=text)
```

Add the import at the top:

```python
from app.config import settings
```

- [ ] **Step 7: Run both new tests to verify pass**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py backend/tests/api/test_routes_about_me.py -v -k "not_schedule_extractor_when_disabled or notes_do_not_schedule_extractor_when_disabled"`
Expected: both PASS.

- [ ] **Step 8: Run full extractor + about-me test files to catch regressions**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py backend/tests/api/test_routes_about_me.py -v`
Expected: existing tests must still pass. Any pre-existing test that assumes the extractor runs must set `settings.comment_extractor_enabled = True` in a `monkeypatch` step. Fix by adding that monkeypatch to any failing existing test.

- [ ] **Step 9: Commit**

```
git add backend/app/config.py backend/app/api/routes_feedback.py backend/app/api/routes_about_me.py backend/tests/api/test_routes_feedback_extractor.py backend/tests/api/test_routes_about_me.py
git commit -m "feat(recommender): gate comment extractor behind flag (default off)"
```

---

## Task 2: Dislike filter becomes pass-through

**Files:**
- Modify: `backend/app/agent/retrieval.py`
- Test: `backend/tests/agent/test_retrieval.py`

- [ ] **Step 1: Rewrite the two dislike-filter tests**

Replace the existing `test_filter_out_disliked_terms_substring_match` and `test_filter_out_disliked_is_case_insensitive` tests in `backend/tests/agent/test_retrieval.py` with:

```python
def test_filter_out_disliked_is_passthrough(db_session):
    from app.agent.retrieval import filter_out_disliked
    from app.db.models import User

    _mk_event(db_session, "e_edm", "party", title="Big EDM night", desc="DJ set")
    _mk_event(db_session, "e_ok", "party", title="Techno party", desc="raw sound")
    db_session.commit()

    user = User(
        id="local",
        # Even with dislike facets present, filter must be a no-op.
        taste_facets={"party": {"disliked.genres": {"edm": 1.0}}},
    )
    kept = filter_out_disliked(db_session, user, "party", ["e_edm", "e_ok"])
    assert kept == ["e_edm", "e_ok"]


def test_filter_out_disliked_passthrough_with_empty_facets(db_session):
    from app.agent.retrieval import filter_out_disliked
    from app.db.models import User

    _mk_event(db_session, "e1", "concerts")
    db_session.commit()
    user = User(id="local", taste_facets={})
    assert filter_out_disliked(db_session, user, "concerts", ["e1"]) == ["e1"]
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `pytest backend/tests/agent/test_retrieval.py -v -k "filter_out_disliked"`
Expected: `test_filter_out_disliked_is_passthrough` FAILS (the current filter removes `e_edm`).

- [ ] **Step 3: Short-circuit `filter_out_disliked`**

Modify `backend/app/agent/retrieval.py`. Replace the body of `filter_out_disliked` with an immediate pass-through:

```python
def filter_out_disliked(
    session: Session,
    user: User,
    category: str,
    event_ids: list[str],
) -> list[str]:
    """Dislike hard-filter is currently disabled.

    Preserved as a call site so re-enabling is a one-line change: revert
    this function to iterate _iter_disliked_terms and substring-match
    against event title/description/tags."""
    return list(event_ids)
```

Leave `_iter_disliked_terms` intact for future re-enable.

- [ ] **Step 4: Run the tests to verify pass**

Run: `pytest backend/tests/agent/test_retrieval.py -v -k "filter_out_disliked"`
Expected: both PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/retrieval.py backend/tests/agent/test_retrieval.py
git commit -m "feat(recommender): disable dislike hard-filter (pass-through)"
```

---

## Task 3: Keyword hits helper in retrieval

**Files:**
- Modify: `backend/app/agent/retrieval.py`
- Test: `backend/tests/agent/test_retrieval.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/agent/test_retrieval.py`:

```python
def test_keyword_hits_matches_venue_name_case_insensitively(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import User

    _mk_event(db_session, "e1", "party", title="Late Night", desc="dj set")
    e = _mk_event(db_session, "e2", "party", title="X", desc="Y")
    e.venue_name = "Südpol Basement"
    _mk_event(db_session, "e3", "party", title="Other", desc="")
    db_session.commit()

    user = User(id="local", taste_facets={"party": {"venues": {"südpol": 1.0}}})
    hits = _keyword_hits_for_category(db_session, user, "party", date_from=None, date_to=None, per_pill_cap=10)
    assert [h.event_id for h in hits] == ["e2"]


def test_keyword_hits_matches_title_and_description_for_artists_and_genres(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import User

    _mk_event(db_session, "e_title", "concerts", title="Nils Frahm live", desc="")
    _mk_event(db_session, "e_desc", "concerts", title="Piano evening", desc="Featuring Nils Frahm")
    _mk_event(db_session, "e_none", "concerts", title="Other", desc="")
    _mk_event(db_session, "e_genre_desc", "concerts", title="Combo", desc="An indie evening")
    db_session.commit()

    user = User(id="local", taste_facets={
        "concerts": {"artists": {"nils frahm": 1.0}, "genres": {"indie": 1.0}},
    })
    hits = _keyword_hits_for_category(db_session, user, "concerts", date_from=None, date_to=None, per_pill_cap=10)
    got = {h.event_id for h in hits}
    assert got == {"e_title", "e_desc", "e_genre_desc"}


def test_keyword_hits_respects_per_pill_cap_and_date_range(db_session):
    from app.agent.retrieval import _keyword_hits_for_category
    from app.db.models import Event, User
    from datetime import datetime, timezone

    # Two "südpol" party events on different dates.
    e_in = Event(id="in", external_id="in", source="t", title="X", description="d",
                 start_datetime=datetime(2026, 6, 15, tzinfo=timezone.utc),
                 category="party", tags=[], source_url="http://e", raw_data={},
                 venue_name="Südpol")
    e_out = Event(id="out", external_id="out", source="t", title="X", description="d",
                  start_datetime=datetime(2026, 8, 15, tzinfo=timezone.utc),
                  category="party", tags=[], source_url="http://e", raw_data={},
                  venue_name="Südpol")
    db_session.add_all([e_in, e_out])
    db_session.commit()

    user = User(id="local", taste_facets={"party": {"venues": {"südpol": 1.0}}})
    hits = _keyword_hits_for_category(
        db_session, user, "party",
        date_from="2026-06-01", date_to="2026-07-01", per_pill_cap=10,
    )
    assert [h.event_id for h in hits] == ["in"]

    # per_pill_cap = 1 caps the per-pill result to 1 event even when both match.
    hits_capped = _keyword_hits_for_category(
        db_session, user, "party",
        date_from=None, date_to=None, per_pill_cap=1,
    )
    assert len(hits_capped) == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_retrieval.py -v -k "keyword_hits"`
Expected: FAIL — `_keyword_hits_for_category` does not exist.

- [ ] **Step 3: Implement the helper**

Modify `backend/app/agent/retrieval.py`. Add near the other helpers (after `_range_clause`, before `get_category_candidates`):

```python
from sqlalchemy import func, or_


def _iter_pills_for_category(user: User, category: str) -> list[tuple[str, str]]:
    """Yield (field, term) pairs from taste_facets[category] for venues, artists, genres.

    Order is stable: venues, then artists, then genres — so the pool is
    predictable across runs."""
    facets = (user.taste_facets or {}).get(category) or {}
    out: list[tuple[str, str]] = []
    for field in ("venues", "artists", "genres"):
        bucket = facets.get(field) or {}
        for term in bucket.keys():
            term = (term or "").strip()
            if term:
                out.append((field, term))
    return out


def _keyword_hits_for_category(
    session: Session,
    user: User,
    category: str,
    *,
    date_from: str | None,
    date_to: str | None,
    per_pill_cap: int,
) -> list[QueryHit]:
    """Run a case-insensitive substring query per pill and union the results.

    - venues.*  → LOWER(venue_name)  LIKE '%term%'
    - artists.* → LOWER(title) OR LOWER(description) LIKE '%term%'
    - genres.*  → same as artists.* (tags column does not carry musical subgenres)

    All within the category and optional date window. Each pill's query is
    capped at `per_pill_cap`. Result is deduplicated across pills, order
    preserved by first appearance. Returns QueryHit objects with a
    `similarity_score` of None (semantic scoring is applied elsewhere)."""
    pills = _iter_pills_for_category(user, category)
    if not pills:
        return []

    # Build the date bounds once.
    date_lo = date_hi = None
    if date_from:
        date_lo = datetime.combine(date.fromisoformat(date_from), time.min, tzinfo=timezone.utc)
    if date_to:
        date_hi = datetime.combine(date.fromisoformat(date_to), time.max, tzinfo=timezone.utc)

    seen: dict[str, QueryHit] = {}
    for field, term in pills:
        like = f"%{term.lower()}%"
        q = session.query(Event.id).filter(Event.category == category)
        if date_lo is not None:
            q = q.filter(Event.start_datetime >= date_lo)
        if date_hi is not None:
            q = q.filter(Event.start_datetime <= date_hi)
        if field == "venues":
            q = q.filter(func.lower(Event.venue_name).like(like))
        else:
            q = q.filter(or_(
                func.lower(Event.title).like(like),
                func.lower(Event.description).like(like),
            ))
        q = q.order_by(Event.start_datetime.asc()).limit(per_pill_cap)
        for (eid,) in q.all():
            if eid not in seen:
                seen[eid] = QueryHit(event_id=eid, similarity_score=None)
    return list(seen.values())
```

If `QueryHit` requires positional args or dataclass defaults that make `similarity_score=None` invalid, adjust the constructor to match its dataclass signature — check `app/rag/chroma_store.py:QueryHit`. If it disallows `None`, pass `0.0` instead and update the tests to allow either.

- [ ] **Step 4: Verify `QueryHit` accepts the value**

Read `backend/app/rag/chroma_store.py` and confirm `QueryHit` dataclass shape. If `similarity_score` is typed as `float`, either widen it to `float | None` in that file (safe — it's a dataclass used only for read paths) or pass `0.0` instead of `None` in the helper. Preferred: widen the type. If widening, remember to keep it non-breaking for existing consumers.

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest backend/tests/agent/test_retrieval.py -v -k "keyword_hits"`
Expected: all three PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/agent/retrieval.py backend/tests/agent/test_retrieval.py backend/app/rag/chroma_store.py
git commit -m "feat(recommender): per-pill keyword hits helper for retrieval"
```

If `chroma_store.py` was not modified, drop it from `git add`.

---

## Task 4: Rewrite `get_category_candidates` — keyword-first + semantic add + generic fill

**Files:**
- Modify: `backend/app/agent/retrieval.py`
- Test: `backend/tests/agent/test_retrieval.py`

- [ ] **Step 1: Delete tests that assert the old cold-start flow**

In `backend/tests/agent/test_retrieval.py`, delete these two tests entirely (their premises no longer hold):
- `test_get_category_candidates_cold_start_from_facets`
- `test_get_category_candidates_returns_empty_when_no_seed`

Keep:
- `test_get_category_candidates_returns_empty_when_category_inactive`
- `test_get_category_candidates_uses_category_centroid`

Adjust `test_get_category_candidates_uses_category_centroid` to allow up to 15 semantic hits: it asserts only that when a centroid exists and Chroma returns hits, those hits show up in the result. Leave its structure intact.

- [ ] **Step 2: Add new tests for the new flow**

Append:

```python
def test_get_category_candidates_keyword_first_no_centroid(db_session):
    from app.agent.retrieval import get_category_candidates
    from app.db.models import Event, User
    from datetime import datetime, timezone

    # Two party events at Südpol + 40 generic party events (enough to trigger fill).
    for i in range(40):
        _mk_event(db_session, f"gen_{i}", "party", title=f"Party {i}", desc="")
    e = Event(id="s1", external_id="s1", source="t", title="Loud",
              description="", start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
              category="party", tags=[], source_url="http://e", raw_data={},
              venue_name="Südpol")
    db_session.add(e)
    db_session.commit()

    user = User(
        id="local", active_categories=["party"],
        taste_facets={"party": {"venues": {"südpol": 1.0}}},
        taste_centroids={},
    )
    hits = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=30)
    ids = [h.event_id for h in hits]
    # Südpol match is always in the pool.
    assert "s1" in ids
    # Generic fill kicks in because pool < GENERIC_FLOOR = 30 after keyword pass.
    assert len(ids) >= 30


def test_get_category_candidates_semantic_add_only_if_centroid(db_session):
    from unittest.mock import patch
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    _mk_event(db_session, "kw1", "concerts", title="Nils Frahm live", desc="")
    _mk_event(db_session, "sem1", "concerts")
    db_session.commit()

    user = User(
        id="local", active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"nils frahm": 1.0}}},
        taste_centroids={"concerts": [1.0, 0.0]},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        q.return_value = [type("H", (), {"event_id": "sem1", "similarity_score": 0.9})()]
        hits = get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=30)
    ids = [h.event_id for h in hits]
    assert "kw1" in ids
    assert "sem1" in ids


def test_get_category_candidates_semantic_skipped_without_centroid(db_session):
    from unittest.mock import patch
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    _mk_event(db_session, "kw1", "concerts", title="Nils Frahm live", desc="")
    db_session.commit()
    user = User(
        id="local", active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"nils frahm": 1.0}}},
        taste_centroids={},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=30)
        q.assert_not_called()


def test_get_category_candidates_per_pill_cap_scales_with_pill_count(db_session):
    from app.agent.retrieval import get_category_candidates
    from app.db.models import User

    # 60 party events, each mentioning both venues.
    for i in range(60):
        _mk_event(db_session, f"p{i}", "party", title=f"Südpol Fundbureau {i}", desc="")
    db_session.commit()

    user = User(
        id="local", active_categories=["party"], taste_centroids={},
        taste_facets={"party": {"venues": {"südpol": 1.0, "fundbureau": 1.0}}},
    )
    hits = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=30)
    # Two pills, target=50 → per_pill_cap = 25. After dedup (both terms match every event)
    # unique events = 25. Then generic fill runs since pool < 30, adding 5 more.
    assert len(hits) >= 30
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_retrieval.py -v -k "get_category_candidates"`
Expected: the new tests FAIL — `get_category_candidates` still uses the old cold-start flow.

- [ ] **Step 4: Rewrite `get_category_candidates`**

Modify `backend/app/agent/retrieval.py`. Replace the entire body of `get_category_candidates` (keep the signature) with:

```python
GENERIC_FLOOR = 30
SEMANTIC_TOP_UP = 15
POOL_TARGET = 50


def _per_pill_cap(user: User, category: str) -> int:
    """Compute per-pill row cap so the pool trends toward POOL_TARGET.

    Minimum of 1 per pill. If no pills are declared, the caller does not
    invoke this — but return 1 as a safe default."""
    n = len(_iter_pills_for_category(user, category))
    if n <= 0:
        return 1
    from math import ceil
    return max(1, ceil(POOL_TARGET / n))


def get_category_candidates(
    session: Session,
    user: User,
    category: str,
    *,
    date_from: str | None,
    date_to: str | None,
    k: int = 30,
) -> list[QueryHit]:
    """Keyword-first candidate retrieval with semantic add and generic fill.

    Order:
    1. Keyword hits from user-typed pills (venues/artists/genres). Always.
    2. Semantic add: up to SEMANTIC_TOP_UP Chroma hits keyed on the
       category centroid, deduplicated against keyword hits. Only when a
       centroid exists.
    3. Generic fill: upcoming events in this category, ordered by
       start_datetime, to reach GENERIC_FLOOR.

    The `k` argument is a soft ceiling for the caller — this function
    returns up to GENERIC_FLOOR + SEMANTIC_TOP_UP events irrespective of
    `k`, since ranking upstream slices the final list.

    Deactivated categories return []. Disliked filter is currently a
    pass-through (see filter_out_disliked)."""
    if user.active_categories is not None and category not in user.active_categories:
        return []

    seen: dict[str, QueryHit] = {}

    # 1. Keyword hits — always.
    per_pill_cap = _per_pill_cap(user, category)
    kw_hits = _keyword_hits_for_category(
        session, user, category,
        date_from=date_from, date_to=date_to, per_pill_cap=per_pill_cap,
    )
    for h in kw_hits:
        seen[h.event_id] = h

    # 2. Semantic add — only with a centroid.
    centroid = (user.taste_centroids or {}).get(category)
    if centroid:
        where: dict = {"category": category}
        rng = _range_clause(date_from, date_to)
        if rng:
            where = {"$and": [where, rng]}
        sem = chroma_store.query_by_vector(list(centroid), n=SEMANTIC_TOP_UP, where=where)
        for h in sem or []:
            if h.event_id not in seen:
                seen[h.event_id] = h

    # 3. Generic fill — top up to GENERIC_FLOOR with upcoming events in this category.
    if len(seen) < GENERIC_FLOOR:
        need = GENERIC_FLOOR - len(seen)
        q = session.query(Event.id).filter(Event.category == category)
        if date_from:
            q = q.filter(Event.start_datetime >= datetime.combine(
                date.fromisoformat(date_from), time.min, tzinfo=timezone.utc))
        if date_to:
            q = q.filter(Event.start_datetime <= datetime.combine(
                date.fromisoformat(date_to), time.max, tzinfo=timezone.utc))
        if seen:
            q = q.filter(~Event.id.in_(seen.keys()))
        for (eid,) in q.order_by(Event.start_datetime.asc()).limit(need).all():
            seen[eid] = QueryHit(event_id=eid, similarity_score=None)

    # Dislike hard-filter is a pass-through — call kept to preserve the seam.
    kept = set(filter_out_disliked(session, user, category, list(seen.keys())))
    return [seen[eid] for eid in seen if eid in kept]
```

Also delete the now-unused `_build_cold_start_seed` and the top-level `from app.rag.embeddings import embed_one` (they are dead once cold-start seeding is gone). Update the module docstring if it references cold-start seeding.

- [ ] **Step 5: Run all retrieval tests to verify pass**

Run: `pytest backend/tests/agent/test_retrieval.py -v`
Expected: all PASS. If `test_get_category_candidates_uses_category_centroid` fails because the semantic path is now conditional on `POOL_TARGET`, review the test — the semantic add still runs when a centroid exists, so the assertion "hit shows up in the result" must still hold.

- [ ] **Step 6: Run tools + digest tests to check for downstream regressions**

Run: `pytest backend/tests/agent/test_tools_recommendations.py backend/tests/api/test_routes_digest.py -v`
Expected: green, or predictable failures from tests that mocked the old behaviour. Fix any test that patched `_build_cold_start_seed` or `embed_one` — the new flow does not call them.

- [ ] **Step 7: Commit**

```
git add backend/app/agent/retrieval.py backend/tests/agent/test_retrieval.py
git commit -m "feat(recommender): keyword-first retrieval with semantic add + generic fill"
```

---

## Task 5: About-Me schemas gain `about_me` field

**Files:**
- Modify: `backend/app/schemas/about_me.py`
- Test: `backend/tests/api/test_routes_about_me.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/api/test_routes_about_me.py`:

```python
def test_about_me_roundtrips_general_text(client, db_session):
    from app.db.models import User

    db_session.add(User(id="local"))
    db_session.commit()

    r = client.put("/about-me", json={
        "active_categories": ["concerts"],
        "about_me": "I bike to venues and hate crowds after 23:00.",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["about_me"] == "I bike to venues and hate crowds after 23:00."

    r2 = client.get("/about-me")
    assert r2.status_code == 200
    assert r2.json()["about_me"] == "I bike to venues and hate crowds after 23:00."
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/api/test_routes_about_me.py::test_about_me_roundtrips_general_text -v`
Expected: FAIL — schema does not have the field yet.

- [ ] **Step 3: Add the field to both schemas**

Modify `backend/app/schemas/about_me.py`:

```python
class AboutMeResponse(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict = Field(default_factory=dict)
    taste_summary: str | None = None
    about_me: str | None = None


class AboutMeUpdate(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict | None = None
    taste_summary: str | None = None
    about_me: str | None = None

    @field_validator("active_categories")
    @classmethod
    def _check_categories(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        unknown = [c for c in v if c not in USER_SELECTABLE_CATEGORIES]
        if unknown:
            raise ValueError(f"unknown categories: {unknown}")
        return v
```

- [ ] **Step 4: Wire `about_me` in `routes_about_me.py`**

Modify `_to_response`:

```python
def _to_response(u: User) -> AboutMeResponse:
    return AboutMeResponse(
        active_categories=u.active_categories,
        taste_facets=dict(u.taste_facets or {}),
        taste_summary=u.taste_summary,
        about_me=u.about_me,
    )
```

And in `update_about_me`, after the `taste_summary` write and before `db.commit()`:

```python
    if payload.about_me is not None:
        u.about_me = payload.about_me
```

- [ ] **Step 5: Run test to verify pass**

Run: `pytest backend/tests/api/test_routes_about_me.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/schemas/about_me.py backend/app/api/routes_about_me.py backend/tests/api/test_routes_about_me.py
git commit -m "feat(about-me): general free-text field roundtrip"
```

---

## Task 6: `get_user_profile` returns the reduced field set

**Files:**
- Modify: `backend/app/agent/tools.py`
- Test: `backend/tests/agent/test_tools_profile.py`

- [ ] **Step 1: Rewrite the profile test**

Overwrite (or add — check the file for the existing profile test and replace it) in `backend/tests/agent/test_tools_profile.py`:

```python
from app.agent.memory import user_id_var
from app.agent.tools import get_user_profile
from app.db.models import User


def test_get_user_profile_returns_new_shape_only(db_session):
    db_session.add(User(
        id="local",
        interest_tags=["legacy"],
        taste_summary="legacy summary",
        about_me="I ride a bike",
        active_categories=["concerts", "party"],
        taste_facets={"concerts": {"artists": {"Nils Frahm": 1.0}}},
    ))
    db_session.commit()

    tok = user_id_var.set("local")
    try:
        result = get_user_profile.invoke({})
    finally:
        user_id_var.reset(tok)

    assert result == {
        "about_me": "I ride a bike",
        "active_categories": ["concerts", "party"],
        "taste_facets": {"concerts": {"artists": {"Nils Frahm": 1.0}}},
    }
    # Legacy fields are dropped from the tool response.
    assert "interest_tags" not in result
    assert "taste_summary" not in result
```

If `user_id_var` is imported under a different name, check `app/agent/memory.py` — the Phase 1 spec calls it `user_id_var` and helper `get_current_user_id`. Use whichever the module exports.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest backend/tests/agent/test_tools_profile.py -v`
Expected: FAIL — the tool still returns `interest_tags` and `taste_summary`.

- [ ] **Step 3: Rewrite `get_user_profile`**

Modify `backend/app/agent/tools.py`. Replace the body of `get_user_profile` with:

```python
@tool
def get_user_profile() -> dict:
    """Return the current user's About Me: general free text, active
    categories, and per-category preferences (facets).

    This is the single source of truth for what the user has told the
    assistant. Legacy fields (interest_tags, taste_summary) are not
    exposed here."""
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")
        return {
            "about_me": user.about_me,
            "active_categories": list(user.active_categories) if user.active_categories is not None else None,
            "taste_facets": dict(user.taste_facets or {}),
        }
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest backend/tests/agent/test_tools_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Sweep for other tests asserting the old shape**

Run: `pytest backend/tests/agent -v -k "profile"`
Expected: green, or failures on tests that assert `interest_tags` / `taste_summary` in the profile response. Update them to reflect the new shape or remove the assertion.

- [ ] **Step 6: Commit**

```
git add backend/app/agent/tools.py backend/tests/agent/test_tools_profile.py
git commit -m "feat(recommender): get_user_profile returns about_me-only shape"
```

---

## Task 7: `CURATION_PROMPT` + digest formatter — drop legacy fields, add taste prose

**Files:**
- Modify: `backend/app/agent/prompts.py`
- Modify: `backend/app/api/routes_digest.py`
- Test: `backend/tests/agent/test_prompts.py`
- Test: `backend/tests/api/test_routes_digest.py`

- [ ] **Step 1: Write / update failing prompt test**

In `backend/tests/agent/test_prompts.py`, add:

```python
def test_curation_prompt_new_placeholders():
    from app.agent.prompts import CURATION_PROMPT

    required = [
        "{about_me}", "{active_categories}", "{inactive_categories}",
        "{taste_prose}", "{event_pool}",
    ]
    for token in required:
        assert token in CURATION_PROMPT, f"missing placeholder: {token}"

    for token in ("{interests}", "{taste_summary}", "{taste_facets_json}", "{disliked_json}"):
        assert token not in CURATION_PROMPT, f"legacy placeholder must be removed: {token}"
```

- [ ] **Step 2: Add the digest formatter helper test**

In `backend/tests/api/test_routes_digest.py`, add:

```python
def test_format_taste_prose_dumps_active_categories_only():
    from app.db.models import User
    from app.api.routes_digest import _format_taste_prose

    user = User(
        id="local",
        active_categories=["concerts", "party"],
        taste_facets={
            "concerts": {"artists": {"Nils Frahm": 1.0}, "genres": {"indie": 1.0}, "venues": {}, "notes": "Piano over guitars"},
            "party":    {"venues":  {"Südpol": 1.0}},
            "theater":  {"venues":  {"Thalia": 1.0}},  # inactive → excluded
        },
    )
    prose = _format_taste_prose(user)
    assert "concerts" in prose
    assert "Nils Frahm" in prose
    assert "Piano over guitars" in prose
    assert "Südpol" in prose
    # Inactive-category facets must not leak in.
    assert "Thalia" not in prose
```

- [ ] **Step 3: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_prompts.py backend/tests/api/test_routes_digest.py -v -k "curation_prompt or format_taste_prose"`
Expected: FAIL — the placeholders are wrong; `_format_taste_prose` does not exist.

- [ ] **Step 4: Rewrite `CURATION_PROMPT`**

Modify `backend/app/agent/prompts.py`. Replace the existing `CURATION_PROMPT` with:

```python
CURATION_PROMPT = """\
You are a Hamburg event concierge picking today's digest for a user.

ABOUT THE USER (single source of truth — the user wrote this):
{about_me}

Active categories: {active_categories}
Deactivated categories (do not proactively suggest): {inactive_categories}

Per-category preferences (verbatim from the user's About Me — no weights):
{taste_prose}

TODAY'S CANDIDATE POOL (JSON):
{event_pool}

Your job: pick 3 to 5 events from the pool that this specific user is most
likely to love today. For each pick, write a 1-2 sentence justification
grounded in the user's About Me and per-category preferences — not generic
praise. When a pick matches a term the user typed (venue, artist, genre),
mention that term in the justification.

Return your final answer in the structured output format.
"""
```

- [ ] **Step 5: Add `_format_taste_prose` and rewire `_generate_digest`**

Modify `backend/app/api/routes_digest.py`.

Add a helper:

```python
def _format_taste_prose(user: User) -> str:
    """Render per-active-category facets as a compact prose block.

    Weights are dropped. Missing fields are omitted. Empty categories
    produce a `(nothing listed)` line so the LLM knows the category is
    active but has no user-typed hints."""
    active = list(user.active_categories or [])
    facets = user.taste_facets or {}
    if not active:
        return "(no active categories)"

    lines: list[str] = []
    for cat in active:
        cat_facets = facets.get(cat) or {}
        cat_lines: list[str] = []
        for field in ("artists", "genres", "venues"):
            bucket = cat_facets.get(field) or {}
            terms = [t for t in bucket.keys() if t]
            if terms:
                cat_lines.append(f"    {field}: {', '.join(terms)}")
        notes = cat_facets.get("notes")
        if isinstance(notes, str) and notes.strip():
            cat_lines.append(f"    notes: {notes.strip()}")
        if not cat_lines:
            cat_lines.append("    (nothing listed)")
        lines.append(f"  {cat}:")
        lines.extend(cat_lines)
    return "\n".join(lines)
```

Replace the `prompt = CURATION_PROMPT.format(...)` block in `_generate_digest` with:

```python
    prompt = CURATION_PROMPT.format(
        about_me=user.about_me or "(nothing written)",
        active_categories=", ".join(user.active_categories) or "(none)",
        inactive_categories=", ".join(inactive) or "(none)",
        taste_prose=_format_taste_prose(user),
        event_pool=json.dumps([_serialise_event_for_prompt(e) for e in pool], indent=2),
    )
```

Delete the now-unused `_extract_disliked` and `_compact_facets` helpers plus their imports if no other consumer references them. Grep the file first — if either is still used elsewhere, leave it.

- [ ] **Step 6: Run tests to verify pass**

Run: `pytest backend/tests/agent/test_prompts.py backend/tests/api/test_routes_digest.py -v`
Expected: all PASS. If existing digest tests break because they asserted the `taste_facets_json` placeholder was populated, update them to assert `taste_prose` instead.

- [ ] **Step 7: Commit**

```
git add backend/app/agent/prompts.py backend/app/api/routes_digest.py backend/tests/agent/test_prompts.py backend/tests/api/test_routes_digest.py
git commit -m "feat(recommender): curation prompt uses About Me prose (drops legacy fields)"
```

---

## Task 8: Frontend types + api client add `about_me`

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Extend the interfaces**

In `frontend/lib/types.ts`, extend the About Me shapes:

```typescript
export interface AboutMeResponse {
  active_categories: string[] | null;
  taste_facets: Partial<Record<EventCategory, CategoryFacets>>;
  taste_summary: string | null;
  about_me: string | null;
}

export interface AboutMeUpdate {
  active_categories?: string[];
  taste_facets?: Partial<Record<EventCategory, CategoryFacets>>;
  taste_summary?: string;
  about_me?: string | null;
}
```

Leave `taste_summary` in the shapes even though the UI will stop rendering it — the backend still returns it, and dropping the field would break the type check.

- [ ] **Step 2: Update the mock branch of the API client**

In `frontend/lib/api.ts`, update `getAboutMe` and `updateAboutMe` mock returns to include `about_me`:

```typescript
export async function getAboutMe(): Promise<AboutMeResponse> {
  if (MOCK) {
    return { active_categories: null, taste_facets: {}, taste_summary: null, about_me: null };
  }
  return jsonFetch<AboutMeResponse>("/about-me");
}

export async function updateAboutMe(body: AboutMeUpdate): Promise<AboutMeResponse> {
  if (MOCK) {
    console.info("[mock] PUT /about-me", body);
    return {
      active_categories: body.active_categories ?? null,
      taste_facets: body.taste_facets ?? {},
      taste_summary: body.taste_summary ?? null,
      about_me: body.about_me ?? null,
    };
  }
  return jsonFetch<AboutMeResponse>("/about-me", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit` (or, keeping cwd stable, run from repo root with `npx --prefix frontend tsc --noEmit`).
Expected: no errors.

- [ ] **Step 4: Commit**

```
git add frontend/lib/types.ts frontend/lib/api.ts
git commit -m "feat(about-me): frontend types + api client for about_me field"
```

---

## Task 9: `ChipInput` component

**Files:**
- Create: `frontend/components/ChipInput.tsx`
- Create: `frontend/components/ChipInput.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/components/ChipInput.test.tsx`:

```typescript
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChipInput from './ChipInput'

function Wrapper({ initial = [] as string[], onChange = () => {} }) {
  return <ChipInput value={initial} onChange={onChange} placeholder="type…" />
}

describe('ChipInput', () => {
  it('commits a chip on Enter', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'the beatles{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['the beatles'])
  })

  it('preserves spaces and commas inside a chip', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'die sterne, hamburg{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['die sterne, hamburg'])
  })

  it('dedupes case-insensitively on commit', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={['Radiohead']} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'radiohead{Enter}')
    // No new chip committed → onChange either not called with a longer array, or called with the same array.
    for (const call of onChange.mock.calls) {
      expect(call[0]).toEqual(['Radiohead'])
    }
  })

  it('ignores empty and whitespace-only commits', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, '   {Enter}')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('removes the last chip on Backspace when input is empty', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={['a', 'b']} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.click(input)
    await userEvent.keyboard('{Backspace}')
    expect(onChange).toHaveBeenLastCalledWith(['a'])
  })

  it('renders existing chips', () => {
    render(<ChipInput value={['a', 'b']} onChange={() => {}} placeholder="type…" />)
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run the test to verify failure**

Run: `cd frontend && npx vitest run components/ChipInput.test.tsx`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the component**

Create `frontend/components/ChipInput.tsx`:

```typescript
'use client'
import { useState, KeyboardEvent } from 'react'

export interface ChipInputProps {
  value: string[]
  onChange: (next: string[]) => void
  placeholder?: string
}

function isDuplicate(existing: string[], candidate: string): boolean {
  const c = candidate.toLowerCase()
  return existing.some((e) => e.toLowerCase() === c)
}

export default function ChipInput({ value, onChange, placeholder }: ChipInputProps) {
  const [draft, setDraft] = useState('')

  function commit(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    if (isDuplicate(value, trimmed)) {
      setDraft('')
      return
    }
    onChange([...value, trimmed])
    setDraft('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      commit(draft)
      return
    }
    if (e.key === 'Backspace' && draft === '' && value.length > 0) {
      e.preventDefault()
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1 rounded border border-border bg-white px-2 py-1 text-[13px]">
      {value.map((chip, idx) => (
        <span
          key={`${chip}-${idx}`}
          className="inline-flex items-center gap-1 rounded bg-bg-page px-2 py-0.5 text-[12px] text-text-primary"
        >
          {chip}
          <button
            type="button"
            aria-label={`remove ${chip}`}
            className="text-text-muted hover:text-text-primary"
            onClick={() => onChange(value.filter((_, i) => i !== idx))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        className="flex-1 min-w-[6ch] border-0 bg-transparent p-0 text-[13px] focus:outline-none"
        placeholder={placeholder}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => commit(draft)}
      />
    </div>
  )
}
```

- [ ] **Step 4: Run the test to verify pass**

Run: `cd frontend && npx vitest run components/ChipInput.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add frontend/components/ChipInput.tsx frontend/components/ChipInput.test.tsx
git commit -m "feat(about-me): ChipInput component for tag-style input"
```

---

## Task 10: Wire `ChipInput` into `CategoryFacetsSection`

**Files:**
- Modify: `frontend/components/CategoryFacetsSection.tsx`
- Modify: `frontend/lib/types.ts` (if `CategoryFacets` needs `string[]` typing — see step 1)

The wire-up here changes what the frontend puts on the wire: instead of a `{term: weight}` dict, the artists/genres/venues fields become a **plain array of terms**. The backend still accepts the old shape for backwards compatibility (see spec §4.3), so we can send arrays without changing the API contract — the store call in `routes_about_me.py` writes `merged[cat] = cat_facets` verbatim, and the retrieval keyword matcher iterates `bucket.keys()`.

But we must handle the read side: when the backend returns an existing dict-shaped facet, `CategoryFacetsSection` must map it to a `string[]` for `ChipInput`.

- [ ] **Step 1: Rewrite `CategoryFacetsSection.tsx`**

Overwrite the file:

```typescript
// frontend/components/CategoryFacetsSection.tsx
'use client'
import ChipInput from './ChipInput'
import type { CategoryDescriptor } from '@/lib/aboutMeCategories'
import type { CategoryFacets } from '@/lib/types'

export interface CategoryFacetsSectionProps {
  descriptor: CategoryDescriptor
  facets: CategoryFacets
  onChange: (next: CategoryFacets) => void
}

/**
 * The backend stores facet buckets as `{term: weight}` dicts for historical
 * reasons. The About Me form treats them as ordered string arrays. These two
 * helpers bridge the shapes for the ChipInput.
 */
function bucketToArray(bucket: unknown): string[] {
  if (Array.isArray(bucket)) return bucket.filter((v): v is string => typeof v === 'string' && v.trim() !== '')
  if (bucket && typeof bucket === 'object') return Object.keys(bucket as Record<string, unknown>).filter((k) => k.trim() !== '')
  return []
}

function arrayToBucket(arr: string[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const term of arr) {
    const key = term.trim()
    if (!key) continue
    // Weight is retained on-disk for schema compatibility but has no consumer.
    out[key] = 1.0
  }
  return out
}

export default function CategoryFacetsSection({ descriptor, facets, onChange }: CategoryFacetsSectionProps) {
  return (
    <section className="rounded-lg border border-border bg-white p-4">
      <h3 className="font-serif font-bold text-[15px] text-text-primary mb-3">
        {descriptor.displayName}
      </h3>
      <div className="flex flex-col gap-3">
        {descriptor.fields.map((f) => (
          <label key={f.label} className="flex flex-col gap-1">
            <span className="text-[12px] font-semibold text-text-primary">{f.label}</span>
            {f.helper ? (
              <span className="text-[11px] text-text-muted">{f.helper}</span>
            ) : null}
            {f.facetField === 'notes' ? (
              <textarea
                className="rounded border border-border px-2 py-1 text-[13px]"
                rows={3}
                value={facets.notes ?? ''}
                onChange={(e) => onChange({ ...facets, notes: e.target.value })}
              />
            ) : (
              <ChipInput
                value={bucketToArray(facets[f.facetField])}
                onChange={(next) => onChange({ ...facets, [f.facetField]: arrayToBucket(next) })}
                placeholder="type and press Enter"
              />
            )}
          </label>
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Update the helper text in `aboutMeCategories.ts` where obsolete**

In `frontend/lib/aboutMeCategories.ts`, remove or update helper texts that say "Comma-separated" or "e.g. punk, indie, jazz" — they are now misleading. Suggested replacements:

- `"Comma-separated"` → remove the field entirely from `helper` (chip UI is self-explanatory).
- `"e.g. punk, indie, jazz"` → `"e.g. punk / indie / jazz"` or drop.
- `"e.g. techno, house, drum'n'bass"` → `"e.g. techno / house / drum'n'bass"` or drop.
- `"Stand-up, Kabarett, Improv..."` → keep (users still benefit from format examples; it's not an input format hint).
- Similar for other `e.g.` helpers that contain commas — swap `,` to `/` where the goal is to list examples.

- [ ] **Step 4: Vitest sanity check**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add frontend/components/CategoryFacetsSection.tsx frontend/lib/aboutMeCategories.ts
git commit -m "feat(about-me): chip inputs for artists/genres/venues"
```

---

## Task 11: About Me page — General textarea, remove "learned about you" section

**Files:**
- Modify: `frontend/app/about-me/page.tsx`

- [ ] **Step 1: Update the page**

Overwrite `frontend/app/about-me/page.tsx`:

```typescript
// frontend/app/about-me/page.tsx
'use client'
import { useEffect, useMemo, useState } from 'react'
import useSWR, { useSWRConfig } from 'swr'
import CategoryFacetsSection from '@/components/CategoryFacetsSection'
import { getAboutMe, updateAboutMe } from '@/lib/api'
import { CATEGORY_DESCRIPTORS, SELECTABLE_CATEGORIES } from '@/lib/aboutMeCategories'
import type { AboutMeResponse, CategoryFacets, EventCategory } from '@/lib/types'

export default function AboutMePage() {
  const { mutate } = useSWRConfig()
  const { data, isLoading } = useSWR<AboutMeResponse>('/about-me', getAboutMe)

  const [active, setActive] = useState<EventCategory[]>([])
  const [facets, setFacets] = useState<Partial<Record<EventCategory, CategoryFacets>>>({})
  const [aboutMe, setAboutMe] = useState<string>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!data) return
    setActive((data.active_categories ?? []) as EventCategory[])
    setFacets(data.taste_facets ?? {})
    setAboutMe(data.about_me ?? '')
  }, [data])

  const isFirstVisit = data?.active_categories === null

  function toggleCategory(cat: EventCategory) {
    setActive((prev) => (prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]))
  }

  function updateFacetsFor(cat: EventCategory, next: CategoryFacets) {
    setFacets((prev) => ({ ...prev, [cat]: next }))
  }

  async function onSave() {
    setSaving(true)
    try {
      const updated = await updateAboutMe({
        active_categories: active,
        taste_facets: facets,
        about_me: aboutMe,
      })
      mutate('/about-me', updated, { revalidate: false })
    } finally {
      setSaving(false)
    }
  }

  const sortedActive = useMemo(
    () => SELECTABLE_CATEGORIES.filter((c) => active.includes(c)),
    [active],
  )

  return (
    <main className="flex-1 overflow-y-auto px-6 py-6 bg-bg-page">
      <h1 className="font-serif font-bold text-lg text-text-primary mb-1">About Me</h1>
      <p className="text-[12px] text-text-muted mb-4">
        Tell the assistant which categories interest you and what you like in each.
        You can update this at any time.
      </p>
      {isFirstVisit ? (
        <div className="mb-4 rounded border border-accent-gold bg-white p-3 text-[12px] text-text-primary">
          Before the assistant can suggest anything, pick at least one category below.
        </div>
      ) : null}

      {isLoading || !data ? (
        <p className="text-[12px] text-text-muted">Loading…</p>
      ) : (
        <div className="flex flex-col gap-4 max-w-2xl">
          <section className="rounded-lg border border-border bg-white p-4">
            <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">
              Categories
            </h2>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {SELECTABLE_CATEGORIES.map((cat) => (
                <label key={cat} className="flex items-center gap-2 text-[13px] text-text-primary">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-accent-gold"
                    checked={active.includes(cat)}
                    onChange={() => toggleCategory(cat)}
                  />
                  {CATEGORY_DESCRIPTORS[cat].displayName}
                </label>
              ))}
            </div>
          </section>

          <section className="rounded-lg border border-border bg-white p-4">
            <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">
              General
            </h2>
            <p className="text-[11px] text-text-muted mb-2">
              Anything the assistant should know that isn't category-specific.
            </p>
            <textarea
              className="w-full rounded border border-border px-2 py-1 text-[13px]"
              rows={6}
              value={aboutMe}
              onChange={(e) => setAboutMe(e.target.value)}
            />
          </section>

          {sortedActive.map((cat) => (
            <CategoryFacetsSection
              key={cat}
              descriptor={CATEGORY_DESCRIPTORS[cat]}
              facets={facets[cat] ?? {}}
              onChange={(next) => updateFacetsFor(cat, next)}
            />
          ))}

          <div className="flex gap-2">
            <button
              onClick={onSave}
              disabled={saving}
              className="rounded bg-accent-gold px-4 py-2 text-[13px] font-semibold text-bg-page disabled:opacity-60"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </main>
  )
}
```

Changes vs. today:
- New "General" section with a 6-row textarea bound to `aboutMe` → sent as `about_me` in the payload.
- The "What the assistant has learned about you" section is gone.
- `tasteSummary` state removed.
- Save payload no longer includes `taste_summary`.

- [ ] **Step 2: Type-check + build**

Run: `cd frontend && npx tsc --noEmit`
Then: `cd frontend && npx next build`
Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/app/about-me/page.tsx
git commit -m "feat(about-me): general free-text section; remove learned-about-you"
```

---

## Task 12: Chroma backfill operator script

**Files:**
- Create: `backend/scripts/embed_events.py`

- [ ] **Step 1: Write the script**

Create `backend/scripts/embed_events.py`:

```python
"""One-shot backfill: (re)populate Chroma from the current visible events.

Wraps `app.ingestion.scheduler.embed_new_events` in an owned DB session so
operators can run it independently of the nightly ingestion cron. Idempotent
— safe to re-run: upserts by event id and drops stale ids."""
import logging

from app.db.session import SessionLocal
from app.ingestion.scheduler import embed_new_events
from app.rag import chroma_store

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("embed_events")


def main() -> None:
    body: dict = {}
    with SessionLocal() as session:
        embed_new_events(session, body=body)
        session.commit()
    logger.info(
        "backfill complete: upserted=%s purged=%s total_in_chroma=%s",
        body.get("upserted"),
        body.get("purged"),
        chroma_store._get_collection().count(),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run**

Run: `cd backend && python -m scripts.embed_events`
Expected: exits 0 with a log line reporting `upserted=<N>` and `total_in_chroma=<N>` where `N > 0` (assuming the DB has visible events).

- [ ] **Step 3: Confirm Chroma is populated**

Run: `cd backend && python -c "from app.rag.chroma_store import _get_collection; print(_get_collection().count())"`
Expected: a positive integer matching the log above.

- [ ] **Step 4: Commit**

```
git add backend/scripts/embed_events.py
git commit -m "feat(recommender): operator script to backfill Chroma from visible events"
```

---

## Task 13: End-to-end verification

- [ ] **Step 1: Full backend test suite**

Run: `pytest backend/tests -q`
Expected: 100% pass. If any test fails because it patched `_build_cold_start_seed`, `embed_one`, `_extract_disliked`, or `_compact_facets` — those helpers are gone, adapt or delete the test.

- [ ] **Step 2: Frontend type-check + tests + build**

Run: `cd frontend && npx tsc --noEmit`
Run: `cd frontend && npx vitest run`
Run: `cd frontend && npx next build`
Expected: no errors.

- [ ] **Step 3: Start both services**

Run backend: `cd backend && uvicorn app.main:app --reload`
Run frontend: `cd frontend && npm run dev`

- [ ] **Step 4: Browser smoke test**

1. Open `http://localhost:3000/about-me`.
2. Confirm the **"What the assistant has learned about you"** section is gone.
3. Confirm a new **"General"** section is visible with a large textarea.
4. Type into General: `I bike to venues and hate crowds after 23:00.` — hit Save.
5. Reload — the text persists.
6. Under Concerts → Favourite artists, type `nils frahm` (spaces allowed) and press Enter — a chip appears. Type `radiohead` Enter — second chip. Try `RADIOHEAD` Enter — no new chip (case-insensitive dedup). Type `die sterne, hamburg` Enter — a chip with the comma in it. Save.
7. Reload — chips persist.
8. Navigate to Timetable — digest must return picks (not 503). If empty and no events available for the range, confirm the pool via `python -c "from app.db.session import SessionLocal; from app.db.models import Event; s = SessionLocal(); print(s.query(Event).filter(Event.category=='concerts').count())"`.
9. Go to Chat. Ask `what do you know about me?` — the assistant should reference the General text and per-category chips. It should **not** mention `interests` or `taste_summary`.
10. Ask `Recommend me concerts next week` — the response must include events. If Chroma was populated in Task 12, `nils frahm` matches should surface even before any saves.

- [ ] **Step 5: Final commit and status check**

Run: `git status`
Expected: clean working tree. If any test-only cleanup was left uncommitted, stage and commit it with a descriptive message.

---

## Rollback

Each task is a single logical commit, so `git revert <sha>` in reverse task order rolls back cleanly.

Feature-flag rollback (fastest):
- Re-enable comment extractor: `COMMENT_EXTRACTOR_ENABLED=true` in `.env`.
- Re-enable dislike hard-filter: restore the original body of `filter_out_disliked` (kept adjacent to the pass-through in `retrieval.py`, one-line diff).

---

## Non-goals reminder (from the spec)

- No umlaut normalization at query time.
- No fuzzy/typo tolerance on user-typed terms.
- No genre-tagging events.
- No dislike UI in About Me.
- No schema changes — all fields already exist.
- No retirement of `interest_tags` / `taste_summary` columns.
