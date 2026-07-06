from datetime import datetime, timezone
from pathlib import Path

from app.ingestion.scrapers.ohschonhell import filter_sitemap

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _read_sitemap() -> str:
    return (_FIXTURE_DIR / "ohschonhell_sitemap_sample.xml").read_text(encoding="utf-8")


def test_filter_returns_only_date_urls_after_cutoff():
    xml = _read_sitemap()
    # Cutoff old enough that everything in the fixture qualifies.
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert all("/date/" in url for url, _ in entries)
    assert len(entries) >= 1


def test_filter_excludes_entries_before_cutoff():
    xml = _read_sitemap()
    # Cutoff in the future — nothing should qualify.
    cutoff = datetime(2100, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert entries == []


def test_filter_result_sorted_ascending_by_lastmod():
    xml = _read_sitemap()
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    lastmods = [lastmod for _, lastmod in entries]
    assert lastmods == sorted(lastmods)


def test_filter_returns_tz_aware_datetimes():
    xml = _read_sitemap()
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert entries, "fixture must yield entries"
    _, lastmod = entries[0]
    assert lastmod.tzinfo is not None
