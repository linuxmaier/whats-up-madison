"""Unit tests for venue normalization (#236).

The match key decides whether two venue strings name the same place. It has to
be permissive enough to collapse the ", <City>" suffix Isthmus appends to
out-of-town venues, and strict enough that twenty different bars all running
trivia at 7pm stay twenty different bars.
"""

from app import canonical_venues as cv

# ---------------------------------------------------------------------------
# split_city_suffix
# ---------------------------------------------------------------------------

def test_split_city_suffix_strips_known_city():
    assert cv.split_city_suffix("Hidden Cave Cidery, Middleton") == (
        "Hidden Cave Cidery", "Middleton"
    )
    assert cv.split_city_suffix("The Mill, Paoli") == ("The Mill", "Paoli")


def test_split_city_suffix_leaves_unknown_trailing_segment():
    # "The" is not a city — the Isthmus listing "Brass Ring, The" must survive.
    assert cv.split_city_suffix("Brass Ring, The") == ("Brass Ring, The", None)
    assert cv.split_city_suffix("Cafe Coda") == ("Cafe Coda", None)


def test_split_city_suffix_strips_only_the_trailing_city():
    assert cv.split_city_suffix("Louisianne's, Etc., Middleton") == (
        "Louisianne's, Etc.", "Middleton"
    )


def test_split_city_suffix_handles_none_and_blank():
    assert cv.split_city_suffix(None) == (None, None)
    assert cv.split_city_suffix("") == ("", None)


# ---------------------------------------------------------------------------
# match_key — collapsing
# ---------------------------------------------------------------------------

def test_match_key_keeps_the_city_so_chain_locations_stay_distinct():
    # Buck and Honey's has four locations. Dropping the city from the key would
    # merge all four into one venue — the bug the collapse report caught.
    keys = {
        cv.match_key(f"Buck and Honey's, {city}")
        for city in ("Monona", "Mount Horeb", "Sun Prairie", "Waunakee")
    }
    assert len(keys) == 4
    assert cv.match_key("Veterans Memorial Park, Black Earth") != cv.match_key(
        "Veterans Memorial Park, Brodhead"
    )


def test_venues_match_treats_a_missing_city_as_compatible():
    # Isthmus ships the town, other sources don't — these are one venue.
    assert cv.venues_match("Hidden Cave Cidery, Middleton", "Hidden Cave Cidery")
    assert cv.venues_match("Hidden Cave Cidery", "Hidden Cave Cidery, Middleton")
    assert cv.venues_match("Taliesin, Spring Green", "Taliesin")


def test_venues_match_rejects_two_different_known_cities():
    assert not cv.venues_match("Buck and Honey's, Monona", "Buck and Honey's, Sun Prairie")
    assert not cv.venues_match("Community Park, Belleville", "Community Park, Black Earth")


def test_venues_match_rejects_different_bases_and_blanks():
    assert not cv.venues_match("Cafe Coda", "Cardinal Bar")
    assert not cv.venues_match(None, None)
    assert not cv.venues_match("", "Cafe Coda")


def test_match_key_collapses_ampersand_and_leading_the():
    assert cv.match_key("Wine & Design") == cv.match_key("Wine and Design")
    assert cv.match_key("The Green Room Public House") == cv.match_key("Green Room Public House")


def test_match_key_collapses_punctuation_and_case():
    assert cv.match_key("Cafe CODA") == cv.match_key("cafe coda")
    assert cv.match_key("Warner Park (Trailsway)") == cv.match_key("Warner Park Trailsway")


def test_match_key_blank_venue_is_empty():
    assert cv.match_key(None) == ""
    assert cv.match_key("   ") == ""


# ---------------------------------------------------------------------------
# match_key — registry precedence and separation
# ---------------------------------------------------------------------------

