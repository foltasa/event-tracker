# Recommender Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-centroid recommender with a per-category taste model (centroids + structured facets), a comment-extractor pipeline, dislike-aware retrieval, and a persistent About-Me page as the user-facing knowledge editor.

**Architecture:** New `taste_centroids`, `taste_facets`, `active_categories` fields on `User`. Signal weighting: save = 2.0, like = 1.0, dislike = extractor-only. Retrieval loops per active category with hard substring-filter for disliked terms. Ranking stays LLM-driven via structured output but with facets and inactive-categories injected. About Me is a new page with category checkboxes and per-category forms.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + Chroma; Pydantic structured LLM output via LangChain; Next.js 14 App Router + SWR + Tailwind.

**Spec:** `docs/specs/2026-07-10-recommender-phase1-design.md`

---

## File Structure

### Files created

Backend:
- `backend/app/agent/categories.py` — vocabulary constant module (CATEGORIES, USER_SELECTABLE_CATEGORIES)
- `backend/app/agent/comment_extractor.py` — LLM extractor turning comments into facet updates
- `backend/app/agent/facets.py` — pure helpers to apply facet deltas (clamp + prune)
- `backend/app/agent/retrieval.py` — per-category candidate retrieval + disliked-substring filter
- `backend/app/api/routes_about_me.py` — GET/PUT `/about-me`
- `backend/app/schemas/about_me.py` — `AboutMeResponse`, `AboutMeUpdate`, `CategoryFacets`
- `backend/app/db/migrations/versions/0006_taste_per_category.py` — schema migration + backfill
- `backend/tests/agent/test_categories.py`
- `backend/tests/agent/test_facets.py`
- `backend/tests/agent/test_comment_extractor.py`
- `backend/tests/agent/test_retrieval.py`
- `backend/tests/agent/test_memory_refresh.py`
- `backend/tests/api/test_routes_about_me.py`
- `backend/tests/api/test_routes_feedback_extractor.py`

Frontend:
- `frontend/app/about-me/page.tsx` — About Me page (checkboxes + per-category sections)
- `frontend/components/CategoryFacetsSection.tsx` — reusable per-category form section
- `frontend/lib/aboutMeCategories.ts` — per-category form field descriptors

### Files modified

Backend:
- `backend/app/db/models/user.py` — new columns
- `backend/app/agent/memory.py` — replace `refresh_taste_centroid` with `refresh_taste_centroids`
- `backend/app/agent/tools.py` — `get_recommendations` (category param, active_categories, no_active_categories error); `get_user_profile` (return active_categories + facets); wire refresh in `save_to_calendar`
- `backend/app/api/routes_feedback.py` — BackgroundTasks for extractor, refresh on save/like/dislike
- `backend/app/api/routes_calendar.py` — refresh after save/unsave
- `backend/app/api/routes_digest.py` — per-category candidate pool + disliked filter + extended prompt
- `backend/app/agent/prompts.py` — CURATION_PROMPT gains facets + active/inactive categories
- `backend/app/main.py` — include `routes_about_me.router`
- `backend/app/db/migrations/versions/__init__.py` — none; alembic auto-detects

Frontend:
- `frontend/lib/types.ts` — `CategoryFacets`, `AboutMeResponse`, `AboutMeUpdate`
- `frontend/lib/api.ts` — `getAboutMe`, `updateAboutMe`
- `frontend/components/TopNav.tsx` — add About Me link + type widening
- `frontend/components/AppShell.tsx` — redirect to `/about-me` when `active_categories === null`

---

## Conventions

- Commit style: `feat(area): subject`, `fix(area): subject`, `docs(specs|plans): subject`. Match the recent log (see `git log --oneline -20`).
- Never chain shell commands with `&&` or `;` when each is already allowed under `Bash(git:*)`; run them as separate calls.
- All code comments in English (repo-wide rule in `CLAUDE.md`).
- Tests use the existing `conftest.py` `db_session` and `client` fixtures.
- LLM calls in tests are mocked at the `llm` boundary — never make real network calls in tests.

---

## Task 1: Category vocabulary module

**Files:**
- Create: `backend/app/agent/categories.py`
- Test: `backend/tests/agent/test_categories.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_categories.py
from app.agent.categories import CATEGORIES, USER_SELECTABLE_CATEGORIES


def test_categories_contain_expected_top_level():
    for expected in [
        "concerts", "party", "comedy", "theater", "arts", "literature",
        "film", "family", "food", "sports", "outdoor",
    ]:
        assert expected in CATEGORIES


def test_categories_include_classifier_fallbacks():
    assert "other" in CATEGORIES
    assert "unknown" in CATEGORIES


def test_user_selectable_excludes_fallbacks():
    assert "other" not in USER_SELECTABLE_CATEGORIES
    assert "unknown" not in USER_SELECTABLE_CATEGORIES
    for c in USER_SELECTABLE_CATEGORIES:
        assert c in CATEGORIES
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest backend/tests/agent/test_categories.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement module**

```python
# backend/app/agent/categories.py
"""Canonical category vocabulary for the recommender.

Kept separate from `app/ingestion/categorize_prompts.py` because the
recommender needs a stable Python constant it can iterate. If the
classifier vocabulary ever changes, update BOTH files."""

CATEGORIES: list[str] = [
    "concerts", "party", "comedy", "theater", "arts", "literature",
    "film", "family", "food", "sports", "outdoor", "other", "unknown",
]

# User-selectable in About Me. Excludes classifier fallbacks.
USER_SELECTABLE_CATEGORIES: list[str] = [
    c for c in CATEGORIES if c not in ("other", "unknown")
]
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest backend/tests/agent/test_categories.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/categories.py backend/tests/agent/test_categories.py
git commit -m "feat(recommender): categories vocabulary module"
```

---

## Task 2: Alembic migration 0006 — schema for per-category taste

**Files:**
- Create: `backend/app/db/migrations/versions/0006_taste_per_category.py`
- Modify: `backend/app/db/models/user.py`
- Test: `backend/tests/db/test_user.py` (extend)

- [ ] **Step 1: Extend failing test**

Add to `backend/tests/db/test_user.py`:

```python
def test_user_new_taste_columns_defaults(db_session):
    from app.db.models import User
    u = User(id="alice")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    assert u.taste_centroids == {}
    assert u.taste_facets == {}
    assert u.active_categories is None


