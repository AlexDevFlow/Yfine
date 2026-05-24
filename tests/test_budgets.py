"""Tests for the budget service — period math, actuals, rollover, status, alerts."""
from datetime import date

import pytest
from sqlmodel import select

from models.budget import Budget
from models.movement import Movement, MovementTag
from models.notification import Notification
from models.source import Source
from models.tag import Tag
from schemas.budget import BudgetCreate, BudgetUpdate
from services.budgets import (
    budget_status,
    check_budget_alerts,
    create_budget,
    delete_budget,
    get_budget,
    list_budget_statuses,
    next_period_start,
    period_bounds,
    period_key,
    shift_period,
    update_budget,
)
from services.tags import delete_tag


# ── helpers ──────────────────────────────────────────────────────

def _tag(session, name="Groceries", color="#ff0000"):
    t = Tag(name=name, color=color)
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def _source(session, name="Bank", currency="EUR"):
    s = Source(name=name, currency=currency)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _spend(session, source, tag, amount, when=None, direction="out",
           exclude=False, transfer_pair=None):
    m = Movement(
        source_id=source.id, amount=amount, direction=direction,
        date=when or date.today(), exclude_from_stats=exclude,
        transfer_pair_id=transfer_pair,
    )
    session.add(m)
    session.commit()
    session.refresh(m)
    if tag is not None:
        session.add(MovementTag(movement_id=m.id, tag_id=tag.id))
        session.commit()
    return m


def _budget(session, tag, source_currency="EUR", **kw):
    defaults = dict(tag_id=tag.id, amount=400.0, currency=source_currency,
                    period="monthly", direction="out", rollover=False,
                    alert_threshold_pct=80, active=True, start_date=date.today())
    defaults.update(kw)
    b = Budget(**defaults)
    session.add(b)
    session.commit()
    session.refresh(b)
    return b


# ── Period math ──────────────────────────────────────────────────

class TestPeriodMath:
    def test_monthly_bounds(self):
        start, end = period_bounds("monthly", date(2026, 5, 17))
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 31)

    def test_quarterly_bounds(self):
        start, end = period_bounds("quarterly", date(2026, 5, 17))
        assert start == date(2026, 4, 1)
        assert end == date(2026, 6, 30)

    def test_yearly_bounds(self):
        start, end = period_bounds("yearly", date(2026, 5, 17))
        assert (start, end) == (date(2026, 1, 1), date(2026, 12, 31))

    def test_weekly_bounds_monday_to_sunday(self):
        start, end = period_bounds("weekly", date(2026, 5, 21))  # Thursday
        assert start == date(2026, 5, 18)  # Monday
        assert end == date(2026, 5, 24)    # Sunday

    def test_period_key(self):
        assert period_key("monthly", date(2026, 5, 1)) == "2026-05"
        assert period_key("quarterly", date(2026, 4, 1)) == "2026-Q2"
        assert period_key("yearly", date(2026, 1, 1)) == "2026"

    def test_next_and_shift(self):
        assert next_period_start("monthly", date(2026, 5, 1)) == date(2026, 6, 1)
        assert shift_period("monthly", date(2026, 5, 17), -1) == date(2026, 4, 1)
        assert shift_period("monthly", date(2026, 5, 17), 2) == date(2026, 7, 1)


# ── Actuals ──────────────────────────────────────────────────────

class TestActuals:
    def test_sums_tagged_spending(self, session):
        src, tag = _source(session), _tag(session)
        _spend(session, src, tag, 100)
        _spend(session, src, tag, 50)
        b = _budget(session, tag)
        st = budget_status(session, b)
        assert st["actual"] == 150.0
        assert st["remaining"] == 250.0

    def test_excludes_transfers_and_excluded_and_income(self, session):
        src, tag = _source(session), _tag(session)
        _spend(session, src, tag, 100)                       # counts
        _spend(session, src, tag, 30, exclude=True)          # exclude_from_stats
        _spend(session, src, tag, 40, transfer_pair=999)     # transfer leg
        _spend(session, src, tag, 70, direction="in")        # income, not a spend
        b = _budget(session, tag)
        assert budget_status(session, b)["actual"] == 100.0

    def test_currency_isolation(self, session):
        tag = _tag(session)
        eur, usd = _source(session, "EUR acct", "EUR"), _source(session, "USD acct", "USD")
        _spend(session, eur, tag, 100)
        _spend(session, usd, tag, 999)
        b = _budget(session, tag, source_currency="EUR")
        assert budget_status(session, b)["actual"] == 100.0

    def test_external_movements_excluded(self, session):
        # A movement with no source has no currency → cannot match a budget.
        src, tag = _source(session), _tag(session)
        _spend(session, src, tag, 100)
        ext = Movement(source_id=None, amount=500, direction="out", date=date.today())
        session.add(ext); session.commit(); session.refresh(ext)
        session.add(MovementTag(movement_id=ext.id, tag_id=tag.id)); session.commit()
        b = _budget(session, tag)
        assert budget_status(session, b)["actual"] == 100.0

    def test_only_current_period_counts(self, session):
        src, tag = _source(session), _tag(session)
        start, _ = period_bounds("monthly", date.today())
        _spend(session, src, tag, 100, when=start)                       # this month
        prev = shift_period("monthly", date.today(), -1)
        _spend(session, src, tag, 200, when=prev)                        # last month
        b = _budget(session, tag)
        assert budget_status(session, b)["actual"] == 100.0


# ── Rollover ─────────────────────────────────────────────────────

