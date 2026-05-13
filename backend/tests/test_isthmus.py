"""Unit tests for isthmus.py detail-page extraction helpers."""
from bs4 import BeautifulSoup

from app.scrapers.isthmus import _CATEGORY_MAP, _extract_categories


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


class TestCategoryMap:
    def test_all_mapped_values_are_in_canonical_taxonomy(self):
        # Guard against a future taxonomy rename leaving a stale entry behind.
        from app.categories import CATEGORIES
        for source_tag, mapped in _CATEGORY_MAP.items():
            assert mapped in CATEGORIES, f"{source_tag!r} maps to {mapped!r}, which is not a canonical category"
