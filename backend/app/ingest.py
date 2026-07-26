import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import cast, select
from sqlalchemy import Date as SQLDate
from sqlalchemy.orm import Session

from app import canonical_venues
from app.models import Event, EventSource
from app.scrapers.base import RawEvent

logger = logging.getLogger(__name__)

# Trust ranking for event sources — lower index = higher trust.
# Mirrors SOURCE_PRIORITY in frontend/src/lib/sources.js; keep in sync when adding scrapers.
SOURCE_PRIORITY = ["High Noon Saloon", "Atwood Music Hall", "Majestic Theatre", "Ticketmaster", "Our Lives", "Wisconsin Chamber Orchestra", "Isthmus", "Visit Madison", "City of Madison", "Alliant Energy Center"]

# Fields that higher-priority sources may overwrite, not just fill when null.
# title is included because a trusted venue source often has the canonical event name.
# start_at and end_at are included so a re-scrape can correct a previously-wrong time
# (surfaced by Atwood: their structured time fields ship placeholder values, and we
# initially trusted them — without overwrite the bug data would stick post-fix).
# canonical_hash keys on the start *date*, not time, so same-day corrections don't
# break dedup; for cross-date corrections the row would simply be inserted as new.
_OVERWRITABLE_FIELDS = ("title", "description", "start_at", "end_at", "venue_name", "venue_address")

FUZZY_TITLE_THRESHOLD = 0.65  # tuned empirically against the Isthmus + Visit Madison overlap

# Dropped from the head of a title before scoring — see _normalize_title_for_match.
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")

# Words that carry no identifying signal, so two titles sharing only these are
# not evidence of the same event (#246).
_TITLE_STOPWORDS = frozenset({
    "the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "with",
    "by", "from", "featuring", "feat", "presents",
})
_TITLE_WORD_RE = re.compile(r"[a-z0-9']+")

# Headliner extraction (#243). Cross-source duplicates routinely agree on the
# act and disagree on everything after it — Isthmus lists the full bill
# ("Max McNown, Sam Burchfield") where Ticketmaster lists the tour
# ("Max McNown - The Summer Vacation Tour"). Those score 0.51, far below any
# threshold that would be safe to set: #236 measured that lowering the bar far
# enough to catch them also merges two different APT plays in the same slot.
_STATUS_PREFIX_RE = re.compile(
    r"^(?:sold out|canceled|cancelled|postponed|free|rescheduled)\s*[:\-]\s*"
)
# Separators between the headliner and whatever follows it. The spaced forms of
# the dashes matter — an unspaced hyphen is usually inside a name
# ("Teeny-Tiny Terrace Trot"), not a separator.
_HEADLINER_SPLIT_RE = re.compile(
    r"\s+[-–—+|/]\s+|[,:;]\s+|\s+(?:with|w/|feat\.?|featuring|presents)\s+"
)
# Below this, a headliner is too generic to carry a merge on its own.
_MIN_HEADLINER_LEN = 5


def ingest_chunk(
    source_name: str,
    raw_events: list[RawEvent],
    db: Session,
    *,
    run_start: datetime,
) -> dict:
    """Insert/update one batch of raw events from ``source_name``.

    Commits at the end. Does NOT deactivate stale rows or mark events removed
    — those passes belong in :func:`finalize_source_run` and only run after
    the full set of chunks for a source has been processed. The split lets
    scrapers with long per-event fetch phases (Isthmus) yield events
    incrementally: each chunk commits while later chunks are still being
    built, keeping the DB connection warm and persisting partial progress
    when a later batch fails.
    """
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
    # the rest. Scoped to the chunk: two raws in different chunks with the
    # same hash collide on the DB lookup instead (the first commit makes the
    # EventSource visible to the second chunk's query).
    raw_events = _dedupe_by_hash(raw_events)

    # Tracks event_ids for which we've already created/updated an EventSource
    # for source_name in this chunk. Needed because fuzzy matching can map two
    # distinct raws (different canonical_hashes) to the same Event row, which
    # would otherwise produce a duplicate (event_id, source_name) insert
    # before the next db.flush() makes the first add visible.
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
            # Propagate description=None on self-reruns at the top of the priority
            # stack. If this source previously stored a description but now emits
            # None (e.g. a boilerplate filter added after initial ingest), clear
            # the stale value so lower-priority sources can fill via null-fill
            # semantics on the next pass. Mirrors the end_at special case above.
            if is_self_rerun_at_top and raw.description is None and event.description is not None:
                event.description = None
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

    db.flush()
    db.commit()

    stats = {"inserted": inserted, "updated": updated}
    logger.info("%s ingest chunk: %s", source_name, stats)
    return stats


