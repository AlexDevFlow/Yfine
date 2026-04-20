from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from models.source import Source
from schemas.recurring import RecurringCreate, RecurringRead, RecurringUpdate
from services import recurring as recurring_service


class ApplyBody(BaseModel):
    amount: Optional[float] = None
    note: Optional[str] = None

router = APIRouter(prefix="/api/recurring", tags=["recurring"])


def _to_read(session: Session, item) -> RecurringRead:
    source_name = None
    if item.source_id:
        source = session.get(Source, item.source_id)
        source_name = source.name if source else None
    return RecurringRead(
        id=item.id,
        name=item.name,
        amount=item.amount,
        direction=item.direction,
        currency=item.currency,
        frequency=item.frequency,
        start_date=item.start_date,
        end_date=item.end_date,
        source_id=item.source_id,
        source_name=source_name,
        apply_mode=item.apply_mode,
        next_due_date=item.next_due_date,
        alert_days_before=item.alert_days_before,
        alert_if_insufficient=item.alert_if_insufficient,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("", response_model=list[RecurringRead])
def list_recurring(
    skip: int = 0, limit: int = 50, session: Session = Depends(get_session)
):
    items = recurring_service.list_recurring(session, skip, limit)
    return [_to_read(session, i) for i in items]


@router.post("", response_model=RecurringRead, status_code=201)
def create_recurring(data: RecurringCreate, session: Session = Depends(get_session)):
    item = recurring_service.create_recurring(session, data)
    return _to_read(session, item)


@router.get("/{recurring_id}", response_model=RecurringRead)
def get_recurring(recurring_id: int, session: Session = Depends(get_session)):
    item = recurring_service.get_recurring(session, recurring_id)
    return _to_read(session, item)


@router.put("/{recurring_id}", response_model=RecurringRead)
def update_recurring(
    recurring_id: int, data: RecurringUpdate, session: Session = Depends(get_session)
):
    item = recurring_service.update_recurring(session, recurring_id, data)
    return _to_read(session, item)


@router.delete("/{recurring_id}", status_code=204)
def delete_recurring(recurring_id: int, session: Session = Depends(get_session)):
    recurring_service.delete_recurring(session, recurring_id)


@router.post("/{recurring_id}/apply", response_model=RecurringRead)
def apply_recurring(
    recurring_id: int,
    body: ApplyBody = ApplyBody(),
    session: Session = Depends(get_session),
):
    item = recurring_service.apply_recurring_by_id(
        session, recurring_id, override_amount=body.amount, note=body.note
    )
    return _to_read(session, item)
