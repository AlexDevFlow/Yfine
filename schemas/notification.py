from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationRead(BaseModel):
    id: int
    type: str
    title: str
    body: str
    related_entity: Optional[str]
    is_read: bool
    created_at: datetime
