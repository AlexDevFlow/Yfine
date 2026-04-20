"""Tests for the CSV importer: happy paths, sign conventions, header inference."""
from services.importers.csv_parser import CsvParser


def test_csv_parser_happy_path():
    raw = (
        b"date,amount,description,currency\n"
        b"2024-01-15,100.00,Salary,EUR\n"
        b"2024-01-16,-45.20,Groceries,EUR\n"
        b"2024-01-17,25.00,Refund,EUR\n"
    )
    parser = CsvParser()
    result = parser.parse(raw)
    assert len(result.movements) == 3
    m0 = result.movements[0]
    assert m0.direction == "in"
    assert m0.amount == 100.0
    assert m0.note == "Salary"
    assert m0.currency == "EUR"
    m1 = result.movements[1]
    assert m1.direction == "out"
    assert m1.amount == 45.2
    assert result.detected_currency == "EUR"


def test_csv_parser_in_out_columns():
    raw = (
        b"Date,Outflow,Inflow,Payee\n"
        b"2024-02-01,0,1500,Salary\n"
        b"2024-02-02,200,0,Rent\n"
    )
    result = CsvParser().parse(raw)
    assert len(result.movements) == 2
    dirs = [m.direction for m in result.movements]
    assert dirs == ["in", "out"]
    assert result.movements[0].amount == 1500.0
    assert result.movements[1].amount == 200.0


def test_csv_parser_european_decimal():
    raw = (
        b"Data;Importo;Descrizione\n"
        b"15/01/2024;1.234,50;Stipendio\n"
        b"16/01/2024;-45,20;Spesa\n"
    )
    options = {"delimiter": ";", "decimal_separator": ",", "date_format": "%d/%m/%Y"}
    result = CsvParser().parse(raw, options)
    assert len(result.movements) == 2
    assert result.movements[0].amount == 1234.5
    assert result.movements[0].direction == "in"
    assert result.movements[1].amount == 45.2


def test_csv_parser_empty_file():
    result = CsvParser().parse(b"")
    assert result.movements == []
    assert "empty_file" in result.warnings


def test_csv_parser_needs_mapping_when_headers_unknown():
    raw = b"foo,bar,baz\n1,2,3\n"
    result = CsvParser().parse(raw)
    assert result.movements == []
    assert any(w.startswith("needs_mapping:") for w in result.warnings)


def test_csv_parser_sniff_detects_csv():
    parser = CsvParser()
    assert parser.sniff(b"date,amount\n2024-01-01,10\n")
    assert not parser.sniff(b"PK\x03\x04")
    assert not parser.sniff(b"OFXHEADER:100\n")


def test_csv_parser_explicit_column_map():
    raw = (
        b"Booking Date,Amount (EUR),Partner Name\n"
        b"2024-03-01,75.50,Coffee Shop\n"
        b"2024-03-02,-20.00,Gym\n"
    )
    options = {
        "column_map": {"date": "Booking Date", "amount": "Amount (EUR)", "note": "Partner Name"},
        "date_format": "%Y-%m-%d",
    }
    result = CsvParser().parse(raw, options)
    assert len(result.movements) == 2
    assert result.movements[0].note == "Coffee Shop"
