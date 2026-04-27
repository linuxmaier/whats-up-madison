import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

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
    canonical_hash = Column(String, unique=True, nullable=False)
    status = Column(String, nullable=False, server_default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sources = relationship("EventSource", back_populates="event", cascade="all, delete-orphan")


class EventSource(Base):
    __tablename__ = "event_sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    source_name = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    event = relationship("Event", back_populates="sources")

    __table_args__ = (UniqueConstraint("event_id", "source_name"),)


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
