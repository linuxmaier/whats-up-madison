# Event Sources

Catalog of known and prospective event sources for What's Up Madison. The goal is "what should I do in Madison today" — public-facing things-to-do (music, exhibitions, meetups, festivals, food, theater, community), not internal meetings or private gatherings.

**Update this file whenever sourcing changes** — when a scraper is added, retired, deferred, or when feasibility findings (iCal/API availability, signal quality, rate limits) are discovered during investigation.

## Status legend

- **integrated** — registered in `SCRAPERS` in `backend/app/main.py` and running
- **planned** — committed for the next batch of work
- **investigating** — on the radar; feasibility (feed format, signal quality, ToS) not yet confirmed
- **deferred** — known but consciously skipped, with reason
- **rejected** — evaluated and ruled out

When updating an entry, capture *why* the status changed (e.g. "deferred — feed is dominated by internal meetings") so future decisions don't re-litigate the same ground.

---

## Aggregators

These cover many venues and event types from a single source. Highest leverage if scrape-able cleanly.

### Isthmus
- URL: https://isthmus.com/all-events/calendar-of-events-index
- Sub-calendars: Music, Community, Arts & Entertainment, What-To-Do
- Scraper type: rss
- Status: **integrated**
- Notes: Highest-value single source for Madison — local alt-weekly with broad community submissions. Scraper paginates the RSS feed at `/search/event/calendar-of-events/index.rss?page=N` (30 items/page, ~50–60 pages for a 30-day window, ~30 s/run with a 0.5 s detail-fetch delay between events). Each `<item>` is one pre-expanded occurrence — recurring events emit one item per date, so no RRULE expansion is needed. The link/guid carries the local start datetime in `?occ_dtstart=YYYY-MM-DDTHH:MM`; the title carries human-readable start, optional end (`Event - May 18, 2026 11:30 AM - 4:30 PM @ Venue`), and venue. A title with no time is the all-day signal. The iCal feed (`/search/event/calendar-of-events/calendar.ics`) was the original primary path and was dropped in #231: empirical comparison showed iCal covered only ~14% of the events RSS exposes for the same window (217 vs 1523 in a 30-day window), and the iCal path was the source of #210 (zero-duration `end_at` when DTEND was missing) and #228 (stale rescheduled events whose iCal occurrences never refreshed title/start_at). Each event's detail page (`div.mp_tag_cat_1`) carries an in-page taxonomy that the scraper extracts and maps to ours via `_CATEGORY_MAP`: `Music`, `Comedy` → `Open Mic & Comedy`, `Dancing` → `Dance`, `Theater & Dance` → `Theater & Stage`, `Food & Drink`/`Farmers' Markets` → `Food & Drink`, `Health & Fitness` → `Health & Wellness`, `Recreation` → `Sports & Recreation`, `Kids & Family` → `Family & Kids`, `Politics & Activism`/`Public Meetings` → `Civic & Politics`, `Fundraisers` → `Volunteer & Causes`. Ambiguous source tags (`Special Interests`, `Seniors`, `LGBT`, `Arts Notices`, `Movies`, `Isthmus Picks`) and music sub-genres (`Folk`, `Bluegrass`, `Americana`) are dropped so they fall through to the LLM tagging pass.

### Visit Madison
- URL: https://www.visitmadison.com/events/
- Scraper type: api
- Status: **integrated**
- Notes: Official tourism CVB site, curated and lower-noise than Isthmus. Uses the Simpleview DMS events JSON API at `/includes/rest_v2/plugins_events_events_by_date/find/`. Public `apiToken` is hardcoded in the events page HTML and extracted on each run (with a hardcoded fallback in case extraction fails). Paginated at `limit=30` due to a 200 KB server-side response cap; ~460 events in a 30-day window means ~15-16 sequential requests per run, throttled at 0.5 s between pages. Maps Simpleview's category taxonomy to our taxonomy where unambiguous; ambiguous and non-content categories (Annual Events, Arts & Culture, Entertainment & Nightlife, Fairs & Festivals, Free Event, Holiday/Seasonal, Shopping, Virtual Event) are dropped and left for the LLM tagging pass.

