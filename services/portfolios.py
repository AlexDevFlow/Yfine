from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select, func, col

from models.portfolio import Holding, HoldingPriceSnapshot, Portfolio
from models.source import Source
from schemas.portfolio import (
    HoldingCreate,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioUpdate,
)
from services import prices as price_service


# --- Portfolios ---


def list_portfolios(session: Session) -> list[Portfolio]:
    return list(session.exec(select(Portfolio).order_by(Portfolio.name)).all())


def get_portfolio(session: Session, portfolio_id: int) -> Portfolio:
    p = session.get(Portfolio, portfolio_id)
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return p


def _require_source(session: Session, source_id: int) -> Source:
    src = session.get(Source, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return src


def create_portfolio(session: Session, data: PortfolioCreate) -> Portfolio:
    _require_source(session, data.source_id)
    p = Portfolio(**data.model_dump())
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def update_portfolio(session: Session, portfolio_id: int, data: PortfolioUpdate) -> Portfolio:
    p = get_portfolio(session, portfolio_id)
    payload = data.model_dump(exclude_unset=True)
    if "source_id" in payload:
        if payload["source_id"] is None:
            raise HTTPException(status_code=400, detail="source_id cannot be null")
        _require_source(session, payload["source_id"])
    for k, v in payload.items():
        setattr(p, k, v)
    p.updated_at = datetime.utcnow()
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def delete_portfolio(session: Session, portfolio_id: int) -> None:
    p = get_portfolio(session, portfolio_id)
    # Delete holdings explicitly — the DB-level cascade requires PRAGMA
    # foreign_keys=ON which SQLite doesn't enable by default.
    for h in list_holdings(session, portfolio_id):
        _delete_snapshots_for_holding(session, h.id)
        session.delete(h)
    session.delete(p)
    session.commit()


# --- Holdings ---


def list_holdings(session: Session, portfolio_id: int) -> list[Holding]:
    return list(
        session.exec(
            select(Holding)
            .where(Holding.portfolio_id == portfolio_id)
            .order_by(Holding.asset_class, Holding.symbol)
        ).all()
    )


def get_holding(session: Session, holding_id: int) -> Holding:
    h = session.get(Holding, holding_id)
    if not h:
        raise HTTPException(status_code=404, detail="Holding not found")
    return h


def create_holding(session: Session, data: HoldingCreate) -> Holding:
    # Validate portfolio exists
    get_portfolio(session, data.portfolio_id)
    h = Holding(**data.model_dump())
    session.add(h)
    session.commit()
    session.refresh(h)
    # Try to enrich price once on creation (opt-in)
    if price_service.are_prices_enabled(session) and not h.manual_price and h.last_price is None:
        if price_service.refresh_holding_price(h):
            session.add(h)
            upsert_price_snapshot(session, h)
            session.commit()
            session.refresh(h)
    # If the user provided a manual price up front, snapshot it too
    if h.manual_price and h.last_price is not None:
        upsert_price_snapshot(session, h)
        session.commit()
        session.refresh(h)
    return h


def update_holding(session: Session, holding_id: int, data: HoldingUpdate) -> Holding:
    h = get_holding(session, holding_id)
    payload = data.model_dump(exclude_unset=True)
    # When manual_price is toggled OFF, clear the user-set price so the next
    # automatic refresh takes over cleanly.
    was_manual = h.manual_price
    for k, v in payload.items():
        setattr(h, k, v)
    h.updated_at = datetime.utcnow()
    if was_manual and payload.get("manual_price") is False:
        h.last_price = None
        h.last_price_at = None
    session.add(h)
    # Snapshot when user sets / updates a manual price
    if h.manual_price and h.last_price is not None and "last_price" in payload:
        upsert_price_snapshot(session, h)
    session.commit()
    session.refresh(h)
    return h


def _delete_snapshots_for_holding(session: Session, holding_id: int) -> None:
    """Remove price snapshots for a holding. SQLite's FK CASCADE only fires
    when PRAGMA foreign_keys=ON, which Yfine doesn't enable — so we clean up
    explicitly to avoid orphan rows."""
    snaps = session.exec(
        select(HoldingPriceSnapshot).where(HoldingPriceSnapshot.holding_id == holding_id)
    ).all()
    for s in snaps:
        session.delete(s)


def delete_holding(session: Session, holding_id: int) -> None:
    h = get_holding(session, holding_id)
    _delete_snapshots_for_holding(session, h.id)
    session.delete(h)
    session.commit()


# --- Valuation helpers ---


def enrich_holding(h: Holding) -> dict:
    cost_basis = round(h.quantity * h.avg_cost, 2)
    market_value = None
    pnl = None
    pnl_pct = None
    if h.last_price is not None:
        market_value = round(h.quantity * h.last_price, 2)
        pnl = round(market_value - cost_basis, 2)
        pnl_pct = round((pnl / cost_basis * 100.0), 2) if cost_basis else 0.0
    return {
        "id": h.id,
        "portfolio_id": h.portfolio_id,
        "asset_class": h.asset_class,
        "symbol": h.symbol,
        "display_name": h.display_name,
        "quantity": h.quantity,
        "avg_cost": h.avg_cost,
        "currency": h.currency,
        "last_price": h.last_price,
        "last_price_at": h.last_price_at.isoformat() if h.last_price_at else None,
        "manual_price": h.manual_price,
        "note": h.note,
        "cost_basis": cost_basis,
        "market_value": market_value,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
    }


def summarize_portfolio(session: Session, portfolio: Portfolio) -> dict:
    holdings = list_holdings(session, portfolio.id)
    enriched = [enrich_holding(h) for h in holdings]
    total_cost = round(sum((e["cost_basis"] or 0.0) for e in enriched), 2)
    total_value = round(
        sum((e["market_value"] if e["market_value"] is not None else e["cost_basis"] or 0.0) for e in enriched),
        2,
    )
    pnl = round(total_value - total_cost, 2)
    pnl_pct = round((pnl / total_cost * 100.0), 2) if total_cost else 0.0
    source = session.get(Source, portfolio.source_id) if portfolio.source_id else None
    return {
        "id": portfolio.id,
        "name": portfolio.name,
        "kind": portfolio.kind,
        "base_currency": portfolio.base_currency,
        "source_id": portfolio.source_id,
        "source_name": source.name if source else None,
        "note": portfolio.note,
        "created_at": portfolio.created_at,
        "updated_at": portfolio.updated_at,
        "holdings_count": len(enriched),
        "total_cost": total_cost,
        "total_value": total_value,
        "total_pnl": pnl,
        "total_pnl_pct": pnl_pct,
        "holdings": enriched,
    }


def list_portfolios_by_source(session: Session, source_id: int) -> list[dict]:
    """Return summarized portfolios for a given source, ordered by name."""
    portfolios = list(
        session.exec(
            select(Portfolio)
            .where(Portfolio.source_id == source_id)
            .order_by(Portfolio.name)
        ).all()
    )
    return [summarize_portfolio(session, p) for p in portfolios]


def get_counts(session: Session) -> dict:
    p_count = int(session.exec(select(func.count(Portfolio.id))).one() or 0)
    h_count = int(session.exec(select(func.count(Holding.id))).one() or 0)
    return {"portfolios": p_count, "holdings": h_count}


def portfolio_value_by_source(session: Session) -> dict[int, dict[str, float]]:
    """Return total market value of portfolios, grouped by source_id.

    Every portfolio belongs to a source (source_id is NOT NULL). Returns:
        { source_id: { currency: value } }
    where `currency` is the portfolio's base_currency.
    """
    portfolios = list(session.exec(select(Portfolio)).all())
    if not portfolios:
        return {}
    result: dict[int, dict[str, float]] = {}
    for p in portfolios:
        summary = summarize_portfolio(session, p)
        val = summary["total_value"]
        if not val:
            continue
        bucket = result.setdefault(p.source_id, {})
        bucket[p.base_currency] = round(bucket.get(p.base_currency, 0.0) + val, 2)
    return result


def upsert_price_snapshot(session: Session, holding: Holding, snapshot_date: Optional[date] = None) -> None:
    """Store (or replace) today's price for a holding so history charts can render it later.

    Called from the price refresh paths. Silently does nothing if the holding has no
    `last_price` (e.g. auto-refresh failed, no manual price set).
    """
    if holding.last_price is None or holding.id is None:
        return
    d = snapshot_date or date.today()
    existing = session.exec(
        select(HoldingPriceSnapshot).where(
            HoldingPriceSnapshot.holding_id == holding.id,
            HoldingPriceSnapshot.date == d,
        )
    ).first()
    if existing is not None:
        if existing.price != holding.last_price:
            existing.price = holding.last_price
            session.add(existing)
    else:
        session.add(HoldingPriceSnapshot(
            holding_id=holding.id,
            date=d,
            price=holding.last_price,
        ))


def portfolio_value_by_source_over_time(
    session: Session, source_id: int, dates: list[date]
) -> dict[date, float]:
    """Return market value of portfolios linked to `source_id` at each date.

    For each (holding, date) pair we use the most recent snapshot ≤ date; if no
    snapshot exists for that holding yet, we fall back to avg_cost (so the line
    is continuous instead of dropping to zero). Holdings created *after* a date
    contribute zero for that date. Values are summed across holdings whose
    portfolio.base_currency equals the source's currency — other currencies are
    excluded (same rule as the per-source card).
    """
    if not dates:
        return {}
    source = session.get(Source, source_id)
    if source is None:
        return {d: 0.0 for d in dates}
    # Pull all candidate holdings + their portfolios in one query
    rows = list(session.exec(
        select(Holding, Portfolio)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.source_id == source_id)
        .where(Portfolio.base_currency == source.currency)
    ).all())
    if not rows:
        return {d: 0.0 for d in dates}

    holding_ids = [h.id for h, _ in rows]
    snapshots = list(session.exec(
        select(HoldingPriceSnapshot)
        .where(col(HoldingPriceSnapshot.holding_id).in_(holding_ids))
        .order_by(col(HoldingPriceSnapshot.holding_id), col(HoldingPriceSnapshot.date))
    ).all())
    snaps_by_h: dict[int, list[HoldingPriceSnapshot]] = {}
    for s in snapshots:
        snaps_by_h.setdefault(s.holding_id, []).append(s)

    def _price_on(h: Holding, d: date) -> float:
        seq = snaps_by_h.get(h.id, [])
        # latest snapshot with snapshot.date <= d
        chosen = None
        for s in seq:
            if s.date <= d:
                chosen = s
            else:
                break
        if chosen is not None:
            return chosen.price
        return h.avg_cost  # fallback

    out: dict[date, float] = {}
    for d in dates:
        total = 0.0
        for h, _p in rows:
            total += h.quantity * _price_on(h, d)
        out[d] = round(total, 2)
    return out


