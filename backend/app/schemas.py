from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class FeedbackRequest(BaseModel):
    title: str
    body: str
    contact: str = ""
    website: str = ""  # honeypot — bots fill this; humans don't see it

    @field_validator("title", "body")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


class SourceRef(BaseModel):
    source_name: str
    source_url: str

    model_config = {"from_attributes": True}


class EventResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    start_at: datetime
    end_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    categories: list[str] = []
    all_day: bool = False
    status: str
    sources: list[SourceRef] = []

    model_config = {"from_attributes": True}
