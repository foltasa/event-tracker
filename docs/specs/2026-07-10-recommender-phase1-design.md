# Recommender System — Phase 1 Design

**Status:** Draft v1 · **Date:** 2026-07-10 · **Author:** Alexander Foltas
**Companion documents:** `docs/PRD.md`, `docs/specs/2026-06-08-event-tracker-tech-design.md`
**Successor:** Phase 2 (MusicBrainz + Last.fm artist enrichment) will follow in a separate spec.

---

## 1. Motivation

The current recommender is a single global taste centroid over embeddings of liked events. It has three shortcomings that block the "Spotify-level personalization" the product aims for:

1. **Categories are mixed in the vector space.** A user who likes a punk concert and a Kabarett night gets a centroid that's the mean of both. Retrieval returns odd cross-category hits that fit neither taste.
2. **No structural taste representation.** Similar artists, disliked genres, favourite venues, weekday preferences — all invisible to the ranker and to the LLM.
3. **Negative signals are inert.** Dislikes are stored but never affect ranking. `saved_to_calendar` (the strongest positive signal we have) is treated the same as a thumbs-up.

Phase 1 rebuilds the taste model to fix these three points **without any external music-metadata API**. Phase 2 will layer MusicBrainz + Last.fm on top of the same data model.

---

## 2. Goals and non-goals

### Goals

1. Per-category taste representation with an isolated centroid **and** structured facets per top-level category.
2. Saved-to-calendar and dislike signals both change the ranker's behaviour.
3. Free-text feedback comments are structurally distilled into facets by an LLM-based extractor.
4. A persistent "About Me" page lets the user directly view and edit what the assistant knows, and lets them activate or deactivate whole categories.
5. Ranking is two-stage: deterministic retrieval per category → LLM re-rank with the user's structured taste in the prompt.
6. The data model is designed so Phase 2 (artist enrichment via MusicBrainz + Last.fm) is a strict additive change — no re-shape of Phase 1 structures.

### Non-goals (Phase 1)

- Any external music-metadata API. Deferred to Phase 2.
- Artist name extraction from event titles. Deferred to Phase 2 (the same extraction serves both MB resolution and facet updates).
- Implicit signals (clicks, dwell time, skips). Not tracked.
- Weekday / price-sensitivity autolearning as a separate loop. Weekday preference is a facet field the extractor *may* populate; there is no dedicated learning loop.
- Recency decay on feedback. Old likes and new likes count equally.
- ML-based ranker. The ranker is heuristic retrieval + LLM re-rank.
- Diversification / dedup of the final digest. Existing `(source, external_id)` dedup is enough; the digest may contain multiple events from the same category, artist, or venue.

---

## 3. Data model

### 3.1 User table — new columns

The existing `users` table (`backend/app/db/models/user.py`) gains three columns:

```python
# Per-category taste vectors — mean of positive-signal event embeddings.
taste_centroids: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
# {
#   "concerts": [floats...],
#   "party":    [floats...],
#   ...
# }

# Per-category structured facets — LLM- and user-editable.
taste_facets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
# {
#   "concerts": {
#     "artists":  {"Die Sterne": 0.9, "Tocotronic": 0.7},
#     "genres":   {"punk": 0.9, "hamburger schule": 0.8},
#     "venues":   {"Knust": 0.6, "Molotow": 0.5},
#     "disliked": {"genres": {"edm": 1.0}, "artists": {}},
#     "weekday_pref": {"fri": 0.9, "sat": 0.8, "mon": 0.1},
#     "notes": "free-text notes from the About Me form"
#   },
#   ...
# }

# Which categories the user wants the assistant to consider.
# None = never opened About Me → frontend redirects to About Me.
# []   = user consciously turned everything off.
# ["concerts", "theater"] = active.
active_categories: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
```

The existing `taste_centroid: list[float] | None` column stays as a **fallback** for chat-tool paths that don't have a category (e.g. an untargeted `get_recommendations` call with no category param and no `active_categories`). It is recomputed as the mean of per-category centroids on refresh. If all per-category centroids are missing, it becomes `None`.

The existing `taste_summary` and `facts_md` columns are unchanged. Note: `facts_md` is **no longer fed by the comment extractor** in Phase 1 and is **not injected into the digest re-rank prompt** (see §7.2). It remains as a chat-context field editable via the existing `edit_facts` tool.

### 3.2 Categories

The set of top-level categories is the classifier taxonomy from `backend/app/ingestion/categorize_prompts.py`:

```
concerts, party, comedy, theater, arts, literature,
film, family, food, sports, outdoor
```

