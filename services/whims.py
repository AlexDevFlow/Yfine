from datetime import datetime

from fastapi import HTTPException
from sqlmodel import Session, select, col

from models.movement import Movement, MovementTag
from models.notification import Notification
from models.source import Source
from models.whim import Whim
from schemas.whim import WhimCreate, WhimPurchase, WhimUpdate


def list_whims(
    session: Session,
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    priority: str | None = None,
) -> list[Whim]:
    query = select(Whim)
    if status:
        query = query.where(Whim.status == status)
    if priority:
        query = query.where(Whim.priority == priority)
    query = query.order_by(col(Whim.created_at).desc()).offset(skip).limit(limit)
    return list(session.exec(query).all())


def count_whims(session: Session, status: str | None = None) -> int:
    from sqlmodel import func
    query = select(func.count(Whim.id))
    if status:
        query = query.where(Whim.status == status)
    return int(session.exec(query).one())


def get_whim(session: Session, whim_id: int) -> Whim:
    whim = session.get(Whim, whim_id)
    if not whim:
        raise HTTPException(status_code=404, detail="Whim not found")
    return whim


def create_whim(session: Session, data: WhimCreate) -> Whim:
    whim = Whim(**data.model_dump())
    session.add(whim)
    session.commit()
    session.refresh(whim)
    return whim


def update_whim(session: Session, whim_id: int, data: WhimUpdate) -> Whim:
    whim = get_whim(session, whim_id)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(whim, key, value)
    whim.updated_at = datetime.utcnow()
    session.add(whim)
    session.commit()
    session.refresh(whim)
    return whim


def delete_whim(session: Session, whim_id: int) -> None:
    from models.goal import Goal

    whim = get_whim(session, whim_id)
    # SQLite PRAGMA foreign_keys is off, so ON DELETE SET NULL on
    # goals.linked_whim_id never fires. Clear the back-reference manually
    # to avoid dangling IDs (and accidental re-link on ID reuse).
    for goal in session.exec(
        select(Goal).where(Goal.linked_whim_id == whim_id)
    ).all():
        goal.linked_whim_id = None
        session.add(goal)
    session.delete(whim)
    session.commit()


def purchase_whim(session: Session, whim_id: int, data: WhimPurchase) -> Whim:
    """Mark a whim as purchased and create the corresponding movement.

    If the whim has an active linked goal with allocations, first close the
    goal — allocated money refunds into `source_id` before the outgoing
    purchase movement is created. This makes the "saving up for X, then
    paying for X" workflow a single transaction from the user's POV.
    """
    whim = get_whim(session, whim_id)
    if whim.status == "purchased":
        raise HTTPException(status_code=400, detail="Whim already purchased")

    # Validate source exists
    source = session.get(Source, data.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Drain the linked goal onto the chosen source first, if applicable.
    # We drain whenever the goal isn't cancelled, regardless of active/
    # completed status — the only thing that matters is "does it still have
    # money allocated?".
    if whim.linked_goal_id is not None:
        from models.goal import Goal, GoalAllocation
        from schemas.goal import GoalClose
        from services import goals as goal_service
        from sqlmodel import select as _select

        goal = session.get(Goal, whim.linked_goal_id)
        if goal and goal.status != "cancelled":
            has_allocs = session.exec(
                _select(GoalAllocation).where(GoalAllocation.goal_id == goal.id).limit(1)
            ).first() is not None
            if has_allocs:
                if goal.currency != source.currency:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Linked goal currency doesn't match the purchase source. "
                            "Close the goal manually or pick a matching source."
                        ),
                    )
                goal_service.close_goal(
                    session,
                    goal.id,
                    GoalClose(to_source_id=source.id, date=data.date),
                )

    # Create the outgoing movement
    movement = Movement(
        source_id=data.source_id,
        amount=whim.amount,
        direction="out",
        date=data.date,
        note=data.note or whim.name,
    )
    session.add(movement)
    session.flush()

    # Attach tags
    for tag_id in data.tag_ids:
        session.add(MovementTag(movement_id=movement.id, tag_id=tag_id))

    whim.status = "purchased"
    whim.purchased_at = datetime.utcnow()
    whim.updated_at = datetime.utcnow()
    session.add(whim)

    notification = Notification(
        type="info",
        title=f"Whim purchased: {whim.name}",
        body=f"{whim.amount:.2f} {whim.currency}",
        related_entity=f"whim:{whim.id}",
    )
    session.add(notification)

    session.commit()
    session.refresh(whim)
    return whim


def dismiss_whim(session: Session, whim_id: int) -> Whim:
    """Dismiss a whim (decided not to buy)."""
    whim = get_whim(session, whim_id)
    whim.status = "dismissed"
    whim.updated_at = datetime.utcnow()
    session.add(whim)
    session.commit()
    session.refresh(whim)
    return whim


def restore_whim(session: Session, whim_id: int) -> Whim:
    """Restore a dismissed whim back to pending."""
    whim = get_whim(session, whim_id)
    if whim.status != "dismissed":
        raise HTTPException(status_code=422, detail="Only dismissed whims can be restored")
    whim.status = "pending"
    whim.updated_at = datetime.utcnow()
    session.add(whim)
    session.commit()
    session.refresh(whim)
    return whim
