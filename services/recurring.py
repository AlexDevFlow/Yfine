from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from fastapi import HTTPException
from sqlmodel import Session, select, col, func  # noqa: F401

from models.movement import Movement
from models.notification import Notification
from models.recurring import RecurringItem
from models.source import Source
from schemas.recurring import RecurringCreate, RecurringUpdate


def compute_next_due_date(current: date, frequency: str) -> date:
    if frequency == "daily":
        return current + relativedelta(days=1)
    elif frequency == "weekly":
        return current + relativedelta(weeks=1)
    elif frequency == "monthly":
        return current + relativedelta(months=1)
    elif frequency == "yearly":
        return current + relativedelta(years=1)
    return current + relativedelta(months=1)


def _apply_recurring_filters(query, frequency: str | None = None, direction: str | None = None):
    if frequency:
        query = query.where(RecurringItem.frequency == frequency)
    if direction:
        query = query.where(RecurringItem.direction == direction)
    return query


def list_recurring(
    session: Session, skip: int = 0, limit: int = 50,
    frequency: str | None = None, direction: str | None = None,
) -> list[RecurringItem]:
    query = select(RecurringItem).order_by(col(RecurringItem.next_due_date)).offset(skip).limit(limit)
    query = _apply_recurring_filters(query, frequency, direction)
    return list(session.exec(query).all())


def count_recurring(
    session: Session, frequency: str | None = None, direction: str | None = None,
) -> int:
    query = select(func.count(RecurringItem.id))
    query = _apply_recurring_filters(query, frequency, direction)
    return int(session.exec(query).one())


# Frequency → monthly multiplier (365.25/12 for daily, 52.1786/12 for weekly).
_FREQ_TO_MONTHLY = {
    "daily": 365.25 / 12,
    "weekly": 52.1785714 / 12,
    "monthly": 1.0,
    "yearly": 1.0 / 12,
}


def monthly_summary(session: Session) -> dict:
    """Aggregate all recurring items into projected monthly totals per currency.

    Returns a dict with:
      - by_currency: list of {currency, outflow, inflow, net, count_out, count_in}
      - total_count: total recurring items
      - currencies: list of currencies present
    """
    items = list(session.exec(select(RecurringItem)).all())
    buckets: dict[str, dict] = {}
    for it in items:
        cur = (it.currency or "").upper()
        mult = _FREQ_TO_MONTHLY.get(it.frequency, 1.0)
        monthly = float(it.amount or 0) * mult
        b = buckets.setdefault(cur, {
            "currency": cur, "outflow": 0.0, "inflow": 0.0,
            "count_out": 0, "count_in": 0,
        })
        if it.direction == "out":
            b["outflow"] += monthly
            b["count_out"] += 1
        else:
            b["inflow"] += monthly
            b["count_in"] += 1

    by_currency = []
    for cur, b in sorted(buckets.items()):
        by_currency.append({
            "currency": cur,
            "outflow": round(b["outflow"], 2),
            "inflow": round(b["inflow"], 2),
            "net": round(b["inflow"] - b["outflow"], 2),
            "count_out": b["count_out"],
            "count_in": b["count_in"],
        })

    return {
        "by_currency": by_currency,
        "total_count": len(items),
        "currencies": [b["currency"] for b in by_currency],
    }


def get_recurring(session: Session, recurring_id: int) -> RecurringItem:
    item = session.get(RecurringItem, recurring_id)
    if not item:
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return item


def create_recurring(session: Session, data: RecurringCreate) -> RecurringItem:
    item = RecurringItem(
        **data.model_dump(),
        next_due_date=data.start_date,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def update_recurring(session: Session, recurring_id: int, data: RecurringUpdate) -> RecurringItem:
    item = get_recurring(session, recurring_id)
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    # Keep next_due_date in sync with start_date so the schedule reflects edits
    if "start_date" in update_data and update_data["start_date"] is not None:
        item.next_due_date = update_data["start_date"]
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def delete_recurring(session: Session, recurring_id: int) -> None:
    item = get_recurring(session, recurring_id)
    session.delete(item)
    session.commit()


def enrich_recurring_items(session: Session, items: list[RecurringItem]) -> list[dict]:
    """Enrich recurring items with source_name and days_until for display."""
    today = date.today()
    # Batch-fetch sources
    source_ids = {r.source_id for r in items if r.source_id}
    sources_by_id = {}
    if source_ids:
        source_objs = session.exec(select(Source).where(col(Source.id).in_(source_ids))).all()
        sources_by_id = {s.id: s.name for s in source_objs}

    enriched = []
    for r in items:
        source_name = sources_by_id.get(r.source_id) if r.source_id else None
        days_until = (r.next_due_date - today).days if r.next_due_date else None
        enriched.append({
            "id": r.id,
            "name": r.name,
            "amount": r.amount,
            "direction": r.direction,
            "currency": r.currency,
            "frequency": r.frequency,
            "next_due_date": r.next_due_date,
            "apply_mode": r.apply_mode,
            "source_name": source_name,
            "days_until": days_until,
        })
    return enriched


def apply_recurring_item(
    session: Session, item: RecurringItem, override_amount: float | None = None, note: str | None = None
) -> None:
    """Apply a recurring item: create the movement and advance the due date.

    Args:
        override_amount: If provided, use this amount instead of the item's default.
                         Useful for manual confirmation with bonuses or adjustments.
        note: Optional note to append to the movement (e.g. reason for amount change).
    """
    # Enforce end_date
    if item.end_date and item.next_due_date > item.end_date:
        raise HTTPException(status_code=400, detail="Recurring item has ended")

    actual_amount = override_amount if override_amount is not None else item.amount
    movement_note = f"Recurring: {item.name}"
    if note:
        movement_note += f" — {note}"
    if override_amount is not None and override_amount != item.amount:
        movement_note += f" (base: {item.amount:.2f}, adjusted: {actual_amount:.2f})"

    if item.source_id:
        movement = Movement(
            source_id=item.source_id,
            amount=actual_amount,
            direction=item.direction,
            date=item.next_due_date,
            note=movement_note,
        )
        session.add(movement)

    notification = Notification(
        type="info",
        title=f"Applied: {item.name}",
        body=f"{item.direction.capitalize()} of {actual_amount:.2f} {item.currency} applied.",
        related_entity=f"recurring:{item.id}",
    )
    session.add(notification)

    item.next_due_date = compute_next_due_date(item.next_due_date, item.frequency)
    item.updated_at = datetime.utcnow()
    session.add(item)


def apply_recurring_by_id(
    session: Session, recurring_id: int, override_amount: float | None = None, note: str | None = None
) -> RecurringItem:
    """Manually apply a recurring item by its ID, optionally overriding the amount."""
    from datetime import date as date_type
    item = get_recurring(session, recurring_id)

    # Prevent double-apply: don't apply if next_due_date is in the future
    if item.next_due_date > date_type.today():
        raise HTTPException(status_code=400, detail="Recurring item is not yet due")

    apply_recurring_item(session, item, override_amount=override_amount, note=note)
    session.commit()
    session.refresh(item)
    return item
