import base64
import json
from pathlib import Path

import pytest

from app.ingestion.scrapers.theater_hamburg import _extract_jwt


_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _make_jwt(issuer: str, sub: str = "1") -> str:
    """Construct a syntactically valid JWT with the given `iss` claim.

    The signature segment is arbitrary — _extract_jwt only reads the payload.
    Vary `sub` to produce different tokens with the same issuer."""
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": issuer, "sub": sub}).encode()
    ).decode().rstrip("=")
    signature = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"  # 33 chars, base64url shape
    return f"{header}.{payload}.{signature}"


class TestExtractJwt:
    def test_extracts_hht_token_from_real_widget_js_fixture(self):
        js = (_FIXTURE_DIR / "theater_hamburg_widget_sample.js").read_text(encoding="utf-8")
        token = _extract_jwt(js)
        assert token is not None
        assert token.startswith("ey")
        assert token.count(".") == 2
        # Decode payload; must be the HHT tenant, not any of the peers.
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert "hht.imxplatform.de" in payload["iss"]

    def test_returns_none_when_no_graphql_bearer_token_present(self):
        assert _extract_jwt("var x = 1; footerLogo:'/x.svg', ") is None

    def test_picks_hht_token_when_bundle_ships_multiple_tenants(self):
        nrw = _make_jwt("https://nrw.imxplatform.de/oauth")
        hht = _make_jwt("https://hht.imxplatform.de/oauth")
        freiburg = _make_jwt("https://freiburg.imxplatform.de/oauth")
        js = (
            f'x = {{ graphqlBearerToken:"{nrw}" }}; '
            f'y = {{ graphqlBearerToken:"{freiburg}" }}; '
            f'z = {{ graphqlBearerToken:"{hht}" }};'
        )
        assert _extract_jwt(js) == hht

    def test_returns_none_when_only_non_hht_tokens_present(self):
        nrw = _make_jwt("https://nrw.imxplatform.de/oauth")
        assert _extract_jwt(f'graphqlBearerToken:"{nrw}"') is None

    def test_returns_none_when_graphql_bearer_token_key_present_but_value_not_jwt_shaped(self):
        assert _extract_jwt('graphqlBearerToken:"not-a-jwt"') is None

    def test_returns_none_when_payload_undecodable(self):
        # Three "." segments but middle segment isn't valid base64/json.
        assert _extract_jwt('graphqlBearerToken:"eyAAA.@@@notb64@@@.CCC"') is None


import httpx

from app.ingestion.scrapers.theater_hamburg import (
    TheaterHamburgAdapter,
    _WIDGET_JS_URL,
    _API_URL,
)


class _FakeClient:
    """Records GET and POST calls; returns queued responses by URL prefix."""

    def __init__(self, get_map: dict[str, str] | None = None, post_map: dict | None = None):
        self.get_map = get_map or {}
        self.post_map = post_map or {}
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append(url)
        for prefix, text in self.get_map.items():
            if url.startswith(prefix):
                return httpx.Response(200, text=text, request=httpx.Request("GET", url))
        return httpx.Response(404, request=httpx.Request("GET", url))

    def post(self, url: str, *, json: dict, headers: dict, **kwargs):
        self.post_calls.append((url, json, headers))
        for prefix, handler in self.post_map.items():
            if url.startswith(prefix):
                body = handler(json) if callable(handler) else handler
                return httpx.Response(200, json=body, request=httpx.Request("POST", url))
        return httpx.Response(404, request=httpx.Request("POST", url))


_HHT_JWT = _make_jwt("https://hht.imxplatform.de/oauth", sub="4327")
_NEW_HHT_JWT = _make_jwt("https://hht.imxplatform.de/oauth", sub="rotated")
_WIDGET_JS_WITH_JWT = f'var config = {{ graphqlBearerToken:"{_HHT_JWT}" }};'
_WIDGET_JS_WITH_NEW_JWT = f'graphqlBearerToken:"{_NEW_HHT_JWT}"'


