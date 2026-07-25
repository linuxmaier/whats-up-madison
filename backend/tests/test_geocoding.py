from datetime import datetime, timezone

import pytest

from app import canonical_venues
from app.geocoding import geocode_event, normalize_lookup
from app.models import Event


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
