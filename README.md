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
curl -X POST http://localhost:8000/admin/scrape
```

This runs all registered scrapers and populates the database. APScheduler (daily automation) is planned for Step 3.

## Project Structure

```
whats-up-madison/
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI app entry point + /admin/scrape, /admin/geocode
│   │   ├── models.py           # SQLAlchemy models (Event, EventSource, Source, VenueGeocode)
│   │   ├── schemas.py          # Pydantic response schemas
│   │   ├── ingest.py           # Shared scraper ingestion utility
│   │   ├── geocoding.py        # Nominatim wrapper (throttle, User-Agent, Madison bbox, cache)
│   │   ├── geocode_runner.py   # Per-source and backfill geocoding passes
│   │   ├── routers/
│   │   │   └── events.py       # GET /events?date=YYYY-MM-DD
│   │   └── scrapers/
│   │       ├── base.py         # RawEvent dataclass + BaseSource interface
│   │       ├── isthmus.py
│   │       └── ...             # one module per source
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                   # React / Vite + Tailwind CSS
│   └── src/
│       ├── App.jsx             # date picker, filters, List/Map toggle
│       └── components/
│           ├── DatePicker.jsx
│           ├── EventCard.jsx
│           ├── AllDayStrip.jsx
│           ├── EventModal.jsx  # shared expanded-detail modal (used by both card types and MapView)
│           └── MapView.jsx     # Leaflet map of events with clustered + multi-event pins
├── docker-compose.yml
└── local_management/           # gitignored — machine-local notes and commands
```

## Roadmap

- **Step 1 — Skeleton** ✅ Repo structure, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class
- **Step 2 — First scraper + frontend** ✅ Multi-source data model (`Event`/`EventSource`), ingestion utility, React/Vite/Tailwind frontend with date picker and event cards
- **Step 3 — More scrapers** 🔄 Isthmus integrated (iCal + RSS, 30-day window) and Visit Madison integrated (Simpleview JSON API, 30-day window, with category pre-tagging from the source's own taxonomy); Eventbrite API, City of Madison, individual venue HTML scrapers, APScheduler for daily runs still planned
- **Step 4 — Categories** 🔄 Closed taxonomy in `backend/app/categories.py` (15 tags); Visit Madison events pre-tagged from the source taxonomy; frontend filter UI shipped (multi-select tag cloud, sensible defaults, localStorage); LLM-assisted tagging pass still planned to fill in Isthmus + future sources
- **Step 5 — Map view** ✅ Geocoding pipeline (Nominatim, cached per venue in `venue_geocodes` so re-scrapes are free) runs after each scraper; `latitude`/`longitude` exposed on the API; List/Map segmented toggle in the header renders a Leaflet map of Madison with clustered pins, multi-event popups, and a panel for events whose venues didn't resolve

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

### `POST /admin/scrape`

Triggers all registered scrapers and ingests results. After each scraper, also runs a geocoding pass for any newly-active events from that source that don't yet have coordinates. Returns per-source stats including ingestion (`inserted`, `updated`, `deactivated`) and geocoding (`geocoded`, `geocode_misses`, `geocode_skipped`).

### `POST /admin/geocode`

Backfill or retry geocoding outside a scrape. Optional `force=true` clears non-success rows from the `venue_geocodes` cache so previously-failed lookups get retried.
