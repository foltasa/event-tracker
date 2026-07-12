"""Canonical category vocabulary for the recommender.

Kept separate from `app/ingestion/categorize_prompts.py` because the
recommender needs a stable Python constant it can iterate. If the
classifier vocabulary ever changes, update BOTH files."""

CATEGORIES: list[str] = [
    "concerts", "party", "comedy", "theater", "arts", "literature",
    "film", "family", "food", "sports", "outdoor", "other", "unknown",
]

# User-selectable in About Me. Excludes classifier fallbacks.
USER_SELECTABLE_CATEGORIES: list[str] = [
    c for c in CATEGORIES if c not in ("other", "unknown")
]
