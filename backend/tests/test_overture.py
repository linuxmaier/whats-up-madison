"""Unit tests for overture.py parsing helpers."""
from datetime import date, datetime, time as dtime

from bs4 import BeautifulSoup

from app.scrapers.base import RawEvent
from app.scrapers.overture import (
    _CENTRAL,
    _DEFAULT_VENUE_NAME,
    _SOURCE_NAME,
    _expand_with_schedule,
    _extract_date_pair,
    _extract_session_form,
    _map_categories,
    _normalize_venue,
    _parse_card,
    _parse_cards,
    _parse_schedule,
    _parse_span,
    _parse_time,
    OvertureSource,
)


def _card(html: str):
    return BeautifulSoup(html, "lxml").select_one("li.upcoming-event-card")


def _cards(html: str):
    return BeautifulSoup(html, "lxml").select("li.upcoming-event-card")


# ---------------------------------------------------------------------------
# _parse_span / _parse_time / _normalize_venue / _map_categories
# ---------------------------------------------------------------------------

class TestParseSpan:
    def test_simple(self):
        d = _parse_span("May 10")
        assert d is not None and d.month == 5 and d.day == 10

    def test_full_month(self):
        d = _parse_span("September 7")
        assert d is not None and d.month == 9 and d.day == 7

    def test_two_digit_day(self):
        d = _parse_span("November 24")
        assert d is not None and d.month == 11 and d.day == 24

    def test_lowercase(self):
        d = _parse_span("january 9")
        assert d is not None and d.month == 1

    def test_garbage(self):
        assert _parse_span("") is None
        assert _parse_span("Foo 5") is None
        assert _parse_span("May") is None


class TestParseTime:
    def test_evening(self):
        assert _parse_time("7:30 PM") == dtime(19, 30)

    def test_morning(self):
        assert _parse_time("9:30 AM") == dtime(9, 30)

    def test_lowercase(self):
        assert _parse_time("8:00 pm") == dtime(20, 0)

    def test_multiple_showtimes_returns_none(self):
        assert _parse_time("Multiple Showtimes") is None

    def test_empty(self):
        assert _parse_time(None) is None
        assert _parse_time("") is None
        assert _parse_time("TBA") is None


class TestNormalizeVenue:
    def test_internal_room_normalized(self):
        assert _normalize_venue("Capitol Theater") == _DEFAULT_VENUE_NAME
        assert _normalize_venue("Overture Hall") == _DEFAULT_VENUE_NAME
        assert _normalize_venue("Promenade Lobby") == _DEFAULT_VENUE_NAME
        assert _normalize_venue("The Playhouse") == _DEFAULT_VENUE_NAME
        assert _normalize_venue("James Watrous Gallery") == _DEFAULT_VENUE_NAME

    def test_internal_case_insensitive(self):
        assert _normalize_venue("CAPITOL THEATER") == _DEFAULT_VENUE_NAME

    def test_external_kept_literal(self):
        assert _normalize_venue("Bethel Lutheran Church") == "Bethel Lutheran Church"
        assert _normalize_venue("MYArts Starlight Theater") == "MYArts Starlight Theater"
        assert _normalize_venue("Memorial Union Terrace") == "Memorial Union Terrace"

    def test_empty_or_none_defaults(self):
        assert _normalize_venue(None) == _DEFAULT_VENUE_NAME
        assert _normalize_venue("") == _DEFAULT_VENUE_NAME
        assert _normalize_venue("   ") == _DEFAULT_VENUE_NAME


class TestMapCategories:
    def test_music_canonicalizes(self):
        assert _map_categories("Music") == ["Music"]
        assert _map_categories("Classical Music") == ["Music"]
        assert _map_categories("Jazz") == ["Music"]

    def test_theater_collapses(self):
        # "Broadway" + "Musical Theater" both → Theater & Stage; uniq.
        assert _map_categories("Broadway, Musical Theater") == ["Theater & Stage"]

    def test_dance_is_performance(self):
        # The taxonomy puts performance dance under Theater & Stage.
        assert _map_categories("Dance, Family Friendly") == [
            "Theater & Stage",
            "Family & Kids",
        ]

    def test_admin_tags_dropped(self):
        # Season/package/company/free-event tags ignored — the LLM tagger
        # picks up what's relevant from the description.
        assert _map_categories(
            "2025/26 Season, Add-on Event, Madison Symphony Orchestra, Free Events"
        ) == []

    def test_mixed(self):
        result = _map_categories("Comedy, Overture Presents, 2026/27 Season")
        assert result == ["Open Mic & Comedy"]

    def test_empty(self):
        assert _map_categories(None) == []
        assert _map_categories("") == []
        assert _map_categories(",,,") == []


