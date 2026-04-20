import json
import os
from datetime import date, datetime
from pathlib import Path

from database import BASE_DIR

_translations: dict[str, str] = {}


def load_translations():
    global _translations
    locale = os.environ.get("YFINE_LOCALE", "en")
    locale_file = BASE_DIR / "locales" / f"{locale}.json"
    if locale_file.exists():
        with open(locale_file, "r", encoding="utf-8") as f:
            _translations = json.load(f)


def _(key: str) -> str:
    if not _translations:
        load_translations()
    return _translations.get(key, key)


def set_locale(locale: str):
    global _translations, _current_locale
    locale_file = BASE_DIR / "locales" / f"{locale}.json"
    if locale_file.exists():
        with open(locale_file, "r", encoding="utf-8") as f:
            _translations = json.load(f)
        _current_locale = locale


def get_locale() -> str:
    return _current_locale


_CURRENCY_FLAGS = {
    "EUR": "\U0001F1EA\U0001F1FA", "USD": "\U0001F1FA\U0001F1F8", "GBP": "\U0001F1EC\U0001F1E7",
    "CHF": "\U0001F1E8\U0001F1ED", "JPY": "\U0001F1EF\U0001F1F5", "CAD": "\U0001F1E8\U0001F1E6",
    "AUD": "\U0001F1E6\U0001F1FA", "CNY": "\U0001F1E8\U0001F1F3", "INR": "\U0001F1EE\U0001F1F3",
    "BRL": "\U0001F1E7\U0001F1F7", "KRW": "\U0001F1F0\U0001F1F7", "MXN": "\U0001F1F2\U0001F1FD",
    "SEK": "\U0001F1F8\U0001F1EA", "NOK": "\U0001F1F3\U0001F1F4", "DKK": "\U0001F1E9\U0001F1F0",
    "PLN": "\U0001F1F5\U0001F1F1", "CZK": "\U0001F1E8\U0001F1FF", "HUF": "\U0001F1ED\U0001F1FA",
    "RON": "\U0001F1F7\U0001F1F4", "BGN": "\U0001F1E7\U0001F1EC", "HRK": "\U0001F1ED\U0001F1F7",
    "TRY": "\U0001F1F9\U0001F1F7", "RUB": "\U0001F1F7\U0001F1FA", "ZAR": "\U0001F1FF\U0001F1E6",
    "NZD": "\U0001F1F3\U0001F1FF", "SGD": "\U0001F1F8\U0001F1EC", "HKD": "\U0001F1ED\U0001F1F0",
    "TWD": "\U0001F1F9\U0001F1FC", "THB": "\U0001F1F9\U0001F1ED", "IDR": "\U0001F1EE\U0001F1E9",
    "MYR": "\U0001F1F2\U0001F1FE", "PHP": "\U0001F1F5\U0001F1ED", "ARS": "\U0001F1E6\U0001F1F7",
    "CLP": "\U0001F1E8\U0001F1F1", "COP": "\U0001F1E8\U0001F1F4", "PEN": "\U0001F1F5\U0001F1EA",
    "BTC": "\U000020BF", "ETH": "\U0001F48E",
}


def currency_flag(code: str) -> str:
    """Return the flag emoji for a currency code, or empty string."""
    return _CURRENCY_FLAGS.get(code, "")


_current_locale = "en"

_current_theme = "light"


def set_theme(theme: str):
    global _current_theme
    if theme in ("light", "dark", "system"):
        _current_theme = theme


def get_theme() -> str:
    return _current_theme


_hide_net_worth = False


def set_hide_net_worth(val: bool):
    global _hide_net_worth
    _hide_net_worth = bool(val)


def get_hide_net_worth() -> bool:
    return _hide_net_worth


_last_source_id: int | None = None


def set_last_source_id(val: int | None):
    global _last_source_id
    _last_source_id = val


def get_last_source_id() -> int | None:
    return _last_source_id


_mobile_nav_mode = "sidebar"


def set_mobile_nav_mode(val: str):
    global _mobile_nav_mode
    if val in ("sidebar", "bottom"):
        _mobile_nav_mode = val


def get_mobile_nav_mode() -> str:
    return _mobile_nav_mode


_date_format = "dd/mm/yyyy"

# Map setting values to strftime patterns
_DATE_FORMAT_MAP = {
    "dd/mm/yyyy": ("%d/%m/%Y", "%d/%m/%Y %H:%M"),
    "mm/dd/yyyy": ("%m/%d/%Y", "%m/%d/%Y %H:%M"),
    "yyyy-mm-dd": ("%Y-%m-%d", "%Y-%m-%d %H:%M"),
}


def set_date_format(fmt: str):
    global _date_format
    if fmt in _DATE_FORMAT_MAP:
        _date_format = fmt


def get_date_format() -> str:
    return _date_format


def format_date(value) -> str:
    """Format a date or date-string using the configured format."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value)
        except ValueError:
            return value
    fmt_date, fmt_dt = _DATE_FORMAT_MAP.get(_date_format, ("%d/%m/%Y", "%d/%m/%Y %H:%M"))
    if isinstance(value, datetime):
        return value.strftime(fmt_dt)
    if isinstance(value, date):
        return value.strftime(fmt_date)
    return str(value)


def merge_translations(extra: dict[str, str]):
    """Merge extra translations (e.g. from plugins) into the current dict."""
    global _translations
    if not _translations:
        load_translations()
    _translations.update(extra)


def get_translator():
    load_translations()
    return _
