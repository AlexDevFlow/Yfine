import datetime as dt
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from schemas.tag import TagRead
from schemas.validators import validate_note


class MovementCreate(BaseModel):
    source_id: Optional[int] = None
    amount: float = Field(gt=0)
    direction: Literal["in", "out"]
    date: dt.date
    note: Optional[str] = None
    tag_ids: list[int] = []

    @field_validator("note")
    @classmethod
    def check_note(cls, v):
        return validate_note(v)


class MovementUpdate(BaseModel):
    source_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, gt=0)
    direction: Optional[Literal["in", "out"]] = None
    date: Optional[dt.date] = None
    note: Optional[str] = None
    tag_ids: Optional[list[int]] = None

    @field_validator("note")
    @classmethod
    def check_note(cls, v):
        return validate_note(v)


class MovementRead(BaseModel):
    id: int
    source_id: Optional[int]
    source_name: str
    amount: float
    direction: str
    date: dt.date
    note: Optional[str]
    transfer_pair_id: Optional[int]
    tags: list[TagRead]
    created_at: dt.datetime
    updated_at: dt.datetime


class TransferCreate(BaseModel):
    from_source_id: int
    to_source_id: int
    amount: float = Field(gt=0)
    date: dt.date
    note: Optional[str] = None
    tag_ids: list[int] = []

    @field_validator("note")
    @classmethod
    def check_note(cls, v):
        return validate_note(v)

    def model_post_init(self, __context):
        if self.from_source_id == self.to_source_id:
            raise ValueError("from_source_id and to_source_id must be different")


class TransferUpdate(BaseModel):
    from_source_id: Optional[int] = None
    to_source_id: Optional[int] = None
    amount: Optional[float] = Field(default=None, gt=0)
    date: Optional[dt.date] = None
    note: Optional[str] = None
    tag_ids: Optional[list[int]] = None

    @field_validator("note")
    @classmethod
    def check_note(cls, v):
        return validate_note(v)
