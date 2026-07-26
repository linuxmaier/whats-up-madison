"""Unit tests for isthmus.py: detail-page extraction helpers + RSS feed parser."""
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.isthmus import (
    _CATEGORY_MAP,
    _build_events_from_rss,
    _extract_categories,
    _extract_description,
    _extract_venue_address,
    _parse_clock,
    _parse_rss_title,
)

_CENTRAL = ZoneInfo("America/Chicago")


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


class TestExtractDescription:
    def test_strips_media_carousel_image_caption(self):
        # Mirrors the real Jim Erickson page (issue #211): the hero image
        # card is a div.single.media-carousel containing the "× Expand",
        # photographer credit, and image alt text. Without stripping, all of
        # that text prefixes the actual blurb in p.lead.
        html = """
            <html><body>
              <div id="content">
                <div>
                  <div class="single media-carousel">× Expand Laurie Lang Jim Erickson</div>
                  <p class="lead">Jazz, 5:30 pm Saturdays. Free.</p>
                </div>
              </div>
            </body></html>
        """
        result = _extract_description(_soup(html), "https://example.test/jim")
        assert result == "Jazz, 5:30 pm Saturdays. Free."
        assert "× Expand" not in result
        assert "Laurie Lang" not in result

    def test_preserves_full_text_when_no_carousel(self):
        # Longer-form events (e.g. Kids on the Prairie) have no media-carousel
        # and several paragraphs of body copy. The strip must be a no-op there.
        html = """
            <html><body>
              <div id="content">
                <div>
                  <p class="lead">Lead paragraph with the intro blurb.</p>
                  <p>Second paragraph with more detail about the event.</p>
                  <p>Third paragraph with logistics.</p>
                </div>
              </div>
            </body></html>
        """
        result = _extract_description(_soup(html), "https://example.test/long")
        assert "Lead paragraph with the intro blurb." in result
        assert "Second paragraph with more detail about the event." in result
        assert "Third paragraph with logistics." in result

    def test_strips_generic_figure_node(self):
        # Forward safety: if Isthmus ever swaps the media-carousel div for a
        # standard <figure> layout, the strip should still drop it.
        html = """
            <html><body>
              <div id="content">
                <div>
                  <figure><img src="x.jpg" alt="Show photo"><figcaption>Photo: Alice</figcaption></figure>
                  <p>Actual description body.</p>
                </div>
              </div>
            </body></html>
        """
        result = _extract_description(_soup(html), "https://example.test/fig")
        assert result == "Actual description body."
        assert "Photo: Alice" not in result


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


class TestParseRssTitle:
    def test_title_with_start_only(self):
        # Most common shape: timed event with single time.
        name, start, end, venue = _parse_rss_title(
            "Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern"
        )
        assert name == "Open Mic"
        assert start == "10:00 PM"
        assert end is None
        assert venue == "Mickey's Tavern"

    def test_title_with_start_and_end(self):
        # Regression for issue #210: when iCal had no DTEND we wrote
        # end_at == start_at. RSS shows the explicit end time when there is
        # one; the parser must extract it.
        name, start, end, venue = _parse_rss_title(
            "American Red Cross Blood Drive - May 18, 2026 11:30 AM - 4:30 PM @ Garver Feed Mill"
        )
        assert name == "American Red Cross Blood Drive"
        assert start == "11:30 AM"
        assert end == "4:30 PM"
        assert venue == "Garver Feed Mill"

    def test_title_all_day_no_time(self):
        # "RSVP for The Record Club" — no time in title means all-day.
        name, start, end, venue = _parse_rss_title(
            "RSVP for The Record Club - May 18, 2026 @ UW Memorial Library"
        )
        assert name == "RSVP for The Record Club"
        assert start is None
        assert end is None
        assert venue == "UW Memorial Library"

    def test_title_no_venue(self):
        # Some items omit the @ Venue clause.
        name, start, end, venue = _parse_rss_title(
            "Lupus Support Group for Women of Color - May 18, 2026 6:00 PM"
        )
        assert name == "Lupus Support Group for Women of Color"
        assert start == "6:00 PM"
        assert end is None
        assert venue is None

    def test_title_venue_contains_comma(self):
        # Venues with comma-separated qualifiers (city, state, etc).
        _, _, _, venue = _parse_rss_title(
            "Sports for Active Seniors Hiking - May 18, 2026 10:00 AM @ Lake Kegonsa State Park, Stoughton"
        )
        assert venue == "Lake Kegonsa State Park, Stoughton"

    def test_title_unparseable_falls_back_to_raw(self):
        # Don't drop events the regex can't handle — keep the title intact and
        # let the caller fall back to occ_dtstart for the start datetime.
        name, start, end, venue = _parse_rss_title("Some unparseable thing without date")
        assert name == "Some unparseable thing without date"
        assert (start, end, venue) == (None, None, None)


