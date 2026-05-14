"""Unit tests for dmi.py parsing helpers."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.scrapers.dmi import (
    _CENTRAL,
    _build_address,
    _extract_image_url,
    _in_madison_metro,
    _parse_event,
    _venue_dict,
)


# ---------------------------------------------------------------------------
# _venue_dict
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
        for city in ("Milwaukee", "Green Bay", "Chicago"):
            assert _in_madison_metro({"city": city}) is False, city

    def test_no_venue_rejected(self):
        assert _in_madison_metro(None) is False
        assert _in_madison_metro({}) is False

    def test_no_city_with_madison_zip_accepted(self):
        assert _in_madison_metro({"address": "1001 Wisconsin Pl", "zip": "53703"}) is True


# ---------------------------------------------------------------------------
# _build_address
# ---------------------------------------------------------------------------

class TestBuildAddress:
    def test_full_address(self):
        venue = {"address": "1001 Wisconsin Place", "city": "Madison", "state": "WI", "zip": "53703"}
        assert _build_address(venue) == "1001 Wisconsin Place, Madison, WI 53703"

    def test_only_address(self):
        assert _build_address({"address": "201 State Street"}) == "201 State Street"

    def test_empty_returns_none(self):
        assert _build_address({}) is None


# ---------------------------------------------------------------------------
# _extract_image_url — note DMI often ships "image": false
# ---------------------------------------------------------------------------

class TestExtractImageUrl:
    def test_dict_with_url(self):
        assert _extract_image_url({"url": "https://x/y.jpg"}) == "https://x/y.jpg"

    def test_false_returns_none(self):
        # Real DMI events often have `"image": false`. Our helper must not crash.
        assert _extract_image_url(False) is None

    def test_none_returns_none(self):
        assert _extract_image_url(None) is None


# ---------------------------------------------------------------------------
# _parse_event
# ---------------------------------------------------------------------------

def _base_doc(**overrides) -> dict:
    """Minimal shape matching a real DMI Tribe Events API response.

    HTML-entity-encoded title preserved verbatim from the live API response —
    DMI does NOT decode entities server-side (unlike Our Lives).
    """
    doc = {
        "title": "What&#8217;s Up Downtown",
        "url": "https://downtownmadison.org/event/whats-up-downtown-2026-05-28/",
        "description": "<h2>Overview:</h2><p>All DMI members are welcome to join us for &#8220;What&#8217;s Up Downtown&#8221;!</p>",
        "start_date": "2026-05-28 07:45:00",
        "end_date": "2026-05-28 09:00:00",
        "all_day": False,
        "timezone": "America/Chicago",
        "image": False,
        "categories": [{"name": "What’s Up Downtown", "slug": "whats-up-downtown"}],
        "venue": {
            "venue": "The Edgewater Hotel",
            "address": "1001 Wisconsin Place",
            "city": "Madison",
            "state": "WI",
            "zip": "53703",
        },
    }
    doc.update(overrides)
    return doc


class TestParseEvent:
    def test_full_event(self):
        ev = _parse_event(_base_doc())
        assert ev is not None
        # HTML entity in title is decoded.
        assert ev.title == "What’s Up Downtown"
        assert ev.start_at == datetime(2026, 5, 28, 7, 45, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 28, 9, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False
        assert ev.venue_name == "The Edgewater Hotel"
        assert ev.venue_address == "1001 Wisconsin Place, Madison, WI 53703"
        # DMI events deliberately ship no pre-mapped categories — LLM tagger handles them.
        assert ev.categories == []
        assert ev.image_url is None
        assert ev.source_name == "DMI"
        assert ev.source_url == "https://downtownmadison.org/event/whats-up-downtown-2026-05-28/"

    def test_html_entity_title_decoded(self):
        # The defining behavioral difference from Our Lives' parser.
        ev = _parse_event(_base_doc(title="2026 DMI Annual Celebration &amp; Awards"))
        assert ev is not None
        assert ev.title == "2026 DMI Annual Celebration & Awards"

    def test_html_entity_venue_name_decoded(self):
        # Real-world: New Faces New Places at "RDG Planning &#038; Design".
        ev = _parse_event(_base_doc(venue={
            "venue": "RDG Planning &#038; Design",
            "address": "100 W Wilson St",
            "city": "Madison",
            "state": "WI",
            "zip": "53703",
        }))
        assert ev is not None
        assert ev.venue_name == "RDG Planning & Design"

    def test_outside_metro_returns_none(self):
        ev = _parse_event(_base_doc(venue={
            "venue": "Somewhere Else",
            "address": "1 Main St",
            "city": "Milwaukee",
            "state": "WI",
            "zip": "53202",
        }))
        assert ev is None

    def test_no_venue_returns_none(self):
        assert _parse_event(_base_doc(venue=[])) is None
        assert _parse_event(_base_doc(venue=None)) is None

    def test_all_day_multi_day_keeps_end(self):
        # IDA Place Matters pattern — May 13 through May 15, all-day.
        ev = _parse_event(_base_doc(
            title="2026 IDA Place Matters",
            all_day=True,
            start_date="2026-05-13 00:00:00",
            end_date="2026-05-15 23:59:59",
            venue={
                "venue": "Best Western Premier Park Hotel",
                "address": "22 S Carroll St",
                "city": "Madison",
                "state": "WI",
                "zip": "53703",
            },
        ))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 13, 0, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 15, 23, 59, 59, tzinfo=_CENTRAL)

    def test_all_day_single_day_drops_end(self):
        ev = _parse_event(_base_doc(
            all_day=True,
            start_date="2026-05-28 00:00:00",
            end_date="2026-05-28 23:59:59",
        ))
        assert ev is not None
        assert ev.all_day is True
        assert ev.end_at is None

    def test_missing_title_returns_none(self):
        assert _parse_event(_base_doc(title="")) is None

    def test_missing_url_returns_none(self):
        assert _parse_event(_base_doc(url="")) is None

    def test_invalid_start_date_returns_none(self):
        assert _parse_event(_base_doc(start_date="not a date")) is None


def test_central_zone_constant():
    assert _CENTRAL == ZoneInfo("America/Chicago")
