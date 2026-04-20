"""Tests for exchange rates service — CRUD, convert, reverse, rates map."""
import pytest
from sqlmodel import select

from models.exchange_rate import ExchangeRate
from schemas.exchange_rate import ExchangeRateCreate, ExchangeRateUpdate
from services.exchange_rates import (
    convert,
    delete_rate,
    get_rate,
    get_rate_by_id,
    get_rates_map,
    list_rates,
    set_rate,
    update_rate,
)


# ── CRUD ─────────────────────────────────────────────────────────

class TestExchangeRateCRUD:
    def test_set_rate_creates(self, session):
        r = set_rate(session, ExchangeRateCreate(
            from_currency="EUR", to_currency="USD", rate=1.08,
        ))
        assert r.id is not None
        assert r.rate == 1.08

    def test_set_rate_upserts(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.12))
        rates = list_rates(session)
        eur_usd = [r for r in rates if r.from_currency == "EUR" and r.to_currency == "USD"]
        assert len(eur_usd) == 1
        assert eur_usd[0].rate == 1.12

    def test_set_rate_same_currency_rejected(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="EUR", rate=1.0))
        assert exc.value.status_code == 422

    def test_get_rate_by_pair(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="GBP", to_currency="USD", rate=1.27))
        r = get_rate(session, "GBP", "USD")
        assert r is not None
        assert r.rate == 1.27

    def test_get_rate_by_pair_not_found(self, session):
        assert get_rate(session, "EUR", "JPY") is None

    def test_get_rate_by_id(self, session):
        created = set_rate(session, ExchangeRateCreate(
            from_currency="EUR", to_currency="GBP", rate=0.86,
        ))
        found = get_rate_by_id(session, created.id)
        assert found.rate == 0.86

    def test_get_rate_by_id_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_rate_by_id(session, 9999)
        assert exc.value.status_code == 404

    def test_update_rate(self, session):
        r = set_rate(session, ExchangeRateCreate(
            from_currency="EUR", to_currency="CHF", rate=0.97,
        ))
        updated = update_rate(session, r.id, ExchangeRateUpdate(rate=0.95))
        assert updated.rate == 0.95

    def test_delete_rate(self, session):
        r = set_rate(session, ExchangeRateCreate(
            from_currency="EUR", to_currency="SEK", rate=11.5,
        ))
        delete_rate(session, r.id)
        assert session.get(ExchangeRate, r.id) is None

    def test_delete_rate_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            delete_rate(session, 9999)

    def test_list_rates(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="GBP", rate=0.86))
        rates = list_rates(session)
        assert len(rates) == 2


# ── Conversion ───────────────────────────────────────────────────

class TestConversion:
    def test_direct_conversion(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        result = convert(session, 100.0, "EUR", "USD")
        assert result == 108.0

    def test_reverse_conversion(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        result = convert(session, 108.0, "USD", "EUR")
        assert result == 100.0

    def test_same_currency_identity(self, session):
        assert convert(session, 42.0, "EUR", "EUR") == 42.0

    def test_no_rate_returns_none(self, session):
        assert convert(session, 100.0, "EUR", "JPY") is None

    def test_conversion_rounding(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="JPY", rate=162.35))
        result = convert(session, 33.33, "EUR", "JPY")
        # Should be rounded to 2 decimal places
        assert result == round(33.33 * 162.35, 2)

    def test_small_amount_conversion(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="BTC", to_currency="USD", rate=65000.0))
        result = convert(session, 0.001, "BTC", "USD")
        assert result == 65.0

    def test_zero_amount_conversion(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        result = convert(session, 0.0, "EUR", "USD")
        assert result == 0.0


# ── Rates Map ────────────────────────────────────────────────────

class TestRatesMap:
    def test_rates_map_includes_reverse(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        rmap = get_rates_map(session)
        assert ("EUR", "USD") in rmap
        assert ("USD", "EUR") in rmap
        assert rmap[("EUR", "USD")] == 1.08
        assert abs(rmap[("USD", "EUR")] - round(1 / 1.08, 6)) < 0.000001

    def test_rates_map_empty(self, session):
        assert get_rates_map(session) == {}

    def test_rates_map_multiple_pairs(self, session):
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="GBP", rate=0.86))
        rmap = get_rates_map(session)
        # 2 pairs * 2 (direct + reverse) = 4 entries
        assert len(rmap) == 4
