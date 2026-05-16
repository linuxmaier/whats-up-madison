"""Unit tests for city_of_madison.py parsing helpers."""
from datetime import datetime, timedelta

from bs4 import BeautifulSoup

from app.scrapers.city_of_madison import (
    _CENTRAL,
    _parse_item,
    _parse_start_at,
    _parse_time_range,
)


# ---------------------------------------------------------------------------
# _parse_start_at
# ---------------------------------------------------------------------------

class TestParseStartAt:
    def test_iso_with_offset(self):
        dt = _parse_start_at("2026-05-16T08:00:00-05:00")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 5 and dt.day == 16
        assert dt.hour == 8 and dt.minute == 0
        assert dt.utcoffset() == timedelta(hours=-5)

    def test_midnight_all_day(self):
        dt = _parse_start_at("2026-05-16T00:00:00-05:00")
        assert dt is not None
        assert dt.hour == 0 and dt.minute == 0

    def test_invalid_returns_none(self):
        assert _parse_start_at("not a date") is None
        assert _parse_start_at("") is None
        assert _parse_start_at(None) is None


# ---------------------------------------------------------------------------
# _parse_time_range
# ---------------------------------------------------------------------------

_START = datetime(2026, 5, 16, 8, 0, tzinfo=_CENTRAL)


class TestParseTimeRange:
    def test_all_day(self):
        end, all_day = _parse_time_range(_START, "All day")
        assert end is None
        assert all_day is True

    def test_all_day_empty(self):
        end, all_day = _parse_time_range(_START, "")
        assert end is None
        assert all_day is True

    def test_morning_range(self):
        end, all_day = _parse_time_range(_START, "8:00am – 10:00am")
        assert all_day is False
        assert end is not None
        assert end.hour == 10 and end.minute == 0

    def test_afternoon_range(self):
        start = datetime(2026, 5, 16, 13, 0, tzinfo=_CENTRAL)
        end, all_day = _parse_time_range(start, "1:00pm – 2:00pm")
        assert all_day is False
        assert end is not None
        assert end.hour == 14 and end.minute == 0

    def test_cross_noon(self):
        start = datetime(2026, 5, 16, 11, 0, tzinfo=_CENTRAL)
        end, all_day = _parse_time_range(start, "11:00am – 1:00pm")
        assert all_day is False
        assert end is not None
        assert end.hour == 13

    def test_hyphen_separator(self):
        end, all_day = _parse_time_range(_START, "8:00am - 10:00am")
        assert all_day is False
        assert end is not None
        assert end.hour == 10

    def test_end_timezone_matches_start(self):
        end, _ = _parse_time_range(_START, "8:00am – 10:00am")
        assert end is not None
        assert end.tzinfo == _START.tzinfo

    def test_unknown_text(self):
        end, all_day = _parse_time_range(_START, "Time TBA")
        assert end is None
        assert all_day is False

    def test_dst_summer(self):
        start = datetime(2026, 7, 4, 10, 0, tzinfo=_CENTRAL)
        end, all_day = _parse_time_range(start, "10:00am – 12:00pm")
        assert all_day is False
        assert end is not None
        assert end.utcoffset().total_seconds() == -5 * 3600


# ---------------------------------------------------------------------------
# _parse_item (integration over representative HTML fragments)
# ---------------------------------------------------------------------------

_TIMED_ITEM_HTML = """\
<li>
  <div class="views-field views-field-field-smart-date">
    <div class="field-content">
      <div aria-hidden="true">
        <div class="event-date">
          <time class="start-date" datetime="2026-05-16T08:00:00-05:00">
            <span class="month">May</span>
            <span class="day">16</span>
          </time>
        </div>
      </div>
    </div>
  </div>
  <div class="views-field views-field-nothing">
    <span class="field-content">
      <div class="event-content">
        <div class="event-header">
          <h3 class="event-heading">
            <a href="/parks/golf/events/volunteer-at-the-glen-0">Volunteer at The Glen</a>
          </h3>
        </div>
        <time datetime="2026-05-16T08:00:00-05:00">
          <div class="visually-hidden">Saturday, May 16, 2026</div>
          8:00am &ndash; 10:00am
        </time>
        <div class="event-venues">
          <address translate="no">
            <div class="address-location-name">
              <strong>The Glen Golf Park</strong>
            </div>
            <span>3747 Speedway Road</span>
          </address>
        </div>
      </div>
    </span>
  </div>
</li>
"""

_ALL_DAY_ITEM_HTML = """\
<li>
  <div class="views-field views-field-field-smart-date">
    <div class="field-content">
      <div aria-hidden="true">
        <div class="event-date">
          <time class="start-date" datetime="2026-05-16T00:00:00-05:00">
            <span class="month">May</span>
            <span class="day">16</span>
          </time>
        </div>
      </div>
    </div>
  </div>
  <div class="views-field views-field-nothing">
    <span class="field-content">
      <div class="event-content">
        <div class="event-header">
          <h2 class="event-heading">
            <a href="/parks/events/2026-05-16/kids-to-parks-day">Kids To Parks Day</a>
          </h2>
        </div>
        <time datetime="2026-05-16T00:00:00-05:00">
          <div class="visually-hidden">Saturday, May 16, 2026</div>
          All day
        </time>
      </div>
    </span>
  </div>
</li>
"""


def _content(html: str):
    soup = BeautifulSoup(html, "lxml")
    return soup.select_one("div.event-content")


class TestParseItem:
    def test_timed_event_full_fields(self):
        ev = _parse_item(_content(_TIMED_ITEM_HTML))
        assert ev is not None
        assert ev.title == "Volunteer at The Glen"
        assert ev.source_url == "https://www.cityofmadison.com/parks/golf/events/volunteer-at-the-glen-0"
        assert ev.start_at == datetime(2026, 5, 16, 8, 0, tzinfo=_CENTRAL)
        assert ev.end_at is not None
        assert ev.end_at.hour == 10 and ev.end_at.minute == 0
        assert ev.all_day is False
        assert ev.venue_name == "The Glen Golf Park"
        assert ev.venue_address == "3747 Speedway Road"
        assert ev.source_name == "City of Madison"
        assert ev.categories == []
        assert ev.description is None  # description filled by detail-page fetch in fetch()

    def test_all_day_event_no_venue(self):
        ev = _parse_item(_content(_ALL_DAY_ITEM_HTML))
        assert ev is not None
        assert ev.title == "Kids To Parks Day"
        assert ev.source_url == "https://www.cityofmadison.com/parks/events/2026-05-16/kids-to-parks-day"
        assert ev.all_day is True
        assert ev.end_at is None
        assert ev.venue_name is None
        assert ev.venue_address is None

    def test_absolute_url_preserved(self):
        html = _TIMED_ITEM_HTML.replace(
            'href="/parks/golf/events/volunteer-at-the-glen-0"',
            'href="https://www.cityofmadison.com/parks/golf/events/volunteer-at-the-glen-0"',
        )
        ev = _parse_item(_content(html))
        assert ev is not None
        assert ev.source_url == "https://www.cityofmadison.com/parks/golf/events/volunteer-at-the-glen-0"

    def test_missing_title_returns_none(self):
        html = _TIMED_ITEM_HTML.replace(
            '<a href="/parks/golf/events/volunteer-at-the-glen-0">Volunteer at The Glen</a>',
            "",
        )
        assert _parse_item(_content(html)) is None

    def test_missing_start_time_returns_none(self):
        html = _TIMED_ITEM_HTML.replace(
            '<time class="start-date" datetime="2026-05-16T08:00:00-05:00">',
            "<time>",
        )
        assert _parse_item(_content(html)) is None
