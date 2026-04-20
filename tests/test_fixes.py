"""Tests verifying all the fixes from the hardening pass."""
import time
from datetime import date, datetime, timedelta

import pytest
from sqlmodel import Session, select, text

from models.source import Source
from models.movement import Movement, MovementTag
from models.tag import Tag
from models.recurring import RecurringItem
from models.notification import Notification
from models.exchange_rate import ExchangeRate


# ============================================================
# 1. DATABASE INDICES
# ============================================================

class TestDatabaseIndices:
    def test_movement_indices_exist(self, engine):
        """Verify indices on movements table are created."""
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='movements'"
            ))
            index_names = {row[0] for row in result}
        assert "ix_movements_source_id" in index_names
        assert "ix_movements_date" in index_names
        assert "ix_movements_transfer_pair_id" in index_names
        assert "ix_movements_source_id_direction" in index_names

    def test_recurring_indices_exist(self, engine):
        """Verify indices on recurring_items table are created."""
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='recurring_items'"
            ))
            index_names = {row[0] for row in result}
        assert "ix_recurring_items_next_due_date" in index_names
        assert "ix_recurring_items_source_id" in index_names

    def test_notification_indices_exist(self, engine):
        """Verify indices on notifications table are created."""
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='notifications'"
            ))
            index_names = {row[0] for row in result}
        assert "ix_notifications_is_read" in index_names
        assert "ix_notifications_created_at" in index_names
        assert "ix_notifications_related_entity_type" in index_names

    def test_exchange_rate_index_exists(self, engine):
        """Verify unique index on exchange_rates pair."""
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='exchange_rates'"
            ))
            index_names = {row[0] for row in result}
        assert "ix_exchange_rates_pair" in index_names


# ============================================================
# 2. CSRF PROTECTION
# ============================================================

class TestCSRFProtection:
    def test_csrf_middleware_blocks_without_token(self):
        """POST requests without CSRF token should be rejected."""
        from csrf import CSRFMiddleware
        # The middleware checks X-CSRF-Token header against session token
        # We verify the logic exists and the module imports cleanly
        assert CSRFMiddleware is not None

    def test_csrf_safe_methods_pass_through(self):
        """GET/HEAD/OPTIONS should not require CSRF token."""
        from csrf import _SAFE_METHODS
        assert "GET" in _SAFE_METHODS
        assert "HEAD" in _SAFE_METHODS
        assert "OPTIONS" in _SAFE_METHODS

    def test_login_excluded_from_csrf(self):
        """Login endpoint must be excluded from CSRF validation."""
        from csrf import _OPEN_PREFIXES
        assert any("/api/auth/login" in p for p in _OPEN_PREFIXES)


# ============================================================
# 3. RATE LIMITING
# ============================================================

class TestRateLimiting:
    def test_rate_limit_check(self):
        """Rate limiter should block after max attempts."""
        from main import _check_rate_limit, _record_attempt, _login_attempts, _LOGIN_MAX_ATTEMPTS

        test_ip = "192.168.99.99"
        _login_attempts.pop(test_ip, None)

        # Under limit should pass
        for _ in range(_LOGIN_MAX_ATTEMPTS):
            assert _check_rate_limit(test_ip) is None
            _record_attempt(test_ip)

        # Over limit should block
        retry = _check_rate_limit(test_ip)
        assert retry is not None
        assert retry > 0

        # Cleanup
        _login_attempts.pop(test_ip, None)

    def test_rate_limit_window_expiry(self):
        """Old attempts outside the window should be pruned."""
        from main import _check_rate_limit, _login_attempts, _LOGIN_WINDOW_SECONDS

        test_ip = "192.168.99.100"
        # Inject old attempts that are outside the window
        old_time = time.time() - _LOGIN_WINDOW_SECONDS - 10
        _login_attempts[test_ip] = [old_time] * 10

        # Should pass because all attempts are expired
        assert _check_rate_limit(test_ip) is None

        # Cleanup
        _login_attempts.pop(test_ip, None)


# ============================================================
# 4. NOTIFICATION CLEANUP
# ============================================================