def finalize_source_run(
    source_name: str,
    db: Session,
    *,
    run_start: datetime,
) -> dict:
    """Run end-of-source cleanup after all chunks for ``source_name`` complete.

    Deactivates ``EventSource`` rows from this source that weren't touched
    (``last_seen_at < run_start``) and marks events with no remaining active
    sources as ``removed``. Skip this when a chunk raised — without a full
    pass we can't confidently distinguish "source dropped this event" from
    "we never got to it before the failure," so the safe default is to leave
    EventSource rows alone and let the next clean run reconcile.
    """
    deactivated = (
        db.query(EventSource)
        .filter(
            EventSource.source_name == source_name,
            EventSource.last_seen_at < run_start,
            EventSource.is_active.is_(True),
        )
        .update({"is_active": False}, synchronize_session=False)
    )

    active_event_ids = (
        select(EventSource.event_id).where(EventSource.is_active.is_(True))
    )
    db.query(Event).filter(
        Event.id.not_in(active_event_ids),
        Event.status == "active",
    ).update({"status": "removed"}, synchronize_session=False)

    db.commit()

    stats = {"deactivated": deactivated}
    logger.info("%s finalize: %s", source_name, stats)
    return stats


def ingest_events(source_name: str, raw_events: list[RawEvent], db: Session) -> dict:
    """Single-batch convenience wrapper around ingest_chunk + finalize.

    Preserves the original API for tests and any caller that still passes a
    full list at once. New code should drive the chunked path directly via
    ``fetch_chunks()`` → ``ingest_chunk()`` → ``finalize_source_run()`` so
    long-running scrapers don't sit on an idle DB connection.
    """
    run_start = datetime.now(timezone.utc)
    chunk_stats = ingest_chunk(source_name, raw_events, db, run_start=run_start)
    final_stats = finalize_source_run(source_name, db, run_start=run_start)
    return {**chunk_stats, **final_stats}


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

    Finally drops a leading article ("the ", "a ", "an "). On short titles the
    shared prefix is a large fraction of the comparison and inflates the ratio
    past the threshold: American Players Theatre runs "The Chairs" and "The
    Matchmaker" in repertory in the same slot, and they scored 0.667 purely on
    the shared "the " (#246). Mirrors the leading-"the" strip that
    ``canonical_venues.match_key`` already applies on the venue side.
    """
    s = title.lower().strip().replace(" & ", " and ")
    for suffix in (" - madison, wi", " - madison"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].rstrip()
            break
    return _LEADING_ARTICLE_RE.sub("", s)


def _significant_title_tokens(normalized_title: str) -> set[str]:
    """Words in an already-normalized title that carry identifying signal.

    Accents are folded first so a source that ships "Sueno" for APT's "Sueño"
    still shares a token with it — without folding the two would look like
    completely different words despite a 0.80 character ratio.
    """
    folded = "".join(
        c for c in unicodedata.normalize("NFKD", normalized_title)
        if not unicodedata.combining(c)
    )
    return {w for w in _TITLE_WORD_RE.findall(folded) if w not in _TITLE_STOPWORDS}


def _shares_significant_token(title_a: str, title_b: str) -> bool:
    """Whether two normalized titles share at least one meaningful word.

    Used as a guard *after* the similarity score clears the threshold, so it can
    only reject a merge, never create one. Without it, two unrelated short
    titles clear 0.65 on shared stopwords alone — "The Chairs" and "The
    Matchmaker" scored 0.667 and silently collapsed into one event (#246).

    When either title has no significant words left (a title made entirely of
    stopwords), there is nothing to judge on, so the score stands unchallenged.
    """
    tokens_a = _significant_title_tokens(title_a)
    tokens_b = _significant_title_tokens(title_b)
    if not tokens_a or not tokens_b:
        return True
    return bool(tokens_a & tokens_b)


def _headliner(normalized_title: str) -> str:
    """The leading act/show segment of an already-normalized title.

    Takes the normalized form so it inherits the "&"->"and" collapse, the
    trailing-city strip and the leading-article strip for free.
    """
    s = _STATUS_PREFIX_RE.sub("", normalized_title)
    return _HEADLINER_SPLIT_RE.split(s, maxsplit=1)[0].strip()


def _headliner_match(title_a: str, title_b: str) -> bool:
    """Whether two normalized titles lead with the same act or show.

    Equality, or word-boundary prefix containment so "bit brigade" matches
    "bit brigade performs mega man x live". The length floor keeps a very short
    leading token from carrying a merge by itself.

    Only consulted when the similarity score already fell short, and only after
    the shared-significant-token guard has had its say, so this can add merges
    but never create one the #246 guard would have rejected.
    """
    head_a, head_b = _headliner(title_a), _headliner(title_b)
    if len(head_a) < _MIN_HEADLINER_LEN or len(head_b) < _MIN_HEADLINER_LEN:
        return False
    if head_a == head_b:
        return True
    longer, shorter = (head_a, head_b) if len(head_a) >= len(head_b) else (head_b, head_a)
    return longer.startswith(shorter + " ")


def _find_fuzzy_duplicate(
    candidates: list[Event], title: str, venue_name: "str | None"
) -> "tuple[Event, float, bool] | None":
    """Python-side half of fuzzy matching: given a set of time-anchored
    candidates, return the best (event, ratio, was_headliner_match) whose
    venue and title clear FUZZY_TITLE_THRESHOLD, or None.

    Extracted from _fuzzy_find_event (#245) so it can be shared with
    reconcile_duplicate_events, which compares two already-persisted Event
    rows rather than a fresh RawEvent against the DB. Keeping one
    implementation means the two callers can't silently drift apart, which is
    exactly the class of bug (#236/#243/#246) this matcher has repeatedly had
    to have fixed.
    """
    raw_venue = canonical_venues.match_key(venue_name)
    has_venue = bool(raw_venue)

    # The venue anchor can't be a SQL predicate: venues_match compares
    # normalized base names and treats an absent city suffix as compatible with
    # a known one, which SQL equality can't express (#236).
    if has_venue:
        candidates = [
            e for e in candidates if canonical_venues.venues_match(venue_name, e.venue_name)
        ]
    if not candidates:
        return None

    raw_title = _normalize_title_for_match(title)
    best: "Event | None" = None
    best_ratio = 0.0
    best_by_headliner = False
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
        # A high character ratio is not enough on its own: two unrelated short
        # titles can clear the threshold on shared stopwords alone. Require at
        # least one meaningful word in common before the score counts (#246).
        if not _shares_significant_token(raw_title, cand_title):
            continue
        # Sources routinely agree on the act and disagree on everything after
        # it — "Max McNown, Sam Burchfield" vs "Max McNown - The Summer Vacation
        # Tour" is one show at 0.51. Promote a shared headliner to the
        # threshold rather than lowering the threshold itself, which #236
        # measured would merge distinct APT plays (#243).
        if ratio < FUZZY_TITLE_THRESHOLD and _headliner_match(raw_title, cand_title):
            ratio = FUZZY_TITLE_THRESHOLD
            headliner_matched = True
        else:
            headliner_matched = False
        if ratio > best_ratio:
            best_ratio, best = ratio, event
            best_by_headliner = headliner_matched

    if best_ratio >= FUZZY_TITLE_THRESHOLD:
        return best, best_ratio, best_by_headliner
    return None


def _fuzzy_find_event(raw: RawEvent, db: Session) -> "Event | None":
    """Return an existing Event that is likely the same real-world event as raw.

    Requires a strong time anchor (exact start_at for timed events, or same
    date + exact venue for all-day events) plus title similarity ≥ threshold.
    """
    raw_venue = canonical_venues.match_key(raw.venue_name)
    has_venue = bool(raw_venue)

    # All-day events with no venue have no reliable anchor — skip to avoid false positives.
    if raw.all_day and not has_venue:
        return None

    q = db.query(Event).filter(Event.status != "removed")
    if raw.all_day:
        q = q.filter(cast(Event.start_at, SQLDate) == raw.start_at.date())
    else:
        q = q.filter(Event.start_at == raw.start_at)

    candidates = q.all()
    match = _find_fuzzy_duplicate(candidates, raw.title, raw.venue_name)
    if match is None:
        return None
    best, best_ratio, best_by_headliner = match
    logger.debug(
        "Fuzzy match (%s): '%s' → '%s'",
        "headliner" if best_by_headliner else f"{best_ratio:.2f}",
        raw.title,
        best.title,
    )
    return best


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


def _pick_survivor(a: Event, b: Event, db: Session) -> tuple[Event, Event]:
    """Return (survivor, loser) for two events found to be duplicates.

    Higher source-trust rank wins (mirrors the priority ordering ingest_chunk
    already applies to raw-vs-event merges); ties broken by earlier
    created_at so the more established row survives.
    """
    rank_a, rank_b = _best_existing_rank(a, db), _best_existing_rank(b, db)
    if rank_a != rank_b:
        return (a, b) if rank_a < rank_b else (b, a)
    return (a, b) if a.created_at <= b.created_at else (b, a)


def _merge_event(survivor: Event, loser: Event, db: Session) -> None:
    """Fold loser's data into survivor and re-point its EventSource rows.

    Field merge is a one-directional null-fill: survivor is the higher-
    priority side by construction (see _pick_survivor), so there's no
    "overwrite" branch here the way ingest_chunk has for a fresh raw — only
    filling what survivor doesn't already have.
    """
    for field in _OVERWRITABLE_FIELDS:
        if getattr(survivor, field) is None:
            loser_val = getattr(loser, field)
            if loser_val is not None:
                setattr(survivor, field, loser_val)

    if loser.categories:
        merged = list(survivor.categories or [])
        for c in loser.categories:
            if c not in merged:
                merged.append(c)
        survivor.categories = merged

    survivor_sources = {s.source_name: s for s in survivor.sources}
    for source in list(loser.sources):
        existing = survivor_sources.get(source.source_name)
        if existing is None:
            # Assign via the relationship, not the raw event_id column, so
            # survivor.sources reflects the move in-memory immediately — a
            # later iteration in the same reconcile group may need to see it
            # (e.g. a third event in a group merging into this survivor).
            source.event = survivor
            survivor_sources[source.source_name] = source
            continue
        # Both events already carry a link from this source (e.g. Isthmus on
        # both sides of the Great Gatsby pair in #245) — keep whichever
        # reading is more current rather than blindly preferring one row.
        is_fresher = (source.is_active and not existing.is_active) or (
            source.is_active == existing.is_active and source.last_seen_at > existing.last_seen_at
        )
        if is_fresher:
            existing.source_url = source.source_url
            existing.last_seen_at = source.last_seen_at
            existing.is_active = source.is_active
        db.delete(source)

    _apply_canonical_address(survivor)

    # Never hard-delete Events (see AGENTS.md) — the loser becomes an inert,
    # sourceless "removed" row rather than a normal staleness casualty.
    loser.status = "removed"


def reconcile_duplicate_events(db: Session, *, dry_run: bool = True) -> dict:
    """Re-run fuzzy matching over existing rows and merge survivors (#245).

    _fuzzy_find_event only runs at insert time, when a freshly-scraped raw's
    canonical_hash misses. Once two Event rows exist for the same real-world
    event, every later scrape of either source recomputes the same hash it
    already produced and hits its own row directly — fuzzy matching, and any
    later fix to it, is never consulted again for that pair. If each row
    keeps at least one distinct active source, the normal staleness self-heal
    in finalize_source_run can't save it either, since that only fires when a
    row's *last* active source goes quiet. This is a manual/on-demand sweep
    over the whole active table to catch and merge rows that drifted into
    duplication this way — not part of the regular scrape pipeline, since the
    drift it cleans up accumulates slowly, not every run.

    Groups events by the same anchor _fuzzy_find_event uses (exact start_at,
    or date for all-day events), then within each group walks events in
    created_at order looking for fuzzy duplicates against representatives
    already seen, exactly mirroring how ingest_chunk would have processed
    them had they arrived in that order one at a time.
    """
    events = (
        db.query(Event)
        .filter(Event.status != "removed")
        .order_by(Event.created_at)
        .all()
    )

    groups: dict = defaultdict(list)
    for e in events:
        key = e.start_at.date() if e.all_day else e.start_at
        groups[key].append(e)

    merges = []
    duplicate_groups = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        representatives: list[Event] = []
        group_had_merge = False
        for event in group:
            match = _find_fuzzy_duplicate(representatives, event.title, event.venue_name)
            if match is None:
                representatives.append(event)
                continue
            rep, _ratio, _headliner = match
            survivor, loser = _pick_survivor(rep, event, db)
            merges.append({
                "survivor_id": str(survivor.id),
                "survivor_title": survivor.title,
                "loser_id": str(loser.id),
                "loser_title": loser.title,
                "venue_name": survivor.venue_name,
                "start_at": survivor.start_at.isoformat(),
            })
            _merge_event(survivor, loser, db)
            db.flush()
            if survivor is not rep:
                representatives[representatives.index(rep)] = survivor
            group_had_merge = True
        if group_had_merge:
            duplicate_groups += 1

    if dry_run:
        db.rollback()
    else:
        db.commit()

    stats = {
        "groups_scanned": len(groups),
        "duplicate_groups": duplicate_groups,
        "merges": len(merges),
        "dry_run": dry_run,
        "details": merges,
    }
    logger.info("Reconcile duplicates: %s", stats)
    return stats
