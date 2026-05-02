#!/usr/bin/env python3
"""
Cost experimentation eval for the LLM category tagger.

Run from backend/ with the project conda env:
    ~/miniconda3/envs/whats-up-madison/bin/python eval_tagger.py [options]

Options:
    --models haiku sonnet     Models to compare (default: haiku sonnet)
    --sample 50               Events to evaluate (default: 50)
    --batch-sizes 1 5 10 25   Batch sizes to test (default: 25)
    --formats json compact    Output formats to test (default: json)

Uses Visit Madison events (pre-tagged by the scraper) as ground truth.
Strips categories in memory and asks each model to re-predict them, then scores results.
No writes to the database.
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import anthropic  # noqa: E402
from sqlalchemy import create_engine, func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.categories import CATEGORIES, CATEGORY_DESCRIPTIONS  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import Event  # noqa: E402
from app.tagger import _build_event_payload  # noqa: E402

MODEL_IDS = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
}

# Published prices per million tokens: (input $/MTok, output $/MTok)
MODEL_PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-4-6": (3.00, 15.00),
}

_CATEGORIES_SET = frozenset(CATEGORIES)
_TAXONOMY_TEXT = "\n".join(f"- {name}: {desc}" for name, desc in CATEGORY_DESCRIPTIONS.items())

# --- Format: json ---
# Output: {"0": ["Music"], "1": ["Food & Drink"], "2": []}
_SYSTEM_PROMPT_JSON = (
    "You are a category classifier for a Madison, WI community events listing.\n\n"
    "For each event in the batch, assign zero or more categories from the taxonomy below. "
    "Use only these exact category names. Assign multiple only when the event genuinely fits "
    "more than one. Return an empty list if no category fits well.\n\n"
    "CATEGORY TAXONOMY:\n"
    + _TAXONOMY_TEXT
    + "\n\n"
    "Respond with a single JSON object mapping each event's string id to a list of category "
    "names. Output only the JSON object — no explanation, no markdown fences.\n\n"
    'Example: {"0": ["Music"], "1": ["Food & Drink", "Community & Clubs"], "2": []}'
)

# --- Format: compact ---
# Output: one line per event — ID:Category1,Category2 (empty after colon = no categories)
_SYSTEM_PROMPT_COMPACT = (
    "You are a category classifier for a Madison, WI community events listing.\n\n"
    "For each event in the batch, assign zero or more categories from the taxonomy below. "
    "Use only these exact category names. Assign multiple only when the event genuinely fits "
    "more than one. Leave the list empty if no category fits well.\n\n"
    "CATEGORY TAXONOMY:\n"
    + _TAXONOMY_TEXT
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

FORMATS = {
    "json": _SYSTEM_PROMPT_JSON,
    "compact": _SYSTEM_PROMPT_COMPACT,
}


def _parse_json_response(raw_text: str) -> dict:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    predictions = {}
    for key, cats in parsed.items():
        if isinstance(cats, list):
            predictions[str(key)] = [c for c in cats if c in _CATEGORIES_SET]
    return predictions


def _parse_compact_response(raw_text: str) -> dict:
    predictions = {}
    for line in raw_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        idx, _, cats_str = line.partition(":")
        idx = idx.strip()
        cats = [c.strip() for c in cats_str.split(",") if c.strip() in _CATEGORIES_SET]
        predictions[idx] = cats
    return predictions


PARSERS = {
    "json": _parse_json_response,
    "compact": _parse_compact_response,
}


def _call_llm_eval(
    client: anthropic.Anthropic,
    model: str,
    batch: list[dict],
    fmt: str,
) -> tuple[dict, dict]:
    user_msg = "\n".join(json.dumps(item) for item in batch)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": FORMATS[fmt],
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0),
        "output_tokens": response.usage.output_tokens,
    }

    raw_text = response.content[0].text.strip()
    predictions = PARSERS[fmt](raw_text)
    return predictions, usage


def compute_metrics(
    predicted: list[str], ground_truth: list[str]
) -> tuple[float, float, float]:
    pred_set = set(predicted)
    truth_set = set(ground_truth)
    if not truth_set and not pred_set:
        return 1.0, 1.0, 1.0
    if not truth_set:
        return 0.0, 1.0, 0.0
    if not pred_set:
        return 1.0, 0.0, 0.0
    tp = len(pred_set & truth_set)
    precision = tp / len(pred_set)
    recall = tp / len(truth_set)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def estimate_cost(usage: dict, model_id: str) -> float:
    input_price, output_price = MODEL_PRICES.get(model_id, (0.0, 0.0))
    regular = usage["input_tokens"]
    cache_write = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    return (
        regular / 1e6 * input_price
        + cache_write / 1e6 * input_price * 1.25
        + cache_read / 1e6 * input_price * 0.1
        + usage["output_tokens"] / 1e6 * output_price
    )


def run_combination(
    client: anthropic.Anthropic,
    model_id: str,
    eval_events: list[tuple],
    batch_size: int,
    fmt: str,
) -> dict:
    all_predictions: dict[str, list[str]] = {}
    total_usage: dict[str, int] = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    failed_batches = 0

    for i in range(0, len(eval_events), batch_size):
        chunk = eval_events[i : i + batch_size]
        batch_payload = [
            {"id": str(j), **payload} for j, (_, payload, _) in enumerate(chunk)
        ]
        try:
            predictions, usage = _call_llm_eval(client, model_id, batch_payload, fmt)
        except Exception as e:
            print(f"    ERROR in batch starting at {i}: {e}")
            failed_batches += 1
            continue

        for j in range(len(chunk)):
            all_predictions[str(i + j)] = predictions.get(str(j), [])
        for key in total_usage:
            total_usage[key] += usage.get(key, 0)

    precisions, recalls, f1s, cat_counts = [], [], [], []
    for i, (_, _, ground_truth) in enumerate(eval_events):
        predicted = all_predictions.get(str(i), [])
        p, r, f = compute_metrics(predicted, ground_truth)
        precisions.append(p)
        recalls.append(r)
        f1s.append(f)
        cat_counts.append(len(predicted))

    total_cost = estimate_cost(total_usage, model_id)
    cost_per_1k = total_cost / len(eval_events) * 1000

    return {
        "avg_cats": sum(cat_counts) / len(cat_counts),
        "precision": sum(precisions) / len(precisions),
        "recall": sum(recalls) / len(recalls),
        "f1": sum(f1s) / len(f1s),
        "est_cost_per_1k": cost_per_1k,
        "failed_batches": failed_batches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cost experimentation eval for LLM category tagging"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        choices=list(MODEL_IDS),
        default=["haiku", "sonnet"],
        help="Models to evaluate (default: haiku sonnet)",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=50,
        help="Number of events to evaluate (default: 50)",
    )
    parser.add_argument(
        "--batch-sizes",
        nargs="+",
        type=int,
        default=[25],
        metavar="N",
        help="Batch sizes to test (default: 25)",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=list(FORMATS),
        default=["json"],
        help="Output formats to test (default: json)",
    )
    args = parser.parse_args()

    if not settings.anthropic_api_key:
        print("Error: ANTHROPIC_API_KEY is not set in .env")
        sys.exit(1)

    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        raw_events = (
            db.query(Event)
            .filter(
                Event.status == "active",
                func.cardinality(Event.categories) > 0,
            )
            .limit(args.sample * 4)
            .all()
        )

    eval_events: list[tuple] = []
    for ev in raw_events:
        payload = _build_event_payload(ev)
        if payload is not None:
            eval_events.append((ev, payload, list(ev.categories)))
        if len(eval_events) >= args.sample:
            break

    if not eval_events:
        print(
            "No suitable events found.\n"
            "Need active events with non-empty categories and description >= 80 chars.\n"
            "Run a scrape first: curl -X POST http://localhost:8000/admin/scrape"
        )
        sys.exit(1)

    n_combos = len(args.models) * len(args.batch_sizes) * len(args.formats)
    print(
        f"Evaluating {len(eval_events)} events: "
        f"{len(args.models)} model(s) × {len(args.batch_sizes)} batch size(s) × "
        f"{len(args.formats)} format(s) = {n_combos} combination(s)...\n"
    )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    results = []

    for short_name in args.models:
        model_id = MODEL_IDS[short_name]
        for fmt in args.formats:
            for batch_size in args.batch_sizes:
                label = f"{short_name}/{fmt}/batch={batch_size}"
                print(f"  {label}...", flush=True)
                metrics = run_combination(client, model_id, eval_events, batch_size, fmt)
                if metrics["failed_batches"]:
                    print(f"    ({metrics['failed_batches']} failed batch(es))")
                results.append(
                    {
                        "model": short_name,
                        "fmt": fmt,
                        "batch_size": batch_size,
                        **metrics,
                    }
                )

    if not results:
        print("No results to display.")
        sys.exit(1)

    print()
    header = (
        f"{'Model':<8} {'Format':<8} {'Batch':>6} "
        f"{'Precision':>9} {'Recall':>6} {'F1':>5} {'$/1k events':>11}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['model']:<8} {r['fmt']:<8} {r['batch_size']:>6} "
            f"{r['precision']:>9.3f} {r['recall']:>6.3f} "
            f"{r['f1']:>5.3f} {r['est_cost_per_1k']:>11.4f}"
        )

    print("\nTo use a model in production, set TAGGER_MODEL in backend/.env:")
    for short, full in MODEL_IDS.items():
        print(f"  {short} → TAGGER_MODEL={full}")


if __name__ == "__main__":
    main()
