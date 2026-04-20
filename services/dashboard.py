from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import extract
from sqlmodel import Session, select, col, func

from i18n import _
from models.movement import Movement
from models.notification import Notification
from models.recurring import RecurringItem
from models.saving import Saving
from models.source import Source
from services.sources import get_balance, get_balances_batch


def get_dashboard_stats(session: Session) -> dict:
    from services import portfolios as portfolio_service

    today = date.today()
    sources = session.exec(select(Source)).all()

    # Net worth per currency (batch query instead of N+1)
    balances = get_balances_batch(session, list(sources))
    net_worth: dict[str, float] = defaultdict(float)
    for s in sources:
        balance = balances.get(s.id, s.starting_balance)
        net_worth[s.currency] = round(net_worth[s.currency] + balance, 2)

    # Add portfolio market value to net worth (grouped by portfolio base_currency).
    # Cash balance (from movements) and portfolio MTM (from holdings) are
    # independent assets — the sum is correct, not double-counted.
    portfolio_worth = portfolio_service.total_portfolio_value_by_currency(session)
    for cur, val in portfolio_worth.items():
        net_worth[cur] = round(net_worth[cur] + val, 2)

    # Counts
    source_count = len(sources)
    movement_count = session.exec(select(func.count(Movement.id))).one()
    unread_count = session.exec(
        select(func.count(Notification.id)).where(Notification.is_read == False)  # noqa: E712
    ).one()

    # Monthly income/expense per currency (current month, excluding transfers and individually excluded movements)
    first_of_month = today.replace(day=1)
    no_transfer = Movement.transfer_pair_id.is_(None)  # type: ignore
    not_excluded = Movement.exclude_from_stats == False  # noqa: E712
    base = [Movement.date >= first_of_month, no_transfer, not_excluded]

    # Per-currency totals (movements with a source)
    month_in_rows = session.exec(
        select(Source.currency, func.coalesce(func.sum(Movement.amount), 0))
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.direction == "in", *base)
        .group_by(Source.currency)
    ).all()
    month_out_rows = session.exec(
        select(Source.currency, func.coalesce(func.sum(Movement.amount), 0))
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.direction == "out", *base)
        .group_by(Source.currency)
    ).all()
    month_income: dict[str, float] = {cur: round(float(amt), 2) for cur, amt in month_in_rows}
    month_expense: dict[str, float] = {cur: round(float(amt), 2) for cur, amt in month_out_rows}

    # External subtotals (source_id is NULL — currency unknown)
    ext_in = session.exec(
        select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.direction == "in", *base,
            Movement.source_id.is_(None),  # type: ignore
        )
    ).one()
    ext_out = session.exec(
        select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.direction == "out", *base,
            Movement.source_id.is_(None),  # type: ignore
        )
    ).one()

    # Recent movements
    recent = session.exec(
        select(Movement).order_by(col(Movement.date).desc()).limit(5)
    ).all()

    # Upcoming recurring
    upcoming = session.exec(
        select(RecurringItem)
        .where(RecurringItem.next_due_date >= today)
        .order_by(col(RecurringItem.next_due_date))
        .limit(5)
    ).all()

    # Monthly savings
    month_savings_rows = session.exec(
        select(Saving.currency, func.coalesce(func.sum(Saving.amount), 0))
        .where(Saving.date >= first_of_month)
        .group_by(Saving.currency)
    ).all()
    month_savings = {cur: round(float(amt), 2) for cur, amt in month_savings_rows}

    return {
        "net_worth": dict(net_worth),
        "source_count": source_count,
        "movement_count": int(movement_count),
        "unread_notifications": int(unread_count),
        "month_income": month_income,
        "month_expense": month_expense,
        "month_income_ext": round(float(ext_in), 2),
        "month_expense_ext": round(float(ext_out), 2),
        "month_savings": month_savings,
        "recent_movements": recent,
        "upcoming_recurring": upcoming,
        "sources": sources,
    }


def get_monthly_movements(session: Session, direction: str) -> list[dict]:
    """Returns individual movements for the current month (non-transfer), with exclude status."""
    today = date.today()
    first_of_month = today.replace(day=1)
    movements = session.exec(
        select(Movement).where(
            Movement.direction == direction,
            Movement.date >= first_of_month,
            Movement.transfer_pair_id.is_(None),  # type: ignore
        ).order_by(col(Movement.date).desc())
    ).all()

    result = []
    for m in movements:
        source_name = _("external")
        if m.source_id:
            s = session.get(Source, m.source_id)
            if s:
                source_name = s.name
        result.append({
            "id": m.id,
            "source_name": source_name,
            "date": m.date.isoformat(),
            "amount": m.amount,
            "note": m.note,
            "exclude_from_stats": m.exclude_from_stats,
        })
    return result


