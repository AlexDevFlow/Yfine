"""Tests for schema validation — edge cases across all schemas."""
from datetime import date

import pytest

from schemas.source import SourceCreate, SourceUpdate
from schemas.movement import MovementCreate, MovementUpdate, TransferCreate
from schemas.tag import TagCreate, TagUpdate
from schemas.recurring import RecurringCreate, RecurringUpdate
from schemas.exchange_rate import ExchangeRateCreate


# ── Source Schemas ────────────────────────────────────────────────

class TestSourceSchemas:
    def test_valid_source(self):
        s = SourceCreate(name="Wallet", currency="eur")
        assert s.currency == "EUR"  # uppercased
        assert s.starting_balance == 0.0

    def test_empty_name(self):
        with pytest.raises(Exception):
            SourceCreate(name="", currency="EUR")

    def test_whitespace_name(self):
        with pytest.raises(Exception):
            SourceCreate(name="   ", currency="EUR")

    def test_long_name(self):
        with pytest.raises(Exception):
            SourceCreate(name="x" * 201, currency="EUR")

    def test_max_length_name(self):
        s = SourceCreate(name="x" * 200, currency="EUR")
        assert len(s.name) == 200

    def test_invalid_currency(self):
        with pytest.raises(Exception):
            SourceCreate(name="Test", currency="INVALID")

    def test_short_currency(self):
        with pytest.raises(Exception):
            SourceCreate(name="Test", currency="E")

    def test_crypto_currency(self):
        s = SourceCreate(name="Crypto", currency="btc")
        assert s.currency == "BTC"

    def test_negative_starting_balance(self):
        s = SourceCreate(name="Debt", currency="EUR", starting_balance=-500)
        assert s.starting_balance == -500

    def test_update_none_fields_ignored(self):
        u = SourceUpdate()
        dump = u.model_dump(exclude_unset=True)
        assert dump == {}

    def test_update_partial(self):
        u = SourceUpdate(name="New")
        dump = u.model_dump(exclude_unset=True)
        assert dump == {"name": "New"}


# ── Movement Schemas ─────────────────────────────────────────────

class TestMovementSchemas:
    def test_valid_movement(self):
        m = MovementCreate(
            source_id=1, amount=99.99, direction="in",
            date=date.today(), note="Salary",
        )
        assert m.amount == 99.99
        assert m.tag_ids == []

    def test_zero_amount_rejected(self):
        with pytest.raises(Exception):
            MovementCreate(amount=0, direction="in", date=date.today())

    def test_negative_amount_rejected(self):
        with pytest.raises(Exception):
            MovementCreate(amount=-10, direction="in", date=date.today())

    def test_invalid_direction(self):
        with pytest.raises(Exception):
            MovementCreate(amount=10, direction="transfer", date=date.today())

    def test_long_note_rejected(self):
        with pytest.raises(Exception):
            MovementCreate(
                amount=10, direction="in", date=date.today(),
                note="x" * 1001,
            )

    def test_max_length_note(self):
        m = MovementCreate(
            amount=10, direction="in", date=date.today(),
            note="x" * 1000,
        )
        assert len(m.note) == 1000

    def test_null_source_allowed(self):
        m = MovementCreate(amount=10, direction="out", date=date.today())
        assert m.source_id is None

    def test_update_no_fields(self):
        u = MovementUpdate()
        dump = u.model_dump(exclude_unset=True)
        assert dump == {}

    def test_with_tag_ids(self):
        m = MovementCreate(
            amount=10, direction="in", date=date.today(),
            tag_ids=[1, 2, 3],
        )
        assert m.tag_ids == [1, 2, 3]


# ── Transfer Schemas ─────────────────────────────────────────────