`other` and `unknown` are classifier fallbacks and are **not** exposed as user-selectable categories in About Me. Events classified as `other` or `unknown` never make it into the digest via the per-category flow.

### 3.3 Feedback and SavedEvent

No schema change. The signal weighting lives in the centroid-refresh code.

### 3.4 Events

No schema change. Category filtering uses the existing `category` column and the existing Chroma metadata field.

### 3.5 Migration

`backend/app/db/migrations/versions/0006_taste_per_category.py`:

- Add `taste_centroids`, `taste_facets`, `active_categories` columns with defaults.
- One-shot backfill: for every existing user, run the new per-category centroid refresh (see §4.2) over the user's existing feedback and saved events.
- Do not drop or migrate `taste_centroid`; it stays as the fallback field, recomputed by the refresh code as the mean of per-category centroids.

---

## 4. Signals and taste refresh

### 4.1 Signal weights

| Signal | Weight | Effect |
|---|---|---|
| `saved_to_calendar` | +2.0 | Contributes to `taste_centroids[category]` and `taste_facets[category]` |
| `feedback.sentiment = "like"` | +1.0 | Contributes to `taste_centroids[category]` and `taste_facets[category]` |
| `feedback.sentiment = "dislike"` (no comment) | — | Recorded in `feedback` table only. **Does not contribute to the centroid** and **does not update facets**. Phase 1 has no artist extraction, so a dislike without a comment carries no structured signal. |
| `feedback.sentiment = "dislike"` (with comment) | LLM-extracted | Comment goes through the extractor (§5), which typically produces `disliked.artists` / `disliked.genres` updates. **Does not contribute to the centroid.** |
| `feedback.comment` (any sentiment) | LLM-extracted | Updates `taste_facets[category]` fields per the extractor (§5) |

### 4.2 Centroid refresh (per category)

Replaces `refresh_taste_centroid` in `backend/app/agent/memory.py`.

```
def refresh_taste_centroids(session, user_id):
    for category in CATEGORIES:
        pos_ids = collect_positive_event_ids(session, user_id, category)
        # pos_ids is (event_id, weight) pairs:
        #   liked events → weight 1.0
        #   saved events → weight 2.0 (even if not also liked)
        if not pos_ids:
            user.taste_centroids.pop(category, None)
            continue
        embeddings = get_embeddings_for_ids([eid for eid, _ in pos_ids])
        matrix = weighted_mean(embeddings, weights)
        user.taste_centroids[category] = matrix.tolist()

    # Fallback centroid = mean of per-category centroids (or None if empty).
    if user.taste_centroids:
        user.taste_centroid = np.mean(list(user.taste_centroids.values()), axis=0).tolist()
    else:
        user.taste_centroid = None
```

Trigger points (same as today):

- On `record_feedback` if sentiment changes or a save happens.
- On `save_to_calendar`.
- Idempotent, safe to run redundantly.

---

## 5. Comment extractor

New module: `backend/app/agent/comment_extractor.py`.

**Trigger:** any `Feedback` row with a non-empty `comment`, and the "notes" free-text fields from About Me (see §6.2).

**Execution mode:** asynchronous via FastAPI `BackgroundTasks`. The feedback POST returns immediately after DB write; the extractor runs after response is sent. On failure the pending comment is re-queued on the next digest generation trigger.

**LLM contract:**

Input: event context (title, category, venue, description snippet) + user comment + current facets (for the category) as JSON.

Output (structured, LangChain `PydanticOutputParser` or equivalent):

```python
class FacetUpdate(BaseModel):
    category: str            # must be in CATEGORIES
    field: Literal["artists", "genres", "venues",
                   "disliked.artists", "disliked.genres", "weekday_pref"]
    key: str                 # e.g. "Tocotronic", "edm", "fri"
    delta: float             # -1.0 .. +1.0

class ExtractorOutput(BaseModel):
    facet_updates: list[FacetUpdate]
```

**Application:** For each update:

```
current = facets[cat][field].get(key, 0.0)
new = clamp(current + delta, 0.0, 1.0)
facets[cat][field][key] = new
if new == 0.0:
    del facets[cat][field][key]
```

**Errors:** LLM failure → structured error logged, extraction re-queued via a `pending_extraction` flag on the feedback row. No fallback to `facts_md`.

---

## 6. About Me page

### 6.1 Route and redirect logic

New page: `frontend/app/about-me/page.tsx`. Reachable via top-nav at all times.

On app start, if `user.active_categories is None`, the frontend redirects to `/about-me` with a hint text. Once the user saves the About Me form for the first time, `active_categories` is set to a list (possibly empty) and the redirect no longer fires.

