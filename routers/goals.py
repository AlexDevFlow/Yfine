from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from schemas.goal import (
    AllocationCreate,
    GoalAllocationRead,
    GoalClose,
    GoalCreate,
    GoalRead,
    GoalUpdate,
)
from services import goals as goal_service

router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("", response_model=list[GoalRead])
def list_goals(
    status: str | None = Query(default=None),
    currency: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    rows = goal_service.list_goals(session, status=status, currency=currency)
    return [goal_service.to_read(session, g) for g in rows]


@router.post("", response_model=GoalRead, status_code=201)
def create_goal(data: GoalCreate, session: Session = Depends(get_session)):
    g = goal_service.create_goal(session, data)
    return goal_service.to_read(session, g)


@router.get("/{goal_id}", response_model=GoalRead)
def get_goal(goal_id: int, session: Session = Depends(get_session)):
    g = goal_service.get_goal(session, goal_id)
    return goal_service.to_read(session, g)


@router.put("/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: int, data: GoalUpdate, session: Session = Depends(get_session)):
    g = goal_service.update_goal(session, goal_id, data)
    return goal_service.to_read(session, g)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: int, session: Session = Depends(get_session)):
    goal_service.delete_goal(session, goal_id)


# --- Allocations ---


@router.get("/{goal_id}/allocations", response_model=list[GoalAllocationRead])
def list_goal_allocations(goal_id: int, session: Session = Depends(get_session)):
    items = goal_service.list_allocations(session, goal_id)
    return [goal_service.allocation_to_read(session, a) for a in items]


@router.post(
    "/{goal_id}/allocations",
    response_model=GoalAllocationRead,
    status_code=201,
)
def allocate_to_goal(
    goal_id: int,
    data: AllocationCreate,
    session: Session = Depends(get_session),
):
    alloc = goal_service.allocate(session, goal_id, data)
    return goal_service.allocation_to_read(session, alloc)


@router.delete("/allocations/{allocation_id}", status_code=204)
def delete_allocation(allocation_id: int, session: Session = Depends(get_session)):
    goal_service.delete_allocation(session, allocation_id)


@router.post("/{goal_id}/close", response_model=GoalRead)
def close_goal(
    goal_id: int,
    data: GoalClose,
    session: Session = Depends(get_session),
):
    g = goal_service.close_goal(session, goal_id, data)
    return goal_service.to_read(session, g)