def test_registry_aliases_share_a_match_key():
    key = cv.match_key("Madison Senior Center")
    assert cv.match_key("City of Madison - Madison Senior Center") == key
    assert cv.match_key("The Rigby Pub, Grill and Event Space") == cv.match_key("The Rigby")
    assert cv.match_key("Olbrich Gardens") == cv.match_key("Olbrich Botanical Gardens")
    assert cv.match_key("Meadoowood Park") == cv.match_key("Meadowood Park")
    assert cv.match_key("Peace (Elizabeth Link) Park") == cv.match_key("Elizabeth Link Peace Park")
    assert cv.match_key("Overture Center-Playhouse") == cv.match_key("Overture Center for the Arts")


def test_concerts_on_the_square_phrasings_collapse():
    key = cv.match_key("King Street corner of the Capitol Square")
    assert cv.match_key("King Street Corner of Capitol Square") == key
    assert cv.match_key("King Street side of the Capitol Square") == key
    assert cv.match_key("Capitol Square") == key


def test_registry_entry_does_not_collapse_onto_generic_normalization():
    # "The Mill, Paoli" is a registry-free venue whose generic key is "mill".
    # A registry venue must never land on a generic key by accident — the
    # Rigby is listed, so its key is its canonical name, not "rigby pub".
    assert cv.match_key("The Rigby") == "the rigby"
    assert cv.match_key("The Rigby") != cv.match_key("Rigby Pub Somewhere Else")


def test_memorial_union_terrace_and_building_stay_separate():
    # Same coordinates, deliberately different identities: an indoor Union
    # event is not a Terrace event.
    assert cv.match_key("UW Memorial Union-Terrace") == cv.match_key("Memorial Union Terrace")
    assert cv.match_key("UW Memorial Union") != cv.match_key("Memorial Union Terrace")


def test_hop_garden_locations_stay_separate():
    # Two real taprooms of the same brewery in different towns. Stripping the
    # city suffix must not merge them.
    assert cv.match_key("Hop Garden, Belleville") != cv.match_key(
        "Hop Garden Brewing & Tap Room, Evansville"
    )
    assert not cv.venues_match("Hop Garden, Belleville", "Hop Garden, Evansville")


def test_distinct_venues_do_not_collide():
    names = [
        "Brass Ring, The", "Cardinal Bar", "Delta Beer Lab", "Starkweather Brewing Company",
        "Echo Tap", "Madison's", "VFW Post 1318-Ski Lane", "The Red Zone/The Annex",
        "Thrill Factory Entertainment", "Doundrins Distilling, Cottage Grove",
        "Java Cat", "Zafferano Ristorante, Fitchburg", "Working Draft Beer Company",
        "Lone Girl Brewing Company, Waunakee", "Harmony Bar and Grill", "The Kickback, Middleton",
        "Octopi Brewing, Waunakee", "Fairway Lounge, Fitchburg", "Karben4 Brewing", "Northstreet",
    ]
    keys = [cv.match_key(n) for n in names]
    assert len(set(keys)) == len(names), "distinct venues collapsed onto one key"


# ---------------------------------------------------------------------------
# normalize_name / lookup
# ---------------------------------------------------------------------------

def test_normalize_name_resolves_aliases_to_canonical_display_name():
    assert cv.normalize_name("City of Madison - Madison Senior Center") == "Madison Senior Center"
    assert cv.normalize_name("The Orpheum Theatre") == "Orpheum Theater"
    assert cv.normalize_name("Overture Center-Overture Hall") == "Overture Center for the Arts"


def test_normalize_name_passes_through_unlisted_venues():
    assert cv.normalize_name("Some Random Bar") == "Some Random Bar"
    assert cv.normalize_name(None) is None


def test_every_registry_entry_has_a_canonical_name():
    # match_key() keys registry hits on canonical_name; a blank one would make
    # every unnamed entry collide on "".
    for key, entry in cv.CANONICAL_VENUES.items():
        assert entry.canonical_name, f"{key!r} has no canonical_name"


def test_canonical_names_round_trip_to_themselves():
    # Every canonical display name must itself be a registry key, otherwise an
    # already-normalized venue_name stops resolving on the next scrape.
    for entry in set(cv.CANONICAL_VENUES.values()):
        assert cv.lookup(entry.canonical_name) is not None, (
            f"canonical name {entry.canonical_name!r} is not a registry key"
        )
