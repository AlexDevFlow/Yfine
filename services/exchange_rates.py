from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select

from models.exchange_rate import ExchangeRate
from schemas.exchange_rate import ExchangeRateCreate, ExchangeRateUpdate


def list_rates(session: Session) -> list[ExchangeRate]:
    return list(session.exec(select(ExchangeRate)).all())


def get_rate(session: Session, from_currency: str, to_currency: str) -> ExchangeRate | None:
    return session.exec(
        select(ExchangeRate).where(
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
        )
    ).first()


def get_rate_by_id(session: Session, rate_id: int) -> ExchangeRate:
    rate = session.get(ExchangeRate, rate_id)
    if not rate:
        raise HTTPException(status_code=404, detail="Exchange rate not found")
    return rate


def set_rate(session: Session, data: ExchangeRateCreate) -> ExchangeRate:
    """Create or update an exchange rate pair."""
    if data.from_currency == data.to_currency:
        raise HTTPException(status_code=422, detail="from_currency and to_currency must be different")

    existing = get_rate(session, data.from_currency, data.to_currency)
    if existing:
        existing.rate = data.rate
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    rate = ExchangeRate(
        from_currency=data.from_currency,
        to_currency=data.to_currency,
        rate=data.rate,
    )
    session.add(rate)
    session.commit()
    session.refresh(rate)
    return rate


def update_rate(session: Session, rate_id: int, data: ExchangeRateUpdate) -> ExchangeRate:
    rate = get_rate_by_id(session, rate_id)
    rate.rate = data.rate
    rate.updated_at = datetime.utcnow()
    session.add(rate)
    session.commit()
    session.refresh(rate)
    return rate


def delete_rate(session: Session, rate_id: int) -> None:
    rate = get_rate_by_id(session, rate_id)
    session.delete(rate)
    session.commit()


def convert(session: Session, amount: float, from_currency: str, to_currency: str) -> float | None:
    """Convert an amount between currencies. Returns None if no rate is configured."""
    if from_currency == to_currency:
        return amount
    rate = get_rate(session, from_currency, to_currency)
    if rate:
        return round(amount * rate.rate, 2)
    # Try reverse
    reverse = get_rate(session, to_currency, from_currency)
    if reverse and reverse.rate != 0:
        return round(amount / reverse.rate, 2)
    return None


def get_rates_map(session: Session) -> dict[tuple[str, str], float]:
    """Return all rates as a dict for batch conversions."""
    rates = list_rates(session)
    result = {}
    for r in rates:
        result[(r.from_currency, r.to_currency)] = r.rate
        if r.rate != 0:
            result[(r.to_currency, r.from_currency)] = round(1.0 / r.rate, 6)
    return result
