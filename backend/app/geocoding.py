import logging
import re
import threading
import time
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models import Event, VenueGeocode

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "whats-up-madison/0.1 (andrew.eric.maier@gmail.com)"

# Bounding box around Madison, WI used to bias address-form lookups.
# Order matches Nominatim's viewbox param: left,top,right,bottom (lng,lat,lng,lat).
MADISON_VIEWBOX = "-89.6,43.18,-89.20,42.95"

MIN_INTERVAL_SECONDS = 1.05  # Nominatim ToS: max 1 request/second
REQUEST_TIMEOUT_SECONDS = 10.0

# "<name> | madison, wi" marks a venue-name-only lookup so geocode_lookup can
# route the request to the structured (city/state) form rather than free-text q.
_NAME_SEPARATOR = " | "
_MADISON_SUFFIX = ", madison, wi"

_throttle_lock = threading.Lock()
_last_call_at: float = 0.0


def normalize_lookup(venue_name: Optional[str], venue_address: Optional[str]) -> Optional[str]:
    """Build a stable cache key from whatever venue info we have."""
    if venue_address and venue_address.strip():
        addr = re.sub(r"\s+", " ", venue_address.strip().lower())
        if "madison" not in addr:
            addr = f"{addr}{_MADISON_SUFFIX}"
        return addr
    if venue_name and venue_name.strip():
        name = re.sub(r"\s+", " ", venue_name.strip().lower())
        return f"{name}{_NAME_SEPARATOR}madison, wi"
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
        name, _, _suffix = lookup_key.partition(_NAME_SEPARATOR)
        q = f"{name}, madison, wi"
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
    """Set event.latitude/longitude from cache or Nominatim. Returns True on hit."""
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