class TestTransferSchemas:
    def test_valid_transfer(self):
        t = TransferCreate(
            from_source_id=1, to_source_id=2,
            amount=100, date=date.today(),
        )
        assert t.from_source_id != t.to_source_id

    def test_same_source_rejected(self):
        with pytest.raises(ValueError):
            TransferCreate(
                from_source_id=1, to_source_id=1,
                amount=100, date=date.today(),
            )

    def test_zero_amount_rejected(self):
        with pytest.raises(Exception):
            TransferCreate(
                from_source_id=1, to_source_id=2,
                amount=0, date=date.today(),
            )


# ── Tag Schemas ──────────────────────────────────────────────────

class TestTagSchemas:
    def test_valid_tag(self):
        t = TagCreate(name="Food")
        assert t.name == "Food"
        assert t.color is None

    def test_valid_colors(self):
        assert TagCreate(name="A", color="#fff").color == "#fff"
        assert TagCreate(name="B", color="#ff0000").color == "#ff0000"
        assert TagCreate(name="C", color="#ff0000aa").color == "#ff0000aa"

    def test_invalid_color_no_hash(self):
        with pytest.raises(Exception):
            TagCreate(name="Bad", color="ff0000")

    def test_invalid_color_wrong_length(self):
        with pytest.raises(Exception):
            TagCreate(name="Bad", color="#ff00")

    def test_empty_name(self):
        with pytest.raises(Exception):
            TagCreate(name="")

    def test_update_color_only(self):
        u = TagUpdate(color="#abc")
        dump = u.model_dump(exclude_unset=True)
        assert "color" in dump
        assert "name" not in dump


# ── Recurring Schemas ────────────────────────────────────────────

class TestRecurringSchemas:
    def test_valid_recurring(self):
        r = RecurringCreate(
            name="Rent", amount=500, direction="out",
            currency="EUR", frequency="monthly",
            start_date=date(2026, 1, 1),
        )
        assert r.apply_mode == "confirm"  # default
        assert r.alert_days_before == 7  # default
        assert r.alert_if_insufficient is True

    def test_end_before_start_rejected(self):
        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=100, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 1, 1),
            )

    def test_end_equals_start_ok(self):
        r = RecurringCreate(
            name="Once", amount=100, direction="out",
            currency="EUR", frequency="monthly",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
        )
        assert r.end_date == r.start_date

    def test_zero_amount_rejected(self):
        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=0, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date.today(),
            )

    def test_invalid_frequency(self):
        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=100, direction="out",
                currency="EUR", frequency="biweekly",
                start_date=date.today(),
            )

    def test_invalid_apply_mode(self):
        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=100, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date.today(),
                apply_mode="manual",
            )

    def test_alert_days_boundaries(self):
        r = RecurringCreate(
            name="A", amount=100, direction="out",
            currency="EUR", frequency="monthly",
            start_date=date.today(), alert_days_before=0,
        )
        assert r.alert_days_before == 0

        r = RecurringCreate(
            name="B", amount=100, direction="out",
            currency="EUR", frequency="monthly",
            start_date=date.today(), alert_days_before=365,
        )
        assert r.alert_days_before == 365

    def test_alert_days_out_of_range(self):
        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=100, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date.today(), alert_days_before=366,
            )

        with pytest.raises(Exception):
            RecurringCreate(
                name="Bad", amount=100, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date.today(), alert_days_before=-1,
            )


# ── Exchange Rate Schemas ────────────────────────────────────────

class TestExchangeRateSchemas:
    def test_valid_rate(self):
        r = ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08)
        assert r.rate == 1.08

    def test_same_currency_rejected_by_schema(self):
        # The schema allows same currency — validation is in the service layer
        # This test documents that behavior
        r = ExchangeRateCreate(from_currency="EUR", to_currency="EUR", rate=1.0)
        assert r.from_currency == r.to_currency

    def test_zero_rate_rejected(self):
        with pytest.raises(Exception):
            ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=0)

    def test_negative_rate_rejected(self):
        with pytest.raises(Exception):
            ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=-1.5)
