import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import canonical_venues
from app.models import Event, VenueGeocode

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"

# Bounding box used to bias lookups. Order matches Nominatim's viewbox param:
# left,top,right,bottom (lng,lat,lng,lat).
#
# Widened in #236 from a Madison-only box to cover the surrounding towns that
# sources actually list events in. The old box excluded Spring Green (lng
# -90.04), Belleville, Evansville, Lodi, Brooklyn and Lake Mills, so every
# venue in those towns failed with bounded=1 no matter how the query was
# phrased. Verified against live Nominatim: with this box, bounded=1 resolves
# the same results as unbounded, so the bound is kept — it stops queries like
# "Main Street Music, Brooklyn" from matching Brooklyn, NY.
MADISON_VIEWBOX = "-90.2,43.5,-88.7,42.5"

MIN_INTERVAL_SECONDS = 1.05  # Nominatim ToS: max 1 request/second
REQUEST_TIMEOUT_SECONDS = 10.0

# How long an `error` cache row stands before we re-attempt it.
#
# _call_nominatim reports "error" for any exception — rate limiting, 5xx and
# timeouts included — so an error row is often "we couldn't ask right now"
# rather than "this place doesn't exist". Treating those as permanent is what
# left production at 31.6% of events without coordinates after #236 changed the
# key format: hundreds of fresh keys had to resolve back-to-back at 1 req/sec,
# a large share failed transiently, and nothing ever retried them. A later
# `?force=true` pass cleared 173 such rows and recovered 166 events on the spot.
#
# A TTL rather than not caching errors at all: during a genuine Nominatim
# outage, not caching would make every event re-hit the network on every pass.
# Six hours means a rate-limited key recovers by the next daily scrape without
# hammering the service in between (#253).
_ERROR_RETRY_AFTER = timedelta(hours=6)

# "<name> | <city>, wi" marks a venue-name-only lookup so _call_nominatim can
# rebuild the free-text query with the right town. The city half used to be
# hardcoded to Madison, which produced nonsense queries like
# "the mill, paoli, madison, wi" for every Isthmus venue outside the city and
# was the single largest cause of missing map pins (#236).
_NAME_SEPARATOR = " | "
_MADISON_SUFFIX = ", madison, wi"
_DEFAULT_CITY = "madison"
_HAS_STATE_RE = re.compile(r"\b(wi|wisconsin)\b")

_throttle_lock = threading.Lock()
_last_call_at: float = 0.0


def normalize_lookup(venue_name: str | None, venue_address: str | None) -> str | None:
    """Build a stable cache key from whatever venue info we have."""
    if venue_address and venue_address.strip():
        addr = re.sub(r"\s+", " ", venue_address.strip().lower())
        # Only backfill the city/state when the address names no locality at
        # all. Appending unconditionally produced keys like
        # "107 w main st, belleville, wi 53508, madison, wi" for every
        # out-of-town address that happened not to contain "madison" (#236).
        if "madison" not in addr and not _HAS_STATE_RE.search(addr):
            addr = f"{addr}{_MADISON_SUFFIX}"
        return addr
    if venue_name and venue_name.strip():
        # Isthmus appends the town to venues outside Madison ("The Mill, Paoli").
        # Split it off and key on the real city so the Nominatim query names the
        # right place instead of stacking ", madison, wi" onto another town.
        bare, city = canonical_venues.split_city_suffix(venue_name.strip())
        name = re.sub(r"\s+", " ", (bare or "").strip().lower())
        city = (city or _DEFAULT_CITY).strip().lower()
        return f"{name}{_NAME_SEPARATOR}{city}, wi"
    return None


def _throttle() -> None:
    global _last_call_at
    with _throttle_lock:
        elapsed = time.monotonic() - _last_call_at
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        _last_call_at = time.monotonic()


