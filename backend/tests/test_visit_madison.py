"""Unit tests for visit_madison.py time-parsing strategy helpers."""
from datetime import date, datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from app.scrapers.visit_madison import (
    _CENTRAL,
    _day_of_week_events,
    _fallback_all_day_desc,
    _parse_from_to_times,
    _top_level_times,
)

_DATE = date(2026, 5, 8)  # a Friday


# ---------------------------------------------------------------------------
# _top_level_times
# ---------------------------------------------------------------------------

class TestTopLevelTimes:
    def _doc(self, start=None, end=None):
        return {"startTime": start, "endTime": end}

    def test_no_start_time_returns_none(self):
        assert _top_level_times({}, _DATE) is None

    def test_empty_start_time_returns_none(self):
        assert _top_level_times(self._doc(start=""), _DATE) is None

    def test_start_only(self):
        result = _top_level_times(self._doc(start="18:30:00"), _DATE)
        assert result is not None
        start_at, end_at = result
        assert start_at == datetime.combine(_DATE, dtime(18, 30, 0), tzinfo=_CENTRAL)
        assert end_at is None

    def test_start_and_end(self):
        result = _top_level_times(self._doc(start="18:00:00", end="20:00:00"), _DATE)
        assert result is not None
        start_at, end_at = result
        assert start_at == datetime.combine(_DATE, dtime(18, 0, 0), tzinfo=_CENTRAL)
        assert end_at == datetime.combine(_DATE, dtime(20, 0, 0), tzinfo=_CENTRAL)

    def test_midnight_wrap_when_end_before_start(self):
        # Event that runs from 11pm to 1am — end_at should be next day.
        result = _top_level_times(self._doc(start="23:00:00", end="01:00:00"), _DATE)
        assert result is not None
        start_at, end_at = result
        assert end_at == datetime.combine(_DATE + timedelta(days=1), dtime(1, 0, 0), tzinfo=_CENTRAL)
        assert end_at > start_at


# ---------------------------------------------------------------------------
# _parse_from_to_times  (Strategy 2)
# ---------------------------------------------------------------------------

class TestParseFromToTimes:
    def test_standard_range(self):
        result = _parse_from_to_times("From: 06:00 PM to 08:30 PM", _DATE)
        assert result is not None
        start_at, end_at = result
        assert start_at == datetime.combine(_DATE, dtime(18, 0, 0), tzinfo=_CENTRAL)
        assert end_at == datetime.combine(_DATE, dtime(20, 30, 0), tzinfo=_CENTRAL)

    def test_no_match_returns_none(self):
        assert _parse_from_to_times("Doors open at 7pm", _DATE) is None

    def test_midnight_wrap(self):
        result = _parse_from_to_times("From: 11:00 PM to 01:00 AM", _DATE)
        assert result is not None
        start_at, end_at = result
        assert end_at == datetime.combine(_DATE + timedelta(days=1), dtime(1, 0, 0), tzinfo=_CENTRAL)

    def test_case_insensitive(self):
        result = _parse_from_to_times("from: 02:00 pm to 04:00 pm", _DATE)
        assert result is not None


# ---------------------------------------------------------------------------
# _day_of_week_events  (Strategy 3)
# ---------------------------------------------------------------------------

def _iso_z(d: date) -> str:
    """Build a simple UTC ISO string at midnight Central (approximated as T06:00Z)."""
    return datetime(d.year, d.month, d.day, 6, 0, 0, tzinfo=ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


class TestDayOfWeekEvents:
    def _doc(self, start: date, end: date):
        return {"startDate": _iso_z(start), "endDate": _iso_z(end)}

    def test_no_times_str_returns_empty(self):
        doc = self._doc(date(2026, 5, 1), date(2026, 5, 31))
        assert _day_of_week_events(doc, "") == []

    def test_no_start_date_returns_empty(self):
        assert _day_of_week_events({}, "Friday 6:30pm-7:30pm") == []

    def test_no_matching_days_in_range(self):
        # Range is a single Monday; looking for Friday — no match.
        doc = self._doc(date(2026, 5, 4), date(2026, 5, 4))  # Monday only
        result = _day_of_week_events(doc, "Friday 6:30pm-7:30pm")
        assert result == []

    def test_single_day_match(self):
        # Range covers exactly one Friday (May 8 2026).
        doc = self._doc(date(2026, 5, 4), date(2026, 5, 10))
        result = _day_of_week_events(doc, "Friday 6:30pm-7:30pm")
        assert len(result) == 1
        start_at, end_at = result[0]
        assert start_at.date() == date(2026, 5, 8)
        assert start_at.time() == dtime(18, 30, 0)
        assert end_at.time() == dtime(19, 30, 0)
        assert start_at.tzinfo is not None

    def test_multiple_weekday_matches(self):
        # Two-week range should hit two Fridays.
        doc = self._doc(date(2026, 5, 1), date(2026, 5, 14))
        result = _day_of_week_events(doc, "Friday 6:30pm-7:30pm")
        assert len(result) == 2

    def test_multiple_day_types(self):
        # "Friday 6:30pm-7:30pm, Saturday 11am-12pm" over one week.
        doc = self._doc(date(2026, 5, 4), date(2026, 5, 10))
        result = _day_of_week_events(doc, "Friday 6:30pm-7:30pm, Saturday 11am-12pm")
        assert len(result) == 2
        days = {r[0].date() for r in result}
        assert date(2026, 5, 8) in days   # Friday
        assert date(2026, 5, 9) in days   # Saturday

    def test_midnight_wrap(self):
        doc = self._doc(date(2026, 5, 4), date(2026, 5, 10))
        result = _day_of_week_events(doc, "Friday 11pm-1am")
        assert len(result) == 1
        start_at, end_at = result[0]
        assert end_at > start_at
        assert end_at.date() == date(2026, 5, 9)  # next day


# ---------------------------------------------------------------------------
# _fallback_all_day_desc  (Strategy 4)
# ---------------------------------------------------------------------------

class TestFallbackAllDayDesc:
    def test_no_times_str_returns_description(self):
        assert _fallback_all_day_desc("", "Some description") == "Some description"

    def test_times_prepended_to_description(self):
        result = _fallback_all_day_desc("7pm-9pm", "Great event")
        assert result == "7pm-9pm — Great event"

    def test_times_only_when_no_description(self):
        result = _fallback_all_day_desc("7pm-9pm", None)
        assert result == "7pm-9pm"

    def test_see_event_description_passthrough(self):
        result = _fallback_all_day_desc("See event description for times", "My desc")
        assert result == "My desc"

    def test_see_event_description_case_insensitive(self):
        result = _fallback_all_day_desc("SEE EVENT DESCRIPTION", "My desc")
        assert result == "My desc"

    def test_empty_times_with_none_description(self):
        assert _fallback_all_day_desc("", None) is None
