"""Overture Center for the Arts scraper.

Overture is Madison's largest performing-arts venue (seven sub-rooms,
~200 performances/year) and hosts ten resident companies — Madison
Symphony, Madison Opera, Madison Ballet, Forward Theater, Children's
Theater of Madison, Wisconsin Chamber Orchestra, Kanopy Dance, etc. The
public ``/tickets-events/upcoming-events/`` page server-renders all
upcoming events for both Overture-presented and resident-company shows
on a single ~15-month chronological list (no pagination, no XHR).

Three mechanics that make this scraper unusual:

1. **TLS-fingerprint WAF.** ``overture.org`` is fronted by Imperva /
   Incapsula, which 403s any request whose JA3 TLS fingerprint isn't a
   recognized browser. ``httpx`` and ``requests`` (and plain ``curl``)
   are blocked regardless of headers. We use ``curl_cffi`` with
   ``impersonate="safari"`` (chrome variants currently fail the
   challenge); the scraper walks a profile list rather than crashing
   if Imperva tightens.

2. **Tessitura shared-session handshake.** The first GET returns a tiny
   redirect stub containing a hidden form (``EncryptedPayload.Value`` +
   ``ReturnUrl``) that JavaScript auto-submits to ``/login/receive``.
   Until that POST happens the real page is never delivered. We
   replicate the POST in code and the second response is the real page.

3. **Detail-page enrichment for multi-day runs.** The listing card
   shows "Multiple Showtimes" for any multi-day run (one card covers
   e.g. an 8-performance Broadway week). The actual per-performance
   schedule lives on the event's detail page in a ``ul.pdp-tickets-list``
   block with dated/timed ``li.pdp-tickets-item`` entries. For each
   list-card event whose time we don't know yet (multi-day or
   "Multiple Showtimes"), we fetch the detail page and emit one
   ``RawEvent`` per unique date. When a date has multiple performances
   (e.g. Sat matinee + evening), we keep the *latest* time — the
   typical evening headline show — and rely on Ticketmaster to surface
   matinees as separate events.

Year inference (listing only): cards show "May 10" / "May 10 - May 17"
with no year. Events are listed chronologically, so we walk in order
and increment year whenever the (month, start_day) regresses vs. the
previous card. Detail-page schedules already include the year so this
inference is skipped for enriched events.

Venue handling: the card's room (e.g. "Capitol Theater", "Promenade
Hall") is left as ``venue_name`` so it dedups cleanly with the
Ticketmaster scraper's per-room values; the seven Overture-internal
rooms are added to ``canonical_venues`` so geocoding still resolves to
the building's coordinates.
"""

import logging
import re
from dataclasses import dataclass, replace
from datetime import date as dtdate, datetime, time as dtime
from html import unescape as html_unescape
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from curl_cffi import requests as curl_requests

from app.scrapers.base import BaseSource, RawEvent, clean_html_text

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.overture.org"
_LISTING_URL = f"{_BASE_URL}/tickets-events/upcoming-events/"
_SESSION_RECEIVE_URL = f"{_BASE_URL}/login/receive"
_DEFAULT_VENUE_NAME = "Overture Center for the Arts"
_CENTRAL = ZoneInfo("America/Chicago")
_SOURCE_NAME = "Overture Center for the Arts"

_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

_SPAN_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2})$")
_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*(am|pm)\s*$", re.IGNORECASE)

# Sub-rooms physically inside Overture Center at 201 State St. Listed in
# lowercase to match the canonical_venues lookup key style.
_INTERNAL_ROOMS: frozenset[str] = frozenset({
    "overture hall",
    "capitol theater",
    "capitol theater stage",
    "promenade hall",
    "promenade lobby",
    "rotunda stage",
    "the playhouse",
    "james watrous gallery",
})

# Conservative tag mapping. Anything not present here is dropped so the
# Step-4 LLM tagger handles it from the description. We avoid mapping
# tags that are administrative ("2025/26 Season"), audience-targeting
# ("Free Events"), company-name ("Madison Ballet"), or genuinely
# ambiguous ("Variety", "Cabaret", "Fringe Festival").
_CATEGORY_MAP: dict[str, str] = {
    "music": "Music",
    "classical music": "Music",
    "jazz": "Music",
    "comedy": "Open Mic & Comedy",
    "theater": "Theater & Stage",
    "musical theater": "Theater & Stage",
    "broadway": "Theater & Stage",
    "dance": "Theater & Stage",
    "educational/talks": "Talks & Learning",
    "family friendly": "Family & Kids",
}

