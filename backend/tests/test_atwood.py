"""Unit tests for atwood.py parsing helpers."""
from datetime import datetime, time as dtime

from bs4 import BeautifulSoup

from app.scrapers.atwood import (
    _CENTRAL,
    _DEFAULT_VENUE_NAME,
    _normalize_address,
    _parse_card,
    _parse_time,
    AtwoodMusicHallSource,
)


def _card(html: str):
    return BeautifulSoup(html, "lxml").select_one("article.eventlist-event")


# ---------------------------------------------------------------------------
# _parse_time
# ---------------------------------------------------------------------------

class TestParseTime:
    def test_evening(self):
        assert _parse_time("8:00 PM") == dtime(20, 0)

    def test_morning(self):
        assert _parse_time("10:30 AM") == dtime(10, 30)

    def test_lowercase(self):
        assert _parse_time("7:30 pm") == dtime(19, 30)

    def test_extra_whitespace(self):
        assert _parse_time("  8:00 PM  ") == dtime(20, 0)

    def test_garbage_returns_none(self):
        assert _parse_time("") is None
        assert _parse_time("TBA") is None
        assert _parse_time("8:00") is None  # no am/pm


# ---------------------------------------------------------------------------
# _normalize_address
# ---------------------------------------------------------------------------

class TestNormalizeAddress:
    def test_strip_united_states(self):
        assert (
            _normalize_address("1925 Winnebago Avenue Madison, WI, 53704 United States")
            == "1925 Winnebago Avenue Madison, WI 53704"
        )

    def test_strip_united_states_lowercase(self):
        assert (
            _normalize_address("123 Main St Madison, WI, 53703 united states")
            == "123 Main St Madison, WI 53703"
        )

    def test_no_united_states(self):
        # Already-normalized input passes through unchanged.
        assert (
            _normalize_address("1925 Winnebago Avenue Madison, WI 53704")
            == "1925 Winnebago Avenue Madison, WI 53704"
        )

    def test_zip_comma_collapsed(self):
        assert (
            _normalize_address("2090 Atwood Avenue Madison, WI, 53704")
            == "2090 Atwood Avenue Madison, WI 53704"
        )

    def test_empty_returns_none(self):
        assert _normalize_address("") is None
        assert _normalize_address("   ") is None


# ---------------------------------------------------------------------------
# _parse_card (integration of helpers against representative HTML)
# ---------------------------------------------------------------------------

_FULL_CARD_HTML = """
<article class="eventlist-event eventlist-event--upcoming eventlist-event--hasimg eventlist-hasimg">
  <a href="/shows/2026-5-9" class="eventlist-column-thumbnail content-fill">
    <img data-image="https://images.example.com/data-image.jpg" src="https://images.example.com/src.jpg"/>
  </a>
  <div class="eventlist-column-info">
    <h1 class="eventlist-title"><a href="/shows/2026-5-9" class="eventlist-title-link">Boogie Down Broadway</a></h1>
    <ul class="eventlist-meta event-meta">
      <li class="eventlist-meta-item eventlist-meta-date event-meta-item">
        <time class="event-date" datetime="2026-05-09">Saturday, May 9, 2026</time>
      </li>
      <li class="eventlist-meta-item eventlist-meta-time event-meta-item">
        <span class="event-time-localized">
          <time class="event-time-localized-start" datetime="2026-05-09">8:00 PM</time>
          <span class="event-datetime-divider"></span>
          <time class="event-time-localized-end" datetime="2026-05-09">9:00 PM</time>
        </span>
      </li>
      <li class="eventlist-meta-item eventlist-meta-address event-meta-item">
        Atwood Music Hall
        <a href="http://maps.google.com?q=1925 Winnebago Avenue Madison, WI, 53704 United States" class="eventlist-meta-address-maplink">(map)</a>
      </li>
    </ul>
    <div class="eventlist-excerpt"><p>Doors 6PM Show 7PM</p><p>Early Bird: $25</p></div>
  </div>
</article>
"""


