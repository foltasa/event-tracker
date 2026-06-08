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

            ev = self._parse_card(link, slug, title, today)
            if ev:
                yield ev

    def _parse_card(self, title_link, slug: str, title: str, today: date) -> NormalizedEvent | None:
        try:
            source_url = f"{_BASE_URL}/event/{slug}"

            # Compute the next event's title anchor as a forward-search stop boundary.
            # Prevents find_next calls from crossing into the next event's card.
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

            # Category from nearest preceding /kategorie/ link
            cat_link = title_link.find_previous("a", href=lambda h: h and "/kategorie/" in h)
            cat_text = cat_link.get_text(strip=True) if cat_link else ""
            category = _map_category(cat_text)
            tags = [cat_text.lower()] if cat_text else []

            # Image: preceding anchor to same event href that wraps an img
            image_url: str | None = None
            img_anchor = title_link.find_previous("a", href=f"/event/{slug}")
            if img_anchor:
                img_tag = img_anchor.find("img")
                if img_tag:
                    src = img_tag.get("src", "")
                    if src and "icon" not in src:
                        image_url = src if src.startswith("http") else _BASE_URL + src

            # Time from nearest following clock icon
            clock = _before_boundary(title_link.find_next("img", attrs={"src": "/icons/icon-clock.svg"}))
            start_datetime: datetime
            if clock and clock.next_sibling:
                parsed = _parse_time(str(clock.next_sibling), today)
                start_datetime = parsed or datetime.combine(today, time(0, 0), tzinfo=_BERLIN)
            else:
                start_datetime = datetime.combine(today, time(0, 0), tzinfo=_BERLIN)

            # Venue from nearest following map icon's parent anchor
            venue_name: str | None = None
            map_img = _before_boundary(title_link.find_next("img", attrs={"src": "/icons/icon-map.svg"}))
            if map_img:
                venue_name = map_img.parent.get_text(strip=True) or None

            # Price from nearest following ticket icon's parent anchor
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