### 6.2 UI structure

```
[About Me]

Which categories should the assistant consider for you?
  ☐ concerts     ☐ party        ☐ comedy       ☐ theater
  ☐ arts         ☐ literature   ☐ film         ☐ family
  ☐ food         ☐ sports       ☐ outdoor
                          [ Save active categories ]

For each ticked category, an inline section appears:

──────────────  concerts  ──────────────
Favourite artists:        [free text, comma-separated]
Favourite genres:          [multi-select from a small vocab + free text]
Favourite venues:          [free text]
Anything else?             [textarea → routed through comment extractor]

──────────────  theater  ──────────────
Favourite houses / stages: [free text]
Preferred formats:         [multi-select: musical, classical, modern drama...]
Anything else?             [textarea]

...

What the assistant has learned about you so far:
  [Editable textarea, backed by user.taste_summary]
```

### 6.3 Category catalogue

Per-category form field definitions (structural only; frontend renders them):

| Category | Fields (all optional) |
|---|---|
| concerts | artists, genres, venues, notes |
| party | dj_or_acts, genres, venues, notes |
| comedy | artists, formats, venues, notes |
| theater | venues, formats, notes |
| arts | artists_or_venues, formats, notes |
| literature | authors, formats, notes |
| film | directors, genres, cinemas, notes |
| family | child_ages, interests, notes |
| food | cuisines, formats, notes |
| sports | disciplines, teams, notes |
| outdoor | activities, notes |

Field-name conventions in `taste_facets` are unified to `artists / genres / venues / notes / weekday_pref / disliked`. When a category's form uses a different label (e.g. `dj_or_acts` for `party`, `authors` for `literature`), it is stored under `taste_facets[category].artists`. This keeps the extractor and ranker schema uniform.

### 6.4 Save semantics

- Ticking a category adds it to `active_categories`.
- Unticking a category removes it from `active_categories` but leaves `taste_facets[category]` and `taste_centroids[category]` intact in the DB.
- Filling per-category fields writes to `taste_facets[category]` with initial weight `0.8` (not `1.0`, so later like/save events can still increase the weight).
- The category `notes` field is enqueued through the same comment extractor (§5) with a synthetic Feedback-like context.
- The "What the assistant has learned" textarea writes directly to `user.taste_summary`.

### 6.5 Backend endpoints

- `GET /api/about-me` → returns `{active_categories, taste_facets, taste_summary}`
- `PUT /api/about-me` → accepts a partial replacement of the above; validates category names against the vocabulary and stores.
- Existing `/api/profile` endpoints remain for `interest_tags` and `about_me` (which are the first-time cold-start fields, still used for cold-start seeding).

---

## 7. Retrieval and ranking

### 7.1 Retrieval — per-category candidates

New helper `get_category_candidates(user, category, date_range, k)`:

```
def get_category_candidates(user, category, date_range, k=30):
    if category not in user.active_categories:
        return []

    centroid = user.taste_centroids.get(category)
    if centroid is None:
        seed_text = build_cold_start_seed(user, category)
        # cold-start seed uses:
        #   1) facets[category] artists/genres/venues if present
        #   2) user.interest_tags otherwise
        #   3) None → return []
        if not seed_text:
            return []
        vector = embed_one(seed_text)
    else:
        vector = centroid

    where = {
        "category": category,
        "start_time": {"$gte": ..., "$lte": ...},
    }
    return chroma_store.query_by_vector(vector, n=k, where=where)
```

**Hard filters applied at the candidate stage** (not delegated to the LLM):

- Disliked artists/genres in `facets[category].disliked` are matched by **case-insensitive substring** against event `title`, `description`, and `tags`. Matches are removed from the candidate pool. Substring matching is the Phase 1 approximation; Phase 2 replaces it with MBID-based matching on `event_artists`.
- Events in inactive categories never reach the candidate stage.

Chroma stays as a single collection. Category isolation is a metadata filter — the collection already stores `category` in event metadata (`chroma_store.py`).

### 7.2 Ranking — two-stage

Stage 1 — deterministic backend:

```
candidates = []
for category in user.active_categories:
    candidates += get_category_candidates(user, category, date_range, k=30)
```

Stage 2 — LLM re-rank:

Prompt inputs:
- `active_categories` and `inactive_categories`
- `taste_facets` (compact, per active category)
- Aggregated `disliked` set (repeated as an explicit reminder even though hard-filtered)
- `taste_summary`
- Candidate list (title, category, venue, similarity score, snippet)
- User's stated digest size (default: 3–5)

