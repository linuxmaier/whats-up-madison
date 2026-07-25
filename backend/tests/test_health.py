"""Tests for the /health freshness fields (#244).

A scrape that stops running is invisible from the outside — GET /events keeps
serving the last successful ingest, so the site looks fine while quietly showing
week-old data. That is what happened in #244: GitHub disabled the Daily Scrape
workflow after 60 days of repo inactivity and production froze for a week.
These fields give the CI freshness check something to alarm on.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.ingest import ingest_events
from app.main import app
from app.models import EventSource
from app.scrapers.base import RawEvent


@pytest.fixture
def client(db):
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _raw(title: str = "Concert in the Park") -> RawEvent:
    return RawEvent(
        title=title,
        start_at=datetime(2026, 6, 15, 19, 0, 0, tzinfo=timezone.utc),
        source_name="Source A",
        source_url=f"https://example.com/{title.replace(' ', '-')}",
        venue_name="Garner Park",
    )


def test_health_reports_no_ingest_on_an_empty_database(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["last_ingest_at"] is None
    assert body["hours_since_ingest"] is None
    assert body["active_events"] == 0


def test_health_reports_a_fresh_ingest(client, db):
    ingest_events("Source A", [_raw()], db)

    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["active_events"] == 1
    assert body["last_ingest_at"] is not None
    # Just ingested, so effectively zero hours old.
    assert 0 <= body["hours_since_ingest"] < 1


def test_health_reports_a_stale_ingest(client, db):
    # The #244 scenario: the scraper stopped a week ago. The events still serve
    # fine; only last_seen_at reveals that nothing has run.
    ingest_events("Source A", [_raw()], db)
    stale = datetime.now(timezone.utc) - timedelta(days=7)
    db.query(EventSource).update({"last_seen_at": stale}, synchronize_session=False)
    db.commit()

    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["active_events"] == 1
    # ~168h — comfortably past the 48h CI threshold.
    assert body["hours_since_ingest"] > 48


def test_health_stays_200_when_the_database_is_unreachable():
    # The endpoint doubles as a liveness probe, so a database outage must
    # degrade the payload rather than 500 the request.
    class _BrokenSession:
        def query(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    def _override_get_db():
        yield _BrokenSession()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        resp = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "unavailable"
    assert body["last_ingest_at"] is None
    assert body["hours_since_ingest"] is None
    assert body["active_events"] is None
