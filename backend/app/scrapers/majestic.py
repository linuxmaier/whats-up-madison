import logging
import re
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_CALENDAR_URL = "https://majesticmadison.com/calendar/"
_CENTRAL = ZoneInfo("America/Chicago")
_VENUE_NAME = "Majestic Theatre"
_VENUE_ADDRESS = "115 King St, Madison, WI 53703"
_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})$")
_SHOW_TIME_RE = re.compile(r"Show:\s*(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
_DOORS_TIME_RE = re.compile(r"Doors:\s*(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)
_CLASSIFICATION_PREFIX = "tm_classifications-"

# Courtesy delay between detail-page fetches. Majestic publishes ~31 events;
# at 0.3s that adds ~10s to the scrape but keeps us well under any rate
# limit the WordPress host might enforce.
_FETCH_DELAY = 0.3

# Exact <h2> text of the detail-page section that carries the show-specific
# write-up. Sister sections ("<Artist> Bio", venue-info blocks) are dropped
# — per the audit-event-accuracy skill's High Noon exception, promotional
# artist bios are not appropriate for the card description.
_EVENT_DESCRIPTION_HEADING = "Event Description"

# Conservative classification mapping. Music genres collapse to "Music";
# comedy → "Open Mic & Comedy" (matches the Ticketmaster mapping in
# scrapers/ticketmaster.py); ambiguous slugs are dropped so the LLM tagger
# can still enrich them later.
_MUSIC_GENRE_SLUGS: frozenset[str] = frozenset({
    "adult-contemporary", "alternative-rock", "americana", "bluegrass", "blues",
    "country", "dance-electronic", "dance-party", "edm", "electro-pop",
    "electronic", "folk", "funk", "hip-hop-rap", "hyperpop", "indie-folk",
    "indie-pop", "indie-rock", "jam", "jazz", "metal", "metal-rock", "music",
    "nu-metal", "pop", "punk", "rb", "reggae", "rock", "ska", "soul", "trap",
})
_NON_MUSIC_MAP: dict[str, str] = {
    "arts-theatre": "Theater & Stage",
    "comedy": "Open Mic & Comedy",
    "the-moth": "Talks & Learning",
    "use-your-noggin": "Talks & Learning",
    "nerd-nite": "Talks & Learning",
}


class MajesticTheatreSource(BaseSource):
    name = "Majestic Theatre"
    scraper_type = "html"
    # The calendar renders whatever is currently posted (~7-month forward
    # window in practice); no API parameter controls the size, so days=N is
    # a no-op for this scraper.
    supports_window_days = False

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        resp = http_get_with_retry(_CALENDAR_URL, timeout=30)
        soup = BeautifulSoup(resp.content, "lxml")
        events: list[RawEvent] = []
        for card in soup.select("article.event-card"):
            event = _parse_card(card)
            if event is None:
                continue
            detail_desc = _fetch_detail_description(event.source_url)
            if detail_desc:
                event.description = detail_desc
            events.append(event)
            time.sleep(_FETCH_DELAY)
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


def _build_card_description(presented_by: str | None, supporting: str | None) -> str | None:
    parts = [p for p in (presented_by, supporting) if p]
    return "\n".join(parts) if parts else None


def _extract_event_description(soup: BeautifulSoup) -> str | None:
    """Return the text of the `<h2>Event Description</h2>` section, or None.

    Drops `<Artist> Bio`-titled sections (the FPC theme renders these as
    separate `section.event-section` blocks with a different heading), so a
    page with both ends up surfacing only the show-specific copy.
    """
    for section in soup.select("section.event-section"):
        heading = section.select_one("h2")
        if heading is None:
            continue
        if heading.get_text(strip=True) != _EVENT_DESCRIPTION_HEADING:
            continue
        body = section.select_one(".event-section-content")
        if body is None:
            continue
        text = clean_html_text(body.get_text(separator=" "))
        return text or None
    return None


def _fetch_detail_description(url: str) -> str | None:
    try:
        resp = http_get_with_retry(url, timeout=15)
    except Exception as exc:
        logger.warning("Majestic: failed to fetch detail page %s: %s", url, exc)
        return None
    soup = BeautifulSoup(resp.content, "lxml")
    return _extract_event_description(soup)


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
        logger.warning("Majestic: unparseable event-date %r for %r", date_text, title)
        return None

    times_text = _text(card, ".event-times") or ""
    show_time = _extract_time(times_text)
    if show_time is not None:
        start_at = base_dt.replace(hour=show_time.hour, minute=show_time.minute)
        all_day = False
    else:
        start_at = base_dt
        all_day = True

    description = _build_card_description(
        _text(card, ".event-presented-by"),
        _text(card, ".event-supporting-acts"),
    )

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=None,
        venue_name=_VENUE_NAME,
        venue_address=_VENUE_ADDRESS,
        description=description,
        categories=_extract_categories(card),
        all_day=all_day,
        source_name="Majestic Theatre",
        source_url=source_url,
    )
