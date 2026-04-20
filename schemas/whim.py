from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class WhimPurchase(BaseModel):
    source_id: int
    date: date
    note: Optional[str] = None
    tag_ids: list[int] = Field(default_factory=list)


class WhimCreate(BaseModel):
    name: str
    amount: float = Field(gt=0)
    currency: str
    priority: Literal["low", "medium", "high"] = "medium"
    source_id: Optional[int] = None
    note: Optional[str] = None
    url: Optional[str] = None


class WhimUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    priority: Optional[Literal["low", "medium", "high"]] = None
    source_id: Optional[int] = None
    status: Optional[Literal["pending", "purchased", "dismissed"]] = None
    note: Optional[str] = None
    url: Optional[str] = None


class WhimRead(BaseModel):
    id: int
    name: str
    amount: float
    currency: str
    priority: str
    source_id: Optional[int]
    source_name: Optional[str]
    source_balance: Optional[float]
    status: str
    note: Optional[str]
    url: Optional[str]
    linked_goal_id: Optional[int] = None
    linked_goal_allocated: Optional[float] = None
    linked_goal_target: Optional[float] = None
    linked_goal_status: Optional[str] = None
    purchased_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
