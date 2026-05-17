"""Unit tests for ticketmaster.py parsing helpers."""
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.scrapers.ticketmaster import (
    _CENTRAL,
    _build_address,
    _choose_description,
    _map_categories,
    _parse_event,
    _select_image,
)


# Literal venue boilerplate copy harvested from the Discovery API responses
# that drove audit issues #177 (Rebirth Brass Band) and #178 (Highly Suspect).
# Asserting these collapse to ``None`` is the regression for both findings.
_SYLVEE_BOILERPLATE = (
    "Doors at 6:00 pm | Show at 7:30 pm CASHLESS VENUE - The Sylvee services all credit "
    "and debit payments only. No cash accepted. Bags (max size 12\" x 6\" x 12\") are "
    "allowed and will be searched upon entry. Exceptions will be made for necessary "
    "medical equipment and bags for nursing mothers. We encourage you to pack light "
    "with only the necessities to make the entry process as smooth as possible. All "
    "General Admission Tickets are good for the standing General Admission Floor and "
    "GA Balcony areas on a first come first serve basis. Accessible Seating: "
    "Accessible seating is available online through Ticketmaster by filtering on the "
    "ADA Icon and selecting the Accessible Seats, or in person at The Sylvee Box "
    "Office during business hours. For additional information call 608-709-8157."
)
_MAJESTIC_BOILERPLATE = (  # literal info field on the Rebirth Brass Band event (#177)
    "Doors at 7:00 pm | Show at 8:00 pm CASHLESS VENUE - The Majestic Theatre services "
    "all credit and debit payments only. No cash accepted. Bags (max size 12\" x 6\" x "
    "12\") are allowed and will be searched upon entry. Exceptions will be made for "
    "necessary medical equipment and bags for nursing mothers. We encourage you to "
    "pack light with only the necessities to make the entry process as smooth as "
    "possible. All tickets are standing and seated General Admission and are available "
    "on a first come first serve basis. The Opera Boxes are only accessible by stairs. "
    "Advance tickets can be purchased online or at The Sylvee box office. Once the "
    "doors have opened, if tickets are still available, they can be purchased at the "
    "Majestic Theatre."
)
# pleaseNote variants — TM ships these in parallel with info, with slightly
# different wording ("Doors open at 6:00 pm." vs "Doors at 6:00 pm | Show at 7:30 pm",
# "Once the event has started" vs "Once the doors have opened"). Both must scrub.
_SYLVEE_PLEASE_NOTE = (
    "Doors open at 6:00 pm. CASHLESS VENUE - The Sylvee services all credit and debit "
    "payments only. No cash accepted. Bags (max size 12\" x 6\" x 12\") are allowed and "
    "will be searched upon entry. Exceptions will be made for necessary medical "
    "equipment and bags for nursing mothers. We encourage you to pack light with only "
    "the necessities to make the entry process as smooth as possible. Tickets can be "
    "purchased online up to the event start time. Once the event has started, if "
    "tickets are still available, they can be purchased at the Sylvee box office."
)
_BARRYMORE_BOILERPLATE = (
    "Doors at 7:00 pm | Show at 8:00 pm There are no elevators in the theatre. "
    "Advance tickets can be purchased online or at The Sylvee box office. Once the "
    "doors have opened, if tickets are still available, they can be purchased at the "
    "venue."
)
_BARRYMORE_LOWERCASE_THEATER = (  # the feed has both "theatre" and "theater" spellings
    "Doors at 7:00 pm | Show at 8:00 pm There are no elevators in the theater. "
    "Advance tickets can be purchased online or at The Sylvee box office."
)
_RENT_REAL_DESCRIPTION = (
    "This season, we proudly celebrate the 30th anniversary of RENT, the groundbreaking "
    "musical that redefined Broadway and continues to inspire audiences worldwide. "
    "Capital City Theatre is thrilled to present a fresh staging of Jonathan Larson's "
    "iconic work."
)


def _venue(line1="25 S. Livingston Street", city="Madison", state="WI", zipc="53703"):
    out: dict = {"name": "The Sylvee"}
    if line1 is not None:
        out["address"] = {"line1": line1}
    if city is not None:
        out["city"] = {"name": city}
    if state is not None:
        out["state"] = {"stateCode": state}
    if zipc is not None:
        out["postalCode"] = zipc
    return out


