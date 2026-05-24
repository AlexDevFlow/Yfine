"""Regression tests for the logic bugs fixed in the audit pass.

Each test pins the corrected behaviour of a previously confirmed bug so it can
never silently come back. Tests that exercise foreign-key behaviour (export /
import / reset, cross-table cascades) build their own engine with
``PRAGMA foreign_keys=ON`` to match production — the shared conftest engine
leaves FK enforcement off.
"""
from datetime import date, timedelta
from contextlib import contextmanager

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

import models  # noqa: F401 — register all models
from models.budget import Budget
from models.exchange_rate import ExchangeRate
from models.goal import GoalAllocation
from models.movement import Movement
from models.portfolio import Holding, HoldingPriceSnapshot, Portfolio
from models.source import Source
from models.tag import Tag


@contextmanager
def fk_session():
    """In-memory session with FK enforcement ON, like the real app."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


# ── #1 close_goal must not double-refund ─────────────────────────

class TestCloseGoalBalances:
    def test_refund_to_origin_conserves_balance(self):
        from schemas.goal import AllocationCreate, GoalClose, GoalCreate
        from services import goals as gsvc
        from services import sources as ssvc
        with fk_session() as s:
            chk = Source(name="Checking", currency="EUR", starting_balance=1000.0)
            s.add(chk); s.commit(); s.refresh(chk)
            g = gsvc.create_goal(s, GoalCreate(name="Trip", target_amount=500, currency="EUR"))
            gsvc.allocate(s, g.id, AllocationCreate(from_source_id=chk.id, amount=300, date=date.today()))
            gsvc.allocate(s, g.id, AllocationCreate(from_source_id=chk.id, amount=200, date=date.today()))
            assert ssvc.get_balance(s, chk.id) == 500.0
            assert ssvc.get_balance(s, g.source_id) == 500.0

            gsvc.close_goal(s, g.id, GoalClose(to_source_id=chk.id, date=date.today()))

            assert ssvc.get_balance(s, chk.id) == 1000.0          # money back, not 1500
            assert ssvc.get_balance(s, g.source_id) == 0.0        # fund flat, not -500
            assert s.exec(select(GoalAllocation)).all() == []     # tracking rows gone

    def test_refund_to_other_source_conserves_total(self):
        from schemas.goal import AllocationCreate, GoalClose, GoalCreate
        from services import goals as gsvc
        from services import sources as ssvc
        with fk_session() as s:
            origin = Source(name="Origin", currency="EUR", starting_balance=400.0)
            dest = Source(name="Dest", currency="EUR", starting_balance=0.0)
            s.add(origin); s.add(dest); s.commit(); s.refresh(origin); s.refresh(dest)
            g = gsvc.create_goal(s, GoalCreate(name="Phone", target_amount=400, currency="EUR"))
            gsvc.allocate(s, g.id, AllocationCreate(from_source_id=origin.id, amount=400, date=date.today()))
            gsvc.close_goal(s, g.id, GoalClose(to_source_id=dest.id, date=date.today()))
            assert ssvc.get_balance(s, origin.id) == 0.0
            assert ssvc.get_balance(s, g.source_id) == 0.0
            assert ssvc.get_balance(s, dest.id) == 400.0


# ── #2 export/import/reset cover every core table ────────────────

def _seed_full_db(s):
    a = Source(name="A", currency="EUR"); b = Source(name="B", currency="EUR")
    s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
    t = Tag(name="Food"); s.add(t); s.commit(); s.refresh(t)
    s.add(Budget(tag_id=t.id, amount=100, currency="EUR"))
    p = Portfolio(name="PF", base_currency="EUR", source_id=a.id)
    s.add(p); s.commit(); s.refresh(p)
    h = Holding(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                quantity=1, avg_cost=100, currency="EUR")
    s.add(h); s.commit(); s.refresh(h)
    s.add(HoldingPriceSnapshot(holding_id=h.id, date=date.today(), price=120))
    s.add(ExchangeRate(from_currency="EUR", to_currency="USD", rate=1.1))
    s.commit()
    from schemas.movement import TransferCreate
    from services import movements as msvc
    msvc.create_transfer(s, TransferCreate(
        from_source_id=a.id, to_source_id=b.id, amount=10, date=date.today()))


class TestDataRoundTrip:
    def test_export_core_includes_new_tables(self):
        from services import data as dsvc
        with fk_session() as s:
            _seed_full_db(s)
            data = dsvc.export_all(s, mode="core")
        for key in ("budgets", "portfolios", "holdings", "holding_price_snapshots", "exchange_rates"):
            assert len(data[key]) == 1, f"{key} missing from core export"
        assert "_plugin_tables" not in data  # not misclassified as plugin data

    def test_import_roundtrip_with_transfer(self):
        from services import data as dsvc
        with fk_session() as s:
            _seed_full_db(s)
            data = dsvc.export_all(s, mode="core")
        with fk_session() as s2:
            dsvc.import_all(s2, data)  # must not raise (cyclic transfer FK + ordering)
            assert len(s2.exec(select(Budget)).all()) == 1
            assert len(s2.exec(select(Portfolio)).all()) == 1
            assert len(s2.exec(select(Holding)).all()) == 1
            assert len(s2.exec(select(HoldingPriceSnapshot)).all()) == 1
            assert len(s2.exec(select(ExchangeRate)).all()) == 1
            mvs = s2.exec(select(Movement)).all()
            assert len(mvs) == 2 and all(m.transfer_pair_id for m in mvs)

    def test_reset_with_budget_and_portfolio(self, monkeypatch):
        # reset re-seeds tags via the global engine; stub it so the test stays
        # on the in-memory DB.
        import database
        monkeypatch.setattr(database, "_seed_default_tags", lambda: None)
        from services import data as dsvc
        with fk_session() as s:
            _seed_full_db(s)
            dsvc.reset_all_data(s)  # must not raise FK IntegrityError
            assert s.exec(select(Budget)).all() == []
            assert s.exec(select(Portfolio)).all() == []
            assert s.exec(select(Source)).all() == []


# ── #3 delete_source move_to currency / self ─────────────────────

class TestMoveToValidation:
    def test_cross_currency_rejected(self):
        from fastapi import HTTPException
        from services import sources as ssvc
        with fk_session() as s:
            eur = Source(name="EUR", currency="EUR")
            usd = Source(name="USD", currency="USD")
            s.add(eur); s.add(usd); s.commit(); s.refresh(eur); s.refresh(usd)
            with pytest.raises(HTTPException) as exc:
                ssvc.delete_source(s, eur.id, action=f"move_to:{usd.id}")
            assert exc.value.status_code == 400

    def test_move_into_self_rejected(self):
        from fastapi import HTTPException
        from services import sources as ssvc
        with fk_session() as s:
            eur = Source(name="EUR", currency="EUR")
            s.add(eur); s.commit(); s.refresh(eur)
            with pytest.raises(HTTPException) as exc:
                ssvc.delete_source(s, eur.id, action=f"move_to:{eur.id}")
            assert exc.value.status_code == 400


# ── #4 recurring currency must match its source ──────────────────

class TestRecurringCurrency:
    def test_create_mismatch_rejected(self):
        from fastapi import HTTPException
        from schemas.recurring import RecurringCreate
        from services import recurring as rsvc
        with fk_session() as s:
            eur = Source(name="EUR", currency="EUR")
            s.add(eur); s.commit(); s.refresh(eur)
            with pytest.raises(HTTPException) as exc:
                rsvc.create_recurring(s, RecurringCreate(
                    name="Sub", amount=20, direction="out", currency="USD",
                    frequency="monthly", start_date=date.today(), source_id=eur.id))
            assert exc.value.status_code == 422

    def test_external_recurring_allowed(self):
        from schemas.recurring import RecurringCreate
        from services import recurring as rsvc
        with fk_session() as s:
            item = rsvc.create_recurring(s, RecurringCreate(
                name="Cash", amount=20, direction="out", currency="USD",
                frequency="monthly", start_date=date.today(), source_id=None))
            assert item.id is not None


# ── #5 whim purchase currency must match the source ──────────────

class TestWhimPurchaseCurrency:
    def test_mismatch_rejected(self):
        from fastapi import HTTPException
        from schemas.whim import WhimCreate, WhimPurchase
        from services import whims as wsvc
        with fk_session() as s:
            eur = Source(name="EUR", currency="EUR", starting_balance=200.0)
            s.add(eur); s.commit(); s.refresh(eur)
            w = wsvc.create_whim(s, WhimCreate(name="Gadget", amount=50, currency="USD"))
            with pytest.raises(HTTPException) as exc:
                wsvc.purchase_whim(s, w.id, WhimPurchase(source_id=eur.id, date=date.today()))
            assert exc.value.status_code == 422

    def test_matching_currency_ok(self):
        from schemas.whim import WhimCreate, WhimPurchase
        from services import sources as ssvc
        from services import whims as wsvc
        with fk_session() as s:
            eur = Source(name="EUR", currency="EUR", starting_balance=200.0)
            s.add(eur); s.commit(); s.refresh(eur)
            w = wsvc.create_whim(s, WhimCreate(name="Gadget", amount=50, currency="EUR"))
            wsvc.purchase_whim(s, w.id, WhimPurchase(source_id=eur.id, date=date.today()))
            assert ssvc.get_balance(s, eur.id) == 150.0


# ── #8 budget navigation is period-aware ─────────────────────────

class TestBudgetNavigation:
    def test_weekly_offset_shows_correct_week(self):
        from services import budgets as bsvc
        with fk_session() as s:
            src = Source(name="S", currency="EUR")
            tag = Tag(name="Coffee")
            s.add(src); s.add(tag); s.commit(); s.refresh(src); s.refresh(tag)
            s.add(Budget(tag_id=tag.id, amount=50, currency="EUR", period="weekly"))
            s.commit()
            # spend in the current week
            mv = Movement(source_id=src.id, amount=20, direction="out", date=date.today())
            s.add(mv); s.commit(); s.refresh(mv)
            s.add(models.MovementTag(movement_id=mv.id, tag_id=tag.id)); s.commit()

            week_start = date.today() - timedelta(days=date.today().weekday())
            cur = bsvc.list_budget_statuses(s, offset=0)[0]
            assert cur["period_start"] == week_start.isoformat()
            assert cur["actual"] == 20.0  # current week's spend counts at offset 0

            nxt = bsvc.list_budget_statuses(s, offset=1)[0]
            assert nxt["period_start"] == (week_start + timedelta(days=7)).isoformat()
            assert nxt["actual"] == 0.0  # next week has no spend


# ── #9 make-recurring (auto) does not back-fill the past ─────────

class TestMakeRecurringNoBackfill:
    def test_auto_from_old_movement_starts_in_future(self):
        from schemas.movement import MovementCreate
        from services import movements as msvc
        with fk_session() as s:
            src = Source(name="S", currency="EUR")
            s.add(src); s.commit(); s.refresh(src)
            old = date.today() - relativedelta(months=8)
            m = msvc.create_movement(s, MovementCreate(
                source_id=src.id, amount=9.99, direction="out", date=old))
            item = msvc.make_recurring_from_movement(s, m.id, "monthly", "auto")
            assert item.start_date == old           # cadence anchored to the movement
            assert item.next_due_date > date.today()  # but first fire is in the future
