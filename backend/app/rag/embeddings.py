"""Embeddings client. Routes via OpenRouter using the OpenAI SDK
(OpenRouter is OpenAI-API-compatible)."""
from openai import OpenAI

from app.config import settings

_client = OpenAI(
    api_key=settings.openrouter_api_key or "missing",
    base_url="https://openrouter.ai/api/v1",
)

# OpenAI's embeddings API rejects batches that exceed ~300k tokens per
# request. At ~500 tokens per event (title + description) we stay well
# under that with 100 rows per batch.
_EMBED_BATCH_SIZE = 100


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    out: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH_SIZE):
        chunk = texts[i : i + _EMBED_BATCH_SIZE]
        resp = _client.embeddings.create(model=settings.embedding_model, input=chunk)
        out.extend(item.embedding for item in resp.data)
    return out


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
