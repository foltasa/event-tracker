"""Eventim public-search-API adapter.

Fetches Hamburg events from Eventim's undocumented public JSON endpoint
(see docs/specs/2026-07-07-eventim-adapter-design.md). Paginates four
top-level categories, transforms products into NormalizedEvent, yields to
the caller. Anti-bot: 403/429/503 retry + persistent circuit breaker."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Protocol

import httpx
from sqlalchemy.orm import Session

from app.db.models.ingestion_state import IngestionState
from app.db.session import SessionLocal
from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns
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
    warns=None,
) -> dict | None:
    """GET a JSON endpoint with exponential backoff on 403/429/503.

    Returns parsed JSON dict on 2xx, or None if all attempts exhausted or the
    status is non-retriable. On 403, extracts the Akamai Reference ID from
    the body (capped at _AKAMAI_REF_MAX in stats). Network exceptions
    propagate — callers handle them at the pagination level.

    All warnings are operational (`warns.op`) — never suppressed — because
    Eventim's anti-bot fingerprinting means a rate of failures is itself
    the signal that our access is at risk."""
    if warns is None:
        warns = NullWarns()
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
            warns.op("unexpected-status", status=resp.status_code, url=url)
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            warns.op(
                "retry-backoff",
                status=resp.status_code, url=url, backoff_s=backoff,
                attempt=attempt, max=_RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            warns.op("retry-exhausted", url=url, attempts=_RETRY_MAX_ATTEMPTS)
    return None


_CATEGORY_MAP: dict[str, EventCategory] = {
    # Konzerte subcategories (real Eventim leaves)
    "Rock & Pop": "concerts",
    "HipHop & R’n‘B": "concerts",  # Eventim uses typographic quotes, not ASCII
    "Jazz & Blues": "concerts",
    "Electronic & Dance": "concerts",
    "Hard & Heavy": "concerts",
    "Country & Folk": "concerts",
    "Clubkonzerte": "concerts",
    "Festivals": "concerts",
    "Weitere Konzerte": "concerts",
    "Party": "party",
    # Kultur subcategories (real Eventim leaves)
    "Klassische Konzerte": "concerts",
    "Oper & Operette": "theater",
    "Tanz": "theater",
    "Theater": "theater",
    "Ausstellungen": "arts",
    "Lesungen & Vorträge": "literature",
    # Musical & Show subcategories
    "Musical": "theater",
    "Show": "other",
    "Comedy": "comedy",
    "Kleinkunst": "comedy",
    # Sport subcategories (real Eventim leaves)
    "Fußball": "sports",
    "Basketball": "sports",
    "Boxen & Kampfsport": "sports",
    "Motorsport": "sports",
    "Tennis": "sports",
    "Wintersport": "sports",
    "Wrestling": "sports",
    "Weitere Sport-Events": "sports",
    # VIP & Extras (occasionally leaks into targeted categories)
    "VIP & Specials": "other",
}

_SOURCE_NAME = "eventim"
_TARGET_CITY = "Hamburg"


def _category_for(product: dict, warns=None) -> EventCategory:
    """Map the leaf (sub-level) Eventim category to our EventCategory.

    Unknown leaves fall back to 'other' via a fetch.warn so operators
    notice drift in Eventim's taxonomy."""
    if warns is None:
        warns = NullWarns()
    for cat in product.get("categories", []):
        parent = cat.get("parentCategory")
        if not parent:
            continue
        name = cat.get("name")
        mapped = _CATEGORY_MAP.get(name)
        if mapped is not None:
            return mapped
        warns.warn("unknown-category-leaf", str(name))
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


def parse_product(product: dict, warns=None) -> NormalizedEvent | None:
    """Convert one Eventim product dict to a NormalizedEvent.

    Returns None when required fields are missing, type is not
    LiveEntertainment, or city is not the target. Pure - no I/O."""
    if warns is None:
        warns = NullWarns()
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
        category=_category_for(product, warns),
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


_API = "https://public-api.eventim.com/websearch/search/api/exploration/v1/products"
_CATEGORIES = ["Konzerte", "Musical & Show", "Kultur", "Sport"]
_TOP = 50
_REQUEST_DELAY_SECONDS = 0.2

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Origin": "https://www.eventim.de",
    "Referer": "https://www.eventim.de/city/hamburg-72/",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not:A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


