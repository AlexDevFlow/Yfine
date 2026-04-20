"""Goals service.

A Goal is a target amount accumulated inside a Source (usually the per-currency
savings fund). Money is moved in/out via real transfer movements, linked by
GoalAllocation rows so we can report allocated-total and reverse the flow on
demand.
"""
from datetime import date, datetime

from fastapi import HTTPException
from sqlmodel import Session, col, func, select

from models.goal import Goal, GoalAllocation
from models.movement import Movement, MovementTag
from models.source import Source
from models.whim import Whim
from schemas.goal import AllocationCreate, GoalClose, GoalCreate, GoalUpdate
from services import savings_fund as fund_service


# --- Helpers ---

def _get_goal(session: Session, goal_id: int) -> Goal:
    g = session.get(Goal, goal_id)
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")
    return g


def _allocated_sum(session: Session, goal_id: int) -> float:
    total = session.exec(
        select(func.coalesce(func.sum(GoalAllocation.amount), 0.0)).where(
            GoalAllocation.goal_id == goal_id
        )
    ).one()
    return round(float(total or 0.0), 2)


def _allocation_count(session: Session, goal_id: int) -> int:
    return int(
        session.exec(
            select(func.count(GoalAllocation.id)).where(
                GoalAllocation.goal_id == goal_id
            )
        ).one()
    )


def to_read(session: Session, g: Goal) -> dict:
    allocated = _allocated_sum(session, g.id)
    pct = (allocated / g.target_amount * 100.0) if g.target_amount else 0.0
    return {
        "id": g.id,
        "name": g.name,
        "target_amount": g.target_amount,
        "currency": g.currency,
        "target_date": g.target_date,
        "source_id": g.source_id,
        "status": g.status,
        "note": g.note,
        "linked_whim_id": g.linked_whim_id,
        "allocated_amount": allocated,
        "progress_pct": round(pct, 2),
        "allocation_count": _allocation_count(session, g.id),
        "created_at": g.created_at,
        "updated_at": g.updated_at,
    }


def _ensure_source_compatible(session: Session, source_id: int, currency: str) -> Source:
    src = session.get(Source, source_id)
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    if src.currency != currency:
        raise HTTPException(status_code=422, detail="Currency mismatch with source")
    return src


# --- CRUD ---

def list_goals(
    session: Session,
    status: str | None = None,
    currency: str | None = None,
) -> list[Goal]:
    q = select(Goal)
    if status:
        q = q.where(Goal.status == status)
    if currency:
        q = q.where(Goal.currency == currency)
    q = q.order_by(
        # Active goals first, then by target date ascending (nulls last).
        (col(Goal.status) != "active"),
        col(Goal.target_date).is_(None),
        col(Goal.target_date),
        col(Goal.id),
    )
    return list(session.exec(q).all())


def get_goal(session: Session, goal_id: int) -> Goal:
    return _get_goal(session, goal_id)


def create_goal(session: Session, data: GoalCreate) -> Goal:
    currency = data.currency.upper()
    # Auto-pick the savings fund for the chosen currency when none is given.
    source_id = data.source_id
    if source_id is None:
        fund = fund_service.ensure_fund_for_currency(session, currency)
        source_id = fund.id
    _ensure_source_compatible(session, source_id, currency)

    if data.linked_whim_id is not None:
        whim = session.get(Whim, data.linked_whim_id)
        if not whim:
            raise HTTPException(status_code=404, detail="Whim not found")
        if whim.currency != currency:
            raise HTTPException(status_code=422, detail="Whim currency mismatch")

    goal = Goal(
        name=data.name.strip(),
        target_amount=data.target_amount,
        currency=currency,
        target_date=data.target_date,
        source_id=source_id,
        note=data.note,
        status="active",
        linked_whim_id=data.linked_whim_id,
    )
    session.add(goal)
    session.flush()

    # Back-reference on Whim so the UI can find the goal from either side.
    if data.linked_whim_id is not None:
        whim = session.get(Whim, data.linked_whim_id)
        if whim is not None:
            whim.linked_goal_id = goal.id
            whim.updated_at = datetime.utcnow()
            session.add(whim)

    session.commit()
    session.refresh(goal)
    return goal


def update_goal(session: Session, goal_id: int, data: GoalUpdate) -> Goal:
    goal = _get_goal(session, goal_id)
    payload = data.model_dump(exclude_unset=True)
    # source_id is intentionally not updateable — would require moving money
    # between sources mid-flight, which is error-prone.
    for key, value in payload.items():
        setattr(goal, key, value)
    goal.updated_at = datetime.utcnow()
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


def delete_goal(session: Session, goal_id: int) -> None:
    """Delete a goal and auto-deallocate every allocation back to its origin."""
    goal = _get_goal(session, goal_id)
    allocations = list(
        session.exec(
            select(GoalAllocation).where(GoalAllocation.goal_id == goal_id)
        ).all()
    )
    for alloc in allocations:
        _reverse_allocation(session, alloc)
    # Clear back-reference on linked Whim.
    if goal.linked_whim_id is not None:
        whim = session.get(Whim, goal.linked_whim_id)
        if whim and whim.linked_goal_id == goal_id:
            whim.linked_goal_id = None
            session.add(whim)
    session.delete(goal)
    session.commit()


# --- Allocations ---

def list_allocations(session: Session, goal_id: int) -> list[GoalAllocation]:
    _get_goal(session, goal_id)
    return list(
        session.exec(
            select(GoalAllocation)
            .where(GoalAllocation.goal_id == goal_id)
            .order_by(col(GoalAllocation.date).desc(), col(GoalAllocation.id).desc())
        ).all()
    )


