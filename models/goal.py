from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer
from sqlmodel import Field, SQLModel


class Goal(SQLModel, table=True):
    __tablename__ = "goals"
    __table_args__ = (
        Index("ix_goals_source_id", "source_id"),
        Index("ix_goals_status", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    target_amount: float
    currency: str  # ISO 4217; must match the source's currency
    target_date: Optional[date] = None
    # Source where allocated money accumulates — usually the savings fund for
    # this currency, but the user can point it at any same-currency source.
    source_id: int = Field(
        sa_column=Column(Integer, ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    )
    status: str = Field(default="active")  # "active" | "completed" | "cancelled"
    note: Optional[str] = None
    # Bidirectional link with a Whim — set when a user clicks "save for this".
    linked_whim_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("whims.id", ondelete="SET NULL"), nullable=True),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GoalAllocation(SQLModel, table=True):
    __tablename__ = "goal_allocations"
    __table_args__ = (
        Index("ix_goal_allocations_goal_id", "goal_id"),
        Index("ix_goal_allocations_movement_id", "movement_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    goal_id: int = Field(
        sa_column=Column(Integer, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False)
    )
    # The transfer "in"-leg that deposited this allocation into goal.source_id.
    # Cascade: deleting the movement drops the allocation — keeps the goal total
    # honest without background sync.
    movement_id: int = Field(
        sa_column=Column(Integer, ForeignKey("movements.id", ondelete="CASCADE"), nullable=False)
    )
    amount: float  # snapshot at creation; should track the movement's amount
    date: date
    created_at: datetime = Field(default_factory=datetime.utcnow)
