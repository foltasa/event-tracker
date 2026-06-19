"""Tool-less LLM call that parses raw web text into WebExtractedEvent[].

This is the trust boundary: the LLM has NO TOOLS BOUND. Its output is parsed
strictly as JSON and validated by Pydantic before any further processing.
"""
import json
import logging

from langchain_core.messages import SystemMessage
from pydantic import ValidationError

from app.agent.llm import build_llm
from app.agent.schemas import ToolError
from app.config import settings
from app.web_research.prompts import EXTRACTOR_SYSTEM_PROMPT
from app.web_research.schemas import WebExtractedEvent

logger = logging.getLogger(__name__)

# Truncate input to keep prompt size manageable (~150k chars ~= 35k tokens).
_MAX_INPUT_CHARS = 150_000


def _strip_fences(s: str) -> str:
    s = s.strip()
    # Remove leading ```json or ``` and trailing ```
    if s.startswith("```"):
        first_newline = s.find("\n")
        if first_newline != -1:
            s = s[first_newline + 1:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def extract_events(text: str, source_url: str) -> list[WebExtractedEvent]:
    """Run the extractor LLM and return validated WebExtractedEvent objects.

    Invalid individual events are dropped (logged). If the entire LLM output
    is unparseable JSON, raises ToolError("extraction failed")."""
    if not text:
        return []
    truncated = text[:_MAX_INPUT_CHARS]
    prompt = EXTRACTOR_SYSTEM_PROMPT.format(source_url=source_url, text=truncated)

    llm = build_llm(model=settings.web_search_extractor_model, temperature=0.0)
    response = llm.invoke([SystemMessage(content=prompt)])
    raw = _strip_fences(str(response.content))

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("extractor returned non-JSON: %r", raw[:200])
        raise ToolError("extraction failed") from exc

    if not isinstance(payload, list):
        logger.warning("extractor returned non-array: %r", type(payload).__name__)
        raise ToolError("extraction failed")

    events: list[WebExtractedEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            events.append(WebExtractedEvent(**item))
        except ValidationError as exc:
            logger.info("extractor item failed validation, skipping: %s", exc.errors()[:1])
            continue
    return events
