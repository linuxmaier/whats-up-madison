import uuid
from datetime import datetime, timezone

from app.ingest import ingest_events, reconcile_duplicate_events
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
# 4c. Shared-stopword false merges (#246): a high character ratio is not enough
#     on its own. American Players Theatre runs several short-titled plays in
#     repertory in the same slot; "The Chairs" and "The Matchmaker" scored 0.667
#     purely on the shared "the " and silently collapsed into one event, which
#     is worse than a duplicate — the surviving row hides the other play.
# ---------------------------------------------------------------------------

def test_short_titles_sharing_only_an_article_do_not_merge(db):
    ingest_events(
        "Isthmus",
        [_raw(title="The Chairs", venue_name="American Players Theatre, Spring Green")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(
            title="The Matchmaker",
            venue_name="American Players Theatre, Spring Green",
            source_url="https://isthmus.com/events/the-matchmaker/",
        )],
        db,
    )
    assert db.query(Event).count() == 2

    # Reverse order — also stays separate.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events(
        "Isthmus",
        [_raw(title="The Matchmaker", venue_name="American Players Theatre, Spring Green")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(
            title="The Chairs",
            venue_name="American Players Theatre, Spring Green",
            source_url="https://isthmus.com/events/the-chairs/",
        )],
        db,
    )
    assert db.query(Event).count() == 2


def test_apt_repertory_slate_stays_distinct(db):
    # The full set of short-titled plays APT runs in the same slot.
    titles = [
        "The Chairs", "The Matchmaker", "Uncle Vanya", "Casey and Diana",
        "Sueño", "Dontrell, Who Kissed the Sea",
    ]
    for i, title in enumerate(titles):
        ingest_events(
            "Isthmus",
            [_raw(
                title=title,
                venue_name="American Players Theatre, Spring Green",
                source_url=f"https://isthmus.com/events/apt-{i}/",
            )],
            db,
        )
    assert db.query(Event).count() == len(titles)


def test_titles_sharing_a_real_word_still_merge(db):
    # The guard must not block merges backed by a meaningful shared word.
    for first, second in [
        ("Unity Picnic", "12th Annual Unity Picnic"),
        ("Parks Alive", "Parks Alive | Meadowood Park"),
        ("The Great Gatsby", "The Great Gatsby (Touring)"),
    ]:
        db.query(EventSource).delete()
        db.query(Event).delete()
        db.commit()
        ingest_events("Isthmus", [_raw(title=first, venue_name="Test Venue")], db)
        ingest_events(
            "Visit Madison",
            [_raw(title=second, venue_name="Test Venue", source_url="https://vm.example/1")],
            db,
        )
        assert db.query(Event).count() == 1, f"{first!r} should merge with {second!r}"


def test_accent_variants_still_merge(db):
    # Folding accents before tokenizing keeps "Sueno" compatible with "Sueño";
    # without it the guard would reject a 0.80-ratio pair for sharing no token.
    ingest_events("Isthmus", [_raw(title="Sueño", venue_name="Test Venue")], db)
    ingest_events(
        "Visit Madison",
        [_raw(title="Sueno", venue_name="Test Venue", source_url="https://vm.example/2")],
        db,
    )
    assert db.query(Event).count() == 1


# ---------------------------------------------------------------------------
# 4d. Headliner-segment match (#243). Cross-source duplicates routinely agree on
#     the act and disagree on everything after it — Isthmus lists the full bill,
#     Ticketmaster lists the tour. Those score 0.32-0.52, far below any threshold
#     it would be safe to set (#236 measured that lowering the bar far enough
#     also merges distinct APT plays). Each case below is a real production pair.
# ---------------------------------------------------------------------------

def _pair_merges(db, title_a, title_b, venue="The Sylvee"):
    """Ingest two titles at the same slot from different sources; count Events."""
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events("Isthmus", [_raw(title=title_a, venue_name=venue)], db)
    ingest_events(
        "Ticketmaster",
        [_raw(title=title_b, venue_name=venue, source_url="https://tm.example/1")],
        db,
    )
    return db.query(Event).count()


