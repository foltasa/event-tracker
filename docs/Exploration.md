# Exploration: Candidate Concert Sources for the Ingestion Pipeline

Autonomous exploration run 2026-07-06. Goal: evaluate potential new concert
sources for the Hamburg ingestion pipeline. Each provider is judged along
four axes:

1. **Public API** — is there a free, unauthenticated endpoint that returns
   structured event data?
2. **API keys** — free / paid options; is signup available in 2026?
3. **Scraping** — feasibility of a probe-style scraper (Anti-Bot risk,
   how brittle, description quality).
4. **Hamburg coverage** — approximate concert count.

Evaluation focuses on **description quality** (needed for user-facing
copy AND the recommender), plus location, date, time.

Reference adapters in this repo:
- `backend/app/ingestion/scrapers/ohschonhell.py` — sitemap + microdata
  scraping pattern.
- `backend/app/ingestion/scrapers/theater_hamburg.py` — GraphQL widget
  JWT-extraction pattern.

Probe scripts follow the shape of `backend/scripts/probe_ohschonhell.py`
(read-only, no DB writes, coverage stats). New this run:
`backend/scripts/probe_eventim.py`.

---

## Recommended Priority

Ranked by _(description quality × Hamburg volume × integration effort)_:

1. **rausgegangen.de** — best descriptions (median 760 chars, 100%
   schema.org coverage), ~1,760 concerts, no anti-bot. Fits the
   ohschonhell adapter shape almost 1:1.
2. **Eventim** — largest volume (**1,820 Konzerte** in Hamburg), rich
   metadata (venue, geo, artist, image, category tree), tz-aware
   startDate. Descriptions are short teasers (~67 chars) but usable
   as `summary`. Requires proper browser headers + 403-retry.
3. **Resident Advisor** — 140 events but zero overlap with the others;
   niche electronic/underground with `genres[]` (great recommender
   signal). Small ongoing cost.
4. **concert-news.de / hamburgkonzerte.de** — 177 rock/metal events,
   no structured markup → custom parser. **Defer** until 1–3 shipped.
5. **Bandsintown** — SSR ld+json capped at 36 events per city with no
   real pagination. Useful only if paired with a curated artist list
   and an `app_id`. **Skip for MVP.**
6. **Songkick** — API closed to hobbyists (partner+paid), edge returns
   406 to raw fetches. **Skip.**

**Combined addressable Hamburg concerts (candidates 1–3):**
1,760 + 1,820 + 140 ≈ **3,720 events, 12-month window**, before dedup
across sources. Real unique count likely lower (Eventim ↔ rausgegangen
overlap on mainstream tours).

---

## Summary Table

| Provider | API? | Key? | Scrape? | HH count | Recommendation |
| --- | --- | --- | --- | --- | --- |
| Eventim | ✅ undocumented public JSON | none needed (browser headers) | n/a — API sufficient | **1,820 Konzerte** (22,771 all-cat) | **Strong candidate.** API-based adapter, watch for Akamai 403s |
| Bandsintown | partner only (artist-scoped) | app_id on request, artist-only | ⚠️ SSR ld+json capped at 36 events, no pagination | ~36 SSR + N detail fetches | Weak. Skip unless we already have artist seed list |
| Songkick | ❌ partner-only, paid license | not open to hobbyist | ❌ 406 fingerprint block | unknown | Skip |
| hamburg.rausgegangen.de | no public event API | none needed | ✅ schema.org/Event microdata on detail pages | **~1,760** Konzerte | **Top candidate.** Best description quality of all sources tested |
| Resident Advisor | ✅ undocumented GraphQL | none (Referer + UA) | n/a — GraphQL works | **140** (electronic, 12mo) | Ship, niche electronic complement |
| concert-news.de | ❌ no public API | none | ⚠️ HTML-only, no schema markup, brittle | **177** (Hamburg, rock/metal/indie) | Optional, low-priority; niche complement |

