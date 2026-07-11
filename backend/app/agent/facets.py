"""Pure helpers for the taste_facets JSON blob.

Kept side-effect-free so tests don't need a DB session and so both the
comment extractor and the About Me form save path can reuse them."""


def format_taste_prose(user) -> str:
    """Render per-active-category facets as a compact prose block.

    Weights are dropped. Missing fields are omitted. Empty categories
    produce a `(nothing listed)` line so the LLM knows the category is
    active but has no user-typed hints."""
    active = list(user.active_categories or [])
    facets = user.taste_facets or {}
    if not active:
        return "(no active categories)"

    lines: list[str] = []
    for cat in active:
        cat_facets = facets.get(cat) or {}
        cat_lines: list[str] = []
        for field in ("artists", "genres", "venues"):
            bucket = cat_facets.get(field) or {}
            terms = [t for t in bucket.keys() if t]
            if terms:
                cat_lines.append(f"    {field}: {', '.join(terms)}")
        notes = cat_facets.get("notes")
        if isinstance(notes, str) and notes.strip():
            indented = notes.strip().replace("\n", "\n      ")
            cat_lines.append(f"    notes: {indented}")
        if not cat_lines:
            cat_lines.append("    (nothing listed)")
        lines.append(f"  {cat}:")
        lines.extend(cat_lines)
    return "\n".join(lines)


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
