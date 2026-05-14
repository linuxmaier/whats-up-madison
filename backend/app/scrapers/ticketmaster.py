import logging
import re
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.scrapers.base import BaseSource, RawEvent, http_get_with_retry

logger = logging.getLogger(__name__)

_API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"
_CENTRAL = ZoneInfo("America/Chicago")
_WINDOW_DAYS = 30
_PAGE_SIZE = 200  # Discovery API max
_PAGE_SLEEP_SECONDS = 0.25  # well under the 5 req/s rate limit
_DROP_STATUSES: frozenset[str] = frozenset({"cancelled", "postponed"})

# Minimum residual length after stripping venue boilerplate to treat the field
# as carrying event-specific signal. TM populates info/pleaseNote with templated
# venue-policy copy (cashless, bag policy, ADA seating contact, door times) that
# repeats across every show at a venue; below this threshold the residue is
# noise (e.g. just punctuation or fragments), so we surface no description and
# let downstream higher-priority sources fill it via the ingest merge.
_DESCRIPTION_MIN_SIGNAL_LENGTH = 40

# Patterns covering the templated venue-policy phrases that TM ships in
# info/pleaseNote. Each matches a single sentence/clause so the residue test
# is "how much *non-boilerplate* text remains" rather than "is the whole
# field one of N known strings". The set was derived from a survey of every
# unique sentence across info+pleaseNote on the live Madison TM feed; new
# variants should be added here as they show up in the audit.
_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        # Door / show times prefix — variants seen: "Doors at 7:00 pm",
        # "Doors at 7:00 pm | Show at 8:00 pm", "Doors open at 6:00 pm",
        # "Doors at 8: 00 pm | Show at 9:00 pm" (TM occasionally injects spaces).
        r"Doors?\s+(?:open(?:s|ed)?\s+)?at\s+\d{1,2}\s*:?\s*\d{2}\s?[ap]m\s*"
        r"(?:\|\s*Shows?\s+at\s+\d{1,2}\s*:?\s*\d{2}\s?[ap]m\s*)?",
        # Cashless venue policy
        r"CASHLESS\s+VENUE[^.]*(?:\.|$)",
        r"No\s+cash\s+accepted\.",
        # Bag policy
        r"Bags?\s*\(max\s+size[^)]+\)[^.]*(?:\.|$)",
        r"Exceptions\s+will\s+be\s+made\s+for\s+necessary\s+medical[^.]*(?:\.|$)",
        r"We\s+encourage\s+you\s+to\s+pack\s+light[^.]*(?:\.|$)",
        # General-admission seating — Sylvee/Majestic/Orpheum variants:
        #  - "All General Admission Tickets are good for the standing GA Floor..."
        #  - "All General Admission tickets are seated."
        #  - "All tickets are standing and seated General Admission and are
        #    available on a first come first serve basis."
        r"All\s+General\s+Admission\s+[Tt]ickets?\s+are\s+(?:good\s+for|seated)[^.]*(?:\.|$)",
        r"All\s+tickets\s+are\s+(?:standing|seated)[^.]*"
        r"(?:General\s+Admission|first\s+come\s+first\s+serve)[^.]*(?:\.|$)",
        r"They\s+are\s+available\s+on\s+a\s+first\s+come\s+first\s+serve\s+basis\.",
        # Orpheum tiered-GA-pricing boilerplate
        r"A\s+tiered\s+system\s+is\s+in\s+place\s+for\s+General\s+Admission[^.]*(?:\.|$)",
        r"This\s+allows\s+us\s+to\s+reward\s+the\s+most\s+loyal\s+fans[^.]*(?:\.|$)",
        r"Prices\s+will\s+increase\s+as\s+each\s+tier\s+sells\s+out\.",
        r"Every\s+General\s+Admission\s+ticket[^.]*(?:\.|$)",
        # Majestic Opera Boxes accessibility note
        r"The\s+Opera\s+Boxes\s+are\s+only\s+accessible\s+by\s+stairs\.",
        # ADA / accessible seating — "Accessible Seating: Accessible seating
        # is available..." and the shorter "Accessible Seating: Available..."
        r"Accessible\s+Seating:\s*(?:Accessible\s+seating\s+is\s+available|Available)[^.]*(?:\.|$)",
        r"For\s+additional\s+information\s+call\s+[\d\s\-]+\.",
        # Theatre/Theater accessibility note (both spellings appear in the feed).
        r"There\s+are\s+no\s+elevators\s+in\s+the\s+[Tt]heat(?:re|er)\.",
        # Box-office / re-purchase variants — covers "Advance tickets can be
        # purchased online or at The Sylvee box office.", "Tickets can be
        # purchased online up to the event start time.", and "Once the doors
        # have opened, if tickets are still available, they can be purchased
        # at the <venue>." / "Once the event has started, if tickets are still
        # available, they can be purchased at the Sylvee box office."
        r"(?:Advance\s+)?Tickets\s+can\s+be\s+purchased[^.]*(?:\.|$)",
        r"Once\s+the\s+(?:doors?\s+(?:have\s+)?opened|event\s+has\s+started)[^.]*(?:\.|$)",
        # Age restriction noise (also appears mid-sentence)
        r"Ages?\s+\d+\+",
        # Cancellation placeholder TM sometimes leaves on cancelled events
        r"Unfortunately,\s+the\s+Event\s+Organizer\s+has\s+had\s+to\s+cancel\s+your\s+event\.",
    )
)


