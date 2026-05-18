import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_RSS_BASE = "https://isthmus.com/search/event/calendar-of-events/index.rss"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_DESC_MIN_LEN = 80
_FETCH_DELAY = 0.5  # courtesy delay between detail-page fetches; Isthmus has no published rate limit

# Isthmus event-detail-page tag vocabulary → our taxonomy (backend/app/categories.py).
# Mapped conservatively per the per-scraper convention; ambiguous tags
# (Special Interests, Seniors, LGBT, Arts Notices, Movies, Isthmus Picks, music
# sub-genres like Folk/Bluegrass/Americana) are intentionally omitted so they
# fall through to the LLM tagging pass instead of being mis-bucketed.
_CATEGORY_MAP: dict[str, str] = {
    "Music": "Music",
    "Comedy": "Open Mic & Comedy",
    "Theater & Dance": "Theater & Stage",
    "Dancing": "Dance",
    "Food & Drink": "Food & Drink",
    "Farmers' Markets": "Food & Drink",
    "Health & Fitness": "Health & Wellness",
    "Recreation": "Sports & Recreation",
    "Kids & Family": "Family & Kids",
    "Politics & Activism": "Civic & Politics",
    "Public Meetings": "Civic & Politics",
    "Fundraisers": "Volunteer & Causes",
}

# RSS title format: "Event Name - Month DD, YYYY [H:MM AM/PM [- H:MM AM/PM]] [@ Venue]"
# Observed shapes:
#   "Open Mic - May 17, 2026 10:00 PM @ Mickey's Tavern"
#   "Dave Scott Quintet - May 17, 2026 7:00 PM - 10:00 PM @ North Street Cabaret"
#   "RSVP for The Record Club - May 18, 2026 @ UW Memorial Library"  (no time = all-day)
#   "Lupus Support Group for Women of Color - May 18, 2026 6:00 PM"  (no venue)
_RSS_TITLE_RE = re.compile(
    r"^(?P<name>.+?) - "
    r"[A-Z][a-z]+ \d{1,2}, \d{4}"
    r"(?:\s+(?P<start>\d{1,2}:\d{2}\s*[AP]M)"
    r"(?:\s*-\s*(?P<end>\d{1,2}:\d{2}\s*[AP]M))?)?"
    r"(?:\s*@\s*(?P<venue>.+))?$"
)


def _fetch_detail_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = http_get_with_retry(url, timeout=15)
        return BeautifulSoup(resp.content, "lxml")
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def _extract_description(soup: BeautifulSoup, url: str) -> str | None:
    content = soup.find(id="content")
    if not content:
        logger.warning("No id='content' element at %s", url)
        return None
    # Isthmus's hero image card (div.single.media-carousel) injects
    # "× Expand <photographer-credit> <event-title>" into the visible text,
    # which then prefixes every description on events with a hero image.
    # Drop it (and any generic <figure>) before extracting paragraph text.
    for node in content.select("div.media-carousel, figure"):
        node.decompose()
    return clean_html_text(content.get_text()) or None


def _extract_categories(soup: BeautifulSoup) -> list[str]:
    """Read the visible 'Event Categories' block and map to our taxonomy.

    Isthmus emits one or more `<span>` children inside `div.mp_tag_cat_1`,
    each holding a category label. Unmapped values are dropped (left for the
    LLM tagging pass); order is preserved and duplicates removed.
    """
    block = soup.find("div", class_="mp_tag_cat_1")
    if not block:
        return []
    result: list[str] = []
    for span in block.find_all("span"):
        label = span.get_text(strip=True)
        mapped = _CATEGORY_MAP.get(label)
        if mapped and mapped not in result:
            result.append(mapped)
    return result


def _extract_venue_address(soup: BeautifulSoup) -> str | None:
    addr_span = soup.find("span", class_="address")
    if not addr_span:
        return None
    return " ".join(addr_span.get_text().split()) or None