class TestParseClock:
    def test_combines_time_with_date_in_central(self):
        dt = _parse_clock("7:30 PM", date(2026, 5, 18))
        assert dt == datetime(2026, 5, 18, 19, 30, tzinfo=_CENTRAL)

    def test_handles_morning(self):
        dt = _parse_clock("9:00 AM", date(2026, 5, 18))
        assert dt == datetime(2026, 5, 18, 9, 0, tzinfo=_CENTRAL)


def _rss_response(items: list[str]) -> MagicMock:
    """Build a MagicMock response shaped like httpx.Response for one RSS page."""
    body = "<?xml version='1.0'?><rss><channel>" + "".join(items) + "</channel></rss>"
    resp = MagicMock()
    resp.content = body.encode()
    return resp


def _empty_rss_response() -> MagicMock:
    return _rss_response([])


class TestBuildEventsFromRss:
    def _patch_http(self, page_responses: list[MagicMock]):
        """Return a side_effect function that returns each page's response in order."""
        calls = {"i": 0}

        def side_effect(url, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            if i < len(page_responses):
                return page_responses[i]
            return _empty_rss_response()

        return side_effect

    def test_timed_event_parses_start_and_end(self):
        item = """
          <item>
            <title>American Red Cross Blood Drive - May 18, 2026 11:30 AM - 4:30 PM @ Garver Feed Mill</title>
            <link>https://isthmus.com/events/red-cross/?occ_dtstart=2026-05-18T11:30</link>
            <description>Donate blood at Garver Feed Mill.</description>
          </item>
        """
        page1 = _rss_response([item])
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_http([page1])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 1
        ev = events[0]
        assert ev.title == "American Red Cross Blood Drive"
        assert ev.start_at == datetime(2026, 5, 18, 11, 30, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 18, 16, 30, tzinfo=_CENTRAL)
        assert ev.end_at != ev.start_at  # regression for #210
        assert ev.venue_name == "Garver Feed Mill"
        assert ev.all_day is False
        assert ev.source_url.endswith("?occ_dtstart=2026-05-18T11:30")

    def test_timed_event_with_start_only_has_null_end(self):
        item = """
          <item>
            <title>Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern</title>
            <link>https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00</link>
            <description>Free.</description>
          </item>
        """
        page1 = _rss_response([item])
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_http([page1])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 1
        assert events[0].end_at is None
        assert events[0].all_day is False

    def test_no_time_in_title_marks_all_day(self):
        # Title has no time → all-day, even though occ_dtstart=...T00:00 is
        # ambiguous (could be a real midnight event in principle).
        item = """
          <item>
            <title>RSVP for The Record Club - May 18, 2026 @ UW Memorial Library</title>
            <link>https://isthmus.com/events/record-club/?occ_dtstart=2026-05-18T00:00</link>
            <description>Book club for albums.</description>
          </item>
        """
        page1 = _rss_response([item])
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_http([page1])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 1
        ev = events[0]
        assert ev.all_day is True
        assert ev.start_at == datetime(2026, 5, 18, 0, 0, tzinfo=_CENTRAL)
        assert ev.venue_name == "UW Memorial Library"

    def test_pagination_stops_when_all_items_past_window(self):
        # Page 1 has an in-window item, page 2 has only out-of-window items
        # (after the end date) → walker exits without fetching page 3.
        in_window = """
          <item>
            <title>Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern</title>
            <link>https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00</link>
            <description>Free.</description>
          </item>
        """
        past_window = """
          <item>
            <title>Future Show - June 30, 2026 7:00 PM @ Future Venue</title>
            <link>https://isthmus.com/events/future/?occ_dtstart=2026-06-30T19:00</link>
            <description>Out of window.</description>
          </item>
        """
        page1 = _rss_response([in_window])
        page2 = _rss_response([past_window])
        page3 = _rss_response([])  # should not be reached
        responses = [page1, page2, page3]
        calls = {"i": 0}

        def side_effect(url, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            return responses[i] if i < len(responses) else _empty_rss_response()

        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=side_effect) as http, \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 1
        # Page 1 (in-window) and page 2 (decides to stop) fetched; page 3 skipped.
        assert http.call_count == 2

    def test_pagination_continues_until_window_passes(self):
        # Page 1 has an in-window item, page 2 has another in-window item, page
        # 3 has only past-window items → walker fetches all three, then stops.
        in_window_1 = """
          <item>
            <title>Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern</title>
            <link>https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00</link>
          </item>
        """
        in_window_2 = """
          <item>
            <title>Other Show - May 18, 2026 8:00 PM @ Some Venue</title>
            <link>https://isthmus.com/events/other/?occ_dtstart=2026-05-18T20:00</link>
          </item>
        """
        past_window = """
          <item>
            <title>Future Show - June 30, 2026 7:00 PM @ Future Venue</title>
            <link>https://isthmus.com/events/future/?occ_dtstart=2026-06-30T19:00</link>
          </item>
        """
        responses = [_rss_response([in_window_1]), _rss_response([in_window_2]), _rss_response([past_window])]
        calls = {"i": 0}

        def side_effect(url, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            return responses[i] if i < len(responses) else _empty_rss_response()

        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=side_effect) as http, \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 2
        assert http.call_count == 3

    def test_detail_page_categories_and_address_merge_in(self):
        item = """
          <item>
            <title>Jim Erickson - May 17, 2026 5:30 PM @ Louisianne's, Etc.</title>
            <link>https://isthmus.com/events/jim/?occ_dtstart=2026-05-17T17:30</link>
            <description>Jazz.</description>
          </item>
        """
        detail = BeautifulSoup("""
          <html><body>
            <div class="mp_tag_cat_1"><span>Music</span></div>
            <span class="address">7464 Hubbard Ave., Middleton, Wisconsin 53562</span>
            <div id="content"><p>Full description body that is more than eighty characters long for the enrichment trigger.</p></div>
          </body></html>
        """, "lxml")
        page1 = _rss_response([item])
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_http([page1])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=detail), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert len(events) == 1
        ev = events[0]
        assert ev.categories == ["Music"]
        assert ev.venue_address == "7464 Hubbard Ave., Middleton, Wisconsin 53562"
        # Short description in RSS (<80 chars) was enriched from the detail page.
        assert "Full description body" in (ev.description or "")

    def test_item_without_occ_dtstart_is_skipped(self):
        item = """
          <item>
            <title>Broken Item</title>
            <link>https://isthmus.com/events/broken/</link>
          </item>
        """
        page1 = _rss_response([item])
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_http([page1])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25))
        assert events == []


