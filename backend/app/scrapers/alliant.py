import html
import logging
import re
import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from app.scrapers.base import BaseSource, RawEvent, clean_html_text, http_get_with_retry

logger = logging.getLogger(__name__)

_LIST_URL = "https://www.alliantenergycenter.com/upcoming-events"
_USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_DETAIL_SLEEP_SECONDS = 1.0

# Date format on the listing + detail pages: 5/17/2026, 12/3/2026, etc.
_US_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")

# Description blocks shorter than this (after HTML cleaning) are almost always
# the empty placeholder divs the venue's CMS sprinkles around the offers block.
# Real descriptions on the live site are 200+ chars.
_DESCRIPTION_MIN_LEN = 30


class AlliantEnergyCenterSource(BaseSource):
    name = "Alliant Energy Center"
    scraper_type = "html"
    supports_window_days = True

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        today = datetime.now(_CENTRAL).date()
        cutoff = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)
        headers = {"User-Agent": _USER_AGENT}

        resp = http_get_with_retry(_LIST_URL, headers=headers, timeout=30)
        soup = BeautifulSoup(resp.content, "lxml")
        items = soup.select("ul.eventWidgetSimple > li")

        raw_events: list[RawEvent] = []
        for item in items:
            ev = _parse_list_item(item)
            if ev is None:
                continue
            if ev.start_at.date() > cutoff:
                continue
            raw_events.append(ev)

        ok = fail = 0
        for ev in raw_events:
            time.sleep(_DETAIL_SLEEP_SECONDS)
            desc = _fetch_detail_description(ev.source_url, headers)
            if desc:
                ev.description = desc
                ok += 1
            else:
                fail += 1

        logger.info(
            "Alliant Energy Center: %d events, detail enrichment %d/%d succeeded",
            len(raw_events), ok, ok + fail,
        )
        return raw_events


def _parse_us_date(s: str | None) -> datetime | None:
    """Parse M/D/YYYY into a naive datetime at midnight (no tz)."""
    if not s:
        return None
    m = _US_DATE_RE.match(s)
    if not m:
        return None
    month, day, year = (int(m.group(i)) for i in (1, 2, 3))
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _to_central_midnight(d: datetime) -> datetime:
    return d.replace(tzinfo=_CENTRAL)


def _to_central_end_of_day(d: datetime) -> datetime:
    return datetime.combine(d.date(), dtime(23, 59, 59), tzinfo=_CENTRAL)


def _parse_list_item(li: Tag) -> RawEvent | None:
    """Parse one `<li>` from `ul.eventWidgetSimple` on /upcoming-events."""
    title_el = li.select_one(".eventTitle")
    if title_el is None:
        return None
    title = html.unescape(title_el.get_text(strip=True))
    if not title:
        return None

    start_el = li.select_one(".notificationStartDate")
    end_el = li.select_one(".notificationEndDate")
    if start_el is None:
        return None
    start_naive = _parse_us_date(start_el.get_text(strip=True))
    if start_naive is None:
        logger.warning("Alliant Energy Center: unparseable start date for %r", title)
        return None
    start_at = _to_central_midnight(start_naive)

    end_at: datetime | None = None
    if end_el is not None:
        end_naive = _parse_us_date(end_el.get_text(strip=True))
        if end_naive is not None:
            end_at = _to_central_end_of_day(end_naive)

    link_el = li.select_one("a.eventPlannerStandardButton[href]")
    if link_el is None:
        return None
    source_url = link_el["href"].strip()
    if not source_url:
        return None

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name="Alliant Energy Center",
        venue_address=None,
        description=None,
        categories=[],
        all_day=True,
        source_name="Alliant Energy Center",
        source_url=source_url,
    )


def _fetch_detail_description(url: str, headers: dict) -> str | None:
    try:
        resp = http_get_with_retry(url, headers=headers, timeout=15)
    except Exception as exc:
        logger.warning("Alliant Energy Center: failed to fetch detail %s: %s", url, exc)
        return None
    soup = BeautifulSoup(resp.content, "lxml")
    return _extract_description(soup)


_SCAFFOLD_SELECTOR = ".eventTitle, .eventLoc, .eventDateLabel, .websiteField, script"


def _extract_description(soup: BeautifulSoup) -> str | None:
    """Pick the description out of the detail-page nadev blocks.

    The page wraps everything in `div.nadevViewEventDetails.nadevViewEventDetailsPadding`
    blocks — most are empty placeholders, one (always near the end) carries the
    description as one or more `<p>` children. Skip blocks that:

    - sit inside `[itemprop=offers]` (price scaffolding), or
    - carry title/date/website/script scaffolding (the first block is the title
      card with eventTitle/eventLoc/eventDateLabel + a websiteField script that
      together comfortably exceed any length threshold).
    """
    for block in soup.select("div.nadevViewEventDetails.nadevViewEventDetailsPadding"):
        if block.find_parent(attrs={"itemprop": "offers"}) is not None:
            continue
        if block.select_one(_SCAFFOLD_SELECTOR) is not None:
            continue
        text = clean_html_text(block.decode_contents())
        if len(text) >= _DESCRIPTION_MIN_LEN:
            return text
    return None
