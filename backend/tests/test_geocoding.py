from datetime import datetime, timezone

import pytest

from app import canonical_venues
from app.geocoding import geocode_event, normalize_lookup
from app.models import Event, VenueGeocode


def _event(**overrides) -> Event:
    base = dict(
        title="Pert Near Sandstone",
        start_at=datetime(2026, 5, 15, 20, 0, tzinfo=timezone.utc),
        venue_name="High Noon Saloon",
        canonical_hash="hash-1",
        status="active",
    )
    base.update(overrides)
    return Event(**base)


# ---------------------------------------------------------------------------
# normalize_lookup city handling (#236). The old implementation appended
# ", madison, wi" to every venue-name-only lookup, so an Isthmus venue outside
# the city produced "the mill, paoli, madison, wi" — a query naming two towns,
# bounded to a viewbox the real town fell outside of. 449 of the 720
# uncoordinated production events carried a city suffix.
# ---------------------------------------------------------------------------

def test_normalize_lookup_uses_the_venues_own_city():
    assert normalize_lookup("The Mill, Paoli", None) == "the mill | paoli, wi"
    assert normalize_lookup("American Players Theatre, Spring Green", None) == (
        "american players theatre | spring green, wi"
    )


def test_normalize_lookup_defaults_to_madison_without_a_city_suffix():
    assert normalize_lookup("Cafe Coda", None) == "cafe coda | madison, wi"


def test_normalize_lookup_prefers_address_and_keeps_out_of_town_ones_intact():
    # An address that already names a state must not get ", madison, wi" glued
    # onto the end of it.
    assert normalize_lookup(
        "Hop Garden, Belleville", "107 W Main St, Belleville, WI 53508"
    ) == "107 w main st, belleville, wi 53508"


def test_normalize_lookup_backfills_city_for_a_bare_street_address():
    assert normalize_lookup(None, "701 E Washington Ave") == (
        "701 e washington ave, madison, wi"
    )


def test_normalize_lookup_blank_inputs():
    assert normalize_lookup(None, None) is None
    assert normalize_lookup("  ", "  ") is None


def test_canonical_lookup_normalizes_case_and_whitespace():
    assert canonical_venues.lookup("HIGH NOON SALOON") is not None
    assert canonical_venues.lookup("  high noon saloon  ") is not None
    assert canonical_venues.lookup("Random Coffee Shop") is None
    assert canonical_venues.lookup(None) is None
    assert canonical_venues.lookup("") is None


def test_canonical_venue_overrides_existing_bad_coords(db, monkeypatch):
    # Reproduces #115: an Event row carrying the wrong High Noon coords from
    # Visit Madison's malformed address. Without the fix, geocode_event
    # early-exits because latitude is set, leaving the bad coords in place.
    event = _event(
        venue_address="701A E Washington Ave, Madison, WI 53703",
        latitude=43.0849,
        longitude=-89.3699,
    )
    db.add(event)
    db.commit()

    def boom(*args, **kwargs):
        raise AssertionError("Nominatim should not be called for canonical venues")

    monkeypatch.setattr("app.geocoding._call_nominatim", boom)

    updated = geocode_event(event, db)

    assert updated is True
    canonical = canonical_venues.lookup("High Noon Saloon")
    assert event.latitude == canonical.latitude
    assert event.longitude == canonical.longitude


def test_canonical_venue_skips_nominatim_when_already_correct(db, monkeypatch):
    canonical = canonical_venues.lookup("High Noon Saloon")
    event = _event(
        canonical_hash="hash-2",
        latitude=canonical.latitude,
        longitude=canonical.longitude,
    )
    db.add(event)
    db.commit()

    monkeypatch.setattr(
        "app.geocoding._call_nominatim",
        lambda *a, **k: pytest.fail("Nominatim called for already-correct canonical venue"),
    )

    assert geocode_event(event, db) is False


def test_canonical_venue_with_no_coords_uses_registry_not_nominatim(db, monkeypatch):
    event = _event(canonical_hash="hash-3")  # latitude/longitude default to None
    db.add(event)
    db.commit()

    monkeypatch.setattr(
        "app.geocoding._call_nominatim",
        lambda *a, **k: pytest.fail("Nominatim called for canonical venue with no coords"),
    )

    assert geocode_event(event, db) is True
    canonical = canonical_venues.lookup("High Noon Saloon")
    assert (event.latitude, event.longitude) == (canonical.latitude, canonical.longitude)


# ---------------------------------------------------------------------------
# Venue-name fallback (#247). Some sources ship an address OpenStreetMap has no
# node for while carrying the venue under its name — Isthmus's "5950 golf course
# road, spring green" misses where "American Players Theatre, Spring Green"
# resolves. geocode_event used to build one key and give up.
#
# NOTE: conftest truncates events but NOT venue_geocodes, so cache rows survive
# between tests in a session. Each test below uses a distinct venue so one
# test's cached result can't satisfy another's lookup.
# ---------------------------------------------------------------------------

