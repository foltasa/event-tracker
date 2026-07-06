"""ohschonhell.de party-event adapter.

Fetches upcoming Hamburg parties from ohschonhell.de using a
sitemap-delta strategy (see docs/specs/2026-07-06-ohschonhell-scraper-design.md).
Detail pages carry schema.org/Event microdata that we parse for
name, start, venue, and address."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import httpx
from bs4 import BeautifulSoup, Tag

_EVENT_ID_RE = re.compile(r"eventId=(\d+)")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _direct_prop(scope: Tag, name: str) -> Tag | None:
    """Return the itemprop element whose nearest itemscope ancestor is `scope`.

    Schema.org microdata nests scopes (Event -> Place -> PostalAddress), so
    plain find_all(attrs={"itemprop": name}) returns matches inside nested
    scopes too. This helper enforces direct-child semantics."""
    for el in scope.find_all(attrs={"itemprop": name}):
        parent = el.find_parent(attrs={"itemscope": True})
        if parent is scope:
            return el
    return None


def _val(el: Tag | None) -> str:
    if el is None:
        return ""
    if el.has_attr("content") and el["content"].strip():
        return el["content"].strip()
    return el.get_text(separator=" ", strip=True)


def _street_text(el: Tag | None) -> str:
    """Return the streetAddress text, excluding nested itemprop spans.

    ohschonhell.de nests <span itemprop=postalCode> and
    <span itemprop=addressLocality> inside <p itemprop=streetAddress>,
    so a plain get_text() would concatenate the entire address."""
    if el is None:
        return ""
    parts: list[str] = []
    for child in el.descendants:
        if isinstance(child, Tag):
            if child.has_attr("itemprop"):
                # Skip nested itemprop children and everything under them.
                continue
        else:
            # NavigableString — check that no ancestor has itemprop.
            has_itemprop_ancestor = False
            for anc in child.parents:
                if anc is el:
                    break
                if isinstance(anc, Tag) and anc.has_attr("itemprop"):
                    has_itemprop_ancestor = True
                    break
            if has_itemprop_ancestor:
                continue
            text = str(child).strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def parse_event(html: str) -> dict[str, Any] | None:
    """Extract a party event from a `/date/{slug}` page's HTML.

    Returns a dict with keys: event_id, name, date (YYYY-MM-DD), time (HH:MM),
    description, venue_name, street, postal_code, city, image_url.
    Returns None if any required field is missing (event_id, name, date,
    time, venue_name)."""
    soup = BeautifulSoup(html, "html.parser")

    event = soup.find(attrs={"itemtype": "http://schema.org/Event"})
    if not isinstance(event, Tag):
        return None

    m = _EVENT_ID_RE.search(html)
    if not m:
        return None
    event_id = m.group(1)

    name = _val(_direct_prop(event, "name"))
    if not name:
        return None

    start_el = _direct_prop(event, "startDate")
    date = start_el["content"].strip() if start_el and start_el.has_attr("content") else ""
    display_text = start_el.get_text(strip=True) if start_el else ""
    time_match = _TIME_RE.search(display_text) if display_text else None
    if not date or not time_match:
        return None
    time_str = f"{int(time_match.group(1)):02d}:{time_match.group(2)}"

    place = event.find(attrs={"itemtype": "http://schema.org/Place"})
    venue_name = _val(_direct_prop(place, "name")) if isinstance(place, Tag) else ""
    if not venue_name:
        return None

    addr = event.find(attrs={"itemtype": "http://schema.org/PostalAddress"})
    street = _street_text(_direct_prop(addr, "streetAddress")) if isinstance(addr, Tag) else ""
    postal_code = _val(_direct_prop(addr, "postalCode")) if isinstance(addr, Tag) else ""
    city = _val(_direct_prop(addr, "addressLocality")) if isinstance(addr, Tag) else ""

    description = _val(_direct_prop(event, "description")) or None

    og_image_el = soup.find("meta", attrs={"property": "og:image"})
    image_url = og_image_el["content"].strip() if og_image_el and og_image_el.has_attr("content") else None

    return {
        "event_id": event_id,
        "name": name,
        "date": date,
        "time": time_str,
        "description": description,
        "venue_name": venue_name,
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "image_url": image_url,
    }


def filter_sitemap(xml_body: str, cutoff: datetime) -> list[tuple[str, datetime]]:
    """Return (url, lastmod) tuples for /date/ entries with lastmod > cutoff,
    sorted ascending by lastmod. Callers ensure `cutoff` is tz-aware."""
    root = ET.fromstring(xml_body)
    entries: list[tuple[str, datetime]] = []
    for url_el in root.findall("sm:url", _SITEMAP_NS):
        loc = (url_el.findtext("sm:loc", "", _SITEMAP_NS) or "").strip()
        lastmod_str = (url_el.findtext("sm:lastmod", "", _SITEMAP_NS) or "").strip()
        if "/date/" not in loc or not lastmod_str:
            continue
        try:
            lastmod = datetime.fromisoformat(lastmod_str)
        except ValueError:
            continue
        if lastmod > cutoff:
            entries.append((loc, lastmod))
    entries.sort(key=lambda x: x[1])
    return entries


logger = logging.getLogger(__name__)

_RETRY_STATUS_CODES = {429, 503}
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_SLEEP = 1.0  # exponential: 1s, 2s, 4s


@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
) -> str | None:
    """GET `url` with exponential backoff on 429/503. Returns body text or None.

    Non-retriable error statuses (e.g. 404) return None without retrying.
    Network exceptions propagate — callers handle them at the sitemap level.
    """
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.content.decode("utf-8", errors="replace")
        if resp.status_code not in _RETRY_STATUS_CODES:
            logger.warning(
                "ohschonhell: unexpected status %d for %s — skipping",
                resp.status_code, url,
            )
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            logger.warning(
                "ohschonhell: %d from %s — sleeping %.1fs (attempt %d/%d)",
                resp.status_code, url, backoff, attempt, _RETRY_MAX_ATTEMPTS,
            )
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            logger.warning(
                "ohschonhell: giving up on %s after %d attempts",
                url, _RETRY_MAX_ATTEMPTS,
            )
    return None
