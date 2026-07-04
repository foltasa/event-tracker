"""LLM-based event categorization with content-hash caching.

Runs between adapter fetch and DB upsert. Treats the scraper's substring-
mapped category as a hint, not authority. Cache keyed on the hash of the
event's semantic fields (title, description, venue, tags, provider hint)
so each unique event is classified exactly once across ingestion runs."""
import hashlib
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.normalize import NormalizedEvent
from app.schemas.common import EventCategory


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def content_hash(event: NormalizedEvent) -> str:
    """Return a stable sha256 hex over the event's semantic identity.

    Fields included: title, description (HTML-stripped), venue_name, tags
    (order-independent), and event.category (the provider's hint). Anything
    that can change without affecting classification — datetime, price,
    external_id, source_url, image_url — is excluded so re-fetches of the
    same event hit the cache."""
    parts = [
        event.title or "",
        _strip_html(event.description),
        event.venue_name or "",
        "|".join(sorted(event.tags)),
        event.category,
    ]
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CategoryDecision(BaseModel):
    """LLM's classification result. `unknown` means the model was not
    confident enough to pick one of the enum values."""

    category: EventCategory | Literal["unknown"]


class CategoryCache:
    """Thin wrapper over `event_category_cache` for get/set-by-hash access.

    Uses SQLite's INSERT OR IGNORE so concurrent runs / retries never fight
    over the same key. Does not commit — caller controls transaction."""

    def __init__(self, session: Session, model_name: str):
        self._session = session
        self._model_name = model_name

    def get(self, content_hash: str) -> str | None:
        row = (
            self._session.query(EventCategoryCache)
            .filter_by(content_hash=content_hash)
            .one_or_none()
        )
        return row.category if row else None

    def set(self, content_hash: str, category: str) -> None:
        stmt = sqlite_insert(EventCategoryCache).values(
            content_hash=content_hash,
            category=category,
            model=self._model_name,
        ).on_conflict_do_nothing(index_elements=["content_hash"])
        self._session.execute(stmt)
