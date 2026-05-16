import logging
import logging.config

from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.geocode_runner import geocode_all_missing, geocode_missing_for_source
from app.ingest import ingest_events
from app.routers import events
from app.schemas import FeedbackRequest
from app.scrapers.atwood import AtwoodMusicHallSource
from app.scrapers.base import BaseSource
from app.scrapers.city_of_madison import CityOfMadisonSource
from app.scrapers.dmi import DMISource
from app.scrapers.high_noon import HighNoonSource
from app.scrapers.isthmus import IsthmusSource
from app.scrapers.majestic import MajesticTheatreSource
from app.scrapers.our_lives import OurLivesSource
from app.scrapers.ticketmaster import TicketmasterSource
from app.scrapers.visit_madison import VisitMadisonSource
from app.scrapers.wco import WisconsinChamberOrchestraSource
from app.tagger import tag_untagged_events

logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "app": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "app",
            "stream": "ext://sys.stdout",
        }
    },
    "loggers": {
        "app": {
            "handlers": ["console"],
            "level": "DEBUG",
            "propagate": False,
        }
    },
})

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        logger.exception("Schema creation failed at startup: %s", e)
        raise
    yield


app = FastAPI(title="What's Up Madison", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

app.include_router(events.router)

SCRAPERS = [
    IsthmusSource(),
    VisitMadisonSource(),
    HighNoonSource(),
    OurLivesSource(),
    TicketmasterSource(),
    AtwoodMusicHallSource(),
    MajesticTheatreSource(),
    DMISource(),
    WisconsinChamberOrchestraSource(),
    CityOfMadisonSource(),
]


def require_admin_key(x_admin_key: Optional[str] = Header(default=None)):
    if settings.environment == "development" and not settings.admin_api_key:
        return
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    if request.website:
        return {"ok": True}
    if not settings.github_token:
        raise HTTPException(status_code=503, detail="Feedback submissions are not configured")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{settings.github_repo}/issues",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "title": request.title,
                "body": request.body + (f"\n\n---\n**Email:** {request.contact}" if request.contact.strip() else ""),
                "labels": ["user-feedback"],
            },
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"GitHub API error: {resp.status_code}")
    return {"ok": True, "issue_url": resp.json()["html_url"]}


def _select_scrapers(names: list[str]) -> list[BaseSource]:
    """Return the SCRAPERS subset matching `names` (exact match on .name).

    Empty `names` means "all". Unknown names → HTTP 400 with the valid set.
    """
    if not names:
        return list(SCRAPERS)
    by_name = {s.name: s for s in SCRAPERS}
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unknown scraper name(s)",
                "unknown": unknown,
                "available": sorted(by_name),
            },
        )
    # Preserve declaration order in SCRAPERS, not the order names were passed,
    # so repeated runs are deterministic regardless of curl arg order.
    requested = set(names)
    return [s for s in SCRAPERS if s.name in requested]


@app.post("/admin/scrape")
def trigger_scrape(
    scraper: list[str] = Query(default_factory=list),
    days: Optional[int] = Query(default=None, ge=1),
    skip_geocode: bool = False,
    skip_tag: bool = False,
    _: None = Depends(require_admin_key),
    db: Session = Depends(get_db),
):
    selected = _select_scrapers(scraper)
    results = {}
    for s in selected:
        logger.info(
            "Starting scrape: %s (window_days=%s, skip_geocode=%s, skip_tag=%s)",
            s.name, days, skip_geocode, skip_tag,
        )
        try:
            raw = s.fetch(window_days=days)
            stats = ingest_events(s.name, raw, db)
            results[s.name] = stats
            logger.info("Scrape complete: %s — %s", s.name, stats)
        except Exception as e:
            results[s.name] = {"error": str(e)}
            logger.warning("Scrape failed: %s — %s", s.name, e)
            continue
        if days is not None and not s.supports_window_days:
            # Surface the no-op so a caller passing ?days=N knows the filter
            # didn't apply to this HTML-calendar scraper.
            results[s.name]["window_days_honored"] = False
        if skip_geocode:
            continue
        try:
            geo_stats = geocode_missing_for_source(s.name, db)
            results[s.name] = {**results[s.name], **geo_stats}
            logger.info("Geocode complete: %s — %s", s.name, geo_stats)
        except Exception as e:
            results[s.name]["geocode_error"] = str(e)
            logger.warning("Geocode failed: %s — %s", s.name, e)
    if not skip_tag:
        try:
            results["_tagging"] = tag_untagged_events(db)
        except Exception as e:
            results["_tagging"] = {"error": str(e)}
    return results


@app.post("/admin/tag")
def trigger_tag(model: str = None, _: None = Depends(require_admin_key), db: Session = Depends(get_db)):
    try:
        return tag_untagged_events(db, model=model)
    except Exception as e:
        return {"error": str(e)}


@app.post("/admin/geocode")
def trigger_geocode(force: bool = False, _: None = Depends(require_admin_key), db: Session = Depends(get_db)):
    try:
        return geocode_all_missing(db, force=force)
    except Exception as e:
        return {"error": str(e)}
