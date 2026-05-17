import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.cityofmadison.com/events"
# The site's WAF returns 403 for ?page=N requests without a browser-like UA.
_USER_AGENT = "Mozilla/5.0 (compatible; whats-up-madison/0.1; +mailto:andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SLEEP = 0.5
_DETAIL_SLEEP = 1.0

# Matches "8:00am", "12:30pm", "1:00am", etc.
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*(am|pm)", re.IGNORECASE)


class CityOfMadisonSource(BaseSource):
    name = "City of Madison"
    scraper_type = "html"
    supports_window_days = True

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        today = datetime.now(_CENTRAL).date()
        cutoff = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)
        headers = {"User-Agent": _USER_AGENT}

        raw_events: list[RawEvent] = []
        page = 0
        done = False
        while not done:
            params: dict = {} if page == 0 else {"page": page}
            resp = http_get_with_retry(_BASE_URL, params=params, headers=headers, timeout=30)
            soup = BeautifulSoup(resp.content, "lxml")
            items = soup.select("li div.event-content")
            if not items:
                break
            for item in items:
                ev = _parse_item(item)
                if ev is None:
                    continue
                if ev.start_at.date() > cutoff:
                    done = True
                    break
                raw_events.append(ev)
            page += 1
            if not done:
                time.sleep(_PAGE_SLEEP)

        ok = fail = 0
        for ev in raw_events:
            time.sleep(_DETAIL_SLEEP)
            desc, full_addr = _fetch_detail(ev.source_url)
            if desc:
                ev.description = desc
                ok += 1
            else:
                fail += 1
            if full_addr:
                ev.venue_address = full_addr

        logger.info(
            "City of Madison: %d events, detail enrichment %d/%d succeeded",
            len(raw_events), ok, ok + fail,
        )
        return raw_events


def _parse_start_at(dt_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return None


def _parse_time_text(time_text: str) -> datetime | None:
    """Parse a single time token like '8:00am' or '10:00am' into a naive time."""
    m = _TIME_RE.search(time_text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}:{m.group(2)} {m.group(3).upper()}", "%I:%M %p")
    except ValueError:
        return None


def _parse_time_range(start_at: datetime, time_text: str) -> tuple[datetime | None, bool]:
    """Return (end_at, all_day) from the visible time-range text.

    Formats observed:
      "All day"           → (None, True)
      "8:00am – 10:00am"  → (end_at, False)
      "1:00pm – 2:00pm"   → (end_at, False)
      anything else       → (None, False)

    The en-dash separator (U+2013) is used by the site; we also handle a plain
    hyphen in case the markup ever changes.
    """
    text = time_text.strip()
    if not text or text.lower() == "all day":
        return None, True

    # Split on en-dash or hyphen between time tokens
    parts = re.split(r"\s*[–\-]\s*", text)
    if len(parts) >= 2:
        end_parsed = _parse_time_text(parts[1])
        if end_parsed is not None:
            end_at = start_at.replace(
                hour=end_parsed.hour,
                minute=end_parsed.minute,
                second=0,
                microsecond=0,
            )
            return end_at, False

    logger.debug("City of Madison: unrecognised time-range text %r", text)
    return None, False


def _parse_item(content: Tag) -> RawEvent | None:
    """Parse one `.event-content` div from the listing page."""
    # Title and URL
    title_el = content.select_one("h2.event-heading a, h3.event-heading a")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    href = title_el.get("href") or ""
    if not title or not href:
        return None
    source_url = href if href.startswith("http") else f"https://www.cityofmadison.com{href}"

    # Start datetime — from the sibling `time.start-date` in the parent `<li>`.
    # `content` is `.event-content`; climb to the `<li>` to find the date widget.
    li = content.find_parent("li")
    if li is None:
        return None
    start_el = li.select_one("time.start-date")
    if start_el is None:
        return None
    start_at = _parse_start_at(start_el.get("datetime") or "")
    if start_at is None:
        logger.warning("City of Madison: unparseable start datetime for %r", title)
        return None

    # Time range text — from the `<time>` element inside `.event-content`
    # (distinct from `time.start-date`; its text shows the human-readable range).
    range_el = content.select_one("time:not(.start-date)")
    if range_el is not None:
        # The element contains a visually-hidden div with the date; skip it.
        visible = range_el.find("div", class_="visually-hidden")
        if visible:
            visible.decompose()
        time_text = range_el.get_text(strip=True)
    else:
        time_text = ""
    end_at, all_day = _parse_time_range(start_at, time_text)

    # Venue name and street address
    venue_name: str | None = None
    venue_address: str | None = None
    addr_el = content.select_one("address")
    if addr_el is not None:
        name_el = addr_el.select_one(".address-location-name strong")
        if name_el:
            venue_name = name_el.get_text(strip=True) or None
        street_el = addr_el.select_one("span")
        if street_el:
            venue_address = _parse_address_from_span(street_el)

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=None,
        categories=[],
        all_day=all_day,
        source_name="City of Madison",
        source_url=source_url,
    )


def _parse_address_from_span(span_el: Tag) -> str | None:
    """Join all text lines from an address <span>, handling <br> separators."""
    parts = [t.strip() for t in span_el.strings if t.strip()]
    return ", ".join(parts) if parts else None


def _fetch_detail(url: str) -> tuple[str | None, str | None]:
    """Pull description and full venue address from the detail page."""
    try:
        resp = http_get_with_retry(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
    except Exception as exc:
        logger.warning("City of Madison: failed to fetch detail page %s: %s", url, exc)
        return None, None
    soup = BeautifulSoup(resp.content, "lxml")

    description: str | None = None
    body = soup.select_one(".field.body.text-with-summary")
    if body is not None:
        text = clean_html_text(body.get_text(" ", strip=True))
        description = text or None

    venue_address: str | None = None
    addr_el = soup.select_one("address")
    if addr_el is not None:
        span_el = addr_el.select_one("span")
        if span_el is not None:
            venue_address = _parse_address_from_span(span_el)

    return description, venue_address
