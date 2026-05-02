# Agent Instructions — What's Up Madison

## Project Overview

Self-populating Madison WI events aggregator. Backend scrapes known sources daily and stores normalized events in PostgreSQL. Frontend shows a date-picker + event card list with click-through to original sources.

## Environment

- **Conda env:** `whats-up-madison` (Python 3.12)
- **Always use:** `~/miniconda3/envs/whats-up-madison/bin/<tool>` for pip, pytest, ruff, etc.
- **Never use:** bare `pip` or system Python

## Running the Stack Locally

Full stack with Docker Compose (recommended):
```
docker compose up
```

Frontend dev server (separate terminal):
```
cd frontend && npm run dev
```

- API: http://localhost:8000
- Frontend: http://localhost:5173

Without Docker (requires local Postgres at localhost:5432):
```
cd backend
~/miniconda3/envs/whats-up-madison/bin/uvicorn app.main:app --reload
```

## DB Schema Changes

No migration runner yet — tables are created at startup via `Base.metadata.create_all()`. This only creates missing tables; it does not alter existing ones. For schema changes during development, recreate the DB:
```
docker compose down -v && docker compose up
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

After writing a scraper, add it to `SCRAPERS` in `backend/app/main.py`. The `POST /admin/scrape` endpoint triggers all registered scrapers.

`RawEvent.canonical_hash()` generates a deduplication key: `sha256(normalized_title|start_date|venue_name)`. Always set `source_name` and `source_url` on every `RawEvent`.

`RawEvent.categories` is optional. If a source ships its own taxonomy that maps cleanly to ours (`backend/app/categories.py`), populate `categories` per event so we save LLM tagging cost on those events. Map conservatively — drop ambiguous source categories so they fall through to the Step 4 LLM pass instead of mis-tagging. If the source delivers HTML (description, etc.), use `clean_html_text()` from `app.scrapers.base` to strip tags + unescape entities.

### Source Catalog

`docs/EVENT_SOURCES.md` tracks all known and prospective event sources, their integration status (integrated, planned, investigating, deferred, rejected), and notes on feasibility. **Update that file whenever sourcing changes** — adding a scraper, retiring one, deferring a candidate, or recording a feasibility finding (feed format, signal quality, ToS).

### Category Taxonomy

The closed set of event category tags lives in `backend/app/categories.py` (`CATEGORIES`, `CATEGORY_DESCRIPTIONS`). The same list is mirrored with descriptions in `docs/EVENT_SOURCES.md` under "Category Taxonomy", and the bare list (plus the default-excluded set used by the frontend filter) is mirrored in `frontend/src/lib/categories.js`. The LLM tagging pass (Step 4) imports from the module to constrain its output. When changing the taxonomy, update the Python module, the doc, and the frontend mirror together — they should always agree.

### Ingestion (`backend/app/ingest.py`)

All scrapers share `ingest_events(source_name, raw_events, db)`. It handles:
- **Pre-dedup** — collapses multiple raws sharing a `canonical_hash` from the same run before insert (a source can return e.g. two recurring "Volunteer at Foodbank" series with different IDs but identical title/date/venue); categories are unioned across the duplicates
- **Upsert** by `canonical_hash` — inserts new events, skips duplicates
- **Fill-in-nulls** — adds missing scalar fields from later sources; never overwrites set values
- **Category union** — `RawEvent.categories` are merged into `Event.categories` preserving order, no duplicates; later sources can enrich an earlier one
- **Multi-source** — one `EventSource` row per (event, source); same event from two scrapers gets two `EventSource` rows, both linked to the same `Event`
- **Staleness** — after each run, deactivates `EventSource` rows from that scraper not seen in the run; marks `Event.status = 'removed'` when no active sources remain
- **Re-activation** — if a removed event reappears in a future run, `status` is set back to `'active'`

### Event Status

Events are never hard-deleted. `status` values:
- `active` — shown in `GET /events`
- `removed` — hidden from `GET /events`; was once active but all sources stopped returning it

### Multi-Source Response

`GET /events` returns events with a `sources` array instead of single `source_name`/`source_url`:
```json
{
  "sources": [
    {"source_name": "UW-Madison", "source_url": "https://..."}
  ]
}
```

### Events Query

Long-running events appear on every date in their range. The query logic is:
```
start_at::date <= requested_date AND coalesce(end_at, start_at)::date >= requested_date
```

Only `status = 'active'` events are returned.

### Database

- Tables are created at startup via `Base.metadata.create_all()` — no migration runner yet.
- PostgreSQL-specific types in use: `ARRAY(String)` for categories, `JSONB` for source config.
- All primary keys are UUIDs.
- Session uses `autoflush=False` — call `db.flush()` explicitly before bulk update queries that need to see pending inserts.

### Environment Variables

Loaded from `backend/.env` (gitignored). See `backend/.env.example` for required keys. Never hardcode credentials.

`CORS_ORIGINS` must be a **comma-separated string**, not a JSON array. pydantic-settings v2 tries to JSON-parse `list[str]` fields from dotenv sources before validators run, which causes a `SettingsError` for non-JSON values. To avoid this, `cors_origins` is typed as `str` in `Settings` and exposed as a list via `settings.get_cors_origins()`. Do not change it back to `list[str]`.

## Frontend

React + Vite + Tailwind CSS. Node deps are project-local (not in conda).

```
cd frontend
npm install      # first time or after package.json changes
npm run dev      # dev server at http://localhost:5173
npm run build    # production build
```

`vite.config.js` proxies `/events` and `/admin` to `http://localhost:8000`, so no CORS issues in dev.

## Linting

```
~/miniconda3/envs/whats-up-madison/bin/ruff check backend/
```

## Triggering a Scrape (Dev)

```
curl -X POST http://localhost:8000/admin/scrape
```

Returns per-scraper stats: `{"Isthmus": {"inserted": N, "updated": N, "deactivated": N}}`.

## Current Build Status

- **Done (Step 1):** repo skeleton, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class
- **Done (Step 2):** multi-source `Event`/`EventSource` data model, `ingest.py`, `POST /admin/scrape` endpoint, React/Vite/Tailwind frontend (date picker + event cards)
- **In progress (Step 3):** Isthmus integrated (iCal + RSS, 30-day window, ~235 events) and Visit Madison integrated (Simpleview JSON API, 30-day window, ~460 events with category pre-tagging); APScheduler for daily runs still planned; more sources in `docs/EVENT_SOURCES.md`
- **In progress (Step 4):** category filter UI in frontend (multi-select tag cloud, default excludes Volunteer & Causes / Civic & Politics / Community & Clubs, persists to localStorage); LLM-assisted category tagging pass still planned (tracked in GH issue #6)

Backend: http://localhost:8000 — API docs: http://localhost:8000/docs
Frontend: http://localhost:5173

## Local Management

Machine-specific notes (instance IDs, connection strings, useful commands) live in `local_management/` — this directory is gitignored and should never be committed.
