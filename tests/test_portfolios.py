"""Tests for portfolios: CRUD, holdings, valuation, source linking, prices gating."""
from datetime import datetime

import pytest

from models.portfolio import Holding, Portfolio
from models.setting import Setting
from models.source import Source
from schemas.portfolio import (
    HoldingCreate,
    HoldingUpdate,
    PortfolioCreate,
    PortfolioUpdate,
)
from services import portfolios as portfolio_service
from services import prices as price_service
from services import sources as source_service


# ── helpers ──────────────────────────────────────────────────────


def _make_source(session, name="Bank", currency="EUR", balance=0.0):
    s = Source(name=name, currency=currency, starting_balance=balance)
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _make_setting(session, prices_enabled=False, prompted=False):
    s = Setting(
        id=1,
        portfolio_prices_enabled=prices_enabled,
        portfolio_prices_prompted=prompted,
    )
    session.add(s)
    session.commit()
    session.refresh(s)
    return s


def _make_portfolio(session, **kwargs):
    defaults = dict(name="Main", kind="mixed", base_currency="EUR")
    defaults.update(kwargs)
    if "source_id" not in defaults:
        src = _make_source(session, name=defaults["name"] + "_src")
        defaults["source_id"] = src.id
    return portfolio_service.create_portfolio(session, PortfolioCreate(**defaults))


# ── Portfolio CRUD ───────────────────────────────────────────────


class TestPortfolioCRUD:
    def test_create_portfolio(self, session):
        _make_setting(session)
        src = _make_source(session, name="USD Bank", currency="USD")
        p = portfolio_service.create_portfolio(
            session,
            PortfolioCreate(name="Crypto Bag", kind="crypto", base_currency="USD", source_id=src.id),
        )
        assert p.id is not None
        assert p.name == "Crypto Bag"
        assert p.kind == "crypto"
        assert p.base_currency == "USD"
        assert p.source_id == src.id

    def test_create_portfolio_requires_source(self, session):
        _make_setting(session)
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PortfolioCreate(name="Orphan", kind="mixed", base_currency="EUR")  # type: ignore[call-arg]

    def test_create_portfolio_with_nonexistent_source(self, session):
        _make_setting(session)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            portfolio_service.create_portfolio(
                session,
                PortfolioCreate(name="X", kind="mixed", base_currency="EUR", source_id=9999),
            )
        assert exc.value.status_code == 404

    def test_list_portfolios_empty(self, session):
        assert portfolio_service.list_portfolios(session) == []

    def test_list_portfolios_sorted_by_name(self, session):
        _make_setting(session)
        _make_portfolio(session, name="Zeta")
        _make_portfolio(session, name="Alpha")
        names = [p.name for p in portfolio_service.list_portfolios(session)]
        assert names == ["Alpha", "Zeta"]

    def test_get_portfolio_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            portfolio_service.get_portfolio(session, 999)
        assert exc.value.status_code == 404

    def test_update_portfolio(self, session):
        _make_setting(session)
        p = _make_portfolio(session, name="Old")
        updated = portfolio_service.update_portfolio(
            session, p.id, PortfolioUpdate(name="New", note="changed")
        )
        assert updated.name == "New"
        assert updated.note == "changed"

    def test_update_portfolio_with_source(self, session):
        _make_setting(session)
        src = _make_source(session, name="Trading")
        p = _make_portfolio(session)
        portfolio_service.update_portfolio(session, p.id, PortfolioUpdate(source_id=src.id))
        refreshed = portfolio_service.get_portfolio(session, p.id)
        assert refreshed.source_id == src.id

    def test_delete_portfolio_cascades_holdings(self, session):
        _make_setting(session)
        p = _make_portfolio(session)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC", quantity=1, avg_cost=50000),
        )
        assert portfolio_service.get_counts(session) == {"portfolios": 1, "holdings": 1}
        portfolio_service.delete_portfolio(session, p.id)
        assert portfolio_service.get_counts(session) == {"portfolios": 0, "holdings": 0}


# ── Holding CRUD ─────────────────────────────────────────────────


