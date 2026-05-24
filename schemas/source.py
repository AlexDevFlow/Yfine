from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from schemas.validators import validate_currency_code, validate_name

# Bounds for the periodic-yield feature. The rate is the percentage realised per
# period (gross); the period is expressed in whole months so any cadence the
# user wants — monthly, quarterly, semiannual, annual, … — is representable.
MAX_YIELD_RATE = 1000.0
MAX_YIELD_PERIOD_MONTHS = 120


def validate_yield_rate(v: float) -> float:
    if v < 0:
        raise ValueError("Yield rate cannot be negative")
    if v > MAX_YIELD_RATE:
        raise ValueError(f"Yield rate must be at most {MAX_YIELD_RATE:g}%")
    return float(v)


def validate_yield_period_months(v: int) -> int:
    v = int(v)
    if v < 1:
        raise ValueError("Yield period must be at least 1 month")
    if v > MAX_YIELD_PERIOD_MONTHS:
        raise ValueError(f"Yield period must be at most {MAX_YIELD_PERIOD_MONTHS} months")
    return v


class SourceCreate(BaseModel):
    name: str
    currency: str
    starting_balance: float = 0.0
    yield_rate: float = 0.0
    yield_period_months: int = 12

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        return validate_name(v)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        return validate_currency_code(v)

    @field_validator("yield_rate")
    @classmethod
    def check_yield_rate(cls, v):
        return validate_yield_rate(v)

    @field_validator("yield_period_months")
    @classmethod
    def check_yield_period(cls, v):
        return validate_yield_period_months(v)


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    starting_balance: Optional[float] = None
    yield_rate: Optional[float] = None
    yield_period_months: Optional[int] = None

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

    @field_validator("yield_rate")
    @classmethod
    def check_yield_rate(cls, v):
        if v is not None:
            return validate_yield_rate(v)
        return v

    @field_validator("yield_period_months")
    @classmethod
    def check_yield_period(cls, v):
        if v is not None:
            return validate_yield_period_months(v)
        return v


class SourceRead(BaseModel):
    id: int
    name: str
    currency: str
    starting_balance: float
    current_balance: float
    yield_rate: float = 0.0
    yield_period_months: int = 12
    yield_next_date: Optional[date] = None
    created_at: datetime
    updated_at: datetime
