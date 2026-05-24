from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from schemas.validators import validate_currency_code


class BudgetCreate(BaseModel):
    tag_id: int
    amount: float = Field(gt=0)
    currency: str
    period: Literal["weekly", "monthly", "quarterly", "yearly"] = "monthly"
    direction: Literal["in", "out"] = "out"
    rollover: bool = False
    alert_threshold_pct: int = Field(default=80, ge=0, le=100)
    active: bool = True
    start_date: Optional[date] = None

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        return validate_currency_code(v)


class BudgetUpdate(BaseModel):
    tag_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = None
    period: Optional[Literal["weekly", "monthly", "quarterly", "yearly"]] = None
    direction: Optional[Literal["in", "out"]] = None
    rollover: Optional[bool] = None
    alert_threshold_pct: Optional[int] = Field(default=None, ge=0, le=100)
    active: Optional[bool] = None
    start_date: Optional[date] = None

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        if v is not None:
            return validate_currency_code(v)
        return v


class BudgetRead(BaseModel):
    id: int
    tag_id: int
    amount: float
    currency: str
    period: str
    direction: str
    rollover: bool
    alert_threshold_pct: int
    active: bool
    start_date: date
    created_at: datetime
    updated_at: datetime
