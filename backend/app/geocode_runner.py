import logging
import time

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.geocoding import geocode_event
from app.models import Event, EventSource, VenueGeocode

logger = logging.getLogger(__name__)


def _missing_coords_query(db: Session):
    return (
        db.query(Event)
        .filter(
            Event.status == "active",
            Event.latitude.is_(None),
            or_(Event.venue_address.isnot(None), Event.venue_name.isnot(None)),
        )
    )


def geocode_missing_for_source(source_name: str, db: Session) -> dict:
    """Geocode active events from a given source that don't yet have coordinates."""
    candidates = (
        _missing_coords_query(db)
        .join(EventSource, EventSource.event_id == Event.id)
        .filter(EventSource.source_name == source_name, EventSource.is_active.is_(True))
        .distinct()
        .all()
    )

    hits = 0
    misses = 0
    skipped = 0
    for event in candidates:
        try:
            updated = geocode_event(event, db)
        except Exception as e:
            logger.warning("Geocode failed for event %s: %s", event.id, e)
            misses += 1
            continue
        if updated:
            hits += 1
        elif event.venue_name or event.venue_address:
            misses += 1
        else:
            skipped += 1

    if hits:
        db.commit()

    return {
        "geocoded": hits,
        "geocode_misses": misses,
        "geocode_skipped": skipped,
    }


def geocode_all_missing(db: Session, force: bool = False) -> dict:
    """Backfill: geocode every active event missing coordinates. If force, retry failed lookups."""
    started = time.monotonic()

    cleared_failed = 0
    if force:
        cleared_failed = (
            db.query(VenueGeocode)
            .filter(VenueGeocode.status != "success")
            .delete(synchronize_session=False)
        )
        db.commit()

    candidates = _missing_coords_query(db).all()

    hits = 0
    misses = 0
    skipped = 0
    errors = 0
    for event in candidates:
        try:
            updated = geocode_event(event, db)
        except Exception as e:
            logger.warning("Geocode failed for event %s: %s", event.id, e)
            errors += 1
            continue
        if updated:
            hits += 1
        elif event.venue_name or event.venue_address:
            misses += 1
        else:
            skipped += 1

    if hits:
        db.commit()

    return {
        "events_updated": hits,
        "misses": misses,
        "skipped": skipped,
        "errors": errors,
        "cleared_failed_cache": cleared_failed,
        "duration_seconds": round(time.monotonic() - started, 1),
    }