def portfolio_value_history(
    session: Session, portfolio_id: int, range_str: str = "30d"
) -> list[dict]:
    """Return [{date, value}] for a portfolio's total market value over time.

    Uses HoldingPriceSnapshot rows: for each calendar day in the range, for
    each holding, pick the most recent snapshot ≤ that day (fallback: avg_cost).
    Dates without any movement are still included so the line is continuous.
    """
    from datetime import timedelta
    p = session.get(Portfolio, portfolio_id)
    if p is None:
        return []
    range_map = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}
    days = range_map.get(range_str, 30)
    today = date.today()
    start = today - timedelta(days=days)

    holdings = list(session.exec(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    ).all())
    if not holdings:
        return []

    holding_ids = [h.id for h in holdings]
    snapshots = list(session.exec(
        select(HoldingPriceSnapshot)
        .where(col(HoldingPriceSnapshot.holding_id).in_(holding_ids))
        .order_by(col(HoldingPriceSnapshot.holding_id), col(HoldingPriceSnapshot.date))
    ).all())
    snaps_by_h: dict[int, list[HoldingPriceSnapshot]] = {}
    for s in snapshots:
        snaps_by_h.setdefault(s.holding_id, []).append(s)

    def _price_on(h: Holding, d: date) -> float:
        seq = snaps_by_h.get(h.id, [])
        chosen = None
        for s in seq:
            if s.date <= d:
                chosen = s
            else:
                break
        if chosen is not None:
            return chosen.price
        return h.avg_cost

    # Build daily points for the requested window. Keep it coarse: one point
    # per day between first relevant snapshot (or start) and today.
    first_snapshot_date = min((s.date for s in snapshots), default=today)
    window_start = max(start, min(first_snapshot_date, start))
    points: list[dict] = []
    d = window_start
    while d <= today:
        total = sum(h.quantity * _price_on(h, d) for h in holdings)
        points.append({"date": d.isoformat(), "value": round(total, 2)})
        d += timedelta(days=1)
    return points


def total_portfolio_value_by_currency(session: Session) -> dict[str, float]:
    """Sum of market value of ALL portfolios grouped by their base_currency."""
    portfolios = list(session.exec(select(Portfolio)).all())
    totals: dict[str, float] = {}
    for p in portfolios:
        summary = summarize_portfolio(session, p)
        val = summary["total_value"]
        if not val:
            continue
        totals[p.base_currency] = round(totals.get(p.base_currency, 0.0) + val, 2)
    return totals
