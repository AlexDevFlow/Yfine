from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from schemas.validators import validate_currency_code, validate_name


class SourceCreate(BaseModel):
    name: str
    currency: str
    starting_balance: float = 0.0

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        return validate_name(v)

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v):
        return validate_currency_code(v)


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    currency: Optional[str] = None
    starting_balance: Optional[float] = None

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


class SourceRead(BaseModel):
    id: int
    name: str
    currency: str
    starting_balance: float
    current_balance: float
    created_at: datetime
    updated_at: datetime
