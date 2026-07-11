import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.agent import retrieval
from app.agent.categories import USER_SELECTABLE_CATEGORIES
from app.agent.memory import get_current_user_id
from app.agent.prompts import CURATION_PROMPT
from app.agent.schemas import LLMDigestResponse
from app.api.deps import DbSession
from app.db.models import DigestCache, Event, User
from app.schemas.common import EventCard
from app.schemas.digest import DigestPick, DigestResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/digest", tags=["digest"])


_agent_singleton = None

# Digest agent is read-only with respect to long-term memory: it must not be
# able to call edit_facts or edit_taste_summary. The prompt declares this, and
# we enforce it here by gating the tool set.
DIGEST_TOOLS = [
    "search_events",
    "get_recommendations",
    "record_feedback",
    "save_to_calendar",
    "get_calendar",
    "get_user_profile",
    "update_user_profile",
]


def get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        from app.agent.runtime import build_agent
        _agent_singleton = build_agent(tools_enabled=DIGEST_TOOLS)
    return _agent_singleton


def _get_today() -> date:
    return datetime.now(timezone.utc).date()


def _event_to_card(e: Event) -> EventCard:
    return EventCard(
        id=e.id, title=e.title, description=e.description,
        start_datetime=e.start_datetime, end_datetime=e.end_datetime,
        venue_name=e.venue_name, venue_address=e.venue_address,
        category=e.category, tags=e.tags,
        price_min=e.price_min, price_max=e.price_max,
        is_free=e.is_free, currency=e.currency,
        image_url=e.image_url, source_url=e.source_url, source=e.source,
        is_active=e.is_active,
    )


def _serialise_event_for_prompt(e: Event) -> dict:
    return {
        "id": e.id,
        "title": e.title,
        "description": (e.description or "")[:500],
        "category": e.category,
        "start_datetime": e.start_datetime.isoformat(),
        "venue_name": e.venue_name,
        "is_free": e.is_free,
        "price_min": e.price_min,
    }


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_candidate(content: str) -> str | None:
    m = _FENCED_JSON_RE.search(content)
    if m:
        return m.group(1)
    text = content.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    m = _BARE_JSON_RE.search(content)
    return m.group(0) if m else None


def _parse_picks_fallback(messages: list) -> LLMDigestResponse | None:
    """Best-effort recovery when the model didn't honour response_format.

    Some OpenRouter models lack function-calling and return JSON as plain text
    (often wrapped in ```json fences and prefixed with prose) instead of
    populating structured_response. Find the JSON block, remap a common schema
    slip (`id` -> `event_id`), validate.
    """
    if not messages:
        return None
    content = getattr(messages[-1], "content", None)
    if not isinstance(content, str):
        return None

    candidate = _extract_json_candidate(content)
    if candidate is None:
        return None

    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None

    for pick in data.get("picks", []) if isinstance(data, dict) else []:
        if isinstance(pick, dict) and "event_id" not in pick and "id" in pick:
            pick["event_id"] = pick.pop("id")

    try:
        return LLMDigestResponse.model_validate(data)
    except ValidationError:
        return None


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
            indented = notes.strip().replace("\n", "\n      ")
            cat_lines.append(f"    notes: {indented}")
        if not cat_lines:
            cat_lines.append("    (nothing listed)")
        lines.append(f"  {cat}:")
        lines.extend(cat_lines)
    return "\n".join(lines)


def _build_response(picks_raw: list[dict], db, today: date, generated_at: datetime, is_cached: bool) -> DigestResponse:
    ids = [p["event_id"] for p in picks_raw]
    rows = {r.id: r for r in db.query(Event).filter(Event.id.in_(ids)).all()}
    picks: list[DigestPick] = []
    for p in picks_raw:
        e = rows.get(p["event_id"])
        if e is None:
            continue
        picks.append(DigestPick(event=_event_to_card(e), justification=p["justification"]))
    return DigestResponse(date=today, picks=picks, generated_at=generated_at, is_cached=is_cached)


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
        about_me=user.about_me or "(nothing written)",
        active_categories=", ".join(user.active_categories) or "(none)",
        inactive_categories=", ".join(inactive) or "(none)",
        taste_prose=_format_taste_prose(user),
        event_pool=json.dumps([_serialise_event_for_prompt(e) for e in pool], indent=2),
    )

    agent = get_agent()
    result = agent.invoke(
        {"messages": [SystemMessage(content=prompt), HumanMessage(content="Pick today's events.")]},
        config={"configurable": {"thread_id": f"digest:{user.id}:{today.isoformat()}"}},
        response_format=LLMDigestResponse,
    )
    structured = result.get("structured_response") if isinstance(result, dict) else None
    if structured is None or not getattr(structured, "picks", None) or len(structured.picks) < 3:
        fallback = _parse_picks_fallback(result.get("messages", []) if isinstance(result, dict) else [])
        if fallback is not None and len(fallback.picks) >= 3:
            logger.info("digest: recovered picks from message content fallback")
            structured = fallback
        else:
            logger.warning("digest: agent returned malformed structured_response: %r", result)
            raise HTTPException(status_code=502, detail="could not generate digest, please refresh")

    picks_raw = [{"event_id": p.event_id, "justification": p.justification} for p in structured.picks]
    generated_at = datetime.now(timezone.utc)

    db.add(DigestCache(
        id=str(uuid.uuid4()),
        user_id=user.id,
        date=today,
        picks=picks_raw,
        generated_at=generated_at,
    ))
    db.commit()

    return _build_response(picks_raw, db, today, generated_at, is_cached=False)


def _load_user_or_404(db, user_id: str) -> User:
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return u


@router.get("", response_model=DigestResponse)
def get_digest(db: DbSession) -> DigestResponse:
    user_id = get_current_user_id()
    user = _load_user_or_404(db, user_id)
    today = _get_today()

    cached = db.query(DigestCache).filter_by(user_id=user_id, date=today).one_or_none()
    if cached:
        return _build_response(cached.picks, db, today, cached.generated_at, is_cached=True)

    return _generate_digest(db, user, today)


@router.post("/refresh", response_model=DigestResponse)
def refresh_digest(db: DbSession) -> DigestResponse:
    user_id = get_current_user_id()
    user = _load_user_or_404(db, user_id)
    today = _get_today()

    existing = db.query(DigestCache).filter_by(user_id=user_id, date=today).one_or_none()
    if existing is not None:
        db.delete(existing)
        db.commit()
    return _generate_digest(db, user, today)
