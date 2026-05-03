# What's Up Madison

A self-populating events calendar for Madison, WI. Automatically aggregates events from local venues, publications, and calendars — no manual entry required. Browse by date as a time-bucketed list or as a map of where things are happening, and click through to the original source.

## Architecture

- **Backend:** Python / FastAPI + PostgreSQL (SQLAlchemy ORM)
- **Frontend:** React / Vite + Tailwind CSS — date picker + List/Map toggle (Leaflet + OpenStreetMap tiles)
- **Scrapers:** per-source plugins (API, iCal, HTML) run on a daily schedule
- **Geocoding:** Nominatim (free, OpenStreetMap), cached per venue so re-scrapes cost ~0 network calls
- **Local dev:** Docker Compose

## Getting Started

### Prerequisites

- Docker + Docker Compose
- [miniconda](https://docs.conda.io/en/latest/miniconda.html) (for local Python tooling)
- Node.js + npm (for frontend)

### 1. Create the conda environment

```
~/miniconda3/bin/conda create -n whats-up-madison python=3.12
~/miniconda3/envs/whats-up-madison/bin/pip install -r backend/requirements.txt
```

### 2. Configure environment variables

```
cp backend/.env.example backend/.env
```

Edit `backend/.env` as needed (defaults work with Docker Compose).

`CORS_ORIGINS` is a comma-separated string — do not use JSON array format:
```
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### 3. Start the stack

```
docker compose up
```

- API: http://localhost:8000
- API docs: http://localhost:8000/docs

### 4. Start the frontend (dev)

```
cd frontend
npm install
npm run dev
```

- Frontend: http://localhost:5173

### 5. Seed initial events

```
curl -X POST http://localhost:8000/admin/scrape -H "X-Admin-Key: <your-key>"
```

This runs all registered scrapers, geocodes any new venues, and (if `ANTHROPIC_API_KEY` is set) runs the LLM tagger on events without categories. Daily automation is not yet wired up in-process — run this from cron, a systemd timer, or any external scheduler. In development without `ADMIN_API_KEY` set the header is not required.

## Project Structure

```
whats-up-madison/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app entry point + /admin/scrape, /admin/tag, /admin/geocode
│   │   ├── config.py           # pydantic-settings; reads backend/.env
│   │   ├── database.py         # SQLAlchemy engine + session factory
│   │   ├── models.py           # SQLAlchemy models (Event, EventSource, Source, VenueGeocode)
│   │   ├── schemas.py          # Pydantic response schemas
│   │   ├── ingest.py           # Shared scraper ingestion utility (dedup, fuzzy match, multi-source)
│   │   ├── geocoding.py        # Nominatim wrapper (throttle, User-Agent, Madison bbox, cache)
│   │   ├── geocode_runner.py   # Per-source and backfill geocoding passes
│   │   ├── categories.py       # Closed category taxonomy + descriptions
│   │   ├── tagger.py           # LLM-assisted category tagging (Anthropic SDK, prompt-cached)
│   │   ├── routers/
│   │   │   └── events.py       # GET /events?date=YYYY-MM-DD
│   │   └── scrapers/
│   │       ├── base.py         # RawEvent dataclass + BaseSource interface
│   │       ├── isthmus.py      # Isthmus iCal + RSS
│   │       ├── visit_madison.py # Visit Madison Simpleview API
│   │       └── ...             # one module per source
│   ├── eval_tagger.py          # CLI for comparing tagger model cost / quality
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                   # React / Vite + Tailwind CSS
│   └── src/
│       ├── App.jsx             # date picker, filters, List/Map toggle
│       ├── components/
│       │   ├── DatePicker.jsx
│       │   ├── DensityRail.jsx     # sticky hourly-density bar with jump-to-hour
│       │   ├── BucketSection.jsx   # morning/afternoon/evening/night sections
│       │   ├── CategoryFilter.jsx
│       │   ├── VenueFilter.jsx
│       │   ├── EventCard.jsx
│       │   ├── AllDayStrip.jsx
│       │   ├── EventModal.jsx  # shared expanded-detail modal (used by both card types and MapView)
│       │   └── MapView.jsx     # Leaflet map of events with clustered + multi-event pins
│       └── lib/
│           ├── categories.js   # frontend mirror of taxonomy + filter persistence
│           ├── sources.js      # source priority ranking
│           ├── eventTime.js    # time formatting + bucketing
│           └── calendarUtils.js # iCal generation, Google Calendar URLs, share helpers
├── docker-compose.yml
└── local_management/           # gitignored — machine-local notes and commands
```

## Roadmap

- **Step 1 — Skeleton** ✅ Repo structure, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class
- **Step 2 — First scraper + frontend** ✅ Multi-source data model (`Event`/`EventSource`), ingestion utility, React/Vite/Tailwind frontend with date picker and event cards
- **Step 3 — More scrapers** 🔄 Isthmus integrated (iCal + RSS, 30-day window) and Visit Madison integrated (Simpleview JSON API, 30-day window, with category pre-tagging from the source's own taxonomy); Eventbrite API, City of Madison, and individual venue HTML scrapers still planned. Daily automation runs out-of-process for now (cron / systemd timer hitting `/admin/scrape`); no in-process scheduler.
- **Step 4 — Categories** ✅ Closed taxonomy in `backend/app/categories.py` (15 tags); Visit Madison events pre-tagged from the source taxonomy; LLM-assisted tagging pass shipped in `backend/app/tagger.py` (runs at the end of `/admin/scrape` and via the standalone `/admin/tag` endpoint, with the system prompt cached); frontend filter UI shipped (multi-select tag cloud, sensible defaults, localStorage)
- **Step 5 — Map view** ✅ Geocoding pipeline (Nominatim, cached per venue in `venue_geocodes` so re-scrapes are free) runs after each scraper; `latitude`/`longitude` exposed on the API; List/Map segmented toggle in the header renders a Leaflet map of Madison with clustered pins, multi-event popups, and a panel for events whose venues didn't resolve
- **Recent polish** ✅ Fuzzy cross-source dedup in ingest (title similarity ≥ 0.65 anchored by time + venue); explicit source priority ranking; Isthmus description enrichment from event detail pages; Previous/Next nav buttons; sticky-header layout fixes

## Adding a Scraper

1. Create `backend/app/scrapers/<source_name>.py`
2. Subclass `BaseSource` and implement `fetch() -> list[RawEvent]`
3. Add an instance to `SCRAPERS` in `backend/app/main.py`

Each `RawEvent` has a `canonical_hash()` method that generates a deduplication key from the normalized title, start date, and venue name. After an exact hash miss, `ingest_events()` also runs a fuzzy title-similarity check (anchored by time and venue) to catch near-duplicate events listed under slightly different names by different sources. The shared `ingest_events()` function handles upserts, multi-source linking, category merging, and event status tracking automatically.

If the source has its own category taxonomy that maps cleanly to ours (`backend/app/categories.py`), populate `RawEvent.categories` per event to save LLM cost in the Step 4 tagging pass. Map conservatively — drop ambiguous source categories rather than mis-tagging.

Geocoding happens automatically after each scrape via Nominatim, with results cached per venue in the `venue_geocodes` table — scrapers don't need to do anything special. Populate `RawEvent.venue_address` (preferred) or `RawEvent.venue_name` and the geocoder will attempt to resolve coordinates for the map view.

## API

### `GET /events`

Returns active events for a given date. Long-running events appear on every date within their range. Only `status=active` events are returned.

| Parameter | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Date to query (optional — returns all active events if omitted) |

```json
[
  {
    "id": "...",
    "title": "Example Event",
    "start_at": "2025-06-01T19:00:00Z",
    "end_at": null,
    "venue_name": "The Sylvee",
    "venue_address": "25 S Livingston St, Madison, WI",
    "latitude": 43.0731,
    "longitude": -89.3820,
    "categories": [],
    "status": "active",
    "sources": [
      {"source_name": "Isthmus", "source_url": "https://isthmus.com/events/..."},
      {"source_name": "Eventbrite", "source_url": "https://..."}
    ]
  }
]
```

`latitude` and `longitude` are populated by the geocoder when a Nominatim lookup for the venue succeeds; they are `null` for events whose venue couldn't be resolved (those events still appear in the list view and in a "without a location" panel under the map).

### Admin endpoint authentication

All `/admin/*` endpoints require an `X-Admin-Key` header matching `ADMIN_API_KEY` from `backend/.env`. In development mode without `ADMIN_API_KEY` set the check is bypassed; in production `ADMIN_API_KEY` must be set or the app refuses to start.

```
curl -X POST http://localhost:8000/admin/scrape -H "X-Admin-Key: <your-key>"
```

### `POST /admin/scrape`

Triggers all registered scrapers and ingests results. After each scraper, runs a geocoding pass for any newly-active events from that source that don't yet have coordinates. Once all scrapers + geocoding finish, runs the LLM tagger (if `ANTHROPIC_API_KEY` is set) to assign categories to events without any. Returns per-source stats including ingestion (`inserted`, `updated`, `deactivated`) and geocoding (`geocoded`, `geocode_misses`, `geocode_skipped`), plus a top-level `_tagging` entry with `{tagged, skipped_no_description, candidates, batches}`.

### `POST /admin/tag`

Run the LLM category tagger as a standalone pass. Tags only active events whose `categories` array is empty and whose description is at least 80 characters. Idempotent — already-tagged events are skipped. Optional `model=<model-id>` overrides `TAGGER_MODEL`; useful for evaluating a different Claude model without changing config. Requires `ANTHROPIC_API_KEY` in `backend/.env`.

### `POST /admin/geocode`

Backfill or retry geocoding outside a scrape. Optional `force=true` clears non-success rows from the `venue_geocodes` cache so previously-failed lookups get retried.
