"""Schema for events extracted from arbitrary web pages.

Structurally strict (so injection-shaped payloads fail validation),
content-wise lenient (so real-world pages with missing fields still ingest)."""
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

_LOCAL_TZ = ZoneInfo("Europe/Berlin")


class WebExtractedEvent(BaseModel):
    """Output shape required from the extractor LLM. Everything optional except
    the three fields we cannot derive a sensible default for."""

    title: str
    start_datetime: datetime
    source_url: str

    category: str | None = None
    is_free: bool | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    end_datetime: datetime | None = None
    price_min: float | None = None
    price_max: float | None = None
    description: str | None = None
    summary: str | None = None
    image_url: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("title", "source_url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def _stamp_local_if_naive(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        if v.tzinfo is None:
            return v.replace(tzinfo=_LOCAL_TZ)
        return v


from urllib.parse import urlparse

from app.ingestion.normalize import NormalizedEvent
from app.schemas.common import EVENT_CATEGORIES

_SOURCE_TAG = "web_search"


def _origin_match(a: str, b: str) -> bool:
    import tldextract
    if urlparse(a).scheme not in ("http", "https") or urlparse(b).scheme not in ("http", "https"):
        return False
    ea = tldextract.extract(a)
    eb = tldextract.extract(b)
    if not ea.domain or not eb.domain:
        return False
    return (ea.domain, ea.suffix) == (eb.domain, eb.suffix)


def _stable_external_id(source_url: str, start_iso: str, title: str) -> str:
    h = hashlib.sha1(f"{source_url}|{start_iso}|{title}".encode("utf-8")).hexdigest()
    return h[:16]


def map_to_normalized_event(
    extracted: WebExtractedEvent,
    *,
    input_url: str,
) -> NormalizedEvent | None:
    """Map a (validated) WebExtractedEvent to a NormalizedEvent, applying safe
    defaults. Returns None if the origin-check fails (event must come from the
    same host the agent asked us to fetch)."""
    if not _origin_match(extracted.source_url, input_url):
        return None

    category = extracted.category if extracted.category in EVENT_CATEGORIES else "other"
    is_free = bool(extracted.is_free) if extracted.is_free is not None else False
    external_id = _stable_external_id(
        extracted.source_url,
        extracted.start_datetime.isoformat(),
        extracted.title,
    )

    try:
        return NormalizedEvent(
            external_id=external_id,
            source=_SOURCE_TAG,
            title=extracted.title,
            description=extracted.description,
            summary=extracted.summary,
            start_datetime=extracted.start_datetime,
            end_datetime=extracted.end_datetime,
            venue_name=extracted.venue_name,
            venue_address=extracted.venue_address,
            latitude=None,
            longitude=None,
            category=category,
            tags=list(extracted.tags),
            price_min=extracted.price_min,
            price_max=extracted.price_max,
            is_free=is_free,
            currency="EUR",
            image_url=extracted.image_url,
            source_url=extracted.source_url,
            raw_data={},
        )
    except ValidationError as exc:
        logger.info("web_research mapping rejected by NormalizedEvent: %s", exc.errors()[:1])
        return None
