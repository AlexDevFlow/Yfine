from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class SavingTag(SQLModel, table=True):
    __tablename__ = "saving_tag"

    saving_id: int = Field(
        sa_column=Column(Integer, ForeignKey("savings.id", ondelete="CASCADE"), primary_key=True)
    )
    tag_id: int = Field(
        sa_column=Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    )


class Saving(SQLModel, table=True):
    __tablename__ = "savings"

    id: Optional[int] = Field(default=None, primary_key=True)
    amount: float
    currency: str  # ISO 4217
    date: date
    description: Optional[str] = None  # what was saved from
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
