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
    # When set, ingest normalizes venue_name to this string before hashing and
    # dedup so events from sources that use sub-room names merge with events
    # from sources that use the building name.
    canonical_name: Optional[str] = None


_OVERTURE = CanonicalVenue(
    43.0741343, -89.3882773, "201 State St, Madison, WI 53703",
    canonical_name="Overture Center for the Arts",
)

CANONICAL_VENUES: dict[str, CanonicalVenue] = {
    "high noon saloon": CanonicalVenue(
        43.0797191, -89.3762962, "701 E Washington Ave, Madison, WI 53703"
    ),
    "atwood music hall": CanonicalVenue(
        43.0909400, -89.3556544, "1925 Winnebago St, Madison, WI 53704"
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
    # Overture Center building names — the canonical display name is
    # "Overture Center for the Arts"; all sub-room and alias entries
    # below carry canonical_name so ingest normalizes them before hashing.
    "overture center for the arts": CanonicalVenue(
        43.0741343, -89.3882773, "201 State St, Madison, WI 53703"
    ),
    "overture center": _OVERTURE,
    # Sub-rooms by bare room name (Overture scraper, some sources)
    "overture hall":          _OVERTURE,
    "capitol theater":        _OVERTURE,
    "capitol theater stage":  _OVERTURE,
    "promenade hall":         _OVERTURE,
    "promenade lobby":        _OVERTURE,
    "rotunda stage":          _OVERTURE,
    "the playhouse":          _OVERTURE,
    "james watrous gallery":  _OVERTURE,
    # "Venue-Subroom" compound format used by the Isthmus iCal/RSS feed
    "overture center-overture hall":         _OVERTURE,
    "overture center-capitol theater":       _OVERTURE,
    "overture center-capitol theater stage": _OVERTURE,
    "overture center-promenade hall":        _OVERTURE,
    "overture center-promenade lobby":       _OVERTURE,
    "overture center-rotunda stage":         _OVERTURE,
    "overture center-the playhouse":         _OVERTURE,
    "overture center-james watrous gallery": _OVERTURE,
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


def normalize_name(venue_name: Optional[str]) -> Optional[str]:
    """Return the canonical display name for ``venue_name``.

    If the registry entry has a ``canonical_name`` set (e.g. a sub-room or
    alias entry), returns that name. Otherwise returns ``venue_name``
    unchanged so callers can always use the return value directly.
    """
    if not venue_name:
        return venue_name
    entry = lookup(venue_name)
    if entry is not None and entry.canonical_name is not None:
        return entry.canonical_name
    return venue_name


def canonical_keys() -> list[str]:
    """Lowercased venue-name keys, useful for SQL ``IN`` filters."""
    return list(CANONICAL_VENUES.keys())
