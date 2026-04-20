from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from schemas.exchange_rate import ExchangeRateCreate, ExchangeRateRead, ExchangeRateUpdate
from services import exchange_rates as rate_service

router = APIRouter(prefix="/api/exchange-rates", tags=["exchange-rates"])


@router.get("", response_model=list[ExchangeRateRead])
def list_rates(session: Session = Depends(get_session)):
    return rate_service.list_rates(session)


@router.post("", response_model=ExchangeRateRead, status_code=201)
def set_rate(data: ExchangeRateCreate, session: Session = Depends(get_session)):
    return rate_service.set_rate(session, data)


@router.put("/{rate_id}", response_model=ExchangeRateRead)
def update_rate(rate_id: int, data: ExchangeRateUpdate, session: Session = Depends(get_session)):
    return rate_service.update_rate(session, rate_id, data)


@router.delete("/{rate_id}", status_code=204)
def delete_rate(rate_id: int, session: Session = Depends(get_session)):
    rate_service.delete_rate(session, rate_id)


@router.get("/convert")
def convert(
    amount: float = Query(...),
    from_currency: str = Query(..., alias="from"),
    to_currency: str = Query(..., alias="to"),
    session: Session = Depends(get_session),
):
    result = rate_service.convert(session, amount, from_currency.upper(), to_currency.upper())
    if result is None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={"detail": f"No exchange rate configured for {from_currency} -> {to_currency}"},
        )
    return {"amount": amount, "from": from_currency.upper(), "to": to_currency.upper(), "result": result}