def test_headliner_match_merges_bill_vs_tour_listings(db):
    # Isthmus lists the support act, Ticketmaster lists the tour name. 0.51.
    assert _pair_merges(
        db, "Max McNown, Sam Burchfield", "Max McNown - The Summer Vacation Tour"
    ) == 1
    # Reverse order — source priority determines ingest order in production.
    assert _pair_merges(
        db, "Max McNown - The Summer Vacation Tour", "Max McNown, Sam Burchfield"
    ) == 1


def test_headliner_match_strips_a_status_prefix(db):
    # "SOLD OUT:" would otherwise become the headliner. 0.33.
    assert _pair_merges(
        db, "SOLD OUT: Big Thief", "Big Thief: Somersault Slide 360 Tour"
    ) == 1


def test_headliner_match_allows_prefix_containment(db):
    # Not equality — "bit brigade" is a prefix of "bit brigade performs ...". 0.39.
    assert _pair_merges(
        db,
        "Bit Brigade, Lords of the Trident",
        "Bit Brigade Performs “Mega Man X” LIVE",
        venue="Majestic Theatre",
    ) == 1


def test_headliner_match_merges_across_aggregators(db):
    # Isthmus vs Our Lives for the same Overture show. 0.41.
    assert _pair_merges(
        db,
        "Trevor: The Musical",
        "TREVOR: The story that inspired The Trevor Project",
        venue="Overture Center for the Arts",
    ) == 1


def test_headliner_match_merges_multi_act_bills(db):
    assert _pair_merges(
        db, "The Crane Wives, Brye", "The Crane Wives - ACT III With special guest Brye"
    ) == 1
    assert _pair_merges(
        db,
        "Shlump + Tiedye Ky",
        "Shlump, Tiedye Ky, C.A.M, Brainable, Debbie Check",
        venue="Majestic Theatre",
    ) == 1


def test_headliner_match_does_not_merge_distinct_events(db):
    # The negative set established by #236 and #246. A headliner match must not
    # reach any of these — it only ever ADDS merges, so a regression here would
    # mean the rule is too loose rather than too tight.
    for a, b, venue in [
        ("The Chairs", "The Matchmaker", "American Players Theatre, Spring Green"),
        ("Uncle Vanya", "Casey and Diana", "American Players Theatre, Spring Green"),
        ("Friday Open Stage", "First Friday Open Mic", "Madison Senior Center"),
        ("HASfit - Gentle Exercise", "Bridge Belles", "Madison Senior Center"),
        ("Concert in the Park", "Totally Different Event", "Garner Park"),
    ]:
        assert _pair_merges(db, a, b, venue=venue) == 2, f"{a!r} wrongly merged with {b!r}"


# ---------------------------------------------------------------------------
# 4e. No venue anchor (#258): with no venue, title similarity is the only
#     signal left, and a production sweep showed that's not enough.
#     "Waunakee Farmers' Market" and "Monroe Farmers' Market" — two different
#     real-world markets — cleared the #246 significant-token guard on the
#     shared words "farmers"/"market" and scored 0.78 with nothing left to
#     catch the mismatch, silently merging Waunakee's title onto Monroe's
#     venue and source URL. _find_fuzzy_duplicate now refuses to fuzzy-match
#     at all when the incoming side has no venue, mirroring the bail the
#     all-day path already had.
# ---------------------------------------------------------------------------

def test_no_venue_similar_titles_do_not_merge(db):
    # Real production pairs (#258) that shared a start_at and cleared
    # FUZZY_TITLE_THRESHOLD on title similarity alone, with no venue on
    # either side to catch the mismatch.
    for a, b in [
        ("Waunakee Farmers' Market", "Monroe Farmers' Market"),
        ("Capitol View Farmers' Market", "Verona Farmers' Market"),
        ("Shawano Folk Festival - Aug 7, 2026", "White Oak Folk Fest - Aug 7, 2026"),
        ("Art on Main - Aug 7, 2026", "Third Ward Moon Festival - Aug 7, 2026"),
        # Promoted to threshold by the #243 headliner rule on the shared
        # prefix "volunteer with" — the rule is meant for touring acts,
        # which always have a venue, not generic civic listings.
        ("Volunteer with Southern Wisconsin Bird Alliance", "Volunteer with Friends of Hoyt Park"),
    ]:
        assert _pair_merges(db, a, b, venue=None) == 2, f"{a!r} wrongly merged with {b!r}"