class EventimAdapter:
    """Ingest Hamburg events from Eventim's public JSON search API.

    Full-crawl every run across four top-level categories; idempotent via
    upsert on (external_id, source). Circuit breaker (Task 5-6) gates the
    entire run when Akamai flags us."""

    name = _SOURCE_NAME

    _TRIP_CONSECUTIVE_EXHAUSTIONS = 3
    _TRIP_TOTAL_403_BUDGET = 15

    def __init__(
        self,
        client: _HttpGetter | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        self._client = client or httpx.Client(timeout=20, headers=_DEFAULT_HEADERS)
        self._sleep_fn = sleep_fn

    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        state = session.get(IngestionState, self.name)
        if state is not None and state.disabled_at is not None:
            self._log_disabled_banner(state)
            self._bump_runs_while_disabled()
            return

        stats = RetryStats()
        categories_failed_page_1 = 0
        consecutive_exhaustions = 0
        events_yielded_this_run = 0

        for i, category in enumerate(_CATEGORIES):
            first = get_json_with_retry(
                self._client, _API,
                params=self._params(category, page=1),
                stats=stats, sleep_fn=self._sleep_fn, warns=warns,
            )
            if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                           events_yielded_this_run, category, i)
                return
            if first is None:
                warns.op("category-page-1-failed", category=category)
                categories_failed_page_1 += 1
                # Category-level failures do NOT feed consecutive_exhaustions.
                continue

            for ev in self._products(first, warns):
                events_yielded_this_run += 1
                progress.tick(category=category, events=events_yielded_this_run)
                yield ev

            total_pages = int(first.get("totalPages") or 1)
            for page in range(2, total_pages + 1):
                self._sleep_fn(_REQUEST_DELAY_SECONDS)
                body = get_json_with_retry(
                    self._client, _API,
                    params=self._params(category, page=page),
                    stats=stats, sleep_fn=self._sleep_fn, warns=warns,
                )
                if stats.akamai_403s >= self._TRIP_TOTAL_403_BUDGET:
                    self._trip(f"total_403_budget_exceeded: {stats.akamai_403s}",
                               events_yielded_this_run, category, i)
                    return
                if body is None:
                    warns.op("category-page-failed", category=category, page=page)
                    consecutive_exhaustions += 1
                    if consecutive_exhaustions >= self._TRIP_CONSECUTIVE_EXHAUSTIONS:
                        self._trip(
                            f"consecutive_retry_exhaustion: {consecutive_exhaustions} pages",
                            events_yielded_this_run, category, i,
                        )
                        return
                    continue
                consecutive_exhaustions = 0
                for ev in self._products(body, warns):
                    events_yielded_this_run += 1
                    progress.tick(category=category, events=events_yielded_this_run)
                    yield ev

        # Post-loop: if every category's page 1 failed, trip.
        if categories_failed_page_1 == len(_CATEGORIES):
            self._trip("all_categories_failed_page_1",
                       events_yielded_this_run,
                       _CATEGORIES[-1], len(_CATEGORIES) - 1)
            return

    def _trip(self, reason: str, events_before: int, at_category: str, category_index: int) -> None:
        now = datetime.now(timezone.utc)
        # Persist trip in its own transaction so it survives a caller rollback.
        own_session = SessionLocal()
        try:
            row = own_session.get(IngestionState, self.name)
            if row is None:
                row = IngestionState(
                    source=self.name,
                    last_seen_lastmod=None,
                    disabled_at=now,
                    disabled_reason=reason,
                    runs_while_disabled=0,
                )
                own_session.add(row)
            else:
                row.disabled_at = now
                row.disabled_reason = reason
                row.runs_while_disabled = 0
            own_session.commit()
        finally:
            own_session.close()

        skipped = [c for c in _CATEGORIES[category_index + 1:]]
        skipped_str = ", ".join(skipped) if skipped else "(none)"
        logger.warning(
            "\n!! ============================================================\n"
            "!! EVENTIM CIRCUIT BREAKER TRIPPED THIS RUN\n"
            "!!   At:       %s\n"
            "!!   Reason:   %s\n"
            "!!   Partial:  ingested %d events from %s before trip\n"
            "!!   Skipped:  %s\n"
            "!!   Reset:    python -m scripts.reset_adapter_lock eventim\n"
            "!! ============================================================",
            now.isoformat(), reason, events_before, at_category, skipped_str,
        )

    def _params(self, category: str, *, page: int) -> dict:
        return {
            "city_names": _TARGET_CITY,
            "categories": category,
            "webId": "web__eventim-de",
            "language": "de",
            "page": page,
            "top": _TOP,
            "sort": "DateAsc",
        }

    def _products(self, body: dict, warns=None) -> Iterator[NormalizedEvent]:
        for product in body.get("products", []) or []:
            ev = parse_product(product, warns)
            if ev is not None:
                yield ev

    def _log_disabled_banner(self, state: IngestionState) -> None:
        logger.warning(
            "\n!! ============================================================\n"
            "!! EVENTIM ADAPTER DISABLED\n"
            "!!   Tripped at:  %s\n"
            "!!   Reason:      %s\n"
            "!!   Runs since:  %d\n"
            "!!   To re-enable: python -m scripts.reset_adapter_lock eventim\n"
            "!! ============================================================",
            state.disabled_at.isoformat(),
            state.disabled_reason,
            state.runs_while_disabled,
        )

    def _bump_runs_while_disabled(self) -> None:
        """Persist counter bump in its own transaction so it survives even
        if the caller's ingestion transaction later rolls back."""
        own_session = SessionLocal()
        try:
            row = own_session.get(IngestionState, self.name)
            if row is not None and row.disabled_at is not None:
                row.runs_while_disabled = (row.runs_while_disabled or 0) + 1
                own_session.commit()
        finally:
            own_session.close()
