from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from schemas.validators import validate_currency_code, validate_name, validate_note


_VALID_KINDS = {"crypto", "stocks", "mixed"}
_VALID_ASSET_CLASSES = {"crypto", "stock"}


def _validate_symbol(v: str) -> str:
    v = (v or "").strip().upper()
    if not v:
        raise ValueError("Symbol cannot be empty")
    if len(v) > 32:
        raise ValueError("Symbol too long (max 32 chars)")
    return v


# --- Portfolio ---


class PortfolioCreate(BaseModel):
    name: str
    kind: str = "mixed"
    base_currency: str = "EUR"
    source_id: int
    note: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return validate_name(v)

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
        return v

    @field_validator("base_currency")
    @classmethod
    def _c(cls, v):
        return validate_currency_code(v)

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return validate_note(v)


class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    base_currency: Optional[str] = None
    source_id: Optional[int] = None
    note: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _n(cls, v):
        return validate_name(v) if v is not None else v

    @field_validator("kind")
    @classmethod
    def _k(cls, v):
        if v is None:
            return v
        if v not in _VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(_VALID_KINDS)}")
        return v

    @field_validator("base_currency")
    @classmethod
    def _c(cls, v):
        return validate_currency_code(v) if v is not None else v

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return validate_note(v)


class HoldingRead(BaseModel):
    id: int
    portfolio_id: int
    asset_class: str
    symbol: str
    display_name: Optional[str] = None
    quantity: float
    avg_cost: float
    currency: str
    last_price: Optional[float] = None
    last_price_at: Optional[datetime] = None
    manual_price: bool
    note: Optional[str] = None
    # derived (populated by service)
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None


class PortfolioRead(BaseModel):
    id: int
    name: str
    kind: str
    base_currency: str
    source_id: int
    source_name: Optional[str] = None
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    holdings_count: int = 0
    total_cost: float = 0.0
    total_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0


# --- Holding ---


class HoldingCreate(BaseModel):
    portfolio_id: int
    asset_class: str
    symbol: str
    display_name: Optional[str] = None
    quantity: float = 0.0
    avg_cost: float = 0.0
    currency: str = "EUR"
    last_price: Optional[float] = None
    manual_price: bool = False
    note: Optional[str] = None

    @field_validator("asset_class")
    @classmethod
    def _ac(cls, v):
        if v not in _VALID_ASSET_CLASSES:
            raise ValueError(f"asset_class must be one of {sorted(_VALID_ASSET_CLASSES)}")
        return v

    @field_validator("symbol")
    @classmethod
    def _s(cls, v):
        return _validate_symbol(v)

    @field_validator("currency")
    @classmethod
    def _c(cls, v):
        return validate_currency_code(v)

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return validate_note(v)


class HoldingUpdate(BaseModel):
    asset_class: Optional[str] = None
    symbol: Optional[str] = None
    display_name: Optional[str] = None
    quantity: Optional[float] = None
    avg_cost: Optional[float] = None
    currency: Optional[str] = None
    last_price: Optional[float] = None
    manual_price: Optional[bool] = None
    note: Optional[str] = None

    @field_validator("asset_class")
    @classmethod
    def _ac(cls, v):
        if v is None:
            return v
        if v not in _VALID_ASSET_CLASSES:
            raise ValueError(f"asset_class must be one of {sorted(_VALID_ASSET_CLASSES)}")
        return v

    @field_validator("symbol")
    @classmethod
    def _s(cls, v):
        return _validate_symbol(v) if v is not None else v

    @field_validator("currency")
    @classmethod
    def _c(cls, v):
        return validate_currency_code(v) if v is not None else v

    @field_validator("note")
    @classmethod
    def _note(cls, v):
        return validate_note(v)
