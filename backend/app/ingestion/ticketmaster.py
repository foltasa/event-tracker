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
                event = self._parse(raw)
                if event:
                    yield event

            page_info = data.get("page", {})
            total = page_info.get("totalPages", 1)
            current = page_info.get("number", 0)
            if current + 1 >= total:
                break
            params["page"] = current + 1

    def _parse(self, raw: dict) -> NormalizedEvent | None:
        try:
            start_str = raw["dates"]["start"]["dateTime"]
            venues = raw.get("_embedded", {}).get("venues", [{}])
            venue = venues[0] if venues else {}
            loc = venue.get("location", {})
            line1 = venue.get("address", {}).get("line1", "")
            city = venue.get("city", {}).get("name", "Hamburg")
            venue_address = ", ".join(p for p in [line1, city] if p) or None

            ranges = raw.get("priceRanges") or []
            price_min = min((p["min"] for p in ranges if "min" in p), default=None)
            price_max = max((p["max"] for p in ranges if "max" in p), default=None)

            return NormalizedEvent(
                external_id=str(raw["id"]),
                source=self.name,
                title=raw["name"],
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
