from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from schemas.validators import validate_currency_code, validate_name


class RecurringCreate(BaseModel):
    name: str
    amount: float = Field(gt=0)
    direction: Literal["in", "out"]
    currency: str
    frequency: Literal["daily", "weekly", "monthly", "yearly"]
    start_date: date
    end_date: Optional[date] = None
    source_id: Optional[int] = None
    apply_mode: Literal["auto", "confirm"] = "confirm"
    alert_days_before: int = Field(default=7, ge=0, le=365)
    alert_if_insufficient: bool = True

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        return validate_name(v)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        return validate_currency_code(v)

    @model_validator(mode="after")
    def check_date_range(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class RecurringUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    direction: Optional[Literal["in", "out"]] = None
    currency: Optional[str] = None
    frequency: Optional[Literal["daily", "weekly", "monthly", "yearly"]] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    source_id: Optional[int] = None
    apply_mode: Optional[Literal["auto", "confirm"]] = None
    alert_days_before: Optional[int] = Field(default=None, ge=0, le=365)
    alert_if_insufficient: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        if v is not None:
            return validate_name(v)
        return v

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        if v is not None:
            return validate_currency_code(v)
        return v


class RecurringRead(BaseModel):
    id: int
    name: str
    amount: float
    direction: str
    currency: str
    frequency: str
    start_date: date
    end_date: Optional[date]
    source_id: Optional[int]
    source_name: Optional[str]
    apply_mode: str
    next_due_date: date
    alert_days_before: int
    alert_if_insufficient: bool
    created_at: datetime
    updated_at: datetime
