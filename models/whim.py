from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Whim(SQLModel, table=True):
    __tablename__ = "whims"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    amount: float
    currency: str  # ISO 4217
    priority: str = "medium"  # "low" | "medium" | "high"
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    status: str = "pending"  # "pending" | "purchased" | "dismissed"
    note: Optional[str] = None
    url: Optional[str] = None
    purchased_at: Optional[datetime] = None
    # Soft reference to a Goal — app-level cleanup in goals.delete_goal
    # resets this field. Intentionally not a DB FK to avoid an unresolvable
    # cycle with Goal.linked_whim_id.
    linked_goal_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
