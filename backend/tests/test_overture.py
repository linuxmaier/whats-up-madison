"""Unit tests for overture.py parsing helpers."""
from datetime import date, datetime, time as dtime

from bs4 import BeautifulSoup

from app.scrapers.overture import (
    _CENTRAL,
    _DEFAULT_VENUE_NAME,
    _SOURCE_NAME,
    _extract_date_pair,
    _extract_session_form,
    _map_categories,
    _normalize_venue,
    _parse_card,
    _parse_cards,
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
# Page-level: fetch() with the HTML fetch mocked out
# ---------------------------------------------------------------------------

_PAGE_HTML = (
    "<html><body><ul>"
    + _make_card(["May 10"], time_text="7:30 PM", title="First Event")
    + _make_card(["May 17"], time_text="2:00 PM", title="Second Event", venue="Bethel Lutheran Church")
    + _make_card(["November 24", "-", "November 29"], time_text="Multiple Showtimes", title="Long Run")
    + "</ul></body></html>"
)


class TestFetchPageLevel:
    def test_fetch_parses_full_page(self, monkeypatch):
        """Bypass the curl_cffi network handshake and feed the parser
        canned HTML; verify the full fetch() pipeline produces the
        expected RawEvents."""
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_events_html", lambda: _PAGE_HTML,
        )
        # Pin "today" so year inference is deterministic.
        import app.scrapers.overture as ov_mod

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 5, 10, tzinfo=tz)

        monkeypatch.setattr(ov_mod, "datetime", _FixedDateTime)

        events = OvertureSource().fetch()
        assert [e.title for e in events] == ["First Event", "Second Event", "Long Run"]
        assert events[0].start_at == datetime(2026, 5, 10, 19, 30, tzinfo=_CENTRAL)
        assert events[0].venue_name == _DEFAULT_VENUE_NAME  # Capitol Theater normalized
        assert events[1].venue_name == "Bethel Lutheran Church"
        assert events[2].all_day is True
        assert events[2].end_at == datetime(2026, 11, 29, 23, 59, tzinfo=_CENTRAL)

    def test_fetch_empty_page_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "app.scrapers.overture._fetch_events_html",
            lambda: "<html><body>no cards here</body></html>",
        )
        assert OvertureSource().fetch() == []
