"""Pure helpers for the taste_facets JSON blob.

Kept side-effect-free so tests don't need a DB session and so both the
comment extractor and the About Me form save path can reuse them."""


def _ensure_path(facets: dict, category: str, field: str) -> dict:
    cat = facets.setdefault(category, {})
    bucket = cat.setdefault(field, {})
    return bucket


def apply_facet_delta(
    facets: dict,
    category: str,
    field: str,
    key: str,
    delta: float,
) -> None:
    """Add `delta` to facets[category][field][key], clamped to [0.0, 1.0].

    If the resulting value is <= 0, the key is removed to keep the blob
    lean. Missing intermediate structure is created on the fly."""
    bucket = _ensure_path(facets, category, field)
    current = float(bucket.get(key, 0.0))
    new_value = current + delta
    if new_value <= 0.0:
        bucket.pop(key, None)
        return
    if new_value > 1.0:
        new_value = 1.0
    bucket[key] = new_value


def initial_from_form(values: list[str], weight: float) -> dict[str, float]:
    """Turn a comma-separated form field into a {key: weight} dict.

    Trims whitespace, drops empty entries, deduplicates."""
    out: dict[str, float] = {}
    for v in values:
        key = (v or "").strip()
        if not key:
            continue
        out[key] = weight
    return out
