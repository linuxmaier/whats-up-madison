"""Unit tests for high_noon.py parsing helpers."""
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.high_noon import (
    _CENTRAL,
    _build_description,
    _extract_categories,
    _extract_time,
    _parse_card,
    _parse_date,
)


def _card(html: str):
    """Return the parsed <article.event-card> element from the given fragment."""
    return BeautifulSoup(html, "lxml").select_one("article.event-card")


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_date(self):
        result = _parse_date("May 7, 2026")
        assert result == datetime(2026, 5, 7, 0, 0, tzinfo=_CENTRAL)

    def test_date_with_extra_whitespace(self):
        assert _parse_date("  May 7, 2026  ") == datetime(2026, 5, 7, tzinfo=_CENTRAL)

    def test_dst_winter_offset(self):
        # December → Central Standard Time (UTC-6)
        result = _parse_date("December 16, 2026")
        assert result is not None
        assert result.utcoffset().total_seconds() == -6 * 3600

    def test_dst_summer_offset(self):
        # July → Central Daylight Time (UTC-5)
        result = _parse_date("July 4, 2026")
        assert result is not None
        assert result.utcoffset().total_seconds() == -5 * 3600

    def test_invalid_returns_none(self):
        assert _parse_date("Tomorrow") is None
        assert _parse_date("2026-05-07") is None
        assert _parse_date("") is None


# ---------------------------------------------------------------------------
# _extract_time
# ---------------------------------------------------------------------------

class TestExtractTime:
    def test_show_preferred_over_doors(self):
        # When both are present, Show wins.
        assert _extract_time("Doors: 7:00 pm | Show: 8:00 pm") == dtime(20, 0)

    def test_show_only(self):
        assert _extract_time("Show: 4:00 pm") == dtime(16, 0)

    def test_doors_only_fallback(self):
        # Falls back to Doors when no Show is present.
        assert _extract_time("Doors: 6:30 pm") == dtime(18, 30)

    def test_morning_time(self):
        assert _extract_time("Doors: 10:00 am | Show: 10:30 am") == dtime(10, 30)

    def test_case_insensitive(self):
        assert _extract_time("DOORS: 7:00 PM | SHOW: 8:00 PM") == dtime(20, 0)

    def test_no_match_returns_none(self):
        assert _extract_time("") is None
        assert _extract_time("Time TBA") is None


# ---------------------------------------------------------------------------
# _extract_categories
# ---------------------------------------------------------------------------

class TestExtractCategories:
    def test_music_genre_collapses_to_music(self):
        card = _card('<article class="event-card tm_classifications-country"></article>')
        assert _extract_categories(card) == ["Music"]

    def test_multiple_genres_dedup_to_music(self):
        card = _card(
            '<article class="event-card tm_classifications-rock '
            'tm_classifications-punk tm_classifications-indie-rock"></article>'
        )
        assert _extract_categories(card) == ["Music"]

    def test_the_moth_maps_to_talks(self):
        card = _card(
            '<article class="event-card tm_classifications-the-moth '
            'tm_classifications-use-your-noggin"></article>'
        )
        assert _extract_categories(card) == ["Talks & Learning"]

    def test_arts_theatre_maps(self):
        card = _card('<article class="event-card tm_classifications-arts-theatre"></article>')
        assert _extract_categories(card) == ["Theater & Stage"]

    def test_community_civic_dropped(self):
        # community-civic is used loosely by the source (e.g. for music
        # showcases) — we intentionally drop it.
        card = _card('<article class="event-card tm_classifications-community-civic"></article>')
        assert _extract_categories(card) == []

    def test_unknown_classification_dropped(self):
        card = _card('<article class="event-card tm_classifications-mystery-genre"></article>')
        assert _extract_categories(card) == []

    def test_local_origin_tag_dropped(self):
        card = _card(
            '<article class="event-card tm_classifications-local '
            'tm_classifications-bluegrass"></article>'
        )
        assert _extract_categories(card) == ["Music"]

    def test_no_classifications(self):
        card = _card('<article class="event-card tm_event"></article>')
        assert _extract_categories(card) == []