def _call_nominatim(lookup_key: str) -> tuple[str, dict | None]:
    """Returns (status, result_dict_or_None). status is success|not_found|error."""
    # Nominatim rejects `q` combined with structured params (city/state/country),
    # so always use free-text `q` and bias to Madison via the viewbox bbox.
    if _NAME_SEPARATOR in lookup_key:
        name, _, city_suffix = lookup_key.partition(_NAME_SEPARATOR)
        q = f"{name}, {city_suffix}"
    else:
        q = lookup_key

    params = {
        "q": q,
        "viewbox": MADISON_VIEWBOX,
        "bounded": "1",
        "format": "json",
        "limit": "1",
    }

    _throttle()
    try:
        resp = httpx.get(
            NOMINATIM_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except Exception as e:
        logger.warning("Geocoder error for %r: %s", lookup_key, e)
        return "error", None

    data = resp.json()
    if not data:
        return "not_found", None
    return "success", data[0]


def _coords_of(row: VenueGeocode | None) -> tuple[float, float] | None:
    if row is None or row.status != "success":
        return None
    if row.latitude is None or row.longitude is None:
        return None
    return (row.latitude, row.longitude)


def _is_expired(row: VenueGeocode) -> bool:
    """Whether a cached row should be re-attempted.

    Only ``error`` rows expire. ``success`` and ``not_found`` are answers
    Nominatim actually gave us and stay put; ``?force=true`` is the escape
    hatch for re-checking those. See _ERROR_RETRY_AFTER for why errors don't.
    """
    if row.status != "error":
        return False
    if row.geocoded_at is None:
        return True
    stamped = row.geocoded_at
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamped > _ERROR_RETRY_AFTER


def _apply_result(row: VenueGeocode, lookup_key: str, status: str, result: dict | None) -> None:
    """Write a fresh Nominatim outcome onto a cache row."""
    row.status = status
    row.geocoder = "nominatim"
    row.latitude = None
    row.longitude = None
    if status == "success" and result is not None:
        try:
            row.latitude = float(result["lat"])
            row.longitude = float(result["lon"])
            row.display_name = result.get("display_name")
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Geocoder bad payload for %r: %s", lookup_key, e)
            row.status = "error"
            row.latitude = None
            row.longitude = None


def geocode_lookup(lookup_key: str, db: Session) -> tuple[float, float] | None:
    """Return cached or freshly-fetched (lat, lng) for a lookup key, or None."""
    cached = db.query(VenueGeocode).filter(VenueGeocode.lookup_key == lookup_key).first()
    if cached is not None and not _is_expired(cached):
        return _coords_of(cached)

    status, result = _call_nominatim(lookup_key)

    if cached is not None:
        # Retry of an expired error: update in place rather than inserting a
        # second row for the same key (which would violate the unique index).
        _apply_result(cached, lookup_key, status, result)
        cached.attempts = (cached.attempts or 1) + 1
        cached.geocoded_at = datetime.now(timezone.utc)
        db.commit()
        return _coords_of(cached)

    row = VenueGeocode(lookup_key=lookup_key, status=status, geocoder="nominatim")
    _apply_result(row, lookup_key, status, result)
    db.add(row)
    try:
        # Commit immediately so a crash mid-run doesn't waste rate-limit budget
        # on a key we already hit the network for.
        db.commit()
    except IntegrityError:
        # Another pass inserted this key between our read and our write — the
        # check-then-insert above is not atomic, and `?force=true` deleting rows
        # underneath a concurrent run makes the window easy to hit. Take the
        # winner's answer instead of letting the whole pass die on it (#255).
        db.rollback()
        logger.info("Geocode cache race on %r; using the concurrently-written row", lookup_key)
        winner = db.query(VenueGeocode).filter(VenueGeocode.lookup_key == lookup_key).first()
        return _coords_of(winner)

    return _coords_of(row)


def geocode_event(event: Event, db: Session) -> bool:
    """Set event.latitude/longitude from canonical registry, cache, or Nominatim.

    Resolution order is canonical registry → address key → venue-name key.
    Returns True if coordinates were changed. Canonical registry hits short-
    circuit ahead of any cache or network lookup so listed venues are immune
    to upstream address malformations (see #115).

    The venue-name step is a fallback, not a reordering — a street address is
    more precise, so it stays preferred and the name is only tried when the
    address resolved to nothing. Some sources ship addresses OpenStreetMap has
    no node for while carrying the venue under its name: Isthmus's
    "5950 golf course road, spring green" misses where "American Players
    Theatre, Spring Green" resolves (#247).
    """
    canonical = canonical_venues.lookup(event.venue_name)
    if canonical is not None:
        if event.latitude == canonical.latitude and event.longitude == canonical.longitude:
            return False
        event.latitude = canonical.latitude
        event.longitude = canonical.longitude
        return True
    if event.latitude is not None and event.longitude is not None:
        return False
    key = normalize_lookup(event.venue_name, event.venue_address)
    if key is None:
        return False
    coords = geocode_lookup(key, db)
    if coords is None:
        # Passing venue_address=None forces the venue-name form of the key, so
        # the city-suffix parsing from #236 applies here too. The inequality
        # guard skips a redundant second lookup when the address was absent and
        # `key` is already the name-only form. Both keys cache independently, so
        # the extra request costs one call per venue, not one per event.
        fallback_key = normalize_lookup(event.venue_name, None)
        if fallback_key is not None and fallback_key != key:
            coords = geocode_lookup(fallback_key, db)
    if coords is None:
        return False
    event.latitude, event.longitude = coords
    return True
