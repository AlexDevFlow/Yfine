from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from schemas.budget import BudgetCreate, BudgetRead, BudgetUpdate
from services import budgets as budget_service

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("", response_model=list[BudgetRead])
def list_budgets(session: Session = Depends(get_session)):
    return budget_service.list_budgets(session)


@router.get("/status")
def budget_statuses(
    offset: int = Query(default=0),
    active_only: bool = Query(default=True),
    session: Session = Depends(get_session),
):
    return budget_service.list_budget_statuses(
        session, offset=offset, active_only=active_only
    )


@router.post("", response_model=BudgetRead, status_code=201)
def create_budget(data: BudgetCreate, session: Session = Depends(get_session)):
    return budget_service.create_budget(session, data)


@router.get("/{budget_id}", response_model=BudgetRead)
def get_budget(budget_id: int, session: Session = Depends(get_session)):
    return budget_service.get_budget(session, budget_id)


@router.get("/{budget_id}/status")
def budget_status(
    budget_id: int,
    offset: int = Query(default=0),
    session: Session = Depends(get_session),
):
    budget = budget_service.get_budget(session, budget_id)
    ref = budget_service.shift_period(budget.period, date.today(), offset)
    return budget_service.budget_status(session, budget, ref=ref)


@router.put("/{budget_id}", response_model=BudgetRead)
def update_budget(
    budget_id: int, data: BudgetUpdate, session: Session = Depends(get_session)
):
    return budget_service.update_budget(session, budget_id, data)


@router.delete("/{budget_id}", status_code=204)
def delete_budget(budget_id: int, session: Session = Depends(get_session)):
    budget_service.delete_budget(session, budget_id)
