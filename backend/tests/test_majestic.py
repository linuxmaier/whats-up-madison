"""Unit tests for majestic.py parsing helpers."""
from datetime import datetime, time as dtime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.majestic import (
    _CENTRAL,
    _build_card_description,
    _extract_categories,
    _extract_event_description,
    _extract_time,
    _fetch_detail_description,
    _parse_card,
    _parse_date,
)


def _card(html: str):
    """Return the parsed <article.event-card> element from the given fragment."""
    return BeautifulSoup(html, "lxml").select_one("article.event-card")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_valid_date(self):
        assert _parse_date("May 15, 2026") == datetime(2026, 5, 15, 0, 0, tzinfo=_CENTRAL)

    def test_date_with_extra_whitespace(self):
        assert _parse_date("  May 15, 2026  ") == datetime(2026, 5, 15, tzinfo=_CENTRAL)

    def test_dst_winter_offset(self):
        result = _parse_date("December 16, 2026")
        assert result is not None
        assert result.utcoffset().total_seconds() == -6 * 3600

    def test_dst_summer_offset(self):
        result = _parse_date("July 4, 2026")
        assert result is not None
        assert result.utcoffset().total_seconds() == -5 * 3600

    def test_invalid_returns_none(self):
        assert _parse_date("Tomorrow") is None
        assert _parse_date("2026-05-15") is None
        assert _parse_date("") is None


# ---------------------------------------------------------------------------
# _extract_time
# ---------------------------------------------------------------------------

class TestExtractTime:
    def test_show_preferred_over_doors(self):
        assert _extract_time("Doors: 7:00 pm | Show: 8:00 pm") == dtime(20, 0)

    def test_show_only(self):
        assert _extract_time("Show: 4:00 pm") == dtime(16, 0)

    def test_doors_only_fallback(self):
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
    def test_jazz_maps_to_music(self):
        card = _card('<article class="event-card tm_classifications-jazz"></article>')
        assert _extract_categories(card) == ["Music"]

    def test_comedy_maps_to_open_mic_and_comedy(self):
        card = _card('<article class="event-card tm_classifications-comedy"></article>')
        assert _extract_categories(card) == ["Open Mic & Comedy"]

    def test_hyperpop_and_pop_dedup_to_music(self):
        # The Club Slayyy card carried multiple hyperpop/pop variants.
        card = _card(
            '<article class="event-card tm_classifications-hyperpop '
            'tm_classifications-electro-pop tm_classifications-pop"></article>'
        )
        assert _extract_categories(card) == ["Music"]

    def test_dance_party_maps_to_music(self):
        card = _card('<article class="event-card tm_classifications-dance-party"></article>')
        assert _extract_categories(card) == ["Music"]

    def test_unknown_classification_dropped(self):
        card = _card('<article class="event-card tm_classifications-mystery-genre"></article>')
        assert _extract_categories(card) == []

    def test_no_classifications(self):
        card = _card('<article class="event-card tm_event"></article>')
        assert _extract_categories(card) == []


# ---------------------------------------------------------------------------
# _build_card_description
# ---------------------------------------------------------------------------

class TestBuildCardDescription:
    def test_both_parts(self):
        assert _build_card_description("FPC LIVE PRESENTS", "with Mama Digdown's Brass Band") == \
            "FPC LIVE PRESENTS\nwith Mama Digdown's Brass Band"

    def test_presented_only(self):
        assert _build_card_description("FPC LIVE PRESENTS", None) == "FPC LIVE PRESENTS"

    def test_supporting_only(self):
        assert _build_card_description(None, "with openers") == "with openers"

    def test_neither(self):
        assert _build_card_description(None, None) is None
        assert _build_card_description("", "") is None


# ---------------------------------------------------------------------------
# _extract_event_description (detail-page section extraction)
# ---------------------------------------------------------------------------

_DETAIL_EVENT_DESC_ONLY = """
<html><body><main id="main">
<section class="event-section">
  <h2 class="wp-block-heading">Event Description</h2>
  <div class="event-section-content read-more">
    <p>A dance party featuring music from The Strokes, The Killers, YYY's.</p>
  </div>
</section>
</main></body></html>
"""

_DETAIL_EVENT_DESC_AND_BIO = """
<html><body><main id="main">
<section class="event-section">
  <h2 class="wp-block-heading">Event Description</h2>
  <div class="event-section-content read-more">
    <p>Show note: rescheduled to May 21, 2026.</p>
  </div>
</section>
<section class="event-section">
  <h2 class="wp-block-heading">Jacqueline Novak Bio</h2>
  <div class="event-section-content read-more">
    <p>Jacqueline Novak is a touring comedian. (Long bio — should be dropped.)</p>
  </div>
</section>
</main></body></html>
"""

_DETAIL_NO_SECTIONS = """
<html><body><main id="main">
<div class="event-info">
  <span>Event Date</span>
  <div>Friday, May 15</div>
</div>
</main></body></html>
"""

_DETAIL_HTML_ENTITIES = """
<html><body><main id="main">
<section class="event-section">
  <h2 class="wp-block-heading">Event Description</h2>
  <div class="event-section-content"><p>Doors at 7&#8217;ish &#8211; bring a friend.</p></div>
</section>
</main></body></html>
"""


