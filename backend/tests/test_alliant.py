"""Unit tests for alliant.py parsing helpers."""
from datetime import datetime

from bs4 import BeautifulSoup

from app.scrapers.alliant import (
    _CENTRAL,
    _extract_description,
    _parse_list_item,
    _parse_us_date,
)

# ---------------------------------------------------------------------------
# _parse_us_date
# ---------------------------------------------------------------------------

class TestParseUsDate:
    def test_standard_format(self):
        d = _parse_us_date("5/17/2026")
        assert d == datetime(2026, 5, 17)

    def test_zero_padded(self):
        d = _parse_us_date("05/17/2026")
        assert d == datetime(2026, 5, 17)

    def test_two_digit_day(self):
        d = _parse_us_date("12/31/2026")
        assert d == datetime(2026, 12, 31)

    def test_whitespace_tolerated(self):
        d = _parse_us_date("  5/17/2026  ")
        assert d == datetime(2026, 5, 17)

    def test_invalid_returns_none(self):
        assert _parse_us_date("not a date") is None
        assert _parse_us_date("2026-05-17") is None
        assert _parse_us_date("") is None
        assert _parse_us_date(None) is None
        assert _parse_us_date("13/45/2026") is None


# ---------------------------------------------------------------------------
# _parse_list_item
# ---------------------------------------------------------------------------

_SINGLE_DAY_ITEM = """
<li>
    <h3><span class="eventTitle">Wisconsin Bridal and Wedding Expo</span></h3>
    <p>
        <span class="eventDateLabel">Event Start Date: </span>
        <span class="notificationStartDate">5/17/2026</span>
    </p>
    <p>
        <span class="eventDateLabel">Event End Date: </span>
        <span class="notificationEndDate">5/17/2026</span>
    </p>
    <p>
        <a class="eventPlannerStandardButton"
           href="https://www.alliantenergycenter.com/upcoming-events/events-details/964/wisconsin-bridal-and-wedding-expo-17-may-2026">
            View More Details
        </a>
    </p>
</li>
"""

_MULTI_DAY_ITEM = """
<li>
    <h3><span class="eventTitle">The Madison Classic Horse Show</span></h3>
    <p>
        <span class="eventDateLabel">Event Start Date: </span>
        <span class="notificationStartDate">5/18/2026</span>
    </p>
    <p>
        <span class="eventDateLabel">Event End Date: </span>
        <span class="notificationEndDate">5/24/2026</span>
    </p>
    <p>
        <a class="eventPlannerStandardButton"
           href="https://www.alliantenergycenter.com/upcoming-events/events-details/1014/the-madison-classic-horse-show-18-may-2026">
            View More Details
        </a>
    </p>
</li>
"""

_ENTITY_TITLE_ITEM = """
<li>
    <h3><span class="eventTitle">Swim Spa &amp; Hot Tub Sale</span></h3>
    <p><span class="notificationStartDate">6/5/2026</span></p>
    <p><span class="notificationEndDate">6/7/2026</span></p>
    <p><a class="eventPlannerStandardButton" href="https://www.alliantenergycenter.com/upcoming-events/events-details/999/swim-spa-hot-tub-sale-5-jun-2026">More</a></p>
</li>
"""


def _li(html: str):
    return BeautifulSoup(html, "lxml").select_one("li")


class TestParseListItem:
    def test_single_day_event(self):
        ev = _parse_list_item(_li(_SINGLE_DAY_ITEM))
        assert ev is not None
        assert ev.title == "Wisconsin Bridal and Wedding Expo"
        assert ev.start_at == datetime(2026, 5, 17, 0, 0, 0, tzinfo=_CENTRAL)
        assert ev.end_at is not None
        assert ev.end_at.date() == ev.start_at.date()
        assert ev.end_at.hour == 23 and ev.end_at.minute == 59
        assert ev.end_at.tzinfo == _CENTRAL
        assert ev.all_day is True
        assert ev.venue_name == "Alliant Energy Center"
        assert ev.venue_address is None
        assert ev.description is None
        assert ev.categories == []
        assert ev.source_name == "Alliant Energy Center"
        assert ev.source_url.startswith(
            "https://www.alliantenergycenter.com/upcoming-events/events-details/964/"
        )

    def test_multi_day_event_end_at_lands_end_of_end_date(self):
        ev = _parse_list_item(_li(_MULTI_DAY_ITEM))
        assert ev is not None
        # Date range surfaces on every date 5/18..5/24 via the daily query
        # rule (start::date <= req AND coalesce(end,start)::date >= req).
        assert ev.start_at == datetime(2026, 5, 18, 0, 0, 0, tzinfo=_CENTRAL)
        assert ev.end_at == datetime(2026, 5, 24, 23, 59, 59, tzinfo=_CENTRAL)

    def test_title_entities_unescaped(self):
        ev = _parse_list_item(_li(_ENTITY_TITLE_ITEM))
        assert ev is not None
        assert ev.title == "Swim Spa & Hot Tub Sale"

    def test_missing_title_returns_none(self):
        html = _SINGLE_DAY_ITEM.replace('<span class="eventTitle">Wisconsin Bridal and Wedding Expo</span>', "")
        assert _parse_list_item(_li(html)) is None

    def test_missing_start_date_returns_none(self):
        html = _SINGLE_DAY_ITEM.replace('class="notificationStartDate">5/17/2026</span>', 'class="other">5/17/2026</span>')
        assert _parse_list_item(_li(html)) is None

    def test_missing_detail_url_returns_none(self):
        html = _SINGLE_DAY_ITEM.replace('class="eventPlannerStandardButton"', 'class="other"')
        assert _parse_list_item(_li(html)) is None

    def test_missing_end_date_falls_back_to_no_end(self):
        # Page format always emits an end date, but the parser must handle
        # the missing-element case gracefully (event becomes a single-day
        # row with end_at=None).
        html = _SINGLE_DAY_ITEM.replace(
            '<span class="notificationEndDate">5/17/2026</span>', ""
        )
        ev = _parse_list_item(_li(html))
        assert ev is not None
        assert ev.end_at is None


