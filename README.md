# What's Up Madison

A self-populating events calendar for Madison, WI. Automatically aggregates events from local venues, publications, and calendars — no manual entry required. Browse by date, see what's on, click through to the original source.

## Architecture

- **Backend:** Python / FastAPI + PostgreSQL (SQLAlchemy ORM)
- **Frontend:** React / Vite + Tailwind CSS (date picker + event card list)
- **Scrapers:** per-source plugins (API, iCal, HTML) run on a daily schedule
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
│   │   ├── main.py          # FastAPI app entry point + /admin/scrape
│   │   ├── models.py        # SQLAlchemy models (Event, EventSource, Source)
│   │   ├── schemas.py       # Pydantic response schemas
│   │   ├── ingest.py        # Shared scraper ingestion utility
│   │   ├── routers/
│   │   │   └── events.py    # GET /events?date=YYYY-MM-DD
│   │   └── scrapers/
│   │       ├── base.py      # RawEvent dataclass + BaseSource interface
│   │       ├── isthmus.py
│   │       └── ...          # one module per source
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                # React / Vite + Tailwind CSS
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── DatePicker.jsx
│           └── EventCard.jsx
├── docker-compose.yml
└── local_management/        # gitignored — machine-local notes and commands
```

## Roadmap

- **Step 1 — Skeleton** ✅ Repo structure, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class
- **Step 2 — First scraper + frontend** ✅ Multi-source data model (`Event`/`EventSource`), ingestion utility, React/Vite/Tailwind frontend with date picker and event cards
- **Step 3 — More scrapers** 🔄 Isthmus integrated (iCal + RSS, 30-day window) and Visit Madison integrated (Simpleview JSON API, 30-day window, with category pre-tagging from the source's own taxonomy); Eventbrite API, City of Madison, individual venue HTML scrapers, APScheduler for daily runs still planned
- **Step 4 — Categories** 🔄 Closed taxonomy in `backend/app/categories.py` (15 tags); Visit Madison events pre-tagged from the source taxonomy; frontend filter UI shipped (multi-select tag cloud, sensible defaults, localStorage); LLM-assisted tagging pass still planned to fill in Isthmus + future sources

## Adding a Scraper

1. Create `backend/app/scrapers/<source_name>.py`
2. Subclass `BaseSource` and implement `fetch() -> list[RawEvent]`
3. Add an instance to `SCRAPERS` in `backend/app/main.py`

Each `RawEvent` has a `canonical_hash()` method that generates a deduplication key from the normalized title, start date, and venue name. The shared `ingest_events()` function handles upserts, multi-source linking, category merging, and event status tracking automatically.

If the source has its own category taxonomy that maps cleanly to ours (`backend/app/categories.py`), populate `RawEvent.categories` per event to save LLM cost in the Step 4 tagging pass. Map conservatively — drop ambiguous source categories rather than mis-tagging.

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
    "categories": [],
    "status": "active",
    "sources": [
      {"source_name": "Isthmus", "source_url": "https://isthmus.com/events/..."},
      {"source_name": "Eventbrite", "source_url": "https://..."}
    ]
  }
]
```

### `POST /admin/scrape`

Triggers all registered scrapers and ingests results. Returns per-source stats.
