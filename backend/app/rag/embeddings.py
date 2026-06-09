"""OpenAI embeddings client. Uses OpenAI directly (not via OpenRouter) for
embeddings — OpenRouter does not proxy text-embedding-3-small."""
from openai import OpenAI

from app.config import settings

# Use a placeholder when no key is configured so module import never fails
# (e.g. in tests, which patch `_client` directly). Real API calls without a
# valid key will fail at request time, which is the desired behavior.
_client = OpenAI(api_key=settings.openai_api_key or "missing")


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    resp = _client.embeddings.create(model=settings.embedding_model, input=texts)
    return [item.embedding for item in resp.data]


def embed_one(text: str) -> list[float]:
    vectors = embed_texts([text])
    return vectors[0]
