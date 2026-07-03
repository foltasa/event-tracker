"""Theater-Hamburg adapter — imxplatform GraphQL over httpx.

The whitelabel widget's data endpoint requires a Bearer JWT baked into the
public widget.js bundle at the key `graphqlBearerToken:"..."`. The bundle
also ships tokens for other platform tenants (NRW etc.), so we anchor on
the specific key to select the Hamburg (HHT) token.

The list query already includes `shortDescription` — no separate detail
call per event. Each list node expands to one NormalizedEvent per entry
in `eventDates`."""
import logging
import os
import re
from datetime import datetime
from typing import Iterator
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_WIDGET_JS_URL = "https://hht.whitelabel.imxplatform.de/widget/widget.js"
_API_URL = "https://content-delivery.imxplatform.de/hht/imxplatform"
_JWT_RE = re.compile(
    r'graphqlBearerToken\s*:\s*"(ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"'
)
_BERLIN = ZoneInfo("Europe/Berlin")
_PAGE_SIZE = 1000

_LOCATION_IDS = [
    6306, 99, 423, 236, 121387, 1965, 494, 5359, 101488, 944, 947, 117, 119,
    375, 248, 313, 124, 100862, 1854, 767, 769, 833, 898, 771, 97227, 109323,
    5327, 9359, 5399, 12695, 217, 92, 95, 351,
]
_GROUP_IDS = [2, 3, 36, 164, 171, 108, 143, 175, 112, 176, 17, 114, 178, 19, 61]

_LIST_QUERY = """
query EventSearch($filter: EventFilter!, $pagination: Pagination!, $appearance: AppearanceFilter!) {
  events(filter: $filter, pagination: $pagination, appearance: $appearance) {
    nodes {
      id
      title
      permaLink
      shortDescription
      categories { id i18nName }
      location { id title }
      eventDates { date startTime duration }
      geoInfo { coordinates { latitude longitude } }
      bookingLink
    }
    pagination { totalPages totalRecords }
  }
}
"""

_CATEGORY_MAP: dict[str, str] = {
    "theater": "theater",
    "schauspiel": "theater",
    "oper": "theater",
    "musical": "theater",
    "kabarett": "theater",
    "comedy": "theater",
    "ballett": "arts",
    "tanz": "arts",
    "konzert": "music",
    "musik": "music",
    "klassik": "music",
    "jazz": "music",
    "kino": "film",
    "film": "film",
    "ausstellung": "arts",
    "lesung": "arts",
    "kinder": "family",
    "familie": "family",
}


def _extract_jwt(js_body: str) -> str | None:
    """Return the JWT captured after `graphqlBearerToken:"..."`, or None."""
    m = _JWT_RE.search(js_body)
    return m.group(1) if m else None


def _map_category(raw_titles: list[str]) -> tuple[str, list[str]]:
    """Return (primary category, remaining lowercase tags)."""
    lowered = [t.lower().strip() for t in raw_titles if t]
    for t in lowered:
        for key, mapped in _CATEGORY_MAP.items():
            if key in t:
                tags = [x for x in lowered if x != t]
                return mapped, tags
    return "other", lowered


def _parse_start(date_str: str, time_str: str | None) -> datetime:
    """Parse a Berlin-local (date, startTime) into an aware datetime.

    startTime formats accepted: 'HH:MM', 'HH:MM:SS'. Missing time -> midnight."""
    t = (time_str or "00:00").strip()
    if t.count(":") == 1:
        t = f"{t}:00"
    naive = datetime.fromisoformat(f"{date_str}T{t}")
    return naive.replace(tzinfo=_BERLIN)


def _strip_html(html: str | None) -> str | None:
    if not html:
        return None
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return text or None


class TheaterHamburgAdapter:
    """Ingests upcoming Hamburg events from theater-hamburg.org's imxplatform widget."""

    name = "theater_hamburg"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._jwt: str | None = None

    def _get_jwt(self) -> str:
        if self._jwt is not None:
            return self._jwt
        override = os.environ.get("THEATER_HAMBURG_JWT")
        if override:
            self._jwt = override
            return override
        return self._rescrape_jwt()

    def _rescrape_jwt(self) -> str:
        resp = self._client.get(_WIDGET_JS_URL)
        resp.raise_for_status()
        token = _extract_jwt(resp.text)
        if not token:
            raise RuntimeError("No JWT found in theater-hamburg widget.js")
        self._jwt = token
        return token

    def _post(self, body: dict) -> dict:
        """POST to GraphQL, transparently re-scraping JWT once on 401."""
        jwt = self._get_jwt()
        resp = self._client.post(
            _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
        )
        if resp.status_code == 401:
            logger.info("theater_hamburg: 401 — re-scraping widget JWT")
            self._jwt = None
            jwt = self._rescrape_jwt()
            resp = self._client.post(
                _API_URL, json=body, headers={"Authorization": f"Bearer {jwt}"}
            )
        resp.raise_for_status()
        return resp.json()

    def _list_page(self, page: int, from_date: str) -> dict:
        variables = {
            "filter": {
                "and": [
                    {"or": [
                        {"eventLocation": {"id": {"oneOf": _LOCATION_IDS}}},
                        {"eventLocation": {"group": {"oneOf": _GROUP_IDS}}},
                    ]},
                    {"fromDate": from_date},
                ]
            },
            "pagination": {"page": page, "pageSize": _PAGE_SIZE},
            "appearance": {"deliveryChannel": 76},
        }
        body = {"query": _LIST_QUERY, "variables": variables}
        return self._post(body)

    def fetch(self) -> Iterator[NormalizedEvent]:
        today = datetime.now(tz=_BERLIN).date().isoformat()
        page = 1
        while True:
            data = self._list_page(page, today)
            events_root = (data.get("data") or {}).get("events") or {}
            nodes = events_root.get("nodes") or []
            pagination = events_root.get("pagination") or {}
            total_pages = pagination.get("totalPages", 1)

            for node in nodes:
                for parsed in self._expand_node(node):
                    yield parsed

            if page >= total_pages or not nodes:
                break
            page += 1

    def _expand_node(self, node: dict) -> Iterator[NormalizedEvent]:
        """One list node yields one NormalizedEvent per entry in eventDates."""
        permalink = node.get("permaLink") or ""
        title = node.get("title") or ""
        description = _strip_html(node.get("shortDescription"))
        venue = ((node.get("location") or {}).get("title")) or None
        coords = ((node.get("geoInfo") or {}).get("coordinates")) or {}
        cat_titles = [c.get("i18nName") or "" for c in node.get("categories") or []]
        category, tags = _map_category(cat_titles)
        source_url = f"https://theater-hamburg.org/theater-hamburg/veranstaltung/{permalink}/"

        for ed in node.get("eventDates") or []:
            date = ed.get("date")
            start_time = ed.get("startTime")
            if not date:
                continue
            try:
                start = _parse_start(date, start_time)
                external_id = f"{permalink}#{date}T{start_time or '00:00'}"
                yield NormalizedEvent(
                    external_id=external_id,
                    source=self.name,
                    title=title,
                    description=description,
                    start_datetime=start,
                    venue_name=venue,
                    latitude=coords.get("latitude"),
                    longitude=coords.get("longitude"),
                    category=category,
                    tags=tags,
                    is_free=False,
                    currency="EUR",
                    image_url=None,
                    source_url=source_url,
                    raw_data={"node": node, "eventDate": ed},
                )
            except (KeyError, ValueError, TypeError):
                logger.exception("theater_hamburg: skipping malformed date on %s", permalink)