def _scrub_boilerplate(text: str) -> str:
    """Strip well-known TM/venue boilerplate phrases and return the residue.

    Only the gating decision in :func:`_choose_description` consults the
    residue; the value stored on ``RawEvent.description`` is the *original*
    raw text, so mixed descriptions (door-times prefix + real event copy)
    survive verbatim. Whitespace and stray punctuation left behind after a
    strip are normalised so a residue of ", . :" doesn't beat the threshold.
    """
    for pat in _BOILERPLATE_PATTERNS:
        text = pat.sub(" ", text)
    # Collapse runs of orphan punctuation that strips leave behind (e.g.
    # ". . . ." between consecutive scrubbed sentences) so they don't inflate
    # the residue length above the signal threshold.
    text = re.sub(r"(?:\s*[.,;:|\-]+\s*){2,}", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^[\s\.,:;|\-]+|[\s\.,:;|\-]+$", "", text)
    return text


def _choose_description(info: str | None, please_note: str | None) -> str | None:
    """Pick the best event description from TM ``info``/``pleaseNote``.

    Returns the raw ``info`` (or ``pleaseNote`` fallback) when it carries
    enough event-specific signal after boilerplate is conceptually removed;
    otherwise returns ``None`` so a higher-priority source (Isthmus, Visit
    Madison) can fill the field via ingest's source-priority merge, or so
    the frontend simply renders no description.
    """
    for candidate in (info, please_note):
        raw = (candidate or "").strip()
        if not raw:
            continue
        if len(_scrub_boilerplate(raw)) >= _DESCRIPTION_MIN_SIGNAL_LENGTH:
            return raw
    return None

# US state code → full lowercase name for canonical URL slug construction.
_STATE_NAMES: dict[str, str] = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
    "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
    "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
    "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma",
    "OR": "oregon", "PA": "pennsylvania", "RI": "rhode-island", "SC": "south-carolina",
    "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
    "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west-virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district-of-columbia",
}

# Conservative segment/genre → our taxonomy mapping. Lookup order is
# (segment, genre) first, then (segment, None). Anything unmapped is dropped
# so the LLM tagging pass can enrich from description.
_CATEGORY_MAP: dict[tuple[str, str | None], str] = {
    ("Music", None):                            "Music",
    ("Arts & Theatre", "Comedy"):               "Open Mic & Comedy",
    ("Arts & Theatre", "Theatre"):              "Theater & Stage",
    ("Arts & Theatre", "Children's Theatre"):   "Theater & Stage",
    ("Arts & Theatre", "Performance Art"):      "Theater & Stage",
    ("Arts & Theatre", "Dance"):                "Theater & Stage",
    ("Sports", None):                           "Sports & Recreation",
    ("Family", None):                           "Family & Kids",
}


class TicketmasterSource(BaseSource):
    name = "Ticketmaster"
    scraper_type = "api"

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        if not settings.ticketmaster_api_key:
            raise ValueError("TICKETMASTER_API_KEY is not set")

        today = datetime.now(_CENTRAL).date()
        end = today + timedelta(days=window_days if window_days is not None else _WINDOW_DAYS)
        start_iso = _utc_iso_z(datetime.combine(today, dtime.min, tzinfo=_CENTRAL))
        end_iso = _utc_iso_z(datetime.combine(end, dtime.max, tzinfo=_CENTRAL))

        events: list[RawEvent] = []
        page = 0
        while True:
            params = {
                "apikey": settings.ticketmaster_api_key,
                "city": "Madison",
                "stateCode": "WI",
                "countryCode": "US",
                "startDateTime": start_iso,
                "endDateTime": end_iso,
                "size": _PAGE_SIZE,
                "page": page,
                "sort": "date,asc",
            }
            resp = http_get_with_retry(
                _API_URL,
                params=params,
                headers={"User-Agent": _USER_AGENT},
                timeout=30,
            )
            data = resp.json()
            docs = (data.get("_embedded") or {}).get("events") or []
            for doc in docs:
                event = _parse_event(doc)
                if event is not None:
                    events.append(event)
            total_pages = (data.get("page") or {}).get("totalPages") or 1
            if not docs or page + 1 >= total_pages:
                break
            page += 1
            time.sleep(_PAGE_SLEEP_SECONDS)

        return events