class TestHoldingCRUD:
    def test_create_holding(self, session):
        _make_setting(session)
        p = _make_portfolio(session)
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(
                portfolio_id=p.id, asset_class="crypto", symbol="btc",
                quantity=0.5, avg_cost=40000, currency="USD",
            ),
        )
        assert h.id is not None
        assert h.symbol == "BTC"  # validator uppercases
        assert h.quantity == 0.5
        assert h.currency == "USD"

    def test_create_holding_invalid_asset_class(self, session):
        with pytest.raises(ValueError):
            HoldingCreate(portfolio_id=1, asset_class="bond", symbol="X")

    def test_create_holding_invalid_symbol_empty(self, session):
        with pytest.raises(ValueError):
            HoldingCreate(portfolio_id=1, asset_class="stock", symbol="  ")

    def test_create_holding_portfolio_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            portfolio_service.create_holding(
                session,
                HoldingCreate(portfolio_id=999, asset_class="crypto", symbol="BTC"),
            )
        assert exc.value.status_code == 404

    def test_update_holding_toggle_manual_clears_price(self, session):
        _make_setting(session)
        p = _make_portfolio(session)
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(
                portfolio_id=p.id, asset_class="stock", symbol="AAPL",
                manual_price=True, last_price=180.0, quantity=10, avg_cost=150,
            ),
        )
        assert h.last_price == 180.0
        # Toggle manual_price OFF → price should be cleared
        updated = portfolio_service.update_holding(session, h.id, HoldingUpdate(manual_price=False))
        assert updated.manual_price is False
        assert updated.last_price is None

    def test_delete_holding(self, session):
        _make_setting(session)
        p = _make_portfolio(session)
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="ETH"),
        )
        portfolio_service.delete_holding(session, h.id)
        assert portfolio_service.list_holdings(session, p.id) == []


# ── Valuation ────────────────────────────────────────────────────


class TestValuation:
    def test_enrich_holding_no_price(self, session):
        h = Holding(
            portfolio_id=1, asset_class="crypto", symbol="BTC",
            quantity=2, avg_cost=30000, currency="USD",
        )
        e = portfolio_service.enrich_holding(h)
        assert e["cost_basis"] == 60000
        assert e["market_value"] is None
        assert e["unrealized_pnl"] is None
        assert e["last_price_at"] is None  # important: string or None, not datetime

    def test_enrich_holding_with_price_profit(self, session):
        h = Holding(
            portfolio_id=1, asset_class="crypto", symbol="BTC",
            quantity=2, avg_cost=30000, currency="USD",
            last_price=40000, last_price_at=datetime(2026, 4, 19, 12, 30),
        )
        e = portfolio_service.enrich_holding(h)
        assert e["cost_basis"] == 60000
        assert e["market_value"] == 80000
        assert e["unrealized_pnl"] == 20000
        assert e["unrealized_pnl_pct"] == pytest.approx(33.33, rel=1e-2)
        # last_price_at must be JSON-serializable
        assert isinstance(e["last_price_at"], str)
        assert "2026-04-19" in e["last_price_at"]

    def test_enrich_holding_loss(self, session):
        h = Holding(
            portfolio_id=1, asset_class="stock", symbol="X",
            quantity=1, avg_cost=100, currency="EUR", last_price=80,
        )
        e = portfolio_service.enrich_holding(h)
        assert e["unrealized_pnl"] == -20
        assert e["unrealized_pnl_pct"] == -20.0

    def test_enrich_holding_zero_cost(self, session):
        """Unknown cost basis (user left avg_cost blank): market value is
        still reported, but PnL is None so the UI does not show a misleading
        "+50 (+0.00%)" reading."""
        h = Holding(
            portfolio_id=1, asset_class="crypto", symbol="X",
            quantity=10, avg_cost=0, currency="EUR", last_price=5,
        )
        e = portfolio_service.enrich_holding(h)
        assert e["cost_basis"] == 0
        assert e["market_value"] == 50
        assert e["unrealized_pnl"] is None
        assert e["unrealized_pnl_pct"] is None

    def test_summarize_portfolio(self, session):
        _make_setting(session)
        p = _make_portfolio(session, base_currency="EUR")
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=20000, currency="EUR",
                          manual_price=True, last_price=25000),
        )
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="ETH",
                          quantity=5, avg_cost=1000, currency="EUR",
                          manual_price=True, last_price=1200),
        )
        s = portfolio_service.summarize_portfolio(session, p)
        assert s["holdings_count"] == 2
        assert s["total_cost"] == 25000  # 20000 + 5000
        assert s["total_value"] == 31000  # 25000 + 6000
        assert s["total_pnl"] == 6000
        assert s["total_pnl_pct"] == pytest.approx(24.0, rel=1e-2)


# ── Source aggregation ───────────────────────────────────────────


