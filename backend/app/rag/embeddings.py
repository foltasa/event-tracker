"""Embeddings client. Routes via OpenRouter using the OpenAI SDK
(OpenRouter is OpenAI-API-compatible)."""
from openai import OpenAI

from app.config import settings

_client = OpenAI(
    api_key=settings.openrouter_api_key or "missing",
    base_url="https://openrouter.ai/api/v1",
)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = _client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in resp.data]


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