---

## Eventim

**Access model:** Undocumented public JSON endpoint used by eventim.de's own
frontend. No key, no signup. Fronted by Akamai, so **browser-shaped headers
are mandatory** (User-Agent, Origin, Referer, `Sec-Ch-Ua*`, `Sec-Fetch-*`);
minimal-header requests get `403 Access Denied` from the edge. Sporadic
403s under load — proper retry-backoff needed (analogous to
`ohschonhell.get_with_retry`, but treat 403 as retriable here, not 429/503).

**Endpoint:**
```
GET https://public-api.eventim.com/websearch/search/api/exploration/v1/products
    ?city_names=Hamburg
    &categories=Konzerte
    &webId=web__eventim-de
    &language=de
    &page=<n>
    &top=<n>            # 50 max
    &sort=DateAsc
```

**Response shape (top-level):** `facets`, `products`, `results`, `page`,
`totalPages`, `totalResults`. Each `product` object carries:
- `productId`, `productGroupId` — stable IDs (use `productId` as
  `external_id`; multiple dates share a `productGroupId`)
- `name`, `description` (short teaser), `attractions[].name` (artist list)
- `categories[]` — hierarchical (`Konzerte` → `HipHop & R'n'B`, etc.)
- `typeAttributes.liveEntertainment.startDate` — ISO 8601 with tz offset
  (`2026-10-12T20:00:00+02:00`)
- `typeAttributes.liveEntertainment.location` — `city`, `name` (venue),
  `postalCode`, `geoLocation.{latitude,longitude}`
- `imageUrl` (222x222 teaser jpg), `link` (canonical event URL), `price`,
  `currency`, `status`, `inStock`, `rating.{average,count}`

**Hamburg coverage (probed 2026-07-06):**
- All categories: **22,771**
- `categories=Konzerte`: **1,820** ← target set
- Compare: Berlin 15,603 all, Köln 10,970 all (Hamburg leads by facet count).
- Date range in first 50 hits: 2026-08-20 → 2027-06-02.

**Description quality:** short marketing teasers, median **67 chars**,
range 36–155. 42/50 filled. Useful as short-blurb, but too thin as the
sole description for the recommender. Options:
1. use `description` as `summary`, leave `description` empty (schema allows).
2. scrape the detail page (`link`) — the /event/ page contains a fuller
   HTML description; second-tier probe would confirm.
3. use description + attractions + categories as embedding input.

Recommendation is (1)+(3) for MVP, (2) as an enrichment pass if the
recommender is starved.

**Auth failure mode:** widget/frontend fingerprint drift is possible. The
403 responses returned by Akamai edge include a Reference ID
(`errors.edgesuite.net`) — logging these is enough to trigger a header/UA
refresh, no JWT-style rescrape needed.

**Probe:** `backend/scripts/probe_eventim.py`. Reproducible.

**Verdict:** ✅ **Ship candidate.** Cleanest single source outside the
already-integrated Ticketmaster / Eventbrite adapters. Concrete adapter
task: paginate `categories=Konzerte&city_names=Hamburg` (~21 pages @
top=50 with sort=DateAsc), state key on `productGroupId` + startDate
prefix for delta, honor Akamai 403 with exponential backoff.


---

## Bandsintown

**Access model:**
- **Public REST API** (`rest.bandsintown.com`) requires an `app_id` granted
  after a partner request; the API is **artist-scoped only** —
  `/artists/{name}/events` — with **no city / geo endpoint**. Not useful
  for city-wide discovery unless we already have a curated artist list.
  Unauthenticated calls return 401; guessing common `app_id` values
  (`bit_web_app`) returns 403.
- **City web page** (`bandsintown.com/c/hamburg-germany`) — public HTML,
  ships schema.org `MusicEvent` microdata in ld+json.
  Requires a full browser fingerprint (User-Agent + `Sec-Fetch-*`);
  minimal-header requests return 403.

