"""Shared validation constants and helpers for Pydantic schemas."""

# ISO 4217 currency codes (common ones supported by the app)
VALID_CURRENCY_CODES = frozenset({
    "EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "CNY", "INR", "BRL",
    "KRW", "MXN", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN",
    "HRK", "TRY", "RUB", "ZAR", "NZD", "SGD", "HKD", "TWD", "THB", "IDR",
    "MYR", "PHP", "ARS", "CLP", "COP", "PEN", "BTC", "ETH", "AED", "SAR",
    "EGP", "NGN", "KES", "GHS", "MAD", "TND", "ILS", "UAH", "ISK", "GEL",
})

MAX_NAME_LENGTH = 200
MAX_NOTE_LENGTH = 1000
MAX_CURRENCY_LENGTH = 5


def validate_currency_code(v: str) -> str:
    v = v.strip().upper()
    if len(v) < 2 or len(v) > MAX_CURRENCY_LENGTH:
        raise ValueError(f"Currency code must be 2-{MAX_CURRENCY_LENGTH} characters")
    if v not in VALID_CURRENCY_CODES:
        raise ValueError(f"Unknown currency code: {v}. Use a valid ISO 4217 code.")
    return v


def validate_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Name cannot be empty")
    if len(v) > MAX_NAME_LENGTH:
        raise ValueError(f"Name must be at most {MAX_NAME_LENGTH} characters")
    return v


def validate_note(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if len(v) > MAX_NOTE_LENGTH:
        raise ValueError(f"Note must be at most {MAX_NOTE_LENGTH} characters")
    return v if v else None
