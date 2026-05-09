"""Unit tests for ticketmaster.py parsing helpers."""
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from app.scrapers.ticketmaster import (
    _CENTRAL,
    _build_address,
    _map_categories,
    _parse_event,
    _select_image,
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
    info="Doors at 6:30 pm | Show at 8:00 pm. Cashless venue, bag policy applies.",
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
        assert ev.description.startswith("Doors at 6:30 pm")
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

    def test_missing_venue_returns_none(self):
        doc = _doc()
        doc["_embedded"] = {"venues": []}
        assert _parse_event(doc) is None

    def test_description_falls_back_to_please_note(self):
        ev = _parse_event(_doc(info=None, please_note="Bag policy in effect."))
        assert ev is not None
        assert ev.description == "Bag policy in effect."

    def test_description_none_when_both_missing(self):
        ev = _parse_event(_doc(info=None, please_note=None))
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
