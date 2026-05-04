import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

_API_URL = "https://www.visitmadison.com/includes/rest_v2/plugins_events_events_by_date/find/"
_EVENTS_PAGE_URL = "https://www.visitmadison.com/events/"
_FALLBACK_TOKEN = "e3dfe8528d358756953f873be82e42a2"  # public widget token embedded in Visit Madison's own site, not a secret to rotate
_TOKEN_RE = re.compile(r'"apiToken"\s*:\s*"([0-9a-f]{32})"')
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 30
_PAGE_SLEEP_SECONDS = 0.5
# Matches "From: 06:00 PM to 08:30 PM" — the structured times format used by
# one-off events that omit startTime/endTime at the top level.
_FROM_TO_RE = re.compile(
    r"From:\s*(\d{1,2}:\d{2}\s*[AP]M)\s*to\s*(\d{1,2}:\d{2}\s*[AP]M)",
    re.IGNORECASE,
)
# Matches "Friday 6:30pm-7:30pm" within a multi-day times string.
_DAY_TIME_RE = re.compile(
    r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)"
    r"\s+(\d{1,2}(?::\d{2})?(?:am|pm))\s*[-–]\s*(\d{1,2}(?::\d{2})?(?:am|pm))",
    re.IGNORECASE,
)
_WEEKDAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

# Conservative mapping: only Visit Madison categories that map unambiguously to
# our taxonomy. Unmapped categories are silently dropped — those events remain
# eligible for the LLM tagging pass (Step 4).
_VM_CATEGORY_MAP: dict[str, str] = {
    "Education & Lectures":           "Talks & Learning",
    "Food & Drink":                   "Food & Drink",
    "Local Libations":                "Food & Drink",
    "Gallery & Exhibitions":          "Visual Art",
    "General & Community Events":     "Community & Clubs",
    "Health & Wellness":              "Health & Wellness",
    "Kids & Families":                "Family & Kids",
    "Music & Concerts":               "Music",
    "Nature & Outdoors":              "Outdoors & Nature",
    "Tours & Walks":                  "Outdoors & Nature",
    "Theater & Performing Arts":      "Theater & Stage",
    "Trivia":                         "Trivia & Games",
    "Volunteer":                      "Volunteer & Causes",
    "Sports & Recreation":            "Sports & Recreation",
}


class VisitMadisonSource(BaseSource):
    name = "Visit Madison"
    scraper_type = "api"

    def fetch(self) -> list[RawEvent]:
        token = _fetch_token()
        today = datetime.now(_CENTRAL).date()
        end = today + timedelta(days=_WINDOW_DAYS)
        start_iso = _client_midnight_z(today)
        end_iso = _client_midnight_z(end)

        events: list[RawEvent] = []
        skip = 0
        while True:
            payload = {
                "filter": {
                    "active": True,
                    "date_range": {
                        "start": {"$date": start_iso},
                        "end": {"$date": end_iso},
                    },
                },
                "options": {
                    "limit": _PAGE_SIZE,
                    "skip": skip,
                    "sort": {"date": 1},
                },
            }
            resp = http_get_with_retry(
                _API_URL,
                params={"json": json.dumps(payload), "token": token},
                timeout=30,
            )
            docs = resp.json().get("docs") or []
            for doc in docs:
                events.extend(_to_raw_events(doc))
            if len(docs) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE
            time.sleep(_PAGE_SLEEP_SECONDS)

        return events


def _fetch_token() -> str:
    try:
        resp = http_get_with_retry(_EVENTS_PAGE_URL, timeout=30)
        match = _TOKEN_RE.search(resp.text)
        if match:
            return match.group(1)
    except Exception:
        pass
    return _FALLBACK_TOKEN


