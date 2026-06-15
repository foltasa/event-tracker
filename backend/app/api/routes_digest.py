import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

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
        id=e.id, title=e.title, summary=e.summary,
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


def _candidate_pool(db, today: date) -> list[Event]:
    end = datetime.combine(today + timedelta(days=7), datetime.max.time(), tzinfo=timezone.utc)
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    return (
        db.query(Event)
        .filter(Event.is_active == True, Event.start_datetime >= start, Event.start_datetime <= end)  # noqa: E712
        .order_by(Event.start_datetime.asc())
        .limit(150)
        .all()
    )


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
    pool = _candidate_pool(db, today)
    if not pool:
        raise HTTPException(status_code=503, detail="no events available")

    prompt = CURATION_PROMPT.format(
        interests=", ".join(user.interest_tags) or "(none)",
        about_me=user.about_me or "(none)",
        facts_md=user.facts_md or "(empty)",
        taste_summary=user.taste_summary or "(empty)",
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