def _doc(
    *,
    name="Modest Mouse",
    url="https://www.ticketmaster.com/modest-mouse/event/abc",
    local_date="2026-09-29",
    local_time="20:00:00",
    span_multi_days=False,
    end_date=None,
    end_time=None,
    status="onsale",
    timezone="America/Chicago",
    info=(
        "Modest Mouse return with their first headline tour in support of the band's "
        "ninth studio album, joined by a rotating lineup of special guests across the "
        "summer of 2026."
    ),
    please_note=None,
    venue=None,
    images=None,
    classifications=None,
    time_tba=False,
    no_specific_time=False,
):
    if venue is None:
        venue = _venue()
    start: dict = {"localDate": local_date}
    if local_time is not None:
        start["localTime"] = local_time
    if time_tba:
        start["timeTBA"] = True
    if no_specific_time:
        start["noSpecificTime"] = True
    dates: dict = {
        "start": start,
        "timezone": timezone,
        "spanMultipleDays": span_multi_days,
        "status": {"code": status},
    }
    if end_date or end_time:
        end: dict = {}
        if end_date:
            end["localDate"] = end_date
        if end_time:
            end["localTime"] = end_time
        dates["end"] = end
    doc: dict = {
        "name": name,
        "url": url,
        "dates": dates,
        "_embedded": {"venues": [venue]},
    }
    if info is not None:
        doc["info"] = info
    if please_note is not None:
        doc["pleaseNote"] = please_note
    if images is not None:
        doc["images"] = images
    if classifications is not None:
        doc["classifications"] = classifications
    return doc


def _cls(segment, genre=None, primary=True):
    out: dict = {"primary": primary, "segment": {"name": segment}}
    if genre is not None:
        out["genre"] = {"name": genre}
    return out


# ---------------------------------------------------------------------------
# _build_address
# ---------------------------------------------------------------------------

class TestBuildAddress:
    def test_full_address(self):
        assert _build_address(_venue()) == "25 S. Livingston Street, Madison, WI 53703"

    def test_missing_zip(self):
        assert _build_address(_venue(zipc="")) == "25 S. Livingston Street, Madison, WI"

    def test_missing_city(self):
        assert _build_address(_venue(city="")) == "25 S. Livingston Street, WI 53703"

    def test_missing_state(self):
        assert _build_address(_venue(state="")) == "25 S. Livingston Street, Madison, 53703"

    def test_only_line1(self):
        v = {"address": {"line1": "100 Main St"}}
        assert _build_address(v) == "100 Main St"

    def test_empty_returns_none(self):
        assert _build_address({}) is None


# ---------------------------------------------------------------------------
# _select_image
# ---------------------------------------------------------------------------

class TestSelectImage:
    def test_picks_largest_16_9(self):
        images = [
            {"ratio": "16_9", "url": "small.jpg", "width": 205},
            {"ratio": "16_9", "url": "large.jpg", "width": 1136},
            {"ratio": "3_2", "url": "wrong-ratio.jpg", "width": 2000},
        ]
        assert _select_image(images) == "large.jpg"

    def test_falls_back_to_first_when_no_16_9(self):
        images = [
            {"ratio": "3_2", "url": "fallback.jpg", "width": 305},
        ]
        assert _select_image(images) == "fallback.jpg"

    def test_skips_entries_without_url(self):
        images = [
            {"ratio": "16_9", "width": 1136},  # no url
            {"ratio": "16_9", "url": "ok.jpg", "width": 640},
        ]
        assert _select_image(images) == "ok.jpg"

    def test_empty(self):
        assert _select_image([]) is None


# ---------------------------------------------------------------------------
# _map_categories
# ---------------------------------------------------------------------------

