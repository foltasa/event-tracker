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


def test_filter_treats_naive_lastmod_as_utc():
    """A <lastmod> without timezone offset must not crash the comparison
    against a tz-aware cutoff. We treat naive lastmods as UTC."""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ohschonhell.de/date/venue-naive-hamburg-01-08-2026-x</loc>
    <lastmod>2026-08-01T10:00:00</lastmod>
  </url>
</urlset>"""
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    entries = filter_sitemap(xml, cutoff)
    assert len(entries) == 1
    _, lastmod = entries[0]
    assert lastmod.tzinfo is not None