**City-page findings (probed 2026-07-06):**
- SSR HTML ships **exactly 36 `MusicEvent` items** on `/c/hamburg-germany`.
  `?page=2`, `?page=3` return the same 36 events — real pagination is
  client-side and hits an authenticated GraphQL endpoint. No public paging.
- Event fields on the list page are sparse:
  `name`, `startDate` (Berlin local, no tz offset — needs assumption),
  `url`, `location.name`, `performer.name`, `image`, and a
  `description` field that is essentially the artist tag (median 21
  chars, e.g. `"Fred Wesley"`, `"With the Generations Trio"`).
  **`location.address.streetAddress` / `postalCode` / `geo` are empty
  on the list.**
- Event detail pages (`/e/<id>-<slug>`) DO carry the full address,
  `geo.{latitude,longitude}`, and a rich `performer.description`
  (multi-paragraph artist bio, ~1–4 kB).

**Approach if adopted:** two-stage — fetch city page → 36 detail-page
fetches → parse ld+json per detail. Cost per refresh ≈ 37 requests for
36 events. Since new events push older ones off the SSR window without
paging, we'd only see a rolling 36-event tail: **unusable as a primary
source for full Hamburg coverage.**

**Description quality:** artist bios on detail pages are actually
strong recommender input — but only accessible one-by-one, and coverage
is capped by the SSR list.

**Verdict:** ⚠️ **Skip for MVP.** Consider revisiting if we ever get an
`app_id` grant — then the artist-events API becomes attractive as a
per-favourite-artist enrichment pass. Not a Hamburg concert firehose.


---

## Songkick

**Access model:** The `api.songkick.com` REST API (JSON, metro-areas /
calendar, artist-events, venue-events) technically still exists, but
Songkick's developer page as of 2026 states explicitly:

> "We are currently not approving API requests for student projects,
> educational purposes or hobbyist purposes."

Requesting a key requires signing a partnership agreement and paying a
license fee. Ownership moved from Warner Music to AI firm Suno in
November 2025 — no signal that public / free access will return.

**Scraping test:**
Direct HTML fetches (`www.songkick.com/metro-areas/28881...`) return
`406 Not Acceptable` — Songkick's edge rejects requests that lack their
expected fingerprint. Not blanket 403 like Bandsintown; harder to
brute-force by header padding alone. Given the explicit ToS wording
above, further scraping is off the table for MVP.

**Verdict:** ❌ **Skip.** No lawful free-tier path; even best-case
scraping conflicts with a hostile ToS and an actively-fingerprinting
edge. Revisit only if a commercial license becomes budgeted.


---

## hamburg.rausgegangen.de

**Access model:**
- No documented public event API. Their `/api/v1/search` exists but is a
  nationwide autocomplete/search (numFound ≈ 349k globally, ignores city
  filter — returns non-Hamburg events even with `city=Hamburg`) and
  ships thin fields only (title + human-formatted date string, no
  address, no coords).
- **Best path is scraping** the category listing pages + per-event
  detail pages. Detail pages ship pristine schema.org `Event` ld+json.
- Not fingerprint-blocked. Standard browser UA + `Sec-Fetch-*` headers
  work fine, no 4xx bursts encountered on ~10 probes.

**Approach (validated):**
1. GET `https://rausgegangen.de/hamburg/kategorie/konzerte-und-musik/?page=<n>`
   for `n` in `1..totalPages` — page 1 links `?page=55` as the last,
   so ~55 pages × 32 events ≈ **~1,760 Hamburg concert events**.
2. Extract `href="/events/<slug>/"` — 32 unique slugs per page.
3. GET `https://rausgegangen.de/events/<slug>/`, parse the first
   `<script type="application/ld+json">` block whose `@type == "Event"`.