# ---------------------------------------------------------------------------
# Date pair extraction (single day vs multi-day range)
# ---------------------------------------------------------------------------

_SINGLE_DAY_DATE_HTML = """
<li class="upcoming-event-card">
  <div class="upcoming-event-date">
    <div>
      <span class="h3-style">May 10</span>
    </div>
    <p class="small light uppercase">Sunday</p>
  </div>
</li>
"""

_MULTI_DAY_DATE_HTML = """
<li class="upcoming-event-card">
  <div class="upcoming-event-date">
    <div>
      <span class="h3-style">May 10</span>
      <span class="h3-style">-</span>
      <span class="h3-style">May 17</span>
    </div>
    <p class="small light uppercase"></p>
  </div>
</li>
"""


class TestExtractDatePair:
    def test_single_day(self):
        result = _extract_date_pair(_card(_SINGLE_DAY_DATE_HTML))
        assert result is not None
        start, end = result
        assert start.month == 5 and start.day == 10
        assert end is None

    def test_multi_day(self):
        result = _extract_date_pair(_card(_MULTI_DAY_DATE_HTML))
        assert result is not None
        start, end = result
        assert start.month == 5 and start.day == 10
        assert end is not None and end.month == 5 and end.day == 17


# ---------------------------------------------------------------------------
# _parse_cards: year-inference walk
# ---------------------------------------------------------------------------

def _make_card(spans: list[str], time_text: str = "7:30 PM",
               title: str = "Test Event", venue: str = "Capitol Theater"):
    span_html = "\n".join(f'<span class="h3-style">{s}</span>' for s in spans)
    return f"""
<li class="upcoming-event-card">
  <div class="upcoming-event">
    <div class="upcoming-event-half">
      <div class="upcoming-event-date">
        <div>{span_html}</div>
      </div>
      <div class="upcoming-event-image">
        <a href="/tickets-events/test/"><div class="upcoming-event-image-container">
          <img src="/media/test.jpg" alt="Test"/>
        </div></a>
      </div>
    </div>
    <div class="upcoming-event-half">
      <div class="stack flex-column-between">
        <div class="flex-between upcoming-event-content">
          <div class="upcoming-event-details">
            <h3 class="upcoming-event-details-heading">
              <span class="h6-style upcoming-event-details-category">Theater</span>
              <a class="upcoming-event-details-title" href="/tickets-events/test/">{title}</a>
            </h3>
            <p class="small bold">{venue}</p>
            <p class="upcoming-event-details-description">A test event description.</p>
          </div>
          <div class="upcoming-event-price"><span class="h6-style">{time_text}</span></div>
        </div>
        <div class="upcoming-event-ctas"><a class="btn-primary" href="https://tickets.overture.org/1234">Buy Tickets</a></div>
      </div>
    </div>
  </div>
</li>
"""


class TestParseCardsYearInference:
    def test_chronological_same_year(self):
        cards = _cards(
            _make_card(["May 10"]) + _make_card(["June 5"]) + _make_card(["August 20"])
        )
        events = _parse_cards(cards, today=date(2026, 5, 1))
        assert len(events) == 3
        assert events[0].start_at.year == 2026
        assert events[1].start_at.year == 2026
        assert events[2].start_at.year == 2026

    def test_year_wraps_when_month_regresses(self):
        # Nov 24 → Jan 8 means we crossed into the next year.
        cards = _cards(
            _make_card(["November 24"]) + _make_card(["January 8"])
        )
        events = _parse_cards(cards, today=date(2026, 5, 1))
        assert events[0].start_at.year == 2026
        assert events[1].start_at.year == 2027

    def test_multi_day_range_within_same_year(self):
        cards = _cards(_make_card(["May 10", "-", "May 17"]))
        events = _parse_cards(cards, today=date(2026, 5, 1))
        assert len(events) == 1
        assert events[0].start_at.year == 2026
        assert events[0].end_at is not None
        assert events[0].end_at.year == 2026
        assert events[0].end_at.month == 5
        assert events[0].end_at.day == 17

    def test_multi_day_range_crossing_december(self):
        # December 30 - January 4 → end falls in current_year+1 of the
        # cards' inferred year.
        cards = _cards(_make_card(["December 30", "-", "January 4"]))
        events = _parse_cards(cards, today=date(2026, 12, 1))
        assert events[0].start_at.year == 2026
        assert events[0].end_at is not None
        assert events[0].end_at.year == 2027


