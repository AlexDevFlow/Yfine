from datetime import datetime
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_is_read", "is_read"),
        Index("ix_notifications_created_at", "created_at"),
        Index("ix_notifications_related_entity_type", "related_entity", "type"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    type: str  # "alert" | "info" | "warning"
    title: str
    body: str
    related_entity: Optional[str] = None  # e.g. "recurring:3"
    is_read: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
