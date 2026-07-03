import json
from pathlib import Path

from app.ingestion.wikipedia import extract_summary, wiki_title_from_url

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def test_wiki_title_from_url_english():
    assert wiki_title_from_url("https://en.wikipedia.org/wiki/Don_Toliver") == (
        "en.wikipedia.org",
        "Don_Toliver",
    )


def test_wiki_title_from_url_german_with_percent_encoding():
    assert wiki_title_from_url(
        "https://de.wikipedia.org/wiki/Herbert_Gr%C3%B6nemeyer"
    ) == ("de.wikipedia.org", "Herbert_Grönemeyer")


def test_wiki_title_from_url_none_on_non_wiki():
    assert wiki_title_from_url("https://example.com/foo") is None


def test_wiki_title_from_url_none_on_empty():
    assert wiki_title_from_url("") is None
    assert wiki_title_from_url(None) is None


def test_wiki_title_from_url_none_on_malformed_path():
    # No /wiki/ prefix, just the domain.
    assert wiki_title_from_url("https://en.wikipedia.org/") is None


def test_extract_summary_from_real_fixture():
    body = json.loads(
        (_FIXTURE_DIR / "wiki_summary_sample.json").read_text(encoding="utf-8")
    )
    summary = extract_summary(body)
    assert summary is not None
    assert len(summary) >= 40
    assert "Duran Duran" in summary


def test_extract_summary_returns_none_for_disambiguation():
    body = {"type": "disambiguation", "extract": "Foo may refer to:"}
    assert extract_summary(body) is None


def test_extract_summary_returns_none_when_extract_missing():
    assert extract_summary({"type": "standard"}) is None


def test_extract_summary_returns_none_on_empty_extract():
    assert extract_summary({"type": "standard", "extract": "   "}) is None


def test_extract_summary_returns_none_on_non_dict():
    assert extract_summary(None) is None
    assert extract_summary("just a string") is None
