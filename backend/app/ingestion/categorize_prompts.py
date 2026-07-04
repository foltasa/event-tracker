"""System and user prompts for the LLM categorization step.

Held separate from `app.agent.prompts` because these prompts have a
different lifecycle (ingestion, not user-facing agent) and audience
(deterministic classifier, not conversational assistant)."""
from app.ingestion.normalize import NormalizedEvent

_MAX_DESCRIPTION_CHARS = 800

SYSTEM_PROMPT = """You classify cultural events into exactly one of these categories:

- music: concerts, DJ sets, classical performances in concert halls, opera performances
- theater: plays, musicals, tribute shows, cabaret, comedy shows, kabarett — including musical/tribute formats when they run as multi-week series in theater venues (e.g. a "Tribute to Jimi Hendrix" show at a Broadway-style theater is theater, not music)
- arts: exhibitions, ballet, contemporary dance, literary readings (Lesung)
- film: cinema screenings, film festivals
- family: children's events, family-oriented programming
- food: culinary events, tastings, food festivals
- sports: sports matches and tournaments
- tech: tech conferences, hackathons, meetups
- outdoor: outdoor recreation, nature events, hiking, park festivals
- other: anything that clearly does not fit the above

If you cannot confidently pick one, return "unknown".

Signals to weigh:
1. Venue name is a strong signal. Ohnsorg-Theater, St. Pauli Theater, Thalia, Ernst-Deutsch-Theater, Komödie Winterhuder Fährhaus, Centralkomitee → theater programming. Elbphilharmonie, Laeiszhalle, Barclays Arena → primarily music but not exclusively (they also host readings, ballet, etc.).
2. Title and description carry the actual content. A "Klavierabend" in a theater venue is still music. A tribute show with 20+ consecutive performances in a theater venue is theater.
3. Provider tags and hints are noisy — treat them as weak evidence. Provider tags like "weitere konzerte" are frequently applied to non-concert theater events.
4. Multi-week runs (30+ consecutive shows) strongly indicate theater rather than concert.

Return only the category value via structured output. No prose."""


def render_user_prompt(event: NormalizedEvent) -> str:
    """Format one event's signals for the user turn of the classification prompt."""
    description = (event.description or "").strip()
    if len(description) > _MAX_DESCRIPTION_CHARS:
        description = description[:_MAX_DESCRIPTION_CHARS].rstrip() + "…"

    tags_line = ", ".join(event.tags) if event.tags else "(none)"
    venue_line = event.venue_name or "(unknown)"
    description_line = description or "(none)"

    return (
        f"Title: {event.title}\n"
        f"Description: {description_line}\n"
        f"Venue: {venue_line}\n"
        f"Provider tags: {tags_line}\n"
        f"Source: {event.source}\n"
        f"Provider's suggested category: {event.category}\n"
        f"\n"
        f"Classify this event."
    )