def get_monthly_totals(session: Session) -> dict:
    """Returns income/expense totals per currency for the current month, excluding transfers and individually excluded movements."""
    today = date.today()
    first_of_month = today.replace(day=1)
    base = [
        Movement.date >= first_of_month,
        Movement.transfer_pair_id.is_(None),  # type: ignore
        Movement.exclude_from_stats == False,  # noqa: E712
    ]

    month_in_rows = session.exec(
        select(Source.currency, func.coalesce(func.sum(Movement.amount), 0))
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.direction == "in", *base)
        .group_by(Source.currency)
    ).all()
    month_out_rows = session.exec(
        select(Source.currency, func.coalesce(func.sum(Movement.amount), 0))
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.direction == "out", *base)
        .group_by(Source.currency)
    ).all()

    return {
        "month_income": {cur: round(float(amt), 2) for cur, amt in month_in_rows},
        "month_expense": {cur: round(float(amt), 2) for cur, amt in month_out_rows},
    }


def get_net_worth_history(session: Session, range_str: str = "all") -> dict:
    """Returns net worth over time, grouped by currency."""
    today = date.today()
    range_map = {
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
    }

    sources = session.exec(select(Source)).all()
    if not sources:
        return {}

    # Group sources by currency
    currency_sources: dict[str, list[Source]] = defaultdict(list)
    for s in sources:
        currency_sources[s.currency].append(s)

    result: dict[str, list[dict]] = {}

    for currency, src_list in currency_sources.items():
        source_ids = [s.id for s in src_list]
        starting_total = sum(s.starting_balance for s in src_list)

        query = (
            select(Movement)
            .where(col(Movement.source_id).in_(source_ids))
            .order_by(col(Movement.date))
        )

        if range_str in range_map:
            start = today - range_map[range_str]
            # Get prior balance
            prior_in = session.exec(
                select(func.coalesce(func.sum(Movement.amount), 0)).where(
                    col(Movement.source_id).in_(source_ids),
                    Movement.direction == "in",
                    Movement.date < start,
                )
            ).one()
            prior_out = session.exec(
                select(func.coalesce(func.sum(Movement.amount), 0)).where(
                    col(Movement.source_id).in_(source_ids),
                    Movement.direction == "out",
                    Movement.date < start,
                )
            ).one()
            running = round(starting_total + float(prior_in) - float(prior_out), 2)
            query = query.where(Movement.date >= start)
        else:
            running = starting_total

        movements = session.exec(query).all()
        history: list[dict] = []

        for m in movements:
            if m.direction == "in":
                running = round(running + m.amount, 2)
            else:
                running = round(running - m.amount, 2)
            history.append({"date": m.date.isoformat(), "balance": round(running, 2)})

        if not history:
            history.append({"date": today.isoformat(), "balance": round(running, 2)})

        result[currency] = history

    return result


def get_monthly_comparison(session: Session, months: int = 12) -> list[dict]:
    """Returns income/expense totals per month for the last N months, excluding transfers and excluded movements."""
    today = date.today()
    start_date = (today.replace(day=1) - timedelta(days=(months - 1) * 28)).replace(day=1)

    base = [
        Movement.date >= start_date,
        Movement.transfer_pair_id.is_(None),  # type: ignore
        Movement.exclude_from_stats == False,  # noqa: E712
    ]

    year_col = extract("year", Movement.date).label("y")
    month_col = extract("month", Movement.date).label("m")

    rows = session.exec(
        select(
            year_col,
            month_col,
            Movement.direction,
            func.sum(Movement.amount),
        )
        .where(*base)
        .group_by(year_col, month_col, Movement.direction)
        .order_by(year_col, month_col)
    ).all()

    # Build result keyed by YYYY-MM
    data: dict[str, dict] = {}
    for y, m, direction, total in rows:
        key = f"{int(y)}-{int(m):02d}"
        if key not in data:
            data[key] = {"month": key, "income": 0.0, "expense": 0.0}
        if direction == "in":
            data[key]["income"] = round(float(total), 2)
        else:
            data[key]["expense"] = round(float(total), 2)

    return list(data.values())
