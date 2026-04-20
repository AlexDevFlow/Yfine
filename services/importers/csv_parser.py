"""Generic CSV parser with configurable column mapping and preset auto-detection."""
import csv
import hashlib
import io
from datetime import date, datetime

from services.importers.base import ParsedMovement, ParseResult

_CANONICAL_FIELDS = ("date", "amount", "direction", "note", "currency", "amount_in", "amount_out")

_HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "date": (
        "date", "data", "datum", "fecha", "transaction date", "posted date",
        "started date", "completed date", "data valuta", "data operazione",
        "data contabile", "booking date", "value date", "дата",
    ),
    "amount": (
        "amount", "importo", "betrag", "valor", "monto", "total", "montant",
    ),
    "amount_in": (
        "credit", "credito", "entrata", "entrate", "income", "in", "eingang",
        "haber", "accrediti", "inflow", "deposit",
    ),
    "amount_out": (
        "debit", "debito", "uscita", "uscite", "expense", "out", "ausgang",
        "soll", "addebiti", "outflow", "withdrawal",
    ),
    "note": (
        "note", "description", "descrizione", "memo", "detail", "details",
        "payee", "merchant", "name", "narration", "reference", "concepto",
        "causale", "descripcion",
    ),
    "currency": (
        "currency", "valuta", "ccy", "moneda", "waehrung", "wahrung", "devise",
    ),
    "direction": (
        "direction", "type", "tipo", "dir",
    ),
}


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().replace("_", " ").replace("-", " ")


def _guess_column_map(headers: list[str]) -> dict[str, str] | None:
    """Return {canonical_field: actual_header_name} or None when not enough matches."""
    normalized = {_normalize_header(h): h for h in headers if h}
    result: dict[str, str] = {}
    for field, syns in _HEADER_SYNONYMS.items():
        for syn in syns:
            if syn in normalized:
                result[field] = normalized[syn]
                break
    has_amount = "amount" in result or ("amount_in" in result and "amount_out" in result)
    if "date" in result and has_amount:
        return result
    return None


