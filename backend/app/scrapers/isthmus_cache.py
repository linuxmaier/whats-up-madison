"""Persistent cache of Isthmus detail-page extractions.

Isthmus's RSS feed surfaces ~1,000+ items in a typical 30-day window, and the
scraper currently issues one detail-page fetch per item to extract categories,
venue_address, and (when the RSS description is short) an enriched description.
That sequential fan-out dominates the daily scrape runtime.

This cache stores `(categories, venue_address, description)` keyed by the
detail-page URL with `occ_dtstart` stripped — so all recurring occurrences of
an event share one row — and a `rss_signature` over the RSS-visible fields
that should trigger refresh when they change (parsed name, venue_name, and
RSS description). Times are deliberately excluded from the signature: they
vary per occurrence but don't affect detail-page content.

Only successful extractions are cached. Failures (network errors, missing
content) fall through so the next run can retry.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Literal, Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from sqlalchemy.orm import Session

from app.models import IsthmusDetail

logger = logging.getLogger(__name__)


def _strip_occ_dtstart(url: str) -> str:
    """Return `url` with the `occ_dtstart` query param removed.

    Recurring Isthmus events share a detail-page URL but emit one RSS item per
    occurrence, each with `?occ_dtstart=<ISO>`. The detail page itself is the
    same regardless of which occurrence, so we drop that param for the cache key.
    """
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "occ_dtstart"]
    return urlunparse(parts._replace(query=urlencode(kept)))


def compute_rss_signature(event_name: str, venue_name: Optional[str], rss_description: Optional[str]) -> str:
    """Hash the RSS-visible fields that should trigger detail-page refresh."""
    blob = "|".join([
        (event_name or "").strip().lower(),
        (venue_name or "").strip().lower(),
        (rss_description or "").strip().lower(),
    ])
    return hashlib.sha256(blob.encode()).hexdigest()


def get_or_fetch_detail(
    url: str,
    *,
    rss_signature: str,
    rss_description: Optional[str],
    db: Session,
) -> tuple[list[str], Optional[str], Optional[str], Literal["hit", "miss"]]:
    """Return cached or freshly-extracted (categories, venue_address, description, outcome).

    On hit: cached fields returned directly, no HTTP call.
    On miss (no row or signature mismatch): fetch the detail page, extract,
    upsert the cache row, return fresh fields. Failed fetches are not cached
    so transient errors (404/429/timeout) retry on the next run.
    """
    # Local import to avoid an isthmus → isthmus_cache → isthmus circular at module load.
    from app.scrapers.isthmus import (
        _DESC_MIN_LEN,
        _extract_categories,
        _extract_description,
        _extract_venue_address,
        _fetch_detail_soup,
    )

    lookup_key = _strip_occ_dtstart(url)
    cached = db.query(IsthmusDetail).filter(IsthmusDetail.lookup_key == lookup_key).first()
    if cached is not None and cached.rss_signature == rss_signature:
        return (list(cached.categories or []), cached.venue_address, cached.description, "hit")

    soup = _fetch_detail_soup(url)
    if soup is None:
        return ([], None, None, "miss")

    categories = _extract_categories(soup)
    venue_address = _extract_venue_address(soup)
    # Mirror the original scraper's logic: only run description enrichment
    # when the RSS description is short. Storing None when not enriched keeps
    # cache rows honest about what the detail page actually contributed.
    description: Optional[str] = None
    if len(rss_description or "") < _DESC_MIN_LEN:
        description = _extract_description(soup, url)

    if cached is not None:
        cached.rss_signature = rss_signature
        cached.categories = categories
        cached.venue_address = venue_address
        cached.description = description
    else:
        db.add(IsthmusDetail(
            lookup_key=lookup_key,
            rss_signature=rss_signature,
            categories=categories,
            venue_address=venue_address,
            description=description,
        ))
    # Commit-as-you-go (mirrors geocode_lookup) so a crash mid-run doesn't
    # waste the network work we already paid for.
    db.commit()
    return (categories, venue_address, description, "miss")
