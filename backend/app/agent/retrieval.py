"""Per-category candidate retrieval + disliked-substring hard-filter.

Both the digest generator and the get_recommendations tool call into
this module."""
from datetime import date, datetime, time, timezone

from sqlalchemy import func, or_
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
    """Dislike hard-filter is currently disabled.

    Preserved as a call site so re-enabling is a one-line change: revert
    this function to iterate _iter_disliked_terms and substring-match
    against event title/description/tags."""
    return list(event_ids)


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