def test_no_venue_exact_title_still_does_not_merge(db):
    # The one production pair (#258) that plausibly should have merged —
    # a listing matching its own "CANCELED:"-prefixed re-post, both with no
    # venue — now also stays separate. This is an intentional trade-off: a
    # visible duplicate is safer than the alternative (#246), and it was
    # outweighed 10:1 by the false merges the venue requirement prevents.
    assert _pair_merges(
        db, "AtwoodFest - Jul 25, 2026", "CANCELED: AtwoodFest - Jul 25, 2026", venue=None,
    ) == 2


def test_reconcile_does_not_merge_no_venue_events(db):
    # The venue requirement applies to reconcile_duplicate_events too, since
    # it shares _find_fuzzy_duplicate with the insert path (#245) — the
    # production sweep that surfaced #258 walked existing rows exactly this
    # way.
    a = _make_event(db, title="Waunakee Farmers' Market", start_at=_dt())
    _make_source(db, a, "Isthmus")
    b = _make_event(db, title="Monroe Farmers' Market", start_at=_dt())
    _make_source(db, b, "Ticketmaster", source_url="https://tm.example/monroe")

    stats = reconcile_duplicate_events(db, dry_run=False)

    assert stats["merges"] == 0
    assert db.query(Event).filter_by(status="active").count() == 2


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

def test_wrong_date_row_self_heals_on_the_next_run(db):
    # The #244 scenario. Production held "First Friday Open Mic" on 2026-08-14
    # while the source lists Aug 7. The listing page and parser were both
    # correct — the row was stale, left behind because the Daily Scrape had been
    # disabled for a week. Once scraping resumes, the staleness sweep retires
    # the wrong-date row and the correct one ingests alongside it.
    wrong = _raw(
        title="First Friday Open Mic",
        start_at=datetime(2026, 8, 14, 15, 0, 0, tzinfo=timezone.utc),
        venue_name="Madison Senior Center",
        source_name="City of Madison",
    )
    ingest_events("City of Madison", [wrong], db)
    assert db.query(Event).filter_by(status="active").count() == 1

    # Next run: the source only returns the correct Aug 7 occurrence.
    corrected = _raw(
        title="First Friday Open Mic",
        start_at=datetime(2026, 8, 7, 15, 0, 0, tzinfo=timezone.utc),
        venue_name="Madison Senior Center",
        source_name="City of Madison",
    )
    ingest_events("City of Madison", [corrected], db)

    active = db.query(Event).filter_by(status="active").all()
    assert len(active) == 1
    assert active[0].start_at == datetime(2026, 8, 7, 15, 0, 0, tzinfo=timezone.utc)

    removed = db.query(Event).filter_by(status="removed").all()
    assert len(removed) == 1
    assert removed[0].start_at == datetime(2026, 8, 14, 15, 0, 0, tzinfo=timezone.utc)


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


def test_delta_beer_lab_fitchburg_address_corrected_on_insert(db):
    # Our Lives ships city="Madison" for Delta Beer Lab; the canonical registry
    # corrects it to Fitchburg (#229).
    raw = _raw(
        title="Pairs Jigsaw Puzzle Contest",
        venue_name="Delta Beer Lab",
        venue_address="167 E Badger Rd, Madison, WI 53713",
        source_name="Our Lives",
    )
    ingest_events("Our Lives", [raw], db)
    event = db.query(Event).one()
    assert event.venue_address == "167 E Badger Rd, Fitchburg, WI 53713"


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
# 10b. "The" prefix venue alias for Orpheum (#223): Visit Madison ships
#      "The Orpheum Theater" while Ticketmaster ships "Orpheum Theater".
#      The alias in canonical_venues normalizes the "The" form before hashing
#      so fuzzy dedup can find a venue match and merge the two events.
# ---------------------------------------------------------------------------

