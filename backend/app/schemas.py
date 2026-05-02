from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


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
    categories: list[str] = []
    image_url: Optional[str] = None
    all_day: bool = False
    status: str
    sources: list[SourceRef] = []

    model_config = {"from_attributes": True}
