import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Event
from app.schemas import EventResponse

router = APIRouter(prefix="/events", tags=["events"])


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