def test_orpheum_the_prefix_venue_alias_merges(db):
    vm_title = "Joe Jackson"
    tm_title = "Joe Jackson + Band - Hope and Fury Tour 2026"
    start = datetime(2026, 5, 22, 20, 0, 0, tzinfo=timezone.utc)

    ingest_events(
        "Visit Madison",
        [_raw(title=vm_title, venue_name="The Orpheum Theater", start_at=start)],
        db,
    )
    ingest_events(
        "Ticketmaster",
        [_raw(
            title=tm_title,
            venue_name="Orpheum Theater",
            start_at=start,
            source_url="https://www.ticketmaster.com/event/xyz",
        )],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    # Reverse direction: Ticketmaster first, Visit Madison second — also merges.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events(
        "Ticketmaster",
        [_raw(title=tm_title, venue_name="Orpheum Theater", start_at=start)],
        db,
    )
    ingest_events(
        "Visit Madison",
        [_raw(
            title=vm_title,
            venue_name="The Orpheum Theater",
            start_at=start,
            source_url="https://www.visitmadison.com/event/joe-jackson/74824/",
        )],
        db,
    )
    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2


# ---------------------------------------------------------------------------
# 10c. Generic venue normalization (#236): the venue anchor now compares
#      canonical_venues.match_key() rather than the raw string, so the
#      ", <City>" suffix Isthmus appends to out-of-town venues, "&"/"and",
#      a leading "The" and stray punctuation all stop blocking a merge.
#      Measured on 45 days of production data, venue-string variants accounted
#      for ~25 missed merges — more than the title threshold's 15.
# ---------------------------------------------------------------------------

def test_city_suffix_merges_without_a_registry_entry(db):
    # Isthmus ships "Hidden Cave Cidery, Middleton"; Our Lives ships the bare
    # name. Neither is in the canonical registry — the generic match key is
    # what collapses them.
    ingest_events(
        "Isthmus",
        [_raw(title="Cider Market", venue_name="Hidden Cave Cidery, Middleton")],
        db,
    )
    ingest_events(
        "Our Lives",
        [_raw(
            title="Cider Market",
            venue_name="Hidden Cave Cidery",
            source_url="https://ourlivesmadison.com/event/1",
        )],
        db,
    )

    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2

    # Reverse order — bare name first, city-suffixed second.
    db.query(EventSource).delete()
    db.query(Event).delete()
    db.commit()
    ingest_events(
        "Our Lives",
        [_raw(title="Cider Market", venue_name="Hidden Cave Cidery")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(
            title="Cider Market",
            venue_name="Hidden Cave Cidery, Middleton",
            source_url="https://isthmus.com/events/cider-market/",
        )],
        db,
    )
    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2


def test_venue_punctuation_and_ampersand_variants_merge(db):
    # City of Madison ships "Monona Terrace Community & Convention Center",
    # Visit Madison the spelled-out "and" form.
    ingest_events(
        "Visit Madison",
        [_raw(title="Rooftop Yoga", venue_name="Monona Terrace Community and Convention Center")],
        db,
    )
    ingest_events(
        "City of Madison",
        [_raw(
            title="Rooftop Yoga",
            venue_name="Monona Terrace Community & Convention Center",
            source_url="https://www.cityofmadison.com/events/rooftop-yoga",
        )],
        db,
    )
    assert db.query(Event).count() == 1
    assert db.query(EventSource).count() == 2


def test_source_venue_typo_merges_via_registry_alias(db):
    # The City of Madison feed misspells the park as "Meadoowood Park".
    ingest_events(
        "Isthmus",
        [_raw(title="Parks Alive", venue_name="Meadowood Park")],
        db,
    )
    ingest_events(
        "City of Madison",
        [_raw(
            title="Parks Alive",
            venue_name="Meadoowood Park",
            source_url="https://www.cityofmadison.com/events/parks-alive",
        )],
        db,
    )
    assert db.query(Event).count() == 1
    event = db.query(Event).one()
    assert event.venue_name == "Meadowood Park"


def test_same_venue_name_in_different_towns_stays_separate(db):
    # Buck and Honey's runs four locations under one name. The city suffix is
    # the ONLY thing distinguishing them, so it has to stay in the dedup key —
    # a chain promo with the same title on the same night must not collapse
    # four venues into one row.
    towns = ["Monona", "Mount Horeb", "Sun Prairie", "Waunakee"]
    for i, town in enumerate(towns):
        ingest_events(
            "Isthmus",
            [_raw(
                title="Trivia Night",
                venue_name=f"Buck and Honey's, {town}",
                source_url=f"https://isthmus.com/e/buck-{i}",
            )],
            db,
        )
    assert db.query(Event).count() == len(towns)