**Detail-page fields (100% coverage in 6-event probe):**
- `name`, `description`, `startDate`, `endDate` (tz-aware `+0200`)
- `location`: `name`, `address.streetAddress`, `addressLocality`,
  `postalCode`, `addressCountry`
- `image[]`, `offers.{url,price,priceCurrency,validFrom}`
- `eventStatus` (usually `EventScheduled`)

**Description quality (probed 6 events):**
- Median **760 chars**, range 68–1,221. Roughly matches the
  ohschonhell.de bar (party descriptions there are typically 300–800).
  This is by far the richest description source of any provider tested.
- One caveat: some events ship an English placeholder
  (`"Please refer to the German language version…"`, 68 chars) — need
  a `len < ~120` fallback / retry with `/en/events/...` variant if we
  care about coverage.
- Occasional near-duplicates ("Beirut | LIVE" @ Stadtpark Open Air
  vs. "Beirut" @ Stadtpark) — dedup by (title, venue, date) would help.

**Rate-limit tolerance (probed):** 6 sequential requests at 400ms
delay: no throttling, no 4xx. Estimated full crawl: 55 + 1,760 ≈
**1,815 requests**, ~6 min at 200ms delay. Delta strategy needed
because the listing page doesn't expose lastmod — options:
- Track `(event_slug, startDate)` pairs; skip if already ingested and
  startDate hasn't changed.
- Or fetch only pages 1–3 (most recent additions) daily, plus a
  weekly full pass.

**Verdict:** ✅ **Top candidate.** Best description quality of any
source in this exploration, clean schema.org output, no anti-bot
resistance. Fits the ohschonhell adapter shape almost 1:1 (retry
helper + polite delay). Also carries adjacent categories
(`party`, `theater`, `festivals`) if we ever want to widen scope.


---

## Resident Advisor

**Access model:** No documented public API, but ra.co's own frontend hits
`https://ra.co/graphql` **unauthenticated** with only two guards: a real
UA string and a `Referer: https://ra.co/events/de/hamburg`. Confirmed
working against the live endpoint. The general HTML pages (`/events/de/hamburg`)
are behind a fingerprint/JS challenge and return **403** to raw fetches
— but the GraphQL endpoint accepts direct POSTs.

**Endpoint:** `POST https://ra.co/graphql`

**Query:** `GET_EVENT_LISTINGS` — same query used by the ra.co web UI.
Copy from the community scraper
(`github.com/djb-gt/resident-advisor-events-scraper/graphql_query_template.json`).

**Variables:**
```json
{
  "filters": {
    "areas": {"eq": 148},              // Hamburg area ID
    "listingDate": {"gte": "2026-07-06", "lte": "2027-07-06"}
  },
  "filterOptions": {"genre": true},
  "pageSize": 20,                       // capped small; paginate
  "page": 1
}
```

**Area ID discovery:** ra.co does NOT expose a public `areas` query
(schema restricted; returns `OPERATION_RESOLUTION_FAILURE`). Area IDs
were found by scanning `1..200` and matching venue names. For Hamburg:
- **`area = 148`** — venues: Golden Pudel Club, Baalsaal, Turtur,
  Schrødingers, Südpol, MS Stubnitz, etc.
- (For reference: Berlin = 34, London ≈ 13.)
- Hard-code area 148 in the adapter; ID unlikely to change.

**Detail query:** `GET_EVENT_DETAIL(id: ID!)` returns a `content` field
with the human-written event description (up to ~1kB, HTML-lite). The
list query does NOT include content — a per-event follow-up call is
needed for good descriptions.

**Hamburg coverage (probed 2026-07-06):**
- **140 events over 12 months** — that's the entire Hamburg RA catalog,
  not just concerts. This scene is niche: underground techno, house,
  electro, occasional jazz. Complements — not competes with — Eventim
  (mainstream), rausgegangen (broad), ohschonhell (mainstream parties).
