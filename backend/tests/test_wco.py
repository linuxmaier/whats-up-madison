"""Unit tests for wco.py parsing helpers."""
from datetime import datetime

from bs4 import BeautifulSoup

from app.scrapers.wco import (
    _CENTRAL,
    _normalize_venue,
    _parse_datetimes,
    _parse_row,
)


def _row(html: str):
    return BeautifulSoup(html, "lxml").select_one("div.row.event")


# ---------------------------------------------------------------------------
# _parse_datetimes
# ---------------------------------------------------------------------------

class TestParseDatetimes:
    def test_single_datetime_with_time(self):
        result = _parse_datetimes("Saturday, May 16, 2026 — 7:00 PM")
        assert result is not None
        start, end, all_day = result
        assert start == datetime(2026, 5, 16, 19, 0, tzinfo=_CENTRAL)
        assert end is None
        assert all_day is False

    def test_datetime_range(self):
        text = (
            "Wednesday, June 24, 2026 — 7:00 PM\n"
            "to\n"
            "Wednesday, June 24, 2026 — 9:00 PM"
        )
        result = _parse_datetimes(text)
        assert result is not None
        start, end, all_day = result
        assert start == datetime(2026, 6, 24, 19, 0, tzinfo=_CENTRAL)
        assert end == datetime(2026, 6, 24, 21, 0, tzinfo=_CENTRAL)
        assert all_day is False

    def test_morning_time(self):
        result = _parse_datetimes("Friday, May 22, 2026 — 10:00 AM")
        assert result is not None
        start, _, _ = result
        assert start == datetime(2026, 5, 22, 10, 0, tzinfo=_CENTRAL)

    def test_date_only_is_all_day(self):
        # If the site ever ships a date with no clock time, mark it all-day
        # rather than dropping it.
        result = _parse_datetimes("Sunday, July 4, 2027")
        assert result is not None
        start, end, all_day = result
        assert start == datetime(2027, 7, 4, 0, 0, tzinfo=_CENTRAL)
        assert end is None
        assert all_day is True

    def test_unparseable_returns_none(self):
        assert _parse_datetimes("") is None
        assert _parse_datetimes("date TBA") is None
        assert _parse_datetimes("Coming soon") is None

    def test_dst_summer_offset(self):
        # July → Central Daylight Time (UTC-5)
        result = _parse_datetimes("Wednesday, July 15, 2026 — 7:00 PM")
        assert result is not None
        start, _, _ = result
        assert start.utcoffset().total_seconds() == -5 * 3600

    def test_dst_winter_offset(self):
        # January → Central Standard Time (UTC-6)
        result = _parse_datetimes("Friday, January 29, 2027 — 7:30 PM")
        assert result is not None
        start, _, _ = result
        assert start.utcoffset().total_seconds() == -6 * 3600


# ---------------------------------------------------------------------------
# _normalize_venue
# ---------------------------------------------------------------------------

class TestNormalizeVenue:
    def test_capitol_theater_compound_to_room_name(self):
        # Splitting on em-dash leaves "Capitol Theater", which canonical_venues
        # then collapses to "Overture Center for the Arts" during ingest.
        assert (
            _normalize_venue("Capitol Theater — Overture Center for the Arts")
            == "Capitol Theater"
        )

    def test_hamel_compound_to_room_name(self):
        assert (
            _normalize_venue("Hamel Music Center — University of Wisconsin-Madison")
            == "Hamel Music Center"
        )

    def test_unsplit_venue_unchanged(self):
        assert (
            _normalize_venue("King Street corner of the Capitol Square")
            == "King Street corner of the Capitol Square"
        )

    def test_none_and_empty(self):
        assert _normalize_venue(None) is None
        assert _normalize_venue("") is None
        assert _normalize_venue("   ") is None


# ---------------------------------------------------------------------------
# _parse_row (integration over a representative listing fragment)
# ---------------------------------------------------------------------------

_FULL_ROW_HTML = """
<div class="row event">
  <div class="col col-image col-xs-3 col-md-offset-1 h-sync">
    <div class="box">
      <a href="https://wcoconcerts.org/events/joel-john-piano-men-legends" class="image">
        <img src="https://example.com/poster.jpg" alt="poster" class="w-fit">
      </a>
    </div>
  </div>
  <div class="col col-title col-xs-9 col-md-7 h-sync">
    <div class="box">
      <div class="category-icon">
        <img src="https://example.com/icon-cos.svg" alt="Concerts on the Square">
      </div>
      <div class="text y-center">
        <h2 class="title">Joel &amp; John: Piano Men Legends</h2>
        <div class="subtitle">Jeans &#039;n Classics</div>
        <div class="description">
          <div class="datetime">
            Wednesday, June 24, 2026 — 7:00 PM
            to<br>Wednesday, June 24, 2026 — 9:00 PM
          </div>
          <div class="venue">King Street corner of the Capitol Square</div>
          <div class="cta">
            <a href="https://wcoconcerts.org/events/joel-john-piano-men-legends" class="button">Event Details</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
"""


class TestParseRow:
    def test_full_row(self):
        ev = _parse_row(_row(_FULL_ROW_HTML))
        assert ev is not None
        assert ev.title == "Joel & John: Piano Men Legends"
        assert ev.start_at == datetime(2026, 6, 24, 19, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 6, 24, 21, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False
        assert ev.venue_name == "King Street corner of the Capitol Square"
        assert ev.venue_address is None
        # description starts as the subtitle; detail-page enrichment in
        # fetch() replaces it when the network call succeeds.
        assert ev.description == "Jeans 'n Classics"
        assert ev.image_url == "https://example.com/poster.jpg"
        assert ev.categories == ["Music"]
        assert ev.source_name == "Wisconsin Chamber Orchestra"
        assert ev.source_url == (
            "https://wcoconcerts.org/events/joel-john-piano-men-legends"
        )

    def test_single_datetime_no_end(self):
        html = _FULL_ROW_HTML.replace(
            "Wednesday, June 24, 2026 — 7:00 PM\n"
            "            to<br>Wednesday, June 24, 2026 — 9:00 PM",
            "Saturday, May 16, 2026 — 7:00 PM",
        )
        ev = _parse_row(_row(html))
        assert ev is not None
        assert ev.start_at == datetime(2026, 5, 16, 19, 0, tzinfo=_CENTRAL)
        assert ev.end_at is None

    def test_overture_venue_normalized_to_room_name(self):
        html = _FULL_ROW_HTML.replace(
            "King Street corner of the Capitol Square",
            "Capitol Theater — Overture Center for the Arts",
        )
        ev = _parse_row(_row(html))
        assert ev is not None
        assert ev.venue_name == "Capitol Theater"

    def test_missing_datetime_skips_row(self):
        html = _FULL_ROW_HTML.replace(
            'class="datetime">\n'
            "            Wednesday, June 24, 2026 — 7:00 PM\n"
            "            to<br>Wednesday, June 24, 2026 — 9:00 PM\n"
            "          </div",
            'class="datetime">date TBA</div',
        )
        assert _parse_row(_row(html)) is None

    def test_missing_title_skips_row(self):
        html = _FULL_ROW_HTML.replace(
            '<h2 class="title">Joel &amp; John: Piano Men Legends</h2>',
            "",
        )
        assert _parse_row(_row(html)) is None

    def test_missing_event_details_link_skips_row(self):
        # No image link and no cta link → no source URL → drop.
        html = _FULL_ROW_HTML.replace(
            'href="https://wcoconcerts.org/events/joel-john-piano-men-legends"',
            'href="https://wcoconcerts.org/concerts-tickets"',
        )
        assert _parse_row(_row(html)) is None