def _utc_iso_z(dt: datetime) -> str:
    """Convert an aware datetime to ``YYYY-MM-DDTHH:MM:SSZ`` (Discovery API format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_local_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_local_time(raw: str | None) -> dtime | None:
    if not raw:
        return None
    try:
        return dtime.fromisoformat(raw)
    except ValueError:
        return None


def _build_address(venue: dict) -> str | None:
    line1 = ((venue.get("address") or {}).get("line1") or "").strip()
    city = ((venue.get("city") or {}).get("name") or "").strip()
    state = ((venue.get("state") or {}).get("stateCode") or "").strip()
    zipc = (venue.get("postalCode") or "").strip()
    parts: list[str] = []
    if line1:
        parts.append(line1)
    if city:
        parts.append(city)
    state_zip = " ".join(p for p in (state, zipc) if p).strip()
    if state_zip:
        parts.append(state_zip)
    return ", ".join(parts) or None


def _select_image(images: list[dict]) -> str | None:
    """Pick the largest 16:9 image; fall back to the first usable URL."""
    best: dict | None = None
    for img in images or []:
        if not isinstance(img, dict) or not img.get("url"):
            continue
        if img.get("ratio") == "16_9":
            if best is None or (img.get("width") or 0) > (best.get("width") or 0):
                best = img
    if best is not None:
        return best.get("url")
    for img in images or []:
        if isinstance(img, dict) and img.get("url"):
            return img["url"]
    return None


def _map_categories(classifications: list[dict]) -> list[str]:
    if not classifications:
        return []
    primary = next(
        (c for c in classifications if isinstance(c, dict) and c.get("primary")),
        None,
    )
    if primary is None:
        return []
    seg = ((primary.get("segment") or {}).get("name") or "").strip() or None
    gen = ((primary.get("genre") or {}).get("name") or "").strip() or None
    if seg is None:
        return []
    mapped = _CATEGORY_MAP.get((seg, gen)) or _CATEGORY_MAP.get((seg, None))
    return [mapped] if mapped else []


def _event_slug(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", "-", s.strip())


def _build_canonical_url(title: str, event_date: date, venue: dict, event_id: str) -> str | None:
    """Construct a Ticketmaster canonical event URL from event metadata.

    The Discovery API returns short /event/<id> URLs that fail for some users
    due to Imperva bot-detection. The full slug URL
    (/name-city-state-MM-DD-YYYY/event/<id>) is what TM shows in browser
    address bars and is more reliably resolvable."""
    if not event_id:
        return None
    city = ((venue.get("city") or {}).get("name") or "").strip()
    state_code = ((venue.get("state") or {}).get("stateCode") or "").strip()
    if not city or not state_code:
        return None
    state_name = _STATE_NAMES.get(state_code, state_code.lower())
    slug = (
        f"{_event_slug(title)}-{_event_slug(city)}-{state_name}"
        f"-{event_date.strftime('%m-%d-%Y')}"
    )
    return f"https://www.ticketmaster.com/{slug}/event/{event_id}"


def _parse_event(doc: dict) -> RawEvent | None:
    dates = doc.get("dates") or {}
    status = ((dates.get("status") or {}).get("code") or "").strip().lower()
    if status in _DROP_STATUSES:
        return None

    title = (doc.get("name") or "").strip()
    if not title:
        return None

    venues = (doc.get("_embedded") or {}).get("venues") or []
    venue = venues[0] if venues else None
    if not isinstance(venue, dict):
        return None

    start_block = dates.get("start") or {}
    event_date = _parse_local_date(start_block.get("localDate"))
    if event_date is None:
        return None

    tz_name = dates.get("timezone") or "America/Chicago"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = _CENTRAL

    local_time = _parse_local_time(start_block.get("localTime"))
    time_tba = bool(start_block.get("timeTBA")) or bool(start_block.get("noSpecificTime"))
    if local_time is None or time_tba:
        start_at = datetime.combine(event_date, dtime.min, tzinfo=tz)
        all_day = True
    else:
        start_at = datetime.combine(event_date, local_time, tzinfo=tz)
        all_day = False

    end_at: datetime | None = None
    end_block = dates.get("end") or {}
    end_date = _parse_local_date(end_block.get("localDate"))
    if dates.get("spanMultipleDays") and end_date is not None:
        end_time = _parse_local_time(end_block.get("localTime")) or dtime.max
        end_at = datetime.combine(end_date, end_time, tzinfo=tz)

    description = _choose_description(doc.get("info"), doc.get("pleaseNote"))

    venue_name = (venue.get("name") or "").strip() or None
    venue_address = _build_address(venue)
    image_url = _select_image(doc.get("images") or [])
    categories = _map_categories(doc.get("classifications") or [])

    event_id = (doc.get("id") or "").strip()
    source_url = (
        _build_canonical_url(title, event_date, venue, event_id)
        or (doc.get("url") or "").strip()
    )
    if not source_url:
        return None

    return RawEvent(
        title=title,
        start_at=start_at,
        end_at=end_at,
        venue_name=venue_name,
        venue_address=venue_address,
        description=description,
        image_url=image_url,
        categories=categories,
        all_day=all_day,
        source_name="Ticketmaster",
        source_url=source_url,
    )