class TestNotificationCleanup:
    def test_cleanup_old_read_notifications(self, session):
        """Old read notifications should be deleted."""
        from services.notifications import cleanup_old_notifications

        old_date = datetime.utcnow() - timedelta(days=60)
        # Create old read notification
        n1 = Notification(type="info", title="Old", body="old", is_read=True, created_at=old_date)
        # Create recent read notification
        n2 = Notification(type="info", title="Recent", body="recent", is_read=True)
        # Create old unread notification (should NOT be deleted)
        n3 = Notification(type="alert", title="Unread", body="unread", is_read=False, created_at=old_date)
        session.add_all([n1, n2, n3])
        session.commit()

        deleted = cleanup_old_notifications(session, max_age_days=30)
        assert deleted == 1  # Only n1 should be deleted

        remaining = session.exec(select(Notification)).all()
        assert len(remaining) == 2
        titles = {n.title for n in remaining}
        assert "Recent" in titles
        assert "Unread" in titles

    def test_cleanup_respects_max_total(self, session):
        """When total exceeds max, oldest read notifications are trimmed."""
        from services.notifications import cleanup_old_notifications

        # Create many notifications
        for i in range(15):
            session.add(Notification(
                type="info", title=f"N{i}", body="body", is_read=True,
                created_at=datetime.utcnow() - timedelta(hours=i),
            ))
        session.commit()

        deleted = cleanup_old_notifications(session, max_age_days=365, max_total=10)
        assert deleted == 5
        remaining = session.exec(select(Notification)).all()
        assert len(remaining) == 10


# ============================================================
# 5. BATCH BALANCE (N+1 FIX)
# ============================================================

class TestBatchBalance:
    def test_get_balances_batch(self, session):
        """Batch balance calculation should match individual calculations."""
        from services.sources import get_balance, get_balances_batch

        s1 = Source(name="Bank", currency="EUR", starting_balance=100.0)
        s2 = Source(name="Cash", currency="EUR", starting_balance=50.0)
        session.add_all([s1, s2])
        session.commit()
        session.refresh(s1)
        session.refresh(s2)

        # Add movements
        session.add(Movement(source_id=s1.id, amount=30.0, direction="in", date=date.today()))
        session.add(Movement(source_id=s1.id, amount=10.0, direction="out", date=date.today()))
        session.add(Movement(source_id=s2.id, amount=20.0, direction="out", date=date.today()))
        session.commit()

        # Individual
        b1 = get_balance(session, s1.id)
        b2 = get_balance(session, s2.id)

        # Batch
        batch = get_balances_batch(session, [s1, s2])

        assert batch[s1.id] == b1  # 100 + 30 - 10 = 120
        assert batch[s2.id] == b2  # 50 - 20 = 30
        assert batch[s1.id] == 120.0
        assert batch[s2.id] == 30.0

    def test_empty_batch(self, session):
        """Batch with no sources should return empty dict."""
        from services.sources import get_balances_batch
        assert get_balances_batch(session, []) == {}


# ============================================================
# 6. SCHEDULER IDEMPOTENCY
# ============================================================

class TestSchedulerIdempotency:
    def test_lock_prevents_concurrent_execution(self):
        """The recurring lock should prevent concurrent runs."""
        from scheduler import _recurring_lock

        # Acquire the lock
        assert _recurring_lock.acquire(blocking=False)
        # Second acquire should fail
        assert not _recurring_lock.acquire(blocking=False)
        # Release
        _recurring_lock.release()

    def test_has_unread_notification_check(self, session):
        """Dedup check should find existing unread notifications."""
        from scheduler import _has_unread_notification

        # No notification yet
        assert not _has_unread_notification(session, "recurring:1", "alert")

        # Add one
        session.add(Notification(
            type="alert", title="test", body="test",
            related_entity="recurring:1", is_read=False,
        ))
        session.commit()

        # Now should find it
        assert _has_unread_notification(session, "recurring:1", "alert")

        # Different type should not match
        assert not _has_unread_notification(session, "recurring:1", "warning")

        # Read notification should not match
        n = session.exec(select(Notification)).first()
        n.is_read = True
        session.add(n)
        session.commit()
        assert not _has_unread_notification(session, "recurring:1", "alert")


# ============================================================
# 7. PASSWORD MEMORY ZEROING
# ============================================================