# ---------------------------------------------------------------------------
# _parse_card: integration with realistic HTML
# ---------------------------------------------------------------------------

_FULL_CARD_HTML = """
<li class="upcoming-event-card">
  <div class="upcoming-event">
    <div class="upcoming-event-half">
      <div class="upcoming-event-date">
        <div><span class="h3-style">May 10</span></div>
        <p class="small light uppercase">Sunday</p>
      </div>
      <div class="upcoming-event-image">
        <a href="/tickets-events/2025-26-season/madison-ballet-innovation-ii/">
          <div class="upcoming-event-image-container">
            <img alt="Innovation II" src="/media/pc5pla3s/innovation-ii_banner.jpg"/>
          </div>
        </a>
      </div>
    </div>
    <div class="upcoming-event-half">
      <div class="stack flex-column-between">
        <div class="flex-between upcoming-event-content">
          <div class="upcoming-event-details">
            <h3 class="upcoming-event-details-heading">
              <span class="h6-style upcoming-event-details-category">Dance, Family Friendly, Madison Ballet</span>
              <a class="upcoming-event-details-title" href="/tickets-events/2025-26-season/madison-ballet-innovation-ii/">Innovation II</a>
            </h3>
            <p class="small bold">Promenade Hall</p>
            <p class="upcoming-event-details-description">In this invigorating artistic initiative, the dancers of Madison Ballet step into the role of choreographer.</p>
          </div>
          <div class="upcoming-event-price"><span class="h6-style">2:00 PM</span></div>
        </div>
        <div class="upcoming-event-ctas">
          <a class="btn-primary" href="https://tickets.overture.org/11383" target="">Buy Tickets</a>
        </div>
      </div>
    </div>
  </div>
</li>
"""


class TestParseCard:
    def test_full_card(self):
        ev = _parse_card(
            _card(_FULL_CARD_HTML),
            start_date=datetime(2026, 5, 10),
            end_date=None,
        )
        assert ev is not None
        assert ev.title == "Innovation II"
        assert ev.start_at == datetime(2026, 5, 10, 14, 0, tzinfo=_CENTRAL)
        assert ev.end_at is None
        assert ev.all_day is False
        # Promenade Hall → canonical Overture name.
        assert ev.venue_name == _DEFAULT_VENUE_NAME
        assert ev.venue_address is None
        assert "dancers of Madison Ballet" in (ev.description or "")
        # "Dance" → Theater & Stage; "Family Friendly" → Family & Kids;
        # "Madison Ballet" dropped.
        assert ev.categories == ["Theater & Stage", "Family & Kids"]
        assert ev.image_url == (
            "https://www.overture.org/media/pc5pla3s/innovation-ii_banner.jpg"
        )
        assert ev.source_name == _SOURCE_NAME
        assert ev.source_url == (
            "https://www.overture.org/tickets-events/2025-26-season/madison-ballet-innovation-ii/"
        )

    def test_multi_day_range_emits_end_at(self):
        html = _FULL_CARD_HTML.replace(
            '<div><span class="h3-style">May 10</span></div>',
            '<div><span class="h3-style">May 10</span><span class="h3-style">-</span><span class="h3-style">May 17</span></div>',
        ).replace(
            '<div class="upcoming-event-price"><span class="h6-style">2:00 PM</span></div>',
            '<div class="upcoming-event-price"><span class="h6-style">Multiple Showtimes</span></div>',
        )
        ev = _parse_card(
            _card(html),
            start_date=datetime(2026, 5, 10),
            end_date=datetime(2026, 5, 17),
        )
        assert ev is not None
        assert ev.all_day is True  # "Multiple Showtimes" has no parseable time
        assert ev.start_at == datetime(2026, 5, 10, 0, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 17, 23, 59, tzinfo=_CENTRAL)

    def test_external_venue_kept_literal(self):
        html = _FULL_CARD_HTML.replace(
            '<p class="small bold">Promenade Hall</p>',
            '<p class="small bold">Bethel Lutheran Church</p>',
        )
        ev = _parse_card(
            _card(html),
            start_date=datetime(2026, 5, 10),
            end_date=None,
        )
        assert ev is not None
        assert ev.venue_name == "Bethel Lutheran Church"

    def test_missing_venue_defaults_to_overture(self):
        html = _FULL_CARD_HTML.replace(
            '<p class="small bold">Promenade Hall</p>', "",
        )
        ev = _parse_card(
            _card(html),
            start_date=datetime(2026, 5, 10),
            end_date=None,
        )
        assert ev is not None
        assert ev.venue_name == _DEFAULT_VENUE_NAME

    def test_missing_title_skips_card(self):
        html = _FULL_CARD_HTML.replace(
            '<a class="upcoming-event-details-title" href="/tickets-events/2025-26-season/madison-ballet-innovation-ii/">Innovation II</a>',
            "",
        )
        ev = _parse_card(
            _card(html),
            start_date=datetime(2026, 5, 10),
            end_date=None,
        )
        assert ev is None

    def test_unparseable_time_falls_back_to_all_day(self):
        html = _FULL_CARD_HTML.replace(
            '<div class="upcoming-event-price"><span class="h6-style">2:00 PM</span></div>',
            '<div class="upcoming-event-price"><span class="h6-style">Free</span></div>',
        )
        ev = _parse_card(
            _card(html),
            start_date=datetime(2026, 5, 10),
            end_date=None,
        )
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 10, 0, 0, tzinfo=_CENTRAL)


