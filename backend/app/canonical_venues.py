"""Hard-coded coordinates and addresses for well-known Madison venues.

When a scraper ships a slightly malformed address (e.g. Visit Madison's
"701A E Washington Ave" for High Noon Saloon), Nominatim snaps to the wrong
spot — sometimes blocks away. This registry short-circuits both the
geocoder and the ingest address-fill logic for venues we know by name, so
the displayed address and pin are correct regardless of upstream variance.

Every entry carries an explicit ``canonical_name``: it is the display name
ingest normalizes to, and the identity :func:`match_key` dedups on. Aliases
(sub-rooms, city-suffixed forms, "The" prefixes, source typos) are separate
dict keys pointing at the same venue constant, so they all collapse onto one
row.

Coordinates are verified against Nominatim using the canonical address
listed here. To add a venue: pick the name as it appears in
``Event.venue_name`` (lowercase), curl Nominatim with the correct address,
paste the lat/lon into a new entry. Add alt spellings as separate keys.

A venue that merely needs *coordinates* does NOT belong here — the geocoder
resolves ``"<venue>, <city>, WI"`` on its own (see ``geocoding.py``). Add an
entry only when a venue needs alias collapsing for dedup, or when the
upstream address/coordinates are wrong.
"""

import re
from typing import NamedTuple, Optional


class CanonicalVenue(NamedTuple):
    latitude: float
    longitude: float
    address: str
    # The display name ingest normalizes venue_name to before hashing, and the
    # identity match_key() dedups on. Always set — alias keys and the canonical
    # key alike resolve to the same string, which is what makes sub-room,
    # city-suffixed and misspelled forms merge into a single Event.
    canonical_name: str = ""


_HIGH_NOON = CanonicalVenue(
    43.0797191, -89.3762962, "701 E Washington Ave, Madison, WI 53703",
    "High Noon Saloon",
)
# Our Lives stores city="Madison" for Delta Beer Lab; the correct postal city
# is Fitchburg (#229). The canonical entry corrects address and geocode alike.
_DELTA_BEER_LAB = CanonicalVenue(
    43.0373542, -89.3823463, "167 E Badger Rd, Fitchburg, WI 53713",
    "Delta Beer Lab",
)
_ATWOOD = CanonicalVenue(
    43.0909400, -89.3556544, "1925 Winnebago St, Madison, WI 53704",
    "Atwood Music Hall",
)
_SYLVEE = CanonicalVenue(
    43.0808002, -89.3746711, "25 S Livingston St, Madison, WI 53703",
    "The Sylvee",
)
_MAJESTIC = CanonicalVenue(
    43.0744156, -89.3808963, "115 King St, Madison, WI 53703",
    "Majestic Theatre",
)
# Visit Madison ships "The Orpheum Theater" (leading "The") while Ticketmaster
# ships "Orpheum Theater"; both -er/-re spellings occur in the wild (#223).
_ORPHEUM = CanonicalVenue(
    43.0751848, -89.3887320, "216 State St, Madison, WI 53703",
    "Orpheum Theater",
)
_BARRYMORE = CanonicalVenue(
    43.0930640, -89.3522665, "2090 Atwood Ave, Madison, WI 53704",
    "Barrymore Theatre",
)
# Concerts on the Square outdoor stage on the Wisconsin State Capitol lawn.
# The venue has no street address — coords resolve to the Capitol building
# itself, which is the audience's gathering ground. Isthmus, Visit Madison and
# the WCO each phrase the corner differently; all four forms collapse here.
_CAPITOL_SQUARE = CanonicalVenue(
    43.0746917, -89.3841658, "Capitol Square, Madison, WI 53703",
    "King Street Corner of Capitol Square",
)
# Aubergine — Willy Street Co-op community space. Visit Madison uses the
# verbose subtitle form, Isthmus just "Aubergine" (#215).
_AUBERGINE = CanonicalVenue(
    43.0840219, -89.3637186, "1226 Williamson St, Madison, WI 53703",
    "Aubergine",
)
# Isthmus ships "Holy Wisdom Monastery, Middleton" (name + city suffix) while
# Visit Madison uses the bare name (#216).
_HOLY_WISDOM = CanonicalVenue(
    43.1218569, -89.4493683, "4200 County Road M, Middleton, WI 53562",
    "Holy Wisdom Monastery",
)
# Alliant Energy Center campus — south Madison expo/concert/sports complex.
# Coords + address taken from the venue's own LocalBusiness JSON-LD block.
_ALLIANT = CanonicalVenue(
    43.045136, -89.381338, "1919 Alliant Energy Center Way, Madison, WI 53713",
    "Alliant Energy Center",
)
_OVERTURE = CanonicalVenue(
    43.0741343, -89.3882773, "201 State St, Madison, WI 53703",
    "Overture Center for the Arts",
)

