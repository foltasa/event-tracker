"""Eventim public-search-API adapter.

Fetches Hamburg events from Eventim's undocumented public JSON endpoint
(see docs/specs/2026-07-07-eventim-adapter-design.md). Paginates four
top-level categories, transforms products into NormalizedEvent, yields to
the caller. Anti-bot: 403/429/503 retry + persistent circuit breaker."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

import httpx

from app.ingestion.normalize import NormalizedEvent
from app.schemas.common import EventCategory

logger = logging.getLogger(__name__)


_RETRY_STATUS_CODES = {403, 429, 503}
_RETRY_MAX_ATTEMPTS = 4
_RETRY_BASE_SLEEP = 2.0  # exponential: 2s, 4s, 8s
_AKAMAI_REF_MAX = 5
_AKAMAI_REF_RE = re.compile(r"Ref(?:erence)?\s*#\s*([0-9a-fA-F.]+)")


class _HttpGetter(Protocol):
    def get(self, url: str, **kwargs) -> httpx.Response: ...


@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0
    akamai_403s: int = 0
    akamai_refs: list[str] = field(default_factory=list)


def _extract_akamai_ref(body: str) -> str | None:
    m = _AKAMAI_REF_RE.search(body)
    return m.group(1) if m else None


def get_json_with_retry(
    client: _HttpGetter,
    url: str,
    *,
    params: dict[str, Any],
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
) -> dict | None:
    """GET a JSON endpoint with exponential backoff on 403/429/503.

    Returns parsed JSON dict on 2xx, or None if all attempts exhausted or the
    status is non-retriable. On 403, extracts the Akamai Reference ID from
    the body (capped at _AKAMAI_REF_MAX in stats). Network exceptions
    propagate — callers handle them at the pagination level."""
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url, params=params)
        if 200 <= resp.status_code < 300:
            return resp.json()
        if resp.status_code == 403:
            stats.akamai_403s += 1
            ref = _extract_akamai_ref(resp.text or "")
            if ref and len(stats.akamai_refs) < _AKAMAI_REF_MAX:
                stats.akamai_refs.append(ref)
        if resp.status_code not in _RETRY_STATUS_CODES:
            logger.warning("eventim: unexpected status %d for %s — skipping", resp.status_code, url)
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            logger.warning(
                "eventim: %d from %s — sleeping %.1fs (attempt %d/%d)",
                resp.status_code, url, backoff, attempt, _RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            logger.warning(
                "eventim: giving up on %s after %d attempts",
                url, _RETRY_MAX_ATTEMPTS,
            )
    return None


_CATEGORY_MAP: dict[str, EventCategory] = {
    # Konzerte subcategories
    "Rock & Pop": "concerts",
    "HipHop & R'n'B": "concerts",
    "Schlager & Volksmusik": "concerts",
    "Jazz & Blues": "concerts",
    "Elektronische Musik": "concerts",
    "Metal & Hardrock": "concerts",
    "Weitere Konzerte": "concerts",
    # Kultur subcategories
    "Klassische Konzerte": "concerts",
    "Oper": "theater",
    "Ballett & Tanz": "theater",
    "Theater": "theater",
    # Musical & Show subcategories
    "Musical": "theater",
    "Show": "other",
    # Sport subcategories
    "Fußball": "sports",
    "Handball": "sports",
    "Weitere Sportarten": "sports",
}

_SOURCE_NAME = "eventim"
_TARGET_CITY = "Hamburg"


def _category_for(product: dict) -> EventCategory:
    """Map the leaf (sub-level) Eventim category to our EventCategory.

    Unknown leaves fall back to 'other' with a WARNING log so operators
    notice drift in Eventim's taxonomy."""
    for cat in product.get("categories", []):
        parent = cat.get("parentCategory")
        if not parent:
            continue
        name = cat.get("name")
        mapped = _CATEGORY_MAP.get(name)
        if mapped is not None:
            return mapped
        logger.warning(
            "eventim: unknown leaf category '%s' -> falling back to 'other'",
            name,
        )
        return "other"
    return "other"


def _tags_for(product: dict) -> list[str]:
    tags: list[str] = []
    for cat in product.get("categories", []):
        name = cat.get("name")
        if name and name not in tags:
            tags.append(name)
    for attr in product.get("attractions", []):
        name = attr.get("name")
        if name and name not in tags:
            tags.append(name)
    return tags


def parse_product(product: dict) -> NormalizedEvent | None:
    """Convert one Eventim product dict to a NormalizedEvent.

    Returns None when required fields are missing, type is not
    LiveEntertainment, or city is not the target. Pure - no I/O."""
    if product.get("type") != "LiveEntertainment":
        return None

    product_id = product.get("productId")
    name = product.get("name")
    live = (product.get("typeAttributes") or {}).get("liveEntertainment") or {}
    start_raw = live.get("startDate")
    location = live.get("location") or {}

    if not product_id or not name or not start_raw:
        return None
    if location.get("city") != _TARGET_CITY:
        return None

    try:
        start_dt = datetime.fromisoformat(start_raw)
    except ValueError:
        return None
    if start_dt.tzinfo is None:
        return None

    venue_name = location.get("name") or ""
    if not venue_name:
        return None

    postal = (location.get("postalCode") or "").strip()
    city = (location.get("city") or "").strip()
    venue_address = f"{postal} {city}".strip() or None

    geo = location.get("geoLocation") or {}
    lat = geo.get("latitude")
    lng = geo.get("longitude")

    price = product.get("price")
    price_min = float(price) if price is not None else None
    is_free = price_min == 0

    description = product.get("description") or None

    return NormalizedEvent(
        external_id=str(product_id),
        source=_SOURCE_NAME,
        title=name,
        description=description,
        start_datetime=start_dt,
        venue_name=venue_name,
        venue_address=venue_address,
        latitude=lat,
        longitude=lng,
        category=_category_for(product),
        tags=_tags_for(product),
        price_min=price_min,
        price_max=None,
        is_free=is_free,
        currency=product.get("currency") or "EUR",
        image_url=product.get("imageUrl") or None,
        source_url=product.get("link") or "",
        raw_data={
            "productId": str(product_id),
            "productGroupId": product.get("productGroupId"),
            "eventim_categories": product.get("categories", []),
            "startDate_raw": start_raw,
        },
    )
