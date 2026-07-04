"""System and user prompts for the LLM categorization step.

Held separate from `app.agent.prompts` because these prompts have a
different lifecycle (ingestion, not user-facing agent) and audience
(deterministic classifier, not conversational assistant)."""
from app.ingestion.normalize import NormalizedEvent

_MAX_DESCRIPTION_CHARS = 800

SYSTEM_PROMPT = """You classify cultural events into exactly one of these categories:

- concerts: a named act performing live — rock, pop, classical, opera, jazz, singer-songwriter, choirs, big band. Seated or standing. Audience is there to LISTEN.
- party: DJ set, club night, rave, dance party. Audience is there to DANCE. If dancing is the point, it's party even with a live element.
- comedy: stand-up, Kabarett, sketch comedy, improv comedy.
- theater: plays (Schauspiel), musicals, multi-week tribute shows in theater venues, traditional Bühnenformate.
- arts: exhibitions (Ausstellung), ballet, contemporary dance. Static or performance-art visual formats.
- literature: readings (Lesung), poetry slams, book launches (Buchvorstellung), author talks (Autorengespräch).
- film: cinema screenings, film festivals.
- family: events primarily FOR / WITH children — Kinderkonzert, Kindertheater, Bastelkurs für Kinder. A "family-friendly" concert marketed at adults is NOT family; that's concerts. Family wins over content categories only when the event is kids-first.
- food: culinary events, tastings, food festivals.
- sports: sports matches, tournaments, athletic competitions.
- outdoor: hiking, nature events, park festivals without a clear content-category fit.
- other: anything that clearly does not fit the above.

If you cannot confidently pick one, return "unknown".

Signals to weigh:
1. Venue signals. Ohnsorg-Theater, St. Pauli Theater, Thalia, Ernst-Deutsch-Theater, Komödie Winterhuder Fährhaus, Centralkomitee → theater programming. Elbphilharmonie, Laeiszhalle, Barclays Arena → mostly concerts but also host readings, ballet, etc.
2. Content over hint. Title and description are the actual content. A "Klavierabend" at a theater venue → concerts. A tribute show with 20+ consecutive nights → theater.
3. Provider tags are noisy. Tags like "weitere konzerte" get applied to non-concert theater events. Weak evidence only.
4. Multi-week runs (30+ consecutive shows) indicate theater rather than concerts.
5. Concerts vs party: format decides, not venue. A named act playing their setlist → concerts, even in a club. A DJ playing tracks → party, even in a concert hall. Electronic-music festival with named live performers → concerts. Techno rave with anonymous/rotating DJs → party.
6. Family precedence: if the target audience is primarily children (title mentions "Kinder", "ab 4 Jahren", "Familienshow für Kinder"), pick family regardless of content. A rock concert marketed "for the whole family" is still concerts — family means kids-first.
7. Comedy vs theater: stand-up, Kabarett, sketch, improv → comedy. Musical, Schauspiel, drama, tribute show → theater. Comedy at a theater venue is still comedy (venue is weak here).
8. Literature vs arts: readings, poetry, book events → literature. Ballet, exhibitions, dance → arts. Verbal → literature, visual/movement → arts.

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
