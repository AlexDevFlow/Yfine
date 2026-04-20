from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from schemas.validators import validate_currency_code


class ExchangeRateCreate(BaseModel):
    from_currency: str
    to_currency: str
    rate: float = Field(gt=0)

    @field_validator("from_currency", "to_currency")
    @classmethod
    def check_currency(cls, v):
        return validate_currency_code(v)


class ExchangeRateUpdate(BaseModel):
    rate: float = Field(gt=0)


class ExchangeRateRead(BaseModel):
    id: int
    from_currency: str
    to_currency: str
    rate: float
    updated_at: datetime
