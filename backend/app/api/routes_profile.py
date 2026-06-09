from fastapi import APIRouter, HTTPException

from app.agent.memory import get_current_user_id
from app.api.deps import DbSession
from app.db.models import User
from app.schemas.common import UserSettings
from app.schemas.profile import OnboardingRequest, UserProfileResponse, UserProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


def _to_response(u: User) -> UserProfileResponse:
    return UserProfileResponse(
        city=u.city,
        interest_tags=u.interest_tags,
        about_me=u.about_me,
        taste_summary=u.taste_summary,
        settings=UserSettings(**(u.settings or {})),
    )


@router.get("", response_model=UserProfileResponse)
def get_profile(db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    return _to_response(u)


@router.put("", response_model=UserProfileResponse)
def update_profile(payload: UserProfileUpdate, db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        raise HTTPException(status_code=404, detail="user not onboarded")
    if payload.interest_tags is not None:
        u.interest_tags = payload.interest_tags
    if payload.about_me is not None:
        u.about_me = payload.about_me
    u.taste_summary_dirty = True
    db.commit()
    db.refresh(u)
    return _to_response(u)


@router.post("/onboard", response_model=UserProfileResponse)
def onboard(payload: OnboardingRequest, db: DbSession) -> UserProfileResponse:
    user_id = get_current_user_id()
    u = db.query(User).filter_by(id=user_id).one_or_none()
    if u is None:
        u = User(id=user_id)
        db.add(u)
    u.interest_tags = payload.interest_tags
    u.about_me = payload.about_me
    u.taste_summary_dirty = True
    db.commit()
    db.refresh(u)
    return _to_response(u)
