from datetime import datetime
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
