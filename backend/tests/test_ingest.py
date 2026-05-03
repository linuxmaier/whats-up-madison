from datetime import datetime, timezone

from app.ingest import ingest_events
from app.models import Event, EventSource
from app.scrapers.base import RawEvent


def _dt(hour: int = 19) -> datetime:
    return datetime(2026, 6, 15, hour, 0, 0, tzinfo=timezone.utc)


def _raw(
    title: str = "Concert in the Park",
    start_at: datetime | None = None,
    source_name: str = "Source A",
    source_url: str = "https://example.com/event/1",
    description: str | None = None,
    venue_name: str = "Garner Park",
    venue_address: str | None = None,
    categories: list[str] | None = None,
    all_day: bool = False,
) -> RawEvent:
    return RawEvent(
        title=title,
        start_at=start_at or _dt(),
        source_name=source_name,
        source_url=source_url,
        description=description,
        venue_name=venue_name,
        venue_address=venue_address,
        categories=categories or [],
        all_day=all_day,
    )


# ---------------------------------------------------------------------------
# 1. First-run insert
# ---------------------------------------------------------------------------

def test_first_run_insert(db):
    stats = ingest_events("Source A", [_raw()], db)

    assert stats["inserted"] == 1
    assert stats["updated"] == 0

    events = db.query(Event).all()
    assert len(events) == 1
    assert events[0].status == "active"

    sources = db.query(EventSource).all()
    assert len(sources) == 1
    assert sources[0].is_active is True
    assert sources[0].source_name == "Source A"


# ---------------------------------------------------------------------------
# 2. Fill-in-nulls: never overwrites set values; fills previously-null fields
# ---------------------------------------------------------------------------

def test_fill_in_nulls_does_not_overwrite(db):
    first = _raw(description="Original description", venue_address=None)
    ingest_events("Source A", [first], db)

    second = _raw(description="New description attempt", venue_address="123 Main St")
    stats = ingest_events("Source A", [second], db)

    assert stats["updated"] == 1

    event = db.query(Event).one()
    assert event.description == "Original description"
    assert event.venue_address == "123 Main St"


# ---------------------------------------------------------------------------
# 3. Two sources → one Event, two EventSource rows
# ---------------------------------------------------------------------------

def test_two_sources_one_event(db):
    ingest_events("Source A", [_raw(source_name="Source A", source_url="https://a.example/1")], db)
    ingest_events("Source B", [_raw(source_name="Source B", source_url="https://b.example/1")], db)

    assert db.query(Event).count() == 1
    sources = db.query(EventSource).all()
    assert len(sources) == 2
    names = {s.source_name for s in sources}
    assert names == {"Source A", "Source B"}


# ---------------------------------------------------------------------------
# 4. Fuzzy match: near-identical title, same time + venue → merged
# ---------------------------------------------------------------------------

def test_fuzzy_match_merges(db):
    ingest_events("Source A", [_raw(title="Concert in the Park", source_name="Source A")], db)
    ingest_events(
        "Source B",
        [_raw(title="Concert in the Parks", source_name="Source B", source_url="https://b.example/2")],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2


# ---------------------------------------------------------------------------
# 5. Staleness: event removed from a run → EventSource inactive, Event removed
# ---------------------------------------------------------------------------

def test_staleness_deactivates_and_removes(db):
    ingest_events("Source A", [_raw()], db)

    stats = ingest_events("Source A", [], db)

    assert stats["deactivated"] == 1

    source = db.query(EventSource).one()
    assert source.is_active is False

    event = db.query(Event).one()
    assert event.status == "removed"


# ---------------------------------------------------------------------------
# 6. Reactivation: removed event reappears → status back to active
# ---------------------------------------------------------------------------

def test_reactivation(db):
    ingest_events("Source A", [_raw()], db)
    ingest_events("Source A", [], db)

    event = db.query(Event).one()
    assert event.status == "removed"

    ingest_events("Source A", [_raw()], db)

    db.refresh(event)
    assert event.status == "active"

    source = db.query(EventSource).one()
    assert source.is_active is True


# ---------------------------------------------------------------------------
# 7. Pre-dedup: two raws sharing a canonical_hash in one run → one Event,
#    one EventSource, categories unioned
# ---------------------------------------------------------------------------

def test_pre_dedup_collapses_same_hash(db):
    raw_a = _raw(title="Volunteer at Foodbank", categories=["community"])
    raw_b = _raw(title="Volunteer at Foodbank", categories=["food"])

    stats = ingest_events("Source A", [raw_a, raw_b], db)

    assert stats["inserted"] == 1
    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 1

    event = db.query(Event).one()
    assert set(event.categories) == {"community", "food"}
