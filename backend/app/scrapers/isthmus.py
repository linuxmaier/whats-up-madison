import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import recurring_ical_events
from bs4 import BeautifulSoup
from icalendar import Calendar

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_ICAL_URL = "https://isthmus.com/search/event/calendar-of-events/calendar.ics"
_RSS_BASE = "https://isthmus.com/search/event/calendar-of-events/index.rss"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30  # matches the iCal feed's effective range
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


class IsthmusSource(BaseSource):
    name = "Isthmus"
    scraper_type = "ical"

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        # Use Central time, not the container's clock — backend runs in UTC, so
        # date.today() returns tomorrow's date after ~7 PM Central, cutting off
        # today's events from the scrape window.
        today = datetime.now(_CENTRAL).date()
        end_date = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)

        ical_resp = http_get_with_retry(_ICAL_URL, timeout=30)
        if not ical_resp.content.strip():
            logger.warning("Isthmus: iCal feed returned empty response; falling back to RSS")
            return _build_events_from_rss(today, end_date)

        url_map, title_date_map = _build_url_map(today, end_date)
        return _parse_ical(today, end_date, url_map, title_date_map, ical_content=ical_resp.content)


def _parse_rss_title(title: str) -> tuple[str, str]:
    """Return (event_name_lower, venue_lower) from an RSS item title.

    RSS format: 'Event Name - Date [time] [@ Venue]'
    """
    idx = title.find(" - ")
    if idx == -1:
        return title.lower().strip(), ""
    event_name = title[:idx].lower().strip()
    suffix = title[idx + 3:]
    at_idx = suffix.rfind(" @ ")
    venue = suffix[at_idx + 3:].lower().strip() if at_idx != -1 else ""
    return event_name, venue


def _build_url_map(
    start: date, end: date
) -> tuple[dict[tuple[str, str, str], str], dict[tuple[str, str], str]]:
    """Paginate the RSS feed and return two lookup maps.

    url_map:        (title, date, venue) → url  (venue-precise)
    title_date_map: (title, date)        → url  (first match per title+date)
    """
    url_map: dict[tuple[str, str, str], str] = {}
    title_date_map: dict[tuple[str, str], str] = {}
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
            if start <= event_date <= end:
                date_str = event_date.isoformat()
                event_name, venue = _parse_rss_title(title_raw)
                if venue:
                    url_map[(event_name, date_str, venue)] = link
                title_date_map.setdefault((event_name, date_str), link)

        if all_beyond_window:
            break
        page += 1

    return url_map, title_date_map


def _to_aware_datetime(dt: date | datetime) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=_CENTRAL)
    return datetime(dt.year, dt.month, dt.day, tzinfo=_CENTRAL)


def _build_events_from_rss(start: date, end: date) -> list[RawEvent]:
    """Build RawEvents directly from RSS items when the iCal feed is unavailable.

    The RSS occ_dtstart query param includes the local time (e.g. 2026-05-12T19:30)
    so we can produce properly-timed events without the iCal feed."""
    events: list[RawEvent] = []
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

            # RSS title format: "Event Name - Date [time] [@ Venue]"
            dash_idx = title_raw.find(" - ")
            if dash_idx == -1:
                event_name = title_raw.strip()
                venue_name = None
            else:
                event_name = title_raw[:dash_idx].strip()
                suffix = title_raw[dash_idx + 3:]
                at_idx = suffix.rfind(" @ ")
                venue_name = suffix[at_idx + 3:].strip() if at_idx != -1 else None

            if not event_name:
                continue

            if "T" in occ:
                try:
                    start_at = datetime.fromisoformat(occ).replace(tzinfo=_CENTRAL)
                    all_day = False
                except ValueError:
                    start_at = datetime(event_date.year, event_date.month, event_date.day, tzinfo=_CENTRAL)
                    all_day = True
            else:
                start_at = datetime(event_date.year, event_date.month, event_date.day, tzinfo=_CENTRAL)
                all_day = True

            soup = _fetch_detail_soup(link)
            time.sleep(_FETCH_DELAY)
            description = _extract_description(soup, link) if soup is not None else None
            categories = _extract_categories(soup) if soup is not None else []

            events.append(RawEvent(
                title=event_name,
                start_at=start_at,
                venue_name=venue_name or None,
                description=description,
                source_name="Isthmus",
                source_url=link,
                all_day=all_day,
                categories=categories,
            ))

        if all_beyond_window:
            break
        page += 1

    logger.info("Isthmus RSS fallback: built %d events", len(events))
    return events


def _parse_ical(
    start: date,
    end: date,
    url_map: dict[tuple[str, str, str], str],
    title_date_map: dict[tuple[str, str], str],
    ical_content: bytes | None = None,
) -> list[RawEvent]:
    if ical_content is None:
        ical_content = http_get_with_retry(_ICAL_URL, timeout=30).content
    cal = Calendar.from_ical(ical_content)

    events = []
    short_count = enriched_count = failed_count = 0
    for comp in recurring_ical_events.of(cal).between(start, end):
        title = str(comp.get("SUMMARY", "")).strip()
        if not title:
            continue

        start_at = _to_aware_datetime(comp.get("DTSTART").dt)
        dtend = comp.get("DTEND")
        end_at = _to_aware_datetime(dtend.dt) if dtend else None

        raw_location = comp.get("LOCATION")
        venue_name = str(raw_location).strip() or None if raw_location else None

        raw_desc = comp.get("DESCRIPTION")
        description = str(raw_desc).strip() or None if raw_desc else None

        local_date = start_at.astimezone(_CENTRAL).date().isoformat()
        title_lower = title.lower().strip()
        venue_lower = (venue_name or "").lower().strip()

        source_url = (
            url_map.get((title_lower, local_date, venue_lower))
            or title_date_map.get((title_lower, local_date))
        )
        if not source_url:
            continue

        # Always fetch the detail page so we can extract Isthmus's own category
        # tags (the iCal/RSS feeds carry none); use the same fetch to enrich
        # short iCal descriptions.
        categories: list[str] = []
        soup = _fetch_detail_soup(source_url)
        time.sleep(_FETCH_DELAY)
        if soup is not None:
            categories = _extract_categories(soup)
            if len(description or "") < _DESC_MIN_LEN:
                short_count += 1
                enriched = _extract_description(soup, source_url)
                if enriched:
                    description = enriched
                    enriched_count += 1
                else:
                    failed_count += 1
        elif len(description or "") < _DESC_MIN_LEN:
            short_count += 1
            failed_count += 1

        events.append(RawEvent(
            title=title,
            start_at=start_at,
            end_at=end_at,
            venue_name=venue_name,
            description=description,
            source_name="Isthmus",
            source_url=source_url,
            categories=categories,
        ))

    if short_count:
        logger.info(
            "Description enrichment: %d/%d fetched successfully, %d failed",
            enriched_count, short_count, failed_count,
        )
    return events
