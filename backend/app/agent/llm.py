"""ChatOpenAI client pointed at OpenRouter. Single provider for MVP;
multi-model UI plugs in here later."""
from langchain_openai import ChatOpenAI

from app.config import settings


def build_llm(model: str | None = None, temperature: float | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.agent_model,
        api_key=settings.openrouter_api_key or "missing",
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature if temperature is not None else settings.agent_temperature,
        streaming=True,
        max_retries=2,
    )