# --- Added in #236, from an audit of 45 days of production data -------------
# The City of Madison scraper prefixes its own name onto the venue while
# Isthmus uses the bare name. 58 events in the sampled window, the largest
# named venue in the corpus.
_SENIOR_CENTER = CanonicalVenue(
    43.0728785, -89.3893722, "333 W Mifflin St, Madison, WI 53703",
    "Madison Senior Center",
)
_RIGBY = CanonicalVenue(
    43.0749857, -89.3810853, "119 E Main St, Madison, WI 53703",
    "The Rigby",
)
_OLBRICH = CanonicalVenue(
    43.0926153, -89.3345825, "3330 Atwood Ave, Madison, WI 53704",
    "Olbrich Botanical Gardens",
)
# The Terrace and the building proper are deliberately SEPARATE entries that
# share coordinates: an indoor Union event is not a Terrace event, so they
# must not dedup into each other.
_UNION_TERRACE = CanonicalVenue(
    43.0765204, -89.4003002, "800 Langdon St, Madison, WI 53703",
    "Memorial Union Terrace",
)
_UNION = CanonicalVenue(
    43.0765204, -89.4003002, "800 Langdon St, Madison, WI 53703",
    "UW Memorial Union",
)
_MONONA_TERRACE = CanonicalVenue(
    43.0716701, -89.3800230, "1 John Nolen Dr, Madison, WI 53703",
    "Monona Terrace Community & Convention Center",
)
_BARTELL = CanonicalVenue(
    43.0765295, -89.3833781, "113 E Mifflin St, Madison, WI 53703",
    "Bartell Theatre",
)
_BREESE_STEVENS = CanonicalVenue(
    43.0833584, -89.3740396, "917 E Mifflin St, Madison, WI 53703",
    "Breese Stevens Field",
)
# One production event had been geocoded to (43.0976, -89.3542) — the East
# High School pin, ~1.6 km off. Pinning the coordinates corrects it on the
# next geocode pass.
_GARVER = CanonicalVenue(
    43.0945392, -89.3343968, "3241 Garver Green, Madison, WI 53704",
    "Garver Feed Mill",
)
# The City of Madison feed misspells this park as "Meadoowood Park"; the alias
# below collapses the typo onto the correct row.
_MEADOWOOD = CanonicalVenue(
    43.0298405, -89.4807370, "Thrush Ln, Madison, WI 53711",
    "Meadowood Park",
)
_PEACE_PARK = CanonicalVenue(
    43.0751811, -89.3925019, "Elizabeth Link Peace Park, Madison, WI 53703",
    "Elizabeth Link Peace Park",
)
_BLACK_BUSINESS_HUB = CanonicalVenue(
    43.0401290, -89.3944737, "2352 S Park St, Madison, WI 53713",
    "Madison Black Business Hub",
)

