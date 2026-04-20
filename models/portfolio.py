from datetime import date as _date, datetime
from typing import Optional

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel


class Portfolio(SQLModel, table=True):
    __tablename__ = "portfolios"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    kind: str = Field(default="mixed")  # "crypto" | "stocks" | "mixed"
    base_currency: str = Field(default="EUR")
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    )
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Holding(SQLModel, table=True):
    __tablename__ = "holdings"
    __table_args__ = (
        Index("ix_holdings_portfolio_id", "portfolio_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    portfolio_id: int = Field(
        sa_column=Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    )
    asset_class: str  # "crypto" | "stock"
    symbol: str  # e.g. "BTC", "AAPL"
    display_name: Optional[str] = None
    quantity: float = Field(default=0.0)
    avg_cost: float = Field(default=0.0)  # per unit, in `currency`
    currency: str = Field(default="EUR")
    last_price: Optional[float] = None
    last_price_at: Optional[datetime] = None
    manual_price: bool = Field(default=False)
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class HoldingPriceSnapshot(SQLModel, table=True):
    """Daily closing price per holding — feeds the portfolio value history."""
    __tablename__ = "holding_price_snapshots"
    __table_args__ = (
        UniqueConstraint("holding_id", "date", name="uq_holding_snapshot_date"),
        Index("ix_holding_price_snapshots_holding_date", "holding_id", "date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    holding_id: int = Field(
        sa_column=Column(Integer, ForeignKey("holdings.id", ondelete="CASCADE"), nullable=False)
    )
    date: _date = Field(sa_column=Column(Date, nullable=False))
    price: float
    created_at: datetime = Field(default_factory=datetime.utcnow)
