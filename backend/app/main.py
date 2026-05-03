import logging
import logging.config

from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.geocode_runner import geocode_all_missing, geocode_missing_for_source
from app.ingest import ingest_events
from app.routers import events
from app.scrapers.isthmus import IsthmusSource
from app.scrapers.visit_madison import VisitMadisonSource
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

Base.metadata.create_all(bind=engine)

app = FastAPI(title="What's Up Madison")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)

app.include_router(events.router)

SCRAPERS = [IsthmusSource(), VisitMadisonSource()]


def require_admin_key(x_admin_key: Optional[str] = Header(default=None)):
    if settings.environment == "development" and not settings.admin_api_key:
        return
    if not x_admin_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/scrape")
def trigger_scrape(_: None = Depends(require_admin_key), db: Session = Depends(get_db)):
    results = {}
    for scraper in SCRAPERS:
        logger.info("Starting scrape: %s", scraper.name)
        try:
            raw = scraper.fetch()
            stats = ingest_events(scraper.name, raw, db)
            results[scraper.name] = stats
            logger.info("Scrape complete: %s — %s", scraper.name, stats)
        except Exception as e:
            results[scraper.name] = {"error": str(e)}
            logger.warning("Scrape failed: %s — %s", scraper.name, e)
            continue
        try:
            geo_stats = geocode_missing_for_source(scraper.name, db)
            results[scraper.name] = {**results[scraper.name], **geo_stats}
            logger.info("Geocode complete: %s — %s", scraper.name, geo_stats)
        except Exception as e:
            results[scraper.name]["geocode_error"] = str(e)
            logger.warning("Geocode failed: %s — %s", scraper.name, e)
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
