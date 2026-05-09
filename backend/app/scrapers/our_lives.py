import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_API_URL = "https://ourliveswisconsin.com/wp-json/tribe/events/v1/events"
_USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 50
_PAGE_SLEEP_SECONDS = 1.0

# Madison metro: city + immediate Dane County suburbs that the broader app
# already treats as "Madison". Outside this set we drop the event.
_METRO_CITIES: frozenset[str] = frozenset({
    "madison", "middleton", "verona", "sun prairie", "waunakee",
    "fitchburg", "monona", "mcfarland", "stoughton",
})
_MADISON_ZIP_RE = re.compile(r"\b537\d{2}\b")

# Conservative mapping from The Events Calendar (Tribe) taxonomy on Our Lives
# to our closed taxonomy. Ambiguous, regional, audience-targeting, and one-off
# tags are intentionally dropped so the LLM tagger (Step 4) can still enrich
# them later if descriptions support it.
_CATEGORY_MAP: dict[str, str] = {
    "Music":           "Music",
    "Comedy":          "Open Mic & Comedy",
    "Dance":           "Dance",
    "Theater":         "Theater & Stage",
    "Performance Art": "Theater & Stage",
    "Drag":            "Theater & Stage",
    "Workshop":        "Talks & Learning",
    "Lecture":         "Talks & Learning",
    "Reading":         "Talks & Learning",
    "Art Exhibition":  "Visual Art",
    "Activism":        "Civic & Politics",
    "Fundraiser":      "Volunteer & Causes",
    "Sports":          "Sports & Recreation",
    "Networking":      "Community & Clubs",
    "Community":       "Community & Clubs",
    "Outdoor":         "Outdoors & Nature",
    "Food":            "Food & Drink",
    "Market":          "Food & Drink",
}


class OurLivesSource(BaseSource):
    name = "Our Lives"
    scraper_type = "api"

    def fetch(self) -> list[RawEvent]:
        today = datetime.now(_CENTRAL).date()
        end = today + timedelta(days=_WINDOW_DAYS)
        events: list[RawEvent] = []
        page = 1
        while True:
            params = {
                "per_page": _PAGE_SIZE,
                "page": page,
                "start_date": today.isoformat(),
                "end_date": end.isoformat(),
            }
            resp = http_get_with_retry(
                _API_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=30,
            )
            data = resp.json()
            docs = data.get("events") or []
            for doc in docs:
                event = _parse_event(doc)
                if event is not None:
                    events.append(event)
            total_pages = data.get("total_pages") or 1
            if page >= total_pages or not docs:
                break
            page += 1
            time.sleep(_PAGE_SLEEP_SECONDS)
        return events


def _venue_dict(raw) -> dict | None:
    """Tribe returns venue as a dict, an empty list, or omits it. Normalize."""
    if isinstance(raw, dict):
        return raw or None
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw[0]
    return None


def _in_madison_metro(venue: dict | None) -> bool:
    if not venue:
        return False
    city = (venue.get("city") or "").strip().lower()
    if city in _METRO_CITIES:
        return True
    if city:
        # Non-empty but not in allowlist — reject.
        return False
    # No city set: fall back to address-based heuristics for venues like the
    # Overture Center that are unambiguously Madison but missing the field.
    address = (venue.get("address") or "").lower()
    if "madison" in address:
        return True
    if _MADISON_ZIP_RE.search(venue.get("zip") or ""):
        return True
    if _MADISON_ZIP_RE.search(address):
        return True
    return False


def _parse_dt(raw: str | None, tz: ZoneInfo) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None


def _build_address(venue: dict) -> str | None:
    parts: list[str] = []
    addr = (venue.get("address") or "").strip()
    if addr:
        parts.append(addr)
    city = (venue.get("city") or "").strip()
    if city:
        parts.append(city)
    state = (venue.get("state") or "").strip()
    zipc = (venue.get("zip") or "").strip()
    state_zip = " ".join(p for p in (state, zipc) if p).strip()
    if state_zip:
        parts.append(state_zip)
    return ", ".join(parts) or None


def _extract_image_url(image) -> str | None:
    if isinstance(image, dict):
        url = image.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _extract_categories(api_categories) -> list[str]:
    if not isinstance(api_categories, list):
        return []
    seen: list[str] = []
    for cat in api_categories:
        if not isinstance(cat, dict):
            continue
        name = cat.get("name")
        if not isinstance(name, str):
            continue
        mapped = _CATEGORY_MAP.get(name.strip())
        if mapped and mapped not in seen:
            seen.append(mapped)
    return seen


def _parse_event(doc: dict) -> RawEvent | None:
    venue = _venue_dict(doc.get("venue"))
    if not _in_madison_metro(venue):
        return None

    title = (doc.get("title") or "").strip()
    source_url = (doc.get("url") or "").strip()
    if not title or not source_url:
        return None

    tz_name = doc.get("timezone") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = _CENTRAL

    start_at = _parse_dt(doc.get("start_date"), tz)
    if start_at is None:
        logger.warning("Our Lives: unparseable start_date %r for %r",
                       doc.get("start_date"), title)
        return None

    end_at = _parse_dt(doc.get("end_date"), tz)
    all_day = bool(doc.get("all_day"))
    if all_day:
        # Tribe returns midnight-to-midnight for all-day; only keep an end_at
        # if the event actually spans more than one day.
        start_at = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_at is not None and end_at.date() == start_at.date():
            end_at = None

    description = clean_html_text(doc.get("description") or "") or None

    venue_name = (venue.get("venue") or "").strip() or None
    venue_address = _build_address(venue)

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=_extract_image_url(doc.get("image")),
        categories=_extract_categories(doc.get("categories")),
        all_day=all_day,
        source_name="Our Lives",
        source_url=source_url,
    )
