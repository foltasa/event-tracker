from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.comment_extractor import ExtractorInput, extract_and_apply
from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import User
from app.db.session import SessionLocal
from app.schemas.about_me import AboutMeResponse, AboutMeUpdate

router = APIRouter(prefix="/about-me", tags=["about-me"])


def _to_response(u: User) -> AboutMeResponse:
    return AboutMeResponse(
        active_categories=u.active_categories,
        taste_facets=dict(u.taste_facets or {}),
        taste_summary=u.taste_summary,
    )


def _extract_notes_bg(user_id: str, category: str, text: str) -> None:
    """BackgroundTask wrapper: opens its own DB session for About-Me notes."""
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


@router.get("", response_model=AboutMeResponse)
def get_about_me(db: DbSession) -> AboutMeResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return _to_response(u)


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