class TestSourceAggregation:
    def test_portfolio_value_by_source_groups_by_source(self, session):
        _make_setting(session)
        src_a = _make_source(session, name="Coinbase", currency="EUR")
        src_b = _make_source(session, name="Binance", currency="EUR")
        p1 = _make_portfolio(session, name="A", source_id=src_a.id)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p1.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=0, manual_price=True, last_price=50000,
                          currency="EUR"),
        )
        p2 = _make_portfolio(session, name="B", source_id=src_b.id)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p2.id, asset_class="crypto", symbol="ETH",
                          quantity=2, avg_cost=0, manual_price=True, last_price=1500,
                          currency="EUR"),
        )
        by_source = portfolio_service.portfolio_value_by_source(session)
        assert by_source == {src_a.id: {"EUR": 50000.0}, src_b.id: {"EUR": 3000.0}}

    def test_list_portfolios_by_source(self, session):
        _make_setting(session)
        src = _make_source(session, name="Broker", currency="EUR")
        p = _make_portfolio(session, name="ETF", source_id=src.id)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="stock", symbol="VWCE",
                          quantity=5, avg_cost=100, manual_price=True, last_price=120,
                          currency="EUR"),
        )
        items = portfolio_service.list_portfolios_by_source(session, src.id)
        assert len(items) == 1
        assert items[0]["name"] == "ETF"
        assert items[0]["source_id"] == src.id
        assert items[0]["source_name"] == "Broker"
        assert items[0]["total_value"] == 600

    def test_total_portfolio_value_by_currency(self, session):
        _make_setting(session)
        p1 = _make_portfolio(session, name="A", base_currency="EUR")
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p1.id, asset_class="stock", symbol="X",
                          quantity=1, avg_cost=0, manual_price=True, last_price=100,
                          currency="EUR"),
        )
        p2 = _make_portfolio(session, name="B", base_currency="USD")
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p2.id, asset_class="stock", symbol="Y",
                          quantity=1, avg_cost=0, manual_price=True, last_price=200,
                          currency="USD"),
        )
        totals = portfolio_service.total_portfolio_value_by_currency(session)
        assert totals == {"EUR": 100.0, "USD": 200.0}


# ── Prices gating ────────────────────────────────────────────────


class TestPricesGating:
    def test_prices_disabled_by_default(self, session):
        _make_setting(session)
        assert price_service.are_prices_enabled(session) is False

    def test_prices_enabled(self, session):
        _make_setting(session, prices_enabled=True)
        assert price_service.are_prices_enabled(session) is True

    def test_refresh_all_holdings_noop_when_disabled(self, session, monkeypatch):
        _make_setting(session, prices_enabled=False)
        p = _make_portfolio(session)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=50000, currency="USD"),
        )

        def boom(*a, **kw):
            raise AssertionError("network should not be called when disabled")

        monkeypatch.setattr(price_service, "fetch_crypto_prices_batch", boom)
        monkeypatch.setattr(price_service, "fetch_stock_price", boom)
        assert price_service.refresh_all_holdings(session) == 0

    def test_refresh_all_holdings_skips_manual(self, session, monkeypatch):
        _make_setting(session, prices_enabled=True)
        p = _make_portfolio(session)
        h_manual = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=0, currency="USD",
                          manual_price=True, last_price=99999),
        )
        h_auto = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="ETH",
                          quantity=1, avg_cost=0, currency="USD"),
        )

        # Fake CoinGecko: return a price only for ETH
        def fake_batch(symbols, vs_currency="usd"):
            return {"ETH": 2000.0}

        monkeypatch.setattr(price_service, "fetch_crypto_prices_batch", fake_batch)
        updated = price_service.refresh_all_holdings(session)
        assert updated == 1
        session.refresh(h_manual)
        session.refresh(h_auto)
        assert h_manual.last_price == 99999  # untouched
        assert h_auto.last_price == 2000.0

    def test_refresh_holding_price_skips_manual(self, session):
        _make_setting(session, prices_enabled=True)
        p = _make_portfolio(session)
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          manual_price=True, last_price=1, avg_cost=0, quantity=0,
                          currency="USD"),
        )
        assert price_service.refresh_holding_price(h) is False


# ── Source lifecycle with linked portfolios ──────────────────────


