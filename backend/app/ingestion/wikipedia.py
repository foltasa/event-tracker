"""Pure helpers for turning a Wikipedia URL into a REST summary lookup.

Two pieces:
- wiki_title_from_url: parse a Wikipedia URL into (host, title).
- extract_summary: pull the plain-text extract from a Wikipedia REST
  /api/rest_v1/page/summary/{title} response, skipping disambiguation pages.
"""
from urllib.parse import unquote, urlparse


def wiki_title_from_url(url: str | None) -> tuple[str, str] | None:
    """Parse a Wikipedia article URL.

    Returns (host, title) where title is URL-decoded, or None if the URL
    does not look like a Wikipedia article link.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if not parsed.netloc.endswith("wikipedia.org"):
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "wiki":
        return None
    title = unquote("/".join(parts[1:]))
    if not title:
        return None
    return parsed.netloc, title


def extract_summary(body: dict) -> str | None:
    """Return the plain-text summary from a Wikipedia REST summary response.

    Skips disambiguation pages (type == 'disambiguation') — their extract
    is a list of links, not editorial content.
    """
    if not isinstance(body, dict):
        return None
    if body.get("type") == "disambiguation":
        return None
    extract = body.get("extract")
    if not isinstance(extract, str):
        return None
    text = extract.strip()
    return text or None
