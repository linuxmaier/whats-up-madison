from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class FeedbackRequest(BaseModel):
    title: str
    body: str
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
    description: Optional[str] = None
    start_at: datetime
    end_at: Optional[datetime] = None
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    categories: list[str] = []
    image_url: Optional[str] = None
    all_day: bool = False
    status: str
    sources: list[SourceRef] = []

    model_config = {"from_attributes": True}