def _from_source_of_allocation(session: Session, alloc: GoalAllocation) -> Source | None:
    mv = session.get(Movement, alloc.movement_id)
    if not mv or not mv.transfer_pair_id:
        return None
    partner = session.get(Movement, mv.transfer_pair_id)
    if not partner or not partner.source_id:
        return None
    return session.get(Source, partner.source_id)


def allocation_to_read(session: Session, alloc: GoalAllocation) -> dict:
    src = _from_source_of_allocation(session, alloc)
    return {
        "id": alloc.id,
        "goal_id": alloc.goal_id,
        "movement_id": alloc.movement_id,
        "amount": alloc.amount,
        "date": alloc.date,
        "from_source_id": src.id if src else None,
        "from_source_name": src.name if src else None,
        "created_at": alloc.created_at,
    }


def allocate(
    session: Session,
    goal_id: int,
    data: AllocationCreate,
) -> GoalAllocation:
    goal = _get_goal(session, goal_id)
    if goal.status != "active":
        raise HTTPException(status_code=422, detail="Goal is not active")

    from_source = session.get(Source, data.from_source_id)
    if not from_source:
        raise HTTPException(status_code=404, detail="Source not found")
    if from_source.id == goal.source_id:
        raise HTTPException(
            status_code=422,
            detail="Cannot allocate from the goal's own accumulating source",
        )
    if from_source.currency != goal.currency:
        raise HTTPException(status_code=422, detail="Currency mismatch")

    # Build a transfer from from_source → goal.source_id and record the link.
    out_mv = Movement(
        source_id=from_source.id,
        amount=data.amount,
        direction="out",
        date=data.date,
        note=f"→ {goal.name}",
    )
    in_mv = Movement(
        source_id=goal.source_id,
        amount=data.amount,
        direction="in",
        date=data.date,
        note=f"{goal.name}",
    )
    session.add(out_mv)
    session.add(in_mv)
    session.flush()
    out_mv.transfer_pair_id = in_mv.id
    in_mv.transfer_pair_id = out_mv.id
    session.add(out_mv)
    session.add(in_mv)

    alloc = GoalAllocation(
        goal_id=goal.id,
        movement_id=in_mv.id,
        amount=data.amount,
        date=data.date,
    )
    session.add(alloc)
    # Flush so the sum below sees this allocation; we don't auto-complete
    # here anymore — that was gating the "buy linked whim → drain goal"
    # flow in unexpected ways. A goal stays "active" until the user (or
    # a whim purchase) explicitly closes it.
    session.flush()

    session.commit()
    session.refresh(alloc)
    return alloc


def _reverse_allocation(session: Session, alloc: GoalAllocation) -> None:
    """Delete the underlying transfer; cascades to the allocation row."""
    from services import movements as movement_service

    in_mv = session.get(Movement, alloc.movement_id)
    if in_mv:
        # delete_movement handles the partner leg + tag links + attachments +
        # cascaded allocation rows (including the one we're processing).
        movement_service.delete_movement(session, in_mv.id)
    else:
        session.delete(alloc)
    # movement_service.delete_movement commits — reload the session state if
    # needed by callers.


def delete_allocation(session: Session, allocation_id: int) -> None:
    alloc = session.get(GoalAllocation, allocation_id)
    if not alloc:
        raise HTTPException(status_code=404, detail="Allocation not found")
    _reverse_allocation(session, alloc)


def close_goal(session: Session, goal_id: int, data: GoalClose) -> Goal:
    """Mark the goal completed and refund every allocation to `to_source_id`."""
    goal = _get_goal(session, goal_id)
    if goal.status == "cancelled":
        raise HTTPException(status_code=422, detail="Cancelled goals can't be closed")

    to_source = session.get(Source, data.to_source_id)
    if not to_source:
        raise HTTPException(status_code=404, detail="Source not found")
    if to_source.currency != goal.currency:
        raise HTTPException(status_code=422, detail="Currency mismatch")

    when = data.date or date.today()

    allocations = list(
        session.exec(
            select(GoalAllocation).where(GoalAllocation.goal_id == goal_id)
        ).all()
    )

    # Emit a single consolidated transfer from goal.source_id to to_source
    # equal to the total allocated; then drop the allocations + backing
    # movements. This keeps /movements tidy (one refund, not N).
    total = sum(a.amount for a in allocations)
    if total > 0:
        out_mv = Movement(
            source_id=goal.source_id,
            amount=total,
            direction="out",
            date=when,
            note=f"↩ {goal.name}",
        )
        in_mv = Movement(
            source_id=to_source.id,
            amount=total,
            direction="in",
            date=when,
            note=f"↩ {goal.name}",
        )
        session.add(out_mv)
        session.add(in_mv)
        session.flush()
        out_mv.transfer_pair_id = in_mv.id
        in_mv.transfer_pair_id = out_mv.id
        session.add(out_mv)
        session.add(in_mv)

    # Now delete the allocations + their source movements.
    for alloc in allocations:
        in_mv = session.get(Movement, alloc.movement_id)
        if in_mv:
            from services import movements as movement_service
            movement_service.delete_movement(session, in_mv.id)

    goal.status = "completed"
    goal.updated_at = datetime.utcnow()
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return goal


# --- Utility for whim integration ---

def start_saving_for_whim(session: Session, whim_id: int) -> Goal:
    whim = session.get(Whim, whim_id)
    if not whim:
        raise HTTPException(status_code=404, detail="Whim not found")
    if whim.status != "pending":
        raise HTTPException(status_code=422, detail="Only pending whims can be saved for")
    if whim.linked_goal_id is not None:
        existing = session.get(Goal, whim.linked_goal_id)
        if existing:
            return existing

    data = GoalCreate(
        name=whim.name,
        target_amount=whim.amount,
        currency=whim.currency,
        note=whim.note,
        linked_whim_id=whim.id,
    )
    return create_goal(session, data)