def test_same_brewery_different_towns_stay_separate(db):
    # Hop Garden runs taprooms in Belleville and Evansville. Stripping the city
    # suffix must not collapse two real venues into one.
    ingest_events(
        "Isthmus",
        [_raw(title="Live Music", venue_name="Hop Garden, Belleville")],
        db,
    )
    ingest_events(
        "Isthmus",
        [_raw(
            title="Live Music",
            venue_name="Hop Garden Brewing & Tap Room, Evansville",
            source_url="https://isthmus.com/events/live-music-evansville/",
        )],
        db,
    )
    assert db.query(Event).count() == 2


def test_identical_titles_at_different_venues_stay_separate(db):
    # Twenty bars run "Trivia" at 7pm on the same night. The time anchor is
    # shared, so only the venue key keeps them apart.
    venues = ["Cardinal Bar", "Echo Tap", "Java Cat", "Brass Ring, The", "Karben4 Brewing"]
    for i, v in enumerate(venues):
        ingest_events(
            "Isthmus",
            [_raw(title="Trivia", venue_name=v, source_url=f"https://isthmus.com/e/{i}")],
            db,
        )
    assert db.query(Event).count() == len(venues)


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


# ---------------------------------------------------------------------------
# 10. Self-rerun description clearing (#212): a top-priority source that now
#     emits description=None must clear its own stale description so lower-
#     priority sources can fill via null-fill semantics.
# ---------------------------------------------------------------------------

def test_self_rerun_at_top_clears_stale_description_when_none(db):
    # Regression for #212. Simulates Ticketmaster being ingested with boilerplate
    # before _choose_description existed, then re-scraped after the filter was added.
    boilerplate = (
        "Doors at 7:00 pm | Show at 8:00 pm CASHLESS VENUE - The Sylvee services "
        "all credit and debit payments only. No cash accepted."
    )
    raw_tm = _raw(source_name="Ticketmaster", description=boilerplate)
    ingest_events("Ticketmaster", [raw_tm], db)

    event = db.query(Event).one()
    assert event.description == boilerplate

    # TM re-scrapes after filter added — now emits description=None.
    raw_tm_rerun = _raw(source_name="Ticketmaster", description=None)
    ingest_events("Ticketmaster", [raw_tm_rerun], db)

    db.refresh(event)
    assert event.description is None


def test_lower_priority_fills_description_after_top_source_clears_it(db):
    # Regression for #212 (multi-source path). After TM clears its stale boilerplate
    # description to None, Visit Madison (lower priority) must be able to fill it
    # via null-fill semantics — demonstrating the full fix end-to-end.
    boilerplate = (
        "Doors at 7:00 pm | Show at 8:00 pm CASHLESS VENUE - The Sylvee services "
        "all credit and debit payments only. No cash accepted."
    )
    raw_tm = _raw(source_name="Ticketmaster", description=boilerplate)
    ingest_events("Ticketmaster", [raw_tm], db)

    # TM re-scrapes with no description (boilerplate filtered).
    raw_tm_rerun = _raw(source_name="Ticketmaster", description=None)
    ingest_events("Ticketmaster", [raw_tm_rerun], db)

    # Visit Madison fills the now-null description.
    vm_description = "Blending the punchy riffs of J-rock, the playfulness of indie rock."
    raw_vm = _raw(source_name="Visit Madison", description=vm_description)
    ingest_events("Visit Madison", [raw_vm], db)

    event = db.query(Event).one()
    assert event.description == vm_description


# ---------------------------------------------------------------------------
# 11. Alliant Energy Center placement (#155): Alliant's calendar carries no
#     event times (dates only), so it ranks lowest in SOURCE_PRIORITY to keep
#     time-bearing sources (Isthmus, Visit Madison) authoritative on shared
#     events. Confirms the placement decision in code: Alliant's all-day raw
#     does not clobber a higher-priority source's specific times, and its
#     end_at still fills via null-fill semantics.
# ---------------------------------------------------------------------------

