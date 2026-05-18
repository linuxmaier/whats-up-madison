import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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
    latitude = Column(Float)
    longitude = Column(Float)
    categories = Column(ARRAY(String), default=[])
    all_day = Column(Boolean, nullable=False, server_default="false")
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


class VenueGeocode(Base):
    __tablename__ = "venue_geocodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lookup_key = Column(String, unique=True, nullable=False, index=True)
    latitude = Column(Float)
    longitude = Column(Float)
    display_name = Column(String)
    status = Column(String, nullable=False)  # success | not_found | error
    geocoder = Column(String, nullable=False, server_default="nominatim")
    geocoded_at = Column(DateTime(timezone=True), server_default=func.now())
    attempts = Column(Integer, nullable=False, server_default="1")


class IsthmusDetail(Base):
    __tablename__ = "isthmus_details"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lookup_key = Column(String, unique=True, nullable=False, index=True)
    # Hash of RSS-visible fields (parsed name | venue_name | RSS description).
    # When this changes for a given lookup_key, the cache is invalidated and the
    # detail page is re-fetched. Times are intentionally excluded — they vary
    # per occurrence for recurring events but don't change detail-page content.
    rss_signature = Column(String, nullable=False)
    categories = Column(ARRAY(String), nullable=False, server_default="{}")
    venue_address = Column(String)
    description = Column(Text)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
