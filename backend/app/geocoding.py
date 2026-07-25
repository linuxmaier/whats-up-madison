import logging
import re
import threading
import time
from typing import Optional

import httpx
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


def normalize_lookup(venue_name: Optional[str], venue_address: Optional[str]) -> Optional[str]:
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


def _call_nominatim(lookup_key: str) -> tuple[str, Optional[dict]]:
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


def geocode_lookup(lookup_key: str, db: Session) -> Optional[tuple[float, float]]:
    """Return cached or freshly-fetched (lat, lng) for a lookup key, or None."""
    cached = db.query(VenueGeocode).filter(VenueGeocode.lookup_key == lookup_key).first()
    if cached is not None:
        if cached.status == "success" and cached.latitude is not None and cached.longitude is not None:
            return (cached.latitude, cached.longitude)
        return None

    status, result = _call_nominatim(lookup_key)
    row = VenueGeocode(
        lookup_key=lookup_key,
        status=status,
        geocoder="nominatim",
    )
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

    db.add(row)
    # Commit immediately so a crash mid-run doesn't waste rate-limit budget on
    # a key we already hit the network for.
    db.commit()

    if row.status == "success" and row.latitude is not None and row.longitude is not None:
        return (row.latitude, row.longitude)
    return None


def geocode_event(event: Event, db: Session) -> bool:
    """Set event.latitude/longitude from canonical registry, cache, or Nominatim.

    Returns True if coordinates were changed. Canonical registry hits short-
    circuit ahead of any cache or network lookup so listed venues are immune
    to upstream address malformations (see #115).
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
        return False
    event.latitude, event.longitude = coords
    return True
