from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select, col, func

from models.notification import Notification


def list_notifications(
    session: Session,
    skip: int = 0,
    limit: int = 50,
    is_read: bool | None = None,
    type_filter: str | None = None,
) -> list[Notification]:
    query = select(Notification).order_by(col(Notification.created_at).desc()).offset(skip).limit(limit)
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)
    if type_filter:
        query = query.where(Notification.type == type_filter)
    return list(session.exec(query).all())


def get_notification(session: Session, notification_id: int) -> Notification:
    notification = session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notification


def create_notification(
    session: Session, type: str, title: str, body: str, related_entity: str | None = None
) -> Notification:
    notification = Notification(
        type=type, title=title, body=body, related_entity=related_entity
    )
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification


def mark_read(session: Session, notification_id: int) -> Notification:
    notification = get_notification(session, notification_id)
    notification.is_read = True
    session.add(notification)
    session.commit()
    session.refresh(notification)
    return notification


def mark_all_read(session: Session) -> None:
    notifications = session.exec(
        select(Notification).where(Notification.is_read == False)  # noqa: E712
    ).all()
    for n in notifications:
        n.is_read = True
        session.add(n)
    session.commit()


def delete_notification(session: Session, notification_id: int) -> None:
    notification = get_notification(session, notification_id)
    session.delete(notification)
    session.commit()


def delete_all_read(session: Session) -> None:
    notifications = session.exec(
        select(Notification).where(Notification.is_read == True)  # noqa: E712
    ).all()
    for n in notifications:
        session.delete(n)
    session.commit()


def count_notifications(
    session: Session,
    is_read: bool | None = None,
    type_filter: str | None = None,
) -> int:
    query = select(func.count(Notification.id))
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)
    if type_filter:
        query = query.where(Notification.type == type_filter)
    return int(session.exec(query).one())


def get_unread_count(session: Session) -> int:
    result = session.exec(
        select(func.count(Notification.id)).where(Notification.is_read == False)  # noqa: E712
    ).one()
    return int(result)


def cleanup_old_notifications(session: Session, max_age_days: int = 30, max_total: int = 500) -> int:
    """Delete old read notifications to prevent table bloat.

    Deletes read notifications older than max_age_days, and if the total count
    still exceeds max_total, trims the oldest read notifications down to that limit.
    Returns the number of deleted notifications.
    """
    deleted = 0

    # Phase 1: delete read notifications older than max_age_days
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    old_read = session.exec(
        select(Notification).where(
            Notification.is_read == True,  # noqa: E712
            Notification.created_at < cutoff,
        )
    ).all()
    for n in old_read:
        session.delete(n)
        deleted += 1

    # Phase 2: if total still exceeds max_total, trim oldest read notifications
    total = session.exec(select(func.count(Notification.id))).one()
    if int(total) > max_total:
        excess = int(total) - max_total
        to_trim = session.exec(
            select(Notification)
            .where(Notification.is_read == True)  # noqa: E712
            .order_by(col(Notification.created_at))
            .limit(excess)
        ).all()
        for n in to_trim:
            session.delete(n)
            deleted += 1

    if deleted:
        session.commit()
    return deleted