class TestMapCategories:
    def test_music_rock_to_music(self):
        assert _map_categories([_cls("Music", "Rock")]) == ["Music"]

    def test_music_jazz_to_music(self):
        assert _map_categories([_cls("Music", "Jazz")]) == ["Music"]

    def test_music_no_genre_to_music(self):
        assert _map_categories([_cls("Music")]) == ["Music"]

    def test_arts_theatre_comedy_to_open_mic_and_comedy(self):
        assert _map_categories([_cls("Arts & Theatre", "Comedy")]) == ["Open Mic & Comedy"]

    def test_arts_theatre_theatre_to_theater_and_stage(self):
        assert _map_categories([_cls("Arts & Theatre", "Theatre")]) == ["Theater & Stage"]

    def test_arts_theatre_childrens_to_theater_and_stage(self):
        assert _map_categories([_cls("Arts & Theatre", "Children's Theatre")]) == ["Theater & Stage"]

    def test_arts_theatre_dance_to_theater_and_stage(self):
        # TM "Dance" under Arts & Theatre is ballet/contemporary performance, not
        # social dance — keep it under Theater & Stage to match our taxonomy intent.
        assert _map_categories([_cls("Arts & Theatre", "Dance")]) == ["Theater & Stage"]

    def test_sports_football_to_sports_and_recreation(self):
        assert _map_categories([_cls("Sports", "Football")]) == ["Sports & Recreation"]

    def test_family_to_family_and_kids(self):
        assert _map_categories([_cls("Family", "Children's Music")]) == ["Family & Kids"]

    def test_arts_theatre_miscellaneous_dropped(self):
        assert _map_categories([_cls("Arts & Theatre", "Miscellaneous")]) == []

    def test_undefined_segment_dropped(self):
        assert _map_categories([_cls("Undefined")]) == []

    def test_miscellaneous_segment_dropped(self):
        assert _map_categories([_cls("Miscellaneous", "Undefined")]) == []

    def test_non_primary_classification_ignored(self):
        # Only the primary classification is consulted.
        non_primary = _cls("Music", "Rock", primary=False)
        secondary = _cls("Sports", "Football", primary=True)
        assert _map_categories([non_primary, secondary]) == ["Sports & Recreation"]

    def test_no_primary_returns_empty(self):
        non_primary = _cls("Music", "Rock", primary=False)
        assert _map_categories([non_primary]) == []

    def test_empty(self):
        assert _map_categories([]) == []


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------