def _list_response(nodes: list[dict], total_pages: int = 1) -> dict:
    return {
        "data": {
            "events": {
                "nodes": nodes,
                "pagination": {"totalPages": total_pages, "totalRecords": len(nodes)},
            }
        }
    }


def _make_node(
    permalink: str = "hamlet-thalia",
    title: str = "Hamlet",
    venue_id: int = 99,
    venue_title: str = "Thalia Theater",
    dates: list[dict] | None = None,
    categories: list[str] | None = None,
    short_description: str | None = "<p>A brief show.</p>",
) -> dict:
    return {
        "id": 12345,
        "title": title,
        "permaLink": permalink,
        "shortDescription": short_description,
        "categories": [{"id": i, "i18nName": c} for i, c in enumerate(categories or ["Theater"])],
        "location": {"id": venue_id, "title": venue_title},
        "eventDates": dates or [{"date": "2026-07-20", "startTime": "20:00:00", "duration": 120}],
        "geoInfo": {"coordinates": {"latitude": 53.55, "longitude": 10.0}},
        "bookingLink": "https://tix.example/hamlet",
    }


class TestAdapterInit:
    def test_scrapes_jwt_from_widget_js_on_first_use(self):
        client = _FakeClient(get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT})
        adapter = TheaterHamburgAdapter(client=client)
        assert adapter._get_jwt() == _HHT_JWT
        assert client.get_calls == [_WIDGET_JS_URL]

    def test_jwt_env_override_skips_scrape(self, monkeypatch):
        # env override bypasses the iss-claim check — operator is expected to supply a working token.
        monkeypatch.setenv("THEATER_HAMBURG_JWT", "eyOVERRIDE.PART.SIG")
        client = _FakeClient()
        adapter = TheaterHamburgAdapter(client=client)
        assert adapter._get_jwt() == "eyOVERRIDE.PART.SIG"
        assert client.get_calls == []

    def test_raises_when_widget_js_has_no_jwt(self):
        client = _FakeClient(get_map={_WIDGET_JS_URL: "no token here"})
        adapter = TheaterHamburgAdapter(client=client)
        with pytest.raises(RuntimeError, match="JWT"):
            adapter._get_jwt()

    def test_raises_when_widget_js_only_has_peer_tenant_tokens(self):
        nrw = _make_jwt("https://nrw.imxplatform.de/oauth")
        js = f'graphqlBearerToken:"{nrw}"'
        client = _FakeClient(get_map={_WIDGET_JS_URL: js})
        adapter = TheaterHamburgAdapter(client=client)
        with pytest.raises(RuntimeError, match="JWT"):
            adapter._get_jwt()


