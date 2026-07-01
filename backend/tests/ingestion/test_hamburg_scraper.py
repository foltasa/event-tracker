import httpx
import pytest

from app.ingestion.scrapers.hamburg import HamburgScraper

_HTML = """<!DOCTYPE html>
<html><body><main>
  <a href="/event/jazz-night-mojo"><img src="https://cdn.heuteinhamburg.de/img1.jpg" alt="Jazz Night"></a>
  <a href="/kategorie/musik">Musik</a>
  <a href="/event/jazz-night-mojo">Jazz Night at Mojo Club</a>
  <img src="/icons/icon-clock.svg" alt="Icon"> 20:30 Uhr
  <a href="https://maps.google.com/?q=Mojo+Club">
    <img src="/icons/icon-map.svg" alt="Icon"> Mojo Club
  </a>
  <a href="https://tickets.example.com/jazz">
    <img src="/icons/icon-ticket.svg" alt="Icon"> 18 €
  </a>

  <a href="/event/free-concert"><img src="https://cdn.heuteinhamburg.de/img2.jpg" alt="Free Concert"></a>
  <a href="/kategorie/outdoor">Outdoor</a>
  <a href="/event/free-concert">Free Summer Concert</a>
  <img src="/icons/icon-clock.svg" alt="Icon"> 16:00 Uhr
  <a href="https://maps.google.com/?q=Stadtpark">
    <img src="/icons/icon-map.svg" alt="Icon"> Stadtpark
  </a>
  <a href="#">
    <img src="/icons/icon-ticket.svg" alt="Icon"> kostenlos
  </a>
</main></body></html>"""

_EMPTY_HTML = "<html><body><main></main></body></html>"


class _FakeClient:
    def __init__(self, html: str, detail_html: str = "", status_code: int = 200):
        self._html = html
        self._detail_html = detail_html
        self._status_code = status_code

    def get(self, url: str, **kwargs) -> httpx.Response:
        is_detail = url != "https://heuteinhamburg.de"
        text = self._detail_html if is_detail else self._html
        return httpx.Response(
            self._status_code,
            text=text,
            request=httpx.Request("GET", url),
        )


def test_returns_two_events():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert len(events) == 2


def test_title_and_url():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].title == "Jazz Night at Mojo Club"
    assert events[0].source_url == "https://heuteinhamburg.de/event/jazz-night-mojo"
    assert events[0].external_id == "jazz-night-mojo"
    assert events[0].source == "hamburg_scraper"


def test_venue():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].venue_name == "Mojo Club"


def test_paid_price():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].is_free is False
    assert events[0].price_min == 18.0


def test_free_event():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[1].is_free is True
    assert events[1].price_min is None


def test_category_music():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].category == "music"


def test_category_outdoor():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[1].category == "outdoor"


def test_image_url():
    events = list(HamburgScraper(client=_FakeClient(_HTML)).fetch())
    assert events[0].image_url == "https://cdn.heuteinhamburg.de/img1.jpg"


def test_empty_page():
    assert list(HamburgScraper(client=_FakeClient(_EMPTY_HTML)).fetch()) == []


def test_http_error_raises():
    with pytest.raises(httpx.HTTPStatusError):
        list(HamburgScraper(client=_FakeClient("", status_code=500)).fetch())


# Detail-page HTML mirrors the real heuteinhamburg.de structure: description
# is in <meta name="description"> (the site is Next.js / SSR, description text
# is not in a separate <div class="description"> element).
_DETAIL_HTML = """<!DOCTYPE html>
<html><head>
  <meta name="description" content="Hamburg's finest jazz musicians gather for an unforgettable evening.">
</head><body><main>
  <h1>Jazz Night at Mojo Club</h1>
</main></body></html>"""


def test_description_from_detail_page():
    events = list(HamburgScraper(client=_FakeClient(_HTML, detail_html=_DETAIL_HTML)).fetch())
    assert events[0].description == "Hamburg's finest jazz musicians gather for an unforgettable evening."


def test_description_none_when_element_absent():
    events = list(HamburgScraper(client=_FakeClient(_HTML, detail_html="<html><body></body></html>")).fetch())
    assert events[0].description is None


def test_description_empty_meta_content_is_none():
    detail = '<html><head><meta name="description" content="  "></head><body></body></html>'
    events = list(HamburgScraper(client=_FakeClient(_HTML, detail_html=detail)).fetch())
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


def test_skips_malformed_and_continues():
    # An event anchor whose slug produces an error in _parse_card
    # (clock next-sibling raises during _parse_time) should be skipped;
    # a well-formed event after it should still be yielded.
    html = """<html><body><main>
      <a href="/event/bad-event">Bad Event</a>
      <img src="/icons/icon-clock.svg" alt="Icon">
      <a href="/event/good-event"><img src="https://cdn.example.com/good.jpg" alt="Good"></a>
      <a href="/kategorie/musik">Musik</a>
      <a href="/event/good-event">Good Event</a>
      <img src="/icons/icon-clock.svg" alt="Icon"> 19:00 Uhr
      <a href="https://maps.google.com/?q=Venue">
        <img src="/icons/icon-map.svg" alt="Icon"> Some Venue
      </a>
      <a href="#">
        <img src="/icons/icon-ticket.svg" alt="Icon"> kostenlos
      </a>
    </main></body></html>"""
    # bad-event has no category, venue, or price but is structurally valid enough
    # that _parse_card returns None (caught by the except guard) or just yields nothing.
    # good-event must always be yielded.
    events = list(HamburgScraper(client=_FakeClient(html)).fetch())
    slugs = [e.external_id for e in events]
    assert "good-event" in slugs
