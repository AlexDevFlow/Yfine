"""Tests for recurring service — CRUD, apply, due date, end_date enforcement."""
from datetime import date, timedelta

import pytest
from sqlmodel import select

from models.movement import Movement
from models.notification import Notification
from models.recurring import RecurringItem
from models.source import Source
from schemas.recurring import RecurringCreate, RecurringUpdate
from services.recurring import (
    apply_recurring_by_id,
    apply_recurring_item,
    compute_next_due_date,
    count_recurring,
    create_recurring,
    delete_recurring,
    enrich_recurring_items,
    get_recurring,
    list_recurring,
    monthly_summary,
    update_recurring,
)


# ── helpers ──────────────────────────────────────────────────────

def _src(session, name="Salary", balance=5000.0):
    s = Source(name=name, currency="EUR", starting_balance=balance)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _recurring(session, source_id=None, name="Rent", frequency="monthly",
               direction="out", amount=500, start=None, end=None,
               apply_mode="confirm"):
    start = start or date.today()
    r = create_recurring(session, RecurringCreate(
        name=name, amount=amount, direction=direction,
        currency="EUR", frequency=frequency,
        start_date=start, end_date=end,
        source_id=source_id, apply_mode=apply_mode,
    ))
    return r


# ── Due Date Computation ────────────────────────────────────────

class TestComputeNextDueDate:
    def test_daily(self):
        d = date(2026, 1, 15)
        assert compute_next_due_date(d, "daily") == date(2026, 1, 16)

    def test_weekly(self):
        d = date(2026, 1, 15)
        assert compute_next_due_date(d, "weekly") == date(2026, 1, 22)

    def test_monthly(self):
        d = date(2026, 1, 31)
        result = compute_next_due_date(d, "monthly")
        assert result.month == 2
        assert result.year == 2026

    def test_monthly_year_wrap(self):
        d = date(2026, 12, 15)
        result = compute_next_due_date(d, "monthly")
        assert result == date(2027, 1, 15)

    def test_yearly(self):
        d = date(2026, 3, 10)
        assert compute_next_due_date(d, "yearly") == date(2027, 3, 10)

    def test_yearly_leap_day(self):
        d = date(2024, 2, 29)
        result = compute_next_due_date(d, "yearly")
        # 2025 has no Feb 29 — dateutil rounds to Feb 28
        assert result == date(2025, 2, 28)

    def test_unknown_frequency_defaults_monthly(self):
        d = date(2026, 5, 1)
        result = compute_next_due_date(d, "unknown")
        assert result == compute_next_due_date(d, "monthly")


# ── CRUD ─────────────────────────────────────────────────────────

class TestRecurringCRUD:
    def test_create(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id)
        assert r.id is not None
        assert r.name == "Rent"
        assert r.next_due_date == r.start_date

    def test_create_without_source(self, session):
        r = _recurring(session, source_id=None, name="External")
        assert r.source_id is None

    def test_list_recurring(self, session):
        _recurring(session, name="A")
        _recurring(session, name="B")
        result = list_recurring(session)
        assert len(result) == 2

    def test_list_recurring_filter_frequency(self, session):
        _recurring(session, name="Daily", frequency="daily")
        _recurring(session, name="Monthly", frequency="monthly")
        result = list_recurring(session, frequency="daily")
        assert len(result) == 1
        assert result[0].name == "Daily"

    def test_list_recurring_filter_direction(self, session):
        _recurring(session, name="Income", direction="in")
        _recurring(session, name="Expense", direction="out")
        result = list_recurring(session, direction="in")
        assert len(result) == 1
        assert result[0].name == "Income"

    def test_count_recurring(self, session):
        _recurring(session, name="A")
        _recurring(session, name="B")
        _recurring(session, name="C", frequency="daily")
        assert count_recurring(session) == 3
        assert count_recurring(session, frequency="daily") == 1

    def test_get_recurring(self, session):
        r = _recurring(session, name="Found")
        assert get_recurring(session, r.id).name == "Found"

    def test_get_recurring_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_recurring(session, 9999)
        assert exc.value.status_code == 404

    def test_update_recurring(self, session):
        r = _recurring(session, name="Old", amount=100)
        updated = update_recurring(session, r.id, RecurringUpdate(name="New", amount=200))
        assert updated.name == "New"
        assert updated.amount == 200

    def test_update_recurring_partial(self, session):
        r = _recurring(session, name="Stable", amount=100)
        updated = update_recurring(session, r.id, RecurringUpdate(amount=150))
        assert updated.name == "Stable"  # unchanged
        assert updated.amount == 150

    def test_delete_recurring(self, session):
        r = _recurring(session, name="ToDelete")
        delete_recurring(session, r.id)
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            get_recurring(session, r.id)