class TestSourceLifecycle:
    def test_source_dependencies_includes_portfolio_count(self, session):
        _make_setting(session)
        src = _make_source(session, name="Main", currency="EUR")
        _make_portfolio(session, name="P1", source_id=src.id)
        _make_portfolio(session, name="P2", source_id=src.id)
        deps = source_service.get_source_dependencies(session, src.id)
        assert deps["portfolio_count"] == 2
        assert deps["movement_count"] == 0
        assert deps["recurring_count"] == 0

    def test_delete_source_delete_all_removes_portfolios_and_holdings(self, session):
        _make_setting(session)
        src = _make_source(session, name="Gone", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src.id)
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=100, currency="EUR"),
        )
        assert portfolio_service.get_counts(session) == {"portfolios": 1, "holdings": 1}
        source_service.delete_source(session, src.id, action="delete_all")
        assert portfolio_service.get_counts(session) == {"portfolios": 0, "holdings": 0}

    def test_delete_source_move_to_reassigns_portfolios(self, session):
        _make_setting(session)
        src_a = _make_source(session, name="A", currency="EUR")
        src_b = _make_source(session, name="B", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src_a.id)
        source_service.delete_source(session, src_a.id, action=f"move_to:{src_b.id}")
        refreshed = portfolio_service.get_portfolio(session, p.id)
        assert refreshed.source_id == src_b.id

    def test_delete_source_make_external_rejects_if_portfolios(self, session):
        _make_setting(session)
        src = _make_source(session, name="HasPf", currency="EUR")
        _make_portfolio(session, name="P", source_id=src.id)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            source_service.delete_source(session, src.id, action="make_external")
        assert exc.value.status_code == 400

    def test_merge_sources_reassigns_portfolios(self, session):
        _make_setting(session)
        src_a = _make_source(session, name="A", currency="EUR")
        src_b = _make_source(session, name="B", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src_a.id)
        source_service.merge_sources(session, from_id=src_a.id, into_id=src_b.id)
        refreshed = portfolio_service.get_portfolio(session, p.id)
        assert refreshed.source_id == src_b.id


# ── Delete UI regression (pywebview / Swal incompatibility) ──────


class TestPortfolioDeleteUI:
    """Regression tests for the portfolio delete flow.

    Pywebview's embedded WebView does not render SweetAlert2 (Swal) modals:
    the Swal call silently fails and the page just scrolls. The delete flow
    was reworked to use a Bootstrap modal (same pattern as /sources, which
    works in pywebview). These tests pin that choice so nobody accidentally
    reintroduces `confirmDialog` for the portfolio delete button.
    """

    TEMPLATE_PATH = "templates/portfolios/index.html"

    def test_uses_bootstrap_modal_not_swal(self):
        with open(self.TEMPLATE_PATH) as f:
            html = f.read()
        # Bootstrap modal must be present
        assert 'id="deletePortfolioModal"' in html
        assert 'confirm-delete-portfolio-btn' in html
        # The trash button must use the delegated class + type=button
        assert 'portfolio-delete-btn' in html
        assert 'type="button"' in html
        # Must NOT route the portfolio delete through confirmDialog (Swal)
        # — Swal silently fails in pywebview
        assert "confirmDialog('{{ _(\"delete\")" not in html, (
            "portfolio delete must not use confirmDialog/Swal (broken in pywebview)"
        )

    def test_delete_portfolio_via_service_still_works(self, session):
        """Service-level delete works regardless of UI layer."""
        _make_setting(session)
        p = _make_portfolio(session, name="ToDelete")
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=50000, currency="EUR"),
        )
        assert portfolio_service.get_counts(session) == {"portfolios": 1, "holdings": 1}
        portfolio_service.delete_portfolio(session, p.id)
        assert portfolio_service.get_counts(session) == {"portfolios": 0, "holdings": 0}


# ── Holding form adapts to portfolio kind ────────────────────────


