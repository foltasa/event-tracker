"""ohschonhell.de party-event adapter.

Fetches upcoming Hamburg parties from ohschonhell.de using a
sitemap-delta strategy (see docs/specs/2026-07-06-ohschonhell-scraper-design.md).
Detail pages carry schema.org/Event microdata that we parse for
name, start, venue, and address."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator, Protocol
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag
from sqlalchemy.orm import Session

from app.ingestion.logging_util import FetchContext, NullProgress, NullWarns
from app.ingestion.normalize import NormalizedEvent
from app.ingestion.state import get_last_seen, set_last_seen

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
        if lastmod.tzinfo is None:
            lastmod = lastmod.replace(tzinfo=timezone.utc)
        if lastmod > cutoff:
            entries.append((loc, lastmod))
    entries.sort(key=lambda x: x[1])
    return entries


_RETRY_STATUS_CODES = {429, 503}
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BASE_SLEEP = 1.0  # exponential: 1s, 2s, 4s


class _HttpGetter(Protocol):
    def get(self, url: str, **kwargs) -> httpx.Response: ...


@dataclass
class RetryStats:
    total_retries: int = 0
    total_backoff_seconds: float = 0.0
    exhausted: int = 0


def get_with_retry(
    client: _HttpGetter,
    url: str,
    *,
    stats: RetryStats,
    sleep_fn: Callable[[float], None],
    warns=None,
) -> str | None:
    """GET `url` with exponential backoff on 429/503. Returns body text or None.

    Non-retriable error statuses (e.g. 404) return None without retrying.
    Network exceptions propagate — callers handle them at the sitemap level.
    """
    if warns is None:
        warns = NullWarns()
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        resp = client.get(url)
        if resp.status_code == 200:
            return resp.content.decode("utf-8", errors="replace")
        if resp.status_code not in _RETRY_STATUS_CODES:
            warns.warn("http_status", f"{resp.status_code} {url}")
            return None
        if attempt < _RETRY_MAX_ATTEMPTS:
            backoff = _RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            stats.total_retries += 1
            stats.total_backoff_seconds += backoff
            sleep_fn(backoff)
        else:
            stats.total_retries += 1
            stats.exhausted += 1
            warns.warn("http_retry_exhausted", url)
    return None


# WordPress sitemap files are numbered and roll over at ~1000 URLs each.
# 26 is the current active file; when it fills we bump this manually.
_SITEMAP_URL = "https://ohschonhell.de/post-sitemap26.xml"
_BERLIN = ZoneInfo("Europe/Berlin")
_UA = "EventTrackerBot/1.0 (https://github.com/alexander-foltas/event-tracker)"
_BOOTSTRAP_WINDOW_DAYS = 90
_REQUEST_DELAY_SECONDS = 0.15


class OhschonhellScraper:
    """Ingest Hamburg party events from ohschonhell.de via sitemap-delta."""

    name = "ohschonhell"

    def __init__(
        self,
        client: _HttpGetter | None = None,
        sleep_fn=time.sleep,
    ):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": _UA}
        )
        self._sleep_fn = sleep_fn

    def fetch(self, session: Session, ctx: FetchContext | None = None) -> Iterator[NormalizedEvent]:
        progress = ctx.progress if ctx else NullProgress()
        warns = ctx.warns if ctx else NullWarns()

        last_seen = get_last_seen(session, self.name)
        if last_seen is None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=_BOOTSTRAP_WINDOW_DAYS)
        else:
            cutoff = last_seen

        stats = RetryStats()
        sitemap_body = get_with_retry(
            self._client, _SITEMAP_URL,
            stats=stats, sleep_fn=self._sleep_fn, warns=warns,
        )
        if sitemap_body is None:
            raise RuntimeError("ohschonhell: sitemap fetch failed after retries")
        candidates = filter_sitemap(sitemap_body, cutoff)

        max_lastmod: datetime | None = None
        parsed_count = 0
        n_total = len(candidates)

        for i, (url, lastmod) in enumerate(candidates):
            if i > 0:
                self._sleep_fn(_REQUEST_DELAY_SECONDS)

            body = get_with_retry(
                self._client, url,
                stats=stats, sleep_fn=self._sleep_fn, warns=warns,
            )
            if body is None:
                warns.warn("http_error", url)
                continue

            parsed = parse_event(body)
            if parsed is None:
                warns.warn("parse_error", url)
                continue

            try:
                naive = datetime.fromisoformat(f"{parsed['date']}T{parsed['time']}")
                start_dt = naive.replace(tzinfo=_BERLIN)
            except ValueError as e:
                warns.warn("bad_date", url, exc=e)
                continue

            slug = url.rsplit("/date/", 1)[-1]
            venue_address = ", ".join(
                p for p in [parsed["street"], f"{parsed['postal_code']} {parsed['city']}".strip()] if p
            ).strip(", ")

            yield NormalizedEvent(
                external_id=parsed["event_id"],
                source=self.name,
                title=parsed["name"],
                description=parsed["description"],
                start_datetime=start_dt,
                venue_name=parsed["venue_name"],
                venue_address=venue_address or None,
                category="party",
                tags=["party"],
                is_free=False,
                currency="EUR",
                image_url=parsed["image_url"],
                source_url=url,
                raw_data={
                    "event_id": parsed["event_id"],
                    "slug": slug,
                    "sitemap_lastmod": lastmod.isoformat(),
                },
            )
            parsed_count += 1
            progress.tick(parsed=parsed_count, seen=i + 1, total=n_total)
            if max_lastmod is None or lastmod > max_lastmod:
                max_lastmod = lastmod

        if max_lastmod is not None:
            set_last_seen(session, self.name, max_lastmod)
