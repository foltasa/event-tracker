"""Probe Eventim's public search API for Hamburg events.

Endpoint (undocumented public): public-api.eventim.com/websearch/search/api/exploration/v1/products
Filter by city_names=Hamburg. Read-only, no DB writes.

Usage from backend/:
    python -m scripts.probe_eventim [--limit 20] [--category konzerte]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_API = "https://public-api.eventim.com/websearch/search/api/exploration/v1/products"

_HEADERS = {
    "User-Agent": _UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://www.eventim.de",
    "Referer": "https://www.eventim.de/city/hamburg-72/",
    "Sec-Ch-Ua": '"Chromium";v="126", "Not:A-Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def _search(client: httpx.Client, city: str, page: int, top: int, category: str | None) -> dict:
    params = {
        "city_names": city,
        "webId": "web__eventim-de",
        "language": "de",
        "page": page,
        "top": top,
        "sort": "DateAsc",
    }
    if category:
        params["categories"] = category
    r = client.get(_API, params=params, headers=_HEADERS)
    r.raise_for_status()
    return r.json()


def _flatten(obj) -> list[dict]:
    """Try to find the event/product list regardless of top-level shape."""
    if isinstance(obj, dict):
        for key in ("productGroups", "products", "results", "items", "data", "events"):
            v = obj.get(key)
            if isinstance(v, list) and v:
                return v
        # dive one level
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--category", default=None, help="e.g. Konzerte, Musik")
    ap.add_argument("--dump", action="store_true", help="print first raw item")
    args = ap.parse_args()

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        try:
            first = _search(client, "Hamburg", 1, args.limit, args.category)
        except httpx.HTTPStatusError as e:
            print(f"HTTP {e.response.status_code}: {e.response.text[:500]}")
            return

    if args.dump:
        print(json.dumps(first, indent=2, ensure_ascii=False)[:5000])
        print("...")
        return

    print("Top-level keys:", list(first.keys()) if isinstance(first, dict) else type(first).__name__)
    items = _flatten(first)
    print(f"Found list of {len(items)} items in top-level")

    # Look for totals
    for key in ("totalResults", "total", "totalCount", "totalHits", "count"):
        if isinstance(first, dict) and key in first:
            print(f"  {key} = {first[key]}")

    print("\n=== first 3 raw items ===")
    for it in items[:3]:
        print(json.dumps(it, indent=2, ensure_ascii=False)[:2000])
        print("---")

    # Field coverage on all fetched items
    if items:
        fields_of_interest = [
            "name", "title", "productName",
            "startDate", "date", "eventDate",
            "description", "shortDescription",
            "venueName", "venue", "location",
            "city", "cityName",
            "category", "categories",
        ]
        print("\n--- coverage (top-level fields) ---")
        for f in fields_of_interest:
            filled = sum(1 for it in items if isinstance(it, dict) and it.get(f))
            if filled:
                print(f"  {f:<18} {filled}/{len(items)}")

        descs = []
        for it in items:
            d = it.get("description") or it.get("shortDescription") or ""
            if isinstance(d, str) and d.strip():
                descs.append(d.strip())
        if descs:
            lens = [len(d) for d in descs]
            print(f"\n--- description length (chars, n={len(descs)}) ---")
            print(f"  min={min(lens)}  median={int(statistics.median(lens))}  "
                  f"mean={int(statistics.mean(lens))}  max={max(lens)}")
            print("\n--- sample descriptions ---")
            for d in descs[:3]:
                print(f"  ({len(d)}) {d[:200]}")


if __name__ == "__main__":
    main()
