from datetime import datetime, date, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select, func, col  # noqa: F401 — col used in get_balances_batch

from models.movement import Movement, MovementTag
from models.notification import Notification
from models.source import Source
from schemas.source import SourceCreate, SourceUpdate


def list_sources(
    session: Session,
    skip: int = 0,
    limit: int = 50,
    include_hidden: bool = True,
) -> list[Source]:
    q = select(Source)
    if not include_hidden:
        q = q.where(Source.hidden_from_sources == False)  # noqa: E712
    return list(session.exec(q.offset(skip).limit(limit)).all())


def get_source(session: Session, source_id: int) -> Source:
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def create_source(session: Session, data: SourceCreate) -> Source:
    source = Source(**data.model_dump())
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def update_source(session: Session, source_id: int, data: SourceUpdate) -> Source:
    source = get_source(session, source_id)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(source, key, value)
    source.updated_at = datetime.utcnow()
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def get_source_dependencies(session: Session, source_id: int) -> dict:
    """Return counts of entities linked to this source."""
    from models.recurring import RecurringItem
    from models.portfolio import Portfolio
    get_source(session, source_id)  # validate exists
    movement_count = session.exec(
        select(func.count(Movement.id)).where(Movement.source_id == source_id)
    ).one()
    recurring_count = session.exec(
        select(func.count(RecurringItem.id)).where(RecurringItem.source_id == source_id)
    ).one()
    portfolio_count = session.exec(
        select(func.count(Portfolio.id)).where(Portfolio.source_id == source_id)
    ).one()
    return {
        "movement_count": int(movement_count),
        "recurring_count": int(recurring_count),
        "portfolio_count": int(portfolio_count),
    }


def delete_source(session: Session, source_id: int, action: str = "delete_all") -> None:
    """Delete a source with different strategies for linked data.

    Actions:
      - delete_all: cascade delete all movements + recurring + portfolios (default)
      - move_to:<target_id>: reassign movements + recurring + portfolios to target
      - make_external: set movements source_id to NULL, delete recurring.
        Rejected if the source has portfolios (portfolios must belong to a source).
    """
    from models.goal import Goal
    from models.recurring import RecurringItem
    from models.portfolio import Holding, HoldingPriceSnapshot, Portfolio

    source = get_source(session, source_id)

    # Enforce the RESTRICT intent on goals.source_id — SQLite's FK is off so
    # the DB won't block us. Blocking the delete is safer than orphaning the
    # goal (which would misreport allocated_amount against a missing fund).
    blocking_goal = session.exec(
        select(Goal).where(Goal.source_id == source_id, Goal.status == "active")
    ).first()
    if blocking_goal:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Source is used by active goal '{blocking_goal.name}'. "
                "Close or delete the goal before deleting the source."
            ),
        )

    portfolios = session.exec(
        select(Portfolio).where(Portfolio.source_id == source_id)
    ).all()

    if action.startswith("move_to:"):
        target_id = int(action.split(":")[1])
        target = get_source(session, target_id)
        # Reassign movements
        movements = session.exec(
            select(Movement).where(Movement.source_id == source_id)
        ).all()
        for m in movements:
            m.source_id = target_id
            session.add(m)
        # Reassign recurring
        recurring = session.exec(
            select(RecurringItem).where(RecurringItem.source_id == source_id)
        ).all()
        for r in recurring:
            r.source_id = target_id
            session.add(r)
        # Reassign portfolios
        for p in portfolios:
            p.source_id = target_id
            session.add(p)
        # Add source's starting_balance to target
        target.starting_balance += source.starting_balance
        session.add(target)

    elif action == "make_external":
        if portfolios:
            raise HTTPException(
                status_code=400,
                detail="cannot_make_external_with_portfolios",
            )
        # Set movements to external (null source_id)
        movements = session.exec(
            select(Movement).where(Movement.source_id == source_id)
        ).all()
        for m in movements:
            m.source_id = None
            session.add(m)
        # Delete recurring (can't be external)
        recurring = session.exec(
            select(RecurringItem).where(RecurringItem.source_id == source_id)
        ).all()
        for r in recurring:
            session.delete(r)

    else:  # delete_all
        from models.goal import GoalAllocation
        from models.movement import MovementAttachment
        from services import attachments as attachment_service

        def _purge(mid: int) -> None:
            for link in session.exec(
                select(MovementTag).where(MovementTag.movement_id == mid)
            ).all():
                session.delete(link)
            # SQLite PRAGMA foreign_keys is off — cascade allocations manually
            # or close_goal later can re-bind an orphan to a fresh movement
            # (ID reuse) and wipe the refund.
            for alloc in session.exec(
                select(GoalAllocation).where(GoalAllocation.movement_id == mid)
            ).all():
                session.delete(alloc)
            attachment_service.delete_attachments_for_movement(session, mid)

        movements = session.exec(
            select(Movement).where(Movement.source_id == source_id)
        ).all()
        for m in movements:
            _purge(m.id)
            if m.transfer_pair_id:
                partner = session.get(Movement, m.transfer_pair_id)
                if partner:
                    _purge(partner.id)
                    session.delete(partner)
            session.delete(m)
        recurring = session.exec(
            select(RecurringItem).where(RecurringItem.source_id == source_id)
        ).all()
        for r in recurring:
            session.delete(r)
        # Delete portfolios (holdings + price snapshots cascaded manually
        # since SQLite PRAGMA foreign_keys is off by default)
        for p in portfolios:
            holdings = session.exec(
                select(Holding).where(Holding.portfolio_id == p.id)
            ).all()
            for h in holdings:
                snaps = session.exec(
                    select(HoldingPriceSnapshot).where(HoldingPriceSnapshot.holding_id == h.id)
                ).all()
                for s in snaps:
                    session.delete(s)
                session.delete(h)
            session.delete(p)

    session.delete(source)
    session.commit()


