"""Unit tests for our_lives.py parsing helpers."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.scrapers.our_lives import (
    _CENTRAL,
    _build_address,
    _extract_categories,
    _extract_image_url,
    _in_madison_metro,
    _parse_event,
    _venue_dict,
)


# ---------------------------------------------------------------------------
# _venue_dict — Tribe sometimes ships venue as dict, sometimes [], sometimes missing
# ---------------------------------------------------------------------------

class TestVenueDict:
    def test_dict_passthrough(self):
        assert _venue_dict({"venue": "X"}) == {"venue": "X"}

    def test_empty_list_returns_none(self):
        assert _venue_dict([]) is None

    def test_list_with_dict_returns_first(self):
        assert _venue_dict([{"venue": "X"}]) == {"venue": "X"}

    def test_none_returns_none(self):
        assert _venue_dict(None) is None

    def test_empty_dict_returns_none(self):
        assert _venue_dict({}) is None


# ---------------------------------------------------------------------------
# _in_madison_metro
# ---------------------------------------------------------------------------

class TestInMadisonMetro:
    def test_madison_city_accepted(self):
        assert _in_madison_metro({"city": "Madison"}) is True

    def test_madison_case_insensitive(self):
        assert _in_madison_metro({"city": "MADISON"}) is True
        assert _in_madison_metro({"city": "  madison  "}) is True

    def test_metro_suburbs_accepted(self):
        for city in ("Middleton", "Verona", "Sun Prairie", "Waunakee",
                     "Fitchburg", "Monona", "McFarland", "Stoughton"):
            assert _in_madison_metro({"city": city}) is True, city

    def test_outside_metro_rejected(self):
        for city in ("Milwaukee", "Green Bay", "Stevens Point", "Aniwa", "Sheboygan"):
            assert _in_madison_metro({"city": city}) is False, city

    def test_no_venue_rejected(self):
        assert _in_madison_metro(None) is False
        assert _in_madison_metro({}) is False

    def test_no_city_with_madison_address_accepted(self):
        # Overture Center pattern — city missing but address is Madison.
        assert _in_madison_metro({"address": "201 State Street, Madison, WI"}) is True

    def test_no_city_with_madison_zip_accepted(self):
        assert _in_madison_metro({"address": "1 Capitol Sq", "zip": "53703"}) is True

    def test_no_city_with_zip_in_address_accepted(self):
        assert _in_madison_metro({"address": "100 Main St 53715"}) is True

    def test_no_city_no_madison_signal_rejected(self):
        # No city, address doesn't match Madison.
        assert _in_madison_metro({"address": "123 Anywhere St"}) is False
        assert _in_madison_metro({"address": ""}) is False


# ---------------------------------------------------------------------------
# _build_address
# ---------------------------------------------------------------------------

class TestBuildAddress:
    def test_full_address(self):
        venue = {"address": "300 Richard St", "city": "Verona", "state": "WI", "zip": "53593"}
        assert _build_address(venue) == "300 Richard St, Verona, WI 53593"

    def test_missing_zip(self):
        venue = {"address": "201 State Street", "city": "Madison", "state": "WI"}
        assert _build_address(venue) == "201 State Street, Madison, WI"

    def test_missing_state_and_zip(self):
        venue = {"address": "100 Main St", "city": "Madison"}
        assert _build_address(venue) == "100 Main St, Madison"

    def test_only_address(self):
        assert _build_address({"address": "201 State Street"}) == "201 State Street"

    def test_empty_returns_none(self):
        assert _build_address({}) is None
        assert _build_address({"address": "", "city": ""}) is None


# ---------------------------------------------------------------------------
# _extract_image_url
# ---------------------------------------------------------------------------

class TestExtractImageUrl:
    def test_dict_with_url(self):
        assert _extract_image_url({"url": "https://x/y.jpg"}) == "https://x/y.jpg"

    def test_dict_without_url(self):
        assert _extract_image_url({"sizes": {}}) is None

    def test_empty_list(self):
        assert _extract_image_url([]) is None

    def test_none(self):
        assert _extract_image_url(None) is None


# ---------------------------------------------------------------------------
# _extract_categories
# ---------------------------------------------------------------------------

class TestExtractCategories:
    def test_known_tags_mapped(self):
        cats = [{"name": "Music"}, {"name": "Comedy"}]
        assert _extract_categories(cats) == ["Music", "Open Mic & Comedy"]

    def test_drag_maps_to_theater(self):
        assert _extract_categories([{"name": "Drag"}]) == ["Theater & Stage"]

    def test_collapses_duplicates_after_mapping(self):
        # Theater + Performance Art + Drag all map to "Theater & Stage" —
        # output should dedup while preserving first-seen order.
        cats = [{"name": "Theater"}, {"name": "Performance Art"}, {"name": "Drag"}]
        assert _extract_categories(cats) == ["Theater & Stage"]

    def test_dropped_tags_silently_ignored(self):
        cats = [
            {"name": "Social"},
            {"name": "Madison + South Central"},
            {"name": "21+"},
            {"name": "Festival"},
            {"name": "Music"},
        ]
        assert _extract_categories(cats) == ["Music"]

    def test_unknown_tag_dropped(self):
        assert _extract_categories([{"name": "MysteryGenre"}]) == []

    def test_non_list_returns_empty(self):
        assert _extract_categories(None) == []
        assert _extract_categories("Music") == []

    def test_malformed_entries_skipped(self):
        cats = [{"name": "Music"}, "not a dict", {"missing": "name"}, {"name": None}]
        assert _extract_categories(cats) == ["Music"]


# ---------------------------------------------------------------------------
# _parse_event (integration with helpers above)
# ---------------------------------------------------------------------------

def _base_doc(**overrides) -> dict:
    """Minimal shape matching a real Tribe events API response."""
    doc = {
        "title": "Euchre Night",
        "url": "https://ourliveswisconsin.com/event/euchre-night/2026-05-08/",
        "description": "<p>Join us in the taproom for some good old fashioned Euchre!</p>",
        "start_date": "2026-05-08 18:30:00",
        "end_date": "2026-05-08 21:30:00",
        "all_day": False,
        "timezone": "America/Chicago",
        "image": {"url": "https://x/poster.png"},
        "categories": [{"name": "Community"}, {"name": "Social"}],
        "venue": {
            "venue": "Delta Beer Lab",
            "address": "167 E Badger Rd",
            "city": "Madison",
            "state": "WI",
            "zip": "53713",
        },
    }
    doc.update(overrides)
    return doc


class TestParseEvent:
    def test_full_event(self):
        ev = _parse_event(_base_doc())
        assert ev is not None
        assert ev.title == "Euchre Night"
        assert ev.start_at == datetime(2026, 5, 8, 18, 30, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 8, 21, 30, tzinfo=_CENTRAL)
        assert ev.all_day is False
        assert ev.venue_name == "Delta Beer Lab"
        assert ev.venue_address == "167 E Badger Rd, Madison, WI 53713"
        assert ev.description == "Join us in the taproom for some good old fashioned Euchre!"
        assert ev.image_url == "https://x/poster.png"
        # Community → Community & Clubs; Social is dropped.
        assert ev.categories == ["Community & Clubs"]
        assert ev.source_name == "Our Lives"
        assert ev.source_url == "https://ourliveswisconsin.com/event/euchre-night/2026-05-08/"

    def test_outside_metro_returns_none(self):
        ev = _parse_event(_base_doc(venue={
            "venue": "South Second",
            "address": "838 South 2nd Street",
            "city": "Milwaukee",
            "state": "WI",
            "zip": "53204",
        }))
        assert ev is None

    def test_no_venue_returns_none(self):
        assert _parse_event(_base_doc(venue=[])) is None
        assert _parse_event(_base_doc(venue=None)) is None

    def test_overture_no_city_accepted(self):
        # Real-world: Overture Center venue has address but no city. Should
        # be accepted by the address-based fallback.
        ev = _parse_event(_base_doc(venue={
            "venue": "Overture Center – Promenade Hall",
            "address": "201 State Street, Madison",
        }))
        assert ev is not None
        assert ev.venue_name == "Overture Center – Promenade Hall"

    def test_all_day_event(self):
        ev = _parse_event(_base_doc(
            all_day=True,
            start_date="2026-05-08 00:00:00",
            end_date="2026-05-08 23:59:59",
        ))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 8, 0, 0, tzinfo=_CENTRAL)
        # Same-day end_at on an all-day event is dropped.
        assert ev.end_at is None

    def test_multi_day_all_day_keeps_end(self):
        ev = _parse_event(_base_doc(
            all_day=True,
            start_date="2026-05-08 00:00:00",
            end_date="2026-05-10 23:59:59",
        ))
        assert ev is not None
        assert ev.all_day is True
        assert ev.end_at == datetime(2026, 5, 10, 23, 59, 59, tzinfo=_CENTRAL)

    def test_multi_day_timed_event_keeps_end(self):
        # LGBTQ Spring CampOUT pattern — runs across multiple days.
        ev = _parse_event(_base_doc(
            start_date="2026-05-28 12:00:00",
            end_date="2026-05-31 17:00:00",
        ))
        assert ev is not None
        assert ev.start_at.date() != ev.end_at.date()

    def test_missing_image_yields_none(self):
        ev = _parse_event(_base_doc(image=[]))
        assert ev is not None
        assert ev.image_url is None

    def test_missing_title_returns_none(self):
        assert _parse_event(_base_doc(title="")) is None

    def test_missing_url_returns_none(self):
        assert _parse_event(_base_doc(url="")) is None

    def test_invalid_start_date_returns_none(self):
        assert _parse_event(_base_doc(start_date="not a date")) is None

    def test_html_entity_title_decoded(self):
        # Real-world: the live Tribe API ships en-dashes as `&#8211;` in titles
        # (e.g. "Dayshift &#8211; The 30+ Daytime Party"). The undecoded form
        # broke canonical_hash dedup against Atwood's plain-hyphen variant of
        # the same event (#192).
        ev = _parse_event(_base_doc(title="Dayshift &#8211; The 30+ Daytime Party"))
        assert ev is not None
        assert ev.title == "Dayshift – The 30+ Daytime Party"

    def test_html_entity_venue_name_decoded(self):
        # venue_name participates in the canonical_hash too, so the same
        # decoding must happen there.
        ev = _parse_event(_base_doc(venue={
            "venue": "Smith &amp; Sons",
            "address": "1 Main St",
            "city": "Madison",
            "state": "WI",
            "zip": "53703",
        }))
        assert ev is not None
        assert ev.venue_name == "Smith & Sons"

    def test_unusual_timezone_falls_back_to_central(self):
        ev = _parse_event(_base_doc(timezone="Not/A_Zone"))
        assert ev is not None
        # Still parses; falls back to America/Chicago.
        assert ev.start_at.tzinfo is not None


def test_central_zone_constant():
    assert _CENTRAL == ZoneInfo("America/Chicago")