# Hidden-input regexes for the Tessitura shared-session form.
_PAYLOAD_RE = re.compile(
    r'name="EncryptedPayload\.Value"\s+type="hidden"\s+value="([^"]+)"'
)
_RETURN_URL_RE = re.compile(
    r'name="ReturnUrl"\s+type="hidden"\s+value="([^"]+)"'
)


@dataclass
class _ParsedDate:
    """Month + day pair extracted from a card. Year is filled in later
    by the chronological-walk pass that owns inter-card context."""
    month: int
    day: int


class OvertureSource(BaseSource):
    name = _SOURCE_NAME
    scraper_type = "html"
    supports_window_days = False

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        session, listing_html = _fetch_listing()
        if not listing_html:
            return []
        soup = BeautifulSoup(listing_html, "lxml")
        cards = soup.select("li.upcoming-event-card")
        if not cards:
            logger.warning(
                "Overture: 0 cards parsed from %d-byte listing", len(listing_html),
            )
            return []
        base_events = _parse_cards(cards, today=datetime.now(_CENTRAL).date())
        return _enrich_with_schedules(base_events, session)


# ---------------------------------------------------------------------------
# Network: Tessitura session handshake via curl_cffi
# ---------------------------------------------------------------------------

# Imperva (the WAF in front of overture.org) serves a JS-challenge
# "Pardon Our Interruption" page when it doesn't recognize the client's
# fingerprint. Empirically the safari/safari17_2_ios curl_cffi profiles
# slip past on the first request while chrome/firefox/edge do not. We
# try them in order, falling back if one ever stops working.
_IMPERSONATE_PROFILES: tuple[str, ...] = ("safari", "safari17_2_ios", "chrome")
_IMPERVA_BLOCK_MARKER = "Pardon Our Interruption"


def _fetch_listing() -> tuple[Optional[object], str]:
    """Open a curl_cffi session that gets past Imperva on the listing
    URL and do the Tessitura handshake. Returns `(session, html)` on
    success or `(None, "")` if every impersonate profile is challenged.

    The session is kept alive so subsequent detail-page fetches reuse
    its warmed cookies/TLS instead of re-running the handshake."""
    for profile in _IMPERSONATE_PROFILES:
        session = curl_requests.Session(impersonate=profile)
        html_text = _fetch_url(session, _LISTING_URL)
        if html_text:
            return session, html_text
        logger.info(
            "Overture: profile %s blocked or empty on listing; trying next", profile,
        )
    logger.warning("Overture: all impersonate profiles blocked on listing")
    return None, ""


def _fetch_detail_html(session, url: str) -> str:
    """Fetch a detail-page URL through the already-warm session.
    Returns "" if Imperva blocks or the request fails; the caller
    falls back to the listing-card data."""
    return _fetch_url(session, url)


def _fetch_url(session, url: str) -> str:
    """GET `url` through `session`, running the Tessitura form-POST
    handshake if the response is the redirect stub. Returns "" on
    Imperva block or network/HTTP error."""
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Overture: GET %s failed: %s", url, e)
        return ""
    if _IMPERVA_BLOCK_MARKER in resp.text:
        return ""
    payload, return_url = _extract_session_form(resp.text)
    if payload is None or return_url is None:
        return resp.text
    try:
        bridged = session.post(
            _SESSION_RECEIVE_URL,
            data={"EncryptedPayload.Value": payload, "ReturnUrl": return_url},
            timeout=30,
        )
        bridged.raise_for_status()
    except Exception as e:
        logger.warning("Overture: session POST during fetch of %s failed: %s", url, e)
        return ""
    return bridged.text


def _extract_session_form(html_text: str) -> tuple[Optional[str], Optional[str]]:
    m_payload = _PAYLOAD_RE.search(html_text)
    m_return = _RETURN_URL_RE.search(html_text)
    if not m_payload or not m_return:
        return None, None
    return html_unescape(m_payload.group(1)), html_unescape(m_return.group(1))


# ---------------------------------------------------------------------------
# Card parsing
# ---------------------------------------------------------------------------

