"""Agent prompt templates.

Tasks 12 fills these in fully. The Summary prompt is needed for memory.py
imports at Task 8, so it is defined here from the start."""

SUMMARY_PROMPT = """\
You are summarising a user's event taste based on their reactions.

Interests (stated): {interests}
About-me: {about_me}

Recent feedback (newest first):
{feedback}

Recently saved:
{saved}

Write a single paragraph of at most 80 words capturing the user's taste -
what they consistently like, what they dislike, and any patterns
(venue type, vibe, day of week). Use natural language. No lists.
"""

CURATION_PROMPT = "PLACEHOLDER - replaced in Task 12"
CONVERSATIONAL_PROMPT = "PLACEHOLDER - replaced in Task 12"