def test_alliant_does_not_overwrite_visit_madison_times(db):
    vm_start = datetime(2026, 6, 13, 13, 0, 0, tzinfo=timezone.utc)
    vm_end = datetime(2026, 6, 13, 16, 0, 0, tzinfo=timezone.utc)
    vm = _raw(
        title="Bubble Run – Madison",
        venue_name="Alliant Energy Center",
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/bubble-run/1",
        start_at=vm_start,
        description="Visit Madison's 1000-char curated blurb.",
    )
    vm.end_at = vm_end
    ingest_events("Visit Madison", [vm], db)

    # Alliant later ingests the same event (matched via canonical_hash on
    # title+date+venue) with all-day midnight values and a different title.
    alliant_start = datetime(2026, 6, 13, 5, 0, 0, tzinfo=timezone.utc)  # midnight Central
    alliant_end = datetime(2026, 6, 14, 4, 59, 59, tzinfo=timezone.utc)  # end-of-day Central
    alliant = _raw(
        title="Bubble Run – Madison",
        venue_name="Alliant Energy Center",
        source_name="Alliant Energy Center",
        source_url="https://www.alliantenergycenter.com/upcoming-events/events-details/123/bubble-run",
        start_at=alliant_start,
        all_day=True,
        description="Alliant's first-party blurb plus parking info.",
    )
    alliant.end_at = alliant_end
    ingest_events("Alliant Energy Center", [alliant], db)

    assert db.query(Event).count() == 1
    event = db.query(Event).one()
    # Visit Madison's start/end times survive.
    assert event.start_at == vm_start
    assert event.end_at == vm_end
    # Visit Madison's description and title survive.
    assert event.description == "Visit Madison's 1000-char curated blurb."
    # Both sources are attached.
    source_names = {s.source_name for s in db.query(EventSource).all()}
    assert source_names == {"Visit Madison", "Alliant Energy Center"}


def test_alliant_fills_null_end_at_on_visit_madison_event(db):
    # Brat Fest pattern: Visit Madison ships start_at with no end_at; Alliant
    # supplies the multi-day end_at, which the null-fill rule applies even
    # for a lower-priority source.
    vm_start = datetime(2026, 5, 22, 5, 0, 0, tzinfo=timezone.utc)
    vm = _raw(
        title="World's Largest Brat Fest",
        venue_name="Alliant Energy Center",
        source_name="Visit Madison",
        source_url="https://visitmadison.com/event/worlds-largest-brat-fest/1",
        start_at=vm_start,
        all_day=True,
    )
    assert vm.end_at is None
    ingest_events("Visit Madison", [vm], db)

    event_before = db.query(Event).one()
    assert event_before.end_at is None

    alliant_end = datetime(2026, 5, 25, 4, 59, 59, tzinfo=timezone.utc)
    alliant = _raw(
        title="World's Largest Brat Fest",
        venue_name="Alliant Energy Center",
        source_name="Alliant Energy Center",
        source_url="https://www.alliantenergycenter.com/upcoming-events/events-details/971/brat-fest-2026",
        start_at=vm_start,
        all_day=True,
    )
    alliant.end_at = alliant_end
    ingest_events("Alliant Energy Center", [alliant], db)

    event = db.query(Event).one()
    # Visit Madison's start_at + title untouched, but the null end_at fills.
    assert event.start_at == vm_start
    assert event.end_at == alliant_end
    source_names = {s.source_name for s in db.query(EventSource).all()}
    assert source_names == {"Visit Madison", "Alliant Energy Center"}


def test_alliant_subroom_alias_normalizes_for_dedup(db):
    # Isthmus's Bridal Expo lists venue_name="Alliant Energy Center-Exhibition Hall"
    # while Alliant's own scraper lists venue_name="Alliant Energy Center".
    # The canonical-venue alias maps the compound to the base before hashing
    # so the two rows merge into one Event.
    isthmus_start = datetime(2026, 5, 17, 18, 0, 0, tzinfo=timezone.utc)
    isthmus = _raw(
        title="Bridal & Wedding Expo",
        venue_name="Alliant Energy Center-Exhibition Hall",
        source_name="Isthmus",
        source_url="https://isthmus.com/events/bridal-wedding-expo/",
        start_at=isthmus_start,
    )
    ingest_events("Isthmus", [isthmus], db)

    alliant_start = datetime(2026, 5, 17, 5, 0, 0, tzinfo=timezone.utc)
    alliant = _raw(
        title="Wisconsin Bridal and Wedding Expo",
        venue_name="Alliant Energy Center",
        source_name="Alliant Energy Center",
        source_url="https://www.alliantenergycenter.com/upcoming-events/events-details/964/",
        start_at=alliant_start,
        all_day=True,
    )
    ingest_events("Alliant Energy Center", [alliant], db)

    # Both rows collapse into one Event via the canonical-venue alias.
    assert db.query(Event).count() == 1
    event = db.query(Event).one()
    # venue_name is canonicalized to the building name.
    assert event.venue_name == "Alliant Energy Center"
    # Both sources are attached.
    source_names = {s.source_name for s in db.query(EventSource).all()}
    assert source_names == {"Isthmus", "Alliant Energy Center"}