def merge_sources(session: Session, from_id: int, into_id: int) -> Source:
    """Merge source `from_id` into `into_id`.

    Moves all movements, recurring items and portfolios, adds starting_balance,
    deletes the source.
    """
    from models.recurring import RecurringItem
    from models.notification import Notification
    from models.portfolio import Portfolio

    from_source = get_source(session, from_id)
    into_source = get_source(session, into_id)

    if from_source.currency != into_source.currency:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot merge sources with different currencies ({from_source.currency} vs {into_source.currency})"
        )

    # Reassign movements
    movements = session.exec(
        select(Movement).where(Movement.source_id == from_id)
    ).all()
    for m in movements:
        m.source_id = into_id
        session.add(m)

    # Reassign recurring
    recurring = session.exec(
        select(RecurringItem).where(RecurringItem.source_id == from_id)
    ).all()
    for r in recurring:
        r.source_id = into_id
        session.add(r)

    # Reassign portfolios
    portfolios = session.exec(
        select(Portfolio).where(Portfolio.source_id == from_id)
    ).all()
    for p in portfolios:
        p.source_id = into_id
        session.add(p)

    # Transfer starting_balance
    into_source.starting_balance += from_source.starting_balance
    into_source.updated_at = datetime.utcnow()
    session.add(into_source)

    # Log the merge
    notification = Notification(
        type="info",
        title=f"Source merged: {from_source.name} → {into_source.name}",
        body=f"All movements and recurring items from '{from_source.name}' have been transferred to '{into_source.name}'.",
        related_entity=f"source:{into_id}",
    )
    session.add(notification)

    session.delete(from_source)
    session.commit()
    session.refresh(into_source)
    return into_source


