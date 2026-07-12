"""Per-category candidate retrieval.

Keyword-first: SQL substring matches from the user's About Me pills,
then semantic add from the category centroid, then a generic fill up to
GENERIC_FLOOR. The digest generator and the get_recommendations tool
both call get_category_candidates."""
from datetime import date, datetime, time, timezone
from math import ceil

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.db.models import Event, User
from app.rag import chroma_store
from app.rag.chroma_store import QueryHit


GENERIC_FLOOR = 30
SEMANTIC_TOP_UP = 15
POOL_TARGET = 50


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
    """Dislike hard-filter is currently disabled.

    Preserved as a call site so re-enabling is a one-line change: revert
    this function to iterate _iter_disliked_terms and substring-match
    against event title/description/tags."""
    return list(event_ids)


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

    - venues.*  -> LOWER(venue_name)  LIKE '%term%'
    - artists.* -> LOWER(title) OR LOWER(description) LIKE '%term%'
    - genres.*  -> same as artists.* (tags column does not carry musical subgenres)

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
        q = session.query(Event.id).filter(Event.category == category)
        if date_lo is not None:
            q = q.filter(Event.start_datetime >= date_lo)
        if date_hi is not None:
            q = q.filter(Event.start_datetime <= date_hi)
        if field == "venues":
            # Chip input strips whitespace, but ingested venue names keep
            # spaces/hyphens (e.g. pill "beatboutique" vs DB "Beat Boutique").
            # Normalize both sides so the substring match is not doomed.
            venue_norm = func.replace(
                func.replace(func.lower(Event.venue_name), " ", ""),
                "-", "",
            )
            term_norm = term.lower().replace(" ", "").replace("-", "")
            q = q.filter(venue_norm.like(f"%{term_norm}%"))
        else:
            like = f"%{term.lower()}%"
            q = q.filter(or_(
                func.lower(Event.title).like(like),
                func.lower(Event.description).like(like),
            ))
        q = q.order_by(Event.start_datetime.asc()).limit(per_pill_cap)
        for (eid,) in q.all():
            if eid not in seen:
                seen[eid] = QueryHit(event_id=eid, similarity_score=None, source="keyword")
    return list(seen.values())


def _per_pill_cap(user: User, category: str) -> int:
    """Compute per-pill row cap so the pool trends toward POOL_TARGET.

    Minimum of 1 per pill. If no pills are declared, the caller does not
    invoke this — but return 1 as a safe default."""
    n = len(_iter_pills_for_category(user, category))
    if n <= 0:
        return 1
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
            seen[eid] = QueryHit(event_id=eid, similarity_score=None, source="fill")

    # Dislike hard-filter is a pass-through — call kept to preserve the seam.
    kept = set(filter_out_disliked(session, user, category, list(seen.keys())))
    return [seen[eid] for eid in seen if eid in kept]