def test_user_can_persist_taste_centroids_and_facets(db_session):
    from app.db.models import User
    u = User(
        id="bob",
        taste_centroids={"concerts": [0.1, 0.2, 0.3]},
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.9}}},
        active_categories=["concerts", "party"],
    )
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    assert u.taste_centroids["concerts"] == [0.1, 0.2, 0.3]
    assert u.taste_facets["concerts"]["artists"]["Die Sterne"] == 0.9
    assert u.active_categories == ["concerts", "party"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/db/test_user.py -v`
Expected: FAIL (columns missing).

- [ ] **Step 3: Update User model**

Modify `backend/app/db/models/user.py` — add these columns after `taste_centroid`:

```python
    taste_centroids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    taste_facets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active_categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
```

- [ ] **Step 4: Write Alembic migration**

```python
# backend/app/db/migrations/versions/0006_taste_per_category.py
"""taste per category

Revision ID: 0006_taste_per_category
Revises: 0005_saved_event_kind
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_taste_per_category"
down_revision: Union[str, Sequence[str], None] = "0005_saved_event_kind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("taste_centroids", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column("taste_facets", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "users",
        sa.Column("active_categories", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "active_categories")
    op.drop_column("users", "taste_facets")
    op.drop_column("users", "taste_centroids")
```

- [ ] **Step 5: Verify tests pass**

Run: `pytest backend/tests/db/test_user.py -v`
Expected: PASS.

- [ ] **Step 6: Verify migration runs cleanly**

Run: `python -c "from app.db import run_migrations; run_migrations()"` from `backend/`.
Expected: no error.

- [ ] **Step 7: Commit**

```
git add backend/app/db/models/user.py backend/app/db/migrations/versions/0006_taste_per_category.py backend/tests/db/test_user.py
git commit -m "feat(recommender): per-category taste schema + migration"
```

---

## Task 3: Facet helpers (pure functions)

**Files:**
- Create: `backend/app/agent/facets.py`
- Test: `backend/tests/agent/test_facets.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_facets.py
from app.agent.facets import apply_facet_delta, initial_from_form


def test_apply_facet_delta_increments_and_clamps_at_one():
    facets = {"concerts": {"artists": {"Die Sterne": 0.8}}}
    apply_facet_delta(facets, "concerts", "artists", "Die Sterne", 0.5)
    assert facets["concerts"]["artists"]["Die Sterne"] == 1.0


def test_apply_facet_delta_creates_missing_structure():
    facets = {}
    apply_facet_delta(facets, "party", "genres", "techno", 0.4)
    assert facets["party"]["genres"]["techno"] == 0.4


def test_apply_facet_delta_prunes_when_reaches_zero_or_below():
    facets = {"concerts": {"disliked.genres": {"edm": 0.3}}}
    apply_facet_delta(facets, "concerts", "disliked.genres", "edm", -0.5)
    assert "edm" not in facets["concerts"]["disliked.genres"]


def test_apply_facet_delta_leaves_other_fields_untouched():
    facets = {"concerts": {"artists": {"A": 0.5}, "genres": {"punk": 0.7}}}
    apply_facet_delta(facets, "concerts", "artists", "B", 0.6)
    assert facets["concerts"]["genres"]["punk"] == 0.7


def test_initial_from_form_uses_default_weight():
    out = initial_from_form(["Die Sterne", "Tocotronic"], weight=0.8)
    assert out == {"Die Sterne": 0.8, "Tocotronic": 0.8}


def test_initial_from_form_strips_whitespace_and_drops_empties():
    out = initial_from_form([" Die Sterne ", "", "  ", "Interpol"], weight=0.8)
    assert out == {"Die Sterne": 0.8, "Interpol": 0.8}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_facets.py -v`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement helpers**

```python
# backend/app/agent/facets.py
"""Pure helpers for the taste_facets JSON blob.

Kept side-effect-free so tests don't need a DB session and so both the
comment extractor and the About Me form save path can reuse them."""


def _ensure_path(facets: dict, category: str, field: str) -> dict:
    cat = facets.setdefault(category, {})
    bucket = cat.setdefault(field, {})
    return bucket


def apply_facet_delta(
    facets: dict,
    category: str,
    field: str,
    key: str,
    delta: float,
) -> None:
    """Add `delta` to facets[category][field][key], clamped to [0.0, 1.0].

    If the resulting value is <= 0, the key is removed to keep the blob
    lean. Missing intermediate structure is created on the fly."""
    bucket = _ensure_path(facets, category, field)
    current = float(bucket.get(key, 0.0))
    new_value = current + delta
    if new_value <= 0.0:
        bucket.pop(key, None)
        return
    if new_value > 1.0:
        new_value = 1.0
    bucket[key] = new_value


def initial_from_form(values: list[str], weight: float) -> dict[str, float]:
    """Turn a comma-separated form field into a {key: weight} dict.

    Trims whitespace, drops empty entries, deduplicates."""
    out: dict[str, float] = {}
    for v in values:
        key = (v or "").strip()
        if not key:
            continue
        out[key] = weight
    return out
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest backend/tests/agent/test_facets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/facets.py backend/tests/agent/test_facets.py
git commit -m "feat(recommender): facet delta + form helpers"
```

---

## Task 4: Per-category centroid refresh

**Files:**
- Modify: `backend/app/agent/memory.py`
- Test: `backend/tests/agent/test_memory_refresh.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/test_memory_refresh.py
import uuid
from unittest.mock import patch

import pytest

from app.db.models import Event, Feedback, SavedEvent, User


def _make_event(cat: str, ev_id: str, when="2026-06-01T00:00:00+00:00") -> Event:
    from datetime import datetime
    return Event(
        id=ev_id, external_id=ev_id, source="test",
        title=f"{cat} {ev_id}", description=f"desc {ev_id}",
        start_datetime=datetime.fromisoformat(when),
        category=cat, tags=[], source_url=f"http://e/{ev_id}",
        raw_data={},
    )


def _seed_user(db, user_id="alice", active=None):
    u = User(id=user_id, active_categories=active)
    db.add(u)
    db.flush()
    return u


def test_refresh_taste_centroids_per_category(db_session):
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e1 = _make_event("concerts", "e1")
    e2 = _make_event("party", "e2")
    db_session.add_all([e1, e2])
    db_session.add_all([
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e1", sentiment="like"),
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e2", sentiment="like"),
    ])
    db_session.commit()

    fake_embeddings = {"e1": [1.0, 0.0], "e2": [0.0, 1.0]}
    with patch("app.agent.memory.get_embeddings_for_ids", return_value=fake_embeddings):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert u.taste_centroids["concerts"] == [1.0, 0.0]
    assert u.taste_centroids["party"] == [0.0, 1.0]
    # Fallback global centroid is the mean of category centroids.
    assert u.taste_centroid == [0.5, 0.5]


def test_saved_events_weighted_double_over_likes(db_session):
    """A save-only event pulls the centroid twice as strongly as a like-only event."""
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e_like = _make_event("concerts", "e_like")
    e_save = _make_event("concerts", "e_save")
    db_session.add_all([e_like, e_save])
    db_session.add(Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e_like", sentiment="like"))
    db_session.add(SavedEvent(id=str(uuid.uuid4()), user_id="alice", event_id="e_save"))
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e_like": [1.0, 0.0], "e_save": [0.0, 1.0]},
    ):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    concerts = u.taste_centroids["concerts"]
    # Save weight 2.0, like weight 1.0 → (1*1 + 2*0)/3 = 1/3, (1*0 + 2*1)/3 = 2/3.
    assert concerts[0] == pytest.approx(1 / 3, abs=1e-6)
    assert concerts[1] == pytest.approx(2 / 3, abs=1e-6)


def test_dislikes_do_not_affect_centroid(db_session):
    from app.agent.memory import refresh_taste_centroids

    _seed_user(db_session)
    e1 = _make_event("concerts", "e1")
    e2 = _make_event("concerts", "e2")
    db_session.add_all([e1, e2])
    db_session.add_all([
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e1", sentiment="like"),
        Feedback(id=str(uuid.uuid4()), user_id="alice", event_id="e2", sentiment="dislike"),
    ])
    db_session.commit()

    with patch(
        "app.agent.memory.get_embeddings_for_ids",
        return_value={"e1": [1.0, 0.0], "e2": [0.0, 1.0]},
    ):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert u.taste_centroids["concerts"] == [1.0, 0.0]


def test_no_positive_signal_clears_category(db_session):
    from app.agent.memory import refresh_taste_centroids

    u = _seed_user(db_session)
    u.taste_centroids = {"concerts": [0.9, 0.1]}
    db_session.commit()

    with patch("app.agent.memory.get_embeddings_for_ids", return_value={}):
        refresh_taste_centroids(db_session, "alice")

    u = db_session.query(User).filter_by(id="alice").one()
    assert "concerts" not in u.taste_centroids
    assert u.taste_centroid is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_memory_refresh.py -v`
Expected: FAIL (`refresh_taste_centroids` missing).

- [ ] **Step 3: Rewrite `memory.py`**

Replace `refresh_taste_centroid` in `backend/app/agent/memory.py` with:

```python
def refresh_taste_centroids(session: Session, user_id: str) -> None:
    """Recompute per-category centroids and the global fallback centroid.

    Positive signals:
      like               → weight 1.0
      saved_to_calendar  → weight 2.0
    An event with both like and save gets the max (2.0), not the sum.
    Dislikes never contribute.
    """
    from app.agent.categories import CATEGORIES
    from app.db.models import Event, SavedEvent

    liked_rows = (
        session.query(Feedback.event_id, Event.category)
        .join(Event, Event.id == Feedback.event_id)
        .filter(Feedback.user_id == user_id, Feedback.sentiment == "like")
        .all()
    )
    saved_rows = (
        session.query(SavedEvent.event_id, Event.category)
        .join(Event, Event.id == SavedEvent.event_id)
        .filter(SavedEvent.user_id == user_id)
        .all()
    )

    # (event_id → (category, weight))
    per_event: dict[str, tuple[str, float]] = {}
    for eid, cat in liked_rows:
        per_event[eid] = (cat, 1.0)
    for eid, cat in saved_rows:
        # Save dominates like.
        per_event[eid] = (cat, 2.0)

    user = session.query(User).filter_by(id=user_id).one()
    if not per_event:
        user.taste_centroids = {}
        user.taste_centroid = None
        session.flush()
        return

    embeddings = get_embeddings_for_ids(list(per_event.keys()))
    if not embeddings:
        user.taste_centroids = {}
        user.taste_centroid = None
        session.flush()
        return

    # Group by category, weighted mean per group.
    per_cat_vecs: dict[str, list[np.ndarray]] = {}
    per_cat_wts: dict[str, list[float]] = {}
    for eid, (cat, w) in per_event.items():
        vec = embeddings.get(eid)
        if vec is None:
            continue
        per_cat_vecs.setdefault(cat, []).append(np.array(vec, dtype=np.float32))
        per_cat_wts.setdefault(cat, []).append(w)

    taste_centroids: dict[str, list[float]] = {}
    for cat, vecs in per_cat_vecs.items():
        weights = np.array(per_cat_wts[cat], dtype=np.float32)
        matrix = np.stack(vecs)
        weighted = np.average(matrix, axis=0, weights=weights)
        taste_centroids[cat] = weighted.tolist()

    user.taste_centroids = taste_centroids

    if taste_centroids:
        stacked = np.stack([np.array(v, dtype=np.float32) for v in taste_centroids.values()])
        user.taste_centroid = stacked.mean(axis=0).tolist()
    else:
        user.taste_centroid = None
    session.flush()


# Compatibility alias kept so old imports don't break during the migration
# transition. New code MUST call refresh_taste_centroids.
refresh_taste_centroid = refresh_taste_centroids
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest backend/tests/agent/test_memory_refresh.py -v`
Expected: PASS.

- [ ] **Step 5: Run full backend test suite to catch regressions**

Run: `pytest backend/tests -x -q`
Expected: no new failures. Existing `refresh_taste_centroid` callers still work via the alias.

- [ ] **Step 6: Commit**

```
git add backend/app/agent/memory.py backend/tests/agent/test_memory_refresh.py
git commit -m "feat(recommender): per-category weighted centroid refresh"
```

---

## Task 5: Wire refresh into save-to-calendar and feedback-delete paths

**Files:**
- Modify: `backend/app/api/routes_feedback.py`
- Modify: `backend/app/api/routes_calendar.py`
- Modify: `backend/app/agent/tools.py` (the `save_to_calendar` tool)
- Test: `backend/tests/api/test_routes_feedback_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/api/test_routes_feedback_extractor.py
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _seed_event(db, ev_id="e1", cat="concerts"):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title="t", description="d",
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=[], source_url="http://e",
        raw_data={},
    )
    db.add(e)
    return e


def test_dislike_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.refresh_taste_centroids") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "dislike", "comment": None},
        )
    assert res.status_code == 200
    m.assert_called_once()


def test_save_to_calendar_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_calendar.refresh_taste_centroids") as m:
        res = client.post("/calendar", json={"event_id": "e1"})
    assert res.status_code == 200
    m.assert_called_once()


def test_calendar_delete_triggers_centroid_refresh(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()
    client.post("/calendar", json={"event_id": "e1"})

    with patch("app.api.routes_calendar.refresh_taste_centroids") as m:
        res = client.delete("/calendar/e1")
    assert res.status_code == 204
    m.assert_called_once()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py -v`
Expected: FAIL (dislike branch missing; calendar routes don't call refresh).

- [ ] **Step 3: Update `routes_feedback.py`**

Replace the `if payload.sentiment == "like":` block with an unconditional refresh (any state change may affect the centroid via a new save/like/dislike transition):

```python
    from app.agent.memory import refresh_taste_centroids

    db.commit()
    db.refresh(fb)

    refresh_taste_centroids(db, user_id)
    db.commit()
```

Update the import at top:

```python
from app.agent.memory import get_current_user_id, refresh_taste_centroids
```

Update `delete_feedback` similarly — always call `refresh_taste_centroids` after delete (idempotent).

- [ ] **Step 4: Update `routes_calendar.py`**

Add import:

```python
from app.agent.memory import refresh_taste_centroids
```

After the `save_to_calendar` write, before returning, call:

```python
        refresh_taste_centroids(db, user_id)
        db.commit()
```

Same after `unsave` deletes a row (even in the "nothing to delete" branch is fine to skip).

- [ ] **Step 5: Update `save_to_calendar` tool in `tools.py`**

In `backend/app/agent/tools.py`, at the end of the `save_to_calendar` tool, add:

```python
        refresh_taste_centroids(session, user_id)
        session.commit()
```

Also import: `from app.agent.memory import get_current_user_id, refresh_taste_centroids`.

- [ ] **Step 6: Run tests**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py backend/tests/api backend/tests/agent -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```
git add backend/app/api/routes_feedback.py backend/app/api/routes_calendar.py backend/app/agent/tools.py backend/tests/api/test_routes_feedback_extractor.py
git commit -m "feat(recommender): refresh centroids on all signal changes"
```

---

## Task 6: About-Me Pydantic schemas

**Files:**
- Create: `backend/app/schemas/about_me.py`
- Test: `backend/tests/schemas/test_about_me.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/schemas/test_about_me.py
import pytest
from pydantic import ValidationError


def test_about_me_response_shape():
    from app.schemas.about_me import AboutMeResponse
    resp = AboutMeResponse(
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.8}}},
        taste_summary="likes indie rock",
    )
    assert resp.model_dump()["active_categories"] == ["concerts"]


def test_about_me_update_rejects_unknown_category():
    from app.schemas.about_me import AboutMeUpdate
    with pytest.raises(ValidationError):
        AboutMeUpdate(active_categories=["nonsense"])


def test_about_me_update_partial_is_allowed():
    from app.schemas.about_me import AboutMeUpdate
    u = AboutMeUpdate(taste_summary="new")
    assert u.active_categories is None
    assert u.taste_facets is None
    assert u.taste_summary == "new"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest backend/tests/schemas/test_about_me.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement schemas**

```python
# backend/app/schemas/about_me.py
"""API contracts for the About Me page."""
from pydantic import Field, field_validator

from app.agent.categories import USER_SELECTABLE_CATEGORIES
from app.schemas.common import _JsonBase


class AboutMeResponse(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict = Field(default_factory=dict)
    taste_summary: str | None = None


class AboutMeUpdate(_JsonBase):
    active_categories: list[str] | None = None
    taste_facets: dict | None = None
    taste_summary: str | None = None

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

- [ ] **Step 4: Run test to verify pass**

Run: `pytest backend/tests/schemas/test_about_me.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/schemas/about_me.py backend/tests/schemas/test_about_me.py
git commit -m "feat(recommender): about-me API schemas"
```

---

## Task 7: About-Me API routes

**Files:**
- Create: `backend/app/api/routes_about_me.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/api/test_routes_about_me.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/api/test_routes_about_me.py
from app.db.models import User


def _seed(db, **kwargs):
    u = User(id="local", **kwargs)
    db.add(u)
    db.commit()
    return u


def test_get_about_me_returns_defaults_for_fresh_user(client, db_session):
    _seed(db_session)
    res = client.get("/about-me")
    assert res.status_code == 200
    body = res.json()
    assert body["active_categories"] is None
    assert body["taste_facets"] == {}
    assert body["taste_summary"] is None


def test_put_about_me_activates_categories_and_sets_facets(client, db_session):
    _seed(db_session)
    payload = {
        "active_categories": ["concerts", "theater"],
        "taste_facets": {
            "concerts": {"artists": {"Die Sterne": 0.8}, "genres": {"punk": 0.8}},
        },
        "taste_summary": "prefers small venues",
    }
    res = client.put("/about-me", json=payload)
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts", "theater"]
    assert u.taste_facets["concerts"]["artists"]["Die Sterne"] == 0.8
    assert u.taste_summary == "prefers small venues"


def test_put_about_me_rejects_unknown_category(client, db_session):
    _seed(db_session)
    res = client.put("/about-me", json={"active_categories": ["nonsense"]})
    assert res.status_code == 422


def test_put_about_me_preserves_omitted_fields(client, db_session):
    _seed(
        db_session,
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"A": 0.5}}},
        taste_summary="old",
    )
    res = client.put("/about-me", json={"taste_summary": "new"})
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts"]
    assert u.taste_facets == {"concerts": {"artists": {"A": 0.5}}}
    assert u.taste_summary == "new"


def test_deselecting_a_category_preserves_its_facets(client, db_session):
    _seed(
        db_session,
        active_categories=["concerts", "theater"],
        taste_facets={
            "concerts": {"artists": {"Die Sterne": 0.8}},
            "theater": {"venues": {"Thalia": 0.8}},
        },
    )
    res = client.put("/about-me", json={"active_categories": ["concerts"]})
    assert res.status_code == 200
    u = db_session.query(User).filter_by(id="local").one()
    assert u.active_categories == ["concerts"]
    # Deselected category's facets stay in the DB.
    assert u.taste_facets["theater"]["venues"]["Thalia"] == 0.8
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/api/test_routes_about_me.py -v`
Expected: FAIL (routes not registered).

- [ ] **Step 3: Implement routes**

```python
# backend/app/api/routes_about_me.py
from fastapi import APIRouter, HTTPException

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import User
from app.schemas.about_me import AboutMeResponse, AboutMeUpdate

router = APIRouter(prefix="/about-me", tags=["about-me"])


def _to_response(u: User) -> AboutMeResponse:
    return AboutMeResponse(
        active_categories=u.active_categories,
        taste_facets=dict(u.taste_facets or {}),
        taste_summary=u.taste_summary,
    )


@router.get("", response_model=AboutMeResponse)
def get_about_me(db: DbSession) -> AboutMeResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return _to_response(u)


@router.put("", response_model=AboutMeResponse)
def update_about_me(payload: AboutMeUpdate, db: DbSession) -> AboutMeResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    if payload.active_categories is not None:
        u.active_categories = payload.active_categories
    if payload.taste_facets is not None:
        merged = dict(u.taste_facets or {})
        for cat, cat_facets in payload.taste_facets.items():
            merged[cat] = cat_facets
        u.taste_facets = merged
    if payload.taste_summary is not None:
        u.taste_summary = payload.taste_summary
    db.commit()
    db.refresh(u)
    return _to_response(u)
```

- [ ] **Step 4: Register router**

In `backend/app/main.py`, add to the imports:

```python
from app.api import routes_about_me
```

And after the existing `include_router` calls:

```python
app.include_router(routes_about_me.router)
```

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/api/test_routes_about_me.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/api/routes_about_me.py backend/app/main.py backend/tests/api/test_routes_about_me.py
git commit -m "feat(recommender): about-me GET/PUT routes"
```

---

## Task 8: Comment extractor module (LLM-driven)

**Files:**
- Create: `backend/app/agent/comment_extractor.py`
- Test: `backend/tests/agent/test_comment_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/test_comment_extractor.py
from unittest.mock import MagicMock

from app.agent.comment_extractor import ExtractorInput, extract_and_apply


def test_extractor_applies_facet_updates_to_user(db_session):
    from app.db.models import User
    u = User(id="local", taste_facets={"concerts": {"artists": {"Existing": 0.5}}})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.return_value.facet_updates = [
        _fu("concerts", "artists", "Tocotronic", 0.3),
        _fu("concerts", "disliked.genres", "edm", 1.0),
    ]

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "Konzert", "venue": "Molotow", "description": "punk"},
            text="Toll, sound wie Tocotronic. Aber EDM hasse ich.",
        ),
        llm=fake_llm,
    )

    u = db_session.query(User).filter_by(id="local").one()
    assert u.taste_facets["concerts"]["artists"]["Tocotronic"] == 0.3
    assert u.taste_facets["concerts"]["artists"]["Existing"] == 0.5
    assert u.taste_facets["concerts"]["disliked.genres"]["edm"] == 1.0


def test_extractor_ignores_updates_with_unknown_category(db_session):
    from app.db.models import User
    u = User(id="local", taste_facets={})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.return_value.facet_updates = [
        _fu("nonsense", "artists", "X", 0.5),
        _fu("concerts", "artists", "Y", 0.5),
    ]

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "t", "venue": "v", "description": "d"},
            text="ok",
        ),
        llm=fake_llm,
    )

    u = db_session.query(User).filter_by(id="local").one()
    assert "nonsense" not in u.taste_facets
    assert u.taste_facets["concerts"]["artists"]["Y"] == 0.5


def test_extractor_llm_failure_is_swallowed(db_session, caplog):
    from app.db.models import User
    u = User(id="local", taste_facets={})
    db_session.add(u)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.side_effect = RuntimeError("boom")

    extract_and_apply(
        db_session,
        user_id="local",
        input_=ExtractorInput(
            category="concerts",
            source_kind="feedback",
            event_context={"title": "t", "venue": "v", "description": "d"},
            text="ok",
        ),
        llm=fake_llm,
    )

    assert "comment extractor failed" in caplog.text.lower()
    u = db_session.query(User).filter_by(id="local").one()
    assert u.taste_facets == {}


def _fu(category: str, field: str, key: str, delta: float):
    from app.agent.comment_extractor import FacetUpdate
    return FacetUpdate(category=category, field=field, key=key, delta=delta)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_comment_extractor.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement extractor**

```python
# backend/app/agent/comment_extractor.py
"""LLM extractor that turns free-text feedback comments and About-Me notes
into structured facet updates."""
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.categories import CATEGORIES
from app.agent.facets import apply_facet_delta
from app.agent.llm import get_llm
from app.db.models import User

logger = logging.getLogger(__name__)


ALLOWED_FIELDS = (
    "artists", "genres", "venues", "weekday_pref",
    "disliked.artists", "disliked.genres",
)


class FacetUpdate(BaseModel):
    category: str
    field: Literal[
        "artists", "genres", "venues", "weekday_pref",
        "disliked.artists", "disliked.genres",
    ]
    key: str = Field(min_length=1)
    delta: float = Field(ge=-1.0, le=1.0)


class ExtractorOutput(BaseModel):
    facet_updates: list[FacetUpdate] = Field(default_factory=list)


class ExtractorInput(BaseModel):
    category: str
    source_kind: Literal["feedback", "about_me_notes"]
    event_context: dict  # {"title", "venue", "description"} — empty for about_me_notes
    text: str


_SYSTEM = """\
You extract structured taste updates from a user's short comment about an event
or a note they wrote about a category.

Return facet_updates as a list of small changes to their taste profile.

Vocabulary rules:
- category MUST be one of: concerts, party, comedy, theater, arts, literature,
  film, family, food, sports, outdoor.
- field MUST be one of: artists, genres, venues, weekday_pref,
  disliked.artists, disliked.genres.
- key is the specific item (e.g. artist name, genre string, venue name,
  weekday code "mon"/"tue"/... for weekday_pref).
- delta is between -1.0 and 1.0. Use +0.2..+0.4 for a passing positive mention,
  +0.5..+0.8 for a strong positive, +1.0 for "love this". Use similar magnitudes
  on disliked.* for negatives.

If the text doesn't contain a taste signal, return facet_updates: [].
"""


def _render_user_turn(inp: ExtractorInput) -> str:
    parts = [f"Category: {inp.category}", f"Source: {inp.source_kind}"]
    ctx = inp.event_context or {}
    if inp.source_kind == "feedback":
        parts.append(f"Event title: {ctx.get('title', '')}")
        parts.append(f"Venue: {ctx.get('venue', '')}")
        parts.append(f"Description: {(ctx.get('description') or '')[:400]}")
    parts.append("")
    parts.append(f"User text: {inp.text}")
    return "\n".join(parts)


def _default_llm():
    return get_llm().with_structured_output(ExtractorOutput)


def extract_and_apply(
    session: Session,
    user_id: str,
    input_: ExtractorInput,
    llm=None,
) -> None:
    """Run the extractor and mutate `users.taste_facets` accordingly.

    On any LLM failure this is a no-op — comments are safe on the feedback
    row and can be reprocessed later. Never raises to the caller."""
    llm = llm or _default_llm()
    try:
        output: ExtractorOutput = llm.invoke(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content=_render_user_turn(input_)),
            ]
        )
    except Exception:
        logger.exception("Comment extractor failed for user %s", user_id)
        return

    user = session.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        return
    facets = dict(user.taste_facets or {})
    for u in output.facet_updates:
        if u.category not in CATEGORIES:
            continue
        apply_facet_delta(facets, u.category, u.field, u.key, u.delta)
    user.taste_facets = facets
    session.commit()
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest backend/tests/agent/test_comment_extractor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/comment_extractor.py backend/tests/agent/test_comment_extractor.py
git commit -m "feat(recommender): comment extractor with structured LLM output"
```

---

## Task 9: Wire comment extractor into feedback POST as BackgroundTask

**Files:**
- Modify: `backend/app/api/routes_feedback.py`
- Test: `backend/tests/api/test_routes_feedback_extractor.py` (extend)

- [ ] **Step 1: Extend failing tests**

Append to `backend/tests/api/test_routes_feedback_extractor.py`:

```python
def test_feedback_with_comment_schedules_extractor(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.extract_and_apply") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "like", "comment": "great punk"},
        )
    assert res.status_code == 200
    m.assert_called_once()
    kwargs = m.call_args.kwargs or {}
    inp = kwargs.get("input_") or m.call_args.args[2]
    assert inp.category == "concerts"
    assert inp.text == "great punk"


def test_feedback_without_comment_does_not_call_extractor(client, db_session):
    _seed_event(db_session)
    db_session.add(User(id="local"))
    db_session.commit()

    with patch("app.api.routes_feedback.extract_and_apply") as m:
        res = client.post(
            "/feedback",
            json={"event_id": "e1", "sentiment": "like", "comment": None},
        )
    assert res.status_code == 200
    m.assert_not_called()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py -v`
Expected: two new failures.

- [ ] **Step 3: Update route**

Rewrite `post_feedback` in `backend/app/api/routes_feedback.py`:

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.agent.comment_extractor import ExtractorInput, extract_and_apply
from app.agent.memory import get_current_user_id, refresh_taste_centroids
from app.api.deps import DbSession
from app.db.models import Event, Feedback
from app.db.session import SessionLocal
from app.schemas.feedback import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _extract_in_bg(user_id: str, category: str, event_ctx: dict, text: str) -> None:
    """BackgroundTask wrapper: opens its own DB session."""
    with SessionLocal() as bg_session:
        extract_and_apply(
            bg_session,
            user_id=user_id,
            input_=ExtractorInput(
                category=category,
                source_kind="feedback",
                event_context=event_ctx,
                text=text,
            ),
        )


@router.post("", response_model=FeedbackResponse)
def post_feedback(
    payload: FeedbackCreate,
    db: DbSession,
    background: BackgroundTasks,
) -> FeedbackResponse:
    user_id = get_current_user_id()
    event = db.query(Event).filter_by(id=payload.event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="event not found")

    existing = db.query(Feedback).filter_by(user_id=user_id, event_id=payload.event_id).first()
    if existing:
        existing.sentiment = payload.sentiment
        existing.comment = payload.comment
        existing.updated_at = datetime.now(timezone.utc)
        fb = existing
    else:
        fb = Feedback(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_id=payload.event_id,
            sentiment=payload.sentiment,
            comment=payload.comment,
        )
        db.add(fb)

    db.commit()
    db.refresh(fb)

    refresh_taste_centroids(db, user_id)
    db.commit()

    if payload.comment:
        event_ctx = {
            "title": event.title,
            "venue": event.venue_name,
            "description": event.description,
        }
        background.add_task(
            _extract_in_bg,
            user_id=user_id,
            category=event.category,
            event_ctx=event_ctx,
            text=payload.comment,
        )

    return FeedbackResponse(
        id=fb.id, event_id=fb.event_id, sentiment=fb.sentiment,
        comment=fb.comment, created_at=fb.created_at, updated_at=fb.updated_at,
    )


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feedback(event_id: str, db: DbSession) -> None:
    user_id = get_current_user_id()
    existing = db.query(Feedback).filter_by(user_id=user_id, event_id=event_id).first()
    if not existing:
        return
    db.delete(existing)
    db.commit()
    refresh_taste_centroids(db, user_id)
    db.commit()
```

**IMPORTANT for tests:** `TestClient` executes `BackgroundTasks` synchronously after the response. `patch("app.api.routes_feedback.extract_and_apply")` intercepts the extractor call inside `_extract_in_bg`, so tests still work.

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/api/test_routes_feedback_extractor.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/api/routes_feedback.py backend/tests/api/test_routes_feedback_extractor.py
git commit -m "feat(recommender): background comment extraction on feedback"
```

---

## Task 10: Wire comment extractor into About-Me notes save

**Files:**
- Modify: `backend/app/api/routes_about_me.py`
- Test: `backend/tests/api/test_routes_about_me.py` (extend)

- [ ] **Step 1: Extend failing test**

Append:

```python
def test_notes_field_triggers_extractor(client, db_session):
    from app.db.models import User
    db_session.add(User(id="local"))
    db_session.commit()

    payload = {
        "active_categories": ["concerts"],
        "taste_facets": {
            "concerts": {
                "artists": {"Die Sterne": 0.8},
                "notes": "small venues only, no EDM",
            }
        },
    }
    with patch("app.api.routes_about_me.extract_and_apply") as m:
        res = client.put("/about-me", json=payload)
    assert res.status_code == 200
    calls = [c for c in m.call_args_list if c.kwargs.get("input_", None)]
    # One call per category that carries a non-empty "notes" field.
    assert len(calls) == 1
```

Add `from unittest.mock import patch` at the top if not already present.

- [ ] **Step 2: Run test to verify failure**

Run: `pytest backend/tests/api/test_routes_about_me.py::test_notes_field_triggers_extractor -v`
Expected: FAIL.

- [ ] **Step 3: Update route to fire extractor for `notes`**

In `backend/app/api/routes_about_me.py`:

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.comment_extractor import ExtractorInput, extract_and_apply
from app.db.session import SessionLocal
```

And rewrite `update_about_me` signature to accept `BackgroundTasks` and dispatch:

```python
def _extract_notes_bg(user_id: str, category: str, text: str) -> None:
    with SessionLocal() as bg_session:
        extract_and_apply(
            bg_session,
            user_id=user_id,
            input_=ExtractorInput(
                category=category,
                source_kind="about_me_notes",
                event_context={},
                text=text,
            ),
        )


@router.put("", response_model=AboutMeResponse)
def update_about_me(
    payload: AboutMeUpdate,
    db: DbSession,
    background: BackgroundTasks,
) -> AboutMeResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")

    notes_to_extract: list[tuple[str, str]] = []

    if payload.active_categories is not None:
        u.active_categories = payload.active_categories
    if payload.taste_facets is not None:
        merged = dict(u.taste_facets or {})
        for cat, cat_facets in payload.taste_facets.items():
            merged[cat] = cat_facets
            note = (cat_facets or {}).get("notes") if isinstance(cat_facets, dict) else None
            if isinstance(note, str) and note.strip():
                notes_to_extract.append((cat, note.strip()))
        u.taste_facets = merged
    if payload.taste_summary is not None:
        u.taste_summary = payload.taste_summary
    db.commit()
    db.refresh(u)

    for cat, text in notes_to_extract:
        background.add_task(_extract_notes_bg, user_id=user_id, category=cat, text=text)

    return _to_response(u)
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/api/test_routes_about_me.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/api/routes_about_me.py backend/tests/api/test_routes_about_me.py
git commit -m "feat(recommender): about-me notes go through the comment extractor"
```

---

## Task 11: Per-category retrieval + disliked-substring filter

**Files:**
- Create: `backend/app/agent/retrieval.py`
- Test: `backend/tests/agent/test_retrieval.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/test_retrieval.py
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _mk_event(db, ev_id, cat, title="t", desc="d", tags=None):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title=title, description=desc,
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=tags or [], source_url="http://e",
        raw_data={},
    )
    db.add(e)
    return e


def test_filter_out_disliked_terms_substring_match(db_session):
    from app.agent.retrieval import filter_out_disliked
    _mk_event(db_session, "e_edm", "party", title="Big EDM night", desc="DJ set")
    _mk_event(db_session, "e_ok", "party", title="Techno party", desc="raw sound")
    db_session.commit()
    user = User(
        id="local",
        taste_facets={"party": {"disliked.genres": {"edm": 1.0}}},
    )
    kept = filter_out_disliked(db_session, user, "party", ["e_edm", "e_ok"])
    assert kept == ["e_ok"]


def test_filter_out_disliked_is_case_insensitive(db_session):
    from app.agent.retrieval import filter_out_disliked
    _mk_event(db_session, "e1", "concerts", title="Interpol live", desc="")
    db_session.commit()
    user = User(
        id="local",
        taste_facets={"concerts": {"disliked.artists": {"interpol": 1.0}}},
    )
    assert filter_out_disliked(db_session, user, "concerts", ["e1"]) == []


def test_get_category_candidates_returns_empty_when_category_inactive(db_session):
    from app.agent.retrieval import get_category_candidates
    user = User(id="local", active_categories=["concerts"])
    res = get_category_candidates(db_session, user, "party", date_from=None, date_to=None, k=10)
    assert res == []


def test_get_category_candidates_uses_category_centroid(db_session):
    from app.agent.retrieval import get_category_candidates
    _mk_event(db_session, "e1", "concerts")
    db_session.commit()
    user = User(
        id="local",
        active_categories=["concerts"],
        taste_centroids={"concerts": [1.0, 0.0]},
    )
    with patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        q.return_value = [type("H", (), {"event_id": "e1", "similarity_score": 0.9})()]
        res = get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=5)
    assert res and res[0].event_id == "e1"
    args, kwargs = q.call_args
    assert args[0] == [1.0, 0.0]
    assert kwargs.get("where", {}).get("category") == "concerts"


def test_get_category_candidates_cold_start_from_facets(db_session):
    from app.agent.retrieval import get_category_candidates
    _mk_event(db_session, "e1", "concerts")
    db_session.commit()
    user = User(
        id="local",
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.8}, "genres": {"punk": 0.8}}},
    )
    with patch("app.agent.retrieval.embed_one", return_value=[0.5, 0.5]) as e, \
         patch("app.agent.retrieval.chroma_store.query_by_vector") as q:
        q.return_value = []
        get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=5)
    seed = e.call_args.args[0]
    assert "Die Sterne" in seed
    assert "punk" in seed


def test_get_category_candidates_returns_empty_when_no_seed(db_session):
    from app.agent.retrieval import get_category_candidates
    user = User(id="local", active_categories=["concerts"], taste_centroids={}, taste_facets={}, interest_tags=[])
    assert get_category_candidates(db_session, user, "concerts", date_from=None, date_to=None, k=5) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_retrieval.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement module**

```python
# backend/app/agent/retrieval.py
"""Per-category candidate retrieval + disliked-substring hard-filter.

Both the digest generator and the get_recommendations tool call into
this module."""
from datetime import date, datetime, time, timezone

from sqlalchemy.orm import Session

from app.db.models import Event, User
from app.rag import chroma_store
from app.rag.chroma_store import QueryHit
from app.rag.embeddings import embed_one


def _iter_disliked_terms(user: User, category: str) -> list[str]:
    facets = (user.taste_facets or {}).get(category) or {}
    terms: list[str] = []
    for key in ("disliked.artists", "disliked.genres"):
        for term in (facets.get(key) or {}).keys():
            term = (term or "").strip().lower()
            if term:
                terms.append(term)
    return terms


def filter_out_disliked(
    session: Session,
    user: User,
    category: str,
    event_ids: list[str],
) -> list[str]:
    """Substring-match disliked artist/genre terms against title/description/tags.

    Phase 1 approximation. Phase 2 replaces this with MBID-based matching."""
    terms = _iter_disliked_terms(user, category)
    if not terms or not event_ids:
        return list(event_ids)
    rows = session.query(Event).filter(Event.id.in_(event_ids)).all()
    kept: list[str] = []
    for e in rows:
        hay = " ".join([
            (e.title or ""),
            (e.description or ""),
            " ".join(e.tags or []),
        ]).lower()
        if any(term in hay for term in terms):
            continue
        kept.append(e.id)
    return kept


def _build_cold_start_seed(user: User, category: str) -> str | None:
    facets = (user.taste_facets or {}).get(category) or {}
    parts: list[str] = []
    for field in ("artists", "genres", "venues"):
        bucket = facets.get(field) or {}
        parts.extend(bucket.keys())
    if parts:
        return f"{category}: " + ", ".join(parts)
    tags = list(user.interest_tags or [])
    if tags:
        return f"{category}: " + ", ".join(tags)
    return None


def _range_clause(date_from: str | None, date_to: str | None) -> dict | None:
    ranges: list[dict] = []
    if date_from:
        ranges.append({"start_time": {"$gte": int(datetime.combine(
            date.fromisoformat(date_from), time.min, tzinfo=timezone.utc,
        ).timestamp())}})
    if date_to:
        ranges.append({"start_time": {"$lte": int(datetime.combine(
            date.fromisoformat(date_to), time.max, tzinfo=timezone.utc,
        ).timestamp())}})
    if not ranges:
        return None
    return {"$and": ranges} if len(ranges) > 1 else ranges[0]


def get_category_candidates(
    session: Session,
    user: User,
    category: str,
    *,
    date_from: str | None,
    date_to: str | None,
    k: int = 30,
) -> list[QueryHit]:
    if user.active_categories is not None and category not in user.active_categories:
        return []

    centroid = (user.taste_centroids or {}).get(category)
    if centroid:
        vector = list(centroid)
    else:
        seed = _build_cold_start_seed(user, category)
        if not seed:
            return []
        vector = embed_one(seed)

    where: dict = {"category": category}
    rng = _range_clause(date_from, date_to)
    if rng:
        where = {"$and": [where, rng]}

    hits = chroma_store.query_by_vector(vector, n=min(k, 30), where=where)
    if not hits:
        return []
    kept_ids = set(filter_out_disliked(session, user, category, [h.event_id for h in hits]))
    return [h for h in hits if h.event_id in kept_ids]
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/agent/test_retrieval.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/retrieval.py backend/tests/agent/test_retrieval.py
git commit -m "feat(recommender): per-category retrieval + disliked hard-filter"
```

---

## Task 12: Update `get_recommendations` tool

**Files:**
- Modify: `backend/app/agent/tools.py`
- Test: extend an existing test file or create `backend/tests/agent/test_tools_recommendations.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/agent/test_tools_recommendations.py
from datetime import datetime, timezone
from unittest.mock import patch

from app.db.models import Event, User


def _mk_event(db, ev_id, cat):
    e = Event(
        id=ev_id, external_id=ev_id, source="test",
        title="t", description="d",
        start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
        category=cat, tags=[], source_url="http://e", raw_data={},
    )
    db.add(e)
    return e


def test_get_recommendations_returns_no_active_categories_error(db_session, monkeypatch):
    from app.agent import memory
    from app.agent.tools import get_recommendations

    db_session.add(User(id="local", active_categories=[]))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_recommendations.invoke({})
    assert result == {"error": "no_active_categories"}


def test_get_recommendations_honors_explicit_category_overriding_inactive(db_session):
    from app.agent import memory
    from app.agent.tools import get_recommendations

    _mk_event(db_session, "e1", "party")
    db_session.add(User(
        id="local",
        active_categories=[],
        taste_centroids={"party": [1.0, 0.0]},
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    with patch("app.agent.tools.retrieval.get_category_candidates") as q:
        q.return_value = [type("H", (), {"event_id": "e1", "similarity_score": 0.9})()]
        result = get_recommendations.invoke({"category": "party"})
    assert isinstance(result, list) and result[0]["id"] == "e1"


def test_get_recommendations_iterates_over_active_categories(db_session):
    from app.agent import memory
    from app.agent.tools import get_recommendations

    _mk_event(db_session, "e1", "concerts")
    _mk_event(db_session, "e2", "party")
    db_session.add(User(
        id="local",
        active_categories=["concerts", "party"],
        taste_centroids={"concerts": [1.0, 0.0], "party": [0.0, 1.0]},
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    def fake_candidates(session, user, category, **kwargs):
        return [
            type("H", (), {"event_id": {"concerts": "e1", "party": "e2"}[category], "similarity_score": 0.9})()
        ]

    with patch("app.agent.tools.retrieval.get_category_candidates", side_effect=fake_candidates):
        result = get_recommendations.invoke({})
    ids = {r["id"] for r in result}
    assert ids == {"e1", "e2"}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/agent/test_tools_recommendations.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite `get_recommendations` tool**

In `backend/app/agent/tools.py`, replace the existing `get_recommendations` decorator body with:

```python
from app.agent import retrieval  # add near top imports


@tool
def get_recommendations(
    date_from: str | None = None,
    date_to: str | None = None,
    n: int = 10,
    category: str | None = None,
) -> list[dict] | dict:
    """Recommend events for the current user, per category.

    Args:
        date_from: ISO date lower bound (inclusive).
        date_to: ISO date upper bound (inclusive).
        n: max results across all queried categories.
        category: if given, restrict to this category (overrides active_categories).
                  if None, uses active_categories and returns [] with a
                  structured hint when no categories are active.
    """
    session = _session_factory()
    try:
        user_id = get_current_user_id()
        user = session.query(User).filter_by(id=user_id).one_or_none()
        if user is None:
            raise ToolError("user not found")

        if category is not None:
            targets = [category]
        else:
            if not user.active_categories:
                return {"error": "no_active_categories"}
            targets = list(user.active_categories)

        try:
            hits_per_category: list[chroma_store.QueryHit] = []
            for cat in targets:
                hits_per_category.extend(retrieval.get_category_candidates(
                    session, user, cat,
                    date_from=date_from, date_to=date_to, k=min(n * 3, 30),
                ))
        except Exception as exc:
            logger.exception("chroma query failed")
            raise ToolError("recommendations temporarily unavailable") from exc

        if not hits_per_category:
            return []

        id_to_score = {}
        for h in hits_per_category:
            prev = id_to_score.get(h.event_id, -1.0)
            if (h.similarity_score or 0.0) > prev:
                id_to_score[h.event_id] = h.similarity_score

        rows = (
            session.query(Event)
            .filter(Event.id.in_(id_to_score.keys()))
            .filter(visible_events_filter())
            .all()
        )
        ranked = sorted(
            (_event_to_summary(r, similarity_score=id_to_score[r.id]) for r in rows),
            key=lambda d: d["similarity_score"] or 0.0,
            reverse=True,
        )
        return ranked[:n]
    finally:
        session.close()
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/agent/test_tools_recommendations.py backend/tests/agent -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/tools.py backend/tests/agent/test_tools_recommendations.py
git commit -m "feat(recommender): get_recommendations honours active_categories"
```

---

## Task 13: Extend `get_user_profile` tool

**Files:**
- Modify: `backend/app/agent/tools.py` (`get_user_profile`)
- Test: extend or add `backend/tests/agent/test_tools_profile.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/agent/test_tools_profile.py
from app.db.models import User


def test_get_user_profile_returns_active_categories_and_facets(db_session):
    from app.agent import memory
    from app.agent.tools import get_user_profile

    db_session.add(User(
        id="local",
        active_categories=["concerts"],
        taste_facets={"concerts": {"artists": {"Die Sterne": 0.8}}},
        interest_tags=["music"],
        taste_summary="likes indie",
    ))
    db_session.commit()
    memory.set_current_user_id("local")

    result = get_user_profile.invoke({})
    assert result["active_categories"] == ["concerts"]
    assert result["taste_facets"]["concerts"]["artists"]["Die Sterne"] == 0.8
    assert result["interest_tags"] == ["music"]
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest backend/tests/agent/test_tools_profile.py -v`
Expected: FAIL (fields missing).

- [ ] **Step 3: Extend `get_user_profile` tool**

In `backend/app/agent/tools.py`, extend the return dict:

```python
        return {
            "interest_tags": list(user.interest_tags),
            "about_me": user.about_me,
            "taste_summary": user.taste_summary,
            "active_categories": list(user.active_categories) if user.active_categories is not None else None,
            "taste_facets": dict(user.taste_facets or {}),
        }
```

- [ ] **Step 4: Run tests**

Run: `pytest backend/tests/agent/test_tools_profile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add backend/app/agent/tools.py backend/tests/agent/test_tools_profile.py
git commit -m "feat(recommender): get_user_profile exposes active_categories + facets"
```

---

## Task 14: Digest generator uses per-category retrieval + extended prompt

**Files:**
- Modify: `backend/app/agent/prompts.py`
- Modify: `backend/app/api/routes_digest.py`
- Test: `backend/tests/api/test_routes_digest.py` (existing or new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/api/test_routes_digest.py` (or extend if present):

```python
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.db.models import Event, User


def _seed_events(db):
    for i, cat in enumerate(["concerts", "party", "theater"]):
        db.add(Event(
            id=f"e{i}", external_id=f"e{i}", source="test",
            title=f"{cat} event", description="d",
            start_datetime=datetime(2026, 6, 1, tzinfo=timezone.utc),
            category=cat, tags=[], source_url="http://e", raw_data={},
        ))


def test_digest_pool_is_built_per_active_category(client, db_session):
    _seed_events(db_session)
    db_session.add(User(
        id="local",
        active_categories=["concerts", "party"],
        taste_centroids={"concerts": [1.0, 0.0], "party": [0.0, 1.0]},
    ))
    db_session.commit()

    called_categories: list[str] = []

    def fake_candidates(session, user, category, **kwargs):
        called_categories.append(category)
        return [type("H", (), {"event_id": f"e{['concerts','party','theater'].index(category)}", "similarity_score": 0.9})()]

    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {
        "structured_response": type("R", (), {"picks": [
            type("P", (), {"event_id": "e0", "justification": "great match"})(),
            type("P", (), {"event_id": "e1", "justification": "great match"})(),
            type("P", (), {"event_id": "e0", "justification": "again"})(),
        ]})(),
        "messages": [],
    }
    with patch("app.api.routes_digest.retrieval.get_category_candidates", side_effect=fake_candidates), \
         patch("app.api.routes_digest.get_agent", return_value=fake_agent):
        res = client.get("/digest")
    assert res.status_code == 200
    assert set(called_categories) == {"concerts", "party"}


def test_digest_returns_hint_when_no_active_categories(client, db_session):
    db_session.add(User(id="local", active_categories=[]))
    db_session.commit()
    res = client.get("/digest")
    assert res.status_code == 409
    assert "no_active_categories" in res.json().get("detail", "")


def test_digest_redirects_new_user(client, db_session):
    db_session.add(User(id="local"))  # active_categories = None
    db_session.commit()
    res = client.get("/digest")
    assert res.status_code == 409
    assert "about_me_required" in res.json().get("detail", "")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest backend/tests/api/test_routes_digest.py -v`
Expected: FAIL.

- [ ] **Step 3: Extend prompt template**

In `backend/app/agent/prompts.py`, replace `CURATION_PROMPT` with:

```python
CURATION_PROMPT = """\
You are a Hamburg event concierge picking today's digest for a user.

USER PROFILE
  Interests: {interests}
  About-me: {about_me}
  Active categories: {active_categories}
  Deactivated categories (do not proactively suggest): {inactive_categories}

TASTE SUMMARY (max 20 lines, the assistant's picture of the user):
{taste_summary}

TASTE FACETS (per active category, JSON):
{taste_facets_json}

DISLIKED (already hard-filtered from the pool, repeated so you don't reintroduce them):
{disliked_json}

TODAY'S CANDIDATE POOL (JSON):
{event_pool}

Your job: pick 3 to 5 events from the pool that this specific user is most
likely to love today. For each pick, write a 1-2 sentence justification
grounded in the taste facets or taste summary — not generic praise.

Return your final answer in the structured output format.
"""
```

Keep `CONVERSATIONAL_PROMPT` and `build_conversational_prompt` unchanged.

- [ ] **Step 4: Rewrite digest generator**

In `backend/app/api/routes_digest.py`, add imports at the top of the file:

```python
from app.agent import retrieval
from app.agent.categories import USER_SELECTABLE_CATEGORIES
```

Replace `_candidate_pool` with a per-category version, and rewrite `_generate_digest`:

```python
def _per_category_pool(db, user: User, today: date) -> list[Event]:
    date_from = today.isoformat()
    date_to = (today + timedelta(days=7)).isoformat()
    if not user.active_categories:
        return []
    all_ids: set[str] = set()
    for cat in user.active_categories:
        hits = retrieval.get_category_candidates(
            db, user, cat, date_from=date_from, date_to=date_to, k=30,
        )
        all_ids.update(h.event_id for h in hits)
    if not all_ids:
        return []
    return (
        db.query(Event)
        .filter(Event.id.in_(all_ids))
        .order_by(Event.start_datetime.asc())
        .all()
    )


def _extract_disliked(user: User) -> dict:
    out: dict = {}
    for cat, facets in (user.taste_facets or {}).items():
        d = {}
        for key in ("disliked.artists", "disliked.genres"):
            entries = (facets or {}).get(key) or {}
            if entries:
                d[key] = sorted(entries.keys())
        if d:
            out[cat] = d
    return out


def _compact_facets(user: User) -> dict:
    active = set(user.active_categories or [])
    return {c: f for c, f in (user.taste_facets or {}).items() if c in active}


def _generate_digest(db, user: User, today: date) -> DigestResponse:
    if user.active_categories is None:
        raise HTTPException(status_code=409, detail="about_me_required")
    if not user.active_categories:
        raise HTTPException(status_code=409, detail="no_active_categories")

    pool = _per_category_pool(db, user, today)
    if not pool:
        raise HTTPException(status_code=503, detail="no events available")

    inactive = sorted(set(USER_SELECTABLE_CATEGORIES) - set(user.active_categories))

    prompt = CURATION_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        active_categories=", ".join(user.active_categories) or "(none)",
        inactive_categories=", ".join(inactive) or "(none)",
        taste_summary=user.taste_summary or "(empty)",
        taste_facets_json=json.dumps(_compact_facets(user), indent=2),
        disliked_json=json.dumps(_extract_disliked(user), indent=2),
        event_pool=json.dumps([_serialise_event_for_prompt(e) for e in pool], indent=2),
    )

    agent = get_agent()
    result = agent.invoke(
        {"messages": [SystemMessage(content=prompt), HumanMessage(content="Pick today's events.")]},
        config={"configurable": {"thread_id": f"digest:{user.id}:{today.isoformat()}"}},
        response_format=LLMDigestResponse,
    )
    # ... keep the existing structured_response parsing, fallback recovery,
    # DigestCache write, and _build_response(...) exactly as they are today
    # (do not delete them; only the prompt-building and pool-building parts
    # above changed).
```

- [ ] **Step 5: Run tests**

Run: `pytest backend/tests/api/test_routes_digest.py backend/tests/agent -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```
git add backend/app/agent/prompts.py backend/app/api/routes_digest.py backend/tests/api/test_routes_digest.py
git commit -m "feat(recommender): per-category digest pool + facets in curation prompt"
```

---

## Task 15: Frontend types + api client

**Files:**
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Extend types.ts**

Append:

```ts
export interface CategoryFacets {
  artists?: Record<string, number>;
  genres?: Record<string, number>;
  venues?: Record<string, number>;
  weekday_pref?: Record<string, number>;
  disliked?: {
    artists?: Record<string, number>;
    genres?: Record<string, number>;
  };
  notes?: string;
}

export interface AboutMeResponse {
  active_categories: string[] | null;
  taste_facets: Partial<Record<EventCategory, CategoryFacets>>;
  taste_summary: string | null;
}

export interface AboutMeUpdate {
  active_categories?: string[];
  taste_facets?: Partial<Record<EventCategory, CategoryFacets>>;
  taste_summary?: string;
}
```

- [ ] **Step 2: Add api.ts helpers**

Add to `frontend/lib/api.ts`:

```ts
import type { AboutMeResponse, AboutMeUpdate } from "@/lib/types";

// ---------- About Me ----------

export async function getAboutMe(): Promise<AboutMeResponse> {
  if (MOCK) {
    return { active_categories: null, taste_facets: {}, taste_summary: null };
  }
  return jsonFetch<AboutMeResponse>("/about-me");
}

export async function updateAboutMe(body: AboutMeUpdate): Promise<AboutMeResponse> {
  if (MOCK) {
    console.info("[mock] PUT /about-me", body);
    return { active_categories: body.active_categories ?? null, taste_facets: body.taste_facets ?? {}, taste_summary: body.taste_summary ?? null };
  }
  return jsonFetch<AboutMeResponse>("/about-me", { method: "PUT", body: JSON.stringify(body) });
}
```

- [ ] **Step 3: Type-check frontend**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```
git add frontend/lib/types.ts frontend/lib/api.ts
git commit -m "feat(recommender): frontend types + api client for About Me"
```

---

## Task 16: About Me form descriptors

**Files:**
- Create: `frontend/lib/aboutMeCategories.ts`

- [ ] **Step 1: Implement descriptors**

```ts
// frontend/lib/aboutMeCategories.ts
// Structural descriptors for the About Me per-category form sections.
// Every field maps into the shared taste_facets shape (artists / genres /
// venues / notes). Category-specific labels only affect display.

import type { EventCategory } from "@/lib/types";

export interface CategoryField {
  label: string;
  helper?: string;
  facetField: "artists" | "genres" | "venues" | "notes";
}

export interface CategoryDescriptor {
  key: EventCategory;
  displayName: string;
  fields: CategoryField[];
}

export const SELECTABLE_CATEGORIES: EventCategory[] = [
  "concerts", "party", "comedy", "theater", "arts", "literature",
  "film", "family", "food", "sports", "outdoor",
];

export const CATEGORY_DESCRIPTORS: Record<EventCategory, CategoryDescriptor> = {
  concerts: {
    key: "concerts", displayName: "Concerts",
    fields: [
      { label: "Favourite artists", facetField: "artists", helper: "Comma-separated" },
      { label: "Favourite genres", facetField: "genres", helper: "e.g. punk, indie, jazz" },
      { label: "Favourite venues", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  party: {
    key: "party", displayName: "Party",
    fields: [
      { label: "Favourite DJs / acts", facetField: "artists" },
      { label: "Favourite genres", facetField: "genres", helper: "e.g. techno, house, drum'n'bass" },
      { label: "Favourite clubs", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  comedy: {
    key: "comedy", displayName: "Comedy",
    fields: [
      { label: "Favourite comedians", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Stand-up, Kabarett, Improv..." },
      { label: "Favourite venues", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  theater: {
    key: "theater", displayName: "Theater",
    fields: [
      { label: "Favourite houses", facetField: "venues" },
      { label: "Preferred formats", facetField: "genres", helper: "Musical, Classic, Modern..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  arts: {
    key: "arts", displayName: "Arts",
    fields: [
      { label: "Favourite artists / houses", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Exhibition, Ballet, Contemporary Dance..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  literature: {
    key: "literature", displayName: "Literature",
    fields: [
      { label: "Favourite authors", facetField: "artists" },
      { label: "Preferred formats", facetField: "genres", helper: "Reading, Poetry Slam, Book launch..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  film: {
    key: "film", displayName: "Film",
    fields: [
      { label: "Favourite directors", facetField: "artists" },
      { label: "Genres", facetField: "genres" },
      { label: "Favourite cinemas", facetField: "venues" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  family: {
    key: "family", displayName: "Family",
    fields: [
      { label: "Kids' ages", facetField: "genres", helper: "e.g. 3-6, 7-10" },
      { label: "Interests", facetField: "artists" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  food: {
    key: "food", displayName: "Food",
    fields: [
      { label: "Favourite cuisines", facetField: "genres" },
      { label: "Preferred formats", facetField: "artists", helper: "Tasting, Festival, Pop-up..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  sports: {
    key: "sports", displayName: "Sports",
    fields: [
      { label: "Sports / disciplines", facetField: "genres" },
      { label: "Favourite teams", facetField: "artists" },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  outdoor: {
    key: "outdoor", displayName: "Outdoor",
    fields: [
      { label: "Activities", facetField: "genres", helper: "Hiking, Park festival, Nature..." },
      { label: "Anything else?", facetField: "notes" },
    ],
  },
  other: { key: "other", displayName: "Other", fields: [] },
};
```

- [ ] **Step 2: Type-check**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```
git add frontend/lib/aboutMeCategories.ts
git commit -m "feat(recommender): about-me category descriptors"
```

---

## Task 17: About Me page + reusable section component

**Files:**
- Create: `frontend/components/CategoryFacetsSection.tsx`
- Create: `frontend/app/about-me/page.tsx`
- Modify: `frontend/components/TopNav.tsx` (add link)

- [ ] **Step 1: Implement `CategoryFacetsSection.tsx`**

```tsx
// frontend/components/CategoryFacetsSection.tsx
'use client'
import type { CategoryDescriptor } from '@/lib/aboutMeCategories'
import type { CategoryFacets } from '@/lib/types'

export interface CategoryFacetsSectionProps {
  descriptor: CategoryDescriptor
  facets: CategoryFacets
  onChange: (next: CategoryFacets) => void
}

function bucketToText(bucket: Record<string, number> | undefined): string {
  if (!bucket) return ''
  return Object.keys(bucket).join(', ')
}

function textToBucket(text: string, weight = 0.8): Record<string, number> {
  const out: Record<string, number> = {}
  for (const raw of text.split(',')) {
    const key = raw.trim()
    if (!key) continue
    out[key] = weight
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
              <input
                type="text"
                className="rounded border border-border px-2 py-1 text-[13px]"
                value={bucketToText(facets[f.facetField] as Record<string, number> | undefined)}
                onChange={(e) =>
                  onChange({ ...facets, [f.facetField]: textToBucket(e.target.value) })
                }
              />
            )}
          </label>
        ))}
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Implement `about-me/page.tsx`**

```tsx
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
  const [tasteSummary, setTasteSummary] = useState<string>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!data) return
    setActive((data.active_categories ?? []) as EventCategory[])
    setFacets(data.taste_facets ?? {})
    setTasteSummary(data.taste_summary ?? '')
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
        taste_summary: tasteSummary,
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

          {sortedActive.map((cat) => (
            <CategoryFacetsSection
              key={cat}
              descriptor={CATEGORY_DESCRIPTORS[cat]}
              facets={facets[cat] ?? {}}
              onChange={(next) => updateFacetsFor(cat, next)}
            />
          ))}

          <section className="rounded-lg border border-border bg-white p-4">
            <h2 className="text-[12px] uppercase tracking-wider text-accent-gold mb-3">
              What the assistant has learned about you
            </h2>
            <textarea
              className="w-full rounded border border-border px-2 py-1 text-[13px]"
              rows={5}
              value={tasteSummary}
              onChange={(e) => setTasteSummary(e.target.value)}
            />
          </section>

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

- [ ] **Step 3: Add link in TopNav**

Modify `frontend/components/TopNav.tsx`:

```ts
type ActivePage = 'timetable' | 'explore' | 'about-me' | 'settings'

const LINKS: { href: string; label: string; page: ActivePage }[] = [
  { href: '/',          label: 'Timetable', page: 'timetable' },
  { href: '/explore',   label: 'Explore',   page: 'explore'   },
  { href: '/about-me',  label: 'About Me',  page: 'about-me'  },
  { href: '/settings',  label: 'Settings',  page: 'settings'  },
]
```

- [ ] **Step 4: Type-check**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors. If any page passes `active` typed to the old union, fix by widening to the new one.

- [ ] **Step 5: Commit**

```
git add frontend/components/CategoryFacetsSection.tsx frontend/app/about-me/page.tsx frontend/components/TopNav.tsx
git commit -m "feat(recommender): About Me page + category sections"
```

---

## Task 18: First-visit redirect to /about-me

**Files:**
- Modify: `frontend/components/AppShell.tsx`

- [ ] **Step 1: Inspect current AppShell**

Read `frontend/components/AppShell.tsx` to see how routes are wired.

- [ ] **Step 2: Implement redirect**

Add a client-side effect that fetches `/about-me` (via the existing `getAboutMe`) and redirects if `active_categories === null` and the current path is not already `/about-me`.

Concrete change: convert `AppShell` (if it's currently a server component) to include a small client-side `AboutMeGate` child, or add an effect if it's already a client component. Example implementation, assumes AppShell is a client component:

```tsx
// inside AppShell body
'use client'
import { usePathname, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { getAboutMe } from '@/lib/api'

// ...
const pathname = usePathname()
const router = useRouter()
const { data: aboutMe } = useSWR('/about-me', getAboutMe)
useEffect(() => {
  if (!aboutMe) return
  if (aboutMe.active_categories === null && pathname !== '/about-me') {
    router.replace('/about-me')
  }
}, [aboutMe, pathname, router])
```

If AppShell is a server component today, wrap its children in a new `<AboutMeGate>` client component:

```tsx
// frontend/components/AboutMeGate.tsx
'use client'
import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { getAboutMe } from '@/lib/api'

export default function AboutMeGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { data } = useSWR('/about-me', getAboutMe)
  useEffect(() => {
    if (!data) return
    if (data.active_categories === null && pathname !== '/about-me') {
      router.replace('/about-me')
    }
  }, [data, pathname, router])
  return <>{children}</>
}
```

Then wrap `{children}` in `AppShell` with `<AboutMeGate>{children}</AboutMeGate>`.

- [ ] **Step 3: Type-check and lint**

Run: `cd frontend; npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```
git add frontend/components/AppShell.tsx frontend/components/AboutMeGate.tsx
git commit -m "feat(recommender): redirect new users to About Me"
```

---

## Task 19: Backfill script for existing users

**Files:**
- Create: `backend/scripts/backfill_taste_centroids.py`

- [ ] **Step 1: Write the script**

```python
# backend/scripts/backfill_taste_centroids.py
"""One-shot backfill: recompute per-category centroids for every user.

Idempotent — safe to re-run. Does not touch taste_facets or active_categories."""
import logging

from app.agent.memory import refresh_taste_centroids
from app.db.models import User
from app.db.session import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("backfill_taste_centroids")


def main() -> None:
    with SessionLocal() as session:
        users = session.query(User).all()
        logger.info("Refreshing centroids for %d user(s)", len(users))
        for u in users:
            refresh_taste_centroids(session, u.id)
            session.commit()
            logger.info("user=%s categories=%s", u.id, list(u.taste_centroids.keys()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke-run**

Run: `cd backend; python -m scripts.backfill_taste_centroids`
Expected: exits 0 with an "user=local categories=[...]" log line.

- [ ] **Step 3: Commit**

```
git add backend/scripts/backfill_taste_centroids.py
git commit -m "feat(recommender): backfill script for per-category centroids"
```

---

## Task 20: End-to-end verification

- [ ] **Step 1: Full backend test suite**

Run: `pytest backend/tests -q`
Expected: 100% pass. If existing tests fail because they relied on the old `refresh_taste_centroid` signature: they still work through the alias in Task 4. If any test still checks `taste_centroid` global directly, adapt it or delete.

- [ ] **Step 2: Frontend type-check + build**

Run: `cd frontend; npx tsc --noEmit`
Then: `cd frontend; npx next build`
Expected: no errors.

- [ ] **Step 3: Start both services**

Run backend: `cd backend; uvicorn app.main:app --reload`
Run frontend: `cd frontend; npm run dev`

- [ ] **Step 4: Smoke test in browser**

1. Open `http://localhost:3000`.
2. On a fresh DB you should be auto-redirected to `/about-me`.
3. Check two categories, fill a couple of fields, hit Save.
4. Reload → no more redirect, About Me shows saved data.
5. Navigate to Timetable, verify the digest generates. If empty (no matching events), that's OK if the pool is empty; check the backend log for `no events available` vs `about_me_required`.
6. Give a like on an event → observe backend log for `refresh_taste_centroids`.
7. Post a feedback comment "hasse EDM" on a party event → check DB: `users.taste_facets['party']['disliked.genres']['edm']` should appear (after the BackgroundTask completes; may take a second).

If any step fails, fix inline and re-verify.

- [ ] **Step 5: Final commit and push (only if requested)**

If everything is green:

```
git status
```

If the working tree is clean, done. Otherwise stage remaining edits and commit with a descriptive message.

---

## Rollback

If the migration causes issues on a real DB:

```
alembic downgrade -1
```

drops the three new columns. The alias `refresh_taste_centroid = refresh_taste_centroids` keeps old imports functional.

---

## Non-goals reminder (from the spec)

- No external music APIs.
- No artist extraction.
- No implicit signals.
- No weekday/price autolearning loop.
- No recency decay.
- No ML-based ranker.
- No hard diversification cap on the digest.
