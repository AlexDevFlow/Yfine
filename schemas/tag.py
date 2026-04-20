from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from schemas.validators import validate_name


class TagCreate(BaseModel):
    name: str
    color: Optional[str] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        return validate_name(v)

    @field_validator("color")
    @classmethod
    def check_color(cls, v):
        if v is not None:
            v = v.strip()
            if v and not v.startswith("#"):
                raise ValueError("Color must be a hex code starting with #")
            if v and len(v) not in (4, 7, 9):
                raise ValueError("Color must be #RGB, #RRGGBB, or #RRGGBBAA")
        return v


class TagUpdate(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v):
        if v is not None:
            return validate_name(v)
        return v

    @field_validator("color")
    @classmethod
    def check_color(cls, v):
        if v is not None:
            v = v.strip()
            if v and not v.startswith("#"):
                raise ValueError("Color must be a hex code starting with #")
            if v and len(v) not in (4, 7, 9):
                raise ValueError("Color must be #RGB, #RRGGBB, or #RRGGBBAA")
        return v


class TagRead(BaseModel):
    id: int
    name: str
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime
