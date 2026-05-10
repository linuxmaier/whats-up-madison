import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Event
from app.schemas import EventResponse

router = APIRouter(prefix="/events", tags=["events"])

SEARCH_RESULT_LIMIT = 200


@router.get("", response_model=list[EventResponse])
def get_events(
    date: datetime.date,
    db: Session = Depends(get_db),
):
    return (
        db.query(Event)
        .options(joinedload(Event.sources))
        .filter(
            Event.status == "active",
            func.date(func.timezone("America/Chicago", Event.start_at)) <= date,
            func.date(func.timezone("America/Chicago", func.coalesce(Event.end_at, Event.start_at))) >= date,
        )
        .order_by(Event.start_at)
        .all()
    )


@router.get("/search", response_model=list[EventResponse])
def search_events(
    q: str = "",
    db: Session = Depends(get_db),
):
    query = q.strip()
    if not query:
        return []

    pattern = f"%{query}%"

    return (
        db.query(Event)
        .options(joinedload(Event.sources))
        .filter(
            Event.status == "active",
            func.date(
                func.timezone("America/Chicago", func.coalesce(Event.end_at, Event.start_at))
            )
            >= func.date(func.timezone("America/Chicago", func.now())),
            or_(
                Event.title.ilike(pattern),
                Event.description.ilike(pattern),
                Event.venue_name.ilike(pattern),
            ),
        )
        .order_by(Event.start_at)
        .limit(SEARCH_RESULT_LIMIT)
        .all()
    )
