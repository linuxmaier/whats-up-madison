from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.ingest import ingest_events
from app.main import app
from app.models import Event
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


def _future_dt(days_ahead: int = 7, hour: int = 19) -> datetime:
    return (datetime.now(timezone.utc) + timedelta(days=days_ahead)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _past_dt(days_ago: int = 7, hour: int = 19) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0
    )


def _raw(
    title: str = "Concert in the Park",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    source_name: str = "Source A",
    source_url: str = "https://example.com/event/1",
    description: str | None = None,
    venue_name: str = "Garner Park",
) -> RawEvent:
    return RawEvent(
        title=title,
        start_at=start_at or _future_dt(),
        end_at=end_at,
        source_name=source_name,
        source_url=source_url,
        description=description,
        venue_name=venue_name,
        categories=[],
        all_day=False,
    )


def test_empty_query_returns_empty(client, db):
    ingest_events("Source A", [_raw()], db)
    db.commit()

    resp = client.get("/events/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_whitespace_only_query_returns_empty(client, db):
    ingest_events("Source A", [_raw()], db)
    db.commit()

    resp = client.get("/events/search?q=   ")
    assert resp.status_code == 200
    assert resp.json() == []


def test_title_match(client, db):
    ingest_events(
        "Source A",
        [
            _raw(title="Jazz Night at the Park", source_url="https://example.com/event/1"),
            _raw(title="Yoga Class", venue_name="Studio B", source_url="https://example.com/event/2"),
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=jazz")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Jazz Night at the Park"


def test_description_match(client, db):
    ingest_events(
        "Source A",
        [
            _raw(
                title="Quiet Evening",
                description="A relaxing flute performance under the stars.",
                source_url="https://example.com/event/3",
            ),
            _raw(title="Other", venue_name="Other Place", source_url="https://example.com/event/4"),
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=flute")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Quiet Evening"


def test_venue_match(client, db):
    ingest_events(
        "Source A",
        [
            _raw(title="Show 1", venue_name="High Noon Saloon", source_url="https://example.com/event/5"),
            _raw(title="Show 2", venue_name="Other Venue", source_url="https://example.com/event/6"),
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=high noon")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Show 1"


def test_case_insensitive(client, db):
    ingest_events("Source A", [_raw(title="Jazz Night")], db)
    db.commit()

    for query in ("jazz", "JAZZ", "JaZz"):
        resp = client.get(f"/events/search?q={query}")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


def test_past_events_excluded(client, db):
    ingest_events(
        "Source A",
        [
            _raw(
                title="Old Concert",
                start_at=_past_dt(days_ago=14),
                end_at=_past_dt(days_ago=14, hour=22),
                source_url="https://example.com/event/old",
            ),
            _raw(
                title="Future Concert",
                start_at=_future_dt(days_ahead=14),
                source_url="https://example.com/event/new",
            ),
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=concert")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Future Concert"


def test_multi_day_event_in_progress_is_included(client, db):
    # Event started a week ago, ends a week from now — should appear today.
    ingest_events(
        "Source A",
        [
            _raw(
                title="Multi-Day Festival",
                start_at=_past_dt(days_ago=7),
                end_at=_future_dt(days_ahead=7),
            )
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=festival")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_removed_events_excluded(client, db):
    ingest_events("Source A", [_raw(title="Active Concert")], db)
    # Now remove it — second run with empty list deactivates the source and
    # the event becomes status='removed'.
    ingest_events("Source A", [], db)
    db.commit()

    event = db.query(Event).one()
    assert event.status == "removed"

    resp = client.get("/events/search?q=concert")
    assert resp.status_code == 200
    assert resp.json() == []


def test_results_ordered_by_start_at(client, db):
    ingest_events(
        "Source A",
        [
            _raw(
                title="Concert C",
                start_at=_future_dt(days_ahead=14),
                source_url="https://example.com/event/c",
            ),
            _raw(
                title="Concert A",
                start_at=_future_dt(days_ahead=2),
                source_url="https://example.com/event/a",
            ),
            _raw(
                title="Concert B",
                start_at=_future_dt(days_ahead=7),
                source_url="https://example.com/event/b",
            ),
        ],
        db,
    )
    db.commit()

    resp = client.get("/events/search?q=concert")
    assert resp.status_code == 200
    titles = [e["title"] for e in resp.json()]
    assert titles == ["Concert A", "Concert B", "Concert C"]


def test_result_limit(client, db):
    raws = [
        _raw(
            title=f"Concert {i:03d}",
            start_at=_future_dt(days_ahead=1) + timedelta(minutes=i),
            source_url=f"https://example.com/event/{i}",
        )
        for i in range(250)
    ]
    ingest_events("Source A", raws, db)
    db.commit()

    resp = client.get("/events/search?q=concert")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 200


def test_response_includes_sources(client, db):
    ingest_events("Source A", [_raw(title="Jazz Night")], db)
    db.commit()

    resp = client.get("/events/search?q=jazz")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["sources"] == [
        {"source_name": "Source A", "source_url": "https://example.com/event/1"}
    ]