class TestCategoryMap:
    def test_all_mapped_values_are_in_canonical_taxonomy(self):
        # Guard against a future taxonomy rename leaving a stale entry behind.
        from app.categories import CATEGORIES
        for source_tag, mapped in _CATEGORY_MAP.items():
            assert mapped in CATEGORIES, f"{source_tag!r} maps to {mapped!r}, which is not a canonical category"


class TestDetailCache:
    """Cache-aware path of `_build_events_from_rss(..., db=...)`.

    These tests pass a real Session so the cache module's persistence is
    exercised end-to-end; only the network boundary (`_fetch_detail_soup`) is
    mocked. The single source of truth for whether a row was reused is the
    call count of that mock.
    """

    def _detail_soup(self, name: str = "Event Body"):
        return BeautifulSoup(f"""
          <html><body>
            <div class="mp_tag_cat_1"><span>Music</span></div>
            <span class="address">7464 Hubbard Ave., Middleton, Wisconsin 53562</span>
            <div id="content"><p>{name} long form description body that easily exceeds the eighty-character enrichment threshold.</p></div>
          </body></html>
        """, "lxml")

    def _rss_item(self, *, title: str, link: str, description: str = "Long-form RSS description well above 80 chars to keep enrichment off the critical path.") -> str:
        return f"""
          <item>
            <title>{title}</title>
            <link>{link}</link>
            <description>{description}</description>
          </item>
        """

    def _patch_pages(self, *pages_items: list[str]):
        responses = [_rss_response(items) for items in pages_items]
        calls = {"i": 0}

        def side_effect(url, **kwargs):
            i = calls["i"]
            calls["i"] += 1
            return responses[i] if i < len(responses) else _empty_rss_response()

        return side_effect

    def test_detail_cache_hit_skips_network(self, db):
        from app.models import IsthmusDetail

        item = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern",
            link="https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00",
        )
        soup = self._detail_soup()
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([item])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=soup) as fetch, \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert fetch.call_count == 1
        assert db.query(IsthmusDetail).count() == 1

        # Second call to the same RSS payload — should be a pure cache hit.
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([item])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=soup) as fetch2, \
             patch("app.scrapers.isthmus.time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert fetch2.call_count == 0
        assert len(events) == 1
        assert events[0].categories == ["Music"]
        assert events[0].venue_address == "7464 Hubbard Ave., Middleton, Wisconsin 53562"

    def test_detail_cache_key_strips_occ_dtstart(self, db):
        from app.models import IsthmusDetail

        # Two RSS items for the same recurring event — different occurrences
        # carry different occ_dtstart values but point at the same detail page.
        item_a = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern",
            link="https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00",
        )
        item_b = self._rss_item(
            title="Open Mic - May 24, 2026 10:00 PM @ Mickey's Tavern",
            link="https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-24T22:00",
        )
        soup = self._detail_soup()
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([item_a, item_b])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=soup) as fetch, \
             patch("app.scrapers.isthmus.time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 30), db=db)
        assert len(events) == 2
        # One detail-page fetch even though there are two occurrences.
        assert fetch.call_count == 1
        assert db.query(IsthmusDetail).count() == 1
        # Both occurrences inherit the cached fields.
        assert all(e.categories == ["Music"] for e in events)

    def test_detail_cache_signature_invalidates_on_title_change(self, db):
        from app.models import IsthmusDetail

        link = "https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00"
        first = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern",
            link=link,
        )
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([first])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=self._detail_soup("Open Mic")), \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        original_sig = db.query(IsthmusDetail).one().rss_signature

        # Same link but the event was renamed in RSS. Signature mismatch → refresh.
        renamed = self._rss_item(
            title="Renamed Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern",
            link=link,
        )
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([renamed])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=self._detail_soup("Renamed")) as fetch, \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert fetch.call_count == 1
        refreshed = db.query(IsthmusDetail).one()
        assert refreshed.rss_signature != original_sig
        # Refresh upserts, doesn't append.
        assert db.query(IsthmusDetail).count() == 1

    def test_detail_cache_signature_invalidates_on_venue_change(self, db):
        from app.models import IsthmusDetail

        link = "https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00"
        first = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern", link=link,
        )
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([first])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=self._detail_soup()), \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        original_sig = db.query(IsthmusDetail).one().rss_signature

        moved = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Different Venue", link=link,
        )
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([moved])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=self._detail_soup()) as fetch, \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert fetch.call_count == 1
        assert db.query(IsthmusDetail).one().rss_signature != original_sig

    def test_detail_cache_does_not_persist_failed_fetches(self, db):
        from app.models import IsthmusDetail

        item = self._rss_item(
            title="Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern",
            link="https://isthmus.com/events/open-mic/?occ_dtstart=2026-05-17T22:00",
        )
        # _fetch_detail_soup returns None on network/parse errors.
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([item])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None), \
             patch("app.scrapers.isthmus.time.sleep"):
            events = _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert len(events) == 1
        # No row written — next run will retry instead of inheriting a stale empty cache.
        assert db.query(IsthmusDetail).count() == 0

        # Follow-up run must call the network again.
        with patch("app.scrapers.isthmus.http_get_with_retry", side_effect=self._patch_pages([item])), \
             patch("app.scrapers.isthmus._fetch_detail_soup", return_value=None) as fetch, \
             patch("app.scrapers.isthmus.time.sleep"):
            _build_events_from_rss(date(2026, 5, 17), date(2026, 5, 25), db=db)
        assert fetch.call_count == 1
