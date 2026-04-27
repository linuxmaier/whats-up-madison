# What's Up Madison

A self-populating events calendar for Madison, WI. Automatically aggregates events from local venues, publications, and calendars — no manual entry required. Browse by date, see what's on, click through to the original source.

## Architecture

- **Backend:** Python / FastAPI + PostgreSQL (SQLAlchemy ORM)
- **Frontend:** React / Vite (date picker + event card list)
- **Scrapers:** per-source plugins (API, iCal, HTML) run on a daily schedule
- **Local dev:** Docker Compose

## Getting Started

### Prerequisites

- Docker + Docker Compose
- [miniconda](https://docs.conda.io/en/latest/miniconda.html) (for local Python tooling)

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

> **Note:** The frontend is not yet built (planned for Step 2). This step will work once `frontend/` exists.

```
cd frontend
npm install
npm run dev
```

- Frontend: http://localhost:5173

## Project Structure

```
whats-up-madison/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app entry point
│   │   ├── models.py        # SQLAlchemy models (Event, Source)
│   │   ├── schemas.py       # Pydantic response schemas
│   │   ├── routers/
│   │   │   └── events.py    # GET /events?date=YYYY-MM-DD
│   │   └── scrapers/
│   │       ├── base.py      # RawEvent dataclass + BaseSource interface
│   │       └── ...          # one module per source
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                # React / Vite app (not yet scaffolded)
├── docker-compose.yml
└── local_management/        # gitignored — machine-local notes and commands
```

## Roadmap

- **Step 1 — Skeleton** ✅ Repo structure, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class
- **Step 2 — First scraper + frontend** UW-Madison iCal feed wired end-to-end; React/Vite frontend with date picker and event cards linking to original sources
- **Step 3 — More scrapers** Eventbrite API, City of Madison, Isthmus, individual venue HTML scrapers; deduplication logic; APScheduler for daily runs
- **Step 4 — Categories** LLM analysis of accumulated events to propose a category taxonomy; category filtering added to the frontend

## Adding a Scraper

1. Create `backend/app/scrapers/<source_name>.py`
2. Subclass `BaseSource` and implement `fetch() -> list[RawEvent]`
3. Register the source in the scheduler (see `app/main.py`)

Each `RawEvent` has a `canonical_hash()` method that generates a deduplication key from the normalized title, start date, and venue name.

## API

### `GET /events`

Returns events for a given date. Long-running events appear on every date within their range.

| Parameter | Type | Description |
|---|---|---|
| `date` | `YYYY-MM-DD` | Date to query (optional — returns all events if omitted) |

```json
[
  {
    "id": "...",
    "title": "Example Event",
    "start_at": "2025-06-01T19:00:00-05:00",
    "end_at": null,
    "venue_name": "The Sylvee",
    "venue_address": "25 S Livingston St, Madison, WI",
    "categories": [],
    "source_name": "Eventbrite",
    "source_url": "https://..."
  }
]
```
