"""Tests for dashboard service — aggregation, net worth, monthly stats."""
from datetime import date, timedelta

import pytest
from sqlmodel import select

from models.movement import Movement
from models.notification import Notification
from models.recurring import RecurringItem
from models.source import Source
from services.dashboard import (
    get_dashboard_stats,
    get_monthly_comparison,
    get_monthly_movements,
    get_monthly_totals,
    get_net_worth_history,
)


# ── helpers ──────────────────────────────────────────────────────

def _src(session, name="Bank", currency="EUR", balance=0.0, exclude=False):
    s = Source(name=name, currency=currency, starting_balance=balance, exclude_from_stats=exclude)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _mv(session, source_id, amount, direction, dt=None, transfer_pair_id=None, exclude=False):
    m = Movement(
        source_id=source_id, amount=amount, direction=direction,
        date=dt or date.today(), transfer_pair_id=transfer_pair_id,
        exclude_from_stats=exclude,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _recurring(session, source_id, name="Sub", next_due=None):
    r = RecurringItem(
        name=name, amount=10, direction="out", currency="EUR",
        frequency="monthly", start_date=date.today(),
        next_due_date=next_due or date.today() + timedelta(days=5),
        source_id=source_id,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ── Dashboard Stats ──────────────────────────────────────────────

class TestDashboardStats:
    def test_empty_dashboard(self, session):
        stats = get_dashboard_stats(session)
        assert stats["source_count"] == 0
        assert stats["movement_count"] == 0
        assert stats["unread_notifications"] == 0
        assert stats["net_worth"] == {}

    def test_net_worth_single_currency(self, session):
        s1 = _src(session, "Bank", "EUR", 1000)
        s2 = _src(session, "Cash", "EUR", 200)
        _mv(session, s1.id, 500, "in")
        _mv(session, s1.id, 100, "out")
        stats = get_dashboard_stats(session)
        # net_worth[EUR] = (1000+500-100) + 200 = 1600
        assert stats["net_worth"]["EUR"] == 1600.0

    def test_net_worth_multi_currency(self, session):
        _src(session, "EUR Bank", "EUR", 1000)
        _src(session, "USD Bank", "USD", 500)
        stats = get_dashboard_stats(session)
        assert "EUR" in stats["net_worth"]
        assert "USD" in stats["net_worth"]
        assert stats["net_worth"]["EUR"] == 1000.0
        assert stats["net_worth"]["USD"] == 500.0

    def test_counts(self, session):
        s = _src(session)
        _mv(session, s.id, 10, "in")
        _mv(session, s.id, 20, "out")
        n = Notification(type="alert", title="Test", body="body", is_read=False)
        session.add(n)
        session.commit()
        stats = get_dashboard_stats(session)
        assert stats["source_count"] == 1
        assert stats["movement_count"] == 2
        assert stats["unread_notifications"] == 1

    def test_monthly_income_expense(self, session):
        s = _src(session, "Bank", "EUR")
        _mv(session, s.id, 3000, "in")   # this month
        _mv(session, s.id, 500, "out")    # this month
        stats = get_dashboard_stats(session)
        assert stats["month_income"].get("EUR", 0) == 3000.0
        assert stats["month_expense"].get("EUR", 0) == 500.0

    def test_monthly_excludes_transfers(self, session):
        s1 = _src(session, "A")
        s2 = _src(session, "B")
        # Create transfer (has transfer_pair_id set)
        out_m = Movement(source_id=s1.id, amount=100, direction="out", date=date.today())
        in_m = Movement(source_id=s2.id, amount=100, direction="in", date=date.today())
        session.add(out_m)
        session.add(in_m)
        session.flush()
        out_m.transfer_pair_id = in_m.id
        in_m.transfer_pair_id = out_m.id
        session.commit()

        stats = get_dashboard_stats(session)
        # Transfers should be excluded from monthly totals
        assert stats["month_income"].get("EUR", 0) == 0
        assert stats["month_expense"].get("EUR", 0) == 0

    def test_monthly_excludes_excluded_movements(self, session):
        s = _src(session, "Bank", "EUR")
        _mv(session, s.id, 100, "in", exclude=True)
        _mv(session, s.id, 50, "in")
        stats = get_dashboard_stats(session)
        assert stats["month_income"].get("EUR", 0) == 50.0

    def test_recent_movements_limit(self, session):
        s = _src(session)
        for i in range(10):
            _mv(session, s.id, i + 1, "in")
        stats = get_dashboard_stats(session)
        assert len(stats["recent_movements"]) == 5

    def test_upcoming_recurring(self, session):
        s = _src(session)
        _recurring(session, s.id, "Sub1", date.today() + timedelta(days=3))
        _recurring(session, s.id, "Sub2", date.today() + timedelta(days=10))
        # Past due — should not appear
        r = RecurringItem(
            name="Past", amount=10, direction="out", currency="EUR",
            frequency="monthly", start_date=date.today() - timedelta(days=30),
            next_due_date=date.today() - timedelta(days=1), source_id=s.id,
        )
        session.add(r)
        session.commit()
        stats = get_dashboard_stats(session)
        names = [r.name for r in stats["upcoming_recurring"]]
        assert "Sub1" in names
        assert "Sub2" in names

    def test_month_savings(self, session):
        s = _src(session, "Bank", "EUR", 1000)
        m = Movement(
            source_id=s.id, amount=200, direction="out",
            date=date.today(), is_savings_contribution=True,
        )
        session.add(m)
        session.commit()
        stats = get_dashboard_stats(session)
        assert stats["month_savings"].get("EUR", 0) == 200.0


# ── Monthly Movements ────────────────────────────────────────────

class TestMonthlyMovements:
    def test_get_monthly_in(self, session):
        s = _src(session)
        _mv(session, s.id, 100, "in")
        _mv(session, s.id, 200, "in")
        _mv(session, s.id, 50, "out")
        result = get_monthly_movements(session, "in")
        assert len(result) == 2
        assert all(m["amount"] > 0 for m in result)

    def test_excludes_transfers(self, session):
        s1 = _src(session, "A")
        s2 = _src(session, "B")
        out_m = Movement(source_id=s1.id, amount=100, direction="out", date=date.today())
        in_m = Movement(source_id=s2.id, amount=100, direction="in", date=date.today())
        session.add(out_m)
        session.add(in_m)
        session.flush()
        out_m.transfer_pair_id = in_m.id
        in_m.transfer_pair_id = out_m.id
        session.commit()
        result = get_monthly_movements(session, "in")
        assert len(result) == 0

    def test_external_movements(self, session):
        m = Movement(source_id=None, amount=50, direction="in", date=date.today())
        session.add(m)
        session.commit()
        result = get_monthly_movements(session, "in")
        assert len(result) == 1


# ── Monthly Totals ───────────────────────────────────────────────

class TestMonthlyTotals:
    def test_totals_per_currency(self, session):
        s_eur = _src(session, "EUR Bank", "EUR")
        s_usd = _src(session, "USD Bank", "USD")
        _mv(session, s_eur.id, 1000, "in")
        _mv(session, s_usd.id, 500, "in")
        _mv(session, s_eur.id, 200, "out")
        totals = get_monthly_totals(session)
        assert totals["month_income"]["EUR"] == 1000.0
        assert totals["month_income"]["USD"] == 500.0
        assert totals["month_expense"]["EUR"] == 200.0

    def test_totals_exclude_transfers_and_excluded(self, session):
        s = _src(session, "Bank", "EUR")
        _mv(session, s.id, 100, "in")
        _mv(session, s.id, 50, "in", exclude=True)
        totals = get_monthly_totals(session)
        assert totals["month_income"]["EUR"] == 100.0


# ── Net Worth History ────────────────────────────────────────────

class TestNetWorthHistory:
    def test_empty_sources(self, session):
        result = get_net_worth_history(session)
        assert result == {}

    def test_single_currency(self, session):
        s = _src(session, "Bank", "EUR", 1000)
        _mv(session, s.id, 200, "in", date.today() - timedelta(days=3))
        _mv(session, s.id, 50, "out", date.today() - timedelta(days=1))
        result = get_net_worth_history(session, "7d")
        assert "EUR" in result
        history = result["EUR"]
        assert len(history) == 2
        assert history[-1]["balance"] == 1150.0  # 1000 + 200 - 50

    def test_no_movements_returns_today(self, session):
        _src(session, "Empty", "EUR", 500)
        result = get_net_worth_history(session, "30d")
        assert "EUR" in result
        assert len(result["EUR"]) == 1
        assert result["EUR"][0]["balance"] == 500.0

    def test_multi_currency_separate(self, session):
        _src(session, "EUR", "EUR", 100)
        _src(session, "USD", "USD", 200)
        result = get_net_worth_history(session)
        assert "EUR" in result
        assert "USD" in result


# ── Monthly Comparison ───────────────────────────────────────────

class TestMonthlyComparison:
    def test_comparison_basic(self, session):
        s = _src(session, "Bank", "EUR")
        _mv(session, s.id, 1000, "in")
        _mv(session, s.id, 300, "out")
        result = get_monthly_comparison(session, months=3)
        assert len(result) >= 1
        current = result[-1]
        assert current["income"] == 1000.0
        assert current["expense"] == 300.0

    def test_comparison_excludes_transfers(self, session):
        s1 = _src(session, "A")
        s2 = _src(session, "B")
        out_m = Movement(source_id=s1.id, amount=100, direction="out", date=date.today())
        in_m = Movement(source_id=s2.id, amount=100, direction="in", date=date.today())
        session.add(out_m)
        session.add(in_m)
        session.flush()
        out_m.transfer_pair_id = in_m.id
        in_m.transfer_pair_id = out_m.id
        session.commit()

        result = get_monthly_comparison(session, months=1)
        # No income/expense from transfers
        assert result == [] or all(r["income"] == 0 and r["expense"] == 0 for r in result)

    def test_comparison_empty(self, session):
        result = get_monthly_comparison(session, months=6)
        assert result == []
