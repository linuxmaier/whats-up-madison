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
# 2. Same-source re-runs trust the latest scrape output
# ---------------------------------------------------------------------------

def test_same_source_re_run_overwrites_set_fields(db):
    # When the scrape output changes, the venue's data changed — reflect it.
    # Covers reschedules, description edits, image swaps, etc.
    first = _raw(description="Original description", venue_address=None)
    ingest_events("Source A", [first], db)

    second = _raw(description="Venue updated the description", venue_address="123 Main St")
    stats = ingest_events("Source A", [second], db)

    assert stats["updated"] == 1

    event = db.query(Event).one()
    # Set values are overwritten by the new scrape output.
    assert event.description == "Venue updated the description"
    # Previously-null fields are filled.
    assert event.venue_address == "123 Main St"


def test_same_source_re_run_picks_up_time_reschedule(db):
    # Venue moves the show from 8 PM to 11 PM the same day. canonical_hash
    # keys on the date, so the existing row matches and gets updated.
    original = _raw(start_at=datetime(2026, 6, 15, 20, 0, 0, tzinfo=timezone.utc))
    ingest_events("Source A", [original], db)

    rescheduled = _raw(start_at=datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc))
    stats = ingest_events("Source A", [rescheduled], db)

    assert stats["inserted"] == 0
    assert stats["updated"] == 1
    event = db.query(Event).one()
    assert event.start_at == datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc)


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
# 4b. Substring titles merge even when SequenceMatcher ratio is low
# ---------------------------------------------------------------------------

def test_substring_title_merges(db):
    # Real-world case: High Noon ("Pert Near Sandstone") and Ticketmaster
    # ("Pert Near Sandstone-Side by Side Album Release & Road to Blue Ox Tour")
    # for the same show. SequenceMatcher.ratio is ~0.40 because the longer
    # title is much longer, but with identical start_at + venue_name the two
    # rows are clearly the same event and should be merged.
    short_title = "Pert Near Sandstone"
    long_title = "Pert Near Sandstone-Side by Side Album Release & Road to Blue Ox Tour"

    ingest_events("Source A", [_raw(title=short_title, source_name="Source A")], db)
    ingest_events(
        "Source B",
        [_raw(title=long_title, source_name="Source B", source_url="https://b.example/2")],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    # Reverse direction: long title first, short title second — also merges.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events("Source B", [_raw(title=long_title, source_name="Source B")], db)
    ingest_events(
        "Source A",
        [_raw(title=short_title, source_name="Source A", source_url="https://a.example/3")],
        db,
    )
    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2


def test_unrelated_titles_do_not_merge_via_substring(db):
    # Sanity check: two different events at the same time + venue must stay
    # separate even though no title contains the other. (e.g. distinct
    # support acts in opening slots are uncommon, but defensive coverage.)
    ingest_events("Source A", [_raw(title="Concert in the Park", source_name="Source A")], db)
    ingest_events(
        "Source B",
        [_raw(title="Totally Different Event", source_name="Source B", source_url="https://b.example/4")],
        db,
    )
    assert db.query(Event).count() == 2


def test_madison_city_suffix_normalize_merges(db):
    # Issue #187: Visit Madison appended " - Madison" to disambiguate a
    # touring act ("Anberlin - Madison"), while Atwood Music Hall used the
    # full bill ("Anberlin with Emery, Watashi Wa & Motion Light"). Neither
    # title is a substring of the other and SequenceMatcher.ratio is ~0.42,
    # well below the 0.65 threshold, so the two rows were ingested as
    # separate events despite identical start_at + venue_name. Stripping the
    # trailing city suffix from the matching key makes the shorter title a
    # substring of the longer.
    visit_madison_title = "Anberlin - Madison"
    atwood_title = "Anberlin with Emery, Watashi Wa & Motion Light"

    ingest_events(
        "Visit Madison",
        [_raw(title=visit_madison_title, venue_name="Atwood Music Hall")],
        db,
    )
    ingest_events(
        "Atwood Music Hall",
        [_raw(
            title=atwood_title,
            venue_name="Atwood Music Hall",
            source_url="https://www.theatwoodmusichall.com/shows/2026-5-20",
        )],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    # Reverse direction: venue scraper first, Visit Madison second — also merges.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events(
        "Atwood Music Hall",
        [_raw(title=atwood_title, venue_name="Atwood Music Hall")],
        db,
    )
    ingest_events(
        "Visit Madison",
        [_raw(
            title=visit_madison_title,
            venue_name="Atwood Music Hall",
            source_url="https://www.visitmadison.com/event/anberlin-madison/76278/",
        )],
        db,
    )
    assert db.query(Event).count() == 1


def test_ampersand_and_normalize_merges_substring(db):
    # Issue #191: Visit Madison shipped two listings for the same Karben4 trivia
    # night, "Brews & Q's Taproom Trivia at Karben4" and "Brews and Q's". The
    # fuzzy substring branch missed because the shorter title isn't literally
    # contained in the longer until " & " is normalized to " and ".
    long_title = "Brews & Q's Taproom Trivia at Karben4"
    short_title = "Brews and Q's"

    ingest_events(
        "Source A",
        [_raw(title=long_title, venue_name="Karben4 Brewing")],
        db,
    )
    ingest_events(
        "Source A",
        [_raw(
            title=short_title,
            venue_name="Karben4 Brewing",
            source_url="https://a.example/2",
        )],
        db,
    )

    assert db.query(Event).count() == 1
    # Reverse direction: short first, long second — also merges.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events(
        "Source A",
        [_raw(title=short_title, venue_name="Karben4 Brewing")],
        db,
    )
    ingest_events(
        "Source A",
        [_raw(
            title=long_title,
            venue_name="Karben4 Brewing",
            source_url="https://a.example/3",
        )],
        db,
    )
    assert db.query(Event).count() == 1


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


