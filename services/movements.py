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
            .distinct()
        )
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
) -> list[Movement]:
    query = _build_filter_query(source_id, tag_ids, direction, date_from, date_to, amount_min, amount_max, exclude_transfer_in)
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
) -> int:
    base = _build_filter_query(source_id, tag_ids, direction, date_from, date_to, amount_min, amount_max, exclude_transfer_in)
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

    out_movement = Movement(
        source_id=data.from_source_id,
        amount=data.amount,
        direction="out",
        date=data.date,
        note=data.note,
    )
    in_movement = Movement(
        source_id=data.to_source_id,
        amount=data.amount,
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
    if data.amount is not None:
        out_movement.amount = data.amount
        in_movement.amount = data.amount
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