def _try_parse_date(s: str, date_format: str | None) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    if date_format:
        try:
            return datetime.strptime(s, date_format).date()
        except Exception:
            pass
    for fmt in (
        "%Y-%m-%d", "%Y/%m/%d",
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%m/%d/%Y", "%m-%d-%Y",
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    try:
        from dateutil import parser as du_parser
        return du_parser.parse(s, dayfirst=True).date()
    except Exception:
        return None


def _parse_amount(s: str, decimal_separator: str = ".") -> float | None:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace("\u00a0", "").replace(" ", "")
    for symbol in ("€", "$", "£", "¥", "CHF", "USD", "EUR", "GBP"):
        s = s.replace(symbol, "")
    if decimal_separator == ",":
        s = s.replace(".", "").replace(",", ".")
    else:
        if s.count(",") and s.count("."):
            s = s.replace(",", "")
        elif s.count(",") and not s.count("."):
            s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def _detect_dialect(sample: str) -> csv.Dialect:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        class _Dialect(csv.Dialect):
            delimiter = ","
            quotechar = '"'
            doublequote = True
            skipinitialspace = True
            lineterminator = "\n"
            quoting = csv.QUOTE_MINIMAL
        dialect = _Dialect
    return dialect


class CsvParser:
    format_key = "csv"
    display_name = "CSV"
    file_extensions = (".csv",)

    def sniff(self, raw: bytes) -> bool:
        head = raw[:2048].lstrip()
        if not head:
            return False
        if head.startswith(b"<") or head.startswith(b"PK") or head.startswith(b"OFXHEADER"):
            return False
        try:
            text = head.decode("utf-8", errors="replace")
        except Exception:
            return False
        if "\n" not in text and "\r" not in text and len(text) < 20:
            return False
        first_line = text.splitlines()[0] if text.splitlines() else ""
        return any(sep in first_line for sep in (",", ";", "\t", "|"))

    def parse(self, raw: bytes, options: dict | None = None) -> ParseResult:
        opts = options or {}
        encoding = opts.get("encoding") or "utf-8"
        delimiter = opts.get("delimiter")
        date_format = opts.get("date_format")
        decimal_separator = opts.get("decimal_separator", ".")
        column_map = opts.get("column_map")
        skip_rows = int(opts.get("skip_rows", 0) or 0)
        sign_convention = opts.get("sign_convention")  # "signed" | "in_out_columns" | "positive_with_type"

        try:
            text = raw.decode(encoding, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        if text.startswith("\ufeff"):
            text = text[1:]

        lines = text.splitlines()
        if skip_rows:
            lines = lines[skip_rows:]
        text = "\n".join(lines)

        if delimiter:
            class _CustomDialect(csv.Dialect):
                pass
            _CustomDialect.delimiter = delimiter
            _CustomDialect.quotechar = '"'
            _CustomDialect.doublequote = True
            _CustomDialect.skipinitialspace = True
            _CustomDialect.lineterminator = "\n"
            _CustomDialect.quoting = csv.QUOTE_MINIMAL
            dialect = _CustomDialect
        else:
            dialect = _detect_dialect(text[:4096])

        reader = csv.reader(io.StringIO(text), dialect=dialect)
        rows = list(reader)
        if not rows:
            return ParseResult(movements=[], warnings=["empty_file"])

        headers = rows[0]
        data_rows = rows[1:]

        if not column_map:
            column_map = _guess_column_map(headers)
        if not column_map:
            return ParseResult(
                movements=[],
                warnings=[f"needs_mapping:{','.join(headers)}"],
            )

        header_index: dict[str, int] = {}
        for field, header_name in column_map.items():
            try:
                idx = headers.index(header_name)
            except ValueError:
                return ParseResult(
                    movements=[],
                    warnings=[f"column_not_found:{header_name}"],
                )
            header_index[field] = idx

        detected_currency: str | None = None
        movements: list[ParsedMovement] = []
        warnings: list[str] = []

        for row_num, row in enumerate(data_rows, start=2):
            if not row or all((c or "").strip() == "" for c in row):
                continue
            raw_row = dialect.delimiter.join(row).encode("utf-8")
            raw_hash = hashlib.sha256(raw_row).hexdigest()

            d_raw = row[header_index["date"]] if "date" in header_index and header_index["date"] < len(row) else ""
            parsed_date = _try_parse_date(d_raw, date_format)
            if not parsed_date:
                warnings.append(f"row_{row_num}_bad_date")
                continue

            amount: float | None = None
            direction: str | None = None

            if "amount_in" in header_index and "amount_out" in header_index:
                in_raw = row[header_index["amount_in"]] if header_index["amount_in"] < len(row) else ""
                out_raw = row[header_index["amount_out"]] if header_index["amount_out"] < len(row) else ""
                in_val = _parse_amount(in_raw, decimal_separator)
                out_val = _parse_amount(out_raw, decimal_separator)
                if in_val and in_val > 0:
                    amount = in_val
                    direction = "in"
                elif out_val and out_val > 0:
                    amount = out_val
                    direction = "out"
            else:
                amount_raw = row[header_index["amount"]] if "amount" in header_index and header_index["amount"] < len(row) else ""
                a = _parse_amount(amount_raw, decimal_separator)
                if a is None:
                    warnings.append(f"row_{row_num}_bad_amount")
                    continue
                if sign_convention == "positive_with_type" and "direction" in header_index:
                    dir_raw = (row[header_index["direction"]] or "").strip().lower()
                    if dir_raw in ("in", "credit", "income", "entrata", "credito"):
                        direction = "in"
                    elif dir_raw in ("out", "debit", "expense", "uscita", "debito"):
                        direction = "out"
                    else:
                        direction = "in" if a >= 0 else "out"
                    amount = abs(a)
                else:
                    direction = "in" if a >= 0 else "out"
                    amount = abs(a)

            if amount is None or amount == 0 or direction not in ("in", "out"):
                warnings.append(f"row_{row_num}_zero_or_invalid")
                continue

            note = None
            if "note" in header_index and header_index["note"] < len(row):
                note = (row[header_index["note"]] or "").strip() or None

            currency = None
            if "currency" in header_index and header_index["currency"] < len(row):
                currency = (row[header_index["currency"]] or "").strip().upper() or None
                if currency and not detected_currency:
                    detected_currency = currency

            movements.append(ParsedMovement(
                date=parsed_date,
                amount=round(amount, 2),
                direction=direction,
                note=note,
                raw_hash=raw_hash,
                currency=currency,
            ))

        return ParseResult(
            movements=movements,
            detected_currency=detected_currency,
            detected_source_hint=None,
            warnings=warnings,
        )
