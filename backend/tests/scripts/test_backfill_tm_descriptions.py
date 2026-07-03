from datetime import datetime, timezone

import httpx

from app.db.models import Event
from scripts import backfill_tm_descriptions


class _FakeHttp:
    """Records GET calls; returns a queued JSON body per URL prefix."""

    def __init__(self, url_to_body: dict[str, dict]):
        self._map = url_to_body
        self.calls: list[str] = []

    def get(self, url: str, **kwargs) -> httpx.Response:
        self.calls.append(url)
        for prefix, body in self._map.items():
            if url.startswith(prefix):
                return httpx.Response(200, json=body, request=httpx.Request("GET", url))
        raise AssertionError(f"unexpected GET {url}")


_ATTR_WITH_WIKI = {
    "externalLinks": {"wiki": [{"url": "https://en.wikipedia.org/wiki/Don_Toliver"}]}
}

_WIKI_BODY = {
    "type": "standard",
    "extract": "Don Toliver is an American rapper.",
}


def _seed(session, id_, description, source="ticketmaster", raw_data=None):
    session.add(Event(
        id=id_, external_id=id_, source=source, title="T", description=description,
        start_datetime=datetime(2026, 7, 15, 20, 0, tzinfo=timezone.utc),
        category="music", tags=[], source_url="https://tm/e", raw_data=raw_data or {},
    ))
    session.commit()


def test_backfill_updates_missing_descriptions(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e2", "",   raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e3", "Already.", raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e4", None, source="eventbrite",
          raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})

    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver": _WIKI_BODY,
    })
    report = backfill_tm_descriptions.run(db_session, http_client=http)

    assert report["scanned"] == 2  # e1, e2 (e3 already has, e4 is not TM)
    assert report["updated"] == 2
    assert report["failed"] == 0
    db_session.expire_all()
    assert db_session.query(Event).filter_by(id="e1").one().description.startswith("Don Toliver")
    assert db_session.query(Event).filter_by(id="e2").one().description.startswith("Don Toliver")
    assert db_session.query(Event).filter_by(id="e3").one().description == "Already."
    assert db_session.query(Event).filter_by(id="e4").one().description is None


def test_backfill_caches_across_events_with_same_artist(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    _seed(db_session, "e2", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})

    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver": _WIKI_BODY,
    })
    backfill_tm_descriptions.run(db_session, http_client=http)
    # Both events updated but Wikipedia hit only once.
    assert len(http.calls) == 1


def test_backfill_is_idempotent(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver": _WIKI_BODY,
    })
    first = backfill_tm_descriptions.run(db_session, http_client=http)
    second = backfill_tm_descriptions.run(db_session, http_client=http)
    assert first["updated"] == 1
    assert second["scanned"] == 0
    assert second["updated"] == 0


def test_backfill_records_failure_when_no_wiki_link(db_session):
    _seed(db_session, "e1", None,
          raw_data={"_embedded": {"attractions": [{"externalLinks": {}}]}})
    http = _FakeHttp({})
    report = backfill_tm_descriptions.run(db_session, http_client=http)
    assert report["scanned"] == 1
    assert report["updated"] == 0
    assert report["failed"] == 1


def test_backfill_records_failure_on_disambiguation(db_session):
    _seed(db_session, "e1", None, raw_data={"_embedded": {"attractions": [_ATTR_WITH_WIKI]}})
    http = _FakeHttp({
        "https://en.wikipedia.org/api/rest_v1/page/summary/Don_Toliver":
            {"type": "disambiguation", "extract": "Don may refer to..."},
    })
    report = backfill_tm_descriptions.run(db_session, http_client=http)
    assert report["updated"] == 0
    assert report["failed"] == 1
