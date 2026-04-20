import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    currency: str
    target_date: Optional[dt.date] = None
    # Defaults to the savings fund for the chosen currency (server-side).
    source_id: Optional[int] = None
    note: Optional[str] = None
    linked_whim_id: Optional[int] = None


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    target_amount: Optional[float] = Field(default=None, gt=0)
    target_date: Optional[dt.date] = None
    note: Optional[str] = None
    status: Optional[Literal["active", "completed", "cancelled"]] = None


class AllocationCreate(BaseModel):
    from_source_id: int
    amount: float = Field(gt=0)
    date: dt.date


class GoalClose(BaseModel):
    # Source to refund all allocations to (typically a regular account).
    to_source_id: int
    date: Optional[dt.date] = None


class GoalRead(BaseModel):
    id: int
    name: str
    target_amount: float
    currency: str
    target_date: Optional[dt.date]
    source_id: int
    status: str
    note: Optional[str]
    linked_whim_id: Optional[int]
    allocated_amount: float
    progress_pct: float
    allocation_count: int
    created_at: dt.datetime
    updated_at: dt.datetime


class GoalAllocationRead(BaseModel):
    id: int
    goal_id: int
    movement_id: int
    amount: float
    date: dt.date
    from_source_id: Optional[int]
    from_source_name: Optional[str]
    created_at: dt.datetime
