import logging
import re
from datetime import datetime, time as dtime, timedelta
from urllib.parse import unquote, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.theatwoodmusichall.com"
_CALENDAR_URL = f"{_BASE_URL}/shows"
_CENTRAL = ZoneInfo("America/Chicago")
_DEFAULT_VENUE_NAME = "Atwood Music Hall"
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s*$", re.IGNORECASE)
# Atwood's structured `event-time-localized-*` fields are unreliable placeholders
# (commonly nominal "8:00 PM - 9:00 PM" regardless of the real show time). The
# excerpt's "Show <time>" line is what the venue actually communicates as the
# show time — observed off by 1-3 hours from the structured times across the
# entire current calendar. Match "Show 11PM", "Show: 6:00pm", "Show 7:30 PM",
# "/ Show 8pm", etc. Capture groups: hour, optional :minute, am|pm.
_DESC_SHOW_RE = re.compile(
    r"\bShow\b\s*[:/]?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE
)
_DESC_DOORS_RE = re.compile(
    r"\bDoors\b\s*[:/]?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE
)


class AtwoodMusicHallSource(BaseSource):
    name = "Atwood Music Hall"
    scraper_type = "html"
    supports_window_days = False

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        resp = http_get_with_retry(_CALENDAR_URL, timeout=30)
        soup = BeautifulSoup(resp.content, "lxml")
        events: list[RawEvent] = []
        # `eventlist-event--upcoming` filters out the past-show siblings the page
        # still ships (~30 of them at any time) so we don't resurrect events the
        # ingest staleness sweep already deactivated.
        for card in soup.select("article.eventlist-event--upcoming"):
            event = _parse_card(card)
            if event is not None:
                events.append(event)
        return events


def _parse_time(text: str) -> dtime | None:
    m = _TIME_RE.match(text)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)}:{m.group(2)} {m.group(3).upper()}", "%I:%M %p"
        ).time()
    except ValueError:
        return None


def _parse_date(card: Tag) -> datetime | None:
    el = card.select_one("time.event-date")
    if el is None:
        return None
    iso = (el.get("datetime") or "").strip()
    if not iso:
        return None
    try:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return None
    return datetime.combine(d, dtime.min, tzinfo=_CENTRAL)


def _extract_venue(card: Tag) -> tuple[str, str | None]:
    """Return (venue_name, venue_address). Atwood's page also lists Barrymore /
    Liquid events with their own address — venue is per-card, not hardcoded."""
    li = card.select_one("li.eventlist-meta-address")
    if li is None:
        return _DEFAULT_VENUE_NAME, None

    # The <li> contains the venue name as raw text plus an <a class="...maplink">.
    # Strip the link text so we're left with just the venue name.
    name_parts: list[str] = []
    for child in li.children:
        if isinstance(child, Tag):
            classes = child.get("class") or []
            if "eventlist-meta-address-maplink" in classes:
                continue
            name_parts.append(child.get_text(" ", strip=True))
        else:
            name_parts.append(str(child).strip())
    venue_name = " ".join(p for p in name_parts if p).strip() or _DEFAULT_VENUE_NAME

    address: str | None = None
    maplink = li.select_one("a.eventlist-meta-address-maplink")
    if maplink is not None:
        href = maplink.get("href") or ""
        # href is like: http://maps.google.com?q=1925 Winnebago Avenue Madison, WI, 53704 United States
        idx = href.find("q=")
        if idx >= 0:
            raw = unquote(href[idx + 2 :]).strip()
            address = _normalize_address(raw)

    return venue_name, address


def _normalize_address(raw: str) -> str | None:
    # Drop the trailing "United States" / ", United States" — Madison-only
    # geocoding doesn't need it and it clutters the displayed address card.
    s = re.sub(r",?\s*United States\s*$", "", raw, flags=re.IGNORECASE).strip()
    # Collapse "Madison, WI, 53704" → "Madison, WI 53704" so it matches the
    # canonical-address style used elsewhere in the codebase.
    s = re.sub(r"(,\s*WI),\s*(\d{5})", r"\1 \2", s)
    return s or None


def _extract_image(card: Tag) -> str | None:
    img = card.select_one(".eventlist-column-thumbnail img")
    if img is None:
        return None
    return img.get("data-image") or img.get("src")


def _extract_description(card: Tag) -> str | None:
    excerpt = card.select_one(".eventlist-excerpt")
    if excerpt is None:
        return None
    text = clean_html_text(str(excerpt))
    return text or None


def _show_time_from_description(description: str | None) -> dtime | None:
    """Pull the actual show time out of the excerpt. Prefers `Show <time>`;
    falls back to `Doors <time>` (better than nothing — about an hour earlier
    than the show, but on the right calendar day)."""
    if not description:
        return None
    for pattern in (_DESC_SHOW_RE, _DESC_DOORS_RE):
        m = pattern.search(description)
        if m:
            hour = m.group(1)
            minute = m.group(2) or "00"
            ampm = m.group(3).upper()
            try:
                return datetime.strptime(
                    f"{hour}:{minute} {ampm}", "%I:%M %p"
                ).time()
            except ValueError:
                continue
    return None


def _build_start_end(
    base_dt: datetime, card: Tag, description: str | None
) -> tuple[datetime, datetime | None, bool]:
    # Prefer the show time mined from the excerpt — the structured
    # `event-time-localized-*` fields on Atwood's page are placeholders, not
    # the real show time. When we use the excerpt time we drop end_at: the
    # structured end is just nominal-start + 1h and would be just as wrong.
    desc_time = _show_time_from_description(description)
    if desc_time is not None:
        start_at = base_dt.replace(hour=desc_time.hour, minute=desc_time.minute)
        return start_at, None, False

    start_el = card.select_one("time.event-time-localized-start")
    if start_el is None:
        return base_dt, None, True

    start_time = _parse_time(start_el.get_text(strip=True))
    if start_time is None:
        return base_dt, None, True

    start_at = base_dt.replace(hour=start_time.hour, minute=start_time.minute)

    end_at: datetime | None = None
    end_el = card.select_one("time.event-time-localized-end")
    if end_el is not None:
        end_time = _parse_time(end_el.get_text(strip=True))
        if end_time is not None:
            end_at = base_dt.replace(hour=end_time.hour, minute=end_time.minute)
            # Cross-midnight shows: end ≤ start means the end is the next day.
            if end_at <= start_at:
                end_at = end_at + timedelta(days=1)

    return start_at, end_at, False


def _parse_card(card: Tag) -> RawEvent | None:
    title_el = card.select_one("h1.eventlist-title a.eventlist-title-link")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    href = title_el.get("href") or ""
    if not title or not href:
        return None

    base_dt = _parse_date(card)
    if base_dt is None:
        logger.warning("Atwood: unparseable event-date for %r", title)
        return None

    source_url = urljoin(_BASE_URL, href)

    description = _extract_description(card)
    start_at, end_at, all_day = _build_start_end(base_dt, card, description)

    venue_name, venue_address = _extract_venue(card)

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=_extract_image(card),
        categories=[],
        all_day=all_day,
        source_name="Atwood Music Hall",
        source_url=source_url,
    )
