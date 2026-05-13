"""Sample events from production for the /audit-event-accuracy skill.

Hits the public /events?date= endpoint for a spread of forward dates, buckets
events by their first source, and emits JSONL on stdout — one line per sampled
event. Stdlib only so it runs anywhere without conda.
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
import urllib.error
import urllib.request

_DEFAULT_BASE = "https://whats-up-madison.fly.dev"
# Offsets (in days) from today to sample. Spread across two weeks so we hit
# different days of the week and both near- and far-horizon ingest behavior
# without sampling every consecutive day.
_DATE_OFFSETS = (0, 2, 4, 6, 8, 11, 14)
_DESCRIPTION_PREVIEW = 500


def _fetch_date(base_url: str, date: datetime.date) -> list[dict]:
    url = f"{base_url.rstrip('/')}/events?date={date.isoformat()}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _primary_source(event: dict) -> str | None:
    sources = event.get("sources") or []
    if not sources:
        return None
    return sources[0].get("source_name")


def _trim_description(desc: str | None) -> tuple[str | None, bool]:
    if not desc:
        return desc, False
    if len(desc) <= _DESCRIPTION_PREVIEW:
        return desc, False
    return desc[:_DESCRIPTION_PREVIEW], True


def _pick_varied(events: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Pick up to `n` events biased toward variety in venue and start date."""
    if len(events) <= n:
        return events
    rng.shuffle(events)
    picked: list[dict] = []
    seen_venues: set[str] = set()
    seen_dates: set[str] = set()
    # First pass: prefer fresh venue + date combos.
    for event in events:
        if len(picked) >= n:
            break
        venue = (event.get("venue_name") or "").lower()
        date = (event.get("start_at") or "")[:10]
        if venue in seen_venues and date in seen_dates:
            continue
        seen_venues.add(venue)
        seen_dates.add(date)
        picked.append(event)
    # Top up with whatever remains if variety constraint left us short.
    if len(picked) < n:
        for event in events:
            if event in picked:
                continue
            picked.append(event)
            if len(picked) >= n:
                break
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-source", type=int, default=3, help="events to sample per source (default 3)")
    parser.add_argument("--base-url", default=_DEFAULT_BASE, help=f"API base URL (default {_DEFAULT_BASE})")
    parser.add_argument("--seed", type=int, default=None, help="optional RNG seed for deterministic sampling")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    today = datetime.date.today()

    by_id: dict[str, dict] = {}
    fetch_errors: list[str] = []
    for offset in _DATE_OFFSETS:
        date = today + datetime.timedelta(days=offset)
        try:
            events = _fetch_date(args.base_url, date)
        except (urllib.error.URLError, TimeoutError) as exc:
            fetch_errors.append(f"{date.isoformat()}: {exc}")
            continue
        for event in events:
            event_id = event.get("id")
            if event_id and event_id not in by_id:
                by_id[event_id] = event

    if fetch_errors:
        for err in fetch_errors:
            print(f"# fetch error: {err}", file=sys.stderr)

    buckets: dict[str, list[dict]] = {}
    for event in by_id.values():
        src = _primary_source(event) or "(no source)"
        buckets.setdefault(src, []).append(event)

    for source in sorted(buckets):
        events = buckets[source]
        sampled = _pick_varied(events, args.per_source, rng)
        for event in sampled:
            desc, truncated = _trim_description(event.get("description"))
            record = {
                "id": event.get("id"),
                "title": event.get("title"),
                "start_at": event.get("start_at"),
                "end_at": event.get("end_at"),
                "all_day": event.get("all_day", False),
                "venue_name": event.get("venue_name"),
                "venue_address": event.get("venue_address"),
                "categories": event.get("categories", []),
                "description_preview": desc,
                "description_truncated": truncated,
                "image_url": event.get("image_url"),
                "sources": event.get("sources", []),
                "primary_source": source,
                "pool_size_for_source": len(events),
            }
            print(json.dumps(record, ensure_ascii=False))

    summary = {src: {"available": len(buckets[src]), "sampled": min(len(buckets[src]), args.per_source)} for src in buckets}
    print(f"# summary: {json.dumps(summary, ensure_ascii=False)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