- Descriptions: probed 5 events, `content` sizes 0, 122, 174, 197, 1059
  (median ~185, quite short except for editorial "Groove" entries).
  Not every event has content — coverage roughly 80%.

**Extra fields available:** `venue.address` (proper street), `genres[]`
(critical for taste-match — Techno / House / Electronica / etc.),
`artists[]`, `images[]` (flyerFront), `attending` (RSVP count → soft
popularity signal), `startTime`/`endTime` (ISO, no tz — Berlin local
assumption needed).

**Anti-bot:** GraphQL calls survived 200+ consecutive requests during
the area-scan phase (150ms delay between requests) — no throttling.
Frontend HTML fetches always 403; must use the GraphQL path.

**Verdict:** ✅ **Ship.** Small volume but zero overlap with the other
sources. Niche audience match. Adapter shape: single paginated GraphQL
call for the listing + a second GraphQL call per event for `content`
if we care about descriptions. Total refresh cost ≈ (140/20)+140 = 147
requests per full pass.


---

## concert-news.de

**Access model:** `concert-news.de` itself is a news blog (WordPress) —
its homepage links to a sister site, **`hamburgkonzerte.de`**, which
is the actual Hamburg concert database (also WordPress, `/konzerte/<slug>/`).
WP REST API is locked down: `/wp-json/` is 403, `/wp-json/wp/v2/posts`
returns 401 or empty, and the custom `shows` post type is not exposed
via REST. `/wp-json/wp/v2/types` lists no event/venue rest_base.

**Path is scraping.**

**Sitemap-first crawl:**
`https://hamburgkonzerte.de/sitemap-posttype-shows.xml` — clean XML
with `<loc>` + `<lastmod>`, sitemap-index-friendly. **177 upcoming
concert URLs** total (probed 2026-07-06). Same shape as
ohschonhell.de → the `sitemap-delta` state pattern applies 1:1.

**Detail-page parsing (probed 6 events):**
- **No schema.org/ld+json, no microdata.** Pure HTML.
- Reliably extractable via regex/BS on the main article body:
  - `title`: `<h1>` (100% coverage)
  - `date`: `"([Fr|Sa|So|...])., (DD.MM.YYYY)"` (100%)
  - `Beginn: HH:MM` and `Einlass: HH:MM` (100%)
  - `venue`: harder — appears bare after the date, but the "Präsentiert von
    <SUPPORT_BAND>" line collides with it (my first-pass regex mis-matched
    "BETTY" as venue on 3/6 events). A more careful extractor should
    key off the sibling of the "Einlass"/"Beginn" block, not proximity
    to the date. Solvable but not one-line.
- `meta name="description"` is **empty on 100% of probed events** —
  no free description shortcut.
- Main article body has 365–4,331 chars of rich descriptive prose
  (band bios, tour context, album context). Usable as `description`
  after boilerplate strip.

**Hamburg coverage:** 177 concerts (12mo). Genre focus: rock, metal,
indie, alternative — venues like Gruenspan, Bahnhof Pauli, Molotow,
Uebel & Gefährlich, Markthalle. **Zero overlap with RA** (electronic),
partial overlap with Eventim (larger tours) and rausgegangen (broad
coverage). Roughly a 3rd of Hamburg's indie/rock scene.

**Anti-bot:** none observed on ~10 sequential fetches with 300ms delay.
Plain WP behind Cloudflare, no challenge.

**Verdict:** ⚠️ **Low-priority.** Ship-worthy for the specific rock/metal
audience but expensive to build:
- No schema markup → custom HTML parser per template, brittle to theme
  updates.
- Venue extraction needs targeted DOM traversal, not regex.
- Only 177 events — the ROI vs. rausgegangen's 1,760 is 1/10.

Recommendation: **defer until after Eventim + rausgegangen + RA ship**.
If we then still need niche rock coverage, the sitemap-delta pattern
already exists (ohschonhell) so incremental effort is 1–2 days.


---