class TestParseCard:
    def test_full_card(self):
        ev = _parse_card(_card(_FULL_CARD_HTML))
        assert ev is not None
        assert ev.title == "Boogie Down Broadway"
        assert ev.start_at == datetime(2026, 5, 9, 20, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 9, 21, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False
        assert ev.venue_name == "Atwood Music Hall"
        assert ev.venue_address == "1925 Winnebago Avenue Madison, WI 53704"
        assert ev.image_url == "https://images.example.com/data-image.jpg"
        assert ev.description == "Doors 6PM Show 7PM\n\nEarly Bird: $25"
        assert ev.categories == []
        assert ev.source_name == "Atwood Music Hall"
        assert ev.source_url == "https://www.theatwoodmusichall.com/shows/2026-5-9"

    def test_other_venue_barrymore(self):
        html = _FULL_CARD_HTML.replace(
            "Atwood Music Hall\n        <a href=\"http://maps.google.com?q=1925 Winnebago Avenue Madison, WI, 53704 United States\"",
            "Barrymore Theatre\n        <a href=\"http://maps.google.com?q=2090 Atwood Avenue Madison, WI, 53704 United States\"",
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.venue_name == "Barrymore Theatre"
        assert ev.venue_address == "2090 Atwood Avenue Madison, WI 53704"

    def test_missing_time_falls_back_to_all_day(self):
        html = _FULL_CARD_HTML.replace(
            '<li class="eventlist-meta-item eventlist-meta-time event-meta-item">'
            '\n        <span class="event-time-localized">'
            '\n          <time class="event-time-localized-start" datetime="2026-05-09">8:00 PM</time>'
            '\n          <span class="event-datetime-divider"></span>'
            '\n          <time class="event-time-localized-end" datetime="2026-05-09">9:00 PM</time>'
            '\n        </span>'
            '\n      </li>',
            "",
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 9, 0, 0, tzinfo=_CENTRAL)
        assert ev.end_at is None

    def test_end_time_after_midnight(self):
        html = _FULL_CARD_HTML.replace(
            ">8:00 PM<", ">11:00 PM<"
        ).replace(
            ">9:00 PM<", ">1:00 AM<"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        # 11 PM May 9 → 1 AM May 10
        assert ev.start_at == datetime(2026, 5, 9, 23, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 10, 1, 0, tzinfo=_CENTRAL)

    def test_missing_title_skips_card(self):
        html = _FULL_CARD_HTML.replace(
            '<a href="/shows/2026-5-9" class="eventlist-title-link">Boogie Down Broadway</a>',
            "",
        )
        assert _parse_card(_card(html)) is None

    def test_missing_date_skips_card(self):
        html = _FULL_CARD_HTML.replace(
            '<time class="event-date" datetime="2026-05-09">Saturday, May 9, 2026</time>',
            "",
        )
        assert _parse_card(_card(html)) is None

    def test_image_falls_back_to_src(self):
        html = _FULL_CARD_HTML.replace(
            'data-image="https://images.example.com/data-image.jpg" ', ""
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.image_url == "https://images.example.com/src.jpg"

    def test_missing_address_falls_back_to_default_venue(self):
        # Card with no address li at all.
        html = _FULL_CARD_HTML.replace(
            '<li class="eventlist-meta-item eventlist-meta-address event-meta-item">'
            '\n        Atwood Music Hall'
            '\n        <a href="http://maps.google.com?q=1925 Winnebago Avenue Madison, WI, 53704 United States" class="eventlist-meta-address-maplink">(map)</a>'
            '\n      </li>',
            "",
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.venue_name == _DEFAULT_VENUE_NAME
        assert ev.venue_address is None


# ---------------------------------------------------------------------------
# Page-level filtering: past events skipped
# ---------------------------------------------------------------------------

_PAGE_HTML = (
    "<html><body>"
    + _FULL_CARD_HTML
    # A second card with --past should be dropped.
    + _FULL_CARD_HTML.replace(
        "eventlist-event eventlist-event--upcoming",
        "eventlist-event eventlist-event--past",
    ).replace(
        "Boogie Down Broadway", "Past Show"
    )
    + "</body></html>"
)


class TestPageLevelFiltering:
    def test_past_events_skipped(self, monkeypatch):
        """`fetch()` should select only --upcoming articles."""
        class _Resp:
            content = _PAGE_HTML.encode("utf-8")

        def fake_get(url, **kwargs):
            return _Resp()

        monkeypatch.setattr("app.scrapers.atwood.http_get_with_retry", fake_get)

        events = AtwoodMusicHallSource().fetch()
        titles = [e.title for e in events]
        assert "Boogie Down Broadway" in titles
        assert "Past Show" not in titles
