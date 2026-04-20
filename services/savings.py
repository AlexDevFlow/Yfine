"""Savings service — now transfer-backed.

A "saving" is the `in`-leg of a transfer that lands in a savings fund. The old
`savings` table is kept around only for the migration wizard (see
services/savings_migration.py); this service only reads from movements.
"""
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from fastapi import HTTPException
from sqlmodel import Session, select, col, func

from models.movement import Movement, MovementTag
from models.source import Source
from models.tag import Tag
from schemas.saving import SavingCreate, SavingUpdate
from services import movements as movement_service
from services import savings_fund as fund_service


# --- Tag helpers (operate on the in-leg movement's tag links) ---

def get_saving_tags(session: Session, saving_id: int) -> list[Tag]:
    return movement_service.get_movement_tags(session, saving_id)


# --- Internal helpers ---

def _get_contribution_movement(session: Session, saving_id: int) -> Movement:
    m = session.get(Movement, saving_id)
    if not m or not m.is_savings_contribution:
        raise HTTPException(status_code=404, detail="Saving not found")
    return m


def _build_list_query(
    currency: str | None = None,
    tag_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    q = select(Movement).where(
        Movement.is_savings_contribution == True  # noqa: E712
    )
    if tag_id:
        q = q.join(MovementTag, Movement.id == MovementTag.movement_id).where(
            MovementTag.tag_id == tag_id
        )
    if currency:
        # Currency lives on the fund source; join to filter.
        q = q.join(Source, Movement.source_id == Source.id).where(
            Source.currency == currency
        )
    if date_from:
        q = q.where(Movement.date >= date_from)
    if date_to:
        q = q.where(Movement.date <= date_to)
    return q


def _to_saving_view(session: Session, m: Movement) -> dict:
    """Reshape a contribution movement into the old Saving-read contract so
    existing templates and API consumers don't have to change."""
    fund = session.get(Source, m.source_id) if m.source_id else None
    # The partner's source_id tells us "where the money came from".
    partner = None
    if m.transfer_pair_id:
        partner = session.get(Movement, m.transfer_pair_id)
    from_source_id = partner.source_id if partner else None
    tags = movement_service.get_movement_tags(session, m.id)
    return {
        "id": m.id,
        "amount": m.amount,
        "currency": fund.currency if fund else "",
        "date": m.date,
        "description": m.note,  # unified field since the refactor
        "note": None,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in tags],
        "from_source_id": from_source_id,
        "fund_source_id": m.source_id,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


# --- CRUD ---

def list_savings(
    session: Session,
    skip: int = 0,
    limit: int = 50,
    currency: str | None = None,
    tag_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[dict]:
    q = _build_list_query(currency, tag_id, date_from, date_to)
    q = q.order_by(col(Movement.date).desc(), col(Movement.id).desc()).offset(skip).limit(limit)
    rows = list(session.exec(q).all())
    return [_to_saving_view(session, m) for m in rows]


def count_savings(
    session: Session,
    currency: str | None = None,
    tag_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> int:
    base = _build_list_query(currency, tag_id, date_from, date_to)
    return int(session.exec(select(func.count()).select_from(base.subquery())).one())


def get_saving(session: Session, saving_id: int) -> dict:
    m = _get_contribution_movement(session, saving_id)
    return _to_saving_view(session, m)


def create_saving(session: Session, data: SavingCreate) -> dict:
    from_source_id = getattr(data, "from_source_id", None)
    if from_source_id is None:
        raise HTTPException(
            status_code=422,
            detail="from_source_id is required: pick which account the money comes from.",
        )
    from_source = session.get(Source, from_source_id)
    if not from_source:
        raise HTTPException(status_code=404, detail="Source not found")
    if from_source.is_savings_fund:
        raise HTTPException(
            status_code=422,
            detail="Cannot save from the savings fund itself — pick a regular source.",
        )
    # Currency: either provided (for explicit UX) or derived from the source.
    currency = (data.currency or from_source.currency).upper()
    if currency != from_source.currency:
        raise HTTPException(
            status_code=422,
            detail=f"Currency mismatch: source is {from_source.currency}, got {currency}",
        )

    fund = fund_service.ensure_fund_for_currency(session, currency)

    # Build the transfer pair directly so we can flag the in-leg as a
    # savings contribution atomically.
    note = data.description or data.note or None
    out_movement = Movement(
        source_id=from_source.id,
        amount=data.amount,
        direction="out",
        date=data.date,
        note=note,
    )
    in_movement = Movement(
        source_id=fund.id,
        amount=data.amount,
        direction="in",
        date=data.date,
        note=note,
        is_savings_contribution=True,
    )
    session.add(out_movement)
    session.add(in_movement)
    session.flush()
    out_movement.transfer_pair_id = in_movement.id
    in_movement.transfer_pair_id = out_movement.id
    session.add(out_movement)
    session.add(in_movement)

    if data.tag_ids:
        # Tags go on the in-leg (the "saving" itself). Copy onto the out-leg
        # too so tag filters on /movements still catch both sides.
        for tid in data.tag_ids:
            session.add(MovementTag(movement_id=in_movement.id, tag_id=tid))
            session.add(MovementTag(movement_id=out_movement.id, tag_id=tid))

    session.commit()
    session.refresh(in_movement)
    return _to_saving_view(session, in_movement)


def update_saving(session: Session, saving_id: int, data: SavingUpdate) -> dict:
    in_movement = _get_contribution_movement(session, saving_id)
    partner = (
        session.get(Movement, in_movement.transfer_pair_id)
        if in_movement.transfer_pair_id
        else None
    )

    payload = data.model_dump(exclude_unset=True)
    tag_ids = payload.pop("tag_ids", None)
    new_from_source_id = payload.pop("from_source_id", None)
    new_currency = (payload.pop("currency", None) or "").upper() or None
    description = payload.pop("description", None)
    note = payload.pop("note", None)

    if description is not None or note is not None:
        in_movement.note = description if description is not None else note
        if partner:
            partner.note = in_movement.note

    if "amount" in payload:
        in_movement.amount = payload["amount"]
        if partner:
            partner.amount = payload["amount"]
    if "date" in payload:
        in_movement.date = payload["date"]
        if partner:
            partner.date = payload["date"]

    # Changing currency means moving to a different fund — rebuild the
    # transfer cleanly.
    if new_currency and new_currency:
        fund_now = session.get(Source, in_movement.source_id)
        if fund_now and fund_now.currency != new_currency:
            new_fund = fund_service.ensure_fund_for_currency(session, new_currency)
            in_movement.source_id = new_fund.id
            # A partner with a different-currency source doesn't make sense;
            # if the user also supplied a compatible from_source_id, use it,
            # otherwise surface the conflict.
            if partner and new_from_source_id is None:
                partner_src = session.get(Source, partner.source_id)
                if partner_src and partner_src.currency != new_currency:
                    raise HTTPException(
                        status_code=422,
                        detail="Changing currency requires a matching from_source_id.",
                    )

    if new_from_source_id is not None and partner:
        new_src = session.get(Source, new_from_source_id)
        if not new_src:
            raise HTTPException(status_code=404, detail="Source not found")
        fund_now = session.get(Source, in_movement.source_id)
        if fund_now and new_src.currency != fund_now.currency:
            raise HTTPException(status_code=422, detail="Currency mismatch")
        if new_src.is_savings_fund:
            raise HTTPException(status_code=422, detail="Pick a regular source")
        partner.source_id = new_src.id

    in_movement.updated_at = datetime.utcnow()
    if partner:
        partner.updated_at = datetime.utcnow()
    session.add(in_movement)
    if partner:
        session.add(partner)
    session.flush()

    if tag_ids is not None:
        # Reset tags on both legs symmetrically.
        for link in session.exec(
            select(MovementTag).where(MovementTag.movement_id == in_movement.id)
        ).all():
            session.delete(link)
        if partner:
            for link in session.exec(
                select(MovementTag).where(MovementTag.movement_id == partner.id)
            ).all():
                session.delete(link)
        for tid in tag_ids:
            session.add(MovementTag(movement_id=in_movement.id, tag_id=tid))
            if partner:
                session.add(MovementTag(movement_id=partner.id, tag_id=tid))

    session.commit()
    session.refresh(in_movement)
    return _to_saving_view(session, in_movement)


def delete_saving(session: Session, saving_id: int) -> None:
    m = _get_contribution_movement(session, saving_id)
    # Defer to the movement service so its cascade rules (tags, partner,
    # attachments) all run.
    movement_service.delete_movement(session, m.id)


# --- Aggregates ---

def total_saved(session: Session, currency: str | None = None) -> dict[str, float]:
    q = (
        select(Source.currency, func.sum(Movement.amount))
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.is_savings_contribution == True)  # noqa: E712
    )
    if currency:
        q = q.where(Source.currency == currency)
    q = q.group_by(Source.currency)
    return {row[0]: round(float(row[1]), 2) for row in session.exec(q).all()}


def total_saved_period(
    session: Session,
    date_from: date,
    date_to: date,
) -> dict[str, float]:
    q = (
        select(Source.currency, func.sum(Movement.amount))
        .join(Source, Movement.source_id == Source.id)
        .where(
            Movement.is_savings_contribution == True,  # noqa: E712
            Movement.date >= date_from,
            Movement.date <= date_to,
        )
        .group_by(Source.currency)
    )
    return {row[0]: round(float(row[1]), 2) for row in session.exec(q).all()}


def monthly_trend(session: Session, months: int = 12) -> list[dict]:
    """Monthly contributions (deposits only) per currency — tab 1 on the chart."""
    cutoff = date.today().replace(day=1) - relativedelta(months=months - 1)
    q = (
        select(
            func.strftime("%Y-%m", Movement.date).label("month"),
            Source.currency,
            func.sum(Movement.amount),
        )
        .join(Source, Movement.source_id == Source.id)
        .where(
            Movement.is_savings_contribution == True,  # noqa: E712
            Movement.date >= cutoff,
        )
        .group_by("month", Source.currency)
        .order_by("month")
    )
    return [
        {"month": r[0], "currency": r[1], "total": round(float(r[2]), 2)}
        for r in session.exec(q).all()
    ]


def fund_balance_trend(session: Session, months: int = 12) -> list[dict]:
    """Running balance of each savings fund at the end of each month — tab 2.

    Computes the cumulative net flow per fund per month.
    """
    cutoff = date.today().replace(day=1) - relativedelta(months=months - 1)
    # In/out per fund per month
    q = (
        select(
            func.strftime("%Y-%m", Movement.date).label("month"),
            Source.currency,
            Movement.direction,
            func.sum(Movement.amount),
        )
        .join(Source, Movement.source_id == Source.id)
        .where(Source.is_savings_fund == True)  # noqa: E712
        .group_by("month", Source.currency, Movement.direction)
        .order_by("month")
    )
    net_by_month_cur: dict[tuple[str, str], float] = {}
    for month, currency, direction, total in session.exec(q).all():
        key = (month, currency)
        signed = float(total) if direction == "in" else -float(total)
        net_by_month_cur[key] = net_by_month_cur.get(key, 0.0) + signed

    # Build per-currency running totals
    currencies = sorted({k[1] for k in net_by_month_cur})
    all_months = sorted({k[0] for k in net_by_month_cur})
    out: list[dict] = []
    for cur in currencies:
        running = 0.0
        for month in all_months:
            if month < cutoff.strftime("%Y-%m"):
                running += net_by_month_cur.get((month, cur), 0.0)
                continue
            running += net_by_month_cur.get((month, cur), 0.0)
            out.append({"month": month, "currency": cur, "balance": round(running, 2)})
    return out


def most_used_currency(session: Session) -> str | None:
    """Most-used currency across savings funds (for UI defaults)."""
    cnt = func.count(Movement.id)
    q = (
        select(Source.currency, cnt)
        .join(Source, Movement.source_id == Source.id)
        .where(Movement.is_savings_contribution == True)  # noqa: E712
        .group_by(Source.currency)
        .order_by(cnt.desc())
        .limit(1)
    )
    row = session.exec(q).first()
    return row[0] if row else None