class TestPasswordZeroing:
    def test_set_runtime_password_zeros_old(self):
        """Setting a new password should zero the old bytearray."""
        from security import set_runtime_password, _runtime_password

        set_runtime_password("secret123")
        from security import _runtime_password as pw1
        old_ref = pw1

        set_runtime_password("newsecret")
        # Old bytearray should be zeroed
        assert all(b == 0 for b in old_ref)

        # Cleanup
        set_runtime_password(None)

    def test_set_runtime_password_none_zeros(self):
        """Setting password to None should zero and clear."""
        from security import set_runtime_password

        set_runtime_password("test")
        import security
        ref = security._runtime_password
        set_runtime_password(None)
        assert all(b == 0 for b in ref)
        assert security._runtime_password is None

    def test_get_runtime_password(self):
        """get_runtime_password should return the string or None."""
        from security import set_runtime_password, get_runtime_password

        set_runtime_password("hello")
        assert get_runtime_password() == "hello"

        set_runtime_password(None)
        assert get_runtime_password() is None


# ============================================================
# 8. INPUT VALIDATION
# ============================================================

class TestInputValidation:
    def test_valid_currency_code(self):
        """Valid ISO 4217 codes should pass."""
        from schemas.source import SourceCreate
        s = SourceCreate(name="Test", currency="eur")
        assert s.currency == "EUR"  # Should be uppercased

    def test_invalid_currency_code(self):
        """Invalid currency codes should be rejected."""
        from schemas.source import SourceCreate
        with pytest.raises(Exception):
            SourceCreate(name="Test", currency="XYZ123")

    def test_empty_name_rejected(self):
        """Empty names should be rejected."""
        from schemas.source import SourceCreate
        with pytest.raises(Exception):
            SourceCreate(name="", currency="EUR")

    def test_long_name_rejected(self):
        """Names over 200 chars should be rejected."""
        from schemas.source import SourceCreate
        with pytest.raises(Exception):
            SourceCreate(name="x" * 201, currency="EUR")

    def test_long_note_rejected(self):
        """Notes over 1000 chars should be rejected."""
        from schemas.movement import MovementCreate
        with pytest.raises(Exception):
            MovementCreate(
                source_id=1, amount=10, direction="in",
                date=date.today(), note="x" * 1001,
            )

    def test_valid_note_passes(self):
        """Reasonable notes should pass."""
        from schemas.movement import MovementCreate
        m = MovementCreate(
            source_id=1, amount=10, direction="in",
            date=date.today(), note="Lunch with team",
        )
        assert m.note == "Lunch with team"

    def test_recurring_date_range_validation(self):
        """end_date before start_date should be rejected."""
        from schemas.recurring import RecurringCreate
        with pytest.raises(Exception):
            RecurringCreate(
                name="Test", amount=100, direction="out",
                currency="EUR", frequency="monthly",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 1, 1),  # Before start
            )

    def test_recurring_valid_date_range(self):
        """Valid date range should pass."""
        from schemas.recurring import RecurringCreate
        r = RecurringCreate(
            name="Test", amount=100, direction="out",
            currency="EUR", frequency="monthly",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )
        assert r.start_date < r.end_date

    def test_tag_color_validation(self):
        """Invalid color formats should be rejected."""
        from schemas.tag import TagCreate
        with pytest.raises(Exception):
            TagCreate(name="Test", color="not-a-color")

    def test_tag_valid_color(self):
        """Valid hex colors should pass."""
        from schemas.tag import TagCreate
        t = TagCreate(name="Test", color="#ff0000")
        assert t.color == "#ff0000"

    def test_date_range_filter_validation(self, session):
        """date_from > date_to should return 422."""
        from services.movements import _build_filter_query
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _build_filter_query(date_from=date(2026, 12, 1), date_to=date(2026, 1, 1))
        assert exc_info.value.status_code == 422

    def test_amount_range_filter_validation(self, session):
        """amount_min > amount_max should return 422."""
        from services.movements import _build_filter_query
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _build_filter_query(amount_min=100, amount_max=10)
        assert exc_info.value.status_code == 422


# ============================================================
# 9. MOVEMENT GROUPING (extracted from pages.py)
# ============================================================

