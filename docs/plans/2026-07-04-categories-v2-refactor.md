# Category Schema v2 Refactor Plan

Follow-up to the LLM-categorization work in `2026-07-04-llm-event-categorization.md`. This plan replaces the 10-category schema with a 12-category schema, splits `music` into `concerts` / `party`, adds `comedy` and `literature`, drops `tech`, and tightens `family` to strictly children-focused events.

## Category set (12)

| Category | Scope |
|---|---|
| `concerts` | Named act with stage performance: rock, pop, classical, opera, jazz, singer-songwriter, choirs. Seating/standing irrelevant. |
| `party` | DJ set, club night, rave, dance event. Primary activity is dancing, not listening. |
| `comedy` | Stand-up, Kabarett, sketch comedy, improv comedy. Pulled out of `theater`. |
| `theater` | Plays, musicals, multi-week tribute shows, traditional stage formats. |
| `arts` | Exhibitions, ballet, contemporary dance. (Readings move to `literature`.) |
| `literature` | Readings (Lesung), poetry slams, book launches, author talks. |
| `film` | Cinema screenings, film festivals. |
| `family` | **Strictly for/with children.** Kinderkonzert, Kindertheater, Bastelkurs. "Family-friendly" alone is NOT enough. Family wins over content categories when the event is primarily for kids. |
| `food` | Culinary events, tastings, food festivals. |
| `sports` | Sports matches, tournaments, competitions. |
| `outdoor` | Hiking, nature events, park festivals without a clear content category. |
| `other` | Everything else. |

Removed: `music`, `tech`.

## File touch list

**Backend:**
- `backend/app/schemas/common.py` — `EventCategory` Literal + `EVENT_CATEGORIES` frozenset
- `backend/app/ingestion/categorize_prompts.py` — rewrite `SYSTEM_PROMPT`
- `backend/app/ingestion/scrapers/theater_hamburg.py` — `_CATEGORY_MAP`
- `backend/app/ingestion/scrapers/hamburg.py` — `_CATEGORY_MAP`
- `backend/app/ingestion/eventbrite.py` — `_CATEGORY_MAP`
- `backend/app/ingestion/ticketmaster.py` — `_SEGMENT_MAP` + `_GENRE_OVERRIDE`
- `backend/app/agent/tools.py` — docstring example (uses `["music", "tech"]`)
- `backend/app/db/migrations/versions/0007_categories_v2.py` — new migration
- `backend/app/db/migrations/migration_0007_helpers.py` — cache purge + remap helper

**Frontend:**
- `frontend/lib/types.ts` — `EventCategory` union
- `frontend/components/FeedFilters.tsx` — `CATEGORIES` array
- `frontend/fixtures/*.json` — replace `"music"` → `"concerts"`, `"tech"` → `"other"` where present

**Tests:**
- `backend/tests/ingestion/test_categorize.py` — enum-iteration test (Task 4)
- `backend/tests/ingestion/test_categorize_prompts.py` — category presence assertions
- Frontend `__tests__/*` — anything asserting on `music`/`tech`

## Scraper mapping changes

Provider hints go into `event.category` and must be valid enum values. LLM refines afterwards, but the raw hint must pass Pydantic validation.

**theater_hamburg** (`_CATEGORY_MAP`):
- `konzert`, `musik`, `klassik`, `jazz`, `oper` → `concerts` (was `music`; oper was `theater`)
- `comedy`, `kabarett` → `comedy` (was `theater`)
- `lesung` → `literature` (was `arts`)
- `musical` → stays `theater`
- Rest unchanged

**hamburg** (`_CATEGORY_MAP`):
- `musik`, `konzert` → `concerts`
- `comedy` → `comedy` (was `theater`)
- `tech`, `technologie` → **remove** (fall through to `other`)
- Rest unchanged

**eventbrite** (`_CATEGORY_MAP`):
- `music` → `concerts`
- `science & tech` → **remove** (fall through to `other`)
- Rest unchanged

