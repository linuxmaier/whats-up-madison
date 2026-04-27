from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Event, EventSource
from app.scrapers.base import RawEvent

_FILLABLE_FIELDS = ("description", "end_at", "venue_name", "venue_address", "image_url")


def ingest_events(source_name: str, raw_events: list[RawEvent], db: Session) -> dict:
    run_start = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    for raw in raw_events:
        hash_ = raw.canonical_hash()

        event = db.query(Event).filter_by(canonical_hash=hash_).first()
        if event is None:
            event = Event(
                title=raw.title,
                description=raw.description,
                start_at=raw.start_at,
                end_at=raw.end_at,
                venue_name=raw.venue_name,
                venue_address=raw.venue_address,
                image_url=raw.image_url,
                canonical_hash=hash_,
                status="active",
            )
            db.add(event)
            db.flush()
            inserted += 1
        else:
            changed = False
            for field in _FILLABLE_FIELDS:
                if getattr(event, field) is None and getattr(raw, field) is not None:
                    setattr(event, field, getattr(raw, field))
                    changed = True
            if event.status == "removed":
                event.status = "active"
                changed = True
            if changed:
                updated += 1

        source = (
            db.query(EventSource)
            .filter_by(event_id=event.id, source_name=source_name)
            .first()
        )
        if source is None:
            db.add(EventSource(
                event_id=event.id,
                source_name=source_name,
                source_url=raw.source_url,
                last_seen_at=run_start,
                is_active=True,
            ))
        else:
            source.source_url = raw.source_url
            source.last_seen_at = run_start
            source.is_active = True

    # Flush pending EventSource inserts so the cleanup queries below can see them
    db.flush()

    # Deactivate EventSources from this scraper that weren't seen in this run
    deactivated = (
        db.query(EventSource)
        .filter(
            EventSource.source_name == source_name,
            EventSource.last_seen_at < run_start,
            EventSource.is_active.is_(True),
        )
        .update({"is_active": False}, synchronize_session=False)
    )

    # Mark events with no remaining active sources as removed
    active_event_ids = (
        db.query(EventSource.event_id)
        .filter(EventSource.is_active.is_(True))
        .subquery()
    )
    db.query(Event).filter(
        Event.id.not_in(active_event_ids),
        Event.status == "active",
    ).update({"status": "removed"}, synchronize_session=False)

    db.commit()

    return {"inserted": inserted, "updated": updated, "deactivated": deactivated}
