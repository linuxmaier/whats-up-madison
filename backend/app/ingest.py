import logging
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import cast, func, select
from sqlalchemy import Date as SQLDate
from sqlalchemy.orm import Session

from app import canonical_venues
from app.models import Event, EventSource
from app.scrapers.base import RawEvent

logger = logging.getLogger(__name__)

# Trust ranking for event sources — lower index = higher trust.
# Mirrors SOURCE_PRIORITY in frontend/src/lib/sources.js; keep in sync when adding scrapers.
SOURCE_PRIORITY = ["High Noon Saloon", "Atwood Music Hall", "Majestic Theatre", "Ticketmaster", "Our Lives", "DMI", "Wisconsin Chamber Orchestra", "Isthmus", "Visit Madison"]

# Fields that higher-priority sources may overwrite, not just fill when null.
# title is included because a trusted venue source often has the canonical event name.
# start_at and end_at are included so a re-scrape can correct a previously-wrong time
# (surfaced by Atwood: their structured time fields ship placeholder values, and we
# initially trusted them — without overwrite the bug data would stick post-fix).
# canonical_hash keys on the start *date*, not time, so same-day corrections don't
# break dedup; for cross-date corrections the row would simply be inserted as new.
_OVERWRITABLE_FIELDS = ("title", "description", "start_at", "end_at", "venue_name", "venue_address")

FUZZY_TITLE_THRESHOLD = 0.65  # tuned empirically against the Isthmus + Visit Madison overlap


def ingest_events(source_name: str, raw_events: list[RawEvent], db: Session) -> dict:
    run_start = datetime.now(timezone.utc)
    inserted = 0
    updated = 0

    # Normalize venue names to canonical building names before hashing so
    # events from sources that use sub-room names (e.g. Isthmus iCal's
    # "Overture Center-Overture Hall") merge with events from sources that
    # use the building name (e.g. Ticketmaster's "Overture Center for the Arts").
    raw_events = [_normalize_raw_venue(r) for r in raw_events]

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
            incoming_rank = _source_rank(source_name)
            existing_rank = _best_existing_rank(event, db)
            is_higher_priority = incoming_rank < existing_rank
            # Same-source re-runs overwrite their own previous contributions —
            # if the scrape output changed, treat that as the venue having
            # updated the data (reschedules, description edits, image swaps,
            # room moves, etc.). Only allowed when no strictly-higher-priority
            # source has weighed in: equal rank + an existing link from this
            # source means we ARE the top contributor on this row.
            is_self_rerun_at_top = (
                incoming_rank == existing_rank
                and db.query(EventSource.id)
                .filter_by(event_id=event.id, source_name=source_name)
                .first()
                is not None
            )
            for field in _OVERWRITABLE_FIELDS:
                raw_val = getattr(raw, field)
                if raw_val is None:
                    continue
                if (
                    getattr(event, field) is None
                    or is_higher_priority
                    or is_self_rerun_at_top
                ):
                    setattr(event, field, raw_val)
                    changed = True
            # start_at and end_at are a coupled pair — `end_at` is only
            # meaningful relative to `start_at`. When an authoritative source
            # overwrites `start_at`, its view of `end_at` (even None) replaces
            # any prior `end_at`, since the prior end was anchored to a
            # now-stale start. (For other fields None is treated as
            # "no opinion" so cross-source merging keeps lower-source values.)
            if is_higher_priority or is_self_rerun_at_top:
                if event.end_at != raw.end_at:
                    event.end_at = raw.end_at
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

        # Overwrite venue_address with the canonical value when this venue is
        # in the registry, regardless of fill-in-nulls semantics — the whole
        # point is that aggregator addresses for these venues are unreliable
        # (#115). Skipped when the venue isn't a known canonical match.
        _apply_canonical_address(event)

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


def _normalize_title_for_match(title: str) -> str:
    """Lowercase + strip + collapse ' & ' to ' and ' so the fuzzy substring
    check (and SequenceMatcher ratio) treats the two as the same token.

    Targets the literal pattern (with surrounding spaces) so compound tokens
    like "L&G" aren't mangled. Added for #191, where Visit Madison shipped
    two listings for the same Karben4 trivia night as "Brews & Q's Taproom
    Trivia at Karben4" and "Brews and Q's" — the shorter title is only a
    substring of the longer after this normalization.

    Also strips a trailing city suffix (" - madison", " - madison, wi") that
    Visit Madison appends to disambiguate touring acts (#187: their listing
    titled the show "Anberlin - Madison" while Atwood listed it as "Anberlin
    with Emery, Watashi Wa & Motion Light" — without this strip, neither
    title is a substring of the other and the SequenceMatcher ratio falls
    below the fuzzy threshold). Anchored to the end so titles that mention
    Madison mid-string (e.g. "Concert - Madison Symphony") are untouched.
    Applied only to the matching key — stored titles are unchanged.
    """
    s = title.lower().strip().replace(" & ", " and ")
    for suffix in (" - madison, wi", " - madison"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].rstrip()
            break
    return s


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

    raw_title = _normalize_title_for_match(raw.title)
    best: "Event | None" = None
    best_ratio = 0.0
    for event in candidates:
        cand_title = _normalize_title_for_match(event.title)
        ratio = SequenceMatcher(None, raw_title, cand_title).ratio()
        # When one title is fully contained in the other (e.g. "Pert Near
        # Sandstone" vs "Pert Near Sandstone-Side by Side Album Release …"),
        # treat it as a match. SequenceMatcher's ratio drops well below the
        # threshold for prefix/extension cases like this even though it's
        # clearly the same event. Safe because we already require an exact
        # start_at + venue_name anchor.
        if raw_title and cand_title and (raw_title in cand_title or cand_title in raw_title):
            ratio = max(ratio, 1.0)
        if ratio > best_ratio:
            best_ratio, best = ratio, event

    if best_ratio >= FUZZY_TITLE_THRESHOLD:
        logger.debug(
            "Fuzzy match (%.2f): '%s' → '%s'", best_ratio, raw.title, best.title
        )
        return best
    return None


def _source_rank(source_name: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source_name)
    except ValueError:
        return len(SOURCE_PRIORITY)


def _best_existing_rank(event: Event, db: Session) -> float:
    rows = db.query(EventSource).filter_by(event_id=event.id, is_active=True).all()
    if not rows:
        return float("inf")
    return min(_source_rank(r.source_name) for r in rows)


def _normalize_raw_venue(raw: RawEvent) -> RawEvent:
    normalized = canonical_venues.normalize_name(raw.venue_name)
    if normalized == raw.venue_name:
        return raw
    return dc_replace(raw, venue_name=normalized)


def _apply_canonical_address(event: Event) -> None:
    canonical = canonical_venues.lookup(event.venue_name)
    if canonical is None:
        return
    if event.venue_address != canonical.address:
        event.venue_address = canonical.address


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