# ---------------------------------------------------------------------------
# 31. Reconciling pre-existing duplicate rows (#245)
#
# ingest_events() already prevents two live rows for the same event from
# being created going forward, so these tests build the "already duplicated"
# state directly — two Event rows + their EventSource rows — mirroring what
# production actually looked like (the Great Gatsby / Overture Center pair
# from #245: same start_at + venue, substring titles, created minutes apart
# under code that has since been fixed, but never re-checked against each
# other since).
# ---------------------------------------------------------------------------

def _make_event(
    db,
    *,
    title,
    start_at,
    venue_name=None,
    description=None,
    venue_address=None,
    categories=None,
    all_day=False,
    created_at=None,
    status="active",
) -> Event:
    event = Event(
        title=title,
        description=description,
        start_at=start_at,
        venue_name=venue_name,
        venue_address=venue_address,
        categories=categories or [],
        all_day=all_day,
        canonical_hash=uuid.uuid4().hex,
        status=status,
    )
    if created_at is not None:
        event.created_at = created_at
    db.add(event)
    db.flush()
    return event


def _make_source(
    db, event, source_name, *, source_url=None, is_active=True, last_seen_at=None
) -> EventSource:
    source = EventSource(
        event_id=event.id,
        source_name=source_name,
        source_url=source_url or f"https://example.com/{source_name.lower().replace(' ', '-')}",
        last_seen_at=last_seen_at or _dt(),
        is_active=is_active,
    )
    db.add(source)
    db.flush()
    return source


def test_reconcile_dry_run_reports_without_writing(db):
    a = _make_event(
        db, title="The Great Gatsby", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 41, tzinfo=timezone.utc),
    )
    _make_source(db, a, "Isthmus")
    _make_source(db, a, "Visit Madison")

    b = _make_event(
        db, title="The Great Gatsby (Touring)", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 33, tzinfo=timezone.utc),
    )
    _make_source(db, b, "Ticketmaster")
    db.commit()  # mimic already-persisted rows from an earlier scrape run

    stats = reconcile_duplicate_events(db, dry_run=True)

    assert stats["merges"] == 1
    assert stats["dry_run"] is True
    # Nothing committed — both rows are still active, independently sourced.
    assert db.query(Event).filter(Event.status == "active").count() == 2
    assert db.query(EventSource).count() == 3


def test_reconcile_merges_duplicate_pair_with_different_sources(db):
    a = _make_event(
        db, title="The Great Gatsby", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 41, tzinfo=timezone.utc),
    )
    _make_source(db, a, "Isthmus")
    _make_source(db, a, "Visit Madison")

    b = _make_event(
        db, title="The Great Gatsby (Touring)", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 33, tzinfo=timezone.utc),
    )
    _make_source(db, b, "Ticketmaster")

    stats = reconcile_duplicate_events(db, dry_run=False)
    assert stats["merges"] == 1

    active = db.query(Event).filter(Event.status == "active").all()
    assert len(active) == 1
    survivor = active[0]
    active_sources = db.query(EventSource).filter_by(event_id=survivor.id, is_active=True).all()
    assert {s.source_name for s in active_sources} == {"Isthmus", "Visit Madison", "Ticketmaster"}

    removed = db.query(Event).filter(Event.status == "removed").one()
    assert db.query(EventSource).filter_by(event_id=removed.id).count() == 0