# ---------------------------------------------------------------------------
# _extract_session_form: Tessitura redirect-stub form parsing
# ---------------------------------------------------------------------------

_SESSION_STUB_HTML = """<!DOCTYPE html>
<html><body>
<form id="tn-shared-session" action="https://www.overture.org/login/receive" method="post">
    <input id="EncryptedPayload_Value" name="EncryptedPayload.Value" type="hidden" value="abc&#x2B;def/ghi==" />
    <input id="ReturnUrl" name="ReturnUrl" type="hidden" value="https://www.overture.org/tickets-events/upcoming-events/" />
</form>
</body></html>
"""


class TestExtractSessionForm:
    def test_stub_parses(self):
        payload, return_url = _extract_session_form(_SESSION_STUB_HTML)
        # HTML-entity-decoded payload.
        assert payload == "abc+def/ghi=="
        assert return_url == "https://www.overture.org/tickets-events/upcoming-events/"

    def test_no_form_returns_none(self):
        # When the stub form is absent (e.g. a real page came back
        # directly), both fields are None.
        payload, return_url = _extract_session_form("<html><body>No form here</body></html>")
        assert payload is None and return_url is None


# ---------------------------------------------------------------------------
# _parse_schedule: detail-page ticketing block
# ---------------------------------------------------------------------------

_SCHEDULE_HTML = """
<ul class="pdp-tickets-list">
  <li class="pdp-tickets-item">
    <div class="pdp-tickets-item-info">
      <p class="tickets-date h4-style">Tue, May 12, 2026</p>
      <div class="pdp-tickets-item-info-details">
        <p class="tickets-time h4-style light">7:30 PM</p>
      </div>
    </div>
  </li>
  <li class="pdp-tickets-item">
    <div class="pdp-tickets-item-info">
      <p class="tickets-date h4-style">Sat, May 16, 2026</p>
      <p class="tickets-time h4-style light">2:00 PM</p>
    </div>
  </li>
  <li class="pdp-tickets-item">
    <div class="pdp-tickets-item-info">
      <p class="tickets-date h4-style">Sat, May 16, 2026</p>
      <p class="tickets-time h4-style light">7:30 PM</p>
    </div>
  </li>
  <!-- Duplicate of the first entry (Overture occasionally lists the
       same performance twice for accessibility variants) — must be
       collapsed by the dedup logic. -->
  <li class="pdp-tickets-item">
    <div class="pdp-tickets-item-info">
      <p class="tickets-date h4-style">Tue, May 12, 2026</p>
      <p class="tickets-time h4-style light">7:30 PM</p>
    </div>
  </li>
</ul>
"""