CANONICAL_VENUES: dict[str, CanonicalVenue] = {
    "high noon saloon": _HIGH_NOON,
    "delta beer lab": _DELTA_BEER_LAB,
    "atwood music hall": _ATWOOD,
    "the sylvee": _SYLVEE,
    "majestic theatre": _MAJESTIC,
    "orpheum theater": _ORPHEUM,
    "orpheum theatre": _ORPHEUM,
    "the orpheum theater": _ORPHEUM,
    "the orpheum theatre": _ORPHEUM,
    "barrymore theatre": _BARRYMORE,
    # Concerts on the Square — one stage, four phrasings across three sources.
    "king street corner of the capitol square": _CAPITOL_SQUARE,
    "king street corner of capitol square": _CAPITOL_SQUARE,
    "king street side of the capitol square": _CAPITOL_SQUARE,
    "capitol square": _CAPITOL_SQUARE,
    "aubergine": _AUBERGINE,
    "aubergine: a willy street co-op community space": _AUBERGINE,
    "holy wisdom monastery": _HOLY_WISDOM,
    "holy wisdom monastery, middleton": _HOLY_WISDOM,
    "alliant energy center": _ALLIANT,
    # Isthmus venue-subroom compound form (observed on the Bridal Expo listing).
    "alliant energy center-exhibition hall": _ALLIANT,
    # Visit Madison outdoor-grounds form (Willow Island is the lakeside park
    # within the campus, observed on the World's Largest Brat Fest listing).
    "willow island at alliant energy center": _ALLIANT,
    "overture center for the arts": _OVERTURE,
    "overture center": _OVERTURE,
    # Overture sub-rooms by bare room name
    "overture hall":          _OVERTURE,
    "capitol theater":        _OVERTURE,
    "capitol theater stage":  _OVERTURE,
    "promenade hall":         _OVERTURE,
    "promenade lobby":        _OVERTURE,
    "rotunda stage":          _OVERTURE,
    "the playhouse":          _OVERTURE,
    "james watrous gallery":  _OVERTURE,
    # "Venue-Subroom" compound format used by the Isthmus RSS feed
    "overture center-overture hall":         _OVERTURE,
    "overture center-capitol theater":       _OVERTURE,
    "overture center-capitol theater stage": _OVERTURE,
    "overture center-promenade hall":        _OVERTURE,
    "overture center-promenade lobby":       _OVERTURE,
    "overture center-rotunda stage":         _OVERTURE,
    "overture center-the playhouse":         _OVERTURE,
    "overture center-playhouse":             _OVERTURE,
    "overture center-wisconsin studio":      _OVERTURE,
    "overture center-james watrous gallery": _OVERTURE,
    "overture center-james watrous gallery of the wisconsin academy": _OVERTURE,
    # --- #236 additions ---
    "madison senior center": _SENIOR_CENTER,
    "city of madison - madison senior center": _SENIOR_CENTER,
    "the rigby": _RIGBY,
    "the rigby pub": _RIGBY,
    "the rigby pub, grill and event space": _RIGBY,
    "olbrich botanical gardens": _OLBRICH,
    "olbrich gardens": _OLBRICH,
    "memorial union terrace": _UNION_TERRACE,
    "uw memorial union-terrace": _UNION_TERRACE,
    "uw memorial union": _UNION,
    "monona terrace community & convention center": _MONONA_TERRACE,
    "monona terrace community and convention center": _MONONA_TERRACE,
    "monona terrace": _MONONA_TERRACE,
    "monona terrace rooftop": _MONONA_TERRACE,
    "monona terrace - lecture hall": _MONONA_TERRACE,
    "lake vista cafe": _MONONA_TERRACE,
    "bartell theatre": _BARTELL,
    "the bartell theatre": _BARTELL,
    "breese stevens field": _BREESE_STEVENS,
    "garver feed mill": _GARVER,
    "meadowood park": _MEADOWOOD,
    "meadoowood park": _MEADOWOOD,
    "elizabeth link peace park": _PEACE_PARK,
    "peace (elizabeth link) park": _PEACE_PARK,
    "madison black business hub": _BLACK_BUSINESS_HUB,
    "black business hub": _BLACK_BUSINESS_HUB,
    "the black business hub- urban league": _BLACK_BUSINESS_HUB,
}


# Cities and unincorporated communities around Madison that sources append to
# venue names. Isthmus ships "<Venue>, <City>" for anything outside Madison
# ("The Mill, Paoli") while every other source ships the bare name, so the
# suffix has to come off the match key for the two forms to dedup (#236).
# The geocoder parses the same suffix to name the right town in its query
# instead of blindly appending ", madison, wi".
CITY_SUFFIXES = frozenset({
    "madison", "monona", "middleton", "fitchburg", "verona", "waunakee",
    "sun prairie", "cottage grove", "deforest", "de forest", "oregon",
    "stoughton", "mcfarland", "cross plains", "black earth", "mazomanie",
    "spring green", "brooklyn", "evansville", "mount horeb", "belleville",
    "paoli", "lodi", "prairie du sac", "sauk city", "monroe", "lake mills",
    "cambridge", "columbus", "edgerton", "milton", "new glarus", "poynette",
    "ridgeway", "dodgeville", "baraboo", "portage", "janesville", "beloit",
    "watertown", "jefferson", "fort atkinson", "reedsburg", "barneveld",
    "blue mounds", "marshall", "cambria", "arlington", "brodhead",
})

