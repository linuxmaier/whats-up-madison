import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event
from app.schemas import EventResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventResponse])
def get_events(
    date: Optional[datetime.date] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Event)
    if date:
        query = query.filter(
            func.date(Event.start_at) <= date,
            func.date(func.coalesce(Event.end_at, Event.start_at)) >= date,
        )
    return query.order_by(Event.start_at).all()