# ---------------------------------------------------------------------------
# _build_description
# ---------------------------------------------------------------------------

class TestBuildDescription:
    def test_both_parts(self):
        assert _build_description("FPC LIVE PRESENTS", "with Kaleb Sanders") == \
            "FPC LIVE PRESENTS\nwith Kaleb Sanders"

    def test_presented_only(self):
        assert _build_description("THE MOTH", None) == "THE MOTH"

    def test_supporting_only(self):
        assert _build_description(None, "with openers") == "with openers"

    def test_neither(self):
        assert _build_description(None, None) is None
        assert _build_description("", "") is None


# ---------------------------------------------------------------------------
# _parse_card (integration of the helpers above against representative HTML)
# ---------------------------------------------------------------------------

_FULL_CARD_HTML = """
<article class="event-card post-6559 tm_event tm_classifications-country tm_venues-high-noon-saloon">
  <div class="event-inner">
    <div class="event-top">
      <a href="https://high-noon.com/event/kylie-morgan/">
        <img src="https://example.com/poster.jpg"/>
      </a>
    </div>
    <div class="event-bottom">
      <div class="event-presented-by">FPC LIVE PRESENTS</div>
      <div class="event-title"><a href="https://high-noon.com/event/kylie-morgan/">Kylie Morgan</a></div>
      <div class="event-supporting-acts">with Kaleb Sanders</div>
      <div class="event-venue">High Noon Saloon</div>
      <div class="event-date">May 7, 2026</div>
      <div class="event-times">Doors: 7:00 pm | Show: 8:00 pm</div>
    </div>
  </div>
</article>
"""


class TestParseCard:
    def test_full_card(self):
        ev = _parse_card(_card(_FULL_CARD_HTML))
        assert ev is not None
        assert ev.title == "Kylie Morgan"
        assert ev.start_at == datetime(2026, 5, 7, 20, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False
        assert ev.venue_name == "High Noon Saloon"
        assert ev.venue_address == "701 E. Washington Ave, Madison, WI 53703"
        assert ev.description == "FPC LIVE PRESENTS\nwith Kaleb Sanders"
        assert ev.categories == ["Music"]
        assert ev.source_name == "High Noon Saloon"
        assert ev.source_url == "https://high-noon.com/event/kylie-morgan/"

    def test_missing_time_falls_back_to_all_day(self):
        html = _FULL_CARD_HTML.replace(
            "Doors: 7:00 pm | Show: 8:00 pm", "Time TBA"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 7, 0, 0, tzinfo=_CENTRAL)

    def test_missing_date_skips_card(self):
        html = _FULL_CARD_HTML.replace("May 7, 2026", "")
        assert _parse_card(_card(html)) is None

    def test_missing_title_skips_card(self):
        html = _FULL_CARD_HTML.replace(
            '<a href="https://high-noon.com/event/kylie-morgan/">Kylie Morgan</a>',
            '',
            # only inside .event-title
        )
        # The .event-title still contains its outer div but no <a>; _parse_card returns None.
        assert _parse_card(_card(html)) is None

    def test_non_high_noon_venue_no_address(self):
        html = _FULL_CARD_HTML.replace(
            "<div class=\"event-venue\">High Noon Saloon</div>",
            "<div class=\"event-venue\">High Noon Patio</div>",
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.venue_name == "High Noon Patio"
        assert ev.venue_address is None

    def test_show_only_time(self):
        html = _FULL_CARD_HTML.replace(
            "Doors: 7:00 pm | Show: 8:00 pm", "Show: 4:00 pm"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.start_at == datetime(2026, 5, 7, 16, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False


def test_zoneinfo_central_matches():
    """Sanity check that the module's _CENTRAL is the expected zone."""
    assert _CENTRAL == ZoneInfo("America/Chicago")