### Ticketmaster
- URL: https://app.ticketmaster.com/discovery/v2/events.json
- Scraper type: api (Ticketmaster Discovery API)
- Status: **integrated**
- Notes: Multi-venue Madison aggregator. A single GET to `/discovery/v2/events.json?city=Madison&stateCode=WI&countryCode=US` (with `startDateTime`/`endDateTime` bounding a 30-day forward window) covers every Madison venue that sells tickets through Ticketmaster — The Sylvee, Majestic Theatre, Orpheum, Barrymore, Overture Center (and its sub-rooms), Kohl Center, Camp Randall, Breese Stevens, Roxxy, etc. Paginated `size=200` (~2 pages, ~250 events). Auth via `apikey=` query param (the `TICKETMASTER_API_KEY` setting); rate limit is 5 req/s and 5000/day so we sleep 0.25 s between pages. Events with `dates.status.code` in {`cancelled`, `postponed`} are dropped; `onsale`/`offsale`/`rescheduled` are kept. Time parsing uses `dates.start.{localDate,localTime}` + `dates.timezone`; missing `localTime` or `timeTBA=true` falls back to all-day. `spanMultipleDays=true` populates `end_at`. Description from `info` (preferred) or `pleaseNote`; both are plain text so no HTML cleaning needed. Classifications map conservatively: `Music/*` → `Music`; `Arts & Theatre / Comedy` → `Open Mic & Comedy`; `Arts & Theatre / Theatre|Children's Theatre|Performance Art|Dance` → `Theater & Stage`; `Sports/*` → `Sports & Recreation`; `Family/*` → `Family & Kids`. `Arts & Theatre / Miscellaneous` and `Undefined`/`Miscellaneous` segments are dropped so the LLM tagger handles them. The same event sometimes appears multiple times (e.g. distinct listings for affiliate sales channels like the UW Badgers store) — `canonical_hash` collapses these. Events that overlap with the dedicated High Noon Saloon scraper land on the same `Event` row via fuzzy dedup, with both `EventSource` rows kept; the High Noon URL wins for the title link via `SOURCE_PRIORITY`.

### Our Lives
- URL: https://ourliveswisconsin.com/events/
- Scraper type: api
- Status: **integrated**
- Notes: Wisconsin's LGBTQ community magazine and event hub. WordPress site running The Events Calendar (Tribe) plugin; uses the public REST endpoint `/wp-json/tribe/events/v1/events` (no auth). 30-day forward window, paginated `per_page=50` (~3 pages, ~120 events statewide). The feed covers all of Wisconsin, so the scraper applies a city allowlist filter to keep only Madison-metro events: Madison, Middleton, Verona, Sun Prairie, Waunakee, Fitchburg, Monona, McFarland, Stoughton. Venues with no `city` field (e.g. Overture Center) are accepted when the address contains "madison" or a 537xx ZIP. Tribe taxonomy maps conservatively to ours (`Music`, `Comedy`, `Dance`, `Theater`/`Performance Art`/`Drag` → `Theater & Stage`, `Workshop`/`Lecture`/`Reading` → `Talks & Learning`, `Activism` → `Civic & Politics`, `Fundraiser` → `Volunteer & Causes`, etc.); ambiguous tags (`Social`, `Festival`, `Pride`, `Party`), regional tags (`Madison + South Central`, etc.), and audience-targeting tags (`21+`, `All Ages`) are dropped so the LLM tagger handles them. Recurring events arrive as separate occurrences with date-stamped URLs (e.g. `/event/euchre-night/2026-05-08/`), so no RRULE expansion is needed. Polite 1s delay between pages.

