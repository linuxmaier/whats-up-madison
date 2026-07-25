from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.database import get_db
from app.main import app
from app.scrapers.base import BaseSource, RawEvent


class _FakeSource(BaseSource):
    """In-memory BaseSource that records fetch() calls and returns a fixed list."""

    def __init__(self, name: str, supports_window: bool, raws: list[RawEvent]):
        self.name = name
        self.scraper_type = "test"
        self.supports_window_days = supports_window
        self._raws = raws
        self.fetch_calls: list[int | None] = []

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        self.fetch_calls.append(window_days)
        return list(self._raws)


def _raw(title: str, source_name: str) -> RawEvent:
    return RawEvent(
        title=title,
        start_at=datetime(2026, 6, 15, 19, 0, 0, tzinfo=timezone.utc),
        source_name=source_name,
        source_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        venue_name="Test Venue",
    )


@pytest.fixture
def fakes(monkeypatch):
    """Replace SCRAPERS, geocoding, and tagging with hermetic stubs."""
    fake_a = _FakeSource("Fake A", supports_window=True, raws=[_raw("Show A", "Fake A")])
    fake_b = _FakeSource("Fake B", supports_window=False, raws=[_raw("Show B", "Fake B")])
    monkeypatch.setattr(main_module, "SCRAPERS", [fake_a, fake_b])

    geocode_calls: list[str] = []

    def fake_geocode(name, _db):
        geocode_calls.append(name)
        return {"geocoded": 0, "geocode_misses": 0, "geocode_skipped": 0}

    monkeypatch.setattr(main_module, "geocode_missing_for_source", fake_geocode)

    tag_calls: list[None] = []

    def fake_tag(_db, model=None):
        tag_calls.append(None)
        return {"tagged": 0, "batches": 0}

    monkeypatch.setattr(main_module, "tag_untagged_events", fake_tag)

    return {
        "a": fake_a,
        "b": fake_b,
        "geocode_calls": geocode_calls,
        "tag_calls": tag_calls,
    }


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_no_params_runs_all_scrapers(client, fakes):
    resp = client.post("/admin/scrape")
    assert resp.status_code == 200
    body = resp.json()
    assert "Fake A" in body
    assert "Fake B" in body
    assert "_tagging" in body
    assert fakes["a"].fetch_calls == [None]
    assert fakes["b"].fetch_calls == [None]
    assert fakes["geocode_calls"] == ["Fake A", "Fake B"]
    assert len(fakes["tag_calls"]) == 1


def test_single_scraper_filter(client, fakes):
    resp = client.post("/admin/scrape?scraper=Fake A")
    assert resp.status_code == 200
    body = resp.json()
    assert "Fake A" in body
    assert "Fake B" not in body
    assert fakes["a"].fetch_calls == [None]
    assert fakes["b"].fetch_calls == []
    assert fakes["geocode_calls"] == ["Fake A"]


def test_multiple_scraper_filter_preserves_declaration_order(client, fakes):
    # Pass B before A; response order should still mirror SCRAPERS, not query order.
    resp = client.post("/admin/scrape?scraper=Fake B&scraper=Fake A")
    assert resp.status_code == 200
    # Both run, both geocode in declaration order.
    assert fakes["geocode_calls"] == ["Fake A", "Fake B"]
    assert fakes["a"].fetch_calls == [None]
    assert fakes["b"].fetch_calls == [None]


def test_unknown_scraper_returns_400_with_available_set(client, fakes):
    resp = client.post("/admin/scrape?scraper=Bogus")
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["unknown"] == ["Bogus"]
    assert set(detail["available"]) == {"Fake A", "Fake B"}
    # Nothing should have run.
    assert fakes["a"].fetch_calls == []
    assert fakes["b"].fetch_calls == []
    assert fakes["geocode_calls"] == []
    assert fakes["tag_calls"] == []


def test_days_param_is_forwarded(client, fakes):
    resp = client.post("/admin/scrape?days=7")
    assert resp.status_code == 200
    assert fakes["a"].fetch_calls == [7]
    assert fakes["b"].fetch_calls == [7]
    # Fake B does not support a window, so the response flags it.
    body = resp.json()
    assert body["Fake B"]["window_days_honored"] is False
    # Fake A supports a window, so no flag is added.
    assert "window_days_honored" not in body["Fake A"]


def test_days_zero_rejected(client, fakes):
    resp = client.post("/admin/scrape?days=0")
    assert resp.status_code == 422
    assert fakes["a"].fetch_calls == []


def test_skip_geocode(client, fakes):
    resp = client.post("/admin/scrape?skip_geocode=true")
    assert resp.status_code == 200
    assert fakes["geocode_calls"] == []
    assert len(fakes["tag_calls"]) == 1


def test_skip_tag(client, fakes):
    resp = client.post("/admin/scrape?skip_tag=true")
    assert resp.status_code == 200
    body = resp.json()
    assert "_tagging" not in body
    assert fakes["tag_calls"] == []
    assert fakes["geocode_calls"] == ["Fake A", "Fake B"]


# ---------------------------------------------------------------------------
# /admin/geocode robustness (#255). Two overlapping passes corrupted each
# other's cache rows — `?force=true` deletes rows a concurrent run then
# re-inserts — and the endpoint reported the resulting crash as HTTP 200 with
# an {"error": ...} body, so an aborted backfill looked like a success.
# ---------------------------------------------------------------------------

def test_geocode_rejects_a_concurrent_run(client, monkeypatch):
    monkeypatch.setattr(
        main_module, "geocode_all_missing", lambda *a, **k: pytest.fail("should not run")
    )
    # Simulate a pass already in flight.
    assert main_module._geocode_lock.acquire(blocking=False)
    try:
        resp = client.post("/admin/geocode")
    finally:
        main_module._geocode_lock.release()

    assert resp.status_code == 409
    assert "already in progress" in resp.json()["detail"]


def test_geocode_releases_the_lock_after_a_run(client, monkeypatch):
    monkeypatch.setattr(main_module, "geocode_all_missing", lambda *a, **k: {"events_updated": 0})

    assert client.post("/admin/geocode").status_code == 200
    # A failed release would wedge the endpoint permanently.
    assert client.post("/admin/geocode").status_code == 200


def test_geocode_failure_is_not_reported_as_success(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("duplicate key value violates unique constraint")

    monkeypatch.setattr(main_module, "geocode_all_missing", boom)

    resp = client.post("/admin/geocode")
    assert resp.status_code == 500
    assert "Geocode run failed" in resp.json()["detail"]
    # And the lock must still be free afterwards.
    assert main_module._geocode_lock.acquire(blocking=False)
    main_module._geocode_lock.release()
