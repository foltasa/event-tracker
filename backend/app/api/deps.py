"""Shared FastAPI dependencies and middleware."""
from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.agent.memory import set_current_user_id
from app.config import settings
from app.db.session import SessionLocal


async def current_user_id_middleware(request: Request, call_next):
    user_id = request.headers.get("X-User-Id") or settings.default_user_id
    set_current_user_id(user_id)
    try:
        return await call_next(request)
    finally:
        set_current_user_id(None)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]
