"""Hard-coded coordinates and addresses for well-known Madison venues.

When a scraper ships a slightly malformed address (e.g. Visit Madison's
"701A E Washington Ave" for High Noon Saloon), Nominatim snaps to the wrong
spot — sometimes blocks away. This registry short-circuits both the
geocoder and the ingest address-fill logic for venues we know by name, so
the displayed address and pin are correct regardless of upstream variance.

Coordinates are verified against Nominatim using the canonical address
listed here. To add a venue: pick the name as it appears in
``Event.venue_name`` (lowercase), curl Nominatim with the correct address,
paste the lat/lon into a new entry. Add alt spellings as separate keys.
"""

from typing import NamedTuple, Optional


class CanonicalVenue(NamedTuple):
    latitude: float
    longitude: float
    address: str


CANONICAL_VENUES: dict[str, CanonicalVenue] = {
    "high noon saloon": CanonicalVenue(
        43.0797191, -89.3762962, "701 E Washington Ave, Madison, WI 53703"
    ),
    "the sylvee": CanonicalVenue(
        43.0808002, -89.3746711, "25 S Livingston St, Madison, WI 53703"
    ),
    "majestic theatre": CanonicalVenue(
        43.0744156, -89.3808963, "115 King St, Madison, WI 53703"
    ),
    "orpheum theater": CanonicalVenue(
        43.0751848, -89.3887320, "216 State St, Madison, WI 53703"
    ),
    "orpheum theatre": CanonicalVenue(
        43.0751848, -89.3887320, "216 State St, Madison, WI 53703"
    ),
    "barrymore theatre": CanonicalVenue(
        43.0930640, -89.3522665, "2090 Atwood Ave, Madison, WI 53704"
    ),
    "overture center": CanonicalVenue(
        43.0741343, -89.3882773, "201 State St, Madison, WI 53703"
    ),
    "overture center for the arts": CanonicalVenue(
        43.0741343, -89.3882773, "201 State St, Madison, WI 53703"
    ),
}


def _normalize(venue_name: Optional[str]) -> Optional[str]:
    if not venue_name:
        return None
    return venue_name.strip().lower()


def lookup(venue_name: Optional[str]) -> Optional[CanonicalVenue]:
    """Return the canonical entry for ``venue_name``, or None.

    Matching is case-insensitive and ignores leading/trailing whitespace.
    """
    key = _normalize(venue_name)
    if key is None:
        return None
    return CANONICAL_VENUES.get(key)


def canonical_keys() -> list[str]:
    """Lowercased venue-name keys, useful for SQL ``IN`` filters."""
    return list(CANONICAL_VENUES.keys())
