"""Base types for parsers: ParsedMovement, ParseResult, BaseParser protocol."""
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ParsedMovement:
    date: date
    amount: float              # always positive
    direction: str             # "in" | "out"
    note: str | None
    raw_hash: str              # stable hash of source-file row bytes
    currency: str | None = None
    external_ref: str | None = None


@dataclass
class ParseResult:
    movements: list[ParsedMovement]
    detected_currency: str | None = None
    detected_source_hint: str | None = None
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class BaseParser(Protocol):
    format_key: str
    display_name: str
    file_extensions: tuple[str, ...]

    def sniff(self, raw: bytes) -> bool: ...

    def parse(self, raw: bytes, options: dict | None = None) -> ParseResult: ...
