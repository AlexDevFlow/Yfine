"""Price fetching for portfolio holdings.

Crypto prices come from CoinGecko (no API key, public demo tier).
Stock/ETF prices come from Yahoo Finance via the `yfinance` package.

Both are opt-in: fetching only happens when
``Setting.portfolio_prices_enabled`` is True. An in-memory TTL cache
smooths out rate limits and avoids hitting the network on every
dashboard render.

All network calls are wrapped in try/except so that API outages never
break the UI: holdings just keep showing the last cached price.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 10 * 60  # 10 minutes
_HTTP_TIMEOUT = 8.0

# Minimal CoinGecko symbol → id map for the most common crypto.
# If a symbol isn't here we fall back to the `/search` endpoint.
_COINGECKO_ID_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "ADA": "cardano",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "BNB": "binancecoin",
    "TRX": "tron",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ALGO": "algorand",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "FIL": "filecoin",
    "HBAR": "hedera-hashgraph",
    "VET": "vechain",
    "ICP": "internet-computer",
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
}

# { (symbol_upper, asset_class, vs_currency): (price_float, unix_ts) }
_price_cache: dict[tuple[str, str, str], tuple[float, float]] = {}
_cache_lock = threading.Lock()


def are_prices_enabled(session) -> bool:
    """Check the user's preference before any network call."""
    from services.settings import get_settings
    try:
        return bool(get_settings(session).portfolio_prices_enabled)
    except Exception:
        return False


def _cache_get(symbol: str, asset_class: str, vs_currency: str) -> Optional[float]:
    key = (symbol.upper(), asset_class, vs_currency.upper())
    with _cache_lock:
        hit = _price_cache.get(key)
    if not hit:
        return None
    price, ts = hit
    if time.time() - ts > _CACHE_TTL_SECONDS:
        return None
    return price


def _cache_put(symbol: str, asset_class: str, vs_currency: str, price: float) -> None:
    key = (symbol.upper(), asset_class, vs_currency.upper())
    with _cache_lock:
        _price_cache[key] = (price, time.time())


def clear_cache() -> None:
    with _cache_lock:
        _price_cache.clear()


def _coingecko_id_for(symbol: str) -> Optional[str]:
    sym = symbol.upper()
    if sym in _COINGECKO_ID_MAP:
        return _COINGECKO_ID_MAP[sym]
    # Fallback: call /search and pick the first coin result whose symbol matches.
    try:
        import httpx
    except Exception:
        return None
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/search",
            params={"query": symbol},
            timeout=_HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        for coin in data.get("coins", []):
            if coin.get("symbol", "").upper() == sym:
                return coin.get("id")
    except Exception:
        _logger.warning("CoinGecko /search failed for %s", symbol, exc_info=True)
    return None


def fetch_crypto_price(symbol: str, vs_currency: str = "usd") -> Optional[float]:
    """Return the current price for a crypto symbol, or None on failure."""
    cached = _cache_get(symbol, "crypto", vs_currency)
    if cached is not None:
        return cached
    try:
        import httpx
    except Exception:
        _logger.info("httpx not installed — crypto prices disabled")
        return None
    cg_id = _coingecko_id_for(symbol)
    if not cg_id:
        return None
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": cg_id, "vs_currencies": vs_currency.lower()},
            timeout=_HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        price = data.get(cg_id, {}).get(vs_currency.lower())
        if price is None:
            return None
        price = float(price)
        _cache_put(symbol, "crypto", vs_currency, price)
        return price
    except Exception:
        _logger.warning("CoinGecko price fetch failed for %s", symbol, exc_info=True)
        return None


