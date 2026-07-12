from app.agent.categories import CATEGORIES, USER_SELECTABLE_CATEGORIES


def test_categories_contain_expected_top_level():
    for expected in [
        "concerts", "party", "comedy", "theater", "arts", "literature",
        "film", "family", "food", "sports", "outdoor",
    ]:
        assert expected in CATEGORIES


def test_categories_include_classifier_fallbacks():
    assert "other" in CATEGORIES
    assert "unknown" in CATEGORIES


def test_user_selectable_excludes_fallbacks():
    assert "other" not in USER_SELECTABLE_CATEGORIES
    assert "unknown" not in USER_SELECTABLE_CATEGORIES
    for c in USER_SELECTABLE_CATEGORIES:
        assert c in CATEGORIES
