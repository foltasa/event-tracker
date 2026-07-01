# Event Descriptions — Ticketmaster + Hamburg Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Populate the `description` field for events from Ticketmaster (342 events, 87% of DB) and HamburgScraper (21 events), which currently return `None` for every event.

**Architecture:** Ticketmaster — the list endpoint omits description; we call the single-event detail endpoint (`GET /events/{id}.json`) after each list event and read `info` / `additionalInfo` / `pleaseNote`. Hamburg — the listing page (`heuteinhamburg.de`) contains no description text; we follow each `/event/{slug}` link to the detail page and parse the description element. Both adapters already support `description` in `NormalizedEvent`; only the fetch layer changes.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup 4, pytest — no new dependencies.

---

## File Map

| Action | File |
|--------|------|
| Modify | `backend/app/ingestion/ticketmaster.py` |
| Modify | `backend/tests/ingestion/test_ticketmaster.py` |
| Modify | `backend/app/ingestion/scrapers/hamburg.py` |
| Modify | `backend/tests/ingestion/test_hamburg_scraper.py` |

---

## Task 1 — Ticketmaster: fetch description from the detail endpoint

**Files:**
- Modify: `backend/app/ingestion/ticketmaster.py`
- Modify: `backend/tests/ingestion/test_ticketmaster.py`

The Ticketmaster Discovery API's detail endpoint (`GET /discovery/v2/events/{id}.json`) returns `info`, `additionalInfo`, and `pleaseNote` — fields absent from the list endpoint. We call it once per event and pass the result into `_parse`.

### Step 1.1 — Upgrade `_FakeClient` to URL-aware dispatch

The current fake client is a plain iterator; adding detail calls would consume list-page slots. Replace it with a URL-dispatching client that routes `/events.json` to the list iterator and `/events/{id}.json` to a lookup dict.

Open `backend/tests/ingestion/test_ticketmaster.py` and replace the `_FakeClient` class (lines 50–56) with:

```python
class _FakeClient:
    def __init__(self, list_pages: list[dict], detail_map: dict[str, dict] | None = None):
        self._list_iter = iter(list_pages)
        self._detail_map = detail_map or {}

    def get(self, url: str, **kwargs) -> httpx.Response:
        if url.endswith("/events.json"):
            data = next(self._list_iter)
        else:
            event_id = url.rsplit("/", 1)[-1].removesuffix(".json")
            data = self._detail_map.get(event_id, {})
        return httpx.Response(200, json=data, request=httpx.Request("GET", url))
```

All existing test calls `_FakeClient([...])` keep working — `list_pages` is still the first positional arg, and `detail_map` defaults to `{}` (empty → description `None`).

### Step 1.2 — Run existing tests to confirm they still pass

```
cd backend
python -m pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all 8 tests pass. If any fail, fix `_FakeClient` before continuing.

### Step 1.3 — Write four failing tests for the description feature

Append to `backend/tests/ingestion/test_ticketmaster.py`:

```python
_DETAIL_WITH_INFO = {
    "id": "tm_001",
    "name": "Rock Concert at Barclays",
    "info": "An evening of hard rock classics.",
}

_DETAIL_WITH_ADDITIONAL = {
    "id": "tm_001",
    "additionalInfo": "Doors open at 19:00.",
}

_SINGLE_PAGE = {"_embedded": {"events": [_EVENT_1]}, "page": {"totalPages": 1, "number": 0}}


def test_description_from_detail_info():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_INFO}))
    events = list(adapter.fetch())
    assert events[0].description == "An evening of hard rock classics."


def test_description_falls_back_to_additional_info():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE], {"tm_001": _DETAIL_WITH_ADDITIONAL}))
    events = list(adapter.fetch())
    assert events[0].description == "Doors open at 19:00."


def test_description_is_none_when_detail_empty():
    adapter = TicketmasterAdapter(client=_FakeClient([_SINGLE_PAGE]))
    events = list(adapter.fetch())
    assert events[0].description is None