class TestExtractEventDescription:
    def test_event_description_only(self):
        text = _extract_event_description(_soup(_DETAIL_EVENT_DESC_ONLY))
        assert text is not None
        assert "dance party" in text
        assert "The Strokes" in text

    def test_event_description_with_bio_drops_bio(self):
        text = _extract_event_description(_soup(_DETAIL_EVENT_DESC_AND_BIO))
        assert text is not None
        assert "rescheduled" in text
        assert "Bio" not in text
        assert "touring comedian" not in text

    def test_no_event_sections_returns_none(self):
        assert _extract_event_description(_soup(_DETAIL_NO_SECTIONS)) is None

    def test_html_entities_unescaped(self):
        text = _extract_event_description(_soup(_DETAIL_HTML_ENTITIES))
        assert text is not None
        # clean_html_text() should decode &#8217; → ’ and &#8211; → –
        assert "’" in text or "'" in text
        assert "–" in text or "-" in text


# ---------------------------------------------------------------------------
# _fetch_detail_description (HTTP-stubbed)
# ---------------------------------------------------------------------------

class TestFetchDetailDescription:
    def test_returns_section_text_on_success(self):
        class _FakeResp:
            content = _DETAIL_EVENT_DESC_ONLY.encode()

        with patch("app.scrapers.majestic.http_get_with_retry", return_value=_FakeResp()):
            text = _fetch_detail_description("https://majesticmadison.com/event/x/")
        assert text is not None
        assert "dance party" in text

    def test_drops_bio_section(self):
        class _FakeResp:
            content = _DETAIL_EVENT_DESC_AND_BIO.encode()

        with patch("app.scrapers.majestic.http_get_with_retry", return_value=_FakeResp()):
            text = _fetch_detail_description("https://majesticmadison.com/event/x/")
        assert text is not None
        assert "rescheduled" in text
        assert "touring comedian" not in text

    def test_returns_none_when_section_absent(self):
        class _FakeResp:
            content = _DETAIL_NO_SECTIONS.encode()

        with patch("app.scrapers.majestic.http_get_with_retry", return_value=_FakeResp()):
            assert _fetch_detail_description("https://majesticmadison.com/event/x/") is None

    def test_returns_none_on_http_error(self):
        with patch(
            "app.scrapers.majestic.http_get_with_retry",
            side_effect=RuntimeError("boom"),
        ):
            assert _fetch_detail_description("https://majesticmadison.com/event/x/") is None


# ---------------------------------------------------------------------------
# _parse_card (integration against representative HTML captured from the live calendar)
# ---------------------------------------------------------------------------

_FULL_CARD_HTML = """
<article class="event-card post-9182 tm_event tm_classifications-jazz tm_venues-majestic-theatre">
  <div class="event-inner">
    <div class="event-top">
      <a href="https://majesticmadison.com/event/rebirth-brass-band/">
        <img src="https://majesticmadison.com/wp-content/uploads/sites/8/2026/03/RBB.jpg"/>
      </a>
    </div>
    <div class="event-bottom">
      <div class="event-presented-by">FPC LIVE PRESENTS</div>
      <div class="event-title"><a href="https://majesticmadison.com/event/rebirth-brass-band/">Rebirth Brass Band</a></div>
      <div class="event-supporting-acts">with Mama Digdown's Brass Band</div>
      <div class="event-date">May 15, 2026</div>
      <div class="event-times">Doors: 7:00 pm | Show: 8:00 pm</div>
    </div>
  </div>
</article>
"""


class TestParseCard:
    def test_full_card(self):
        ev = _parse_card(_card(_FULL_CARD_HTML))
        assert ev is not None
        assert ev.title == "Rebirth Brass Band"
        assert ev.start_at == datetime(2026, 5, 15, 20, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False
        # Venue is hardcoded to the Majestic, not parsed from the card —
        # the calendar lists multiple FPC venues elsewhere but this scraper
        # only runs against the Majestic calendar URL.
        assert ev.venue_name == "Majestic Theatre"
        assert ev.venue_address == "115 King St, Madison, WI 53703"
        assert ev.description == "FPC LIVE PRESENTS\nwith Mama Digdown's Brass Band"
        assert ev.image_url == "https://majesticmadison.com/wp-content/uploads/sites/8/2026/03/RBB.jpg"
        assert ev.categories == ["Music"]
        assert ev.source_name == "Majestic Theatre"
        assert ev.source_url == "https://majesticmadison.com/event/rebirth-brass-band/"

    def test_missing_time_falls_back_to_all_day(self):
        html = _FULL_CARD_HTML.replace(
            "Doors: 7:00 pm | Show: 8:00 pm", "Time TBA"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 15, 0, 0, tzinfo=_CENTRAL)

    def test_missing_date_skips_card(self):
        html = _FULL_CARD_HTML.replace("May 15, 2026", "")
        assert _parse_card(_card(html)) is None

    def test_missing_title_skips_card(self):
        # Remove the inner <a> from the .event-title block.
        html = _FULL_CARD_HTML.replace(
            '<a href="https://majesticmadison.com/event/rebirth-brass-band/">Rebirth Brass Band</a>',
            '',
        )
        assert _parse_card(_card(html)) is None

    def test_show_only_time(self):
        html = _FULL_CARD_HTML.replace(
            "Doors: 7:00 pm | Show: 8:00 pm", "Show: 4:00 pm"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.start_at == datetime(2026, 5, 15, 16, 0, tzinfo=_CENTRAL)
        assert ev.all_day is False

    def test_comedy_classification(self):
        html = _FULL_CARD_HTML.replace(
            "tm_classifications-jazz", "tm_classifications-comedy"
        )
        ev = _parse_card(_card(html))
        assert ev is not None
        assert ev.categories == ["Open Mic & Comedy"]


def test_zoneinfo_central_matches():
    """Sanity check that the module's _CENTRAL is the expected zone."""
    assert _CENTRAL == ZoneInfo("America/Chicago")