# ---------------------------------------------------------------------------
# _extract_description
# ---------------------------------------------------------------------------

_DETAIL_WITH_DESCRIPTION = """
<html><body>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"> </div>
    <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
        <div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div>
        <div class="nadevViewEventDetails nadevViewEventDetailsPadding" itemprop="price" content="">
            <span itemprop="priceCurrency" content="USD"/>
        </div>
    </div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding">
        <p>The Bridal &amp; Wedding Expo showcases an amazing selection of wedding professionals.</p>
        <p>Get Your Free Passes Today.</p>
    </div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div>
</body></html>
"""

_DETAIL_NO_DESCRIPTION = """
<html><body>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"> </div>
    <div itemprop="offers"><div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div></div>
</body></html>
"""

_DETAIL_OFFERS_LOOKS_LIKE_DESC = """
<html><body>
    <div itemprop="offers">
        <div class="nadevViewEventDetails nadevViewEventDetailsPadding">
            <p>$10 at the door, $5 for kids. Tickets available online or at the box office.</p>
        </div>
    </div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding">
        <p>This is the real description for the event and it is long enough to win.</p>
    </div>
</body></html>
"""

# Mirrors the real Alliant detail-page layout: the FIRST nadev block is the
# title scaffolding (eventTitle h2 + eventLoc + eventDateLabel + websiteField
# with a setup <script>) and its visible text easily exceeds the description
# length threshold. Without scaffolding-aware filtering, the extractor would
# pick the title block instead of the real description further down.
_DETAIL_TITLE_BLOCK_THEN_DESCRIPTION = """
<html><body>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding">
        <h2 itemprop="name"><span class="eventTitle">Wisconsin State FFA Convention &amp; Expo</span></h2>
        <p class="eventLoc"><span class="eventDateLabel">Event Locations</span><br/>Exhibition Hall</p>
        <p><span class="eventDateLabel">Event Website:</span>
           <a id="websiteField" class="websiteField"><span class="eventDateLabel">Event Phone Number: </span>wisconsinaged.org/state-convention</a></p>
        <script type="text/javascript">$("#websiteField span").remove();</script>
        <p><span class="eventDateLabel">Event Start Date: </span><span class="notificationStartDate">6/15/2026</span></p>
        <p><span class="eventDateLabel">Event End Date: </span><span class="notificationEndDate">6/18/2026</span></p>
    </div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div>
    <div itemprop="offers"><div class="nadevViewEventDetails nadevViewEventDetailsPadding"></div></div>
    <div class="nadevViewEventDetails nadevViewEventDetailsPadding">
        <p>Join us at the Alliant Energy Center in Madison for our Annual State FFA Convention June 15-18, 2026 with thousands of FFA members across Wisconsin.</p>
    </div>
</body></html>
"""


class TestExtractDescription:
    def test_picks_first_substantive_block(self):
        soup = BeautifulSoup(_DETAIL_WITH_DESCRIPTION, "lxml")
        desc = _extract_description(soup)
        assert desc is not None
        assert "Bridal & Wedding Expo" in desc
        assert "Get Your Free Passes" in desc

    def test_returns_none_when_no_block_has_text(self):
        soup = BeautifulSoup(_DETAIL_NO_DESCRIPTION, "lxml")
        assert _extract_description(soup) is None

    def test_skips_blocks_nested_in_offers(self):
        soup = BeautifulSoup(_DETAIL_OFFERS_LOOKS_LIKE_DESC, "lxml")
        desc = _extract_description(soup)
        assert desc is not None
        assert "real description" in desc
        assert "Tickets available online" not in desc

    def test_skips_title_scaffolding_block(self):
        # The real Alliant detail-page layout puts the title/eventLoc/date/script
        # scaffolding in the FIRST nadev block. Without scaffolding-aware
        # filtering, the picker would grab the title block instead of the real
        # description further down the page.
        soup = BeautifulSoup(_DETAIL_TITLE_BLOCK_THEN_DESCRIPTION, "lxml")
        desc = _extract_description(soup)
        assert desc is not None
        assert "Annual State FFA Convention" in desc
        assert "Exhibition Hall" not in desc
        assert "wisconsinaged.org" not in desc
        assert "$(" not in desc