def toggle_exclude_from_stats(session: Session, source_id: int) -> Source:
    source = get_source(session, source_id)
    source.exclude_from_stats = not source.exclude_from_stats
    source.updated_at = datetime.utcnow()
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def get_balance(session: Session, source_id: int) -> float:
    source = get_source(session, source_id)
    in_sum = session.exec(
        select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == source_id, Movement.direction == "in"
        )
    ).one()
    out_sum = session.exec(
        select(func.coalesce(func.sum(Movement.amount), 0)).where(
            Movement.source_id == source_id, Movement.direction == "out"
        )
    ).one()
    return round(source.starting_balance + float(in_sum) - float(out_sum), 2)


def get_balances_batch(session: Session, sources: list[Source]) -> dict[int, float]:
    """Compute balances for multiple sources in two queries instead of 2*N.

    Returns a dict mapping source_id -> current balance.
    """
    if not sources:
        return {}

    source_ids = [s.id for s in sources]

    # Single query: SUM grouped by source_id and direction
    rows = session.exec(
        select(
            Movement.source_id,
            Movement.direction,
            func.coalesce(func.sum(Movement.amount), 0),
        )
        .where(col(Movement.source_id).in_(source_ids))
        .group_by(Movement.source_id, Movement.direction)
    ).all()

    # Build lookup: {source_id: {"in": X, "out": Y}}
    sums: dict[int, dict[str, float]] = {}
    for sid, direction, total in rows:
        sums.setdefault(sid, {"in": 0.0, "out": 0.0})
        sums[sid][direction] = float(total)

    result = {}
    for s in sources:
        s_sums = sums.get(s.id, {"in": 0.0, "out": 0.0})
        result[s.id] = round(s.starting_balance + s_sums["in"] - s_sums["out"], 2)
    return result


def get_balance_history(
    session: Session, source_id: int, range_str: str = "all"
) -> list[dict]:
    """Return the source's total value per date: cash balance + portfolio value.

    Cash is reconstructed from movements. Portfolio value per date comes from
    `HoldingPriceSnapshot` rows (see `services.portfolios.portfolio_value_by_source_over_time`).
    If no snapshots exist yet, the portfolio contribution falls back to each
    holding's avg_cost so the line stays continuous.
    """
    from services import portfolios as portfolio_service

    source = get_source(session, source_id)
    today = date.today()

    range_map = {
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "1y": timedelta(days=365),
    }

    query = select(Movement).where(Movement.source_id == source_id).order_by(col(Movement.date))
    if range_str in range_map:
        start = today - range_map[range_str]
        query = query.where(Movement.date >= start)

    movements = session.exec(query).all()

    # Compute starting cash balance at the range start
    if range_str in range_map:
        start = today - range_map[range_str]
        prior_in = session.exec(
            select(func.coalesce(func.sum(Movement.amount), 0)).where(
                Movement.source_id == source_id,
                Movement.direction == "in",
                Movement.date < start,
            )
        ).one()
        prior_out = session.exec(
            select(func.coalesce(func.sum(Movement.amount), 0)).where(
                Movement.source_id == source_id,
                Movement.direction == "out",
                Movement.date < start,
            )
        ).one()
        running = round(source.starting_balance + float(prior_in) - float(prior_out), 2)
    else:
        running = source.starting_balance

    # Build a cash-balance-per-date sequence first
    cash_points: list[tuple[date, float]] = []
    for m in movements:
        if m.direction == "in":
            running = round(running + m.amount, 2)
        else:
            running = round(running - m.amount, 2)
        cash_points.append((m.date, round(running, 2)))

    # Always include "today" so the line extends to the present even without a
    # movement today — this is the date against which live portfolio values apply.
    if not cash_points or cash_points[-1][0] < today:
        cash_points.append((today, round(running, 2)))

    # Fetch portfolio values for the unique dates in one pass
    unique_dates = sorted({d for d, _ in cash_points})
    pf_values = portfolio_service.portfolio_value_by_source_over_time(
        session, source_id, unique_dates
    )

    history = [
        {
            "date": d.isoformat(),
            "balance": round(cash + pf_values.get(d, 0.0), 2),
            "cash": cash,
            "portfolios": round(pf_values.get(d, 0.0), 2),
        }
        for d, cash in cash_points
    ]
    return history