class TestHoldingFormAdaptsToKind:
    """Template regression: the Add Holding modal must adapt to portfolio.kind.

    - For 'crypto' / 'stocks' portfolios: hide the asset_class radio (confusing)
      and use a hidden input with the fixed class.
    - Labels for quantity/avg_cost use token/share variants driven by asset class.
    - deleteHolding uses a Bootstrap modal, not confirmDialog (pywebview issue).
    """

    TEMPLATE_PATH = "templates/portfolios/detail.html"

    def test_fixed_asset_class_branch_present(self):
        with open(self.TEMPLATE_PATH) as f:
            html = f.read()
        # Conditional branch on portfolio.kind
        assert "portfolio.kind == 'mixed'" in html
        # Fixed hidden input path (monokind portfolios)
        assert 'id="h_asset_class_fixed"' in html
        assert "'crypto' if portfolio.kind == 'crypto' else 'stock'" in html

    def test_labels_dynamic_by_asset_class(self):
        with open(self.TEMPLATE_PATH) as f:
            html = f.read()
        assert 'id="h_quantity_label"' in html
        assert 'id="h_avg_cost_label"' in html
        assert "num_tokens" in html
        assert "num_shares" in html
        assert "avg_cost_per_token" in html
        assert "avg_cost_per_share" in html

    def test_delete_holding_uses_bootstrap_modal(self):
        with open(self.TEMPLATE_PATH) as f:
            html = f.read()
        assert 'id="deleteHoldingModal"' in html
        assert 'confirm-delete-holding-btn' in html
        assert "confirmDialog('{{ _(\"delete\") }}: ' + sym" not in html, (
            "deleteHolding must not use confirmDialog/Swal (broken in pywebview)"
        )


class TestHoldingLocales:
    """Ensure the new labels exist in every locale file."""

    def test_new_keys_present_in_all_locales(self):
        import json
        keys = [
            "num_tokens", "num_shares", "avg_cost_per_token", "avg_cost_per_share",
            "cash", "investments", "total_with_portfolios",
        ]
        for f in ["locales/en.json", "locales/it.json", "locales/es.json", "locales/uk.json"]:
            with open(f) as fh:
                data = json.load(fh)
            for k in keys:
                assert k in data, f"{k} missing in {f}"


class TestSourceTotalIncludesPortfolios:
    """When a source has linked portfolios, the displayed total must be
    cash_balance + portfolio_market_value (same currency). When holding
    prices change, the source total should reflect it on the next page load.
    """

    def test_portfolio_value_by_source_sums_market_value(self, session):
        _make_setting(session)
        src = _make_source(session, name="Trading", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src.id, base_currency="EUR")
        portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=2, avg_cost=20000, currency="EUR",
                          manual_price=True, last_price=25000),
        )
        by_src = portfolio_service.portfolio_value_by_source(session)
        assert by_src[src.id]["EUR"] == 50000.0

    def test_total_tracks_price_changes(self, session):
        """Verify total reflects price updates (the 'cambia dinamicamente' case)."""
        _make_setting(session, prices_enabled=True)
        src = _make_source(session, name="Trading", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src.id, base_currency="EUR")
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=1, avg_cost=20000, currency="EUR",
                          manual_price=True, last_price=20000),
        )
        assert portfolio_service.portfolio_value_by_source(session)[src.id]["EUR"] == 20000.0
        # Simulate price move
        from schemas.portfolio import HoldingUpdate
        portfolio_service.update_holding(session, h.id, HoldingUpdate(last_price=30000))
        assert portfolio_service.portfolio_value_by_source(session)[src.id]["EUR"] == 30000.0


# ── Price snapshots + history chart ──────────────────────────────