class TestParseEvent:
    def test_full_happy_path(self):
        ev = _parse_event(_doc(
            classifications=[_cls("Music", "Rock")],
            images=[
                {"ratio": "16_9", "url": "https://img/large.jpg", "width": 1136},
                {"ratio": "3_2", "url": "https://img/wrong.jpg", "width": 2000},
            ],
        ))
        assert ev is not None
        assert ev.title == "Modest Mouse"
        assert ev.start_at == datetime(2026, 9, 29, 20, 0, tzinfo=ZoneInfo("America/Chicago"))
        assert ev.end_at is None
        assert ev.all_day is False
        assert ev.venue_name == "The Sylvee"
        assert ev.venue_address == "25 S. Livingston Street, Madison, WI 53703"
        assert ev.description is not None
        assert ev.description.startswith("Modest Mouse return")
        assert ev.image_url == "https://img/large.jpg"
        assert ev.categories == ["Music"]
        assert ev.source_name == "Ticketmaster"
        assert ev.source_url == "https://www.ticketmaster.com/modest-mouse/event/abc"

    def test_cancelled_returns_none(self):
        assert _parse_event(_doc(status="cancelled")) is None

    def test_postponed_returns_none(self):
        assert _parse_event(_doc(status="postponed")) is None

    def test_offsale_status_kept(self):
        # offsale just means tickets aren't on sale at the moment; event is still happening.
        assert _parse_event(_doc(status="offsale")) is not None

    def test_rescheduled_status_kept(self):
        assert _parse_event(_doc(status="rescheduled")) is not None

    def test_missing_local_time_falls_back_to_all_day(self):
        ev = _parse_event(_doc(local_time=None))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 9, 29, 0, 0, tzinfo=ZoneInfo("America/Chicago"))

    def test_time_tba_treated_as_all_day(self):
        ev = _parse_event(_doc(local_time="20:00:00", time_tba=True))
        assert ev is not None
        assert ev.all_day is True

    def test_no_specific_time_treated_as_all_day(self):
        ev = _parse_event(_doc(local_time="20:00:00", no_specific_time=True))
        assert ev is not None
        assert ev.all_day is True

    def test_span_multi_days_populates_end_at(self):
        ev = _parse_event(_doc(
            local_date="2026-09-29",
            local_time="10:00:00",
            span_multi_days=True,
            end_date="2026-10-01",
            end_time="22:00:00",
        ))
        assert ev is not None
        assert ev.start_at == datetime(2026, 9, 29, 10, 0, tzinfo=ZoneInfo("America/Chicago"))
        assert ev.end_at == datetime(2026, 10, 1, 22, 0, tzinfo=ZoneInfo("America/Chicago"))

    def test_single_day_span_ignored(self):
        # spanMultipleDays=False even with end block → end_at should be None.
        ev = _parse_event(_doc(
            span_multi_days=False,
            end_date="2026-09-29",
            end_time="23:00:00",
        ))
        assert ev is not None
        assert ev.end_at is None

    def test_missing_local_date_returns_none(self):
        assert _parse_event(_doc(local_date=None)) is None

    def test_missing_title_returns_none(self):
        assert _parse_event(_doc(name="")) is None

    def test_missing_url_returns_none(self):
        assert _parse_event(_doc(url="")) is None

    def test_api_url_used_directly_when_event_id_present(self):
        # Regression for #206: slug URLs constructed from metadata 404 because
        # TM's internal slug generation can't be replicated exactly. Use the
        # URL the Discovery API returns for the event instead.
        api_url = "https://www.ticketmaster.com/foo-madison-wi-01-01-2026/event/ABC123"
        doc = _doc(url=api_url)
        doc["id"] = "ABC123"
        ev = _parse_event(doc)
        assert ev is not None
        assert ev.source_url == api_url

    def test_fallback_to_short_event_url_when_api_url_missing(self):
        # When the url field is absent but id is present, fall back to the
        # bare /event/<id> URL rather than dropping the event entirely.
        doc = _doc(url="")
        doc["id"] = "ABC123"
        ev = _parse_event(doc)
        assert ev is not None
        assert ev.source_url == "https://www.ticketmaster.com/event/ABC123"

    def test_missing_venue_returns_none(self):
        doc = _doc()
        doc["_embedded"] = {"venues": []}
        assert _parse_event(doc) is None

    def test_description_falls_back_to_please_note(self):
        # info absent → fall back to pleaseNote when it carries real signal.
        ev = _parse_event(_doc(
            info=None,
            please_note=(
                "Free meet-and-greet with the artist runs in the lobby from 7-7:45pm "
                "for VIP ticket holders only."
            ),
        ))
        assert ev is not None
        assert ev.description is not None
        assert ev.description.startswith("Free meet-and-greet")

    def test_description_none_when_please_note_is_boilerplate(self):
        # Both fields populated but pleaseNote is venue boilerplate → no description.
        ev = _parse_event(_doc(info=None, please_note=_SYLVEE_BOILERPLATE))
        assert ev is not None
        assert ev.description is None

    def test_description_none_when_both_missing(self):
        ev = _parse_event(_doc(info=None, please_note=None))
        assert ev is not None
        assert ev.description is None

    def test_description_none_when_info_is_venue_boilerplate(self):
        # Regression for #178 (Highly Suspect at The Sylvee).
        ev = _parse_event(_doc(info=_SYLVEE_BOILERPLATE, please_note=None))
        assert ev is not None
        assert ev.description is None

    def test_zoneinfo_central_matches(self):
        # Sanity check that the module uses the expected zone.
        assert _CENTRAL == ZoneInfo("America/Chicago")
        # And that the parser uses the timezone field from dates.
        ev = _parse_event(_doc(timezone="America/Chicago"))
        assert ev.start_at.tzinfo is not None
        assert ev.start_at.utcoffset() in {
            ZoneInfo("America/Chicago").utcoffset(datetime(2026, 9, 29, 20, 0)),
        }

    def test_dst_summer_offset(self):
        # July → CDT (UTC-5)
        ev = _parse_event(_doc(local_date="2026-07-04", local_time="20:00:00"))
        assert ev.start_at.utcoffset().total_seconds() == -5 * 3600

    def test_dst_winter_offset(self):
        # December → CST (UTC-6)
        ev = _parse_event(_doc(local_date="2026-12-15", local_time="20:00:00"))
        assert ev.start_at.utcoffset().total_seconds() == -6 * 3600

    def test_end_at_defaults_to_end_of_day_when_end_time_missing(self):
        ev = _parse_event(_doc(
            span_multi_days=True,
            end_date="2026-10-01",
            end_time=None,
        ))
        assert ev is not None
        assert ev.end_at is not None
        assert ev.end_at.date().isoformat() == "2026-10-01"
        assert ev.end_at.time() == dtime.max


