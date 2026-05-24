from datetime import date as date_type, datetime

from fastapi import HTTPException
from sqlmodel import Session, select, col, func

from models.movement import Movement, MovementTag
from models.source import Source
from models.tag import Tag
from schemas.movement import MovementCreate, MovementUpdate, TransferCreate, TransferUpdate


def _build_filter_query(
    source_id: int | None = None,
    tag_ids: list[int] | None = None,
    direction: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    exclude_transfer_in: bool = False,
    q: str | None = None,
    tag_match: str = "or",
):
    # Validate date range
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to")
    # Validate amount range
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        raise HTTPException(status_code=422, detail="amount_min must not be greater than amount_max")

    if tag_ids:
        query = (
            select(Movement)
            .join(MovementTag, Movement.id == MovementTag.movement_id)
            .where(col(MovementTag.tag_id).in_(tag_ids))
        )
        if tag_match == "and":
            # Keep only movements carrying ALL selected tags.
            query = query.group_by(col(Movement.id)).having(
                func.count(func.distinct(MovementTag.tag_id)) == len(tag_ids)
            )
        else:
            query = query.distinct()
    else:
        query = select(Movement)
    if source_id is not None:
        query = query.where(Movement.source_id == source_id)
    if direction is not None:
        query = query.where(Movement.direction == direction)
    if date_from is not None:
        query = query.where(Movement.date >= date_from)
    if date_to is not None:
        query = query.where(Movement.date <= date_to)
    if amount_min is not None:
        query = query.where(Movement.amount >= amount_min)
    if amount_max is not None:
        query = query.where(Movement.amount <= amount_max)
    if q:
        # Case-insensitive substring search on the note; escape LIKE wildcards
        # so a literal % or _ in the query doesn't act as a wildcard.
        like = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(col(Movement.note).ilike(f"%{like}%", escape="\\"))
    if exclude_transfer_in:
        from sqlalchemy import or_
        query = query.where(
            or_(Movement.transfer_pair_id == None, Movement.direction != "in")  # noqa: E711
        )
    return query


def list_movements(
    session: Session,
    skip: int = 0,
    limit: int = 50,
    source_id: int | None = None,
    tag_ids: list[int] | None = None,
    direction: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    exclude_transfer_in: bool = False,
    q: str | None = None,
    tag_match: str = "or",
) -> list[Movement]:
    query = _build_filter_query(source_id, tag_ids, direction, date_from, date_to, amount_min, amount_max, exclude_transfer_in, q, tag_match)
    query = query.order_by(col(Movement.date).desc(), col(Movement.id).desc()).offset(skip).limit(limit)
    return list(session.exec(query).all())


def count_movements(
    session: Session,
    source_id: int | None = None,
    tag_ids: list[int] | None = None,
    direction: str | None = None,
    date_from: date_type | None = None,
    date_to: date_type | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    exclude_transfer_in: bool = False,
    q: str | None = None,
    tag_match: str = "or",
) -> int:
    base = _build_filter_query(source_id, tag_ids, direction, date_from, date_to, amount_min, amount_max, exclude_transfer_in, q, tag_match)
    # Replace the selected columns with a count
    count_query = select(func.count()).select_from(base.subquery())
    return session.exec(count_query).one()


def get_movement(session: Session, movement_id: int) -> Movement:
    movement = session.get(Movement, movement_id)
    if not movement:
        raise HTTPException(status_code=404, detail="Movement not found")
    return movement


def get_movement_tags(session: Session, movement_id: int) -> list[Tag]:
    links = session.exec(
        select(MovementTag).where(MovementTag.movement_id == movement_id)
    ).all()
    tag_ids = [link.tag_id for link in links]
    if not tag_ids:
        return []
    return list(session.exec(select(Tag).where(col(Tag.id).in_(tag_ids))).all())


def _set_tags(session: Session, movement_id: int, tag_ids: list[int]):
    # Remove existing
    existing = session.exec(
        select(MovementTag).where(MovementTag.movement_id == movement_id)
    ).all()
    for link in existing:
        session.delete(link)
    # Add new
    for tag_id in tag_ids:
        session.add(MovementTag(movement_id=movement_id, tag_id=tag_id))


