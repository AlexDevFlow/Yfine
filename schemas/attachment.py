import datetime as dt

from pydantic import BaseModel


class AttachmentRead(BaseModel):
    id: int
    movement_id: int
    filename: str
    mime_type: str
    size_bytes: int
    created_at: dt.datetime