class TestRollover:
    def test_surplus_carries_forward(self, session):
        src, tag = _source(session), _tag(session)
        # Budget started two months ago; spent only 100 of 400 last two months.
        start = shift_period("monthly", date.today(), -2)
        b = _budget(session, tag, amount=400.0, rollover=True, start_date=start)
        m1 = shift_period("monthly", date.today(), -2)
        m2 = shift_period("monthly", date.today(), -1)
        _spend(session, src, tag, 100, when=m1)
        _spend(session, src, tag, 100, when=m2)
        st = budget_status(session, b)
        # carry = (400-100) + (400-100) = 600 into this month
        assert st["rollover_in"] == 600.0
        assert st["available"] == 1000.0  # 400 + 600

    def test_overspend_carries_as_deficit(self, session):
        src, tag = _source(session), _tag(session)
        start = shift_period("monthly", date.today(), -1)
        b = _budget(session, tag, amount=400.0, rollover=True, start_date=start)
        _spend(session, src, tag, 500, when=start)  # overspent last month by 100
        st = budget_status(session, b)
        assert st["rollover_in"] == -100.0
        assert st["available"] == 300.0  # 400 - 100

    def test_no_rollover_means_zero_carry(self, session):
        src, tag = _source(session), _tag(session)
        start = shift_period("monthly", date.today(), -1)
        b = _budget(session, tag, amount=400.0, rollover=False, start_date=start)
        _spend(session, src, tag, 100, when=start)
        assert budget_status(session, b)["rollover_in"] == 0.0


# ── Status ───────────────────────────────────────────────────────

class TestStatus:
    def test_status_colors(self, session):
        src, tag = _source(session), _tag(session, name="A")
        b = _budget(session, tag, amount=100.0, alert_threshold_pct=80)
        assert budget_status(session, b)["status"] == "ok"
        _spend(session, src, tag, 85)
        assert budget_status(session, b)["status"] == "warning"
        _spend(session, src, tag, 30)  # total 115 > 100
        assert budget_status(session, b)["status"] == "over"

    def test_sorted_most_at_risk_first(self, session):
        src = _source(session)
        ok_tag = _tag(session, name="OK")
        over_tag = _tag(session, name="OVER")
        _budget(session, ok_tag, amount=1000.0)
        _budget(session, over_tag, amount=10.0)
        _spend(session, src, over_tag, 50)
        statuses = list_budget_statuses(session)
        assert statuses[0]["tag_name"] == "OVER"
        assert statuses[0]["status"] == "over"


# ── CRUD ─────────────────────────────────────────────────────────

class TestCRUD:
    def test_create_defaults_start_date(self, session):
        tag = _tag(session)
        b = create_budget(session, BudgetCreate(tag_id=tag.id, amount=300, currency="EUR"))
        assert b.start_date == period_bounds("monthly", date.today())[0]
        assert b.period == "monthly" and b.direction == "out"

    def test_duplicate_rejected(self, session):
        from fastapi import HTTPException
        tag = _tag(session)
        create_budget(session, BudgetCreate(tag_id=tag.id, amount=300, currency="EUR"))
        with pytest.raises(HTTPException) as exc:
            create_budget(session, BudgetCreate(tag_id=tag.id, amount=100, currency="EUR"))
        assert exc.value.status_code == 409

    def test_same_tag_other_currency_allowed(self, session):
        tag = _tag(session)
        create_budget(session, BudgetCreate(tag_id=tag.id, amount=300, currency="EUR"))
        b2 = create_budget(session, BudgetCreate(tag_id=tag.id, amount=300, currency="USD"))
        assert b2.id is not None

    def test_unknown_tag_rejected(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            create_budget(session, BudgetCreate(tag_id=9999, amount=300, currency="EUR"))
        assert exc.value.status_code == 400

    def test_update_resets_alert_band(self, session):
        tag = _tag(session)
        b = _budget(session, tag)
        b.last_alert_period = "2026-05"; b.last_alert_level = 80
        session.add(b); session.commit()
        update_budget(session, b.id, BudgetUpdate(amount=500))
        refreshed = get_budget(session, b.id)
        assert refreshed.amount == 500
        assert refreshed.last_alert_period is None and refreshed.last_alert_level == 0

    def test_delete(self, session):
        tag = _tag(session)
        b = _budget(session, tag)
        delete_budget(session, b.id)
        assert session.get(Budget, b.id) is None

    def test_deleting_tag_removes_budget(self, session):
        tag = _tag(session)
        b = _budget(session, tag)
        delete_tag(session, tag.id)
        assert session.get(Budget, b.id) is None


# ── Alerts ───────────────────────────────────────────────────────

class TestAlerts:
    def test_threshold_then_overspend_then_idempotent(self, session):
        src, tag = _source(session), _tag(session)
        b = _budget(session, tag, amount=100.0, alert_threshold_pct=80)

        _spend(session, src, tag, 85)            # crosses 80%
        assert check_budget_alerts(session) == 1
        assert check_budget_alerts(session) == 0  # idempotent within same band

        _spend(session, src, tag, 30)            # now 115 > 100 → overspend band
        assert check_budget_alerts(session) == 1
        assert check_budget_alerts(session) == 0

        notifs = session.exec(select(Notification)).all()
        assert len(notifs) == 2
        assert any(n.related_entity == f"budget:{b.id}" for n in notifs)

    def test_threshold_zero_disables_alerts(self, session):
        src, tag = _source(session), _tag(session)
        _budget(session, tag, amount=100.0, alert_threshold_pct=0)
        _spend(session, src, tag, 150)
        assert check_budget_alerts(session) == 0

    def test_inactive_budget_no_alert(self, session):
        src, tag = _source(session), _tag(session)
        _budget(session, tag, amount=100.0, active=False)
        _spend(session, src, tag, 150)
        assert check_budget_alerts(session) == 0
