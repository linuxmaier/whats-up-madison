# Agent Instructions — What's Up Madison

## Project Overview

Self-populating Madison WI events aggregator. Backend scrapes known sources daily and stores normalized events in PostgreSQL. Frontend shows a date-picker + event card list with click-through to original sources.

## Environment

- **Conda env:** `whats-up-madison` (Python 3.12)
- **Always use:** `~/miniconda3/envs/whats-up-madison/bin/<tool>` for pip, pytest, ruff, etc.
- **Never use:** bare `pip` or system Python

## Running the Backend Locally

With Docker Compose (full stack, recommended):
```
docker compose up
```

Without Docker (requires local Postgres at localhost:5432):
```
cd backend
~/miniconda3/envs/whats-up-madison/bin/uvicorn app.main:app --reload
```

## Key Conventions

### Scrapers

All scrapers live in `backend/app/scrapers/`. Each source is one file, one class:

```python
from app.scrapers.base import BaseSource, RawEvent

class MySource(BaseSource):
    name = "My Source"
    scraper_type = "ical"  # api | ical | html

    def fetch(self) -> list[RawEvent]:
        ...
```

`RawEvent.canonical_hash()` generates a deduplication key: `sha256(normalized_title|start_date|venue_name)`. Always set `source_name` and `source_url` on every `RawEvent`.

### Events Query

Long-running events appear on every date in their range. The query logic is:
```
start_at::date <= requested_date AND coalesce(end_at, start_at)::date >= requested_date
```

### Database

- Tables are created at startup via `Base.metadata.create_all()` — no migration runner yet.
- PostgreSQL-specific types in use: `ARRAY(String)` for categories, `JSONB` for source config.
- All primary keys are UUIDs.

### Environment Variables

Loaded from `backend/.env` (gitignored). See `backend/.env.example` for required keys. Never hardcode credentials.

`CORS_ORIGINS` must be a **comma-separated string**, not a JSON array. pydantic-settings v2 tries to JSON-parse `list[str]` fields from dotenv sources before validators run, which causes a `SettingsError` for non-JSON values. To avoid this, `cors_origins` is typed as `str` in `Settings` and exposed as a list via `settings.get_cors_origins()`. Do not change it back to `list[str]`.

## Linting

```
~/miniconda3/envs/whats-up-madison/bin/ruff check backend/
```

## Current Build Status

- **Done (Step 1):** repo skeleton, Docker Compose, PostgreSQL, SQLAlchemy models (`Event`, `Source`), FastAPI with `GET /events?date=` endpoint, scraper base class
- **Next (Step 2):** UW-Madison iCal scraper end-to-end + React/Vite frontend (date picker, event cards)
- **Planned (Step 3):** more scrapers (Eventbrite API, City of Madison, Isthmus, venue HTML), deduplication, APScheduler for daily runs
- **Planned (Step 4):** LLM-assisted category taxonomy pass, category filtering in frontend

The backend is confirmed running at `http://localhost:8000`. API docs at `http://localhost:8000/docs`. The frontend does not exist yet.

## Local Management

Machine-specific notes (instance IDs, connection strings, useful commands) live in `local_management/` — this directory is gitignored and should never be committed.