def test_reconcile_handles_overlapping_source_on_both_sides(db):
    # Both rows carry an Isthmus link (the actual shape of the #245 Great
    # Gatsby pair) — merging must not violate the (event_id, source_name)
    # unique constraint, and the fresher/active reading should survive.
    a = _make_event(
        db, title="The Great Gatsby", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 41, tzinfo=timezone.utc),
    )
    _make_source(db, a, "Isthmus", is_active=True, last_seen_at=datetime(2026, 7, 25, 20, 37, tzinfo=timezone.utc))
    _make_source(db, a, "Visit Madison")

    b = _make_event(
        db, title="The Great Gatsby (Touring)", start_at=_dt(), venue_name="Overture Center for the Arts",
        created_at=datetime(2026, 6, 28, 13, 33, tzinfo=timezone.utc),
    )
    _make_source(
        db, b, "Isthmus", is_active=False,
        last_seen_at=datetime(2026, 6, 28, 13, 33, tzinfo=timezone.utc),
        source_url="https://isthmus.com/events/stale-occurrence/",
    )
    _make_source(db, b, "Ticketmaster")

    stats = reconcile_duplicate_events(db, dry_run=False)
    assert stats["merges"] == 1

    survivor = db.query(Event).filter(Event.status == "active").one()
    isthmus_rows = db.query(EventSource).filter_by(event_id=survivor.id, source_name="Isthmus").all()
    assert len(isthmus_rows) == 1
    assert isthmus_rows[0].is_active is True

    all_names = {s.source_name for s in db.query(EventSource).filter_by(event_id=survivor.id).all()}
    assert all_names == {"Isthmus", "Visit Madison", "Ticketmaster"}


def test_reconcile_leaves_distinct_events_alone(db):
    # Reuses the #246 shape: two different APT plays sharing only "the ".
    a = _make_event(
        db, title="The Chairs", start_at=_dt(), venue_name="American Players Theatre, Spring Green",
        created_at=datetime(2026, 6, 25, tzinfo=timezone.utc),
    )
    _make_source(db, a, "Isthmus")

    b = _make_event(
        db, title="The Matchmaker", start_at=_dt(), venue_name="American Players Theatre, Spring Green",
        created_at=datetime(2026, 6, 26, tzinfo=timezone.utc),
    )
    _make_source(db, b, "Isthmus", source_url="https://isthmus.com/events/the-matchmaker/")

    stats = reconcile_duplicate_events(db, dry_run=False)

    assert stats["merges"] == 0
    assert db.query(Event).filter(Event.status == "active").count() == 2


def test_reconcile_null_fills_survivor_and_unions_categories(db):
    winner = _make_event(
        db, title="Trivia Night", start_at=_dt(), venue_name="Test Venue",
        categories=["Nightlife"],
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    _make_source(db, winner, "Ticketmaster")  # rank 3 — higher trust than Isthmus

    loser = _make_event(
        db, title="Trivia Nights", start_at=_dt(), venue_name="Test Venue",
        description="Weekly trivia at the bar.", venue_address="123 Main St",
        categories=["Community"],
        created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )
    _make_source(db, loser, "Isthmus", source_url="https://isthmus.com/events/trivia-night/")

    stats = reconcile_duplicate_events(db, dry_run=False)
    assert stats["merges"] == 1

    survivor = db.query(Event).filter(Event.status == "active").one()
    # Winner's own non-null fields are untouched; nulls are filled from the loser.
    assert survivor.title == "Trivia Night"
    assert survivor.description == "Weekly trivia at the bar."
    assert survivor.venue_address == "123 Main St"
    assert set(survivor.categories) == {"Nightlife", "Community"}


def test_reconcile_is_idempotent(db):
    a = _make_event(
        db, title="Trivia Night", start_at=_dt(), venue_name="Test Venue",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    _make_source(db, a, "Isthmus")

    b = _make_event(
        db, title="Trivia Nights", start_at=_dt(), venue_name="Test Venue",
        created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )
    _make_source(db, b, "Visit Madison", source_url="https://visitmadison.com/event/trivia-night/")

    first = reconcile_duplicate_events(db, dry_run=False)
    assert first["merges"] == 1

    second = reconcile_duplicate_events(db, dry_run=False)
    assert second["merges"] == 0
