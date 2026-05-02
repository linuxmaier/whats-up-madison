import json
import logging
from typing import Optional

import anthropic
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.categories import CATEGORIES, CATEGORY_DESCRIPTIONS
from app.config import settings
from app.models import Event

logger = logging.getLogger(__name__)

_CATEGORIES_SET = frozenset(CATEGORIES)
_MIN_DESCRIPTION_LEN = 80

_SYSTEM_PROMPT = (
    "You are a category classifier for a Madison, WI community events listing.\n\n"
    "For each event in the batch, assign zero or more categories from the taxonomy below. "
    "Use only these exact category names. Assign multiple only when the event genuinely fits "
    "more than one. Leave the list empty if no category fits well.\n\n"
    "CATEGORY TAXONOMY:\n"
    + "\n".join(f"- {name}: {desc}" for name, desc in CATEGORY_DESCRIPTIONS.items())
    + "\n\n"
    "Respond with one line per event: ID:Category1,Category2 "
    "(comma-separated, no spaces around commas). "
    "Use an empty value after the colon if no category fits. "
    "Output only these lines — no explanation, no markdown.\n\n"
    "Example:\n"
    "0:Music\n"
    "1:Food & Drink,Community & Clubs\n"
    "2:"
)


def _build_event_payload(event: Event) -> Optional[dict]:
    """Returns None if the event lacks sufficient context for tagging."""
    desc = event.description
    if not desc or len(desc.strip()) < _MIN_DESCRIPTION_LEN:
        return None
    payload: dict = {"title": event.title, "description": desc.strip()}
    if event.venue_name:
        payload["venue"] = event.venue_name
    return payload


def _call_llm(
    client: anthropic.Anthropic, model: str, batch: list[dict]
) -> tuple[dict, dict]:
    """
    Tag a batch of events via the LLM.

    batch: list of dicts with keys id (str), title, description, venue (optional)
    Returns: (predictions mapping str(id) -> list[str] categories, usage dict)
    """
    user_msg = "\n".join(json.dumps(item) for item in batch)

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "cache_creation_input_tokens": getattr(
            response.usage, "cache_creation_input_tokens", 0
        ),
        "cache_read_input_tokens": getattr(
            response.usage, "cache_read_input_tokens", 0
        ),
        "output_tokens": response.usage.output_tokens,
    }

    predictions: dict = {}
    for line in response.content[0].text.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        idx, _, cats_str = line.partition(":")
        idx = idx.strip()
        cats = [c.strip() for c in cats_str.split(",") if c.strip() in _CATEGORIES_SET]
        predictions[idx] = cats

    return predictions, usage


def tag_untagged_events(db: Session, model: Optional[str] = None) -> dict:
    """Tag active events that have no categories and a sufficient description."""
    model = model or settings.tagger_model

    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    candidates = (
        db.query(Event)
        .filter(
            Event.status == "active",
            func.coalesce(func.cardinality(Event.categories), 0) == 0,
        )
        .all()
    )

    to_tag: list[tuple[Event, dict]] = []
    skipped_no_desc = 0
    for event in candidates:
        payload = _build_event_payload(event)
        if payload is None:
            skipped_no_desc += 1
        else:
            to_tag.append((event, payload))

    tagged = 0
    batches = 0
    batch_size = 25

    for i in range(0, len(to_tag), batch_size):
        batch_items = to_tag[i : i + batch_size]
        batch_payload = [
            {"id": str(j), **payload} for j, (_, payload) in enumerate(batch_items)
        ]

        try:
            predictions, _ = _call_llm(client, model, batch_payload)
        except Exception as e:
            logger.warning(
                "Tagger: LLM call failed for batch starting at index %d: %s", i, e
            )
            batches += 1
            continue

        for j, (event, _) in enumerate(batch_items):
            cats = predictions.get(str(j), [])
            if cats:
                event.categories = cats
                tagged += 1

        db.commit()
        batches += 1

    return {
        "tagged": tagged,
        "skipped_no_description": skipped_no_desc,
        "candidates": len(candidates),
        "batches": batches,
    }