def _parse_cards(cards, today) -> list[RawEvent]:
    """Walk cards in document order, inferring year by chronological
    progression. Returns RawEvents in the same order."""
    events: list[RawEvent] = []
    current_year = today.year
    last_month_day: tuple[int, int] | None = None

    for card in cards:
        date_pair = _extract_date_pair(card)
        if date_pair is None:
            continue
        start_md, end_md = date_pair
        if last_month_day is not None and (start_md.month, start_md.day) < last_month_day:
            current_year += 1
        last_month_day = (start_md.month, start_md.day)

        try:
            start_date = datetime(current_year, start_md.month, start_md.day)
        except ValueError:
            logger.warning(
                "Overture: invalid date %d-%d-%d", current_year, start_md.month, start_md.day,
            )
            continue
        end_date: datetime | None = None
        if end_md is not None:
            # Same year as the start unless the range crosses December
            # ("December 30 - January 4") — detect by end month being
            # earlier than start month.
            end_year = current_year + 1 if end_md.month < start_md.month else current_year
            try:
                end_date = datetime(end_year, end_md.month, end_md.day)
            except ValueError:
                end_date = None

        ev = _parse_card(card, start_date, end_date)
        if ev is not None:
            events.append(ev)
    return events


def _extract_date_pair(card: Tag) -> tuple[_ParsedDate, _ParsedDate | None] | None:
    """Read the `.upcoming-event-date` block and return
    (start_md, end_md) or (start_md, None) for single-day events."""
    date_block = card.select_one(".upcoming-event-date")
    if date_block is None:
        return None
    spans = [s.get_text(strip=True) for s in date_block.select("span.h3-style")]
    spans = [s for s in spans if s and s != "-"]
    if not spans:
        return None
    start = _parse_span(spans[0])
    if start is None:
        return None
    if len(spans) >= 2:
        end = _parse_span(spans[1])
        return start, end
    return start, None


def _parse_span(text: str) -> _ParsedDate | None:
    m = _SPAN_DATE_RE.match(text.strip())
    if not m:
        return None
    month_name = m.group(1).lower()
    if month_name not in _MONTHS:
        return None
    try:
        day = int(m.group(2))
    except ValueError:
        return None
    return _ParsedDate(month=_MONTHS[month_name], day=day)


def _parse_time(text: str | None) -> dtime | None:
    if not text:
        return None
    m = _TIME_RE.match(text)
    if not m:
        return None
    try:
        return datetime.strptime(
            f"{m.group(1)}:{m.group(2)} {m.group(3).upper()}", "%I:%M %p"
        ).time()
    except ValueError:
        return None


def _normalize_venue(room_name: str | None) -> str:
    """Internal Overture rooms collapse to the canonical building name
    so the venue card and source-priority merge are consistent. External
    venues (Bethel Lutheran Church, MYArts, etc.) keep their literal
    name and rely on Nominatim for geocoding."""
    if not room_name or not room_name.strip():
        return _DEFAULT_VENUE_NAME
    cleaned = room_name.strip()
    if cleaned.lower() in _INTERNAL_ROOMS:
        return _DEFAULT_VENUE_NAME
    return cleaned


def _map_categories(raw_text: str | None) -> list[str]:
    """Conservative tag mapping. Comma-separated source list → 0+
    canonical categories; unmapped values are dropped."""
    if not raw_text:
        return []
    seen: list[str] = []
    for raw in raw_text.split(","):
        key = raw.strip().lower()
        if not key:
            continue
        mapped = _CATEGORY_MAP.get(key)
        if mapped and mapped not in seen:
            seen.append(mapped)
    return seen


def _parse_card(card: Tag, start_date: datetime, end_date: datetime | None) -> RawEvent | None:
    title_el = card.select_one("a.upcoming-event-details-title")
    if title_el is None:
        return None
    title = title_el.get_text(strip=True)
    href = title_el.get("href") or ""
    if not title or not href:
        return None
    source_url = urljoin(_BASE_URL, href)

    price_el = card.select_one(".upcoming-event-price")
    price_text = price_el.get_text(strip=True) if price_el is not None else ""
    show_time = _parse_time(price_text)

    if show_time is not None:
        start_at = start_date.replace(
            hour=show_time.hour, minute=show_time.minute, tzinfo=_CENTRAL,
        )
        all_day = False
    else:
        start_at = start_date.replace(tzinfo=_CENTRAL)
        all_day = True

    end_at: datetime | None = None
    if end_date is not None:
        # Multi-day events: end_at at last-day end-of-day (23:59) so the
        # range query catches every date inside the run regardless of
        # show-time parity.
        end_at = end_date.replace(
            hour=23, minute=59, second=0, tzinfo=_CENTRAL,
        )

    venue_el = card.select_one(".upcoming-event-half .small.bold")
    venue_name = _normalize_venue(venue_el.get_text(strip=True) if venue_el else None)

    desc_el = card.select_one(".upcoming-event-details-description")
    description = clean_html_text(str(desc_el)) if desc_el is not None else None
    description = description or None

    cat_el = card.select_one(".upcoming-event-details-category")
    categories = _map_categories(cat_el.get_text(strip=True) if cat_el else None)

    img_el = card.select_one(".upcoming-event-image img")
    image_url: str | None = None
    if img_el is not None:
        src = img_el.get("src")
        if src:
            image_url = urljoin(_BASE_URL, src)

    # Overture's _internal_ rooms always live at the canonical building
    # address, so we leave venue_address null and rely on the
    # canonical_venues registry to fill in the address + coordinates
    # during geocoding. External venues likewise have no address on the
    # card; Nominatim handles them.
    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=None,
        description=description,
        image_url=image_url,
        categories=categories,
        all_day=all_day,
        source_name=_SOURCE_NAME,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Detail-page enrichment: read per-performance schedule, expand events
