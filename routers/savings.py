from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from schemas.saving import SavingCreate, SavingRead, SavingUpdate
from services import savings as saving_service
from services import savings_fund as fund_service
from services import savings_migration as wizard_service

router = APIRouter(prefix="/api/savings", tags=["savings"])


class _WizardRun(BaseModel):
    mode: str  # "movements" | "starting_balance" | "discard"
    unified_source_id: Optional[int] = None


def _as_read(view: dict) -> SavingRead:
    return SavingRead(**view)


@router.get("")
def list_savings(
    skip: int = 0,
    limit: int = 50,
    currency: str | None = None,
    tag_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    views = saving_service.list_savings(
        session, skip, limit,
        currency=currency, tag_id=tag_id,
        date_from=date_from, date_to=date_to,
    )
    return [_as_read(v) for v in views]


@router.get("/total")
def total_saved(
    currency: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    session: Session = Depends(get_session),
):
    if date_from and date_to:
        return saving_service.total_saved_period(session, date_from, date_to)
    return saving_service.total_saved(session, currency=currency)


@router.get("/trend")
def savings_trend(
    months: int = Query(default=12, ge=1, le=36),
    session: Session = Depends(get_session),
):
    return saving_service.monthly_trend(session, months)


@router.get("/fund-balance")
def savings_fund_balance(
    months: int = Query(default=12, ge=1, le=36),
    session: Session = Depends(get_session),
):
    """Running balance of every savings fund at end-of-month — tab 2 chart."""
    return saving_service.fund_balance_trend(session, months)


@router.get("/by-month/{year_month}")
def savings_by_month(
    year_month: str,
    session: Session = Depends(get_session),
):
    """Get all savings for a given month (YYYY-MM)."""
    from datetime import date as date_cls
    from calendar import monthrange
    parts = year_month.split("-")
    year, month = int(parts[0]), int(parts[1])
    first = date_cls(year, month, 1)
    last = date_cls(year, month, monthrange(year, month)[1])
    views = saving_service.list_savings(session, skip=0, limit=500, date_from=first, date_to=last)
    return [
        {
            "id": v["id"],
            "date": v["date"].isoformat(),
            "amount": v["amount"],
            "currency": v["currency"],
            "description": v["description"],
            "note": v["note"],
            "tags": v["tags"],
        }
        for v in views
    ]


@router.post("", status_code=201)
def create_saving(data: SavingCreate, session: Session = Depends(get_session)):
    return _as_read(saving_service.create_saving(session, data))


@router.get("/{saving_id}")
def get_saving(saving_id: int, session: Session = Depends(get_session)):
    return _as_read(saving_service.get_saving(session, saving_id))


@router.put("/{saving_id}")
def update_saving(saving_id: int, data: SavingUpdate, session: Session = Depends(get_session)):
    return _as_read(saving_service.update_saving(session, saving_id, data))


@router.delete("/{saving_id}", status_code=204)
def delete_saving(saving_id: int, session: Session = Depends(get_session)):
    saving_service.delete_saving(session, saving_id)


# --- Savings fund ---


@router.get("/funds/list")
def list_funds(session: Session = Depends(get_session)):
    funds = fund_service.list_funds(session)
    return [
        {
            "id": f.id,
            "name": f.name,
            "currency": f.currency,
            "hidden_from_sources": f.hidden_from_sources,
        }
        for f in funds
    ]


@router.put("/funds/{fund_id}/visibility")
def toggle_fund_visibility(
    fund_id: int,
    payload: dict = Body(...),
    session: Session = Depends(get_session),
):
    from fastapi import HTTPException
    from models.source import Source

    fund = session.get(Source, fund_id)
    if not fund or not fund.is_savings_fund:
        raise HTTPException(status_code=404, detail="Fund not found")
    fund.hidden_from_sources = bool(payload.get("hidden_from_sources", fund.hidden_from_sources))
    from datetime import datetime as _dt
    fund.updated_at = _dt.utcnow()
    session.add(fund)
    session.commit()
    return {"id": fund.id, "hidden_from_sources": fund.hidden_from_sources}


# --- Migration wizard ---


@router.get("/wizard/status")
def wizard_status(session: Session = Depends(get_session)):
    if not wizard_service.needs_wizard(session):
        return {"needed": False}
    return {"needed": True, "preview": wizard_service.preview(session)}


@router.post("/wizard/run")
def wizard_run(body: _WizardRun, session: Session = Depends(get_session)):
    return wizard_service.run(session, body.mode, body.unified_source_id)
