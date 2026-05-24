from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    currency: str  # ISO 4217
    starting_balance: float = Field(default=0.0)
    exclude_from_stats: bool = Field(default=False)
    # Per-currency savings "pot" backing the /savings page. At most one per
    # currency is created automatically the first time the user saves that
    # currency; exposed in /sources only when hidden_from_sources=False.
    is_savings_fund: bool = Field(default=False)
    hidden_from_sources: bool = Field(default=False)
    # Periodic interest/yield (e.g. a term-deposit account). When yield_rate > 0
    # the scheduler credits an "in" movement of balance * (yield_rate/100) every
    # yield_period_months, compounding on the running cash balance. yield_rate is
    # the percentage realised per period (not annualised); 0 disables accrual.
    yield_rate: float = Field(default=0.0)
    yield_period_months: int = Field(default=12)
    # Next date interest should be credited, and the last date already credited
    # (idempotency guard so a missed-period catch-up never double-pays).
    yield_next_date: Optional[date] = Field(default=None)
    yield_last_date: Optional[date] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
