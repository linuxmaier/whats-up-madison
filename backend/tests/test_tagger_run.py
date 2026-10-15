"""DB-bound tests for tag_untagged_events' failure accounting.

The LLM call is stubbed, so these cover how per-batch failures are counted
and surfaced, not tagging quality.
"""

import uuid
from datetime import datetime, timezone

import pytest

from app import tagger
from app.models import Event
from app.tagger import TaggingFailedError, tag_untagged_events

_DESC = "A long enough description for the tagger to consider this event. " * 2


def _add_events(db, n):
    for i in range(n):
        db.add(Event(
            title=f"Event {i}",
            description=_DESC,
            start_at=datetime(2026, 6, 15, 19, 0, tzinfo=timezone.utc),
            categories=[],
            canonical_hash=uuid.uuid4().hex,
        ))
    db.commit()


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setattr(tagger.settings, "anthropic_api_key", "test-key")


def _tag_everything(_client, _model, batch_payload):
    return {item["id"]: ["Music"] for item in batch_payload}, {}


def test_every_batch_failing_raises_with_stats(db, monkeypatch):
    _add_events(db, 30)  # two batches

    def fail(*_args):
        raise RuntimeError("credit balance is too low")

    monkeypatch.setattr(tagger, "_call_llm", fail)
    with pytest.raises(TaggingFailedError) as exc:
        tag_untagged_events(db)
    assert exc.value.stats["batches"] == 2
    assert exc.value.stats["failed_batches"] == 2
    assert exc.value.stats["tagged"] == 0
    assert "credit balance is too low" in str(exc.value)


def test_partial_failure_reports_without_raising(db, monkeypatch):
    _add_events(db, 30)
    calls = []

    def first_fails(client, model, batch_payload):
        calls.append(None)
        if len(calls) == 1:
            raise RuntimeError("transient 529")
        return _tag_everything(client, model, batch_payload)

    monkeypatch.setattr(tagger, "_call_llm", first_fails)
    stats = tag_untagged_events(db)
    assert stats["batches"] == 2
    assert stats["failed_batches"] == 1
    assert stats["tagged"] == 5
    assert stats["last_error"] == "transient 529"


def test_clean_run_reports_zero_failures(db, monkeypatch):
    _add_events(db, 3)
    monkeypatch.setattr(tagger, "_call_llm", _tag_everything)
    stats = tag_untagged_events(db)
    assert stats == {
        "tagged": 3, "skipped_no_description": 0, "candidates": 3,
        "batches": 1, "failed_batches": 0,
    }


def test_no_candidates_is_not_a_failure(db, monkeypatch):
    monkeypatch.setattr(tagger, "_call_llm", _tag_everything)
    assert tag_untagged_events(db)["batches"] == 0
