import logging
from datetime import datetime
from typing import Iterator

import httpx

from app.config import settings
from app.ingestion.normalize import NormalizedEvent

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.eventbriteapi.com/v3"

_CATEGORY_MAP: dict[str, str] = {
    "music": "music",
    "arts": "arts",
    "visual arts": "arts",
    "performing arts": "theater",
    "performing & visual arts": "theater",
    "film & media": "film",
    "food & drink": "food",
    "sports & fitness": "sports",
    "science & tech": "tech",
    "outdoors & adventure": "outdoor",
    "family & education": "family",
    "theater": "theater",
}


def _map_category(raw: str) -> str:
    return _CATEGORY_MAP.get(raw.lower().strip(), "other")


def _parse_prices(
    ticket_availability: dict | None, is_free: bool
) -> tuple[float | None, float | None]:
    if is_free or not ticket_availability:
        return None, None
    lo = ticket_availability.get("minimum_ticket_price")
    hi = ticket_availability.get("maximum_ticket_price")
    return (
        float(lo["major_value"]) if lo else None,
        float(hi["major_value"]) if hi else None,
    )


class EventbriteAdapter:
    name = "eventbrite"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=15)
        self._token = settings.eventbrite_token

    def fetch(self) -> Iterator[NormalizedEvent]:
        params: dict = {
            "location.address": "Hamburg, Germany",
            "location.within": "20km",
            "expand": "venue,category,ticket_availability",
            "page_size": 50,
        }
        if self._token:
            params["token"] = self._token

        continuation: str | None = None
        while True:
            if continuation:
                params["continuation"] = continuation

            resp = self._client.get(f"{_BASE_URL}/events/search/", params=params)
            resp.raise_for_status()
            data = resp.json()

            for raw in data.get("events", []):
                event = self._parse(raw)
                if event:
                    yield event

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break
            continuation = pagination.get("continuation")
            if not continuation:
                break

    def _parse(self, raw: dict) -> NormalizedEvent | None:
        try:
            venue = raw.get("venue") or {}
            address = venue.get("address") or {}
            category_obj = raw.get("category") or {}
            is_free = raw.get("is_free", False)
            price_min, price_max = _parse_prices(raw.get("ticket_availability"), is_free)
            logo = raw.get("logo") or {}
            end_raw = (raw.get("end") or {}).get("utc")

            return NormalizedEvent(
                external_id=str(raw["id"]),
                source=self.name,
                title=raw["name"]["text"],
                description=(raw.get("description") or {}).get("text"),
                summary=raw.get("summary"),
                start_datetime=datetime.fromisoformat(
                    raw["start"]["utc"].replace("Z", "+00:00")
                ),
                end_datetime=datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
                if end_raw
                else None,
                venue_name=venue.get("name"),
                venue_address=address.get("localized_address_display"),
                latitude=float(venue["latitude"]) if venue.get("latitude") else None,
                longitude=float(venue["longitude"]) if venue.get("longitude") else None,
                category=_map_category(category_obj.get("name", "")),
                tags=[
                    t["display_name"]
                    for t in (raw.get("tags") or [])
                    if t.get("display_name")
                ],
                price_min=price_min,
                price_max=price_max,
                is_free=is_free,
                currency="EUR",
                image_url=logo.get("url"),
                source_url=raw["url"],
                raw_data=raw,
            )
        except (KeyError, ValueError, TypeError):
            logger.exception("Skipping malformed Eventbrite event: %s", raw.get("id"))
            return None
