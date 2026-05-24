"""Signed undo tokens: 15-min window to delete a just-imported batch."""
from datetime import datetime

import itsdangerous
from sqlmodel import Session, delete, select

from models.movement import Movement, MovementTag
from security import get_session_secret

_UNDO_SALT = "yfine-import-undo-v1"
_UNDO_MAX_AGE = 15 * 60  # 15 minutes


def _serializer() -> itsdangerous.URLSafeTimedSerializer:
    return itsdangerous.URLSafeTimedSerializer(get_session_secret(), salt=_UNDO_SALT)


def make_undo_token(source_id: int, created_from: datetime, created_to: datetime) -> str:
    payload = {
        "source_id": source_id,
        "from": created_from.isoformat(),
        "to": created_to.isoformat(),
    }
    return _serializer().dumps(payload)


def verify_undo_token(token: str) -> dict | None:
    try:
        payload = _serializer().loads(token, max_age=_UNDO_MAX_AGE)
    except itsdangerous.SignatureExpired:
        return None
    except itsdangerous.BadSignature:
        return None
    return payload


def delete_batch(session: Session, token: str) -> int | None:
    """Return the number of movements deleted, or None if token invalid/expired."""
    payload = verify_undo_token(token)
    if payload is None:
        return None
    source_id = int(payload["source_id"])
    created_from = datetime.fromisoformat(payload["from"])
    created_to = datetime.fromisoformat(payload["to"])

    stmt = (
        select(Movement)
        .where(Movement.source_id == source_id)
        .where(Movement.created_at >= created_from)
        .where(Movement.created_at <= created_to)
    )
    from services.attachments import delete_attachments_for_movement

    movements = session.exec(stmt).all()
    count = 0
    for m in movements:
        session.exec(delete(MovementTag).where(MovementTag.movement_id == m.id))
        # Remove attachment rows AND their files on disk — a bare delete would
        # cascade the rows (FK ON) but leak the files.
        delete_attachments_for_movement(session, m.id)
        session.delete(m)
        count += 1
    session.commit()
    return count


def undo_ttl_seconds() -> int:
    return _UNDO_MAX_AGE
