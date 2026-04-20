from datetime import date, datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class RecurringItem(SQLModel, table=True):
    __tablename__ = "recurring_items"
    __table_args__ = (
        Index("ix_recurring_items_next_due_date", "next_due_date"),
        Index("ix_recurring_items_source_id", "source_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    amount: float
    direction: str  # "in" | "out"
    currency: str  # ISO 4217
    frequency: str  # "daily" | "weekly" | "monthly" | "yearly"
    start_date: date
    end_date: Optional[date] = None
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    apply_mode: str = "confirm"  # "auto" | "confirm"
    next_due_date: date
    alert_days_before: int = Field(default=7)
    alert_if_insufficient: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
