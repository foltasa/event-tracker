import json
import logging
from pathlib import Path

import pytest

from app.ingestion.eventim import _CATEGORY_MAP, parse_product

_FIXTURES = Path(__file__).parent / "fixtures" / "eventim"


def _load(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_full_konzert_all_fields():
    ev = parse_product(_load("full_konzert.json"))
    assert ev is not None
    assert ev.external_id == "20925654"
    assert ev.source == "eventim"
    assert ev.title == "Beirut"
    assert ev.description.startswith("Mit A Study of Losses")
    assert ev.summary is None
    assert ev.start_datetime.isoformat() == "2026-07-07T19:00:00+02:00"
    assert ev.end_datetime is None
    assert ev.venue_name == "Stadtpark Open Air"
    assert ev.venue_address == "22303 Hamburg"
    assert ev.latitude == 53.596
    assert ev.longitude == 10.051
    assert ev.category == "concerts"
    assert "Konzerte" in ev.tags
    assert "Rock & Pop" in ev.tags
    assert "Beirut" in ev.tags
    assert ev.price_min == 60.4
    assert ev.price_max is None
    assert ev.is_free is False
    assert ev.currency == "EUR"
    assert ev.image_url == "https://www.eventim.de/obj/media/DE-eventim/teaser/222x222/2025/beirut.jpg"
    assert ev.source_url == "https://www.eventim.de/event/beirut-stadtpark-open-air-20925654/"
    assert ev.raw_data["productId"] == "20925654"
    assert ev.raw_data["productGroupId"] == "4028322"


def test_parse_missing_description_returns_none_field():
    ev = parse_product(_load("no_description.json"))
    assert ev is not None
    assert ev.description is None
    assert ev.title == "Wade Black's 35 Years Of Metal"


def test_parse_klassik_maps_to_concerts_category():
    ev = parse_product(_load("klassik.json"))
    assert ev is not None
    assert ev.category == "concerts"


def test_parse_rejects_freizeit_leak_by_type():
    assert parse_product(_load("freizeit_leak.json")) is None


def test_parse_rejects_missing_product_id():
    p = _load("full_konzert.json")
    del p["productId"]
    assert parse_product(p) is None


def test_parse_rejects_missing_name():
    p = _load("full_konzert.json")
    del p["name"]
    assert parse_product(p) is None


def test_parse_rejects_missing_start_date():
    p = _load("full_konzert.json")
    del p["typeAttributes"]["liveEntertainment"]["startDate"]
    assert parse_product(p) is None


def test_parse_rejects_non_hamburg_city():
    p = _load("full_konzert.json")
    p["typeAttributes"]["liveEntertainment"]["location"]["city"] = "Berlin"
    assert parse_product(p) is None


def test_parse_no_geo_leaves_lat_lng_none():
    p = _load("full_konzert.json")
    del p["typeAttributes"]["liveEntertainment"]["location"]["geoLocation"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.latitude is None
    assert ev.longitude is None


def test_parse_zero_price_is_free():
    p = _load("full_konzert.json")
    p["price"] = 0
    ev = parse_product(p)
    assert ev is not None
    assert ev.is_free is True
    assert ev.price_min == 0


def test_parse_missing_price_leaves_price_min_none():
    p = _load("full_konzert.json")
    del p["price"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.price_min is None
    assert ev.price_max is None
    assert ev.is_free is False


def test_parse_missing_image_url_ok():
    p = _load("full_konzert.json")
    del p["imageUrl"]
    ev = parse_product(p)
    assert ev is not None
    assert ev.image_url is None


def test_category_map_covers_all_known_leaves():
    expected = {
        "Rock & Pop": "concerts",
        "HipHop & R'n'B": "concerts",
        "Schlager & Volksmusik": "concerts",
        "Jazz & Blues": "concerts",
        "Elektronische Musik": "concerts",
        "Metal & Hardrock": "concerts",
        "Weitere Konzerte": "concerts",
        "Klassische Konzerte": "concerts",
        "Oper": "theater",
        "Ballett & Tanz": "theater",
        "Theater": "theater",
        "Musical": "theater",
        "Show": "other",
        "Fußball": "sports",
        "Handball": "sports",
        "Weitere Sportarten": "sports",
    }
    for leaf, cat in expected.items():
        assert _CATEGORY_MAP[leaf] == cat


def test_unknown_leaf_falls_back_to_other_and_warns(caplog):
    p = _load("full_konzert.json")
    p["categories"] = [
        {"name": "Konzerte"},
        {"name": "Nu-Weirdcore", "parentCategory": {"name": "Konzerte"}},
    ]
    with caplog.at_level(logging.WARNING, logger="app.ingestion.eventim"):
        ev = parse_product(p)
    assert ev is not None
    assert ev.category == "other"
    assert any("Nu-Weirdcore" in rec.message for rec in caplog.records)


def test_no_leaf_category_falls_back_to_other():
    p = _load("full_konzert.json")
    p["categories"] = [{"name": "Konzerte"}]
    ev = parse_product(p)
    assert ev is not None
    assert ev.category == "other"
