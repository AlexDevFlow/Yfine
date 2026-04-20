"""Pydantic schemas for the /api/imports endpoints."""
from datetime import date as date_type, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FormatInfo(BaseModel):
    key: str
    display_name: str
    extensions: list[str]


class PresetInfo(BaseModel):
    id: str
    display_name: str
    bank: Optional[str] = None
    format: str
    currency_hint: Optional[str] = None
    source_hint: Optional[str] = None


class PreviewRow(BaseModel):
    index: int
    date: date_type
    amount: float
    direction: Literal["in", "out"]
    note: Optional[str] = None
    currency: Optional[str] = None
    is_duplicate: bool = False


class ImportPreviewResponse(BaseModel):
    preview_id: str
    detected_format: str
    detected_preset: Optional[PresetInfo] = None
    row_count: int
    total_in: float
    total_out: float
    detected_currency: Optional[str] = None
    detected_source_hint: Optional[str] = None
    duplicate_count: int = 0
    default_include: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rows: list[PreviewRow] = Field(default_factory=list)
    needs_mapping: bool = False
    headers: Optional[list[str]] = None


class NewSource(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(min_length=3, max_length=3)
    starting_balance: float = 0.0


class ImportCommitRequest(BaseModel):
    preview_id: str
    source_id: Optional[int] = None
    new_source: Optional[NewSource] = None
    include_indices: list[int] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    exclude_from_stats: bool = False


class ImportCommitResponse(BaseModel):
    imported: int
    skipped: int
    source_id: int
    undo_token: str
    undo_expires_at: datetime


class ImportUndoRequest(BaseModel):
    undo_token: str


class ImportUndoResponse(BaseModel):
    deleted: int


class ImportPreviewOptions(BaseModel):
    """Optional CSV/XLSX options passed as JSON in the preview request body."""
    delimiter: Optional[str] = None
    encoding: Optional[str] = None
    date_format: Optional[str] = None
    decimal_separator: Optional[Literal[",", "."]] = None
    column_map: Optional[dict[str, str]] = None
    sign_convention: Optional[Literal["signed", "in_out_columns", "positive_with_type"]] = None
    skip_rows: Optional[int] = None
    sheet_name: Optional[str] = None
    header_row: Optional[int] = None
