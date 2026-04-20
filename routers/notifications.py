from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from database import get_session
from schemas.notification import NotificationRead
from services import notifications as notif_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
def list_notifications(
    skip: int = 0,
    limit: int = 50,
    is_read: bool | None = Query(default=None),
    session: Session = Depends(get_session),
):
    return notif_service.list_notifications(session, skip, limit, is_read)


@router.put("/{notification_id}/read", response_model=NotificationRead)
def mark_read(notification_id: int, session: Session = Depends(get_session)):
    return notif_service.mark_read(session, notification_id)


@router.post("/read-all", status_code=204)
def mark_all_read(session: Session = Depends(get_session)):
    notif_service.mark_all_read(session)


@router.delete("/read", status_code=204)
def delete_all_read(session: Session = Depends(get_session)):
    notif_service.delete_all_read(session)


@router.delete("/{notification_id}", status_code=204)
def delete_notification(notification_id: int, session: Session = Depends(get_session)):
    notif_service.delete_notification(session, notification_id)