# ---------------------------------------------------------------------------
# _choose_description
# ---------------------------------------------------------------------------

class TestChooseDescription:
    """Gating logic for the description field.

    TM ships per-venue policy boilerplate in info/pleaseNote; the helper
    must surface real event copy and drop pure boilerplate so audit issues
    #177 and #178 don't recur.
    """

    def test_pure_sylvee_boilerplate_returns_none(self):
        # Regression for #178.
        assert _choose_description(_SYLVEE_BOILERPLATE, None) is None

    def test_pure_majestic_boilerplate_returns_none(self):
        # Regression for #177.
        assert _choose_description(_MAJESTIC_BOILERPLATE, None) is None

    def test_pure_barrymore_boilerplate_returns_none(self):
        assert _choose_description(_BARRYMORE_BOILERPLATE, None) is None

    def test_barrymore_lowercase_theater_spelling_returns_none(self):
        # The feed has both "theatre" and "theater" — must scrub both.
        assert _choose_description(_BARRYMORE_LOWERCASE_THEATER, None) is None

    def test_sylvee_please_note_variant_returns_none(self):
        # The other observed regression: pleaseNote ships the same boilerplate
        # with different wording ("Doors open at" / "Once the event has started").
        assert _choose_description(None, _SYLVEE_PLEASE_NOTE) is None

    def test_orpheum_tiered_ga_boilerplate_returns_none(self):
        # Observed on Orpheum events that ship the tiered-GA-pricing block.
        tiered = (
            "Doors at 7:00 pm | Show at 8:00 pm A tiered system is in place for "
            "General Admission tickets. This allows us to reward the most loyal fans "
            "who buy early by giving them access to the lowest priced tickets. Prices "
            "will increase as each tier sells out. Every General Admission ticket "
            "(regardless of tier) will have the same access and benefits at the show."
        )
        assert _choose_description(tiered, None) is None

    def test_empty_inputs_return_none(self):
        assert _choose_description(None, None) is None
        assert _choose_description("", "") is None
        assert _choose_description("   ", "\n\t") is None

    def test_real_event_description_kept_verbatim(self):
        assert _choose_description(_RENT_REAL_DESCRIPTION, None) == _RENT_REAL_DESCRIPTION

    def test_cancellation_placeholder_dropped(self):
        # TM occasionally swaps the info field on cancelled events for this
        # boilerplate placeholder. Drop it so we don't render it as a description.
        assert _choose_description(
            "Unfortunately, the Event Organizer has had to cancel your event.",
            None,
        ) is None

    def test_doortime_prefix_with_real_copy_preserved_verbatim(self):
        # Mixed input — boilerplate prefix + real artist copy. The original
        # raw string is returned (we only use scrubbing to decide whether to
        # keep it), so the door times survive too.
        mixed = (
            "Doors at 6:00 pm | Show at 7:00 pm Cary Elwes (Westley) is hitting "
            "the road to share never-before-told stories from the making of The "
            "Princess Bride, followed by a screening and live Q&A."
        )
        assert _choose_description(mixed, None) == mixed

    def test_info_empty_falls_back_to_please_note(self):
        assert _choose_description(None, _RENT_REAL_DESCRIPTION) == _RENT_REAL_DESCRIPTION
        assert _choose_description("", _RENT_REAL_DESCRIPTION) == _RENT_REAL_DESCRIPTION

    def test_info_preferred_over_please_note(self):
        # Both populated and both have signal → info wins, mirroring the
        # original `info or pleaseNote` precedence.
        assert (
            _choose_description(_RENT_REAL_DESCRIPTION, "different note")
            == _RENT_REAL_DESCRIPTION
        )

    def test_info_boilerplate_falls_through_to_please_note(self):
        # info is boilerplate but pleaseNote carries real signal — pick pleaseNote.
        assert (
            _choose_description(_SYLVEE_BOILERPLATE, _RENT_REAL_DESCRIPTION)
            == _RENT_REAL_DESCRIPTION
        )
