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
- Scraper type: ical + rss
- Status: **integrated**
- Notes: Highest-value single source for Madison — local alt-weekly with broad community submissions. iCal feed (`/search/event/calendar-of-events/calendar.ics`) provides structured data including RRULE for recurring events; RSS feed (`/search/event/calendar-of-events/index.rss`) is paginated (~2 pages/day) and provides per-event deep-link URLs. Scraper fetches iCal as primary, paginates RSS to build a `(title, date) → url` map for the 30-day window (~60 requests/run), falls back to the calendar index URL for unmatched events. No per-event URL in the iCal itself. Each event's detail page (`div.mp_tag_cat_1`) carries an in-page taxonomy that the scraper extracts and maps to ours via `_CATEGORY_MAP`: `Music`, `Comedy` → `Open Mic & Comedy`, `Dancing` → `Dance`, `Theater & Dance` → `Theater & Stage`, `Food & Drink`/`Farmers' Markets` → `Food & Drink`, `Health & Fitness` → `Health & Wellness`, `Recreation` → `Sports & Recreation`, `Kids & Family` → `Family & Kids`, `Politics & Activism`/`Public Meetings` → `Civic & Politics`, `Fundraisers` → `Volunteer & Causes`. Ambiguous source tags (`Special Interests`, `Seniors`, `LGBT`, `Arts Notices`, `Movies`, `Isthmus Picks`) and music sub-genres (`Folk`, `Bluegrass`, `Americana`) are dropped so they fall through to the LLM tagging pass.

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
- Scraper type prospect: api
- Status: **investigating**
- Notes: Has a public API (token required). Strong long-tail coverage of meetups, classes, nightlife, food. Verify current API access tier and rate limits.

### Meetup
- URL: https://www.meetup.com/find/us--wi--madison/
- Scraper type prospect: api (uncertain)
- Status: **investigating**
- Notes: Best source for recurring social/professional/hobby groups. Public API access has been restricted in recent years; confirm whether GraphQL API is usable for our case.

### City of Madison
- URL: https://www.cityofmadison.com/events
- Scraper type prospect: html
- Status: **investigating**
- Notes: Official municipal events. Likely lower volume but high signal for civic/public events.

### Downtown Madison Inc.
- URL: https://visitdowntownmadison.com/events
- Scraper type prospect: html
- Status: **investigating**
- Notes: Downtown-specific aggregator.

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
- Scraper type prospect: api
- Status: **investigating**
- Notes: Concert aggregator with a public API. Good fallback for music coverage if direct venue scrapers miss anything.

---

## Music venues

Direct sources, generally worth their own scraper for completeness and richer data than aggregators provide.

### High Noon Saloon
- URL: https://high-noon.com/calendar/
- Scraper type: html
- Status: **integrated**
- Notes: Frank Productions / FPC Live property at 701 E. Washington Ave. WordPress site (custom post type `tm_event`, theme `fpc-main` from 45press.com). Calendar page renders ~60 upcoming shows in a single HTML response (~7-month forward window) as `article.event-card` elements with title, date ("May 7, 2026"), times ("Doors: 7:00 pm | Show: 8:00 pm" — Show preferred, Doors fallback), supporting acts, presented-by line, image, and `tm_classifications-*` taxonomy slugs as CSS classes. Single GET per scrape, no pagination (`/calendar/page/2/` returns the same page). robots.txt is fully open. Music genres map to `Music`; `arts-theatre` maps to `Theater & Stage`; `the-moth` / `use-your-noggin` / `nerd-nite` map to `Talks & Learning`. The source's `community-civic` slug is dropped — observed in practice as a catch-all (e.g. tagging student music showcases) rather than a clean civic-events category. WP REST API at `/wp-json/wp/v2/tm_event` was rejected: it exposes the post-publish timestamp under `date`, not the event date, and `acf` is empty.

### Majestic Theatre
- URL: https://majesticmadison.com/
- Scraper type: api (Ticketmaster Discovery API)
- Status: **integrated**
- Notes: Covered by the **Ticketmaster** aggregator scraper above (Discovery API venue ID `KovZpZAaltvA`, ~33 upcoming events at integration time). No standalone Majestic scraper needed. The Majestic's own site (majesticmadison.com) was not separately scraped — Ticketmaster is the authoritative ticket-sales URL, and `SOURCE_PRIORITY` already routes title links there for Majestic events.

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

### Concerts on the Square (Wisconsin Chamber Orchestra)
- URL: https://wcoconcerts.org/concerts-tickets/concerts-on-the-square
- Scraper type prospect: html
- Status: **investigating**
- Notes: Free outdoor summer series, six concerts. High public interest.

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
