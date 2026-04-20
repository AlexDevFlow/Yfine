from fastapi import APIRouter, Depends
from sqlmodel import Session

from database import get_session
from models.goal import Goal, GoalAllocation
from models.source import Source
from schemas.goal import GoalRead
from schemas.whim import WhimCreate, WhimPurchase, WhimRead, WhimUpdate
from services import goals as goal_service
from services import sources as source_service
from services import whims as whim_service

router = APIRouter(prefix="/api/whims", tags=["whims"])


def _to_read(session: Session, whim) -> WhimRead:
    source_name = None
    source_balance = None
    if whim.source_id:
        source = session.get(Source, whim.source_id)
        if source:
            source_name = source.name
            source_balance = source_service.get_balance(session, whim.source_id)
    linked_goal_id = whim.linked_goal_id
    linked_goal_allocated = None
    linked_goal_target = None
    linked_goal_status = None
    if linked_goal_id:
        g = session.get(Goal, linked_goal_id)
        if g:
            from sqlmodel import func, select as _select
            allocated = session.exec(
                _select(func.coalesce(func.sum(GoalAllocation.amount), 0.0)).where(
                    GoalAllocation.goal_id == g.id
                )
            ).one()
            linked_goal_allocated = round(float(allocated or 0.0), 2)
            linked_goal_target = g.target_amount
            linked_goal_status = g.status
        else:
            linked_goal_id = None
    return WhimRead(
        id=whim.id,
        name=whim.name,
        amount=whim.amount,
        currency=whim.currency,
        priority=whim.priority,
        source_id=whim.source_id,
        source_name=source_name,
        source_balance=source_balance,
        status=whim.status,
        note=whim.note,
        url=whim.url,
        linked_goal_id=linked_goal_id,
        linked_goal_allocated=linked_goal_allocated,
        linked_goal_target=linked_goal_target,
        linked_goal_status=linked_goal_status,
        purchased_at=whim.purchased_at,
        created_at=whim.created_at,
        updated_at=whim.updated_at,
    )


@router.get("", response_model=list[WhimRead])
def list_whims(
    skip: int = 0,
    limit: int = 50,
    status: str | None = None,
    priority: str | None = None,
    session: Session = Depends(get_session),
):
    items = whim_service.list_whims(session, skip, limit, status=status, priority=priority)
    return [_to_read(session, w) for w in items]


@router.post("", response_model=WhimRead, status_code=201)
def create_whim(data: WhimCreate, session: Session = Depends(get_session)):
    whim = whim_service.create_whim(session, data)
    return _to_read(session, whim)


@router.get("/{whim_id}", response_model=WhimRead)
def get_whim(whim_id: int, session: Session = Depends(get_session)):
    whim = whim_service.get_whim(session, whim_id)
    return _to_read(session, whim)


@router.put("/{whim_id}", response_model=WhimRead)
def update_whim(whim_id: int, data: WhimUpdate, session: Session = Depends(get_session)):
    whim = whim_service.update_whim(session, whim_id, data)
    return _to_read(session, whim)


@router.delete("/{whim_id}", status_code=204)
def delete_whim(whim_id: int, session: Session = Depends(get_session)):
    whim_service.delete_whim(session, whim_id)


@router.post("/{whim_id}/purchase", response_model=WhimRead)
def purchase_whim(whim_id: int, data: WhimPurchase, session: Session = Depends(get_session)):
    whim = whim_service.purchase_whim(session, whim_id, data)
    return _to_read(session, whim)


@router.post("/{whim_id}/dismiss", response_model=WhimRead)
def dismiss_whim(whim_id: int, session: Session = Depends(get_session)):
    whim = whim_service.dismiss_whim(session, whim_id)
    return _to_read(session, whim)


@router.post("/{whim_id}/save-for", response_model=GoalRead, status_code=201)
def start_saving_for_whim(whim_id: int, session: Session = Depends(get_session)):
    """Create (or reuse) a Goal tied to this Whim so the user can accumulate
    money toward the purchase."""
    goal = goal_service.start_saving_for_whim(session, whim_id)
    session.refresh(goal)
    return goal_service.to_read(session, goal)
