from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer
from sqlmodel import Field, SQLModel


class MovementTag(SQLModel, table=True):
    __tablename__ = "movement_tag"

    movement_id: int = Field(
        sa_column=Column(Integer, ForeignKey("movements.id", ondelete="CASCADE"), primary_key=True)
    )
    tag_id: int = Field(
        sa_column=Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    )


class Movement(SQLModel, table=True):
    __tablename__ = "movements"
    __table_args__ = (
        Index("ix_movements_source_id", "source_id"),
        Index("ix_movements_date", "date"),
        Index("ix_movements_transfer_pair_id", "transfer_pair_id"),
        Index("ix_movements_source_id_direction", "source_id", "direction"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: Optional[int] = Field(default=None, foreign_key="sources.id")
    amount: float
    direction: str  # "in" | "out"
    date: date
    note: Optional[str] = None
    transfer_pair_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, ForeignKey("movements.id", ondelete="SET NULL"), nullable=True)
    )
    exclude_from_stats: bool = Field(default=False)
    # Marks the in-leg of a transfer that lands in a savings fund. Lets the
    # savings page query contributions without joining Source every time.
    is_savings_contribution: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MovementAttachment(SQLModel, table=True):
    __tablename__ = "movement_attachments"
    __table_args__ = (
        Index("ix_movement_attachments_movement_id", "movement_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    movement_id: int = Field(
        sa_column=Column(Integer, ForeignKey("movements.id", ondelete="CASCADE"), nullable=False)
    )
    filename: str  # original name as uploaded by the user
    stored_name: str  # UUID4 + extension on disk (never trust filename for paths)
    mime_type: str
    size_bytes: int
    created_at: datetime = Field(default_factory=datetime.utcnow)