def _nominatim_stub(resolving: dict, seen: list):
    """Stub _call_nominatim: resolve only the keys in `resolving`, recording each."""
    def _call(lookup_key):
        seen.append(lookup_key)
        if lookup_key in resolving:
            lat, lng = resolving[lookup_key]
            return "success", {"lat": str(lat), "lon": str(lng), "display_name": "stub"}
        return "not_found", None
    return _call


def test_address_miss_falls_back_to_venue_name(db, monkeypatch):
    venue, address = "Fallback Playhouse, Spring Green", "1 Nonexistent Rd, Spring Green, WI"
    addr_key = normalize_lookup(venue, address)
    name_key = normalize_lookup(venue, None)
    assert addr_key != name_key

    event = _event(canonical_hash="h-247-a", venue_name=venue, venue_address=address)
    db.add(event)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr(
        "app.geocoding._call_nominatim", _nominatim_stub({name_key: (43.1432, -90.0396)}, seen)
    )

    assert geocode_event(event, db) is True
    assert (event.latitude, event.longitude) == (43.1432, -90.0396)
    # Address first, then the name — order matters, the address is more precise.
    assert seen == [addr_key, name_key]

    # Both keys cache, so the second lookup costs one request per venue, not per event.
    cached = {
        r.lookup_key: r.status
        for r in db.query(VenueGeocode).filter(VenueGeocode.lookup_key.in_([addr_key, name_key]))
    }
    assert cached == {addr_key: "not_found", name_key: "success"}


def test_address_hit_never_queries_the_venue_name(db, monkeypatch):
    venue, address = "Resolvable Hall, Verona", "500 Real St, Verona, WI"
    addr_key = normalize_lookup(venue, address)

    event = _event(canonical_hash="h-247-b", venue_name=venue, venue_address=address)
    db.add(event)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr(
        "app.geocoding._call_nominatim", _nominatim_stub({addr_key: (43.0, -89.5)}, seen)
    )

    assert geocode_event(event, db) is True
    # The fallback must cost nothing on the happy path.
    assert seen == [addr_key]


def test_event_without_a_venue_name_has_nothing_to_fall_back_to(db, monkeypatch):
    address = "77 Unmatched Ave, Fitchburg, WI"
    addr_key = normalize_lookup(None, address)

    event = _event(canonical_hash="h-247-c", venue_name=None, venue_address=address)
    db.add(event)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr("app.geocoding._call_nominatim", _nominatim_stub({}, seen))

    assert geocode_event(event, db) is False
    assert seen == [addr_key]


def test_name_only_event_does_not_issue_a_duplicate_lookup(db, monkeypatch):
    # With no address the primary key is already the name-only form, so the
    # fallback would re-query the identical key without the inequality guard.
    venue = "Nameless Address Tavern, Monona"
    name_key = normalize_lookup(venue, None)

    event = _event(canonical_hash="h-247-d", venue_name=venue, venue_address=None)
    db.add(event)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr("app.geocoding._call_nominatim", _nominatim_stub({}, seen))

    assert geocode_event(event, db) is False
    assert seen == [name_key]


def test_both_keys_missing_are_cached_so_neither_is_retried(db, monkeypatch):
    venue, address = "Doubly Unknown Cidery, Middleton", "2 Missing Way, Middleton, WI"
    addr_key = normalize_lookup(venue, address)
    name_key = normalize_lookup(venue, None)

    event = _event(canonical_hash="h-247-e", venue_name=venue, venue_address=address)
    db.add(event)
    db.commit()

    seen: list[str] = []
    monkeypatch.setattr("app.geocoding._call_nominatim", _nominatim_stub({}, seen))

    assert geocode_event(event, db) is False
    assert seen == [addr_key, name_key]

    statuses = {
        r.lookup_key: r.status
        for r in db.query(VenueGeocode).filter(VenueGeocode.lookup_key.in_([addr_key, name_key]))
    }
    assert statuses == {addr_key: "not_found", name_key: "not_found"}

    # A second pass must hit the cache, not the network.
    seen.clear()
    assert geocode_event(event, db) is False
    assert seen == []


def test_non_canonical_venue_falls_through_to_nominatim_path(db, monkeypatch):
    event = _event(
        canonical_hash="hash-4",
        venue_name="Some Random Bar",
        venue_address="999 Fake Street, Madison, WI",
    )
    db.add(event)
    db.commit()

    calls: list[str] = []

    def fake_lookup(_key, _db):
        calls.append("lookup")
        return (43.0, -89.4)

    monkeypatch.setattr("app.geocoding.geocode_lookup", fake_lookup)

    assert geocode_event(event, db) is True
    assert calls == ["lookup"]
    assert event.latitude == 43.0
    assert event.longitude == -89.4
