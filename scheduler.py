import logging
import threading
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, select

from database import engine
from i18n import _, format_date

_logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()
_recurring_lock = threading.Lock()
_prices_lock = threading.Lock()
_yield_lock = threading.Lock()
_budget_lock = threading.Lock()


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

                # Advance alert: notify N days before due date (including due day itself).
                # last_alert_date prevents re-firing once the user reads the notification.
                alert_window_start = item.next_due_date - timedelta(days=item.alert_days_before)
                in_alert_window = alert_window_start <= today <= item.next_due_date
                already_alerted_for_due = (
                    item.last_alert_date is not None
                    and item.last_alert_date >= alert_window_start
                )
                if in_alert_window and not already_alerted_for_due:
                    # Check insufficient funds
                    if item.alert_if_insufficient and item.source_id:
                        balance = get_balance(session, item.source_id)
                        if balance < item.amount:
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
                    item.last_alert_date = today
                    session.add(item)

                # Due items: catch up every missed period in one tick.
                # Cap iterations defensively in case compute_next_due_date ever returns
                # the same date (shouldn't, but a stuck loop would hang the scheduler).
                if item.apply_mode == "auto":
                    iterations = 0
                    while item.next_due_date <= today and iterations < 3650:
                        # Stop if the rule has ended — apply_recurring_item raises
                        # HTTPException past end_date, which would abort the whole tick.
                        if item.end_date and item.next_due_date > item.end_date:
                            break
                        # Idempotency by last_fired_date: never apply the same due date twice.
                        if item.last_fired_date == item.next_due_date:
                            break
                        prev_due = item.next_due_date
                        apply_recurring_item(session, item)
                        if item.next_due_date <= prev_due:
                            # Defensive: frequency calc didn't advance — bail out.
                            break
                        iterations += 1
                elif item.apply_mode == "confirm":
                    if item.next_due_date <= today and not _has_unread_notification(session, entity, "alert"):
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


def process_source_yields():
    """Periodic job: credit due interest to sources with a yield rate set."""
    from services.sources import accrue_source_yields

    if not _yield_lock.acquire(blocking=False):
        _logger.info("Yield accrual skipped — another run is in progress")
        return
    try:
        with Session(engine) as session:
            created = accrue_source_yields(session)
            if created:
                _logger.info("Source yields accrued: %d movement(s) created", created)
    except Exception:
        _logger.exception("Source yield accrual failed")
    finally:
        _yield_lock.release()


def process_budget_alerts():
    """Periodic job: notify when a budget crosses its threshold or 100%."""
    from services.budgets import check_budget_alerts

    if not _budget_lock.acquire(blocking=False):
        _logger.info("Budget alert check skipped — another run is in progress")
        return
    try:
        with Session(engine) as session:
            fired = check_budget_alerts(session)
            if fired:
                _logger.info("Budget alerts fired: %d", fired)
    except Exception:
        _logger.exception("Budget alert check failed")
    finally:
        _budget_lock.release()


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
    # Interest accrual is date-based — credit any due periods on startup, then
    # re-check a few times a day so a long-running app keeps crediting on time.
    process_source_yields()
    scheduler.add_job(process_source_yields, "interval", hours=6, id="source_yield_job", replace_existing=True)
    # Budget alerts: check on startup, then a few times a day.
    process_budget_alerts()
    scheduler.add_job(process_budget_alerts, "interval", hours=6, id="budget_alert_job", replace_existing=True)
    # Portfolio prices: refresh on startup, then every 30 minutes.
    # `next_run_time=now` fires the first run on a scheduler thread as soon
    # as `scheduler.start()` returns, so we don't block app startup on
    # network calls but the user doesn't have to wait 30 minutes to see
    # fresh prices after opening the app.
    scheduler.add_job(
        refresh_portfolio_prices,
        "interval",
        minutes=30,
        next_run_time=datetime.now(),
        id="portfolio_prices_job",
        replace_existing=True,
    )
    scheduler.start()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
