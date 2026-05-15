import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

# The calendar page (`/concerts-tickets/calendar`) loads its cards via this
# AJAX endpoint. Returns the whole upcoming WCO slate as server-rendered
# HTML cards — no forward-window parameter, so `supports_window_days = False`.
_LISTING_URL = "https://wcoconcerts.org/load/events?timespan=upcoming&limit=30"
_CENTRAL = ZoneInfo("America/Chicago")
_FETCH_DELAY = 0.5  # courtesy delay between detail-page fetches

# Datetime block forms observed on /load/events:
#   single:  "Saturday, May 16, 2026 — 7:00 PM"
#   range:   "Wednesday, June 24, 2026 — 7:00 PM\n\t\tto\nWednesday, June 24, 2026 — 9:00 PM"
# The leading weekday name is decorative — anchor on "<Month> <day>, <year>"
# optionally followed by an em-dash and a clock time. The em-dash is U+2014;
# we also accept a hyphen as a fallback in case the site ever flattens it.
_DT_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),\s+(\d{4})"
    r"(?:\s*[—\-]+\s*(\d{1,2}):(\d{2})\s*(AM|PM))?",
    re.IGNORECASE,
)


class WisconsinChamberOrchestraSource(BaseSource):
    name = "Wisconsin Chamber Orchestra"
    scraper_type = "html"
    supports_window_days = False

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        resp = http_get_with_retry(_LISTING_URL, timeout=30)
        soup = BeautifulSoup(resp.content, "lxml")
        events: list[RawEvent] = []
        ok = fail = 0
        for row in soup.select("div.row.event"):
            event = _parse_row(row)
            if event is None:
                continue
            time.sleep(_FETCH_DELAY)
            detail_desc = _fetch_detail_description(event.source_url)
            if detail_desc:
                event.description = detail_desc
                ok += 1
            else:
                fail += 1
            events.append(event)
        logger.info(
            "Wisconsin Chamber Orchestra: detail enrichment %d/%d succeeded",
            ok, ok + fail,
        )
        return events


def _text(node: Tag | None, selector: str) -> str | None:
    if node is None:
        return None
    el = node.select_one(selector)
    if el is None:
        return None
    text = el.get_text(separator=" ", strip=True)
    return text or None


def _parse_datetimes(dt_text: str) -> tuple[datetime, datetime | None, bool] | None:
    """Parse the `.datetime` block.

    Returns (start_at, end_at, all_day) or None if no date could be parsed.
    `all_day` is True when a date matched but no clock time was present.
    """
    matches = list(_DT_RE.finditer(dt_text))
    if not matches:
        return None

    start = _match_to_datetime(matches[0])
    if start is None:
        return None
    end: datetime | None = None
    if len(matches) > 1:
        end = _match_to_datetime(matches[1])

    # all_day flag tracks the *start* row only — end is dropped if the start
    # was all-day so we don't carry through an inconsistent end timestamp.
    start_has_time = matches[0].group(4) is not None
    if not start_has_time:
        return start, None, True
    return start, end, False


def _match_to_datetime(m: re.Match[str]) -> datetime | None:
    month, day, year = m.group(1), m.group(2), m.group(3)
    hour_s, minute_s, ampm = m.group(4), m.group(5), m.group(6)
    try:
        d = datetime.strptime(f"{month} {day}, {year}", "%B %d, %Y").date()
    except ValueError:
        return None
    if hour_s is None:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=_CENTRAL)
    try:
        t = datetime.strptime(f"{hour_s}:{minute_s} {ampm.upper()}", "%I:%M %p").time()
    except ValueError:
        return datetime(d.year, d.month, d.day, 0, 0, tzinfo=_CENTRAL)
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=_CENTRAL)


def _normalize_venue(raw: str | None) -> str | None:
    """Strip the building-name suffix WCO appends with an em-dash.

    Examples:
      "Capitol Theater — Overture Center for the Arts" -> "Capitol Theater"
        (then canonical_venues normalizes "Capitol Theater" to the full Overture
        building name during ingest, so cross-source dedup works.)
      "Hamel Music Center — University of Wisconsin-Madison" -> "Hamel Music Center"
      "King Street corner of the Capitol Square" -> unchanged

    Taking the part before the em-dash gives the most specific room/landmark
    name, which is what other sources tend to use as well.
    """
    if not raw:
        return None
    parts = re.split(r"\s*[—]\s*", raw, maxsplit=1)
    return parts[0].strip() or None


def _extract_source_url(row: Tag) -> str | None:
    """The Event Details button and the listing image both point to the same
    detail page (`/events/<slug>`). Prefer the image-link as it always exists;
    fall back to the first `.cta a.button` that points at the events path."""
    img_link = row.select_one("a.image")
    if img_link is not None:
        href = img_link.get("href") or ""
        if "/events/" in href:
            return href
    for a in row.select(".cta a.button"):
        href = a.get("href") or ""
        if "/events/" in href:
            return href
    return None


def _extract_image(row: Tag) -> str | None:
    img = row.select_one("a.image img")
    if img is None:
        return None
    return img.get("src")


def _fetch_detail_description(url: str) -> str | None:
    """Pull event-specific show copy from the detail page.

    Detail pages have several `.block.text` panels inside `.section.content`:
    the first is the show write-up, subsequent ones are "Table Reservations" /
    "Plan Your Visit" / "About <Artist>" boilerplate. We take only the first
    so artist bios and venue-policy text don't bloat the card description.
    """
    try:
        resp = http_get_with_retry(url, timeout=15)
    except Exception as exc:
        logger.warning("WCO: failed to fetch detail page %s: %s", url, exc)
        return None
    soup = BeautifulSoup(resp.content, "lxml")
    content = soup.select_one(".section.content")
    if content is None:
        return None
    first_block = content.select_one(".block.text")
    if first_block is None:
        return None
    paras = [clean_html_text(p.get_text(" ", strip=True)) for p in first_block.select("p")]
    text = "\n".join(p for p in paras if p)
    return text or None


def _parse_row(row: Tag) -> RawEvent | None:
    title_el = row.select_one("h2.title")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    if not title:
        return None

    source_url = _extract_source_url(row)
    if not source_url:
        return None

    dt_text = _text(row, ".datetime")
    if not dt_text:
        logger.warning("WCO: missing .datetime for %r", title)
        return None
    parsed = _parse_datetimes(dt_text)
    if parsed is None:
        logger.warning("WCO: unparseable .datetime %r for %r", dt_text, title)
        return None
    start_at, end_at, all_day = parsed

    venue_name = _normalize_venue(_text(row, ".venue"))

    # Subtitle is used as a listing-only description fallback. Detail-page
    # enrichment replaces this in fetch() when it succeeds.
    subtitle = _text(row, ".subtitle")

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=None,
        description=subtitle,
        image_url=_extract_image(row),
        categories=["Music"],
        all_day=all_day,
        source_name="Wisconsin Chamber Orchestra",
        source_url=source_url,
    )
