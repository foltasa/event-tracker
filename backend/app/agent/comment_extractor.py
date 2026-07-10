"""LLM extractor that turns free-text feedback comments and About-Me notes
into structured facet updates."""
import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agent.categories import CATEGORIES
from app.agent.facets import apply_facet_delta
from app.agent.llm import build_llm
from app.db.models import User

logger = logging.getLogger(__name__)


ALLOWED_FIELDS = (
    "artists", "genres", "venues", "weekday_pref",
    "disliked.artists", "disliked.genres",
)


class FacetUpdate(BaseModel):
    category: str
    field: Literal[
        "artists", "genres", "venues", "weekday_pref",
        "disliked.artists", "disliked.genres",
    ]
    key: str = Field(min_length=1)
    delta: float = Field(ge=-1.0, le=1.0)


class ExtractorOutput(BaseModel):
    facet_updates: list[FacetUpdate] = Field(default_factory=list)


class ExtractorInput(BaseModel):
    category: str
    source_kind: Literal["feedback", "about_me_notes"]
    event_context: dict  # {"title", "venue", "description"} — empty for about_me_notes
    text: str


_SYSTEM = """\
You extract structured taste updates from a user's short comment about an event
or a note they wrote about a category.

Return facet_updates as a list of small changes to their taste profile.

Vocabulary rules:
- category MUST be one of: concerts, party, comedy, theater, arts, literature,
  film, family, food, sports, outdoor.
- field MUST be one of: artists, genres, venues, weekday_pref,
  disliked.artists, disliked.genres.
- key is the specific item (e.g. artist name, genre string, venue name,
  weekday code "mon"/"tue"/... for weekday_pref).
- delta is between -1.0 and 1.0. Use +0.2..+0.4 for a passing positive mention,
  +0.5..+0.8 for a strong positive, +1.0 for "love this". Use similar magnitudes
  on disliked.* for negatives.

If the text doesn't contain a taste signal, return facet_updates: [].
"""


def _render_user_turn(inp: ExtractorInput) -> str:
    parts = [f"Category: {inp.category}", f"Source: {inp.source_kind}"]
    ctx = inp.event_context or {}
    if inp.source_kind == "feedback":
        parts.append(f"Event title: {ctx.get('title', '')}")
        parts.append(f"Venue: {ctx.get('venue', '')}")
        parts.append(f"Description: {(ctx.get('description') or '')[:400]}")
    parts.append("")
    parts.append(f"User text: {inp.text}")
    return "\n".join(parts)


def _default_llm():
    return build_llm().with_structured_output(ExtractorOutput)


def extract_and_apply(
    session: Session,
    user_id: str,
    input_: ExtractorInput,
    llm=None,
) -> None:
    """Run the extractor and mutate `users.taste_facets` accordingly.

    On any LLM failure this is a no-op — comments are safe on the feedback
    row and can be reprocessed later. Never raises to the caller."""
    llm = llm or _default_llm()
    try:
        output: ExtractorOutput = llm.invoke(
            [
                SystemMessage(content=_SYSTEM),
                HumanMessage(content=_render_user_turn(input_)),
            ]
        )
    except Exception:
        logger.exception("Comment extractor failed for user %s", user_id)
        return

    user = session.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        return
    facets = dict(user.taste_facets or {})
    for u in output.facet_updates:
        if u.category not in CATEGORIES:
            continue
        apply_facet_delta(facets, u.category, u.field, u.key, u.delta)
    user.taste_facets = facets
    # SQLAlchemy JSON column doesn't detect in-place nested mutations; force flag.
    flag_modified(user, "taste_facets")
    session.commit()
