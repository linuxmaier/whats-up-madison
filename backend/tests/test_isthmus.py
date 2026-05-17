"""Unit tests for isthmus.py detail-page extraction helpers."""
from datetime import date
from unittest.mock import patch

from bs4 import BeautifulSoup

from app.scrapers.isthmus import _CATEGORY_MAP, _extract_categories, _extract_venue_address, _parse_ical


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


class TestExtractCategories:
    def test_single_tag_maps(self):
        # The exact shape Isthmus emits for the issue's example event.
        html = """
            <div class="mp_tag_cat_1">
                <label class="">Event Categories</label>
                <span class="Music ">Music</span>
            </div>
        """
        assert _extract_categories(_soup(html)) == ["Music"]

    def test_multi_tag_drops_unmapped_and_preserves_order(self):
        # Real-world Isthmus page: "Arts Notices, Music". Arts Notices is
        # intentionally dropped; Music passes through.
        html = """
            <div class="mp_tag_cat_1">
                <label class="">Event Categories</label>
                <span class="Arts-Notices ">Arts Notices</span>,
                <span class="Music ">Music</span>
            </div>
        """
        assert _extract_categories(_soup(html)) == ["Music"]

    def test_multiple_mapped_tags_preserve_source_order(self):
        html = """
            <div class="mp_tag_cat_1">
                <label class="">Event Categories</label>
                <span class="Fundraisers ">Fundraisers</span>,
                <span class="Recreation ">Recreation</span>
            </div>
        """
        # Source order is Fundraisers, Recreation — preserved after mapping.
        assert _extract_categories(_soup(html)) == ["Volunteer & Causes", "Sports & Recreation"]

    def test_two_tags_collapsing_to_same_canonical_dedup(self):
        # Both "Food & Drink" and "Farmers' Markets" map to Food & Drink.
        html = """
            <div class="mp_tag_cat_1">
                <label class="">Event Categories</label>
                <span class="Farmers-Markets ">Farmers' Markets</span>,
                <span class="Food-Drink ">Food &amp; Drink</span>
            </div>
        """
        assert _extract_categories(_soup(html)) == ["Food & Drink"]

    def test_missing_category_block_returns_empty(self):
        # 404 pages and event pages without categories simply lack the div.
        html = "<html><body><h1>No categories here</h1></body></html>"
        assert _extract_categories(_soup(html)) == []

    def test_all_unmapped_returns_empty(self):
        # Falls through to the LLM tagging pass rather than emitting wrong tags.
        html = """
            <div class="mp_tag_cat_1">
                <label class="">Event Categories</label>
                <span class="Special-Interests ">Special Interests</span>,
                <span class="Seniors ">Seniors</span>
            </div>
        """
        assert _extract_categories(_soup(html)) == []


class TestExtractVenueAddress:
    def test_full_postaladdress_markup(self):
        # Matches the real Isthmus schema.org PostalAddress shape confirmed via curl.
        html = """
            <span class="address">
              <span itemprop="address" itemscope="" itemtype="https://schema.org/PostalAddress">
                <span itemprop="streetAddress">101 N. Main St.</span>,
                <span itemprop="addressLocality">Verona</span>,
                <span itemprop="addressRegion">Wisconsin</span>
                <span itemprop="postalCode">53593</span>
              </span>
            </span>
        """
        assert _extract_venue_address(_soup(html)) == "101 N. Main St., Verona, Wisconsin 53593"

    def test_missing_address_span_returns_none(self):
        html = "<html><body><h1>No address here</h1></body></html>"
        assert _extract_venue_address(_soup(html)) is None

    def test_extra_whitespace_normalized(self):
        html = """<span class="address">  123   Main St. ,  Madison ,  Wisconsin   53703  </span>"""
        assert _extract_venue_address(_soup(html)) == "123 Main St. , Madison , Wisconsin 53703"


_MINIMAL_SOUP = BeautifulSoup("<html><body></body></html>", "lxml")