def fetch_crypto_prices_batch(symbols: list[str], vs_currency: str = "usd") -> dict[str, float]:
    """Fetch many crypto prices in a single CoinGecko call. Cached hits are skipped."""
    result: dict[str, float] = {}
    missing: list[tuple[str, str]] = []  # (symbol, cg_id)
    for sym in symbols:
        cached = _cache_get(sym, "crypto", vs_currency)
        if cached is not None:
            result[sym.upper()] = cached
            continue
        cg_id = _coingecko_id_for(sym)
        if cg_id:
            missing.append((sym.upper(), cg_id))

    if not missing:
        return result

    try:
        import httpx
    except Exception:
        return result

    ids = ",".join({cg for _, cg in missing})
    try:
        r = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids, "vs_currencies": vs_currency.lower()},
            timeout=_HTTP_TIMEOUT,
        )
        if r.status_code != 200:
            return result
        data = r.json()
        for sym, cg_id in missing:
            price = data.get(cg_id, {}).get(vs_currency.lower())
            if price is not None:
                p = float(price)
                result[sym] = p
                _cache_put(sym, "crypto", vs_currency, p)
    except Exception:
        _logger.warning("CoinGecko batch fetch failed", exc_info=True)
    return result


def fetch_stock_price(symbol: str) -> Optional[float]:
    """Return the latest price for a stock/ETF symbol via yfinance, or None.

    Note: yfinance returns prices in the ticker's native currency
    (AAPL → USD, ENI.MI → EUR). We do not convert — the caller is
    expected to record `holding.currency` accordingly.
    """
    cached = _cache_get(symbol, "stock", "native")
    if cached is not None:
        return cached
    try:
        import yfinance as yf
    except Exception:
        _logger.info("yfinance not installed — stock prices disabled")
        return None
    try:
        ticker = yf.Ticker(symbol)
        # fast_info is cheap and avoids pulling the full profile
        info = getattr(ticker, "fast_info", None)
        price = None
        if info is not None:
            for key in ("last_price", "regular_market_price", "previous_close"):
                try:
                    v = info[key] if hasattr(info, "__getitem__") else getattr(info, key, None)
                except Exception:
                    v = None
                if v is not None:
                    price = float(v)
                    break
        if price is None:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        if price is None:
            return None
        _cache_put(symbol, "stock", "native", price)
        return price
    except Exception:
        _logger.warning("yfinance fetch failed for %s", symbol, exc_info=True)
        return None


def refresh_holding_price(holding) -> bool:
    """Refresh a single holding's `last_price`. Returns True on success.

    Respects ``manual_price``: if set, the user controls the price.
    Does NOT commit — the caller decides when to persist.
    """
    if holding.manual_price:
        return False
    if holding.asset_class == "crypto":
        price = fetch_crypto_price(holding.symbol, holding.currency or "usd")
    elif holding.asset_class == "stock":
        price = fetch_stock_price(holding.symbol)
    else:
        return False
    if price is None:
        return False
    holding.last_price = price
    holding.last_price_at = datetime.utcnow()
    holding.updated_at = datetime.utcnow()
    return True


def refresh_all_holdings(session) -> int:
    """Refresh every holding's price if prices are enabled. Returns the number updated."""
    if not are_prices_enabled(session):
        return 0
    from models.portfolio import Holding
    from sqlmodel import select
    holdings = list(session.exec(select(Holding)).all())
    if not holdings:
        return 0

    # Batch crypto by vs_currency for fewer HTTP calls.
    crypto_by_currency: dict[str, list] = {}
    stock_holdings: list = []
    for h in holdings:
        if h.manual_price:
            continue
        if h.asset_class == "crypto":
            crypto_by_currency.setdefault((h.currency or "USD").upper(), []).append(h)
        elif h.asset_class == "stock":
            stock_holdings.append(h)

    updated = 0
    now = datetime.utcnow()

    from services import portfolios as portfolio_service

    for vs_currency, hs in crypto_by_currency.items():
        symbols = [h.symbol for h in hs]
        prices = fetch_crypto_prices_batch(symbols, vs_currency=vs_currency)
        for h in hs:
            p = prices.get(h.symbol.upper())
            if p is not None:
                h.last_price = p
                h.last_price_at = now
                h.updated_at = now
                session.add(h)
                portfolio_service.upsert_price_snapshot(session, h)
                updated += 1

    for h in stock_holdings:
        p = fetch_stock_price(h.symbol)
        if p is not None:
            h.last_price = p
            h.last_price_at = now
            h.updated_at = now
            session.add(h)
            portfolio_service.upsert_price_snapshot(session, h)
            updated += 1

    if updated:
        session.commit()
    return updated
