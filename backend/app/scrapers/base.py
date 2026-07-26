import hashlib
import html
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app import canonical_venues

logger = logging.getLogger(__name__)


@dataclass
class RawEvent:
    title: str
    start_at: datetime
    source_name: str
    source_url: str
    description: str | None = None
    end_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    categories: list[str] = field(default_factory=list)
    all_day: bool = False

    def canonical_hash(self) -> str:
        # The venue component is the normalized match key, not the raw name, so
        # "Hidden Cave Cidery, Middleton" and "Hidden Cave Cidery" hash the same
        # (#236). venue_name itself is left alone — the geocoder reads the city
        # suffix off it to build the right Nominatim query.
        key = "|".join([
            self.title.lower().strip(),
            str(self.start_at.date()),
            canonical_venues.match_key(self.venue_name),
        ])
        return hashlib.sha256(key.encode()).hexdigest()


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError))


def _log_retry_attempt(retry_state) -> None:
    logger.warning(
        "HTTP request failed (attempt %d/3), retrying: %s",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception(_is_retriable),
    before_sleep=_log_retry_attempt,
)
def http_get_with_retry(url: str, **kwargs) -> httpx.Response:
    """GET `url` with automatic retry on 5xx and network/timeout errors."""
    resp = httpx.get(url, **kwargs)
    resp.raise_for_status()
    return resp


def clean_html_text(s: str) -> str:
    """Unescape HTML entities, strip tags, and preserve paragraph structure."""
    s = html.unescape(s)
    # Block-level closers become paragraph breaks; <br> becomes a line break
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"</(p|div|h[1-6]|li|section|article)>", "\n\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    # Collapse horizontal whitespace (but not newlines)
    s = re.sub(r"[^\S\n]+", " ", s)
    # At most one blank line between paragraphs
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


class BaseSource:
    name: str = ""
    scraper_type: str = ""
    # False when the source has no controllable forward-window (HTML calendar
    # pages that just render what's posted). The /admin/scrape endpoint uses
    # this to flag in its response that the `days` filter was a no-op.
    supports_window_days: bool = True

    def fetch(self, window_days: int | None = None) -> list[RawEvent]:
        raise NotImplementedError

    def fetch_chunks(self, window_days: int | None = None) -> Iterator[list[RawEvent]]:
        """Yield batches of events as they become available.

        The orchestrator ingests each batch immediately, so scrapers whose
        fetch phase is long (per-event detail fetches with rate limiting)
        keep the DB connection warm and persist partial progress if a later
        batch fails. The default implementation yields one batch containing
        the full fetch() result — appropriate for fast scrapers where there
        is no natural chunk boundary.
        """
        yield self.fetch(window_days=window_days)
