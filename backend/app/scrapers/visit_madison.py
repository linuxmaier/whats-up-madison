import json
import re
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.scrapers.base import BaseSource, RawEvent, clean_html_text

_API_URL = "https://www.visitmadison.com/includes/rest_v2/plugins_events_events_by_date/find/"
_EVENTS_PAGE_URL = "https://www.visitmadison.com/events/"
_FALLBACK_TOKEN = "e3dfe8528d358756953f873be82e42a2"
_TOKEN_RE = re.compile(r'"apiToken"\s*:\s*"([0-9a-f]{32})"')
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 30
_PAGE_SLEEP_SECONDS = 0.5

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
            resp = httpx.get(
                _API_URL,
                params={"json": json.dumps(payload), "token": token},
                timeout=30,
            )
            resp.raise_for_status()
            docs = resp.json().get("docs") or []
            for doc in docs:
                raw = _to_raw_event(doc)
                if raw is not None:
                    events.append(raw)
            if len(docs) < _PAGE_SIZE:
                break
            skip += _PAGE_SIZE
            time.sleep(_PAGE_SLEEP_SECONDS)

        return events


def _fetch_token() -> str:
    try:
        resp = httpx.get(_EVENTS_PAGE_URL, timeout=30)
        resp.raise_for_status()
        match = _TOKEN_RE.search(resp.text)
        if match:
            return match.group(1)
    except httpx.HTTPError:
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


def _to_raw_event(doc: dict) -> RawEvent | None:
    title = (doc.get("title") or "").strip()
    if not title:
        return None

    event_date = _event_local_date(doc)
    if event_date is None:
        return None

    start_time = _parse_hms(doc.get("startTime"))
    if start_time is not None:
        start_at = datetime.combine(event_date, start_time, tzinfo=_CENTRAL)
    else:
        start_at = datetime.combine(event_date, dtime.min, tzinfo=_CENTRAL)

    end_at: datetime | None = None
    end_time = _parse_hms(doc.get("endTime"))
    if end_time is not None:
        end_at = datetime.combine(event_date, end_time, tzinfo=_CENTRAL)
        if end_at < start_at:
            end_at += timedelta(days=1)

    venue_name = (doc.get("location") or "").strip() or None
    venue_address = _build_address(doc)

    raw_desc = doc.get("description") or doc.get("teaser") or ""
    description = clean_html_text(raw_desc) or None

    image_url = None
    media = doc.get("media_raw") or []
    if media:
        image_url = media[0].get("mediaurl") or None

    source_url = doc.get("absoluteUrl") or doc.get("url") or _EVENTS_PAGE_URL

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=image_url,
        categories=_map_categories(doc),
        source_name="Visit Madison",
        source_url=source_url,
    )