def _client_midnight_z(d: date) -> str:
    """Return the UTC ISO timestamp for local midnight on `d` in Central Time.

    The Simpleview API requires date_range bounds at 00:00 in the client's
    timezone (it 500s otherwise). Returns e.g. ``2026-04-27T05:00:00.000Z``
    during CDT or ``…T06:00:00.000Z`` during CST.
    """
    local_midnight = datetime.combine(d, dtime.min, tzinfo=_CENTRAL)
    utc = local_midnight.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _parse_iso_z(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_from_to_times(times_str: str, event_date: date) -> tuple[datetime, datetime] | None:
    m = _FROM_TO_RE.search(times_str)
    if not m:
        return None
    try:
        start_t = datetime.strptime(m.group(1).strip().upper(), "%I:%M %p").time()
        end_t = datetime.strptime(m.group(2).strip().upper(), "%I:%M %p").time()
        start_dt = datetime.combine(event_date, start_t, tzinfo=_CENTRAL)
        end_dt = datetime.combine(event_date, end_t, tzinfo=_CENTRAL)
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
        return start_dt, end_dt
    except ValueError:
        return None


def _parse_ampm_time(s: str) -> dtime | None:
    s = s.strip().upper()
    for fmt in ("%I:%M%p", "%I%p"):
        try:
            return datetime.strptime(s, fmt).time()
        except ValueError:
            pass
    return None


def _parse_day_occurrences(
    times_str: str, start_date: date, end_date: date
) -> list[tuple[date, dtime, dtime]]:
    """Parse 'Friday 6:30pm-7:30pm, Saturday 11:00am-12:00pm' into per-date occurrences.

    Resolves each day-of-week name to the matching date(s) in [start_date, end_date].
    Returns an empty list if nothing matches or times can't be parsed.
    """
    matches = _DAY_TIME_RE.findall(times_str)
    if not matches:
        return []
    results = []
    for day_name, start_s, end_s in matches:
        weekday = _WEEKDAY_MAP.get(day_name.lower())
        start_t = _parse_ampm_time(start_s)
        end_t = _parse_ampm_time(end_s)
        if weekday is None or start_t is None or end_t is None:
            continue
        d = start_date
        while d <= end_date:
            if d.weekday() == weekday:
                results.append((d, start_t, end_t))
            d += timedelta(days=1)
    return results


def _parse_hms(s: str) -> dtime | None:
    if not s:
        return None
    try:
        h, m, sec = (int(p) for p in s.split(":"))
        return dtime(h, m, sec)
    except (ValueError, TypeError):
        return None


def _event_local_date(doc: dict) -> date | None:
    """Pick the next-occurrence date in Central Time.

    For one-off events ``startDate`` is correct. For recurring events the API
    sets ``startDate`` to the original series start, so prefer ``nextDate`` /
    ``dates.eventDate`` (both encode the upcoming-occurrence day as 23:59:59
    Central → converting to Central gives that day's date).
    """
    candidates = [
        (doc.get("dates") or {}).get("eventDate"),
        doc.get("nextDate"),
        doc.get("startDate"),
    ]
    for raw in candidates:
        dt = _parse_iso_z(raw)
        if dt is not None:
            return dt.astimezone(_CENTRAL).date()
    return None


def _build_address(doc: dict) -> str | None:
    parts = [doc.get("address1"), doc.get("city")]
    state_zip = " ".join(p for p in (doc.get("state"), doc.get("zip")) if p)
    if state_zip:
        parts.append(state_zip)
    parts = [p for p in parts if p]
    return ", ".join(parts) if parts else None


def _map_categories(doc: dict) -> list[str]:
    seen: list[str] = []
    for c in doc.get("categories") or []:
        ours = _VM_CATEGORY_MAP.get(c.get("catName"))
        if ours and ours not in seen:
            seen.append(ours)
    return seen


def _top_level_times(
    doc: dict, event_date: date
) -> tuple[datetime, datetime | None] | None:
    """Strategy 1: top-level startTime/endTime HMS fields.

    Returns (start_at, end_at) when startTime is present, None otherwise.
    end_at is None when endTime is absent; midnight-wrap is applied when
    end_at would otherwise fall before start_at.
    """
    start_t = _parse_hms(doc.get("startTime"))
    if start_t is None:
        return None
    start_at = datetime.combine(event_date, start_t, tzinfo=_CENTRAL)
    end_at = None
    end_t = _parse_hms(doc.get("endTime"))
    if end_t is not None:
        end_at = datetime.combine(event_date, end_t, tzinfo=_CENTRAL)
        if end_at < start_at:
            end_at += timedelta(days=1)
    return start_at, end_at


def _day_of_week_events(
    doc: dict, times_str: str
) -> list[tuple[datetime, datetime]]:
    """Strategy 3: day-of-week recurrence from the times string.

    Uses startDate/endDate from the doc to resolve weekday names to actual
    dates, then returns a list of (start_at, end_at) aware datetime pairs.
    Returns [] when dates are missing, times_str is empty, or no days match.
    """
    if not times_str:
        return []
    start_date_raw = _parse_iso_z(doc.get("startDate"))
    end_date_raw = _parse_iso_z(doc.get("endDate"))
    if not start_date_raw or not end_date_raw:
        return []
    start_date_local = start_date_raw.astimezone(_CENTRAL).date()
    end_date_local = end_date_raw.astimezone(_CENTRAL).date()
    occurrences = _parse_day_occurrences(times_str, start_date_local, end_date_local)
    result = []
    for d, st, et in occurrences:
        start_at = datetime.combine(d, st, tzinfo=_CENTRAL)
        end_at = datetime.combine(d, et, tzinfo=_CENTRAL)
        if end_at < start_at:
            end_at += timedelta(days=1)
        result.append((start_at, end_at))
    return result


def _fallback_all_day_desc(times_str: str, description: str | None) -> str | None:
    """Strategy 4: build the description for an all-day fallback event.

    Prepends times_str to description when it carries useful info (non-empty
    and does not just say "see event description").
    """
    if times_str and "see event description" not in times_str.lower():
        return f"{times_str} — {description}" if description else times_str
    return description


def _to_raw_events(doc: dict) -> list[RawEvent]:
    title = (doc.get("title") or "").strip()
    if not title:
        return []

    event_date = _event_local_date(doc)
    if event_date is None:
        return []

    times_str = (doc.get("times") or "").strip()
    venue_name = (doc.get("location") or "").strip() or None
    venue_address = _build_address(doc)
    raw_desc = doc.get("description") or doc.get("teaser") or ""
    description = clean_html_text(raw_desc) or None
    image_url = (((doc.get("media_raw") or [{}])[0]).get("mediaurl")) or None
    source_url = doc.get("absoluteUrl") or doc.get("url") or _EVENTS_PAGE_URL
    categories = _map_categories(doc)

    def make_event(start_at, end_at=None, all_day=False, desc=description):
        return RawEvent(
            title=title,
            start_at=start_at,
            end_at=end_at,
            venue_name=venue_name,
            venue_address=venue_address,
            description=desc,
            image_url=image_url,
            categories=list(categories),
            all_day=all_day,
            source_name="Visit Madison",
            source_url=source_url,
        )

    # Strategy 1: top-level startTime/endTime HMS fields.
    top = _top_level_times(doc, event_date)
    if top is not None:
        return [make_event(*top)]

    # Strategy 2: structured "From: HH:MM AM to HH:MM PM" in the times field.
    parsed = _parse_from_to_times(times_str, event_date) if times_str else None
    if parsed is not None:
        return [make_event(*parsed)]

    # Strategy 3: day-of-week recurrence ("Friday 6:30pm-7:30pm, Saturday 11am-12pm").
    day_pairs = _day_of_week_events(doc, times_str)
    if day_pairs:
        return [make_event(*pair) for pair in day_pairs]

    # Strategy 4: fall back to all-day with freeform times prepended to description.
    all_day_desc = _fallback_all_day_desc(times_str, description)
    return [make_event(datetime.combine(event_date, dtime.min, tzinfo=_CENTRAL), all_day=True, desc=all_day_desc)]
