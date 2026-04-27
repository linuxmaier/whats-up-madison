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
- Notes: Highest-value single source for Madison — local alt-weekly with broad community submissions. iCal feed (`/search/event/calendar-of-events/calendar.ics`) provides structured data including RRULE for recurring events; RSS feed (`/search/event/calendar-of-events/index.rss`) is paginated (~2 pages/day) and provides per-event deep-link URLs. Scraper fetches iCal as primary, paginates RSS to build a `(title, date) → url` map for the 30-day window (~60 requests/run), falls back to the calendar index URL for unmatched events. No per-event URL in the iCal itself.

### Visit Madison
- URL: https://www.visitmadison.com/events/
- Scraper type prospect: html or unknown feed
- Status: **investigating**
- Notes: Official tourism CVB site. Curated, lower noise than Isthmus. Check for iCal/RSS export.

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
- Scraper type prospect: html
- Status: **investigating**

### Majestic Theatre
- URL: https://majesticmadison.com/
- Scraper type prospect: html
- Status: **investigating**

### The Sylvee (Frank Productions)
- URL: https://www.ticketmaster.com/the-sylvee-tickets-madison/venue/237554
- Scraper type prospect: api (Ticketmaster Discovery API)
- Status: **investigating**
- Notes: Tickets sold via Ticketmaster — could pull this and other Ticketmaster venues at once.

### Atwood Music Hall
- URL: https://www.theatwoodmusichall.com/shows
- Scraper type prospect: html
- Status: **investigating**

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
- Scraper type prospect: html
- Status: **investigating**
- Notes: Seven venues, ~200 performances/year. Houses 10 resident companies (Madison Symphony, Madison Opera, Madison Ballet, Forward Theater, etc.) — scraping Overture should cover most of those companies' events, avoiding the need for individual scrapers.

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
- **Talks & Learning** — lectures, panels, classes, workshops, book clubs, author readings
- **Civic & Politics** — government meetings, town halls, candidate forums, advocacy
- **Family & Kids** — story hours, kid-targeted programming
- **Community & Clubs** — hobby clubs, social meetups, identity-based gatherings, networking, Toastmasters
- **Volunteer & Causes** — volunteer work days, blood drives, fundraisers, charity