class TestParseSchedule:
    def test_extracts_unique_performances_sorted(self):
        sched = _parse_schedule(_SCHEDULE_HTML)
        # The Tue duplicate should be collapsed; Sat 2 PM should sort
        # before Sat 7:30 PM (both kept since matinee + evening are
        # distinct performances at the schedule level — the per-day
        # collapsing happens later in _expand_with_schedule).
        assert sched == [
            (date(2026, 5, 12), dtime(19, 30)),
            (date(2026, 5, 16), dtime(14, 0)),
            (date(2026, 5, 16), dtime(19, 30)),
        ]

    def test_no_block_returns_empty(self):
        assert _parse_schedule("<html><body>No ticketing here</body></html>") == []

    def test_missing_time_treated_as_none(self):
        html = """<ul class="pdp-tickets-list"><li class="pdp-tickets-item">
            <p class="tickets-date h4-style">Mon, June 1, 2026</p>
        </li></ul>"""
        assert _parse_schedule(html) == [(date(2026, 6, 1), None)]

    def test_garbage_date_skipped(self):
        html = """<ul class="pdp-tickets-list">
          <li class="pdp-tickets-item"><p class="tickets-date">not a date</p></li>
          <li class="pdp-tickets-item">
            <p class="tickets-date">Mon, June 1, 2026</p>
            <p class="tickets-time">8:00 PM</p>
          </li>
        </ul>"""
        assert _parse_schedule(html) == [(date(2026, 6, 1), dtime(20, 0))]


# ---------------------------------------------------------------------------
# _expand_with_schedule: per-performance event emission
# ---------------------------------------------------------------------------

def _base_event(title: str = "Test", source_url: str = "https://example.com/e") -> RawEvent:
    return RawEvent(
        title=title,
        start_at=datetime(2026, 5, 12, 0, 0, tzinfo=_CENTRAL),
        end_at=datetime(2026, 5, 17, 23, 59, tzinfo=_CENTRAL),
        venue_name=_DEFAULT_VENUE_NAME,
        venue_address=None,
        description="A multi-day run.",
        image_url=None,
        categories=["Theater & Stage"],
        all_day=True,
        source_name=_SOURCE_NAME,
        source_url=source_url,
    )


class TestExpandWithSchedule:
    def test_empty_schedule_keeps_base(self):
        base = _base_event()
        assert _expand_with_schedule(base, []) == [base]

    def test_one_performance_per_day(self):
        # Tue 7:30, Wed 7:30, Thu 7:30 — three distinct dates, one
        # performance each → three RawEvents, all with real times,
        # all_day=False, end_at=None.
        schedule = [
            (date(2026, 5, 12), dtime(19, 30)),
            (date(2026, 5, 13), dtime(19, 30)),
            (date(2026, 5, 14), dtime(19, 30)),
        ]
        events = _expand_with_schedule(_base_event(), schedule)
        assert len(events) == 3
        for ev in events:
            assert ev.all_day is False
            assert ev.end_at is None
            assert ev.start_at.hour == 19 and ev.start_at.minute == 30
        assert [e.start_at.date() for e in events] == [
            date(2026, 5, 12), date(2026, 5, 13), date(2026, 5, 14),
        ]

    def test_same_day_keeps_latest_time(self):
        # Sat matinee + evening → keep only the 7:30 PM evening.
        schedule = [
            (date(2026, 5, 16), dtime(14, 0)),
            (date(2026, 5, 16), dtime(19, 30)),
        ]
        events = _expand_with_schedule(_base_event(), schedule)
        assert len(events) == 1
        assert events[0].start_at == datetime(2026, 5, 16, 19, 30, tzinfo=_CENTRAL)

    def test_missing_time_falls_back_to_all_day(self):
        schedule = [(date(2026, 5, 12), None)]
        events = _expand_with_schedule(_base_event(), schedule)
        assert len(events) == 1
        assert events[0].all_day is True
        assert events[0].start_at == datetime(2026, 5, 12, 0, 0, tzinfo=_CENTRAL)

    def test_preserves_other_fields(self):
        base = _base_event(title="Hadestown")
        schedule = [(date(2026, 5, 12), dtime(19, 30))]
        ev = _expand_with_schedule(base, schedule)[0]
        # All non-time fields should be carried over from the base.
        assert ev.title == "Hadestown"
        assert ev.venue_name == base.venue_name
        assert ev.categories == base.categories
        assert ev.source_url == base.source_url
        assert ev.description == base.description
        assert ev.image_url == base.image_url


