"""Tests for the XLSX importer — uses openpyxl in-memory workbooks."""
import io
from datetime import date

import openpyxl

from services.importers.xlsx_parser import XlsxParser


def _make_workbook(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_happy_path():
    data = _make_workbook([
        ["Date", "Amount", "Description", "Currency"],
        [date(2024, 1, 15), 100.0, "Salary", "EUR"],
        [date(2024, 1, 16), -20.0, "Coffee", "EUR"],
    ])
    result = XlsxParser().parse(data)
    assert len(result.movements) == 2
    assert result.movements[0].direction == "in"
    assert result.movements[0].amount == 100.0
    assert result.movements[1].direction == "out"
    assert result.detected_currency == "EUR"


def test_xlsx_sniff_accepts_xlsx():
    data = _make_workbook([["Date", "Amount"], [date(2024, 1, 1), 1.0]])
    assert XlsxParser().sniff(data)
    assert not XlsxParser().sniff(b"plain text")


def test_xlsx_needs_mapping_when_unknown_headers():
    data = _make_workbook([["foo", "bar"], [1, 2]])
    result = XlsxParser().parse(data)
    assert result.movements == []
    assert any(w.startswith("needs_mapping:") for w in result.warnings)
