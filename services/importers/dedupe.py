"""Duplicate detection by (source, date, amount, direction, note) hash."""
import hashlib
from datetime import date as date_type

from sqlmodel import Session, select

from models.movement import Movement
from services.importers.base import ParsedMovement


def row_hash(source_id: int, d: date_type, amount: float, direction: str, note: str | None) -> str:
    key = f"{source_id}|{d.isoformat()}|{round(float(amount), 2):.2f}|{direction}|{(note or '').strip().lower()}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def find_existing_hashes(
    session: Session, source_id: int, parsed: list[ParsedMovement]
) -> set[str]:
    if not parsed:
        return set()
    dates = [m.date for m in parsed]
    min_d = min(dates)
    max_d = max(dates)
    stmt = (
        select(Movement)
        .where(Movement.source_id == source_id)
        .where(Movement.date >= min_d)
        .where(Movement.date <= max_d)
    )
    existing = session.exec(stmt).all()
    return {
        row_hash(m.source_id, m.date, m.amount, m.direction, m.note)
        for m in existing
        if m.source_id is not None
    }


def mark_duplicates(
    session: Session,
    source_id: int | None,
    parsed: list[ParsedMovement],
) -> list[bool]:
    """Return a list[bool] aligned with `parsed` (True where row is duplicate)."""
    if source_id is None or not parsed:
        return [False] * len(parsed)
    existing = find_existing_hashes(session, source_id, parsed)
    flags: list[bool] = []
    seen_in_batch: set[str] = set()
    for m in parsed:
        h = row_hash(source_id, m.date, m.amount, m.direction, m.note)
        is_dup = h in existing or h in seen_in_batch
        seen_in_batch.add(h)
        flags.append(is_dup)
    return flags
