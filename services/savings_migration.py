"""One-shot wizard: convert the legacy `savings` table into transfer-backed
contributions on per-currency savings funds.

Exposed via /api/savings/wizard/* and rendered in the Savings page when
needed. After a successful run the legacy rows are deleted.
"""
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select, func, col

from models.movement import Movement, MovementTag
from models.saving import Saving, SavingTag
from models.source import Source
from services import savings_fund as fund_service


def needs_wizard(session: Session) -> bool:
    """Do we still have legacy Saving rows that haven't been migrated?"""
    count = session.exec(select(func.count(Saving.id))).one()
    return int(count or 0) > 0


def preview(session: Session) -> dict:
    """Summarize the legacy data so the UI can show the user what they're
    about to migrate."""
    rows = session.exec(
        select(Saving.currency, func.count(Saving.id), func.sum(Saving.amount))
        .group_by(Saving.currency)
    ).all()
    by_currency = [
        {"currency": r[0], "count": int(r[1] or 0), "total": round(float(r[2] or 0.0), 2)}
        for r in rows
    ]
    earliest = session.exec(select(func.min(Saving.date))).first()
    latest = session.exec(select(func.max(Saving.date))).first()
    return {
        "count": sum(b["count"] for b in by_currency),
        "by_currency": by_currency,
        "earliest_date": str(earliest) if earliest else None,
        "latest_date": str(latest) if latest else None,
    }


def _tags_for_saving(session: Session, saving_id: int) -> list[int]:
    return [
        t.tag_id
        for t in session.exec(
            select(SavingTag).where(SavingTag.saving_id == saving_id)
        ).all()
    ]


def _migrate_as_movements(
    session: Session,
    unified_source_id: Optional[int],
) -> int:
    """Create one transfer per legacy saving. Source side is either
    `unified_source_id` (all savings came from here) or None (external)."""
    rows = list(session.exec(select(Saving).order_by(col(Saving.date))).all())
    if not rows:
        return 0

    unified_src = None
    if unified_source_id is not None:
        unified_src = session.get(Source, unified_source_id)
        if not unified_src:
            raise HTTPException(status_code=404, detail="Source not found")
        if unified_src.is_savings_fund:
            raise HTTPException(status_code=422, detail="Pick a regular source")

    count = 0
    for s in rows:
        currency = (s.currency or "").upper()
        if unified_src is not None and unified_src.currency != currency:
            # Mixed-currency history with a single source picked — fall back
            # to external for the rows that don't match.
            out_source_id = None
        else:
            out_source_id = unified_src.id if unified_src else None

        fund = fund_service.ensure_fund_for_currency(session, currency)

        out_mv = Movement(
            source_id=out_source_id,
            amount=s.amount,
            direction="out",
            date=s.date,
            note=s.description or s.note,
        )
        in_mv = Movement(
            source_id=fund.id,
            amount=s.amount,
            direction="in",
            date=s.date,
            note=s.description or s.note,
            is_savings_contribution=True,
        )
        session.add(out_mv)
        session.add(in_mv)
        session.flush()
        out_mv.transfer_pair_id = in_mv.id
        in_mv.transfer_pair_id = out_mv.id
        session.add(out_mv)
        session.add(in_mv)

        for tag_id in _tags_for_saving(session, s.id):
            session.add(MovementTag(movement_id=in_mv.id, tag_id=tag_id))
            session.add(MovementTag(movement_id=out_mv.id, tag_id=tag_id))
        count += 1

    # Done — drop the legacy rows so the wizard won't re-fire.
    for s in rows:
        for t in session.exec(
            select(SavingTag).where(SavingTag.saving_id == s.id)
        ).all():
            session.delete(t)
        session.delete(s)

    session.commit()
    return count


def _migrate_as_starting_balance(session: Session) -> int:
    """Collapse the legacy data into a single opening balance per fund.
    Fast but you lose per-saving granularity."""
    rows = session.exec(
        select(Saving.currency, func.sum(Saving.amount))
        .group_by(Saving.currency)
    ).all()
    if not rows:
        return 0
    for currency, total in rows:
        cur = (currency or "").upper()
        fund = fund_service.ensure_fund_for_currency(session, cur)
        fund.starting_balance += float(total or 0.0)
        fund.updated_at = datetime.utcnow()
        session.add(fund)
    # Drop legacy tagged rows.
    for s in session.exec(select(Saving)).all():
        for t in session.exec(
            select(SavingTag).where(SavingTag.saving_id == s.id)
        ).all():
            session.delete(t)
        session.delete(s)
    session.commit()
    return int(sum(1 for _ in rows))


def _discard_all(session: Session) -> int:
    """Drop every legacy saving and start from zero."""
    count = 0
    for s in session.exec(select(Saving)).all():
        for t in session.exec(
            select(SavingTag).where(SavingTag.saving_id == s.id)
        ).all():
            session.delete(t)
        session.delete(s)
        count += 1
    session.commit()
    return count


def run(
    session: Session,
    mode: str,
    unified_source_id: Optional[int] = None,
) -> dict:
    if mode == "movements":
        migrated = _migrate_as_movements(session, unified_source_id)
        return {"mode": mode, "migrated": migrated}
    if mode == "starting_balance":
        migrated = _migrate_as_starting_balance(session)
        return {"mode": mode, "funds_touched": migrated}
    if mode == "discard":
        dropped = _discard_all(session)
        return {"mode": mode, "dropped": dropped}
    raise HTTPException(status_code=422, detail=f"Unknown mode: {mode}")