### Eventbrite
- URL: https://www.eventbrite.com/d/wi--madison/events/
- Scraper type: api → none
- Status: **rejected**
- Reason: Eventbrite's public Event Search API (`GET /v3/events/search/`) was deprecated Dec 2019 and turned off Feb 20 2020. The remaining public endpoints require a known event/venue/organization ID; there is no supported "events in a city" query. HTML scraping of `/d/wi--madison/events/` is technically feasible (the listing page exposes ~112 JSON-LD `Event` entries on the first response) but is ToS-questionable and likely IP-fragile from Fly.io's range — same failure pattern that retired the Overture scraper (#162). Revisit only if either (a) Eventbrite reopens a public discovery API or (b) we gain a non-datacenter egress path (residential proxy, Cloudflare Worker fetch, etc.).

### Meetup
- URL: https://www.meetup.com/find/us--wi--madison/
- Scraper type: api → none
- Status: **rejected**
- Reason: Investigated for #70 in May 2026 and ruled out on machine-policy grounds. (1) Meetup's `robots.txt` explicitly disallows the GraphQL API at `https://www.meetup.com/gql*` for all user-agents — that's the only programmatic event surface, and the issue body's "GraphQL API" path is named directly in the disallow list. The legacy gateway at `api.meetup.com/gql` returns HTTP 404 (decommissioned). (2) `robots.txt` also disallows every URL parameter we'd need to filter events from the HTML surface: `?location=*`, `?categoryId=*`, `?dateRange=*`, `?eventType=*`, `?distance=*`, `?radius=*`, `?keywords=*`, plus `/n/*`, `/mu_api/`, and `/api/?`. `GPTBot` is fully disallowed in a separate stanza — broader stance against automated crawling. (3) The unparameterized city find page `/find/us--wi--madison/` itself is robots-allowed and returns 45 JSON-LD `Event` blocks with name/startDate/endDate/location.address/url, but is too thin to be useful as a scraper: no pagination (no `rel="next"`, no `?page=` anchors), no date or category control (those params are all disallowed), `description` is empty in JSON-LD so we'd need a second per-event fetch on a host that doesn't want bots. A sample run covered 2026-05-14 → 2026-06-06 — the "soonest 45" default sort with no way to widen the window. (4) Meetup's GraphQL docs (`meetup.com/api` → `/graphql/`) frame the API around "Business Solutions" for Meetup Pro customers, indicating it's gated behind the paid org subscription, not a per-app free developer key. Coverage gap is acceptable: **Isthmus** already surfaces many of Madison's recurring community/hobby events (Toastmasters, civic meetings, hobby clubs, social gatherings), and the LLM tagger handles `Community & Clubs` / `Health & Wellness` / `Talks & Learning` tagging for events from other sources. Revisit only if (a) Meetup reopens an unauthenticated city-search API, or (b) `robots.txt` relaxes `/gql*` and the event-filter params, or (c) we acquire a Meetup Pro / Partner credential whose ToS permits aggregation.

### City of Madison
- URL: https://www.cityofmadison.com/events
- Scraper type: html
- Status: **integrated**
- Notes: Integrated for #71 in May 2026. Official municipal events — high signal for parks programming, civic meetings, community events, and public gatherings that are underrepresented on entertainment-focused aggregators. Drupal 10 site; events are server-side rendered HTML (no JSON API or iCal feed available). Listing at `/events?page=N` returns 10 events/page, ordered chronologically; scraper paginates until the forward window is exhausted (default 30 days). The site WAF returns 403 for paginated (`?page=N`) requests without a browser-like User-Agent, so the scraper sends a descriptive browser UA. Each event's detail page (`/parks/…/events/…`, `/monona-terrace/events/…`, etc.) carries a rich description in `.field.body.text-with-summary`; the scraper enriches each event with a 1 s/page courtesy delay. Volume: ~100–120 events per 30-day run. No source-category mapping: city events span a wide civic taxonomy that doesn't map cleanly to our closed set — descriptions are rich and the LLM tagger handles category assignment. Ranked lowest in `SOURCE_PRIORITY` (after Visit Madison); if an event appears on both the city site and a higher-ranked aggregator, the aggregator's richer entertainment copy wins.

### Downtown Madison Inc. (DMI)
- URL: https://downtownmadison.org/wp-json/tribe/events/v1/events/?categories=dmi-events
- Public-facing calendar page: https://downtownmadison.org/calendar/category/dmi-events/
- Scraper type: api
- Status: **integrated**
- Notes: Investigated for #72 in May 2026. The URL named in the issue (`visitdowntownmadison.com/events`) is a hand-curated annual highlights list — a static page that DMI staff edit once per year with `<month>: <day> <link>` rows pointing mostly to partner sites. No event timestamps, descriptions, or venues, so not a viable structured source. The actual DMI calendar lives on the sister site `downtownmadison.org`, which runs The Events Calendar (Tribe) plugin and exposes the same JSON REST API shape used by the Our Lives scraper. The unfiltered feed includes ~20 internal DMI committee meetings (Board of Directors, Executive Committee, Transportation, Government Relations, Economic Development, Quality of Life, Beyond Compliance) that aren't public events — we filter to `?categories=dmi-events` to surface only the public-facing slate: What's Up Downtown breakfasts at The Edgewater, New Faces New Places networking, Behind The Scenes tours, the IDA Place Matters conference, the I.D.E.A. Series at Overture Center, the DMI Annual Celebration. Volume is low (~12 upcoming events) but signal is high and there's zero overlap with Isthmus / Visit Madison. 30-day forward window, paginated `per_page=50` (one page in practice), `?categories=dmi-events` filter. No source-category mapping: DMI's tags are program-specific (`whats-up-downtown`, `new-faces-new-places`, `the-i-d-e-a-series`) and don't map cleanly to our closed taxonomy — descriptions are rich multi-paragraph HTML, so the LLM tagger handles category assignment. Titles ship HTML entities raw (`What&#8217;s Up Downtown`), so the parser unescapes before constructing the canonical hash; descriptions flow through `clean_html_text()` which already handles entities. Polite 1s delay between pages.

### 608today (6AM City)
- URL: https://608today.6amcity.com/events
- Scraper type prospect: html
- Status: **investigating**
- Notes: Curated newsletter list. Useful as a quality cross-check; may overlap heavily with other aggregators.

### Madison.com / Channel 3000
- URLs: https://madison.com/events/, https://www.channel3000.com/madison-magazine/events/
- Scraper type prospect: html
- Status: **investigating**
- Notes: Local news event listings.

### Songkick
- URL: https://www.songkick.com/metro-areas/8265-us-madison
- Scraper type prospect: api
- Status: **investigating**
- Notes: Concert aggregator. API exists but has historically required partner access.

### Bandsintown
- URL: https://www.bandsintown.com/c/madison-wi
- Scraper type: api → none
- Status: **rejected**
- Reason: Investigated for #76 in May 2026 and ruled out on three independent grounds. (1) The public REST API at `rest.bandsintown.com` is **artist-centric only** — the documented event endpoint is `GET /v3.1/artists/{name}/events?app_id=...`, with no city/location discovery route. Probing `/v3.1/cities/madison-wi/events`, `/v4/...`, and the retired `api.bandsintown.com/v2/events.json?location=...` all return `MissingAuthenticationTokenException` (route does not exist on the public API gateway). City-wide aggregation would require us to maintain a manual artist allowlist, which defeats the point of a fallback aggregator. (2) `www.bandsintown.com/c/madison-wi` is fronted by **Cloudflare** and returns the "Sorry, you have been blocked" interstitial (HTTP 403, `cf-ray` set) from a non-datacenter residential IP — Fly.io's range will be blocked at least as aggressively (same failure pattern that retired Overture in #162 and Eventbrite in #182), so HTML scraping isn't a viable path either. (3) Bandsintown's location-aware **Partner API** exists but is B2B/approval-gated, pitched at venue/promoter partners rather than third-party aggregators, and would impose a different ToS than the public API. Coverage gap is acceptable: Madison's ticketed concert volume is already covered by the **Ticketmaster** (Sylvee, Majestic, Orpheum, Barrymore, Overture, Kohl Center), **High Noon Saloon**, and **Atwood Music Hall** scrapers, with DIY/independent shows surfaced via **Isthmus**. Revisit only if (a) Bandsintown reopens a public city-search API or (b) we gain a non-datacenter egress path (residential proxy, Cloudflare Worker fetch) *and* find a documented HTML or feed surface that carries city-keyed event data.

---

## Music venues

Direct sources, generally worth their own scraper for completeness and richer data than aggregators provide.

### High Noon Saloon
- URL: https://high-noon.com/calendar/
- Scraper type: html
- Status: **integrated**
- Notes: Frank Productions / FPC Live property at 701 E. Washington Ave. WordPress site (custom post type `tm_event`, theme `fpc-main` from 45press.com). Calendar page renders ~60 upcoming shows in a single HTML response (~7-month forward window) as `article.event-card` elements with title, date ("May 7, 2026"), times ("Doors: 7:00 pm | Show: 8:00 pm" — Show preferred, Doors fallback), supporting acts, presented-by line, image, and `tm_classifications-*` taxonomy slugs as CSS classes. Single GET per scrape, no pagination (`/calendar/page/2/` returns the same page). robots.txt is fully open. Music genres map to `Music`; `arts-theatre` maps to `Theater & Stage`; `the-moth` / `use-your-noggin` / `nerd-nite` map to `Talks & Learning`. The source's `community-civic` slug is dropped — observed in practice as a catch-all (e.g. tagging student music showcases) rather than a clean civic-events category. WP REST API at `/wp-json/wp/v2/tm_event` was rejected: it exposes the post-publish timestamp under `date`, not the event date, and `acf` is empty.

### Majestic Theatre
- URL: https://majesticmadison.com/calendar/
- Scraper type: html
- Status: **integrated**
- Notes: Frank Productions / FPC Live property at 115 King St. Same WordPress site / `fpc-main` theme as High Noon Saloon — custom post type `tm_event`, `article.event-card` markup, `tm_classifications-*` slugs as CSS classes, `.event-date` / `.event-times` ("Doors: 7:00 pm | Show: 8:00 pm" — Show preferred, Doors fallback) / `.event-presented-by` / `.event-supporting-acts` blocks. Single GET to `/calendar/` returns ~31 events spanning ~7 months; no pagination, no JS rendering. After parsing each card the scraper fetches the per-event detail page (`/event/<slug>/`) and reads the `section.event-section` whose `<h2>` heading is exactly **"Event Description"** — that section carries the show-specific copy, while a sibling `<Artist> Bio` section (when present) is dropped because long promotional bios clutter the card UI without adding event-specific signal (mirrors the codified High Noon exception in `.claude/skills/audit-event-accuracy/audit-exceptions.md`). Events with no `event-section` blocks fall back to the card-level `presented-by + supporting-acts` heading. Music genres (`jazz`, `dance-party`, `electro-pop`, `hyperpop`, `pop`, `rock`, etc.) map to `Music`; `comedy` maps to `Open Mic & Comedy`; `arts-theatre` maps to `Theater & Stage`. Ranked above Ticketmaster in `SOURCE_PRIORITY` because TM's `info`/`pleaseNote` for Madison shows is dominated by venue-policy boilerplate that strips to near-empty descriptions (the original audit issues #177 / #178 were instances of this class of gap), whereas the Majestic detail pages carry real show copy. Cross-source dedup with Ticketmaster rows already works via canonical-venue normalization (`backend/app/canonical_venues.py` entry for `majestic theatre`) plus the fuzzy title+time+venue match in `ingest.py`. robots.txt is fully open. Courtesy delay of 0.3 s between detail-page fetches (~10 s added to the scrape).

### The Sylvee (Frank Productions)
- URL: https://www.ticketmaster.com/the-sylvee-tickets-madison/venue/237554
- Scraper type: api (Ticketmaster Discovery API)
- Status: **integrated**
- Notes: Covered by the **Ticketmaster** aggregator scraper above (Discovery API venue ID `KovZ917AQBC`, ~30 upcoming events at integration time). The Sylvee shares Frank Productions ownership with High Noon Saloon, but unlike High Noon (which has its own calendar page) The Sylvee's only public events surface is Ticketmaster.

### Atwood Music Hall
- URL: https://www.theatwoodmusichall.com/shows
- Scraper type: html
- Status: **integrated**
- Notes: Squarespace **events collection** rendered server-side as well-structured HTML. Single GET to `/shows` returns ~70 events spanning ~9 months — past + upcoming on the same page. The scraper selects only `article.eventlist-event--upcoming` to avoid resurrecting events the staleness sweep has already deactivated. Per-event venue is extracted from `li.eventlist-meta-address`: at integration time the page also surfaced shows at sister venues **Barrymore Theatre** (2090 Atwood Ave) and **Liquid** (624 University Ave), so the scraper does not hardcode a venue name. Address is parsed from the embedded `maps.google.com?q=…` link and normalized (drop trailing `, United States`, collapse `Madison, WI, 53704` → `Madison, WI 53704`). `event-time-localized-start`/`-end` text gives wall-clock times that we localize to `America/Chicago`; cross-midnight shows are detected via end ≤ start and the end rolls to the next calendar day. Categories left empty and deferred to the LLM tagger — Atwood hosts music, comedy/improv, sing-along dance parties, etc., too varied to safely pre-tag from the venue alone (and many excerpts are short enough that the tagger will skip them, which is preferable to mis-tagging everything as Music). robots.txt allows the rendered `/shows` page; only `?format=ical`, `?format=json`, `/api/`, etc. are disallowed (the scraper doesn't touch those). Canonical venue entry added for `atwood music hall` so the geocoder short-circuits Nominatim and the displayed address stays consistent.

### Wisconsin Chamber Orchestra (Concerts on the Square + indoor series)
- URL: https://wcoconcerts.org/concerts-tickets/calendar
- Scraper type: html
- Status: **integrated**
- Notes: Investigated for #81 in May 2026. The marketing landing page `/concerts-tickets/concerts-on-the-square` is FAQ-only — no per-event data. The actual events live on the calendar page, which loads its cards via an AJAX endpoint at `GET /load/events?timespan=upcoming&limit=30`. That endpoint returns ~15 cards as server-rendered HTML (one `div.row.event` per concert) covering all upcoming WCO programming: the six free Concerts on the Square outdoor evenings on the Capitol Square (typically late-June through July, every Wednesday at 7 PM), plus indoor series (Side by Side at Hamel Music Center, Sound Explorers at Overture Center, Masterworks, Musical Landscapes in Color, Concerts & Cuisine). Each card carries title, subtitle, datetime block (single time or `<start> to <end>` range), venue text, image, and a link to the detail page. The detail page's JSON-LD `MusicEvent` carries only generic org-level boilerplate, so the scraper fetches the detail page and reads the **first** `.block.text` paragraphs inside `.section.content` — that's the show-specific copy. Subsequent `.block.text` siblings ("Table Reservations", "Plan Your Visit", "About <Artist>") are dropped as boilerplate / artist bios (same exception class codified for High Noon and Majestic in `.claude/skills/audit-event-accuracy/audit-exceptions.md`). Venues in `<room> — <building>` form (e.g. "Capitol Theater — Overture Center for the Arts", "Hamel Music Center — University of Wisconsin-Madison") are split on the em-dash to the room name only — for Overture sub-rooms, the existing canonical-venues registry then normalizes that to "Overture Center for the Arts" before dedup, so cross-source merging with Isthmus / Ticketmaster works. Canonical-venues entry added for `"king street corner of the capitol square"` mapping to the Wisconsin State Capitol coordinates (the COTS audience occupies the Capitol's south lawn). Events are pre-tagged `Music` — WCO publishes orchestral and crossover concert programs only, so the LLM tagger is skipped. robots.txt is permissive (only `/cpresources/`, `/vendor/`, `/.env`, `/cache/` are disallowed). 0.5 s courtesy delay between detail-page fetches. No forward-window parameter; the listing returns whatever is currently published. Ranked above Isthmus and Visit Madison in `SOURCE_PRIORITY` so the WCO detail-page link wins as the displayed title link when the same concert also appears in a community aggregator.

### Monona Terrace (Concerts on the Rooftop, Dane Dances)
- URL: https://www.mononaterrace.com/
- Scraper type prospect: html
- Status: **investigating**
- Notes: Summer-only outdoor series.

---

## Theater / arts / dance

### Overture Center for the Arts
- URL: https://www.overture.org/tickets-events/upcoming-events/
- Scraper type: html
- Status: **deferred**
- Reason: Imperva/Incapsula fronts the entire `*.overture.org` domain (including `tickets.overture.org`) and serves every request from Fly.io's IP range a JavaScript-iframe challenge page that can't be solved by `curl_cffi` regardless of TLS-fingerprint profile. Probed for an IP-friendly data path during issue #162 investigation: `sitemap.xml` and `robots.txt` are served, but every event-data endpoint we tried (`/tickets-events/upcoming-events/`, `/rss`, `/feed`, `/calendar`, `/api/*`, `?format=json`, all of `tickets.overture.org`) returns the same ~920-byte iframe block. The scraper worked from residential/home IPs (which aren't on Incapsula's flagged list) but never produced events from production. Removed in #162; canonical-venue entries for Overture and its seven sub-rooms remain in `canonical_venues.py` so Isthmus and Ticketmaster events at Overture still merge under the canonical building name and resolve to 201 State St. Revisit only if we either (a) gain access to a non-datacenter egress (residential proxy, Cloudflare Worker fetch, etc.) or (b) Overture publishes a non-Imperva-fronted feed.
- Historical implementation notes (kept for future revival): cards lived at `/tickets-events/upcoming-events/`, ~75 events over ~15 months, rendered server-side in one ~240KB response (no pagination, no XHR). Year was implicit on cards ("May 10" / "May 10 - May 17") and inferred by chronological-walk pass. Multi-day runs required a detail-page fetch to expand per-performance times. The first GET returned a 1KB Tessitura-handshake stub with a hidden form (`EncryptedPayload.Value` + `ReturnUrl`) that had to be POSTed to `/login/receive` to receive the real page on the second response. Source category mapping: `Music`/`Classical Music`/`Jazz` → `Music`; `Comedy` → `Open Mic & Comedy`; `Theater`/`Musical Theater`/`Broadway`/`Dance` → `Theater & Stage`; `Educational/Talks` → `Talks & Learning`; `Family Friendly` → `Family & Kids`. Scraper code preserved in git history (last live in commit `50ed6c7`).

---

## Museums / exhibitions

### Chazen Museum of Art
- URL: https://chazen.wisc.edu/exhibitions-and-events/
- Scraper type prospect: html
- Status: **investigating**
- Notes: UW-Madison museum, free admission. Note (as of 2026): galleries currently closed for de-installation, full reopening in fall — exhibitions calendar may be sparse until then.

### Madison Museum of Contemporary Art (MMoCA)
- URL: https://www.mmoca.org/
- Scraper type prospect: html
- Status: **investigating**
- Notes: Free admission. ~6,000 objects in permanent collection. Hosts Art Fair on the Square.

---

## Markets / festivals / food

### Dane County Farmers' Market
- URL: https://dcfm.org/
- Scraper type prospect: html (recurring)
- Status: **investigating**
- Notes: Largest producer-only farmers' market in the US. Saturday on the Square + Wednesday market. Recurring events — needs careful handling so it doesn't drown out other listings.

### Madison Eastside Farmers' Market
- URL: http://www.eastsidefarmersmarket.org/
- Scraper type prospect: html
- Status: **investigating**

### Taste of Madison
- URL: https://www.tasteofmadison.com/
- Scraper type prospect: html
- Status: **investigating**
- Notes: Annual Labor Day weekend festival. Single event per year — could be covered by aggregators rather than its own scraper.

### Other annual festivals (Art Fair on the Square, Madison Night Market, Mad Gluten Free Fest, Thirsty Troll Brew Fest, Madison Jazz Festival)
- Status: **investigating**
- Notes: Likely covered by Visit Madison or Isthmus once those are integrated. Revisit only if coverage gaps appear.

---

## Deferred

### UW-Madison `today.wisc.edu` iCal feed
- URL: https://today.wisc.edu/
- Scraper type prospect: ical
- Status: **deferred**
- Reason: Low-interest events. The feed is dominated by internal university meetings, academic talks, and departmental gatherings — not the public-interest things-to-do this calendar is meant to surface. Scraper code was written but never registered in `SCRAPERS`. Revisit only if a better-filtered feed or category-restricted endpoint becomes available.

---

## Geocoding

Event coordinates power the map view. The pipeline runs after each scraper inside `POST /admin/scrape` and is also exposed as `POST /admin/geocode` for backfill (`force=true` clears non-success cache rows and retries).

### Nominatim (OpenStreetMap)
- URL: https://nominatim.openstreetmap.org/search
- Used by: `backend/app/geocoding.py`
- Status: **integrated**
- Notes: Free, open-source geocoder. ToS requires (a) max 1 request/second (enforced via module-level lock in `geocoding.py`), (b) a real `User-Agent` containing contact info (`whats-up-madison/0.1 (andrew.eric.maier@gmail.com)`), and (c) attribution on rendered tiles (handled by Leaflet's default attribution control). Address-form lookups are biased to a Madison bounding box; venue-name-only lookups (mostly Isthmus events with no street address) use structured `city=Madison&state=Wisconsin` params. Results are cached in the `venue_geocodes` table by a normalized lookup key, so re-scrapes cost ~0 network calls. Failed lookups (`status=not_found|error`) are also cached to avoid retry loops.

### Tile provider — OpenStreetMap
- URL: https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
- Used by: `frontend/src/components/MapView.jsx`
- Status: **integrated**
- Notes: Free public OSM tile servers used by the Leaflet map. Attribution is included in the `TileLayer` config per OSM's tile usage policy. If usage grows beyond hobby scale, switch to a hosted provider (MapTiler / Stadia / Mapbox).

---

## Category Taxonomy

Events are tagged with zero or more categories from a closed vocabulary. The canonical list lives in `backend/app/categories.py` — that module is the source of truth referenced by the LLM tagging pass (Step 4). When the taxonomy changes, update both files together.

Multi-tagging is allowed (e.g. a UW author event may be both **Visual Art** and **Talks & Learning**; a family concert is both **Music** and **Family & Kids**).

- **Music** — concerts, jams, DJ sets, songwriter circles (excludes open mics)
- **Open Mic & Comedy** — open mics (any genre), stand-up, improv
- **Theater & Stage** — plays, staged readings, performance art, dance performances meant to be watched
- **Visual Art** — gallery exhibits, museum events, artist talks, studio tours
- **Dance** — social/participatory dance: salsa, tango, contra, swing, ballroom, folk practices
- **Trivia & Games** — pub trivia, bingo, board games, Lego nights
- **Food & Drink** — farmers' markets, food festivals, tastings, brewery/restaurant events
- **Health & Wellness** — yoga, meditation, group fitness, group walks
- **Outdoors & Nature** — birding, hikes, conservation work, park events, gardening
- **Tours & Sightseeing** — guided tours and sightseeing: architectural and historic-site tours, museum and gallery tours, brewery and food tours, ghost/history walks, trolley/bus tours (excludes hikes and exercise walks)
- **Sports & Recreation** — pickup games, recreational leagues, races, fitness meetups, sports-watch parties, organized athletic events
- **Talks & Learning** — lectures, panels, classes, workshops, book clubs, author readings
- **Civic & Politics** — government meetings, town halls, candidate forums, advocacy
- **Family & Kids** — story hours, kid-targeted programming
- **Community & Clubs** — hobby clubs, social meetups, identity-based gatherings, networking, Toastmasters
- **Volunteer & Causes** — volunteer work days, blood drives, fundraisers, charity