def create_movement(session: Session, data: MovementCreate) -> Movement:
    # Validate source exists if specified
    if data.source_id is not None:
        source = session.get(Source, data.source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

    movement = Movement(
        source_id=data.source_id,
        amount=data.amount,
        direction=data.direction,
        date=data.date,
        note=data.note,
    )
    session.add(movement)
    session.flush()
    if data.tag_ids:
        _set_tags(session, movement.id, data.tag_ids)
    session.commit()
    session.refresh(movement)
    return movement


def update_movement(session: Session, movement_id: int, data: MovementUpdate) -> Movement:
    movement = get_movement(session, movement_id)
    update_data = data.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)
    # Validate source exists if being changed
    if "source_id" in update_data and update_data["source_id"] is not None:
        source = session.get(Source, update_data["source_id"])
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
    for key, value in update_data.items():
        setattr(movement, key, value)
    movement.updated_at = datetime.utcnow()
    session.add(movement)
    session.flush()
    if tag_ids is not None:
        _set_tags(session, movement.id, tag_ids)
    session.commit()
    session.refresh(movement)
    return movement


def delete_movement(session: Session, movement_id: int) -> None:
    from models.goal import GoalAllocation
    from services import attachments as attachment_service

    movement = get_movement(session, movement_id)

    def _purge(mid: int) -> None:
        # Tag links
        for link in session.exec(
            select(MovementTag).where(MovementTag.movement_id == mid)
        ).all():
            session.delete(link)
        # Attachment files + rows
        attachment_service.delete_attachments_for_movement(session, mid)
        # Goal allocations linked to this movement. SQLite doesn't enforce the
        # FK CASCADE unless PRAGMA foreign_keys=ON, so we do it manually.
        for alloc in session.exec(
            select(GoalAllocation).where(GoalAllocation.movement_id == mid)
        ).all():
            session.delete(alloc)

    _purge(movement_id)

    if movement.transfer_pair_id:
        partner = session.get(Movement, movement.transfer_pair_id)
        if partner:
            _purge(partner.id)
            session.delete(partner)

    session.delete(movement)
    session.commit()


def enrich_movements_with_sources(session: Session, movements: list[Movement]) -> list[dict]:
    """Enrich a list of movements with source names and tags. Batch-fetches sources."""
    from i18n import _

    # Collect all source_ids and fetch them in one query
    source_ids = {m.source_id for m in movements if m.source_id}
    sources_by_id = {}
    if source_ids:
        source_objs = session.exec(select(Source).where(col(Source.id).in_(source_ids))).all()
        sources_by_id = {s.id: s.name for s in source_objs}

    result = []
    for m in movements:
        source_name = _("external")
        if m.source_id:
            source_name = sources_by_id.get(m.source_id, _("deleted"))
        result.append({
            "id": m.id,
            "date": m.date,
            "source_name": source_name,
            "amount": m.amount,
            "direction": m.direction,
            "note": m.note,
            "transfer_pair_id": m.transfer_pair_id,
        })
    return result


def group_movements_hierarchically(movements: list[dict]) -> list[dict]:
    """Group movements by year -> month -> day with in/out totals."""
    from itertools import groupby as itertools_groupby

    def _sum_in_out(mvs):
        total_in = sum(m['amount'] for m in mvs if m['direction'] == 'in' and not m.get('transfer_pair_id'))
        total_out = sum(m['amount'] for m in mvs if m['direction'] == 'out' and not m.get('transfer_pair_id'))
        return round(total_in, 2), round(total_out, 2)

    grouped = []
    for year_key, year_group in itertools_groupby(movements, key=lambda m: m['date'].year if hasattr(m['date'], 'year') else int(str(m['date'])[:4])):
        year_mvs = list(year_group)
        months = []
        for month_key, month_group in itertools_groupby(year_mvs, key=lambda m: m['date'].month if hasattr(m['date'], 'month') else int(str(m['date'])[5:7])):
            month_mvs = list(month_group)
            days = []
            for date_key, day_group in itertools_groupby(month_mvs, key=lambda m: m['date']):
                day_list = list(day_group)
                d_in, d_out = _sum_in_out(day_list)
                days.append({'date': date_key, 'movements': day_list, 'total_in': d_in, 'total_out': d_out})
            m_in, m_out = _sum_in_out(month_mvs)
            months.append({'month': month_key, 'year_month': f"{year_key}-{month_key:02d}", 'days': days, 'count': len(month_mvs), 'total_in': m_in, 'total_out': m_out})
        y_in, y_out = _sum_in_out(year_mvs)
        grouped.append({'year': year_key, 'months': months, 'count': len(year_mvs), 'total_in': y_in, 'total_out': y_out})
    return grouped


