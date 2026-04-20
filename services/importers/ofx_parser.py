"""OFX and QFX parser via ofxparse."""
import hashlib
import io

from services.importers.base import ParsedMovement, ParseResult


class OfxParser:
    format_key = "ofx"
    display_name = "OFX / QFX"
    file_extensions = (".ofx", ".qfx")

    def sniff(self, raw: bytes) -> bool:
        head = raw[:1024].lstrip().upper()
        return b"OFXHEADER" in head or b"<OFX>" in head

    def parse(self, raw: bytes, options: dict | None = None) -> ParseResult:
        try:
            from ofxparse import OfxParser as _Ofx
        except ImportError:
            return ParseResult(movements=[], warnings=["ofxparse_not_installed"])

        try:
            ofx = _Ofx.parse(io.BytesIO(raw))
        except Exception as exc:
            return ParseResult(movements=[], warnings=[f"parse_error:{exc.__class__.__name__}"])

        movements: list[ParsedMovement] = []
        detected_currency: str | None = None
        source_hint: str | None = None
        warnings: list[str] = []

        accounts = getattr(ofx, "accounts", None) or ([ofx.account] if getattr(ofx, "account", None) else [])
        if len(accounts) > 1:
            warnings.append("multiple_accounts_merged")

        for account in accounts:
            statement = getattr(account, "statement", None)
            if statement is None:
                continue
            currency = (getattr(statement, "currency", None) or "").upper() or None
            if currency and not detected_currency:
                detected_currency = currency
            institution = getattr(account, "institution", None)
            if institution and not source_hint:
                org = getattr(institution, "organization", None)
                if org:
                    source_hint = org

            for tx in getattr(statement, "transactions", []) or []:
                amt = getattr(tx, "amount", None)
                if amt is None:
                    continue
                try:
                    amt_f = float(amt)
                except Exception:
                    continue
                if amt_f == 0:
                    continue
                direction = "in" if amt_f >= 0 else "out"
                amount = abs(amt_f)

                tx_date = getattr(tx, "date", None)
                if tx_date is None:
                    continue
                try:
                    d = tx_date.date() if hasattr(tx_date, "date") else tx_date
                except Exception:
                    d = tx_date

                memo = getattr(tx, "memo", "") or ""
                payee = getattr(tx, "payee", "") or ""
                note = (payee + (" - " + memo if memo and payee else memo)).strip() or None

                fitid = getattr(tx, "id", None) or ""
                raw_key = f"{fitid}|{d}|{amt_f}|{note or ''}".encode("utf-8")
                raw_hash = hashlib.sha256(raw_key).hexdigest()

                movements.append(ParsedMovement(
                    date=d,
                    amount=round(amount, 2),
                    direction=direction,
                    note=note,
                    raw_hash=raw_hash,
                    currency=currency,
                    external_ref=fitid or None,
                ))

        return ParseResult(
            movements=movements,
            detected_currency=detected_currency,
            detected_source_hint=source_hint,
            warnings=warnings,
        )
