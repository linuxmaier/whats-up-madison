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
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30


class IsthmusSource(BaseSource):
    name = "Isthmus"
    scraper_type = "ical"

    def fetch(self) -> list[RawEvent]:
        today = date.today()
        end_date = today + timedelta(days=_WINDOW_DAYS)
        url_map, title_date_map = _build_url_map(today, end_date)
        return _parse_ical(today, end_date, url_map, title_date_map)


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


def _parse_ical(
    start: date,
    end: date,
    url_map: dict[tuple[str, str, str], str],
    title_date_map: dict[tuple[str, str], str],
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