def toggle_exclude_from_stats(session: Session, movement_id: int) -> Movement:
    movement = get_movement(session, movement_id)
    movement.exclude_from_stats = not movement.exclude_from_stats
    movement.updated_at = datetime.utcnow()
    session.add(movement)
    session.commit()
    session.refresh(movement)
    return movement


def create_transfer(session: Session, data: TransferCreate) -> tuple[Movement, Movement]:
    # Validate both sources
    from_source = session.get(Source, data.from_source_id)
    if not from_source:
        raise HTTPException(status_code=404, detail="Source (from) not found")
    to_source = session.get(Source, data.to_source_id)
    if not to_source:
        raise HTTPException(status_code=404, detail="Source (to) not found")

    # in-leg amount differs from out-leg only for cross-currency transfers;
    # to_amount=None preserves the historical 1:1 behaviour.
    in_amount = data.to_amount if data.to_amount is not None else data.amount

    out_movement = Movement(
        source_id=data.from_source_id,
        amount=data.amount,
        direction="out",
        date=data.date,
        note=data.note,
    )
    in_movement = Movement(
        source_id=data.to_source_id,
        amount=in_amount,
        direction="in",
        date=data.date,
        note=data.note,
    )
    session.add(out_movement)
    session.add(in_movement)
    session.flush()

    out_movement.transfer_pair_id = in_movement.id
    in_movement.transfer_pair_id = out_movement.id
    session.add(out_movement)
    session.add(in_movement)

    if data.tag_ids:
        _set_tags(session, out_movement.id, data.tag_ids)
        _set_tags(session, in_movement.id, data.tag_ids)

    session.commit()
    session.refresh(out_movement)
    session.refresh(in_movement)
    return out_movement, in_movement


