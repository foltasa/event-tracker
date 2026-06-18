"""Tavily HTTP client.

Two operations:
  - search(query)  -> list[SearchHit dict]
  - extract(url)   -> raw text content

Every failure path raises ToolError so the agent layer sees data, not stacktraces.
"""
import logging

import httpx

from app.agent.schemas import ToolError
from app.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.tavily.com"
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def _require_key() -> str:
    if not settings.tavily_api_key:
        raise ToolError("web search not configured")
    return settings.tavily_api_key


def search(query: str) -> list[dict]:
    """Return up to settings.web_search_max_results hits.

    Each hit dict has at least: url, title, content (snippet)."""
    key = _require_key()
    body = {
        "api_key": key,
        "query": query,
        "max_results": settings.web_search_max_results,
        "search_depth": "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{_BASE}/search", json=body)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tavily search failed: %s", exc)
        raise ToolError("web search unavailable") from exc

    data = resp.json()
    results = data.get("results") or []
    return [
        {
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "content": r.get("content", ""),
        }
        for r in results
        if r.get("url")
    ]


def extract(url: str) -> str:
    """Fetch + extract main text content of a URL via Tavily's extract endpoint."""
    key = _require_key()
    body = {"api_key": key, "urls": [url]}
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{_BASE}/extract", json=body)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("tavily extract failed: %s", exc)
        raise ToolError("page not fetchable") from exc

    data = resp.json()
    results = data.get("results") or []
    if not results:
        raise ToolError("page not fetchable")
    return results[0].get("raw_content", "") or ""
