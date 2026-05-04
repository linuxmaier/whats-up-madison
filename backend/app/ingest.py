import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import cast, func, select
from sqlalchemy import Date as SQLDate
from sqlalchemy.orm import Session

from app.models import Event, EventSource
from app.scrapers.base import RawEvent

logger = logging.getLogger(__name__)

_FILLABLE_FIELDS = ("description", "end_at", "venue_name", "venue_address", "image_url")
FUZZY_TITLE_THRESHOLD = 0.65  # tuned empirically against the Isthmus + Visit Madison overlap


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

    # Tracks event_ids for which we've already created/updated an EventSource
    # for source_name in this run. Needed because fuzzy matching can map two
    # distinct raws (different canonical_hashes) to the same Event row, which
    # would otherwise produce a duplicate (event_id, source_name) insert.
    seen_for_source: set = set()

    for raw in raw_events:
        hash_ = raw.canonical_hash()

        event = db.query(Event).filter_by(canonical_hash=hash_).first()
        if event is None:
            event = _fuzzy_find_event(raw, db)
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

        if event.id not in seen_for_source:
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
            seen_for_source.add(event.id)

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
        select(EventSource.event_id).where(EventSource.is_active.is_(True))
    )
    db.query(Event).filter(
        Event.id.not_in(active_event_ids),
        Event.status == "active",
    ).update({"status": "removed"}, synchronize_session=False)

    db.commit()

    stats = {"inserted": inserted, "updated": updated, "deactivated": deactivated}
    logger.info("%s ingest: %s", source_name, stats)
    return stats


def _fuzzy_find_event(raw: RawEvent, db: Session) -> "Event | None":
    """Return an existing Event that is likely the same real-world event as raw.

    Requires a strong time anchor (exact start_at for timed events, or same
    date + exact venue for all-day events) plus title similarity ≥ threshold.
    """
    raw_venue = (raw.venue_name or "").lower().strip()
    has_venue = bool(raw_venue)

    # All-day events with no venue have no reliable anchor — skip to avoid false positives.
    if raw.all_day and not has_venue:
        return None

    q = db.query(Event).filter(Event.status != "removed")
    if raw.all_day:
        q = q.filter(cast(Event.start_at, SQLDate) == raw.start_at.date())
    else:
        q = q.filter(Event.start_at == raw.start_at)
    if has_venue:
        q = q.filter(func.lower(func.trim(Event.venue_name)) == raw_venue)

    candidates = q.all()
    if not candidates:
        return None

    raw_title = raw.title.lower().strip()
    best: "Event | None" = None
    best_ratio = 0.0
    for event in candidates:
        ratio = SequenceMatcher(None, raw_title, event.title.lower().strip()).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, event

    if best_ratio >= FUZZY_TITLE_THRESHOLD:
        logger.debug(
            "Fuzzy match (%.2f): '%s' → '%s'", best_ratio, raw.title, best.title
        )
        return best
    return None


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
