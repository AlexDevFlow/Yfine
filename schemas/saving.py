from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class SavingCreate(BaseModel):
    from_source_id: int  # required — which account does the money come from
    amount: float = Field(gt=0)
    # Optional; if provided must match the source's currency. Kept for backward
    # compatibility with earlier clients that sent it explicitly.
    currency: Optional[str] = None
    date: date
    description: Optional[str] = None
    note: Optional[str] = None
    tag_ids: list[int] = []


class SavingUpdate(BaseModel):
    from_source_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    date: Optional[date] = None
    description: Optional[str] = None
    note: Optional[str] = None
    tag_ids: Optional[list[int]] = None


class SavingRead(BaseModel):
    id: int
    amount: float
    currency: str
    date: date
    description: Optional[str]
    note: Optional[str]
    tags: list[dict] = []
    from_source_id: Optional[int] = None
    fund_source_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