def _parse_rss_title(title: str) -> tuple[str, str | None, str | None, str | None]:
    """Split RSS title into (event_name, start_time, end_time, venue).

    Falls back to (raw_title, None, None, None) when the regex doesn't match —
    keeping the item is better than dropping it; caller can still use
    occ_dtstart for the start datetime.
    """
    m = _RSS_TITLE_RE.match(title.strip())
    if not m:
        return (title.strip(), None, None, None)
    venue = m.group("venue")
    return (
        m.group("name").strip(),
        m.group("start"),
        m.group("end"),
        venue.strip() if venue else None,
    )


def _parse_clock(text: str, on: date) -> datetime:
    t = datetime.strptime(text.strip().upper().replace(" ", ""), "%I:%M%p").time()
    return datetime.combine(on, t).replace(tzinfo=_CENTRAL)


class IsthmusSource(BaseSource):
    name = "Isthmus"
    # The RSS feed is now the only data source. The iCal feed was dropped in
    # issue #231 — it covered only ~14% of what RSS exposes for the same
    # window and was the source of #210 (zero-duration end_at) and #228
    # (stale rescheduled events).
    scraper_type = "rss"

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        # Use Central time, not the container's clock — backend runs in UTC, so
        # date.today() returns tomorrow's date after ~7 PM Central, cutting off
        # today's events from the scrape window.
        today = datetime.now(_CENTRAL).date()
        end_date = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)
        return _build_events_from_rss(today, end_date)


def _build_events_from_rss(start: date, end: date) -> list[RawEvent]:
    """Walk the paginated RSS feed and build RawEvents.

    Each <item> is one pre-expanded occurrence (recurring events emit one item
    per date). The link/guid carries `occ_dtstart` with the local start
    datetime; the title carries human-readable start time, optional end time,
    and venue. We trust `occ_dtstart` for the datetime and use the title for
    end_at and all-day detection.
    """
    events: list[RawEvent] = []
    short_count = enriched_count = failed_count = 0
    page = 1
    while True:
        resp = http_get_with_retry(_RSS_BASE, params={"page": page}, timeout=30)
        if not resp.content.strip():
            break
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        if not items:
            break

        all_beyond_window = True
        for item in items:
            link = item.findtext("link") or ""
            title_raw = item.findtext("title") or ""
            qs = parse_qs(urlparse(link).query)
            occ = qs.get("occ_dtstart", [None])[0]
            if not occ:
                continue

            event_date = date.fromisoformat(occ[:10])
            if event_date <= end:
                all_beyond_window = False
            if not (start <= event_date <= end):
                continue

            event_name, start_time, end_time, venue_name = _parse_rss_title(title_raw)
            if not event_name:
                continue

            # The RSS title not carrying a time is the strongest all-day signal:
            # occ_dtstart=...T00:00 alone is ambiguous (a real midnight event
            # would look the same). Trust the human-readable title.
            if start_time:
                start_at = _parse_clock(start_time, event_date)
                all_day = False
            else:
                start_at = datetime(event_date.year, event_date.month, event_date.day, tzinfo=_CENTRAL)
                all_day = True

            end_at = _parse_clock(end_time, event_date) if end_time else None

            soup = _fetch_detail_soup(link)
            time.sleep(_FETCH_DELAY)
            description = item.findtext("description") or None
            categories: list[str] = []
            venue_address: str | None = None
            if soup is not None:
                categories = _extract_categories(soup)
                venue_address = _extract_venue_address(soup)
                if len(description or "") < _DESC_MIN_LEN:
                    short_count += 1
                    enriched = _extract_description(soup, link)
                    if enriched:
                        description = enriched
                        enriched_count += 1
                    else:
                        failed_count += 1
            elif len(description or "") < _DESC_MIN_LEN:
                short_count += 1
                failed_count += 1

            events.append(RawEvent(
                title=event_name,
                start_at=start_at,
                end_at=end_at,
                venue_name=venue_name,
                venue_address=venue_address,
                description=description,
                source_name="Isthmus",
                source_url=link,
                all_day=all_day,
                categories=categories,
            ))

        if all_beyond_window:
            break
        page += 1

    if short_count:
        logger.info(
            "Isthmus description enrichment: %d/%d fetched successfully, %d failed",
            enriched_count, short_count, failed_count,
        )
    logger.info("Isthmus: built %d events from RSS", len(events))
    return events
