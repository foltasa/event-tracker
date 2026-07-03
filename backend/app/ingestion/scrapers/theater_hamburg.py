"""Theater-Hamburg adapter — imxplatform GraphQL over httpx.

The whitelabel widget's data endpoint requires a Bearer JWT that is baked
into the public widget.js bundle at the key `graphqlBearerToken:"..."`.
The bundle also ships JWTs for other platform tenants (NRW etc.), so we
anchor on the specific key to select the Hamburg (HHT) token.

We scrape it on init and re-scrape once on 401 (see Task 4). All events
are Hamburg cultural venues with editorial shortDescription populated in
the list query response."""
import logging
import re

logger = logging.getLogger(__name__)

_WIDGET_JS_URL = "https://hht.whitelabel.imxplatform.de/widget/widget.js"
_JWT_RE = re.compile(
    r'graphqlBearerToken\s*:\s*"(ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"'
)


def _extract_jwt(js_body: str) -> str | None:
    """Return the JWT captured after `graphqlBearerToken:"..."`, or None."""
    m = _JWT_RE.search(js_body)
    return m.group(1) if m else None
