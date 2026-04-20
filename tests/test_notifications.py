"""Tests for notifications service — CRUD, mark read, cleanup, counts."""
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from models.notification import Notification
from services.notifications import (
    cleanup_old_notifications,
    count_notifications,
    create_notification,
    delete_all_read,
    delete_notification,
    get_notification,
    get_unread_count,
    list_notifications,
    mark_all_read,
    mark_read,
)


# ── helpers ──────────────────────────────────────────────────────

def _notif(session, title="Test", type_="info", is_read=False, age_days=0, related_entity=None):
    n = Notification(
        type=type_, title=title, body=f"Body of {title}",
        is_read=is_read, related_entity=related_entity,
        created_at=datetime.utcnow() - timedelta(days=age_days),
    )
    session.add(n)
    session.commit()
    session.refresh(n)
    return n


# ── CRUD ─────────────────────────────────────────────────────────

class TestNotificationCRUD:
    def test_create_notification(self, session):
        n = create_notification(session, "alert", "Payment Due", "Your rent is due", "recurring:1")
        assert n.id is not None
        assert n.type == "alert"
        assert n.title == "Payment Due"
        assert n.related_entity == "recurring:1"
        assert n.is_read is False

    def test_get_notification(self, session):
        n = _notif(session, title="Found")
        assert get_notification(session, n.id).title == "Found"

    def test_get_notification_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            get_notification(session, 9999)
        assert exc.value.status_code == 404

    def test_delete_notification(self, session):
        n = _notif(session)
        delete_notification(session, n.id)
        assert session.get(Notification, n.id) is None

    def test_delete_not_found(self, session):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            delete_notification(session, 9999)


# ── Listing & Filtering ─────────────────────────────────────────

class TestNotificationListing:
    def test_list_empty(self, session):
        assert list_notifications(session) == []

    def test_list_all(self, session):
        _notif(session, "A")
        _notif(session, "B")
        _notif(session, "C")
        assert len(list_notifications(session)) == 3

    def test_list_filter_is_read(self, session):
        _notif(session, "Unread", is_read=False)
        _notif(session, "Read", is_read=True)
        unread = list_notifications(session, is_read=False)
        assert len(unread) == 1
        assert unread[0].title == "Unread"

    def test_list_filter_type(self, session):
        _notif(session, "Alert", type_="alert")
        _notif(session, "Info", type_="info")
        _notif(session, "Warning", type_="warning")
        alerts = list_notifications(session, type_filter="alert")
        assert len(alerts) == 1
        assert alerts[0].title == "Alert"

    def test_list_pagination(self, session):
        for i in range(10):
            _notif(session, f"N{i}")
        page = list_notifications(session, skip=0, limit=3)
        assert len(page) == 3

    def test_list_ordered_by_created_at_desc(self, session):
        _notif(session, "Old", age_days=10)
        _notif(session, "New", age_days=0)
        result = list_notifications(session)
        assert result[0].title == "New"
        assert result[1].title == "Old"


# ── Mark Read ────────────────────────────────────────────────────

class TestMarkRead:
    def test_mark_single_read(self, session):
        n = _notif(session)
        assert n.is_read is False
        result = mark_read(session, n.id)
        assert result.is_read is True

    def test_mark_already_read(self, session):
        n = _notif(session, is_read=True)
        result = mark_read(session, n.id)
        assert result.is_read is True  # idempotent

    def test_mark_all_read(self, session):
        _notif(session, "A")
        _notif(session, "B")
        _notif(session, "C", is_read=True)
        mark_all_read(session)
        all_notifs = list_notifications(session)
        assert all(n.is_read for n in all_notifs)

    def test_mark_all_read_empty(self, session):
        # Should not raise
        mark_all_read(session)


# ── Delete All Read ──────────────────────────────────────────────

class TestDeleteAllRead:
    def test_delete_all_read(self, session):
        _notif(session, "Read1", is_read=True)
        _notif(session, "Read2", is_read=True)
        _notif(session, "Unread", is_read=False)
        delete_all_read(session)
        remaining = list_notifications(session)
        assert len(remaining) == 1
        assert remaining[0].title == "Unread"

    def test_delete_all_read_empty(self, session):
        _notif(session, "Unread")
        delete_all_read(session)
        assert len(list_notifications(session)) == 1  # unread preserved


# ── Counts ───────────────────────────────────────────────────────

class TestNotificationCounts:
    def test_count_all(self, session):
        _notif(session, "A")
        _notif(session, "B")
        assert count_notifications(session) == 2

    def test_count_by_read_status(self, session):
        _notif(session, "Unread1")
        _notif(session, "Unread2")
        _notif(session, "Read", is_read=True)
        assert count_notifications(session, is_read=False) == 2
        assert count_notifications(session, is_read=True) == 1

    def test_count_by_type(self, session):
        _notif(session, "A", type_="alert")
        _notif(session, "B", type_="alert")
        _notif(session, "C", type_="info")
        assert count_notifications(session, type_filter="alert") == 2
        assert count_notifications(session, type_filter="warning") == 0

    def test_unread_count(self, session):
        _notif(session, "A")
        _notif(session, "B")
        _notif(session, "C", is_read=True)
        assert get_unread_count(session) == 2


# ── Cleanup ──────────────────────────────────────────────────────

class TestNotificationCleanup:
    def test_cleanup_old_read(self, session):
        _notif(session, "OldRead", is_read=True, age_days=60)
        _notif(session, "RecentRead", is_read=True, age_days=5)
        _notif(session, "OldUnread", is_read=False, age_days=60)
        deleted = cleanup_old_notifications(session, max_age_days=30)
        assert deleted == 1
        remaining = session.exec(select(Notification)).all()
        assert len(remaining) == 2
        titles = {n.title for n in remaining}
        assert "OldRead" not in titles

    def test_cleanup_trims_to_max_total(self, session):
        for i in range(20):
            _notif(session, f"N{i}", is_read=True, age_days=i)
        deleted = cleanup_old_notifications(session, max_age_days=365, max_total=10)
        assert deleted == 10
        remaining = session.exec(select(Notification)).all()
        assert len(remaining) == 10

    def test_cleanup_no_deletions(self, session):
        _notif(session, "Recent", is_read=True, age_days=1)
        _notif(session, "Unread", is_read=False, age_days=100)
        deleted = cleanup_old_notifications(session, max_age_days=30, max_total=100)
        assert deleted == 0

    def test_cleanup_empty_table(self, session):
        deleted = cleanup_old_notifications(session)
        assert deleted == 0
