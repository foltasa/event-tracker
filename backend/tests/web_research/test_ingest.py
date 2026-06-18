from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.schemas import ToolError
from app.db.models import Event
from app.web_research.schemas import WebExtractedEvent

BERLIN = timezone(timedelta(hours=2))


def _make_extracted(title="Hamlet", source_url="https://thalia-theater.de/x"):
    return WebExtractedEvent(
        title=title,
        start_datetime=datetime(2026, 6, 19, 19, 30, tzinfo=BERLIN),
        source_url=source_url,
        venue_name="Großes Haus",
        category="theater",
    )


def test_happy_path_inserts_events_and_embeds(db_session):
    extracted_list = [_make_extracted("Hamlet"), _make_extracted("Faust")]
    with patch("app.web_research.ingest.client.extract", return_value="page text"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=extracted_list), \
         patch("app.web_research.ingest.chroma_upsert") as chroma_mock:
        from app.web_research.ingest import ingest_event_from_url
        report = ingest_event_from_url(
            url="https://thalia-theater.de/x",
            session=db_session,
        )

    assert report["ingested"] == 2
    assert report["updated"] == 0
    assert report["skipped"] == 0
    assert len(report["event_ids"]) == 2
    chroma_mock.assert_called_once()
    rows = db_session.query(Event).all()
    assert len(rows) == 2
    assert {r.title for r in rows} == {"Hamlet", "Faust"}
    assert all(r.source == "web_search" for r in rows)


def test_dedup_on_second_call_yields_updates_not_inserts(db_session):
    extracted = [_make_extracted("Hamlet")]
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=extracted), \
         patch("app.web_research.ingest.chroma_upsert"):
        from app.web_research.ingest import ingest_event_from_url
        r1 = ingest_event_from_url(url="https://thalia-theater.de/x", session=db_session)
        r2 = ingest_event_from_url(url="https://thalia-theater.de/x", session=db_session)

    assert r1["ingested"] == 1 and r1["updated"] == 0
    assert r2["ingested"] == 0 and r2["updated"] == 1


def test_origin_mismatch_drops_event(db_session):
    extracted = [_make_extracted(source_url="https://attacker.example/x")]
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=extracted), \
         patch("app.web_research.ingest.chroma_upsert"):
        from app.web_research.ingest import ingest_event_from_url
        report = ingest_event_from_url(
            url="https://thalia-theater.de/x",
            session=db_session,
        )
    assert report["ingested"] == 0
    assert report["skipped"] == 1


def test_no_events_extracted_returns_zero_report(db_session):
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=[]), \
         patch("app.web_research.ingest.chroma_upsert") as chroma_mock:
        from app.web_research.ingest import ingest_event_from_url
        report = ingest_event_from_url(
            url="https://thalia-theater.de/x",
            session=db_session,
        )
    assert report == {"ingested": 0, "updated": 0, "skipped": 0, "event_ids": []}
    chroma_mock.assert_not_called()


def test_extractor_failure_propagates_as_toolerror(db_session):
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events",
               side_effect=ToolError("extraction failed")):
        from app.web_research.ingest import ingest_event_from_url
        with pytest.raises(ToolError):
            ingest_event_from_url(url="https://thalia-theater.de/x", session=db_session)


def test_chroma_failure_is_swallowed(db_session):
    extracted = [_make_extracted("Hamlet")]
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=extracted), \
         patch("app.web_research.ingest.chroma_upsert", side_effect=RuntimeError("chroma down")):
        from app.web_research.ingest import ingest_event_from_url
        report = ingest_event_from_url(url="https://thalia-theater.de/x", session=db_session)
    # SQL succeeded even though chroma failed:
    assert report["ingested"] == 1
    assert db_session.query(Event).count() == 1


def test_allowed_domains_blocks_disallowed_url(db_session, monkeypatch):
    monkeypatch.setattr("app.web_research.ingest.settings.web_search_allowed_domains", "thalia-theater.de")
    with patch("app.web_research.ingest.client.extract") as extract_mock:
        from app.web_research.ingest import ingest_event_from_url
        with pytest.raises(ToolError, match="not allowed"):
            ingest_event_from_url(url="https://attacker.example/x", session=db_session)
    extract_mock.assert_not_called()


def test_empty_allowed_domains_allows_everything(db_session, monkeypatch):
    monkeypatch.setattr("app.web_research.ingest.settings.web_search_allowed_domains", "")
    with patch("app.web_research.ingest.client.extract", return_value="t"), \
         patch("app.web_research.ingest.extractor.extract_events", return_value=[]), \
         patch("app.web_research.ingest.chroma_upsert"):
        from app.web_research.ingest import ingest_event_from_url
        # Should not raise:
        ingest_event_from_url(url="https://any-domain.example/x", session=db_session)