**ticketmaster** (`_SEGMENT_MAP` + `_GENRE_OVERRIDE`):
- `music` → `concerts` (in `_SEGMENT_MAP`)
- `classical`, `opera` → `concerts` (in `_GENRE_OVERRIDE`; opera was `theater`)
- `comedy` → `comedy` (was `theater`)
- Rest unchanged

## Migration 0007 design

Same helper-plus-thin-wrapper pattern as 0006.

1. **Purge cache** — `DELETE FROM event_category_cache`. All existing hashes are invalidated because (a) the schema of `event.category` changed so `content_hash` inputs differ, and (b) the prompt changed so decisions may differ.
2. **Safety remap** — bulk `UPDATE events SET category='other' WHERE category IN ('music','tech')`. Pydantic-based reads would fail otherwise between the migration and the LLM loop.
3. **Reclassify all** — call `reclassify_all(session, LangchainClassifier(), settings.categorization_model)` from the fixed Task-11 CLI helper. Iterates every event, writes cache under post-update hash, updates `row.category` to the new decision.

Downgrade: `DROP` new categories in cache, remap `concerts`/`party`/`comedy`/`literature` rows back to `music`/`theater`/`arts` heuristically. Best-effort only — the point of downgrade is DB rollback, not perfect data recovery.

## Task sequence (subagent-driven)

### Task A: Enums synced (backend + frontend)
Update `common.py` and `types.ts` in one commit. No LLM/logic touched.

### Task B: Rewrite SYSTEM_PROMPT
Full rewrite in `categorize_prompts.py`. Must cover:
- All 12 categories with explicit examples
- Explicit family-precedence rule ("if primarily for children, choose family regardless of content")
- Concerts vs party format rule ("concerts = named act, party = DJ/club/dance")
- Literature separated from arts
- Venue signals (retained from v1)
- Provider-tag noise warning (retained)
- Multi-week-run signal (retained, indicates theater over concerts)

Also update `test_categorize_prompts.py` category-presence assertions.

### Task C: Scraper mappings
Update all four scrapers per the table above.

### Task D: Migration 0007
Create `migration_0007_helpers.py` with `purge_and_reclassify(session, classifier, model_name)`:
```python
def purge_and_reclassify(session, classifier, model_name):
    session.query(EventCategoryCache).delete()
    session.execute(
        update(Event).where(Event.category.in_(["music", "tech"])).values(category="other")
    )
    reclassify_all(session, classifier, model_name)
```
Create `versions/0007_categories_v2.py` — lazy-imports the helper and classifier inside `upgrade()`, calls the helper, commits.

Tests in `test_migration_0007.py` (use fake classifier): verify cache purge, verify old `music`/`tech` rows get reclassified to something valid, verify new decisions land in DB.

### Task E: Update Task-4 enum-iteration test + fixtures
- `test_categorize.py::test_category_decision_accepts_all_enum_values` — swap list
- Frontend fixtures + test files — replace `"music"`/`"tech"` occurrences with sensible new values (`"concerts"` for music; case-by-case for tech, probably `"other"` or drop the assertion)

### Task F: Full sanity + review
- `pytest -x -q` (backend)
- `npm test` or equivalent (frontend)
- Cross-cutting review: does the new prompt reliably produce concerts vs party? Family-precedence tested?

## Constraints
- Comments in English
- `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` on every commit
- One commit per task
- TDD where a test can meaningfully drive the change (Tasks D, E). For pure data mappings (Task C), test the mapping table indirectly by re-running scraper tests.

## Files not touched
- `docs/specs/2026-07-04-llm-event-categorization-design.md` — spec of the underlying mechanism; the schema change is a follow-up, not a redesign.
- `backend/app/ingestion/categorize.py` — mechanism unchanged.
- `backend/app/ingestion/scheduler.py` — mechanism unchanged.
