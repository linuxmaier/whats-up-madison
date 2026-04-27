import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import recurring_ical_events
from icalendar import Calendar

from app.scrapers.base import BaseSource, RawEvent

_ICAL_URL = "https://isthmus.com/search/event/calendar-of-events/calendar.ics"
_RSS_BASE = "https://isthmus.com/search/event/calendar-of-events/index.rss"
_CAL_BASE = "https://isthmus.com/search/event/calendar-of-events/"
_FALLBACK_URL = "https://isthmus.com/all-events/calendar-of-events-index"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30


class IsthmusSource(BaseSource):
    name = "Isthmus"
    scraper_type = "ical"

    def fetch(self) -> list[RawEvent]:
        today = date.today()
        end_date = today + timedelta(days=_WINDOW_DAYS)
        url_map, date_page_map = _build_url_map(today, end_date)
        return _parse_ical(today, end_date, url_map, date_page_map)


def _rss_title_to_event_name(title: str) -> str:
    """Strip the ' - Date @ Venue' suffix from an RSS item title."""
    idx = title.find(" - ")
    if idx != -1:
        title = title[:idx]
    return title.lower().strip()


def _build_url_map(
    start: date, end: date
) -> tuple[dict[tuple[str, str], str], dict[str, int]]:
    url_map: dict[tuple[str, str], str] = {}
    date_page_map: dict[str, int] = {}
    page = 1
    while True:
        resp = httpx.get(_RSS_BASE, params={"page": page}, timeout=30)
        resp.raise_for_status()
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
                date_page_map.setdefault(date_str, page)
                key = (_rss_title_to_event_name(title_raw), date_str)
                url_map[key] = link

        if all_beyond_window:
            break
        page += 1

    return url_map, date_page_map


def _to_aware_datetime(dt: date | datetime) -> datetime:
    if isinstance(dt, datetime):
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=_CENTRAL)
    return datetime(dt.year, dt.month, dt.day, tzinfo=_CENTRAL)


def _parse_ical(
    start: date, end: date, url_map: dict, date_page_map: dict
) -> list[RawEvent]:
    resp = httpx.get(_ICAL_URL, timeout=30)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)

    events = []
    for comp in recurring_ical_events.of(cal).between(start, end):
        title = str(comp.get("SUMMARY", "")).strip()
        if not title:
            continue

        start_at = _to_aware_datetime(comp.get("DTSTART").dt)
        dtend = comp.get("DTEND")
        end_at = _to_aware_datetime(dtend.dt) if dtend else None

        local_date = start_at.astimezone(_CENTRAL).date().isoformat()
        page = date_page_map.get(local_date)
        fallback = f"{_CAL_BASE}?page={page}" if page else _FALLBACK_URL
        source_url = url_map.get((title.lower().strip(), local_date), fallback)

        raw_location = comp.get("LOCATION")
        venue_name = str(raw_location).strip() or None if raw_location else None

        raw_desc = comp.get("DESCRIPTION")
        description = str(raw_desc).strip() or None if raw_desc else None

        events.append(RawEvent(
            title=title,
            start_at=start_at,
            end_at=end_at,
            venue_name=venue_name,
            description=description,
            source_name="Isthmus",
            source_url=source_url,
        ))

    return events
