"""LLM-based event categorization with content-hash caching.

Runs between adapter fetch and DB upsert. Treats the scraper's substring-
mapped category as a hint, not authority. Cache keyed on the hash of the
event's semantic fields (title, description, venue, tags, provider hint)
so each unique event is classified exactly once across ingestion runs."""
import hashlib
import logging
from typing import Literal, Protocol

from bs4 import BeautifulSoup
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models.event_category_cache import EventCategoryCache
from app.ingestion.categorize_prompts import SYSTEM_PROMPT, render_user_prompt
from app.ingestion.normalize import NormalizedEvent
from app.schemas.common import EventCategory

logger = logging.getLogger(__name__)


def _strip_html(text: str | None) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)


def content_hash(event: NormalizedEvent) -> str:
    """Return a stable sha256 hex over the event's semantic identity.

    Fields included: title, description (HTML-stripped), venue_name, tags
    (order-independent), and event.category (the provider's hint). Anything
    that can change without affecting classification — datetime, price,
    external_id, source_url, image_url — is excluded so re-fetches of the
    same event hit the cache."""
    parts = [
        event.title or "",
        _strip_html(event.description),
        event.venue_name or "",
        "|".join(sorted(event.tags)),
        event.category,
    ]
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CategoryDecision(BaseModel):
    """LLM's classification result. `unknown` means the model was not
    confident enough to pick one of the enum values."""

    category: EventCategory | Literal["unknown"]


class CategoryCache:
    """Thin wrapper over `event_category_cache` for get/set-by-hash access.

    Uses SQLite's INSERT OR IGNORE so concurrent runs / retries never fight
    over the same key. Does not commit — caller controls transaction."""

    def __init__(self, session: Session, model_name: str):
        self._session = session
        self._model_name = model_name

    def get(self, content_hash: str) -> str | None:
        row = (
            self._session.query(EventCategoryCache)
            .filter_by(content_hash=content_hash)
            .one_or_none()
        )
        return row.category if row else None

    def set(self, content_hash: str, category: str) -> None:
        stmt = sqlite_insert(EventCategoryCache).values(
            content_hash=content_hash,
            category=category,
            model=self._model_name,
        ).on_conflict_do_nothing(index_elements=["content_hash"])
        self._session.execute(stmt)


class LLMClassifier(Protocol):
    """Structural type for the categorization LLM. Any object with a
    `classify(event) -> CategoryDecision` method satisfies this, including
    real LangChain wrappers and test doubles."""

    def classify(self, event: NormalizedEvent) -> CategoryDecision: ...


def refine_category(
    event: NormalizedEvent,
    cache: CategoryCache,
    classifier: LLMClassifier,
) -> EventCategory:
    """Return the final category for `event`.

    Contract:
    - Cache hit with a valid category → return it directly.
    - Cache hit with 'unknown' → return `event.category` (provider hint).
    - Cache miss → call the classifier.
      - success with valid enum → cache + return.
      - success with 'unknown' → cache 'unknown' + return `event.category`.
      - any exception → return `event.category`, do NOT cache.
    """
    hash_ = content_hash(event)
    cached = cache.get(hash_)
    if cached is not None:
        if cached == "unknown":
            return event.category
        return cached  # type: ignore[return-value]

    try:
        decision = classifier.classify(event)
    except Exception:  # noqa: BLE001 — defensive: any classifier failure falls back
        logger.warning(
            "categorize: classifier failed for '%s' — using provider hint '%s'",
            event.title, event.category, exc_info=True,
        )
        return event.category

    if decision.category == "unknown":
        cache.set(hash_, "unknown")
        return event.category

    cache.set(hash_, decision.category)
    return decision.category


def build_categorization_llm() -> ChatOpenAI:
    """Configured LangChain client for the categorization LLM.

    Reuses OpenRouter (same pattern as `app.agent.llm.build_llm`) so we
    don't add a new provider. Temperature=0 for reproducibility; timeout
    keeps the ingestion loop bounded per event."""
    return ChatOpenAI(
        model=settings.categorization_model,
        api_key=settings.openrouter_api_key or "missing",
        base_url="https://openrouter.ai/api/v1",
        temperature=0,
        timeout=settings.categorization_timeout_seconds,
        max_retries=2,
    )


class LangchainClassifier:
    """Concrete `LLMClassifier` backed by a LangChain chat model with
    structured output. Constructed once per ingestion run; safe to reuse."""

    def __init__(self, llm: ChatOpenAI | None = None):
        base = llm if llm is not None else build_categorization_llm()
        self._structured = base.with_structured_output(CategoryDecision)

    def classify(self, event: NormalizedEvent) -> CategoryDecision:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=render_user_prompt(event)),
        ]
        return self._structured.invoke(messages)