# ---------------------------------------------------------------------------
# Page-level: fetch() with both listing + detail fetches mocked out
# ---------------------------------------------------------------------------

_PAGE_HTML = (
    "<html><body><ul>"
    + _make_card(["May 10"], time_text="7:30 PM", title="First Event")
    + _make_card(["May 17"], time_text="2:00 PM", title="Second Event", venue="Bethel Lutheran Church")
    + _make_card(["November 24", "-", "November 29"], time_text="Multiple Showtimes", title="Long Run")
    + "</ul></body></html>"
)

# Detail page for "Long Run" — three performances Nov 24, 25, 29.
_LONG_RUN_DETAIL_HTML = """
<ul class="pdp-tickets-list">
  <li class="pdp-tickets-item">
    <p class="tickets-date">Tue, November 24, 2026</p>
    <p class="tickets-time">7:30 PM</p>
  </li>
  <li class="pdp-tickets-item">
    <p class="tickets-date">Wed, November 25, 2026</p>
    <p class="tickets-time">7:30 PM</p>
  </li>
  <li class="pdp-tickets-item">
    <p class="tickets-date">Sun, November 29, 2026</p>
    <p class="tickets-time">2:00 PM</p>
  </li>
</ul>
"""


def _pin_datetime(monkeypatch, year=2026, month=5, day=10):
    """Pin `datetime.now(...)` inside the scraper module so year
    inference is deterministic."""
    import app.scrapers.overture as ov_mod

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(year, month, day, tzinfo=tz)

    monkeypatch.setattr(ov_mod, "datetime", _FixedDateTime)


class TestFetchPageLevel:
    def test_fetch_parses_full_page(self, monkeypatch):
        """Bypass curl_cffi network. Detail fetches are counted so we
        can verify that only multi-day / "Multiple Showtimes" events
        trigger enrichment, and the Long Run gets expanded into per-day
        events with real times."""
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_listing",
            lambda: (object(), _PAGE_HTML),
        )
        fetch_calls: list[str] = []

        def _fake_detail(_session, url):
            fetch_calls.append(url)
            return _LONG_RUN_DETAIL_HTML

        monkeypatch.setattr(
            "app.scrapers.overture._fetch_detail_html", _fake_detail,
        )
        _pin_datetime(monkeypatch)

        events = OvertureSource().fetch()

        # Only the multi-day Long Run triggers detail-page enrichment;
        # the single-day specific-time cards skip the fetch entirely.
        assert len(fetch_calls) == 1

        titles = [e.title for e in events]
        assert titles[0] == "First Event"
        assert titles[1] == "Second Event"
        assert titles[2:] == ["Long Run", "Long Run", "Long Run"]
        long_runs = events[2:]
        assert [e.start_at.date() for e in long_runs] == [
            date(2026, 11, 24), date(2026, 11, 25), date(2026, 11, 29),
        ]
        assert all(e.all_day is False for e in long_runs)
        assert all(e.end_at is None for e in long_runs)
        assert events[0].start_at == datetime(2026, 5, 10, 19, 30, tzinfo=_CENTRAL)
        assert events[1].venue_name == "Bethel Lutheran Church"

    def test_fetch_falls_back_to_base_on_empty_detail(self, monkeypatch):
        """When the detail-page fetch returns an empty body (Imperva
        block, 5xx, etc.) the base list-card event is kept as-is."""
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_listing",
            lambda: (object(), _PAGE_HTML),
        )
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_detail_html",
            lambda _s, _u: "",
        )
        _pin_datetime(monkeypatch)

        events = OvertureSource().fetch()
        assert [e.title for e in events] == ["First Event", "Second Event", "Long Run"]
        long_run = events[2]
        assert long_run.all_day is True
        assert long_run.end_at == datetime(2026, 11, 29, 23, 59, tzinfo=_CENTRAL)

    def test_fetch_empty_listing_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_listing",
            lambda: (None, ""),
        )
        assert OvertureSource().fetch() == []
