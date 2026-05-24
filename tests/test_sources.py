"""Tests for sources service — CRUD, balance, delete strategies, merge, history."""
from datetime import date, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from sqlmodel import select

from models.movement import Movement
from models.notification import Notification
from models.recurring import RecurringItem
from models.source import Source
from schemas.source import SourceCreate, SourceUpdate
from services.sources import (
    accrue_source_yields,
    create_source,
    delete_source,
    get_balance,
    get_balance_history,
    get_balances_batch,
    get_source,
    get_source_dependencies,
    list_sources,
    merge_sources,
    toggle_exclude_from_stats,
    update_source,
)


# ── helpers ──────────────────────────────────────────────────────

def _make_source(session, name="Bank", currency="EUR", balance=0.0):
    s = Source(name=name, currency=currency, starting_balance=balance)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _make_movement(session, source_id, amount, direction, dt=None):
    m = Movement(
        source_id=source_id,
        amount=amount,
        direction=direction,
        date=dt or date.today(),
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


def _make_recurring(session, source_id, name="Rent"):
    r = RecurringItem(
        name=name, amount=500, direction="out", currency="EUR",
        frequency="monthly", start_date=date.today(),
        next_due_date=date.today(), source_id=source_id,
    )
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


# ── CRUD ─────────────────────────────────────────────────────────

class TestSourceCRUD:
    def test_create_source(self, session):
        src = create_source(session, SourceCreate(name="Wallet", currency="EUR", starting_balance=100))
        assert src.id is not None
        assert src.name == "Wallet"
        assert src.currency == "EUR"
        assert src.starting_balance == 100.0

    def test_list_sources_empty(self, session):
        assert list_sources(session) == []

    def test_list_sources_pagination(self, session):
        for i in range(5):
            _make_source(session, name=f"S{i}")
        assert len(list_sources(session, skip=0, limit=3)) == 3
        assert len(list_sources(session, skip=3, limit=10)) == 2

    def test_get_source_found(self, session):
        s = _make_source(session)
        assert get_source(session, s.id).name == "Bank"

    def test_get_source_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_source(session, 9999)
        assert exc.value.status_code == 404

    def test_update_source_partial(self, session):
        s = _make_source(session, name="Old")
        updated = update_source(session, s.id, SourceUpdate(name="New"))
        assert updated.name == "New"
        assert updated.currency == "EUR"  # unchanged

    def test_update_source_currency(self, session):
        s = _make_source(session)
        updated = update_source(session, s.id, SourceUpdate(currency="USD"))
        assert updated.currency == "USD"


# ── Balance ──────────────────────────────────────────────────────

class TestSourceBalance:
    def test_balance_starting_only(self, session):
        s = _make_source(session, balance=500.0)
        assert get_balance(session, s.id) == 500.0

    def test_balance_with_movements(self, session):
        s = _make_source(session, balance=100.0)
        _make_movement(session, s.id, 50, "in")
        _make_movement(session, s.id, 30, "out")
        assert get_balance(session, s.id) == 120.0  # 100 + 50 - 30

    def test_balance_no_movements(self, session):
        s = _make_source(session, balance=0.0)
        assert get_balance(session, s.id) == 0.0

    def test_balance_many_movements(self, session):
        s = _make_source(session, balance=1000.0)
        for _ in range(20):
            _make_movement(session, s.id, 10, "in")
            _make_movement(session, s.id, 5, "out")
        # 1000 + 20*10 - 20*5 = 1000 + 200 - 100 = 1100
        assert get_balance(session, s.id) == 1100.0

    def test_balance_goes_negative(self, session):
        s = _make_source(session, balance=10.0)
        _make_movement(session, s.id, 50, "out")
        assert get_balance(session, s.id) == -40.0


# ── Balance History ──────────────────────────────────────────────

class TestBalanceHistory:
    def test_history_all(self, session):
        s = _make_source(session, balance=100.0)
        _make_movement(session, s.id, 50, "in", date.today() - timedelta(days=10))
        _make_movement(session, s.id, 20, "out", date.today() - timedelta(days=5))
        history = get_balance_history(session, s.id, "all")
        # Two movement points + a "today" extension point so the chart reaches now.
        assert history[0]["balance"] == 150.0  # 100 + 50
        assert history[1]["balance"] == 130.0  # 150 - 20
        assert history[-1]["date"] == date.today().isoformat()
        assert history[-1]["balance"] == 130.0

    def test_history_7d_excludes_old(self, session):
        s = _make_source(session, balance=100.0)
        _make_movement(session, s.id, 50, "in", date.today() - timedelta(days=30))
        _make_movement(session, s.id, 10, "out", date.today() - timedelta(days=3))
        history = get_balance_history(session, s.id, "7d")
        # One movement point within window + today's extension point.
        movement_points = [p for p in history if p["date"] != date.today().isoformat()]
        assert len(movement_points) <= 1
        assert history[-1]["balance"] == 140.0  # (100+50) - 10, no change since

    def test_history_empty_returns_today(self, session):
        s = _make_source(session, balance=250.0)
        history = get_balance_history(session, s.id, "30d")
        assert len(history) == 1
        assert history[0]["balance"] == 250.0
        assert history[0]["date"] == date.today().isoformat()


# ── Dependencies ─────────────────────────────────────────────────

class TestSourceDependencies:
    def test_dependencies_count(self, session):
        s = _make_source(session)
        _make_movement(session, s.id, 10, "in")
        _make_movement(session, s.id, 20, "out")
        _make_recurring(session, s.id)
        deps = get_source_dependencies(session, s.id)
        assert deps["movement_count"] == 2
        assert deps["recurring_count"] == 1

    def test_dependencies_zero(self, session):
        s = _make_source(session)
        deps = get_source_dependencies(session, s.id)
        assert deps["movement_count"] == 0
        assert deps["recurring_count"] == 0


# ── Delete Strategies ────────────────────────────────────────────

class TestDeleteSource:
    def test_delete_all_cascades(self, session):
        s = _make_source(session)
        _make_movement(session, s.id, 100, "in")
        _make_recurring(session, s.id)
        delete_source(session, s.id, "delete_all")
        assert session.get(Source, s.id) is None
        assert session.exec(select(Movement).where(Movement.source_id == s.id)).all() == []

    def test_delete_move_to(self, session):
        s1 = _make_source(session, name="From", balance=200.0)
        s2 = _make_source(session, name="To", balance=100.0)
        m = _make_movement(session, s1.id, 50, "in")
        r = _make_recurring(session, s1.id)

        delete_source(session, s1.id, f"move_to:{s2.id}")

        assert session.get(Source, s1.id) is None
        # Movement reassigned
        moved = session.get(Movement, m.id)
        assert moved.source_id == s2.id
        # Recurring reassigned
        moved_r = session.get(RecurringItem, r.id)
        assert moved_r.source_id == s2.id
        # Balance transferred
        target = session.get(Source, s2.id)
        assert target.starting_balance == 300.0  # 100 + 200

    def test_delete_make_external(self, session):
        s = _make_source(session)
        m = _make_movement(session, s.id, 30, "out")
        r = _make_recurring(session, s.id)

        delete_source(session, s.id, "make_external")

        assert session.get(Source, s.id) is None
        ext_m = session.get(Movement, m.id)
        assert ext_m.source_id is None  # external
        assert session.get(RecurringItem, r.id) is None  # deleted

    def test_delete_nonexistent_raises_404(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            delete_source(session, 9999)


# ── Merge ────────────────────────────────────────────────────────

class TestMergeSources:
    def test_merge_same_currency(self, session):
        s1 = _make_source(session, name="A", balance=100.0)
        s2 = _make_source(session, name="B", balance=200.0)
        _make_movement(session, s1.id, 50, "in")
        _make_recurring(session, s1.id, name="Sub")

        result = merge_sources(session, s1.id, s2.id)

        assert result.id == s2.id
        assert result.starting_balance == 300.0  # 200 + 100
        assert session.get(Source, s1.id) is None
        # Movement reassigned
        mvs = session.exec(select(Movement).where(Movement.source_id == s2.id)).all()
        assert len(mvs) == 1
        # Notification created
        notifs = session.exec(select(Notification)).all()
        assert any("merged" in n.title.lower() for n in notifs)

    def test_merge_different_currency_rejected(self, session):
        s1 = _make_source(session, name="EUR", currency="EUR")
        s2 = _make_source(session, name="USD", currency="USD")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            merge_sources(session, s1.id, s2.id)
        assert exc.value.status_code == 400

    def test_merge_with_savings_fund_as_source_rejected(self, session):
        # Merging the fund INTO another source would orphan goals (FK RESTRICT)
        # or silently mix savings contributions into a regular source.
        fund = _make_source(session, name="Fund EUR", currency="EUR")
        fund.is_savings_fund = True
        session.add(fund); session.commit()
        regular = _make_source(session, name="Wallet", currency="EUR")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            merge_sources(session, fund.id, regular.id)
        assert exc.value.status_code == 422
        assert "savings fund" in exc.value.detail.lower()

    def test_merge_into_savings_fund_rejected(self, session):
        # Merging a regular source INTO the fund would inflate the fund's
        # apparent balance with non-savings movements.
        fund = _make_source(session, name="Fund EUR", currency="EUR")
        fund.is_savings_fund = True
        session.add(fund); session.commit()
        regular = _make_source(session, name="Wallet", currency="EUR")
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            merge_sources(session, regular.id, fund.id)
        assert exc.value.status_code == 422
        assert "savings fund" in exc.value.detail.lower()


# ── Toggle Exclude ───────────────────────────────────────────────

class TestToggleExclude:
    def test_toggle_on_off(self, session):
        s = _make_source(session)
        assert s.exclude_from_stats is False
        s = toggle_exclude_from_stats(session, s.id)
        assert s.exclude_from_stats is True
        s = toggle_exclude_from_stats(session, s.id)
        assert s.exclude_from_stats is False


# ── Periodic Yield / Interest ────────────────────────────────────

def _make_yielding_source(session, *, rate, period_months, balance, next_date):
    """A source with an interest schedule whose next accrual is `next_date`."""
    s = Source(
        name="Deposit", currency="EUR", starting_balance=balance,
        yield_rate=rate, yield_period_months=period_months,
        yield_next_date=next_date,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


class TestYieldSchedule:
    def test_create_with_yield_sets_next_date(self, session):
        src = create_source(session, SourceCreate(
            name="Conto deposito", currency="EUR", starting_balance=1000,
            yield_rate=3.0, yield_period_months=12,
        ))
        assert src.yield_rate == 3.0
        assert src.yield_next_date == date.today() + relativedelta(months=12)
        assert src.yield_last_date is None

    def test_create_without_yield_leaves_schedule_empty(self, session):
        src = create_source(session, SourceCreate(name="Wallet", currency="EUR"))
        assert src.yield_rate == 0.0
        assert src.yield_next_date is None

    def test_update_enabling_yield_sets_schedule(self, session):
        s = _make_source(session)
        assert s.yield_next_date is None
        updated = update_source(session, s.id, SourceUpdate(yield_rate=2.0, yield_period_months=6))
        assert updated.yield_next_date == date.today() + relativedelta(months=6)

    def test_update_disabling_yield_clears_schedule(self, session):
        s = _make_yielding_source(session, rate=3, period_months=12, balance=100,
                                  next_date=date.today() + relativedelta(months=12))
        updated = update_source(session, s.id, SourceUpdate(yield_rate=0))
        assert updated.yield_next_date is None

    def test_unrelated_update_keeps_schedule(self, session):
        nd = date.today() + relativedelta(months=12)
        s = _make_yielding_source(session, rate=3, period_months=12, balance=100, next_date=nd)
        updated = update_source(session, s.id, SourceUpdate(name="Renamed"))
        assert updated.yield_next_date == nd  # countdown not reset


class TestYieldAccrual:
    def test_accrues_when_due(self, session):
        s = _make_yielding_source(session, rate=3, period_months=12, balance=1000,
                                  next_date=date.today())
        created = accrue_source_yields(session, today=date.today())
        assert created == 1
        assert get_balance(session, s.id) == 1030.0  # 1000 + 3%
        session.refresh(s)
        assert s.yield_last_date == date.today()
        assert s.yield_next_date == date.today() + relativedelta(months=12)
        # The credit is a real "in" movement on the source.
        movs = session.exec(select(Movement).where(Movement.source_id == s.id)).all()
        assert len(movs) == 1
        assert movs[0].direction == "in"
        assert movs[0].amount == 30.0

    def test_not_due_yet_does_nothing(self, session):
        s = _make_yielding_source(session, rate=3, period_months=12, balance=1000,
                                  next_date=date.today() + relativedelta(months=1))
        assert accrue_source_yields(session, today=date.today()) == 0
        assert get_balance(session, s.id) == 1000.0

    def test_catch_up_compounds_missed_periods(self, session):
        # Three periods elapsed without the app running — credit all of them,
        # each compounding on the prior balance.
        start = date.today() - relativedelta(months=24)
        s = _make_yielding_source(session, rate=3, period_months=12, balance=1000,
                                  next_date=start)
        created = accrue_source_yields(session, today=date.today())
        assert created == 3
        # 1000 → 1030 → 1060.90 → 1092.73 (rounded each step)
        assert get_balance(session, s.id) == 1092.73
        session.refresh(s)
        assert s.yield_next_date == start + relativedelta(months=36)

    def test_idempotent_same_day(self, session):
        s = _make_yielding_source(session, rate=3, period_months=12, balance=1000,
                                  next_date=date.today())
        accrue_source_yields(session, today=date.today())
        # A second pass the same day must not credit again.
        assert accrue_source_yields(session, today=date.today()) == 0
        assert get_balance(session, s.id) == 1030.0

    def test_zero_balance_advances_without_movement(self, session):
        s = _make_yielding_source(session, rate=5, period_months=12, balance=0,
                                  next_date=date.today())
        assert accrue_source_yields(session, today=date.today()) == 0
        movs = session.exec(select(Movement).where(Movement.source_id == s.id)).all()
        assert movs == []
        session.refresh(s)
        # Schedule still advances so we don't re-check the same due date forever.
        assert s.yield_last_date == date.today()
        assert s.yield_next_date == date.today() + relativedelta(months=12)

    def test_disabled_source_never_accrues(self, session):
        s = _make_source(session, balance=1000)  # yield_rate defaults to 0
        assert accrue_source_yields(session, today=date.today()) == 0
        assert get_balance(session, s.id) == 1000.0


class TestYieldValidation:
    def test_negative_rate_rejected(self, session):
        with pytest.raises(Exception):
            SourceCreate(name="X", currency="EUR", yield_rate=-1)

    def test_zero_period_rejected(self, session):
        with pytest.raises(Exception):
            SourceCreate(name="X", currency="EUR", yield_period_months=0)
