import hashlib
import html
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawEvent:
    title: str
    start_at: datetime
    source_name: str
    source_url: str
    description: Optional[str] = None
    end_at: Optional[datetime] = None
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    image_url: Optional[str] = None
    categories: list[str] = field(default_factory=list)
    all_day: bool = False

    def canonical_hash(self) -> str:
        key = "|".join([
            self.title.lower().strip(),
            str(self.start_at.date()),
            (self.venue_name or "").lower().strip(),
        ])
        return hashlib.sha256(key.encode()).hexdigest()


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

    def fetch(self) -> list[RawEvent]:
        raise NotImplementedError
