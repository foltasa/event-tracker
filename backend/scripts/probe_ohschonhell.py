"""Probe ohschonhell.de event-detail parsing quality.

Pulls the N most recently modified /date/... URLs from the current post
sitemap, extracts schema.org/Event microdata from each, and reports
per-field coverage plus description-length distribution. Read-only,
no DB writes.

Usage from backend/:
    python -m scripts.probe_ohschonhell [--limit 20]
"""
from __future__ import annotations

import argparse
import statistics
import sys
import xml.etree.ElementTree as ET

import httpx
from bs4 import BeautifulSoup, Tag

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_UA = "Mozilla/5.0 (compatible; EventTrackerProbe/1.0)"
_SITEMAP = "https://ohschonhell.de/post-sitemap26.xml"
_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _get(client: httpx.Client, url: str) -> str:
    r = client.get(url, headers={"User-Agent": _UA})
    r.raise_for_status()
    try:
        return r.content.decode("utf-8")
    except UnicodeDecodeError:
        return r.content.decode("windows-1252")


def _recent_urls(client: httpx.Client, limit: int) -> list[tuple[str, str]]:
    xml = _get(client, _SITEMAP)
    root = ET.fromstring(xml)
    entries: list[tuple[str, str]] = []
    for url in root.findall("sm:url", _NS):
        loc = url.findtext("sm:loc", "", _NS)
        lastmod = url.findtext("sm:lastmod", "", _NS)
        if "/date/" in loc:
            entries.append((loc, lastmod))
    entries.sort(key=lambda x: x[1], reverse=True)
    return entries[:limit]


def _direct_prop(scope: Tag, name: str) -> Tag | None:
    for el in scope.find_all(attrs={"itemprop": name}):
        nearest_scope = el.find_parent(attrs={"itemscope": True})
        if nearest_scope is scope:
            return el
    return None


def _val(el: Tag | None) -> str:
    if el is None:
        return ""
    if el.has_attr("content") and el["content"].strip():
        return el["content"].strip()
    return el.get_text(strip=True)


def _parse_event(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    event = soup.find(attrs={"itemtype": "http://schema.org/Event"})
    if not isinstance(event, Tag):
        return {}
    place = event.find(attrs={"itemtype": "http://schema.org/Place"})
    addr = event.find(attrs={"itemtype": "http://schema.org/PostalAddress"})

    start_el = _direct_prop(event, "startDate")
    return {
        "url": _val(_direct_prop(event, "url")),
        "name": _val(_direct_prop(event, "name")),
        "startDate_content": start_el["content"].strip() if start_el and start_el.has_attr("content") else "",
        "startDate_display": start_el.get_text(strip=True) if start_el else "",
        "description": _val(_direct_prop(event, "description")),
        "location_name": _val(_direct_prop(place, "name")) if isinstance(place, Tag) else "",
        "street": _val(_direct_prop(addr, "streetAddress")) if isinstance(addr, Tag) else "",
        "postalCode": _val(_direct_prop(addr, "postalCode")) if isinstance(addr, Tag) else "",
        "city": _val(_direct_prop(addr, "addressLocality")) if isinstance(addr, Tag) else "",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        urls = _recent_urls(client, args.limit)
        print(f"Fetched {len(urls)} recent /date/ URLs from sitemap.\n")
        parsed: list[dict] = []
        for loc, _lm in urls:
            try:
                html = _get(client, loc)
                p = _parse_event(html)
                p["_src"] = loc
                parsed.append(p)
            except Exception as e:
                print(f"  ! {loc}: {e}")

    print(f"=== parsed {len(parsed)} events ===\n")
    for p in parsed:
        date = p.get("startDate_content") or "?"
        loc_name = (p.get("location_name") or "?")[:22]
        name = (p.get("name") or "?")[:62]
        print(f"- {date:>10}  {loc_name:<22}  {name}")
        desc = p.get("description") or ""
        if desc:
            snippet = desc.replace("\n", " ")[:140]
            print(f"      desc({len(desc)}): {snippet}")
        else:
            print("      desc: <empty>")

    fields = ["name", "startDate_content", "description", "location_name",
              "street", "postalCode", "city"]
    n = len(parsed)
    print("\n--- coverage ---")
    for f in fields:
        filled = sum(1 for p in parsed if p.get(f))
        pct = filled * 100 // max(n, 1)
        print(f"  {f:<20} {filled}/{n} ({pct}%)")

    desc_lens = [len(p.get("description", "")) for p in parsed if p.get("description")]
    if desc_lens:
        print("\n--- description length (chars) ---")
        print(
            f"  n={len(desc_lens)}  min={min(desc_lens)}  "
            f"median={int(statistics.median(desc_lens))}  "
            f"mean={int(statistics.mean(desc_lens))}  max={max(desc_lens)}"
        )


if __name__ == "__main__":
    main()
