# Agent Instructions — What's Up Madison

> **CLAUDE.md is a symlink to this file.** Always edit `AGENTS.md` directly — never edit `CLAUDE.md`.

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
- **Upsert** by `canonical_hash` — inserts new events, skips exact duplicates
- **Fuzzy dedup** — after an exact hash miss, a secondary search matches candidates by time+venue and scores title similarity via `difflib.SequenceMatcher`; events scoring ≥ `FUZZY_TITLE_THRESHOLD` (0.65) are treated as duplicates and merged rather than inserted as new rows; this catches near-identical events listed under slightly different titles by different sources
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

### Geocoding (`backend/app/geocoding.py`, `geocode_runner.py`)

After each scraper runs inside `POST /admin/scrape`, a geocoding pass populates `Event.latitude`/`longitude` for any active event from that source that doesn't yet have coordinates. Results are cached in the `venue_geocodes` table keyed by a normalized lookup string, so two events at the same venue cost one Nominatim request and re-scrapes cost ~0 network calls.

- Geocoder: Nominatim (OpenStreetMap). Free, but ToS requires (a) max 1 req/sec — enforced via a module-level lock in `geocoding.py`, (b) a real `User-Agent` with contact info, (c) attribution on rendered tiles (handled by Leaflet's default attribution control).
- Address-form lookups query free-text bounded to a Madison bbox. Venue-name-only lookups (mostly Isthmus, no street address) append `", madison, wi"` to the name and use the same bbox-bounded query. **Do not** combine `q` with structured `city`/`state`/`country` params — Nominatim returns 400.
- Failed lookups (`status=not_found|error`) are also cached so we don't retry every run. To retry them, hit `POST /admin/geocode?force=true` (clears non-success rows from `venue_geocodes` and re-runs the missing set).
- For backfill or one-off geocodes outside a scrape, use `POST /admin/geocode`. Cache makes it near-instant when warm.

Scrapers don't need to do anything special — populating `RawEvent.venue_address` (preferred) or `RawEvent.venue_name` is enough for the geocoder to attempt a lookup.

### Tagging (`backend/app/tagger.py`)

`tag_untagged_events(db, model=None)` runs the LLM category-tagging pass. It selects active events whose `categories` array is empty (i.e., the source didn't pre-tag them) and whose `description` is at least 80 characters, batches them 25 at a time, and asks Claude to assign zero or more tags from `CATEGORIES`. The system prompt is sent with `cache_control: ephemeral` so repeated batches reuse the prompt cache. Predictions outside the taxonomy are silently dropped. Each batch commits independently, so a mid-run failure leaves prior batches persisted.

- Runs automatically at the end of `POST /admin/scrape` after all scrapers + geocoding finish (under the `_tagging` key in the response).
- Also exposed as `POST /admin/tag?model=<model-id>` for one-off runs or model evaluation. Without `model`, uses `settings.tagger_model` (default `claude-haiku-4-5`).
- Idempotent — events that already have at least one category are skipped, so re-running is cheap.
- Requires `ANTHROPIC_API_KEY` in `backend/.env`; raises `ValueError` if unset.
- Skips events with short descriptions (<80 chars). Their card just shows no categories rather than wasting a token budget on guesses; if a source improves its descriptions, the next run picks them up.

### Environment Variables

Loaded from `backend/.env` (gitignored). See `backend/.env.example` for required keys. Never hardcode credentials.

`ADMIN_API_KEY` gates the `/admin/scrape`, `/admin/tag`, and `/admin/geocode` endpoints. All three require an `X-Admin-Key: <key>` request header. In development (`ENVIRONMENT=development`) with no key set the check is bypassed so existing dev workflows keep working. In production the app refuses to start if `ADMIN_API_KEY` is unset.

`CORS_ORIGINS` must be a **comma-separated string**, not a JSON array. pydantic-settings v2 tries to JSON-parse `list[str]` fields from dotenv sources before validators run, which causes a `SettingsError` for non-JSON values. To avoid this, `cors_origins` is typed as `str` in `Settings` and exposed as a list via `settings.get_cors_origins()`. Do not change it back to `list[str]`.

`GITHUB_TOKEN` is a GitHub Personal Access Token with `issues: write` scope. Used by `POST /feedback` to file user-submitted feedback as GitHub Issues labeled `user-feedback`. If unset, the endpoint returns HTTP 503. Not required in development if you don't need to test feedback submission.

## Frontend

React + Vite + Tailwind CSS. Node deps are project-local (not in conda).

### Source priority

`frontend/src/lib/sources.js` exports `sortedSources(sources)`, which sorts a `sources` array by `SOURCE_PRIORITY` (currently `['Isthmus', 'Visit Madison']`). Both card components use this to determine the title link (first source wins) and footer display order. When adding a new scraper, add it to `SOURCE_PRIORITY` at the appropriate trust rank; sources not in the list sort to the end.

### Card types

There are two card components: `EventCard` (`frontend/src/components/EventCard.jsx`) for timed events and `AllDayCard` (inside `frontend/src/components/AllDayStrip.jsx`) for all-day / time-varies events. They have different visual weights but share most interaction patterns. When making a UI or behavior change to one, consider whether it applies to the other. It won't always be appropriate to treat them identically, but check both before deciding.

The expanded-detail modal is shared: `frontend/src/components/EventModal.jsx` is rendered by both card components and by `MapView` pin popups. Modal-related changes (layout, share/calendar buttons, Escape behavior, etc.) belong in `EventModal.jsx` so all three callers stay in sync. Note: `EventModal` uses an inline `zIndex: 10000` rather than a Tailwind `z-*` class so it renders above Leaflet's panes (which go up to ~700).

### List vs Map view

The header has a List/Map segmented toggle. Both views consume the same `filteredEvents` array from `App.jsx`, so date / category / venue filters apply identically to both. View mode is persisted to localStorage under `whats-up-madison.viewMode`. List view renders the time-bucketed sections + density rail; map view renders `MapView.jsx` (Leaflet + react-leaflet, with `react-leaflet-cluster` for low-zoom clustering). Pins group co-located events (lat/lng to 5 decimal places ≈ 1m) into a single marker with a count badge; multi-event popups list `time — title` rows that each open `EventModal`. Events without coordinates are surfaced in a collapsible "events without a location" panel below the map so they're never dropped from view. When adding a new filter or selection that should affect the visible event set, apply it to `filteredEvents` in `App.jsx` and both views pick it up automatically.

```
cd frontend
npm install      # first time or after package.json changes
npm run dev      # dev server at http://localhost:5173
npm run build    # production build
```

`vite.config.js` proxies `/events`, `/admin`, and `/feedback` to `http://localhost:8000`, so no CORS issues in dev.

## Linting

```
~/miniconda3/envs/whats-up-madison/bin/ruff check backend/
```

## Triggering a Scrape (Dev)

```
curl -X POST http://localhost:8000/admin/scrape
```

Returns per-scraper stats including ingestion + geocoding:
`{"Isthmus": {"inserted": N, "updated": N, "deactivated": N, "geocoded": N, "geocode_misses": N, "geocode_skipped": N}}`.

To backfill or retry geocoding outside a scrape: `curl -X POST 'http://localhost:8000/admin/geocode'` (add `?force=true` to clear non-success cache rows and retry previously-failed lookups).

## Current Build Status

- **Done (Step 1):** repo skeleton, Docker Compose, PostgreSQL, SQLAlchemy models, FastAPI `GET /events?date=` endpoint, scraper base class.
- **Done (Step 2):** multi-source `Event`/`EventSource` data model, `ingest.py`, `POST /admin/scrape` endpoint, React/Vite/Tailwind frontend (date picker + event cards).
- **Done (Step 4):** closed category taxonomy in `backend/app/categories.py` (15 tags); Visit Madison events pre-tagged from the source's own taxonomy; LLM-assisted tagging pass shipped in `backend/app/tagger.py` (runs at end of `/admin/scrape`, also exposed as `/admin/tag`); category filter UI in frontend (multi-select tag cloud, sensible defaults, persists to localStorage).
- **Done (Step 5):** geocoding pipeline (Nominatim, cached per venue in `venue_geocodes`) runs after each scraper; `latitude`/`longitude` exposed on the API; List/Map segmented toggle in the header renders a Leaflet map of Madison with clustered pins, multi-event popups, and a panel for events whose venues didn't resolve.
- **Done (recent polish):** fuzzy cross-source dedup in ingest (title similarity ≥ 0.65 anchored by time + venue); explicit source priority ranking (`SOURCE_PRIORITY` in `frontend/src/lib/sources.js`); Isthmus description enrichment from event detail pages; Previous/Next nav buttons; sticky-header layout fixes.
- **In progress (Step 3):** Isthmus integrated (iCal + RSS, 30-day window, ~235 events) and Visit Madison integrated (Simpleview JSON API, 30-day window, ~460 events); more sources in `docs/EVENT_SOURCES.md`; daily scheduling not yet wired up (no APScheduler — recommend running `/admin/scrape` from cron / systemd timer / external scheduler).

Backend: http://localhost:8000 — API docs: http://localhost:8000/docs
Frontend: http://localhost:5173

## Local Management

Machine-specific notes (instance IDs, connection strings, useful commands) live in `local_management/` — this directory is gitignored and should never be committed.
