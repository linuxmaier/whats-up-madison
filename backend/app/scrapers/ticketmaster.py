import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.scrapers.base import BaseSource, RawEvent, http_get_with_retry

logger = logging.getLogger(__name__)

_API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 200  # Discovery API max
_PAGE_SLEEP_SECONDS = 0.25  # well under the 5 req/s rate limit
_DROP_STATUSES: frozenset[str] = frozenset({"cancelled", "postponed"})

# Conservative segment/genre → our taxonomy mapping. Lookup order is
# (segment, genre) first, then (segment, None). Anything unmapped is dropped
# so the LLM tagging pass can enrich from description.
_CATEGORY_MAP: dict[tuple[str, str | None], str] = {
    ("Music", None):                            "Music",
    ("Arts & Theatre", "Comedy"):               "Open Mic & Comedy",
    ("Arts & Theatre", "Theatre"):              "Theater & Stage",
    ("Arts & Theatre", "Children's Theatre"):   "Theater & Stage",
    ("Arts & Theatre", "Performance Art"):      "Theater & Stage",
    ("Arts & Theatre", "Dance"):                "Theater & Stage",
    ("Sports", None):                           "Sports & Recreation",
    ("Family", None):                           "Family & Kids",
}


class TicketmasterSource(BaseSource):
    name = "Ticketmaster"
    scraper_type = "api"

    def fetch(self) -> list[RawEvent]:
        if not settings.ticketmaster_api_key:
            raise ValueError("TICKETMASTER_API_KEY is not set")

        today = datetime.now(_CENTRAL).date()
        end = today + timedelta(days=_WINDOW_DAYS)
        start_iso = _utc_iso_z(datetime.combine(today, dtime.min, tzinfo=_CENTRAL))
        end_iso = _utc_iso_z(datetime.combine(end, dtime.max, tzinfo=_CENTRAL))

        events: list[RawEvent] = []
        page = 0
        while True:
            params = {
                "apikey": settings.ticketmaster_api_key,
                "city": "Madison",
                "stateCode": "WI",
                "countryCode": "US",
                "startDateTime": start_iso,
                "endDateTime": end_iso,
                "size": _PAGE_SIZE,
                "page": page,
                "sort": "date,asc",
            }
            resp = http_get_with_retry(
                _API_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=30,
            )
            data = resp.json()
            docs = (data.get("_embedded") or {}).get("events") or []
            for doc in docs:
                event = _parse_event(doc)
                if event is not None:
                    events.append(event)
            total_pages = (data.get("page") or {}).get("totalPages") or 1
            if not docs or page + 1 >= total_pages:
                break
            page += 1
            time.sleep(_PAGE_SLEEP_SECONDS)

        return events


def _utc_iso_z(dt: datetime) -> str:
    """Convert an aware datetime to ``YYYY-MM-DDTHH:MM:SSZ`` (Discovery API format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_local_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_local_time(raw: str | None) -> dtime | None:
    if not raw:
        return None
    try:
        return dtime.fromisoformat(raw)
    except ValueError:
        return None


def _build_address(venue: dict) -> str | None:
    line1 = ((venue.get("address") or {}).get("line1") or "").strip()
    city = ((venue.get("city") or {}).get("name") or "").strip()
    state = ((venue.get("state") or {}).get("stateCode") or "").strip()
    zipc = (venue.get("postalCode") or "").strip()
    parts: list[str] = []
    if line1:
        parts.append(line1)
    if city:
        parts.append(city)
    state_zip = " ".join(p for p in (state, zipc) if p).strip()
    if state_zip:
        parts.append(state_zip)
    return ", ".join(parts) or None


def _select_image(images: list[dict]) -> str | None:
    """Pick the largest 16:9 image; fall back to the first usable URL."""
    best: dict | None = None
    for img in images or []:
        if not isinstance(img, dict) or not img.get("url"):
            continue
        if img.get("ratio") == "16_9":
            if best is None or (img.get("width") or 0) > (best.get("width") or 0):
                best = img
    if best is not None:
        return best.get("url")
    for img in images or []:
        if isinstance(img, dict) and img.get("url"):
            return img["url"]
    return None


def _map_categories(classifications: list[dict]) -> list[str]:
    if not classifications:
        return []
    primary = next(
        (c for c in classifications if isinstance(c, dict) and c.get("primary")),
        None,
    )
    if primary is None:
        return []
    seg = ((primary.get("segment") or {}).get("name") or "").strip() or None
    gen = ((primary.get("genre") or {}).get("name") or "").strip() or None
    if seg is None:
        return []
    mapped = _CATEGORY_MAP.get((seg, gen)) or _CATEGORY_MAP.get((seg, None))
    return [mapped] if mapped else []


def _parse_event(doc: dict) -> RawEvent | None:
    dates = doc.get("dates") or {}
    status = ((dates.get("status") or {}).get("code") or "").strip().lower()
    if status in _DROP_STATUSES:
        return None

    title = (doc.get("name") or "").strip()
    source_url = (doc.get("url") or "").strip()
    if not title or not source_url:
        return None

    venues = (doc.get("_embedded") or {}).get("venues") or []
    venue = venues[0] if venues else None
    if not isinstance(venue, dict):
        return None

    start_block = dates.get("start") or {}
    event_date = _parse_local_date(start_block.get("localDate"))
    if event_date is None:
        return None

    tz_name = dates.get("timezone") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = _CENTRAL

    local_time = _parse_local_time(start_block.get("localTime"))
    time_tba = bool(start_block.get("timeTBA")) or bool(start_block.get("noSpecificTime"))
    if local_time is None or time_tba:
        start_at = datetime.combine(event_date, dtime.min, tzinfo=tz)
        all_day = True
    else:
        start_at = datetime.combine(event_date, local_time, tzinfo=tz)
        all_day = False

    end_at: datetime | None = None
    end_block = dates.get("end") or {}
    end_date = _parse_local_date(end_block.get("localDate"))
    if dates.get("spanMultipleDays") and end_date is not None:
        end_time = _parse_local_time(end_block.get("localTime")) or dtime.max
        end_at = datetime.combine(end_date, end_time, tzinfo=tz)

    description = (doc.get("info") or doc.get("pleaseNote") or "").strip() or None

    venue_name = (venue.get("name") or "").strip() or None
    venue_address = _build_address(venue)
    image_url = _select_image(doc.get("images") or [])
    categories = _map_categories(doc.get("classifications") or [])

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=image_url,
        categories=categories,
        all_day=all_day,
        source_name="Ticketmaster",
        source_url=source_url,
    )
