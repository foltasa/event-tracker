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
    def __init__(self, html: str, status_code: int = 200):
        self._html = html
        self._status_code = status_code

    def get(self, url: str, **kwargs) -> httpx.Response:
        return httpx.Response(
            self._status_code,
            text=self._html,
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
    with pytest.raises(Exception):
        list(HamburgScraper(client=_FakeClient("", status_code=500)).fetch())