def test_description_none_on_detail_http_error():
    class _ListOkDetailFail:
        def get(self, url, **kwargs):
            if url.endswith("/events.json"):
                return httpx.Response(
                    200,
                    json=_SINGLE_PAGE,
                    request=httpx.Request("GET", url),
                )
            return httpx.Response(500, request=httpx.Request("GET", url))

    adapter = TicketmasterAdapter(client=_ListOkDetailFail())
    events = list(adapter.fetch())
    assert len(events) == 1
    assert events[0].description is None
```

### Step 1.4 — Run the new tests to confirm they fail

```
python -m pytest tests/ingestion/test_ticketmaster.py::test_description_from_detail_info \
    tests/ingestion/test_ticketmaster.py::test_description_falls_back_to_additional_info \
    tests/ingestion/test_ticketmaster.py::test_description_is_none_when_detail_empty \
    tests/ingestion/test_ticketmaster.py::test_description_none_on_detail_http_error -v
```

Expected: all 4 FAIL (description is `None` / `_fetch_detail` doesn't exist yet).

### Step 1.5 — Implement the changes in `ticketmaster.py`

Replace the entire content of `backend/app/ingestion/ticketmaster.py` with:

```python
import logging
from datetime import datetime
from typing import Iterator

import httpx

from app.config import settings
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://app.ticketmaster.com/discovery/v2"

_SEGMENT_MAP: dict[str, str] = {
    "music": "music",
    "arts & theatre": "theater",
    "arts & theater": "theater",
    "sports": "sports",
    "film": "film",
    "family": "family",
    "miscellaneous": "other",
}

_GENRE_OVERRIDE: dict[str, str] = {
    "classical": "arts",
    "opera": "theater",
    "ballet": "arts",
    "comedy": "theater",
}


def _map_category(classifications: list[dict]) -> str:
    for cls in classifications:
        if not cls.get("primary"):
            continue
        genre = cls.get("genre", {}).get("name", "").lower()
        if genre in _GENRE_OVERRIDE:
            return _GENRE_OVERRIDE[genre]
        segment = cls.get("segment", {}).get("name", "").lower()
        return _SEGMENT_MAP.get(segment, "other")
    return "other"


def _best_image(images: list[dict]) -> str | None:
    if not images:
        return None
    return max(images, key=lambda i: i.get("width", 0) * i.get("height", 0)).get("url")


