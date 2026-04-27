import uuid
from sqlalchemy import Boolean, Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from app.database import Base


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String, nullable=False)
    description = Column(Text)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True))
    venue_name = Column(String)
    venue_address = Column(String)
    categories = Column(ARRAY(String), default=[])
    image_url = Column(String)
    source_name = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    canonical_hash = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Source(Base):
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    scraper_type = Column(String, nullable=False)  # api, ical, html
    config = Column(JSONB)
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime(timezone=True))
    last_run_status = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
