import html
import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_API_URL = "https://downtownmadison.org/wp-json/tribe/events/v1/events"
_USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 50
_PAGE_SLEEP_SECONDS = 1.0

# Downtown Madison Inc. also publishes internal-committee meetings on this
# calendar (Board of Directors, Executive Committee, Transportation, etc.) —
# not events the general public attends. The "dmi-events" category collects
# DMI's public-facing slate (What's Up Downtown, New Faces New Places, Behind
# The Scenes, IDA Place Matters, the I.D.E.A. Series, Annual Celebration).
_DMI_PUBLIC_CATEGORY = "dmi-events"

# Same Madison-metro filter as Our Lives — DMI events should all be local, but
# the filter is cheap and matches the project's "only Madison metro" invariant.
_METRO_CITIES: frozenset[str] = frozenset({
    "madison", "middleton", "verona", "sun prairie", "waunakee",
    "fitchburg", "monona", "mcfarland", "stoughton",
})
_MADISON_ZIP_RE = re.compile(r"\b537\d{2}\b")


class DMISource(BaseSource):
    name = "DMI"
    scraper_type = "api"

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        today = datetime.now(_CENTRAL).date()
        end = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)
        events: list[RawEvent] = []
        page = 1
        while True:
            params = {
                "per_page": _PAGE_SIZE,
                "page": page,
                "categories": _DMI_PUBLIC_CATEGORY,
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
        return False
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


def _parse_event(doc: dict) -> RawEvent | None:
    venue = _venue_dict(doc.get("venue"))
    if not _in_madison_metro(venue):
        return None

    # The DMI API ships HTML entities raw in titles (e.g. `What&#8217;s Up
    # Downtown`), unlike Our Lives' API which decodes them server-side. Unescape
    # here so the canonical_hash and rendered card text are both clean.
    title = html.unescape((doc.get("title") or "").strip())
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
        logger.warning("DMI: unparseable start_date %r for %r",
                       doc.get("start_date"), title)
        return None

    end_at = _parse_dt(doc.get("end_date"), tz)
    all_day = bool(doc.get("all_day"))
    if all_day:
        start_at = start_at.replace(hour=0, minute=0, second=0, microsecond=0)
        if end_at is not None and end_at.date() == start_at.date():
            end_at = None

    description = clean_html_text(doc.get("description") or "") or None

    # Same entity-decoding issue as the title — the DMI feed ships venue names
    # like "RDG Planning &#038; Design" raw. Decode so the card and the canonical
    # hash both see "RDG Planning & Design".
    venue_name = html.unescape((venue.get("venue") or "").strip()) or None
    venue_address = _build_address(venue)

    # No source-category mapping: DMI's tags are program-specific
    # ("whats-up-downtown", "new-faces-new-places", "the-i-d-e-a-series") and
    # don't map cleanly to our closed taxonomy. The LLM tagger pass (Step 4)
    # handles these — descriptions are rich enough to support good tags.
    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=_extract_image_url(doc.get("image")),
        categories=[],
        all_day=all_day,
        source_name="DMI",
        source_url=source_url,
    )