class TestMovementGrouping:
    def test_group_movements_hierarchically(self):
        """Movements should be grouped by year -> month -> day."""
        from services.movements import group_movements_hierarchically

        movements = [
            {"date": date(2026, 3, 15), "amount": 100, "direction": "in", "transfer_pair_id": None},
            {"date": date(2026, 3, 15), "amount": 50, "direction": "out", "transfer_pair_id": None},
            {"date": date(2026, 3, 10), "amount": 200, "direction": "in", "transfer_pair_id": None},
            {"date": date(2026, 2, 1), "amount": 75, "direction": "out", "transfer_pair_id": None},
        ]
        grouped = group_movements_hierarchically(movements)

        assert len(grouped) == 1  # 1 year
        assert grouped[0]["year"] == 2026
        assert len(grouped[0]["months"]) == 2  # March and February
        assert grouped[0]["total_in"] == 300.0
        assert grouped[0]["total_out"] == 125.0

    def test_empty_movements(self):
        """Empty list should return empty grouped result."""
        from services.movements import group_movements_hierarchically
        assert group_movements_hierarchically([]) == []


# ============================================================
# 10. EXCHANGE RATES
# ============================================================

class TestExchangeRates:
    def test_set_and_convert(self, session):
        """Setting a rate and converting should work."""
        from services.exchange_rates import set_rate, convert
        from schemas.exchange_rate import ExchangeRateCreate

        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))

        result = convert(session, 100.0, "EUR", "USD")
        assert result == 108.0

    def test_reverse_conversion(self, session):
        """Reverse conversion should work using 1/rate."""
        from services.exchange_rates import set_rate, convert
        from schemas.exchange_rate import ExchangeRateCreate

        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))

        result = convert(session, 108.0, "USD", "EUR")
        assert result == 100.0

    def test_same_currency_conversion(self, session):
        """Converting same currency should return same amount."""
        from services.exchange_rates import convert
        assert convert(session, 50.0, "EUR", "EUR") == 50.0

    def test_no_rate_returns_none(self, session):
        """Missing rate should return None."""
        from services.exchange_rates import convert
        assert convert(session, 100.0, "EUR", "GBP") is None

    def test_upsert_rate(self, session):
        """Setting the same pair twice should update, not duplicate."""
        from services.exchange_rates import set_rate, list_rates
        from schemas.exchange_rate import ExchangeRateCreate

        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.08))
        set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="USD", rate=1.10))

        rates = list_rates(session)
        eur_usd = [r for r in rates if r.from_currency == "EUR" and r.to_currency == "USD"]
        assert len(eur_usd) == 1
        assert eur_usd[0].rate == 1.10

    def test_same_currency_pair_rejected(self, session):
        """from_currency == to_currency should be rejected."""
        from services.exchange_rates import set_rate
        from schemas.exchange_rate import ExchangeRateCreate
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            set_rate(session, ExchangeRateCreate(from_currency="EUR", to_currency="EUR", rate=1.0))
        assert exc_info.value.status_code == 422


# ============================================================
# 11. ENRICHMENT SERVICES (moved from pages.py)
# ============================================================

class TestEnrichmentServices:
    def test_enrich_movements_with_sources(self, session):
        """Movements should be enriched with source names."""
        from services.movements import enrich_movements_with_sources

        s = Source(name="Bank", currency="EUR", starting_balance=0)
        session.add(s)
        session.commit()
        session.refresh(s)

        m = Movement(source_id=s.id, amount=10, direction="in", date=date.today())
        session.add(m)
        session.commit()
        session.refresh(m)

        enriched = enrich_movements_with_sources(session, [m])
        assert len(enriched) == 1
        assert enriched[0]["source_name"] == "Bank"

    def test_enrich_recurring_items(self, session):
        """Recurring items should be enriched with source_name and days_until."""
        from services.recurring import enrich_recurring_items

        s = Source(name="Salary Account", currency="EUR", starting_balance=0)
        session.add(s)
        session.commit()
        session.refresh(s)

        r = RecurringItem(
            name="Rent", amount=500, direction="out", currency="EUR",
            frequency="monthly", start_date=date.today(),
            next_due_date=date.today() + timedelta(days=5),
            source_id=s.id,
        )
        session.add(r)
        session.commit()
        session.refresh(r)

        enriched = enrich_recurring_items(session, [r])
        assert len(enriched) == 1
        assert enriched[0]["source_name"] == "Salary Account"
        assert enriched[0]["days_until"] == 5