_LEADING_THE_RE = re.compile(r"^the\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def _normalize(venue_name: Optional[str]) -> Optional[str]:
    if not venue_name:
        return None
    return venue_name.strip().lower()


def split_city_suffix(venue_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Split a trailing ``", <City>"`` into ``(bare_name, city)``.

    Only splits when the trailing segment is a known nearby city, so names that
    merely end in a comma-separated fragment survive intact ("Brass Ring, The"
    keeps its suffix; "Louisianne's, Etc., Middleton" loses only "Middleton").
    Returns ``(venue_name, None)`` when there is no recognizable city suffix.
    """
    if not venue_name:
        return venue_name, None
    head, sep, tail = venue_name.rpartition(",")
    if not sep:
        return venue_name, None
    city = tail.strip()
    if city.lower() in CITY_SUFFIXES and head.strip():
        return head.strip(), city
    return venue_name, None


def match_parts(venue_name: Optional[str]) -> tuple[str, str]:
    """Split a venue name into its normalized ``(base, city)`` identity.

    Registry entries win outright and key on their canonical name with an empty
    city, so a listed venue never collapses onto an unrelated venue that happens
    to normalize the same way. Everything else gets generic normalization:
    casefold, "&" → "and", drop a leading "the", strip punctuation, collapse
    whitespace — with any known city suffix returned separately rather than
    thrown away.
    """
    if not venue_name or not venue_name.strip():
        return "", ""
    entry = lookup(venue_name)
    if entry is not None:
        return entry.canonical_name.strip().lower(), ""
    bare, city = split_city_suffix(venue_name)
    s = (bare or "").strip().lower()
    s = s.replace(" & ", " and ")
    s = _LEADING_THE_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    return _WS_RE.sub(" ", s).strip(), (city or "").strip().lower()


def match_key(venue_name: Optional[str]) -> str:
    """Return the normalized dedup key for a venue name.

    This is a *comparison* key, not a display name — ``Event.venue_name`` keeps
    whatever the source shipped (after canonical-name normalization) so the
    geocoder can still read the city off it.

    The city stays **in** the key. Dropping it would collapse the four
    "Buck and Honey's" locations (Monona, Mount Horeb, Sun Prairie, Waunakee)
    into one venue, along with the "Veterans Memorial Park" in Black Earth and
    the one in Brodhead. Cross-source merging of "Hidden Cave Cidery, Middleton"
    against a bare "Hidden Cave Cidery" is handled by :func:`venues_match` on
    the fuzzy path instead, which treats an absent city as compatible with any.
    """
    base, city = match_parts(venue_name)
    return f"{base}|{city}" if city else base


def venues_match(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two venue names plausibly denote the same place.

    Bases must be identical. Cities must agree *when both are known* — a source
    that omits the town ("Hidden Cave Cidery") is treated as compatible with one
    that includes it ("Hidden Cave Cidery, Middleton"), while two different
    known towns never match.
    """
    base_a, city_a = match_parts(a)
    base_b, city_b = match_parts(b)
    if not base_a or base_a != base_b:
        return False
    return not city_a or not city_b or city_a == city_b


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

    Registry hits resolve to their ``canonical_name`` so sub-room, alias and
    misspelled forms all render as one venue. Unlisted venues come back
    unchanged, so callers can always use the return value directly.
    """
    if not venue_name:
        return venue_name
    entry = lookup(venue_name)
    if entry is not None and entry.canonical_name:
        return entry.canonical_name
    return venue_name


def canonical_keys() -> list[str]:
    """Lowercased venue-name keys, useful for SQL ``IN`` filters."""
    return list(CANONICAL_VENUES.keys())