# ---------------------------------------------------------------------------
# 8. Canonical-venue address override (#115): a malformed address from an
#    aggregator is replaced with the canonical address regardless of fill-in-
#    nulls semantics, so the displayed address card and the geocoder both see
#    the clean string.
# ---------------------------------------------------------------------------

def test_canonical_venue_address_overrides_malformed_input_on_insert(db):
    bad = _raw(
        title="Pert Near Sandstone",
        venue_name="High Noon Saloon",
        venue_address="701A E Washington Ave, Madison, WI 53703",
        source_name="Visit Madison",
    )

    ingest_events("Visit Madison", [bad], db)

    event = db.query(Event).one()
    assert event.venue_address == "701 E Washington Ave, Madison, WI 53703"


def test_canonical_venue_address_corrected_on_subsequent_run(db):
    bad = _raw(
        title="Pert Near Sandstone",
        venue_name="High Noon Saloon",
        venue_address="701A E Washington Ave, Madison, WI 53703",
        source_name="Source A",
    )
    ingest_events("Source A", [bad], db)
    event = db.query(Event).one()
    assert event.venue_address == "701 E Washington Ave, Madison, WI 53703"

    # A second source confirming the same event keeps the canonical value
    # rather than falling back to its own address (also possibly off).
    other = _raw(
        title="Pert Near Sandstone",
        venue_name="High Noon Saloon",
        venue_address="701 East Washington Avenue, Madison, WI 53703",
        source_name="Source B",
        source_url="https://b.example/1",
    )
    ingest_events("Source B", [other], db)

    db.refresh(event)
    assert event.venue_address == "701 E Washington Ave, Madison, WI 53703"


def test_non_canonical_venue_address_is_left_untouched(db):
    raw = _raw(
        venue_name="Some Random Bar",
        venue_address="999 Fake Street, Madison, WI",
    )
    ingest_events("Source A", [raw], db)

    event = db.query(Event).one()
    assert event.venue_address == "999 Fake Street, Madison, WI"


# ---------------------------------------------------------------------------
# 9. Canonical-venue alias normalization for dedup (#215): sources that use
#    a verbose subtitle form of a venue name ("Aubergine: A Willy Street
#    Co-Op Community Space") must merge with sources that use the short form
#    ("Aubergine") because both normalize to the same canonical_name before
#    canonical_hash runs.
# ---------------------------------------------------------------------------

def test_venue_alias_normalizes_for_dedup(db):
    ingest_events(
        "Visit Madison",
        [_raw(title="Story Hour", venue_name="Aubergine: A Willy Street Co-Op Community Space")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(title="Story Hour", venue_name="Aubergine", source_url="https://isthmus.com/e/1")],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    event = db.query(Event).one()
    assert event.venue_name == "Aubergine"
    assert event.venue_address == "1226 Williamson St, Madison, WI 53703"


# ---------------------------------------------------------------------------
# 10. City-suffix venue alias normalization for dedup (#216): Isthmus ships
#     "Holy Wisdom Monastery, Middleton" (name + city) while Visit Madison
#     ships "Holy Wisdom Monastery"; the alias maps the city-suffixed form to
#     the bare name so both sources produce the same canonical_hash.
# ---------------------------------------------------------------------------

def test_city_suffix_venue_alias_normalizes_for_dedup(db):
    ingest_events(
        "Visit Madison",
        [_raw(title="Kids on the Prairie", venue_name="Holy Wisdom Monastery")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(
            title="Kids on the Prairie",
            venue_name="Holy Wisdom Monastery, Middleton",
            source_url="https://isthmus.com/e/1",
        )],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    event = db.query(Event).one()
    assert event.venue_name == "Holy Wisdom Monastery"
    assert event.venue_address == "4200 County Road M, Middleton, WI 53562"


# ---------------------------------------------------------------------------
# 9. Source-priority overwrite (#114): higher-trust source overwrites fields
#    set by a lower-trust source; lower-trust source cannot overwrite back.
# ---------------------------------------------------------------------------

def test_higher_priority_source_overwrites_description(db):
    # Visit Madison (rank 4, lowest trust) runs first with a thin description.
    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        description="Check out the event website for more information.",
    )
    ingest_events("Visit Madison", [vm_event], db)

    event = db.query(Event).one()
    assert event.description == "Check out the event website for more information."

    # High Noon (rank 0, highest trust) runs second with a richer description.
    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        description="Jackie Venson performs her soulful blend of blues and rock.",
    )
    ingest_events("High Noon Saloon", [hn_event], db)

    db.refresh(event)
    assert event.description == "Jackie Venson performs her soulful blend of blues and rock."