# ── Apply ────────────────────────────────────────────────────────

class TestApplyRecurring:
    def test_apply_creates_movement(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id, name="Salary", direction="in",
                        amount=3000, start=date.today() - timedelta(days=1))
        # Manually set next_due_date to past to allow application
        r.next_due_date = date.today() - timedelta(days=1)
        session.add(r)
        session.commit()

        apply_recurring_item(session, r)
        session.commit()

        mvs = session.exec(select(Movement).where(Movement.source_id == s.id)).all()
        assert len(mvs) == 1
        assert mvs[0].amount == 3000
        assert mvs[0].direction == "in"
        assert "Salary" in mvs[0].note

    def test_apply_creates_notification(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id, start=date.today() - timedelta(days=1))
        r.next_due_date = date.today() - timedelta(days=1)
        session.add(r)
        session.commit()

        apply_recurring_item(session, r)
        session.commit()

        notifs = session.exec(select(Notification)).all()
        assert len(notifs) == 1
        assert notifs[0].type == "info"
        assert "Applied" in notifs[0].title

    def test_apply_advances_due_date(self, session):
        s = _src(session)
        start = date.today() - timedelta(days=31)
        r = _recurring(session, source_id=s.id, frequency="monthly", start=start)
        r.next_due_date = start
        session.add(r)
        session.commit()

        old_due = r.next_due_date
        apply_recurring_item(session, r)
        session.commit()
        session.refresh(r)

        expected = compute_next_due_date(old_due, "monthly")
        assert r.next_due_date == expected

    def test_apply_with_override_amount(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id, amount=100, start=date.today() - timedelta(days=1))
        r.next_due_date = date.today() - timedelta(days=1)
        session.add(r)
        session.commit()

        apply_recurring_item(session, r, override_amount=150)
        session.commit()

        mvs = session.exec(select(Movement)).all()
        assert mvs[0].amount == 150
        assert "adjusted" in mvs[0].note

    def test_apply_with_note(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id, start=date.today() - timedelta(days=1))
        r.next_due_date = date.today() - timedelta(days=1)
        session.add(r)
        session.commit()

        apply_recurring_item(session, r, note="Bonus included")
        session.commit()

        mvs = session.exec(select(Movement)).all()
        assert "Bonus included" in mvs[0].note

    def test_apply_ended_item_raises(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id,
                        start=date(2025, 1, 1), end=date(2025, 6, 1))
        r.next_due_date = date(2025, 7, 1)  # past end_date
        session.add(r)
        session.commit()

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            apply_recurring_item(session, r)
        assert exc.value.status_code == 400

    def test_apply_without_source_no_movement(self, session):
        r = _recurring(session, source_id=None, name="External",
                        start=date.today() - timedelta(days=1))
        r.next_due_date = date.today() - timedelta(days=1)
        session.add(r)
        session.commit()

        apply_recurring_item(session, r)
        session.commit()

        mvs = session.exec(select(Movement)).all()
        assert len(mvs) == 0  # no movement without source
        # But notification still created
        notifs = session.exec(select(Notification)).all()
        assert len(notifs) == 1


# ── Apply By ID ──────────────────────────────────────────────────

class TestApplyRecurringById:
    def test_apply_due_item(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id,
                        start=date.today() - timedelta(days=31))
        # Make it due today or earlier
        r.next_due_date = date.today()
        session.add(r)
        session.commit()

        result = apply_recurring_by_id(session, r.id)
        assert result.next_due_date > date.today()

    def test_apply_future_item_raises(self, session):
        s = _src(session)
        r = _recurring(session, source_id=s.id,
                        start=date.today() + timedelta(days=30))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            apply_recurring_by_id(session, r.id)
        assert exc.value.status_code == 400
        assert "not yet due" in exc.value.detail


# ── Enrichment ───────────────────────────────────────────────────

