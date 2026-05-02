from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.ingest import ingest_events
from app.routers import events
from app.scrapers.isthmus import IsthmusSource
from app.scrapers.visit_madison import VisitMadisonSource
from app.tagger import tag_untagged_events

Base.metadata.create_all(bind=engine)

app = FastAPI(title="What's Up Madison")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(events.router)

SCRAPERS = [IsthmusSource(), VisitMadisonSource()]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/scrape")
def trigger_scrape(db: Session = Depends(get_db)):
    results = {}
    for scraper in SCRAPERS:
        try:
            raw = scraper.fetch()
            stats = ingest_events(scraper.name, raw, db)
            results[scraper.name] = stats
        except Exception as e:
            results[scraper.name] = {"error": str(e)}
    try:
        results["_tagging"] = tag_untagged_events(db)
    except Exception as e:
        results["_tagging"] = {"error": str(e)}
    return results


@app.post("/admin/tag")
def trigger_tag(model: str = None, db: Session = Depends(get_db)):
    try:
        return tag_untagged_events(db, model=model)
    except Exception as e:
        return {"error": str(e)}
