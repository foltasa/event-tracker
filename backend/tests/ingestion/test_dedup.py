import pytest

from app.ingestion.dedup import _normalize_venue, _title_jaccard


class TestNormalizeVenue:
    def test_lowercase_and_strip(self):
        assert _normalize_venue("  Laeiszhalle  ") == "laeiszhalle"

    def test_strips_parenthesized_hall_suffix(self):
        assert _normalize_venue("Laeiszhalle (Großer Saal)") == "laeiszhalle"
        assert _normalize_venue("Elbphilharmonie (Kleiner Saal)") == "elbphilharmonie"

    def test_splits_camelcase(self):
        assert _normalize_venue("DeutschesSchauSpielHausHamburg") == "deutsches schau spiel haus hamburg"

    def test_collapses_whitespace_runs(self):
        assert _normalize_venue("Thalia   Theater\tHamburg") == "thalia theater hamburg"

    def test_none_and_empty(self):
        assert _normalize_venue(None) == ""
        assert _normalize_venue("") == ""
        assert _normalize_venue("   ") == ""

    def test_combined_camelcase_and_paren(self):
        assert _normalize_venue("JungesSchauSpielHaus (Malersaal)") == "junges schau spiel haus"


class TestTitleJaccard:
    def test_identical_titles_return_one(self):
        assert _title_jaccard("Hamlet", "Hamlet") == 1.0

    def test_case_insensitive(self):
        assert _title_jaccard("Hamlet", "hamlet") == 1.0

    def test_punctuation_stripped(self):
        assert _title_jaccard("Hamlet!", "Hamlet.") == 1.0

    def test_hamlet_with_subtitle(self):
        # {"hamlet"} vs {"hamlet", "premiere"} -> 1/2
        assert _title_jaccard("Hamlet", "Hamlet (Premiere)") == pytest.approx(0.5)

    def test_disjoint_titles(self):
        assert _title_jaccard("Batman", "Barbie") == 0.0

    def test_none_or_empty(self):
        assert _title_jaccard(None, "Hamlet") == 0.0
        assert _title_jaccard("Hamlet", None) == 0.0
        assert _title_jaccard("", "") == 0.0

    def test_multi_word_overlap(self):
        # {"der", "kirschgarten"} vs {"kirschgarten"} -> 1/2
        assert _title_jaccard("Der Kirschgarten", "Kirschgarten") == pytest.approx(0.5)