class TestRecurringEnrichment:
    def test_enrich_with_source(self, session):
        s = _src(session, name="Main Account")
        r = RecurringItem(
            name="Sub", amount=10, direction="out", currency="EUR",
            frequency="monthly", start_date=date.today(),
            next_due_date=date.today() + timedelta(days=15),
            source_id=s.id,
        )
        session.add(r)
        session.commit()
        session.refresh(r)

        enriched = enrich_recurring_items(session, [r])
        assert enriched[0]["source_name"] == "Main Account"
        assert enriched[0]["days_until"] == 15

    def test_enrich_without_source(self, session):
        r = RecurringItem(
            name="External", amount=10, direction="in", currency="EUR",
            frequency="weekly", start_date=date.today(),
            next_due_date=date.today(),
        )
        session.add(r)
        session.commit()
        session.refresh(r)

        enriched = enrich_recurring_items(session, [r])
        assert enriched[0]["source_name"] is None
        assert enriched[0]["days_until"] == 0

    def test_enrich_overdue_negative_days(self, session):
        r = RecurringItem(
            name="Late", amount=10, direction="out", currency="EUR",
            frequency="monthly", start_date=date.today() - timedelta(days=40),
            next_due_date=date.today() - timedelta(days=5),
        )
        session.add(r)
        session.commit()
        session.refresh(r)

        enriched = enrich_recurring_items(session, [r])
        assert enriched[0]["days_until"] == -5


# ── Monthly Summary ──────────────────────────────────────────────

class TestMonthlySummary:
    def test_empty_returns_zero_buckets(self, session):
        summary = monthly_summary(session)
        assert summary["total_count"] == 0
        assert summary["by_currency"] == []
        assert summary["currencies"] == []

    def test_monthly_items_not_multiplied(self, session):
        s = _src(session)
        _recurring(session, source_id=s.id, amount=500, direction="out", frequency="monthly")
        _recurring(session, source_id=s.id, amount=2000, direction="in", frequency="monthly")
        summary = monthly_summary(session)
        assert summary["total_count"] == 2
        assert len(summary["by_currency"]) == 1
        bucket = summary["by_currency"][0]
        assert bucket["currency"] == "EUR"
        assert bucket["outflow"] == 500.0
        assert bucket["inflow"] == 2000.0
        assert bucket["net"] == 1500.0
        assert bucket["count_out"] == 1
        assert bucket["count_in"] == 1

    def test_yearly_divided_by_twelve(self, session):
        s = _src(session)
        # 1200 EUR/year → 100 EUR/month
        _recurring(session, source_id=s.id, amount=1200, direction="out", frequency="yearly")
        summary = monthly_summary(session)
        assert summary["by_currency"][0]["outflow"] == 100.0

    def test_daily_uses_30_44_days_per_month(self, session):
        s = _src(session)
        # 10/day → ~304.38/month
        _recurring(session, source_id=s.id, amount=10, direction="out", frequency="daily")
        summary = monthly_summary(session)
        # 365.25 / 12 ≈ 30.4375, * 10 = 304.375 → rounded to 304.38
        assert summary["by_currency"][0]["outflow"] == 304.38

    def test_weekly_uses_52_weeks_per_year(self, session):
        s = _src(session)
        # 50/week → ~217.41/month (52.1786/12 * 50)
        _recurring(session, source_id=s.id, amount=50, direction="out", frequency="weekly")
        summary = monthly_summary(session)
        assert summary["by_currency"][0]["outflow"] == 217.41

    def test_grouped_by_currency(self, session):
        eur = Source(name="EUR bank", currency="EUR", starting_balance=0)
        usd = Source(name="USD bank", currency="USD", starting_balance=0)
        session.add_all([eur, usd])
        session.commit()
        session.refresh(eur); session.refresh(usd)

        create_recurring(session, RecurringCreate(
            name="EUR rent", amount=500, direction="out", currency="EUR",
            frequency="monthly", start_date=date.today(), source_id=eur.id,
        ))
        create_recurring(session, RecurringCreate(
            name="USD sub", amount=20, direction="out", currency="USD",
            frequency="monthly", start_date=date.today(), source_id=usd.id,
        ))

        summary = monthly_summary(session)
        assert len(summary["by_currency"]) == 2
        currencies = {b["currency"]: b for b in summary["by_currency"]}
        assert currencies["EUR"]["outflow"] == 500.0
        assert currencies["USD"]["outflow"] == 20.0
        assert set(summary["currencies"]) == {"EUR", "USD"}

    def test_net_can_be_negative(self, session):
        s = _src(session)
        _recurring(session, source_id=s.id, amount=1000, direction="out", frequency="monthly")
        _recurring(session, source_id=s.id, amount=100, direction="in", frequency="monthly")
        bucket = monthly_summary(session)["by_currency"][0]
        assert bucket["net"] == -900.0
