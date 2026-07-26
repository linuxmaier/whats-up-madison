import logging
import re
from datetime import datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.base import BaseSource, RawEvent, http_get_with_retry

logger = logging.getLogger(__name__)

_CALENDAR_URL = "https://high-noon.com/calendar/"
_CENTRAL = ZoneInfo("America/Chicago")
_VENUE_ADDRESS = "701 E. Washington Ave, Madison, WI 53703"
_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$")
_SHOW_TIME_RE = re.compile(r"Show:\s*(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
_DOORS_TIME_RE = re.compile(r"Doors:\s*(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
_CLASSIFICATION_PREFIX = "tm_classifications-"

# Conservative mapping: only High Noon classifications that map unambiguously
# to our taxonomy. All music-genre slugs collapse to "Music"; ambiguous or
# pure-origin tags (e.g. "local") are dropped so the LLM tagger can still
# enrich them later if descriptions improve.
_MUSIC_GENRE_SLUGS: frozenset[str] = frozenset({
    "adult-contemporary", "alternative-rock", "americana", "bluegrass", "blues",
    "country", "dance-electronic", "edm", "electro-pop", "folk", "funk",
    "hip-hop-rap", "indie-folk", "indie-pop", "indie-rock", "jam", "metal",
    "metal-rock", "music", "nu-metal", "pop", "punk", "rb", "reggae", "rock",
    "ska", "soul", "trap",
})
_NON_MUSIC_MAP: dict[str, str] = {
    "arts-theatre": "Theater & Stage",
    "the-moth": "Talks & Learning",
    "use-your-noggin": "Talks & Learning",
    "nerd-nite": "Talks & Learning",
}


class HighNoonSource(BaseSource):
    name = "High Noon Saloon"
    scraper_type = "html"
    supports_window_days = False

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        resp = http_get_with_retry(_CALENDAR_URL, timeout=30)
        soup = BeautifulSoup(resp.content, "lxml")
        events: list[RawEvent] = []
        for card in soup.select("article.event-card"):
            event = _parse_card(card)
            if event is not None:
                events.append(event)
        return events


def _text(card, selector: str) -> str | None:
    el = card.select_one(selector)
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    return text or None


def _parse_date(text: str) -> datetime | None:
    """Parse 'May 7, 2026' into a Central-time-aware datetime at midnight."""
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        d = datetime.strptime(text.strip(), "%B %d, %Y").date()
    except ValueError:
        return None
    return datetime.combine(d, dtime.min, tzinfo=_CENTRAL)


def _extract_time(times_str: str) -> dtime | None:
    """Prefer Show: HH:MM am|pm; fall back to Doors: HH:MM am|pm."""
    for pattern in (_SHOW_TIME_RE, _DOORS_TIME_RE):
        m = pattern.search(times_str)
        if m:
            try:
                return datetime.strptime(
                    f"{m.group(1)}:{m.group(2)} {m.group(3).upper()}", "%I:%M %p"
                ).time()
            except ValueError:
                continue
    return None


def _extract_categories(card) -> list[str]:
    seen: list[str] = []
    for cls in card.get("class", []):
        if not cls.startswith(_CLASSIFICATION_PREFIX):
            continue
        slug = cls[len(_CLASSIFICATION_PREFIX):]
        mapped: str | None = None
        if slug in _MUSIC_GENRE_SLUGS:
            mapped = "Music"
        elif slug in _NON_MUSIC_MAP:
            mapped = _NON_MUSIC_MAP[slug]
        if mapped and mapped not in seen:
            seen.append(mapped)
    return seen


def _build_description(presented_by: str | None, supporting: str | None) -> str | None:
    parts = [p for p in (presented_by, supporting) if p]
    return "\n".join(parts) if parts else None


def _parse_card(card) -> RawEvent | None:
    title_el = card.select_one(".event-title a")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    source_url = title_el.get("href")
    if not title or not source_url:
        return None

    date_text = _text(card, ".event-date")
    if not date_text:
        return None
    base_dt = _parse_date(date_text)
    if base_dt is None:
        logger.warning("High Noon: unparseable event-date %r for %r", date_text, title)
        return None

    times_text = _text(card, ".event-times") or ""
    show_time = _extract_time(times_text)
    if show_time is not None:
        start_at = base_dt.replace(hour=show_time.hour, minute=show_time.minute)
        all_day = False
    else:
        start_at = base_dt
        all_day = True

    venue_name = _text(card, ".event-venue") or "High Noon Saloon"
    venue_address = _VENUE_ADDRESS if venue_name.lower() == "high noon saloon" else None

    description = _build_description(
        _text(card, ".event-presented-by"),
        _text(card, ".event-supporting-acts"),
    )

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=None,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        categories=_extract_categories(card),
        all_day=all_day,
        source_name="High Noon Saloon",
        source_url=source_url,
    )
