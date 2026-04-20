"""Tests for whim service — CRUD, dismiss, restore, purchase."""
from datetime import date

import pytest
from fastapi import HTTPException

from models.source import Source
from models.whim import Whim
from schemas.whim import WhimCreate
from services.whims import (
    create_whim,
    delete_whim,
    dismiss_whim,
    get_whim,
    list_whims,
    restore_whim,
)


# ── helpers ──────────────────────────────────────────────────────

def _whim(session, name="Shoes", amount=80, currency="EUR",
          priority="medium", source_id=None, note=None):
    return create_whim(session, WhimCreate(
        name=name, amount=amount, currency=currency,
        priority=priority, source_id=source_id, note=note,
    ))


# ── Create + list ────────────────────────────────────────────────

class TestWhimCRUD:
    def test_create_defaults_pending(self, session):
        w = _whim(session)
        assert w.status == "pending"
        assert w.purchased_at is None

    def test_list_returns_only_pending_by_default(self, session):
        _whim(session, name="A")
        b = _whim(session, name="B")
        dismiss_whim(session, b.id)
        pending = list_whims(session, status="pending")
        names = {w.name for w in pending}
        assert names == {"A"}

    def test_delete_removes_row(self, session):
        w = _whim(session)
        delete_whim(session, w.id)
        with pytest.raises(HTTPException):
            get_whim(session, w.id)


# ── Dismiss / Restore ────────────────────────────────────────────

class TestWhimDismissRestore:
    def test_dismiss_sets_status(self, session):
        w = _whim(session)
        dismissed = dismiss_whim(session, w.id)
        assert dismissed.status == "dismissed"
        # Round-trip: fetched again from DB
        assert get_whim(session, w.id).status == "dismissed"

    def test_restore_pending_raises(self, session):
        """Can't restore a whim that's already pending."""
        w = _whim(session)
        with pytest.raises(HTTPException) as exc:
            restore_whim(session, w.id)
        assert exc.value.status_code == 422

    def test_restore_dismissed_returns_to_pending(self, session):
        w = _whim(session)
        dismiss_whim(session, w.id)
        restored = restore_whim(session, w.id)
        assert restored.status == "pending"
        # Round-trip
        assert get_whim(session, w.id).status == "pending"

    def test_restore_updates_timestamp(self, session):
        w = _whim(session)
        dismiss_whim(session, w.id)
        before = get_whim(session, w.id).updated_at
        import time; time.sleep(0.01)
        restored = restore_whim(session, w.id)
        assert restored.updated_at > before

    def test_restore_missing_whim_raises_404(self, session):
        with pytest.raises(HTTPException) as exc:
            restore_whim(session, 9999)
        assert exc.value.status_code == 404

    def test_dismiss_then_restore_then_dismiss_cycle(self, session):
        w = _whim(session)
        dismiss_whim(session, w.id)
        restore_whim(session, w.id)
        dismissed_again = dismiss_whim(session, w.id)
        assert dismissed_again.status == "dismissed"

    def test_restore_purchased_raises(self, session):
        """Restore only works on dismissed, not purchased."""
        w = _whim(session)
        # Mark as purchased directly (no purchase helper needed — test the guard)
        w.status = "purchased"
        session.add(w); session.commit()
        with pytest.raises(HTTPException) as exc:
            restore_whim(session, w.id)
        assert exc.value.status_code == 422