def test_lower_priority_source_does_not_overwrite(db):
    # High Noon (rank 0) runs first with a good description.
    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        description="Jackie Venson performs her soulful blend of blues and rock.",
    )
    ingest_events("High Noon Saloon", [hn_event], db)

    # Visit Madison (rank 4) runs second with a worse description — must not win.
    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        description="Check out the event website for more information.",
    )
    ingest_events("Visit Madison", [vm_event], db)

    event = db.query(Event).one()
    assert event.description == "Jackie Venson performs her soulful blend of blues and rock."


def test_higher_priority_source_overwrites_start_at(db):
    # Visit Madison (rank 4) runs first with a wrong time.
    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        start_at=datetime(2026, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
    )
    ingest_events("Visit Madison", [vm_event], db)

    # High Noon (rank 0) runs second with the right time — must overwrite.
    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        start_at=datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc),
    )
    ingest_events("High Noon Saloon", [hn_event], db)

    event = db.query(Event).one()
    assert event.start_at == datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc)


def test_higher_priority_none_end_at_clears_lower_priority_end_at(db):
    # start_at + end_at are a coupled pair: the end is anchored to the start.
    # If a higher-trust source overwrites start_at, its view of end_at — even
    # None — replaces the prior end, because the prior end belonged to the
    # now-discarded start.
    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        start_at=datetime(2026, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
    )
    vm_event.end_at = datetime(2026, 6, 15, 21, 0, 0, tzinfo=timezone.utc)
    ingest_events("Visit Madison", [vm_event], db)

    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        start_at=datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc),
    )
    # High Noon doesn't carry end_at — raw.end_at is None.
    assert hn_event.end_at is None
    ingest_events("High Noon Saloon", [hn_event], db)

    event = db.query(Event).one()
    assert event.start_at == datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc)
    # Visit Madison's 9 PM end is gone — it was anchored to the 8 PM start
    # that High Noon overrode.
    assert event.end_at is None


def test_same_source_re_run_clears_stale_end_at(db):
    # Atwood's prod-bug scenario: the first run wrote a placeholder end_at;
    # the scraper now correctly emits end_at=None when the start was sourced
    # from the description. The same-source re-run must clear the stale end.
    placeholder = _raw(start_at=datetime(2026, 7, 7, 20, 0, 0, tzinfo=timezone.utc))
    placeholder.end_at = datetime(2026, 7, 7, 21, 0, 0, tzinfo=timezone.utc)
    ingest_events("Source A", [placeholder], db)

    corrected = _raw(start_at=datetime(2026, 7, 7, 23, 0, 0, tzinfo=timezone.utc))
    assert corrected.end_at is None
    ingest_events("Source A", [corrected], db)

    event = db.query(Event).one()
    assert event.start_at == datetime(2026, 7, 7, 23, 0, 0, tzinfo=timezone.utc)
    assert event.end_at is None


def test_lower_priority_does_not_clear_end_at(db):
    # Symmetric counter-case: a lower-priority source's None end_at must NOT
    # clear a higher-priority source's set end_at. (Without this, every
    # Visit Madison run would nuke end_at fields populated by High Noon /
    # Ticketmaster on overlapping events.)
    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        start_at=datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc),
    )
    hn_event.end_at = datetime(2026, 6, 16, 1, 0, 0, tzinfo=timezone.utc)
    ingest_events("High Noon Saloon", [hn_event], db)

    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        start_at=datetime(2026, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
    )
    assert vm_event.end_at is None
    ingest_events("Visit Madison", [vm_event], db)

    event = db.query(Event).one()
    # High Noon's start + end remain authoritative.
    assert event.start_at == datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc)
    assert event.end_at == datetime(2026, 6, 16, 1, 0, 0, tzinfo=timezone.utc)


def test_lower_priority_source_does_not_overwrite_start_at(db):
    # High Noon (rank 0) runs first with the right time.
    hn_event = _raw(
        source_name="High Noon Saloon",
        source_url="https://highnoonsaloon.com/event/1",
        start_at=datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc),
    )
    ingest_events("High Noon Saloon", [hn_event], db)

    # Visit Madison (rank 4) runs second with a worse time — must not win.
    vm_event = _raw(
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/1",
        start_at=datetime(2026, 6, 15, 20, 0, 0, tzinfo=timezone.utc),
    )
    ingest_events("Visit Madison", [vm_event], db)

    event = db.query(Event).one()
    assert event.start_at == datetime(2026, 6, 15, 23, 0, 0, tzinfo=timezone.utc)
