import hashlib
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

    def canonical_hash(self) -> str:
        key = "|".join([
            self.title.lower().strip(),
            str(self.start_at.date()),
            (self.venue_name or "").lower().strip(),
        ])
        return hashlib.sha256(key.encode()).hexdigest()


class BaseSource:
    name: str = ""
    scraper_type: str = ""

    def fetch(self) -> list[RawEvent]:
        raise NotImplementedError