# ---------------------------------------------------------------------------

# Detail-page date format: "Tue, May 12, 2026". Year is explicit so
# the chronological-walk inference used on the listing isn't needed.
_DETAIL_DATE_FMT = "%a, %B %d, %Y"


def _enrich_with_schedules(
    base_events: list[RawEvent], session,
) -> list[RawEvent]:
    """For each base event whose list-card time was missing or set to
    "Multiple Showtimes" (i.e. all_day=True or end_at populated), fetch
    the detail page and replace the base event with per-performance
    entries. Single-day events with a real time pass through unchanged
    — the list card already had the only time we have.

    On detail-page failure or empty schedule the base event is kept
    as-is so we never lose an event due to enrichment hiccups."""
    out: list[RawEvent] = []
    for base in base_events:
        needs_enrichment = base.all_day or base.end_at is not None
        if not needs_enrichment:
            out.append(base)
            continue
        detail_html = _fetch_detail_html(session, base.source_url)
        if not detail_html:
            logger.info(
                "Overture: detail fetch empty for %r; keeping list-card data",
                base.title,
            )
            out.append(base)
            continue
        schedule = _parse_schedule(detail_html)
        if not schedule:
            out.append(base)
            continue
        out.extend(_expand_with_schedule(base, schedule))
    return out


def _parse_schedule(html_text: str) -> list[tuple[dtdate, dtime | None]]:
    """Extract per-performance `(date, time-or-none)` entries from a
    detail page's `ul.pdp-tickets-list` block. Duplicates (same date
    + same time, occasionally emitted by Overture for events with
    multiple accessibility variants) are removed. Sorted chronologically."""
    soup = BeautifulSoup(html_text, "lxml")
    seen: set[tuple[dtdate, dtime | None]] = set()
    results: list[tuple[dtdate, dtime | None]] = []
    for item in soup.select("li.pdp-tickets-item"):
        date_el = item.select_one(".tickets-date")
        time_el = item.select_one(".tickets-time")
        if date_el is None:
            continue
        try:
            d = datetime.strptime(
                date_el.get_text(strip=True), _DETAIL_DATE_FMT,
            ).date()
        except ValueError:
            continue
        t = _parse_time(time_el.get_text(strip=True)) if time_el else None
        key = (d, t)
        if key in seen:
            continue
        seen.add(key)
        results.append(key)
    results.sort(key=lambda x: (x[0], x[1] or dtime.min))
    return results


def _expand_with_schedule(
    base: RawEvent, schedule: list[tuple[dtdate, dtime | None]],
) -> list[RawEvent]:
    """Replace `base` with one RawEvent per unique date in `schedule`.
    For dates with multiple performances (e.g. Sat 2 PM matinee +
    Sat 7:30 PM evening) we keep the latest time — the typical
    evening headline show — and rely on Ticketmaster to emit the
    matinee as a separate event with its own time.

    `schedule` is already sorted ascending by (date, time), so writing
    each (date, time) into a dict in order yields the latest time per
    date by last-write-wins."""
    if not schedule:
        return [base]
    latest_by_date: dict[dtdate, dtime | None] = {}
    for d, t in schedule:
        latest_by_date[d] = t

    out: list[RawEvent] = []
    for d in sorted(latest_by_date.keys()):
        t = latest_by_date[d]
        if t is None:
            start = datetime(d.year, d.month, d.day, tzinfo=_CENTRAL)
            all_day = True
        else:
            start = datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=_CENTRAL)
            all_day = False
        out.append(replace(base, start_at=start, end_at=None, all_day=all_day))
    return out
