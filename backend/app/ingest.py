from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Event, EventSource
from app.scrapers.base import RawEvent

_FILLABLE_FIELDS = ("description", "end_at", "venue_name", "venue_address", "image_url")


def ingest_events(source_name: str, raw_events: list[RawEvent], db: Session) -> dict:
    run_start = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    # Collapse raws that share a canonical_hash — a single source can return
    # multiple records that map to the same event (e.g. Visit Madison lists two
    # recurring "Volunteer at Foodbank" series with different recids but the
    # same title/date/venue). They produce one Event row, so we must produce
    # one EventSource row too — otherwise the (event_id, source_name) unique
    # constraint trips. We keep the first occurrence and union categories from
    # the rest.
    raw_events = _dedupe_by_hash(raw_events)

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
                categories=list(raw.categories),
                all_day=raw.all_day,
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
            if raw.categories:
                existing = list(event.categories or [])
                merged = existing + [c for c in raw.categories if c not in existing]
                if merged != existing:
                    event.categories = merged
                    changed = True
            if event.status == "removed":
                event.status = "active"
                changed = True
            # If an all-day placeholder is superseded by a raw with a real time, upgrade it.
            if event.all_day and not raw.all_day:
                event.all_day = False
                event.start_at = raw.start_at
                event.end_at = raw.end_at
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


def _dedupe_by_hash(raw_events: list[RawEvent]) -> list[RawEvent]:
    seen: dict[str, RawEvent] = {}
    for raw in raw_events:
        h = raw.canonical_hash()
        kept = seen.get(h)
        if kept is None:
            seen[h] = raw
        else:
            for c in raw.categories:
                if c not in kept.categories:
                    kept.categories.append(c)
    return list(seen.values())