Output (structured):

```python
class DigestPick(BaseModel):
    event_id: str
    justification: str  # one paragraph, in the user's language

class DigestOutput(BaseModel):
    picks: list[DigestPick]
```

**Not injected into the prompt:** `facts_md` (see §3.1). It stays as a chat-context read-only field.

**No hard diversification cap.** The LLM is free to return N events of the same category, same venue, or same day if that's the best match for the user's structural taste.

### 7.3 Chat tools

- `get_recommendations(category=None, date_range, n)`:
  - if `category is None` and `active_categories` is populated → results are drawn from `active_categories` implicitly.
  - if `category` is passed explicitly → honored, even if not in `active_categories` (user intent overrides).
  - if `active_categories` is `None` or `[]` and no category param → returns `[]` with a structured error hint `"no_active_categories"` for the agent to surface.
- `search_events(...)`: unchanged. Explicit search is user-driven; category filter is respected only via the `categories` param.
- `get_user_profile()`: extended return shape to include `active_categories` and `taste_facets` so the LLM sees the structured taste in every turn.

### 7.4 Cold-start semantics

1. `active_categories is None` → frontend forces About Me. No digest is generated.
2. `active_categories == []` → digest is empty. Frontend shows "activate categories in About Me" hint.
3. `active_categories = [...]` with facets but no centroids → cold-start seed per category from facets.
4. `active_categories = [...]` with neither facets nor centroids but `interest_tags` present → seed from `interest_tags` (concatenated as text), embedded once, used as the query vector for each active category's Chroma query. Chroma metadata `category` filter still applies per query, so results are category-scoped even from a shared seed.
5. Fully populated → the normal per-category retrieval flow.

---

## 8. Phase 2 preparation

Phase 2 (MusicBrainz + Last.fm enrichment) will layer on top of the Phase 1 data model without reshaping it:

- `taste_facets[category].artists` in Phase 1 is `{name: weight}`. Phase 2 migrates to `{name: {weight, mbid}}`. Both shapes are read-tolerant if we key on `name`.
- A new `event_artists` table will be introduced in Phase 2 by an artist-extraction pipeline that runs against existing events as a backfill. Nothing in Phase 1 touches event tables.
- The comment extractor gains a post-processing step in Phase 2: after `facet_updates`, look up newly added artists in MB → Last.fm and expand `taste_facets[category].artists` with similar artists at attenuated weight. The hook point (a `post_process` callback in the extractor pipeline) is present in Phase 1 as a no-op.
- The hard-filter step in retrieval will optionally match `event_artists.mbid` against `disliked.artists` and `favourite artists` for structural matches instead of substring matches. Phase 1 uses substring matching.

---

## 9. Success criteria for Phase 1

Concrete, testable outcomes after Phase 1 ships:

1. The digest never mixes categories the user has deactivated.
2. A dislike on an event whose title contains "EDM" measurably suppresses future events with "EDM" in title/description/tags in the digest.
3. A save-to-calendar changes the next digest's suggestions (via the +2.0 weighted centroid), demonstrably more strongly than an equivalent like.
4. A comment "hasse EDM in großen Venues" causes:
   - `facets[category].disliked.genres["edm"]` to increase, and
   - subsequent digests to filter EDM events at the candidate stage.
5. The About Me page renders, saves, and round-trips `active_categories` and `taste_facets`. Deselecting a category preserves its data in the DB.
6. Cold-start: a brand-new user who fills only About Me (no likes/saves yet) gets a non-empty digest whose picks come from per-category cold-start seeds.
7. `get_recommendations` in chat, with no explicit category, respects `active_categories`.

---

## 10. Open implementation questions

Deferred to the implementation plan:

- Exact vocabulary of category-specific `formats` / `genres` multi-select choices.
- Whether the comment extractor is invoked synchronously as a fallback when `BackgroundTasks` cannot be scheduled (test environments).
- Weight-decay policy for facets: should un-touched weights slowly decay? Phase 1 defaults to no decay; revisit if facet growth causes prompt bloat.
- Prompt template design for the Stage-2 re-rank (compactness of the facets serialization matters here).
- Whether `taste_summary` is auto-regenerated after every N feedback events, or only on-demand via the existing `edit_taste_summary` tool. Phase 1 keeps the current on-demand behaviour.

---

## 11. What this document does not cover

- Prompt templates for the comment extractor and digest re-rank (implementation plan).
- Frontend component decomposition for the About Me page (implementation plan).
- Test matrix (implementation plan).
- Phase 2 (MusicBrainz + Last.fm) — separate spec.