# Shared URL / date values for _parse_ical tests.
# between() needs start < end to include the event date (same start==end returns nothing).
_TEST_START = date(2026, 5, 15)
_TEST_END = date(2026, 5, 17)
_TEST_URL = "https://isthmus.com/events/test-event/?occ_dtstart=2026-05-16T19:00"
_TEST_URL_MAP: dict = {("test event", "2026-05-16", ""): _TEST_URL}
_TEST_TITLE_DATE_MAP: dict = {("test event", "2026-05-16"): _TEST_URL}

_ICAL_NO_DTEND = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/Chicago:20260516T190000
SUMMARY:Test Event
END:VEVENT
END:VCALENDAR"""

_ICAL_WITH_DTEND = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=America/Chicago:20260516T190000
DTEND;TZID=America/Chicago:20260516T210000
SUMMARY:Test Event
END:VEVENT
END:VCALENDAR"""

_SOUP_WITH_ADDRESS = BeautifulSoup("""
<html><body>
  <span class="address">
    <span itemprop="address" itemscope="" itemtype="https://schema.org/PostalAddress">
      <span itemprop="streetAddress">1326 MacArthur Road</span>,
      <span itemprop="addressLocality">Madison</span>,
      <span itemprop="addressRegion">Wisconsin</span>
      <span itemprop="postalCode">53714</span>
    </span>
  </span>
</body></html>
""", "lxml")


class TestParseIcal:
    def test_no_dtend_yields_null_end_at(self):
        # recurring_ical_events fills DTEND=DTSTART when the feed has no DTEND;
        # _parse_ical must treat that zero-duration result as end_at=None.
        with patch("app.scrapers.isthmus._fetch_detail_soup", return_value=_MINIMAL_SOUP), \
             patch("time.sleep"):
            events = _parse_ical(
                _TEST_START, _TEST_END,
                _TEST_URL_MAP, _TEST_TITLE_DATE_MAP,
                ical_content=_ICAL_NO_DTEND,
            )
        assert len(events) == 1
        assert events[0].end_at is None

    def test_explicit_dtend_preserved(self):
        # When an event has a real end time, it must survive the fix.
        with patch("app.scrapers.isthmus._fetch_detail_soup", return_value=_MINIMAL_SOUP), \
             patch("time.sleep"):
            events = _parse_ical(
                _TEST_START, _TEST_END,
                _TEST_URL_MAP, _TEST_TITLE_DATE_MAP,
                ical_content=_ICAL_WITH_DTEND,
            )
        assert len(events) == 1
        assert events[0].end_at is not None
        assert events[0].end_at != events[0].start_at

    def test_venue_address_extracted_from_detail_page(self):
        with patch("app.scrapers.isthmus._fetch_detail_soup", return_value=_SOUP_WITH_ADDRESS), \
             patch("time.sleep"):
            events = _parse_ical(
                _TEST_START, _TEST_END,
                _TEST_URL_MAP, _TEST_TITLE_DATE_MAP,
                ical_content=_ICAL_NO_DTEND,
            )
        assert len(events) == 1
        assert events[0].venue_address == "1326 MacArthur Road, Madison, Wisconsin 53714"

    def test_venue_address_null_when_detail_page_unavailable(self):
        with patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _parse_ical(
                _TEST_START, _TEST_END,
                _TEST_URL_MAP, _TEST_TITLE_DATE_MAP,
                ical_content=_ICAL_NO_DTEND,
            )
        assert len(events) == 1
        assert events[0].venue_address is None


class TestCategoryMap:
    def test_all_mapped_values_are_in_canonical_taxonomy(self):
        # Guard against a future taxonomy rename leaving a stale entry behind.
        from app.categories import CATEGORIES
        for source_tag, mapped in _CATEGORY_MAP.items():
            assert mapped in CATEGORIES, f"{source_tag!r} maps to {mapped!r}, which is not a canonical category"
