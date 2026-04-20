import logging
import threading
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from database import engine
from i18n import _, format_date

_logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()
_recurring_lock = threading.Lock()
_prices_lock = threading.Lock()


def _has_unread_notification(session, related_entity: str, notif_type: str) -> bool:
    """Check if an unread notification already exists for this entity and type."""
    from models import Notification
    existing = session.exec(
        select(Notification).where(
            Notification.related_entity == related_entity,
            Notification.type == notif_type,
            Notification.is_read == False,  # noqa: E712
        )
    ).first()
    return existing is not None


def process_recurring_items():
    from models import RecurringItem, Notification
    from services.recurring import apply_recurring_item, compute_next_due_date
    from services.sources import get_balance

    # Prevent concurrent execution (e.g. startup + hourly job overlap)
    if not _recurring_lock.acquire(blocking=False):
        _logger.info("Recurring job skipped — another instance is running")
        return

    try:
        today = date.today()
        with Session(engine) as session:
            items = session.exec(select(RecurringItem)).all()
            for item in items:
                entity = f"recurring:{item.id}"

                # Skip ended items
                if item.end_date and item.end_date < today:
                    continue

                # Advance alert: notify N days before due date (including due day itself)
                alert_date = item.next_due_date - timedelta(days=item.alert_days_before)
                if alert_date <= today <= item.next_due_date:
                    if not _has_unread_notification(session, entity, "alert"):
                        # Check insufficient funds
                        if item.alert_if_insufficient and item.source_id:
                            balance = get_balance(session, item.source_id)
                            if balance < item.amount:
                                if not _has_unread_notification(session, entity, "warning"):
                                    notification = Notification(
                                        type="warning",
                                        title=f"⚠️ {item.name}",
                                        body=f"{_('balance')}: {balance:.2f} — {_('amount')}: {item.amount:.2f} {item.currency}. {format_date(item.next_due_date)}",
                                        related_entity=entity,
                                    )
                                    session.add(notification)

                        direction_label = _('income') if item.direction == 'in' else _('expense')
                        sign = '+' if item.direction == 'in' else '-'
                        notification = Notification(
                            type="alert",
                            title=f"📅 {item.name}",
                            body=f"{direction_label} {sign}{item.amount:.2f} {item.currency} — {format_date(item.next_due_date)}",
                            related_entity=entity,
                        )
                        session.add(notification)

                # Due items
                if item.next_due_date <= today:
                    if item.apply_mode == "auto":
                        # Idempotency: check if a movement was already created for this due date
                        from models import Movement
                        already_applied = session.exec(
                            select(Movement).where(
                                Movement.source_id == item.source_id,
                                Movement.date == item.next_due_date,
                                Movement.note.contains(f"Recurring: {item.name}"),  # type: ignore
                            )
                        ).first()
                        if not already_applied:
                            apply_recurring_item(session, item)
                    elif item.apply_mode == "confirm":
                        if not _has_unread_notification(session, entity, "alert"):
                            direction_label = _('income') if item.direction == 'in' else _('expense')
                            sign = '+' if item.direction == 'in' else '-'
                            notification = Notification(
                                type="alert",
                                title=f"✅ {_('confirm')}: {item.name}",
                                body=f"{direction_label} {sign}{item.amount:.2f} {item.currency} — {format_date(item.next_due_date)}",
                                related_entity=entity,
                            )
                            session.add(notification)

            session.commit()
    finally:
        _recurring_lock.release()


def cleanup_notifications():
    """Periodic job: delete old read notifications to prevent table bloat."""
    from services.notifications import cleanup_old_notifications

    with Session(engine) as session:
        deleted = cleanup_old_notifications(session)
        if deleted:
            import logging
            logging.getLogger(__name__).info("Notification cleanup: removed %d old notifications", deleted)


def refresh_portfolio_prices():
    """Periodic job: refresh holding prices if the user has opted in."""
    if not _prices_lock.acquire(blocking=False):
        _logger.info("Price refresh skipped — another run is in progress")
        return
    try:
        from services.prices import refresh_all_holdings, are_prices_enabled
        with Session(engine) as session:
            if not are_prices_enabled(session):
                return
            updated = refresh_all_holdings(session)
            if updated:
                _logger.info("Portfolio prices refreshed: %d holdings updated", updated)
    except Exception:
        _logger.exception("Portfolio price refresh failed")
    finally:
        _prices_lock.release()


def start_scheduler():
    if scheduler.running:
        return
    # Run immediately on startup, then every hour
    process_recurring_items()
    scheduler.add_job(process_recurring_items, "interval", hours=1, id="recurring_job", replace_existing=True)
    scheduler.add_job(cleanup_notifications, "interval", hours=24, id="notification_cleanup_job", replace_existing=True)
    # Portfolio prices: refresh every 30 minutes (only if enabled in settings)
    scheduler.add_job(refresh_portfolio_prices, "interval", minutes=30, id="portfolio_prices_job", replace_existing=True)
    scheduler.start()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