def update_transfer(session: Session, movement_id: int, data: TransferUpdate) -> tuple[Movement, Movement]:
    movement = get_movement(session, movement_id)
    if not movement.transfer_pair_id:
        raise HTTPException(status_code=400, detail="Not a transfer")
    partner = get_movement(session, movement.transfer_pair_id)

    if movement.direction == "out":
        out_movement, in_movement = movement, partner
    else:
        out_movement, in_movement = partner, movement

    if data.from_source_id is not None:
        source = session.get(Source, data.from_source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source (from) not found")
        out_movement.source_id = data.from_source_id
    if data.to_source_id is not None:
        source = session.get(Source, data.to_source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source (to) not found")
        in_movement.source_id = data.to_source_id
    # For same-currency transfers, editing the (out) amount keeps both legs in
    # sync (1:1). For cross-currency transfers we must NOT mirror the out amount
    # onto the converted in-leg — only an explicit to_amount changes it.
    out_src = session.get(Source, out_movement.source_id) if out_movement.source_id else None
    in_src = session.get(Source, in_movement.source_id) if in_movement.source_id else None
    same_ccy = bool(out_src and in_src and out_src.currency == in_src.currency)
    if data.amount is not None:
        out_movement.amount = data.amount
        if data.to_amount is None and same_ccy:
            in_movement.amount = data.amount
    if data.to_amount is not None:
        in_movement.amount = data.to_amount
    if data.date is not None:
        out_movement.date = data.date
        in_movement.date = data.date
    if data.note is not None:
        out_movement.note = data.note
        in_movement.note = data.note

    now = datetime.utcnow()
    out_movement.updated_at = now
    in_movement.updated_at = now
    session.add(out_movement)
    session.add(in_movement)

    if data.tag_ids is not None:
        _set_tags(session, out_movement.id, data.tag_ids)
        _set_tags(session, in_movement.id, data.tag_ids)

    session.commit()
    session.refresh(out_movement)
    session.refresh(in_movement)
    return out_movement, in_movement


# ── Bulk operations ──────────────────────────────────────────────

def _targets_for_bulk(session: Session, ids: list[int]) -> set[int]:
    """Expand a set of movement ids with their transfer partners, so a bulk
    tag/exclude change keeps both legs of a transfer in sync (the same invariant
    create_transfer/update_transfer maintain)."""
    targets: set[int] = set()
    for mid in ids:
        m = session.get(Movement, mid)
        if not m:
            continue
        targets.add(mid)
        if m.transfer_pair_id:
            targets.add(m.transfer_pair_id)
    return targets


def bulk_delete(session: Session, ids: list[int]) -> dict:
    """Delete many movements. delete_movement already cascades the transfer
    partner, so when both legs are selected the second id is skipped."""
    deleted: set[int] = set()
    skipped: list[int] = []
    affected = 0
    for mid in ids:
        if mid in deleted:
            continue
        m = session.get(Movement, mid)
        if not m:
            skipped.append(mid)
            continue
        partner_id = m.transfer_pair_id
        delete_movement(session, mid)
        deleted.add(mid)
        if partner_id:
            deleted.add(partner_id)
        affected += 1
    return {"affected": affected, "skipped": skipped}


def bulk_set_tags(session: Session, ids: list[int], tag_ids: list[int], mode: str) -> dict:
    if tag_ids:
        found = set(session.exec(select(Tag.id).where(col(Tag.id).in_(tag_ids))).all())
        if any(t not in found for t in tag_ids):
            raise HTTPException(status_code=422, detail="Unknown tag id(s)")
    skipped = [mid for mid in ids if session.get(Movement, mid) is None]
    valid = [mid for mid in ids if mid not in skipped]
    add_set = set(tag_ids)
    for mid in _targets_for_bulk(session, valid):
        existing = {
            link.tag_id
            for link in session.exec(select(MovementTag).where(MovementTag.movement_id == mid)).all()
        }
        if mode == "replace":
            new = list(dict.fromkeys(tag_ids))
        elif mode == "remove":
            new = [t for t in existing if t not in add_set]
        else:  # add
            new = list(existing | add_set)
        _set_tags(session, mid, new)
        m = session.get(Movement, mid)
        if m:
            m.updated_at = datetime.utcnow()
            session.add(m)
    session.commit()
    return {"affected": len(valid), "skipped": skipped}


def bulk_set_source(session: Session, ids: list[int], source_id: int | None) -> dict:
    if source_id is not None and not session.get(Source, source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    skipped: list[int] = []
    affected = 0
    for mid in ids:
        m = session.get(Movement, mid)
        if not m:
            skipped.append(mid)
            continue
        if m.transfer_pair_id:
            # Changing the "source" of a transfer leg is ambiguous — edit it in
            # the transfer form instead.
            skipped.append(mid)
            continue
        m.source_id = source_id
        m.updated_at = datetime.utcnow()
        session.add(m)
        affected += 1
    session.commit()
    return {"affected": affected, "skipped": skipped}


def bulk_set_exclude(session: Session, ids: list[int], value: bool) -> dict:
    skipped = [mid for mid in ids if session.get(Movement, mid) is None]
    valid = [mid for mid in ids if mid not in skipped]
    for mid in _targets_for_bulk(session, valid):
        m = session.get(Movement, mid)
        if m:
            m.exclude_from_stats = value
            m.updated_at = datetime.utcnow()
            session.add(m)
    session.commit()
    return {"affected": len(valid), "skipped": skipped}


def make_recurring_from_movement(
    session: Session, movement_id: int, frequency: str, apply_mode: str
):
    """Create a RecurringItem mirroring an existing movement."""
    from schemas.recurring import RecurringCreate
    from services import recurring as recurring_service
    from services.settings import get_settings

    m = get_movement(session, movement_id)
    if m.transfer_pair_id:
        raise HTTPException(status_code=400, detail="cannot_make_transfer_recurring")

    currency = None
    if m.source_id:
        src = session.get(Source, m.source_id)
        currency = src.currency if src else None
    if not currency:
        currency = get_settings(session).base_currency
    if not currency:
        raise HTTPException(status_code=422, detail="no_currency_for_external_movement")

    name = (m.note or "").strip() or f"{m.amount:.2f} {currency}"
    payload = RecurringCreate(
        name=name,
        amount=m.amount,
        direction=m.direction,
        currency=currency,
        frequency=frequency,
        start_date=m.date,
        source_id=m.source_id,
        apply_mode=apply_mode,
    )
    item = recurring_service.create_recurring(session, payload)
    # The source movement already covers its own date. Roll the first due date to
    # the next occurrence in the future so 'auto' mode doesn't back-fill the gap
    # between an old movement's date and today with a burst of duplicate
    # movements (and 'confirm' doesn't fire a stale prompt for a past date).
    today = date_type.today()
    if item.next_due_date <= today:
        nd = item.next_due_date
        while nd <= today:
            nd = recurring_service.compute_next_due_date(nd, item.frequency)
        item.next_due_date = nd
        item.updated_at = datetime.utcnow()
        session.add(item)
        session.commit()
        session.refresh(item)
    return item
