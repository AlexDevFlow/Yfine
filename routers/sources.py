from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from schemas.source import SourceCreate, SourceRead, SourceUpdate
from services import portfolios as portfolio_service
from services import sources as source_service

router = APIRouter(prefix="/api/sources", tags=["sources"])


def _to_read(s, current_balance: float) -> SourceRead:
    """Build the API representation of a source with its computed balance."""
    return SourceRead(
        id=s.id,
        name=s.name,
        currency=s.currency,
        starting_balance=s.starting_balance,
        current_balance=current_balance,
        yield_rate=s.yield_rate,
        yield_period_months=s.yield_period_months,
        yield_next_date=s.yield_next_date,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


class MergeBody(BaseModel):
    from_source_id: int
    into_source_id: int


@router.get("", response_model=list[SourceRead])
def list_sources(
    skip: int = 0, limit: int = 50, session: Session = Depends(get_session)
):
    items = source_service.list_sources(session, skip, limit)
    balances = source_service.get_balances_batch(session, items)
    return [
        _to_read(s, balances.get(s.id, s.starting_balance))
        for s in items
    ]


@router.post("", response_model=SourceRead, status_code=201)
def create_source(data: SourceCreate, session: Session = Depends(get_session)):
    s = source_service.create_source(session, data)
    return _to_read(s, s.starting_balance)


@router.get("/{source_id}", response_model=SourceRead)
def get_source(source_id: int, session: Session = Depends(get_session)):
    s = source_service.get_source(session, source_id)
    balance = source_service.get_balance(session, s.id)
    return _to_read(s, balance)


@router.put("/{source_id}", response_model=SourceRead)
def update_source(
    source_id: int, data: SourceUpdate, session: Session = Depends(get_session)
):
    s = source_service.update_source(session, source_id, data)
    balance = source_service.get_balance(session, s.id)
    return _to_read(s, balance)


@router.get("/{source_id}/dependencies")
def get_dependencies(source_id: int, session: Session = Depends(get_session)):
    return source_service.get_source_dependencies(session, source_id)


@router.get("/{source_id}/portfolios")
def list_portfolios_by_source(source_id: int, session: Session = Depends(get_session)):
    source_service.get_source(session, source_id)
    return portfolio_service.list_portfolios_by_source(session, source_id)


@router.delete("/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    action: str = Query(default="delete_all"),
    session: Session = Depends(get_session),
):
    source_service.delete_source(session, source_id, action=action)


@router.post("/merge", response_model=SourceRead)
def merge_sources(body: MergeBody, session: Session = Depends(get_session)):
    s = source_service.merge_sources(session, body.from_source_id, body.into_source_id)
    balance = source_service.get_balance(session, s.id)
    return _to_read(s, balance)


@router.get("/{source_id}/history")
def get_source_history(
    source_id: int,
    range: str = Query(default="all", alias="range"),
    session: Session = Depends(get_session),
):
    return source_service.get_balance_history(session, source_id, range)


@router.post("/{source_id}/exclude")
def toggle_exclude_from_stats(source_id: int, session: Session = Depends(get_session)):
    s = source_service.toggle_exclude_from_stats(session, source_id)
    return {"id": s.id, "exclude_from_stats": s.exclude_from_stats}