class TicketmasterAdapter:
    name = "ticketmaster"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._api_key = settings.ticketmaster_api_key

    def fetch(self) -> Iterator[NormalizedEvent]:
        params: dict = {
            "city": "Hamburg",
            "countryCode": "DE",
            "size": 200,
            "page": 0,
        }
        if self._api_key:
            params["apikey"] = self._api_key

        while True:
            resp = self._client.get(f"{_BASE_URL}/events.json", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("_embedded", {}).get("events", []):
                detail = self._fetch_detail(raw.get("id", ""))
                event = self._parse(raw, detail)
                if event:
                    yield event

            page_info = data.get("page", {})
            total = page_info.get("totalPages", 1)
            current = page_info.get("number", 0)
            if current + 1 >= total:
                break
            params["page"] = current + 1

    def _fetch_detail(self, event_id: str) -> dict:
        if not event_id:
            return {}
        params = {"apikey": self._api_key} if self._api_key else {}
        try:
            resp = self._client.get(f"{_BASE_URL}/events/{event_id}.json", params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.warning("TM detail fetch failed for event %s", event_id)
            return {}

    def _parse(self, raw: dict, detail: dict | None = None) -> NormalizedEvent | None:
        try:
            start_info = raw["dates"]["start"]
            start_str = start_info.get("dateTime") or start_info["localDate"] + "T00:00:00+02:00"
            venues = raw.get("_embedded", {}).get("venues", [{}])
            venue = venues[0] if venues else {}
            loc = venue.get("location", {})
            line1 = venue.get("address", {}).get("line1", "")
            city = venue.get("city", {}).get("name", "Hamburg")
            venue_address = ", ".join(p for p in [line1, city] if p) or None

            ranges = raw.get("priceRanges") or []
            price_min = min((p["min"] for p in ranges if "min" in p), default=None)
            price_max = max((p["max"] for p in ranges if "max" in p), default=None)

            description: str | None = None
            if detail:
                description = (
                    detail.get("info") or detail.get("additionalInfo") or detail.get("pleaseNote")
                ) or None

            return NormalizedEvent(
                external_id=str(raw["id"]),
                source=self.name,
                title=raw["name"],
                description=description,
                start_datetime=datetime.fromisoformat(start_str.replace("Z", "+00:00")),
                venue_name=venue.get("name"),
                venue_address=venue_address,
                latitude=float(loc["latitude"]) if loc.get("latitude") else None,
                longitude=float(loc["longitude"]) if loc.get("longitude") else None,
                category=_map_category(raw.get("classifications") or []),
                tags=[],
                price_min=price_min,
                price_max=price_max,
                is_free=False,
                currency="EUR",
                image_url=_best_image(raw.get("images") or []),
                source_url=raw["url"],
                raw_data=raw,
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Skipping malformed Ticketmaster event: %s", raw.get("id"))
            return None
```

### Step 1.6 — Run all Ticketmaster tests

```
python -m pytest tests/ingestion/test_ticketmaster.py -v
```

Expected: all 12 tests pass (8 original + 4 new).

### Step 1.7 — Commit

```
git add backend/app/ingestion/ticketmaster.py backend/tests/ingestion/test_ticketmaster.py
git commit -m "feat(ticketmaster): fetch description from detail endpoint"
```

---

## Task 2 — Hamburg Scraper: fetch description from the detail page

**Files:**
- Modify: `backend/app/ingestion/scrapers/hamburg.py`
- Modify: `backend/tests/ingestion/test_hamburg_scraper.py`

The listing page at `heuteinhamburg.de` has no description text. Each event's detail page at `/event/{slug}` does. We fetch it per event and parse the description element.

### Step 2.1 — Inspect the real detail page HTML to find the description selector

Run this one-time recon command (requires network):

```
python -c "
import httpx
from bs4 import BeautifulSoup

# Replace SLUG with any real slug from the DB:
# python -c \"import sqlite3; c=sqlite3.connect('backend/event_tracker.db').cursor(); c.execute(\\\"SELECT external_id FROM events WHERE source='hamburg_scraper' LIMIT 3\\\"); print(c.fetchall())\"
slug = 'REPLACE_ME'
r = httpx.get(f'https://heuteinhamburg.de/event/{slug}', headers={'User-Agent': 'EventTrackerBot/1.0'})
soup = BeautifulSoup(r.text, 'html.parser')
print(soup.find('main'))
"
```

Identify which element wraps the description text. The implementation in Step 2.5 uses `soup.find("div", class_="description")` — update the selector in `_fetch_description` if the real page uses a different element or class name.

### Step 2.2 — Upgrade `_FakeClient` to URL-aware dispatch

Open `backend/tests/ingestion/test_hamburg_scraper.py`. Replace the `_FakeClient` class (lines 34–44) with a version that routes `/event/` URLs to a separate `detail_html` response:

```python
class _FakeClient:
    def __init__(self, html: str, detail_html: str = "", status_code: int = 200):
        self._html = html
        self._detail_html = detail_html
        self._status_code = status_code

    def get(self, url: str, **kwargs) -> httpx.Response:
        is_detail = "/event/" in url
        text = self._detail_html if is_detail else self._html
        return httpx.Response(
            self._status_code,
            text=text,
            request=httpx.Request("GET", url),
        )
```

Existing test calls like `_FakeClient(_HTML)` and `_FakeClient("", status_code=500)` keep working unchanged.

### Step 2.3 — Run existing tests to confirm they still pass

```
python -m pytest tests/ingestion/test_hamburg_scraper.py -v
```

Expected: all 11 tests pass. The description is now `None` (detail_html defaults to `""`), which existing tests never assert.

### Step 2.4 — Write three failing tests for the description feature

Add a detail-page HTML fixture and three tests to `backend/tests/ingestion/test_hamburg_scraper.py`:

```python
_DETAIL_HTML = """<!DOCTYPE html>
<html><body><main>
  <h1>Jazz Night at Mojo Club</h1>
  <div class="description">Hamburg's finest jazz musicians gather for an unforgettable evening.</div>
</main></body></html>"""


def test_description_from_detail_page():
    events = list(HamburgScraper(client=_FakeClient(_HTML, detail_html=_DETAIL_HTML)).fetch())
    assert events[0].description == "Hamburg's finest jazz musicians gather for an unforgettable evening."


def test_description_none_when_element_absent():
    events = list(HamburgScraper(client=_FakeClient(_HTML, detail_html="<html><body></body></html>")).fetch())
    assert events[0].description is None


def test_description_none_on_detail_http_error():
    class _ListOkDetailFail:
        def get(self, url, **kwargs):
            if "/event/" in url:
                return httpx.Response(500, request=httpx.Request("GET", url))
            return httpx.Response(200, text=_HTML, request=httpx.Request("GET", url))

    events = list(HamburgScraper(client=_ListOkDetailFail()).fetch())
    assert len(events) == 2
    assert all(e.description is None for e in events)
```

**Note:** If the recon in Step 2.1 revealed a different selector, update `_DETAIL_HTML` to match the real site's structure now, before implementing.

### Step 2.5 — Run the new tests to confirm they fail

```
python -m pytest tests/ingestion/test_hamburg_scraper.py::test_description_from_detail_page \
    tests/ingestion/test_hamburg_scraper.py::test_description_none_when_element_absent \
    tests/ingestion/test_hamburg_scraper.py::test_description_none_on_detail_http_error -v
```

Expected: all 3 FAIL (`description` is always `None`, `_fetch_description` doesn't exist yet).

### Step 2.6 — Implement the changes in `hamburg.py`

Replace the entire content of `backend/app/ingestion/scrapers/hamburg.py` with:

```python
import logging
import re
from datetime import date, datetime, time
from typing import Iterator
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://heuteinhamburg.de"
_BERLIN = ZoneInfo("Europe/Berlin")

_CATEGORY_MAP: dict[str, str] = {
    "musik": "music",
    "konzert": "music",
    "kunst": "arts",
    "ausstellung": "arts",
    "kultur": "arts",
    "kino": "film",
    "film": "film",
    "theater": "theater",
    "show": "theater",
    "comedy": "theater",
    "sport": "sports",
    "outdoor": "outdoor",
    "natur": "outdoor",
    "food": "food",
    "essen": "food",
    "genuss": "food",
    "tech": "tech",
    "technologie": "tech",
    "kinder": "family",
    "familie": "family",
}


def _map_category(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.lower().strip(), "other")


def _parse_price(text: str) -> tuple[bool, float | None, float | None]:
    """Returns (is_free, price_min, price_max)."""
    cleaned = text.strip().lower()
    if any(w in cleaned for w in ("kostenlos", "gratis", "frei", "free")):
        return True, None, None
    nums = re.findall(r"\d+(?:[.,]\d+)?", cleaned)
    if not nums:
        return False, None, None
    prices = [float(n.replace(",", ".")) for n in nums]
    return False, prices[0], prices[-1] if len(prices) > 1 else None


def _parse_time(text: str, today: date) -> datetime | None:
    """Parse '20:30 Uhr' or 'ab 20:00 Uhr' into a tz-aware datetime."""
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    return datetime.combine(today, time(int(m.group(1)), int(m.group(2))), tzinfo=_BERLIN)


class HamburgScraper:
    name = "hamburg_scraper"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            timeout=15, headers={"User-Agent": "EventTrackerBot/1.0"}
        )

    def fetch(self) -> Iterator[NormalizedEvent]:
        resp = self._client.get(_BASE_URL)
        resp.raise_for_status()

        today = datetime.now(tz=_BERLIN).date()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href: str = link["href"]
            if not href.startswith("/event/"):
                continue
            if link.find("img"):
                continue  # skip image-only anchors
            title = link.get_text(strip=True)
            if not title:
                continue
            slug = href.split("/event/", 1)[1].split("/")[0]
            if not slug or slug in seen:
                continue
            seen.add(slug)

            description = self._fetch_description(slug)
            ev = self._parse_card(link, slug, title, today, description=description)
            if ev:
                yield ev

    def _fetch_description(self, slug: str) -> str | None:
        url = f"{_BASE_URL}/event/{slug}"
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Selector verified against heuteinhamburg.de in Step 2.1.
            # Update this if the site uses a different element/class.
            el = soup.find("div", class_="description")
            if el:
                text = el.get_text(separator=" ", strip=True)
                return text or None
            return None
        except Exception:
            logger.warning("Hamburg detail fetch failed for %s", slug)
            return None

    def _parse_card(
        self,
        title_link,
        slug: str,
        title: str,
        today: date,
        description: str | None = None,
    ) -> NormalizedEvent | None:
        try:
            source_url = f"{_BASE_URL}/event/{slug}"

            end = next(
                (
                    a for a in title_link.find_all_next("a", href=True)
                    if a.get("href", "").startswith("/event/")
                    and not a.find("img")
                    and a.get_text(strip=True)
                ),
                None,
            )

            def _before_boundary(tag):
                if tag is None or end is None:
                    return tag
                for el in title_link.find_all_next():
                    if el is end:
                        return None
                    if el is tag:
                        return tag
                return None

            cat_link = title_link.find_previous("a", href=lambda h: h and "/kategorie/" in h)
            cat_text = cat_link.get_text(strip=True) if cat_link else ""
            category = _map_category(cat_text)
            tags = [cat_text.lower()] if cat_text else []

            image_url: str | None = None
            img_anchor = title_link.find_previous("a", href=f"/event/{slug}")
            if img_anchor:
                img_tag = img_anchor.find("img")
                if img_tag:
                    src = img_tag.get("src", "")
                    if src and "icon" not in src:
                        image_url = src if src.startswith("http") else _BASE_URL + src

            clock = _before_boundary(title_link.find_next("img", attrs={"src": "/icons/icon-clock.svg"}))
            start_datetime: datetime
            if clock and clock.next_sibling:
                parsed = _parse_time(str(clock.next_sibling), today)
                start_datetime = parsed or datetime.combine(today, time(0, 0), tzinfo=_BERLIN)
            else:
                start_datetime = datetime.combine(today, time(0, 0), tzinfo=_BERLIN)

            venue_name: str | None = None
            map_img = _before_boundary(title_link.find_next("img", attrs={"src": "/icons/icon-map.svg"}))
            if map_img:
                venue_name = map_img.parent.get_text(strip=True) or None

            is_free, price_min, price_max = False, None, None
            ticket_img = _before_boundary(title_link.find_next("img", attrs={"src": "/icons/icon-ticket.svg"}))
            if ticket_img:
                is_free, price_min, price_max = _parse_price(
                    ticket_img.parent.get_text(strip=True)
                )

            return NormalizedEvent(
                external_id=slug,
                source=self.name,
                title=title,
                description=description,
                start_datetime=start_datetime,
                venue_name=venue_name,
                category=category,
                tags=tags,
                is_free=is_free,
                price_min=price_min,
                price_max=price_max,
                currency="EUR",
                image_url=image_url,
                source_url=source_url,
                raw_data={"slug": slug},
            )
        except Exception:
            logger.exception("Skipping malformed heuteinhamburg event: %s", slug)
            return None
```

### Step 2.7 — Run all Hamburg tests

```
python -m pytest tests/ingestion/test_hamburg_scraper.py -v
```

Expected: all 14 tests pass (11 original + 3 new).

### Step 2.8 — Verify real-world selector works (requires network + API key)

If you have a Ticketmaster API key and network access, run a live ingestion and spot-check the DB:

```
python -c "
import sqlite3
conn = sqlite3.connect('backend/event_tracker.db')
cur = conn.cursor()
cur.execute(\"SELECT source, COUNT(*) as total, SUM(CASE WHEN description IS NOT NULL AND description != '' THEN 1 ELSE 0 END) as with_desc FROM events GROUP BY source\")
for row in cur.fetchall():
    print(row)
conn.close()
"
```

If Hamburg descriptions are still `None` after a fresh ingestion, the selector in `_fetch_description` needs updating based on the recon output from Step 2.1.

### Step 2.9 — Commit

```
git add backend/app/ingestion/scrapers/hamburg.py backend/tests/ingestion/test_hamburg_scraper.py
git commit -m "feat(hamburg): fetch description from event detail page"
```