class TestPriceSnapshotsFeedHistory:
    """The source's balance_history chart must react to price changes, not
    only to cash movements. Snapshots are captured whenever a price is set
    (manual or refreshed) and `get_balance_history` sums cash + portfolio.
    """

    def _setup_portfolio(self, session, with_price: float = 100.0):
        _make_setting(session, prices_enabled=True)
        src = _make_source(session, name="Trading", currency="EUR", balance=1000)
        p = _make_portfolio(session, name="P", source_id=src.id, base_currency="EUR")
        h = portfolio_service.create_holding(
            session,
            HoldingCreate(portfolio_id=p.id, asset_class="crypto", symbol="BTC",
                          quantity=2, avg_cost=50, currency="EUR",
                          manual_price=True, last_price=with_price),
        )
        return src, p, h

    def test_manual_price_creates_snapshot(self, session):
        from models.portfolio import HoldingPriceSnapshot
        from sqlmodel import select as _select
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        snaps = list(session.exec(_select(HoldingPriceSnapshot)).all())
        assert len(snaps) == 1
        assert snaps[0].holding_id == h.id
        assert snaps[0].price == 100.0

    def test_manual_price_update_refreshes_today_snapshot(self, session):
        from models.portfolio import HoldingPriceSnapshot
        from sqlmodel import select as _select
        from schemas.portfolio import HoldingUpdate
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        portfolio_service.update_holding(session, h.id, HoldingUpdate(last_price=150.0))
        snaps = list(session.exec(_select(HoldingPriceSnapshot)).all())
        # Same day → the row is replaced, not duplicated
        assert len(snaps) == 1
        assert snaps[0].price == 150.0

    def test_portfolio_value_over_time_uses_snapshots(self, session):
        from datetime import date as _date, timedelta
        from models.portfolio import HoldingPriceSnapshot
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        # Backfill a snapshot for a past date
        d_past = _date.today() - timedelta(days=5)
        session.add(HoldingPriceSnapshot(holding_id=h.id, date=d_past, price=50.0))
        session.commit()

        values = portfolio_service.portfolio_value_by_source_over_time(
            session, src.id, [d_past, _date.today()]
        )
        assert values[d_past] == 100.0      # 2 * 50
        assert values[_date.today()] == 200.0  # 2 * 100

    def test_delete_holding_removes_its_snapshots(self, session):
        from models.portfolio import HoldingPriceSnapshot
        from sqlmodel import select as _select
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        assert session.exec(_select(HoldingPriceSnapshot)).first() is not None
        portfolio_service.delete_holding(session, h.id)
        assert session.exec(_select(HoldingPriceSnapshot)).first() is None

    def test_delete_portfolio_removes_holdings_snapshots(self, session):
        from models.portfolio import HoldingPriceSnapshot
        from sqlmodel import select as _select
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        portfolio_service.delete_portfolio(session, p.id)
        assert session.exec(_select(HoldingPriceSnapshot)).first() is None

    def test_portfolio_value_history_returns_points(self, session):
        from datetime import date as _date, timedelta
        from models.portfolio import HoldingPriceSnapshot
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        # Backfill a snapshot 3 days ago (price 80)
        d_past = _date.today() - timedelta(days=3)
        session.add(HoldingPriceSnapshot(holding_id=h.id, date=d_past, price=80.0))
        session.commit()
        history = portfolio_service.portfolio_value_history(session, p.id, "30d")
        by_date = {e["date"]: e["value"] for e in history}
        # From d_past onwards price=80 applies (until today's snapshot at 100)
        assert by_date[d_past.isoformat()] == 160.0  # 2 * 80
        assert by_date[_date.today().isoformat()] == 200.0  # 2 * 100
        # Before d_past, fallback to avg_cost (50) since no snapshot yet
        far_past = (_date.today() - timedelta(days=20)).isoformat()
        assert by_date[far_past] == 100.0  # 2 * 50

    def test_portfolio_value_history_no_holdings_empty(self, session):
        _make_setting(session)
        src = _make_source(session, name="S", currency="EUR")
        p = _make_portfolio(session, name="P", source_id=src.id, base_currency="EUR")
        assert portfolio_service.portfolio_value_history(session, p.id, "30d") == []

    def test_delete_source_delete_all_removes_snapshots(self, session):
        from models.portfolio import HoldingPriceSnapshot
        from sqlmodel import select as _select
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        source_service.delete_source(session, src.id, action="delete_all")
        assert session.exec(_select(HoldingPriceSnapshot)).first() is None

    def test_balance_history_combines_cash_and_portfolios(self, session):
        from datetime import date as _date, timedelta
        from models.movement import Movement
        from models.portfolio import HoldingPriceSnapshot
        src, p, h = self._setup_portfolio(session, with_price=100.0)
        # Add a movement (cash in) yesterday
        m = Movement(source_id=src.id, direction="in", amount=200,
                     date=_date.today() - timedelta(days=1))
        session.add(m)
        # Snapshot price of 50 for yesterday
        session.add(HoldingPriceSnapshot(
            holding_id=h.id, date=_date.today() - timedelta(days=1), price=50.0,
        ))
        session.commit()

        history = source_service.get_balance_history(session, src.id, range_str="7d")
        # Yesterday: cash = 1000 + 200, portfolio = 2*50 = 100, total = 1300
        # Today: cash = 1200, portfolio = 2*100 = 200, total = 1400
        entries = {h["date"]: h for h in history}
        yday_iso = (_date.today() - timedelta(days=1)).isoformat()
        today_iso = _date.today().isoformat()
        assert entries[yday_iso]["cash"] == 1200
        assert entries[yday_iso]["portfolios"] == 100
        assert entries[yday_iso]["balance"] == 1300
        assert entries[today_iso]["cash"] == 1200
        assert entries[today_iso]["portfolios"] == 200
        assert entries[today_iso]["balance"] == 1400
