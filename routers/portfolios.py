from fastapi import APIRouter, Depends
from sqlmodel import Session

from database import get_session
from schemas.portfolio import (
    HoldingCreate,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioUpdate,
)
from services import portfolios as portfolio_service
from services import prices as price_service

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


@router.get("")
def list_portfolios(session: Session = Depends(get_session)):
    items = portfolio_service.list_portfolios(session)
    return [portfolio_service.summarize_portfolio(session, p) for p in items]


@router.post("", status_code=201)
def create_portfolio(data: PortfolioCreate, session: Session = Depends(get_session)):
    p = portfolio_service.create_portfolio(session, data)
    return portfolio_service.summarize_portfolio(session, p)


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: int, session: Session = Depends(get_session)):
    p = portfolio_service.get_portfolio(session, portfolio_id)
    return portfolio_service.summarize_portfolio(session, p)


@router.put("/{portfolio_id}")
def update_portfolio(portfolio_id: int, data: PortfolioUpdate, session: Session = Depends(get_session)):
    p = portfolio_service.update_portfolio(session, portfolio_id, data)
    return portfolio_service.summarize_portfolio(session, p)


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: int, session: Session = Depends(get_session)):
    portfolio_service.delete_portfolio(session, portfolio_id)


@router.get("/{portfolio_id}/history")
def get_portfolio_history(
    portfolio_id: int,
    range: str = "30d",
    session: Session = Depends(get_session),
):
    portfolio_service.get_portfolio(session, portfolio_id)
    return portfolio_service.portfolio_value_history(session, portfolio_id, range)


# --- Holdings ---


@router.post("/{portfolio_id}/holdings", status_code=201)
def create_holding(portfolio_id: int, data: HoldingCreate, session: Session = Depends(get_session)):
    if data.portfolio_id != portfolio_id:
        data = data.model_copy(update={"portfolio_id": portfolio_id})
    h = portfolio_service.create_holding(session, data)
    return portfolio_service.enrich_holding(h)


@router.put("/holdings/{holding_id}")
def update_holding(holding_id: int, data: HoldingUpdate, session: Session = Depends(get_session)):
    h = portfolio_service.update_holding(session, holding_id, data)
    return portfolio_service.enrich_holding(h)


@router.delete("/holdings/{holding_id}", status_code=204)
def delete_holding(holding_id: int, session: Session = Depends(get_session)):
    portfolio_service.delete_holding(session, holding_id)


# --- Price refresh (manual trigger) ---


@router.post("/refresh-prices")
def refresh_prices(session: Session = Depends(get_session)):
    if not price_service.are_prices_enabled(session):
        return {"updated": 0, "enabled": False}
    updated = price_service.refresh_all_holdings(session)
    return {"updated": updated, "enabled": True}


@router.post("/holdings/{holding_id}/refresh-price")
def refresh_holding_price(holding_id: int, session: Session = Depends(get_session)):
    if not price_service.are_prices_enabled(session):
        return {"updated": False, "enabled": False}
    h = portfolio_service.get_holding(session, holding_id)
    ok = price_service.refresh_holding_price(h)
    if ok:
        session.add(h)
        portfolio_service.upsert_price_snapshot(session, h)
        session.commit()
        session.refresh(h)
    return {"updated": ok, "enabled": True, "holding": portfolio_service.enrich_holding(h)}
