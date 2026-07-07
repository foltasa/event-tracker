"""Eventim public-search-API adapter.

Fetches Hamburg events from Eventim's undocumented public JSON endpoint
(see docs/specs/2026-07-07-eventim-adapter-design.md). Paginates four
top-level categories, transforms products into NormalizedEvent, yields to
the caller. Anti-bot: 403/429/503 retry + persistent circuit breaker."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

import httpx

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
