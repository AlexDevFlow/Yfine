"""Multi-format import pipeline for bank statements and other apps."""
from services.importers.base import BaseParser, ParsedMovement, ParseResult
from services.importers.csv_parser import CsvParser
from services.importers.ofx_parser import OfxParser
from services.importers.xlsx_parser import XlsxParser

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB

FORMAT_REGISTRY: dict[str, type[BaseParser]] = {
    "csv": CsvParser,
    "ofx": OfxParser,
    "qfx": OfxParser,
    "xlsx": XlsxParser,
}

_DISPLAY = {
    "csv": "CSV",
    "ofx": "OFX",
    "qfx": "QFX",
    "xlsx": "Excel (XLSX)",
}

_EXTENSIONS = {
    "csv": (".csv",),
    "ofx": (".ofx",),
    "qfx": (".qfx",),
    "xlsx": (".xlsx",),
}


def get_parser(key: str) -> BaseParser:
    cls = FORMAT_REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"Unknown format: {key}")
    return cls()


def list_formats() -> list[dict]:
    seen: list[dict] = []
    added: set[str] = set()
    for key in FORMAT_REGISTRY.keys():
        if key in added:
            continue
        added.add(key)
        seen.append({
            "key": key,
            "display_name": _DISPLAY.get(key, key.upper()),
            "extensions": list(_EXTENSIONS.get(key, ())),
        })
    return seen


def detect_format(filename: str, raw: bytes) -> str | None:
    """Detect format from extension first, then by content sniff."""
    if filename:
        lower = filename.lower()
        for key, exts in _EXTENSIONS.items():
            if any(lower.endswith(ext) for ext in exts):
                return key
    for key in ("ofx", "xlsx", "csv"):
        parser = get_parser(key)
        try:
            if parser.sniff(raw):
                return key
        except Exception:
            continue
    return None


__all__ = [
    "BaseParser", "ParsedMovement", "ParseResult",
    "CsvParser", "OfxParser", "XlsxParser",
    "FORMAT_REGISTRY", "MAX_UPLOAD_BYTES",
    "get_parser", "list_formats", "detect_format",
]
