"""Commit parsed movements into the DB, reusing services.movements.create_movement."""
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session

from schemas.movement import MovementCreate
from services import movements as movement_service
from services.importers.base import ParsedMovement


@dataclass
class CommitResult:
    imported: int
    skipped: int
    created_from: datetime
    created_to: datetime
    source_id: int


def commit(
    session: Session,
    parsed: list[ParsedMovement],
    source_id: int,
    include_flags: list[bool],
    tag_ids: list[int] | None = None,
    exclude_from_stats: bool = False,
) -> CommitResult:
    """Create Movement records for rows where include_flags[i] is True."""
    if len(include_flags) != len(parsed):
        raise ValueError("include_flags length mismatch with parsed movements")

    created_from = datetime.utcnow()
    imported = 0
    skipped = 0
    tag_ids = tag_ids or []

    for movement, include in zip(parsed, include_flags):
        if not include:
            skipped += 1
            continue
        data = MovementCreate(
            source_id=source_id,
            amount=float(movement.amount),
            direction=movement.direction,
            date=movement.date,
            note=movement.note,
            tag_ids=tag_ids,
        )
        created = movement_service.create_movement(session, data)
        if exclude_from_stats:
            created.exclude_from_stats = True
            session.add(created)
        imported += 1

    if exclude_from_stats and imported:
        session.commit()

    created_to = datetime.utcnow()
    return CommitResult(
        imported=imported,
        skipped=skipped,
        created_from=created_from,
        created_to=created_to,
        source_id=source_id,
    )
