"""ohschonhell.de party-event adapter.

Fetches upcoming Hamburg parties from ohschonhell.de using a
sitemap-delta strategy (see docs/specs/2026-07-06-ohschonhell-scraper-design.md).
Detail pages carry schema.org/Event microdata that we parse for
name, start, venue, and address."""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

_EVENT_ID_RE = re.compile(r"eventId=(\d+)")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")


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
    street = _val(_direct_prop(addr, "streetAddress")) if isinstance(addr, Tag) else ""
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