class TestListFetch:
    def test_single_page_yields_one_event_per_date(self):
        node = _make_node(
            dates=[
                {"date": "2026-07-20", "startTime": "20:00:00", "duration": 120},
                {"date": "2026-07-21", "startTime": "20:00:00", "duration": 120},
            ],
            short_description="<p>Nice show.</p>",
        )
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node], total_pages=1)},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 2
        assert events[0].title == "Hamlet"
        assert events[0].description == "Nice show."
        # external_id is stable per (permalink, date, time).
        assert events[0].external_id == "hamlet-thalia#2026-07-20T20:00:00"
        assert events[1].external_id == "hamlet-thalia#2026-07-21T20:00:00"

    def test_paginates_until_last_page(self):
        node_a = _make_node(permalink="a", title="A")
        node_b = _make_node(permalink="b", title="B")

        def handler(body):
            page = body["variables"]["pagination"]["page"]
            if page == 1:
                return _list_response([node_a], total_pages=2)
            return _list_response([node_b], total_pages=2)

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert {e.title for e in events} == {"A", "B"}

    def test_duplicate_external_ids_across_pages_are_dropped(self):
        node = _make_node(permalink="dup", title="Dup", dates=[
            {"date": "2026-07-20", "startTime": "20:00:00", "duration": 120},
        ])

        def handler(body):
            page = body["variables"]["pagination"]["page"]
            # Same node on both pages; expected external_id is emitted only once.
            return _list_response([node], total_pages=2)

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: handler},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert events[0].external_id == "dup#2026-07-20T20:00:00"

    def test_duplicate_event_dates_on_same_node_are_dropped(self):
        node = _make_node(dates=[
            {"date": "2026-07-20", "startTime": "20:00:00", "duration": 120},
            {"date": "2026-07-20", "startTime": "20:00:00", "duration": 120},  # duplicate
        ])
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1

    def test_401_triggers_one_rescrape_and_retry(self):
        widget_calls = {"count": 0}
        first_jwt = _HHT_JWT

        class _RotatingClient(_FakeClient):
            def get(self, url, **kwargs):
                self.get_calls.append(url)
                widget_calls["count"] += 1
                text = (
                    _WIDGET_JS_WITH_JWT
                    if widget_calls["count"] == 1
                    else _WIDGET_JS_WITH_NEW_JWT
                )
                return httpx.Response(200, text=text, request=httpx.Request("GET", url))

            def post(self, url, *, json, headers, **kwargs):
                self.post_calls.append((url, json, headers))
                bearer = headers.get("Authorization", "")
                if bearer == f"Bearer {first_jwt}":
                    return httpx.Response(401, request=httpx.Request("POST", url))
                node = _make_node()
                return httpx.Response(
                    200,
                    json=_list_response([node]),
                    request=httpx.Request("POST", url),
                )

        client = _RotatingClient()
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert widget_calls["count"] == 2


class TestDescriptionParsing:
    def test_short_description_html_stripped(self):
        node = _make_node(short_description="<p>Line one.</p><br><em>Line two.</em>")
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert events[0].description == "Line one. Line two."

    def test_missing_short_description_leaves_none(self):
        node = _make_node(short_description=None)
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert events[0].description is None

    def test_empty_short_description_string_leaves_none(self):
        node = _make_node(short_description="")
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert events[0].description is None

    def test_real_fixture_end_to_end(self):
        """Parses the captured EventSearch JSON without erroring; sanity-check the shape."""
        import json
        search = json.loads(
            (_FIXTURE_DIR / "theater_hamburg_search_sample.json").read_text(encoding="utf-8")
        )
        # The fixture was captured mid-season so totalPages/totalRecords reflect the
        # live catalogue (394 pages).  Clamp to 1 page so the adapter stops after
        # processing the 5 sample nodes instead of making 393 more identical requests.
        search["data"]["events"]["pagination"]["totalPages"] = 1

        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: search},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        # Fixture has 5 nodes, each with 1 eventDate → 5 events.
        assert len(events) == 5
        assert all(e.source == "theater_hamburg" for e in events)
        # Every event in the fixture has a real shortDescription.
        assert all(e.description and len(e.description) > 50 for e in events)
        # tz-aware datetimes are enforced by NormalizedEvent.
        assert all(e.start_datetime.tzinfo is not None for e in events)


class TestMalformedResilience:
    def test_node_with_empty_event_dates_produces_no_events(self):
        node = _make_node()
        node["eventDates"] = []
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert events == []

    def test_date_entry_without_date_field_skipped(self):
        node = _make_node(dates=[
            {"startTime": "20:00:00", "duration": 120},  # missing 'date'
            {"date": "2026-07-20", "startTime": "20:00:00", "duration": 120},
        ])
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert events[0].start_datetime.date().isoformat() == "2026-07-20"

    def test_null_geo_info_yields_none_lat_lng(self):
        node = _make_node()
        node["geoInfo"] = None
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert events[0].latitude is None and events[0].longitude is None

    def test_null_location_yields_none_venue_name(self):
        node = _make_node()
        node["location"] = None
        client = _FakeClient(
            get_map={_WIDGET_JS_URL: _WIDGET_JS_WITH_JWT},
            post_map={_API_URL: lambda body: _list_response([node])},
        )
        adapter = TheaterHamburgAdapter(client=client)
        events = list(adapter.fetch())
        assert len(events) == 1
        assert events[0].venue_name is None
