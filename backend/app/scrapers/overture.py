"""Overture Center for the Arts scraper.

Overture is Madison's largest performing-arts venue (seven sub-rooms,
~200 performances/year) and hosts ten resident companies — Madison
Symphony, Madison Opera, Madison Ballet, Forward Theater, Children's
Theater of Madison, Wisconsin Chamber Orchestra, Kanopy Dance, etc. The
public ``/tickets-events/upcoming-events/`` page server-renders all
upcoming events for both Overture-presented and resident-company shows
on a single ~15-month chronological list (no pagination, no XHR).

Two quirks that make this scraper unusual:

1. **TLS-fingerprint WAF.** ``overture.org`` is fronted by Imperva /
   Incapsula, which 403s any request whose JA3 TLS fingerprint isn't a
   recognized browser. ``httpx`` and ``requests`` (and plain ``curl``)
   are blocked regardless of headers. We use ``curl_cffi`` with
   ``impersonate="chrome"`` instead, which performs the TLS handshake
   with Chrome's exact cipher suites / extensions.

2. **Tessitura shared-session handshake.** The first GET returns a tiny
   redirect stub containing a hidden form (``EncryptedPayload.Value`` +
   ``ReturnUrl``) that JavaScript auto-submits to ``/login/receive``.
   Until that POST happens the real page is never delivered. We
   replicate the POST in code and the second response is the real
   ~240KB events page.

Year inference: cards show "May 10" / "May 10 - May 17" with no year.
Events are listed chronologically, so we walk in order and increment
year whenever the (month, start_day) regresses vs. the previous card.

Venue handling: the card's room (e.g. "Capitol Theater", "Promenade
Hall") is left as ``venue_name`` so it dedups cleanly with the
Ticketmaster scraper's per-room values; the seven Overture-internal
rooms are added to ``canonical_venues`` so geocoding still resolves to
the building's coordinates.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, time as dtime
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

    def fetch(self) -> list[RawEvent]:
        html_text = _fetch_events_html()
        soup = BeautifulSoup(html_text, "lxml")
        cards = soup.select("li.upcoming-event-card")
        if not cards:
            logger.warning("Overture: 0 cards parsed from %d-byte response", len(html_text))
            return []
        return _parse_cards(cards, today=datetime.now(_CENTRAL).date())


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


def _fetch_events_html() -> str:
    """Two-step fetch: GET the redirect stub, then POST the encrypted
    session payload. Returns the real events-page HTML.

    Walks `_IMPERSONATE_PROFILES` until one returns something that
    isn't an Imperva challenge page; raises only after all profiles
    fail (the caller logs and the scrape stats reflect 0 events)."""
    last_html: str = ""
    for profile in _IMPERSONATE_PROFILES:
        session = curl_requests.Session(impersonate=profile)
        try:
            stub = session.get(_LISTING_URL, timeout=30)
            stub.raise_for_status()
        except Exception as e:
            logger.warning("Overture: stub GET failed with profile %s: %s", profile, e)
            continue
        if _IMPERVA_BLOCK_MARKER in stub.text:
            last_html = stub.text
            logger.info("Overture: Imperva challenge with profile %s; trying next", profile)
            continue
        payload, return_url = _extract_session_form(stub.text)
        if payload is None or return_url is None:
            # The stub response IS the events page (e.g. when a
            # warm session cookie is in play). Return it.
            return stub.text
        try:
            response = session.post(
                _SESSION_RECEIVE_URL,
                data={"EncryptedPayload.Value": payload, "ReturnUrl": return_url},
                timeout=30,
            )
            response.raise_for_status()
        except Exception as e:
            logger.warning(
                "Overture: session POST failed with profile %s: %s", profile, e,
            )
            continue
        return response.text
    # All profiles fell back to the Imperva challenge — return whatever
    # we last got so the caller can log the byte count and bail with
    # zero cards.
    return last_html


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
