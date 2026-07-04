"""LLM-based event categorization with content-hash caching.

Runs between adapter fetch and DB upsert. Treats the scraper's substring-
mapped category as a hint, not authority. Cache keyed on the hash of the
event's semantic fields (title, description, venue, tags, provider hint)
so each unique event is classified exactly once across ingestion runs."""
import hashlib
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel

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
