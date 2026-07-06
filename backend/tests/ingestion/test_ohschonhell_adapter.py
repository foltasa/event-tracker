"""End-to-end adapter tests using a fake httpx client.

Uses hand-rolled minimal sitemap and event HTML — self-contained so tests
don't depend on the exact contents of the on-disk fixtures."""
from datetime import datetime, timezone

import httpx
import pytest

from app.ingestion.scrapers.ohschonhell import OhschonhellScraper
from app.ingestion.state import get_last_seen, set_last_seen


_SITEMAP_TWO = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a</loc>
    <lastmod>2026-07-01T10:00:00+00:00</lastmod>
  </url>
  <url>
    <loc>https://ohschonhell.de/date/venue-b-hamburg-11-07-2026-party-b</loc>
    <lastmod>2026-07-02T11:00:00+00:00</lastmod>
  </url>
</urlset>"""


def _event_html(event_id: str, name: str) -> str:
    return f"""<!doctype html>
<html><head><meta property="og:image" content="https://cdn/{event_id}.jpg"></head>
<body>
<a href="/ajax/ical.php?eventId={event_id}&osh_page=hamburg">cal</a>
<div itemscope itemtype="http://schema.org/Event">
  <span itemprop=name>{name}</span>
  <time itemprop=startDate content="2026-07-10">10.07.2026, 23:00</time>
  <div itemprop=description>Great party</div>
  <div itemprop=location itemscope itemtype="http://schema.org/Place">
    <span itemprop=name>Venue X</span>
    <div itemprop=address itemscope itemtype="http://schema.org/PostalAddress">
      <span itemprop=streetAddress>Beispielstraße 1</span>
      <span itemprop=postalCode>20000</span>
      <span itemprop=addressLocality>Hamburg</span>
    </div>
  </div>
</div>
</body></html>"""


class _FakeClient:
    """Maps URL to sequence of (status, body) responses."""

    def __init__(self, routes: dict[str, list[tuple[int, str]]]):
        self._routes = {u: list(rs) for u, rs in routes.items()}

    def get(self, url: str, **kwargs) -> httpx.Response:
        seq = self._routes.get(url)
        if not seq:
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        status, body = seq.pop(0)
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))


@pytest.fixture
def routes_two_events():
    sitemap_url = "https://ohschonhell.de/post-sitemap26.xml"
    url_a = "https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a"
    url_b = "https://ohschonhell.de/date/venue-b-hamburg-11-07-2026-party-b"
    return {
        sitemap_url: [(200, _SITEMAP_TWO)],
        url_a: [(200, _event_html("111", "Party A"))],
        url_b: [(200, _event_html("222", "Party B"))],
    }, url_a, url_b


def test_bootstrap_yields_both_events_and_sets_state(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)

    events = list(scraper.fetch(db_session))
    db_session.flush()

    assert len(events) == 2
    ids = sorted(e.external_id for e in events)
    assert ids == ["111", "222"]
    assert all(e.source == "ohschonhell" for e in events)
    assert all(e.start_datetime.tzinfo is not None for e in events)
    # State advanced to the highest processed lastmod (2026-07-02T11:00Z).
    ts = get_last_seen(db_session, "ohschonhell")
    assert ts == datetime(2026, 7, 2, 11, 0, tzinfo=timezone.utc)


def test_delta_yields_only_new_events(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    # Pre-seed state so entry A (lastmod 2026-07-01T10:00Z) is skipped.
    set_last_seen(
        db_session, "ohschonhell", datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    )
    db_session.flush()

    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))

    assert [e.external_id for e in events] == ["222"]


def test_retry_exhausted_skips_event_and_does_not_advance_state(db_session):
    sitemap_url = "https://ohschonhell.de/post-sitemap26.xml"
    url_a = "https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a"
    # Single-entry sitemap containing only URL A.
    single_entry_sitemap = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a</loc>
    <lastmod>2026-07-01T10:00:00+00:00</lastmod>
  </url>
</urlset>"""
    routes = {
        sitemap_url: [(200, single_entry_sitemap)],
        url_a: [(429, ""), (429, ""), (429, "")],
    }
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)

    events = list(scraper.fetch(db_session))
    db_session.flush()

    assert events == []
    # No successful events -> state remains None.
    assert get_last_seen(db_session, "ohschonhell") is None


def test_parse_failure_skips_event_but_continues_batch(db_session, routes_two_events):
    routes, url_a, _ = routes_two_events
    # Overwrite URL A with malformed HTML (no Event microdata).
    routes[url_a] = [(200, "<html><body>nothing here</body></html>")]

    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))
    db_session.flush()

    assert [e.external_id for e in events] == ["222"]
    # State advanced to entry B (only entry that succeeded).
    ts = get_last_seen(db_session, "ohschonhell")
    assert ts == datetime(2026, 7, 2, 11, 0, tzinfo=timezone.utc)


def test_start_datetime_uses_berlin_timezone(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))
    assert events
    for ev in events:
        assert ev.start_datetime.year == 2026
        assert ev.start_datetime.hour == 23
        assert str(ev.start_datetime.tzinfo) == "Europe/Berlin"


def test_venue_address_is_combined_string(db_session, routes_two_events):
    routes, _, _ = routes_two_events
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)
    events = list(scraper.fetch(db_session))
    assert events[0].venue_address == "Beispielstraße 1, 20000 Hamburg"


def test_non_retriable_http_error_logged_separately(db_session, caplog):
    """A 404 should count as http-error, not retries-exhausted."""
    import logging as _logging
    caplog.set_level(_logging.INFO, logger="app.ingestion.scrapers.ohschonhell")

    sitemap_url = "https://ohschonhell.de/post-sitemap26.xml"
    url_a = "https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a"
    single_entry_sitemap = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
  <url>
    <loc>https://ohschonhell.de/date/venue-a-hamburg-10-07-2026-party-a</loc>
    <lastmod>2026-07-01T10:00:00+00:00</lastmod>
  </url>
</urlset>"""
    routes = {
        sitemap_url: [(200, single_entry_sitemap)],
        url_a: [(404, "")],
    }
    scraper = OhschonhellScraper(client=_FakeClient(routes), sleep_fn=lambda _s: None)

    events = list(scraper.fetch(db_session))
    assert events == []

    messages = " || ".join(r.getMessage() for r in caplog.records)
    assert "http error: 1" in messages
    assert "retries exhausted: 0" in messages
