from datetime import datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class ExchangeRate(SQLModel, table=True):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        Index("ix_exchange_rates_pair", "from_currency", "to_currency", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    from_currency: str  # ISO 4217
    to_currency: str  # ISO 4217
    rate: float  # 1 unit of from_currency = rate units of to_currency
    updated_at: datetime = Field(default_factory=datetime.utcnow)
