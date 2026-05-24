from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlmodel import Session, select, func, col  # noqa: F401

from models.budget import Budget
from models.movement import Movement, MovementTag
from models.notification import Notification
from models.source import Source
from models.tag import Tag
from schemas.budget import BudgetCreate, BudgetUpdate

# Defensive cap on the rollover walk so a corrupt start_date can never hang the
# request (≈50 years of monthly periods).
_MAX_ROLLOVER_PERIODS = 600


# ── Period math ──────────────────────────────────────────────────

def period_bounds(period: str, ref: date) -> tuple[date, date]:
    """Calendar-aligned [start, end] of the period containing ``ref``."""
    if period == "weekly":
        start = ref - timedelta(days=ref.weekday())  # Monday
        return start, start + timedelta(days=6)
    if period == "quarterly":
        q = (ref.month - 1) // 3  # 0..3
        start = date(ref.year, q * 3 + 1, 1)
        return start, start + relativedelta(months=3) - timedelta(days=1)
    if period == "yearly":
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    # monthly (default)
    start = date(ref.year, ref.month, 1)
    return start, start + relativedelta(months=1) - timedelta(days=1)


def period_key(period: str, start: date) -> str:
    """Stable label for a period, used for alert idempotency and the UI."""
    if period == "weekly":
        iso = start.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if period == "quarterly":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    if period == "yearly":
        return f"{start.year}"
    return f"{start.year}-{start.month:02d}"


def next_period_start(period: str, start: date) -> date:
    if period == "weekly":
        return start + timedelta(days=7)
    if period == "quarterly":
        return start + relativedelta(months=3)
    if period == "yearly":
        return start + relativedelta(years=1)
    return start + relativedelta(months=1)


def shift_period(period: str, ref: date, offset: int) -> date:
    """A date inside the period ``offset`` steps from the one containing ``ref``."""
    start, _ = period_bounds(period, ref)
    if offset >= 0:
        for _ in range(offset):
            start = next_period_start(period, start)
    else:
        for _ in range(-offset):
            start = period_bounds(period, start - timedelta(days=1))[0]
    return start


# ── Actuals & rollover ───────────────────────────────────────────

def _actual_for(session: Session, budget: Budget, start: date, end: date) -> float:
    """Spending counted against a budget in [start, end].

    Sums movements that carry the budget's tag, match its direction, sit in the
    date range and whose *source* is in the budget's currency. Transfers
    (``transfer_pair_id`` set), excluded-from-stats movements and external
    movements (no source → no currency) never count.
    """
    total = session.exec(
        select(func.coalesce(func.sum(Movement.amount), 0.0))
        .join(MovementTag, col(MovementTag.movement_id) == Movement.id)
        .join(Source, col(Source.id) == Movement.source_id)
        .where(
            MovementTag.tag_id == budget.tag_id,
            Movement.direction == budget.direction,
            Movement.date >= start,
            Movement.date <= end,
            Source.currency == budget.currency,
            Movement.exclude_from_stats == False,  # noqa: E712
            col(Movement.transfer_pair_id).is_(None),
        )
    ).one()
    return round(float(total), 2)


def _rollover_in(session: Session, budget: Budget, current_start: date) -> float:
    """Signed remainder carried into the period that starts on ``current_start``.

    Walks every period from the budget's start up to (but excluding) the current
    one, compounding ``available - actual`` so both surplus and overspend carry.
    Returns 0 when rollover is off.
    """
    if not budget.rollover:
        return 0.0
    ro = 0.0
    p_start, _ = period_bounds(budget.period, budget.start_date)
    iterations = 0
    while p_start < current_start and iterations < _MAX_ROLLOVER_PERIODS:
        _, p_end = period_bounds(budget.period, p_start)
        actual = _actual_for(session, budget, p_start, p_end)
        ro = round(budget.amount + ro - actual, 2)
        p_start = next_period_start(budget.period, p_start)
        iterations += 1
    return ro


def budget_status(session: Session, budget: Budget, ref: date | None = None,
                  tag: Tag | None = None) -> dict:
    """Full computed view of a budget for the period containing ``ref``."""
    ref = ref or date.today()
    today = date.today()
    start, end = period_bounds(budget.period, ref)

    actual = _actual_for(session, budget, start, end)
    rollover_in = _rollover_in(session, budget, start)
    available = round(budget.amount + rollover_in, 2)
    remaining = round(available - actual, 2)

    if available > 0:
        spent_pct = round(actual / available * 100, 1)
    else:
        spent_pct = 100.0 if actual > 0 else 0.0

    # Pace: how far through the period we are vs how much is spent.
    total_days = (end - start).days + 1
    if today < start:
        elapsed_days = 0
    elif today > end:
        elapsed_days = total_days
    else:
        elapsed_days = (today - start).days + 1
    elapsed_pct = round(elapsed_days / total_days * 100, 1) if total_days else 0.0
    days_remaining = max(0, total_days - elapsed_days)
    projected = round(actual / elapsed_days * total_days, 2) if elapsed_days > 0 else 0.0
    daily_remaining = round(remaining / days_remaining, 2) if days_remaining > 0 else 0.0

    threshold = budget.alert_threshold_pct or 0
    if available > 0 and actual > available:
        status = "over"
    elif threshold and spent_pct >= threshold:
        status = "warning"
    else:
        status = "ok"

    if tag is None:
        tag = session.get(Tag, budget.tag_id)

    return {
        "id": budget.id,
        "tag_id": budget.tag_id,
        "tag_name": tag.name if tag else "?",
        "tag_color": (tag.color if tag else None) or "#696cff",
        "currency": budget.currency,
        "period": budget.period,
        "direction": budget.direction,
        "rollover": budget.rollover,
        "amount": round(budget.amount, 2),
        "rollover_in": rollover_in,
        "available": available,
        "actual": actual,
        "remaining": remaining,
        "spent_pct": spent_pct,
        "elapsed_pct": elapsed_pct,
        "days_remaining": days_remaining,
        "projected": projected,
        "daily_remaining": daily_remaining,
        "status": status,
        "alert_threshold_pct": budget.alert_threshold_pct,
        "period_key": period_key(budget.period, start),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
    }


def list_budget_statuses(session: Session, offset: int = 0,
                         active_only: bool = True) -> list[dict]:
    """Computed status for every budget (batches tag lookups).

    ``offset`` navigates by whole periods *in each budget's own cadence*: at
    offset 0 every budget shows its current period; offset=±1 shows the
    next/previous one (weekly → a week, yearly → a year). This keeps a page that
    mixes periods correct, instead of always stepping by a calendar month.
    """
    today = date.today()
    q = select(Budget)
    if active_only:
        q = q.where(Budget.active == True)  # noqa: E712
    budgets = list(session.exec(q).all())
    if not budgets:
        return []
    tag_ids = {b.tag_id for b in budgets}
    tags = {t.id: t for t in session.exec(select(Tag).where(col(Tag.id).in_(tag_ids))).all()}
    statuses = [
        budget_status(session, b, shift_period(b.period, today, offset), tag=tags.get(b.tag_id))
        for b in budgets
    ]
    # Most-at-risk first so the page leads with what needs attention.
    order = {"over": 0, "warning": 1, "ok": 2}
    statuses.sort(key=lambda s: (order.get(s["status"], 3), -s["spent_pct"]))
    return statuses


# ── CRUD ─────────────────────────────────────────────────────────

def list_budgets(session: Session) -> list[Budget]:
    return list(session.exec(select(Budget)).all())


def get_budget(session: Session, budget_id: int) -> Budget:
    budget = session.get(Budget, budget_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    return budget


def _ensure_tag(session: Session, tag_id: int) -> Tag:
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=400, detail="Unknown tag")
    return tag


def _reject_duplicate(session: Session, tag_id: int, currency: str,
                      exclude_id: int | None = None) -> None:
    """One active budget per (tag, currency) — keeps the mental model simple."""
    q = select(Budget).where(
        Budget.tag_id == tag_id,
        Budget.currency == currency,
        Budget.active == True,  # noqa: E712
    )
    existing = session.exec(q).first()
    if existing and existing.id != exclude_id:
        raise HTTPException(
            status_code=409,
            detail="A budget for this tag and currency already exists.",
        )


def create_budget(session: Session, data: BudgetCreate) -> Budget:
    _ensure_tag(session, data.tag_id)
    if data.active:
        _reject_duplicate(session, data.tag_id, data.currency)
    payload = data.model_dump()
    if payload.get("start_date") is None:
        payload["start_date"] = period_bounds(payload["period"], date.today())[0]
    budget = Budget(**payload)
    session.add(budget)
    session.commit()
    session.refresh(budget)
    return budget


def update_budget(session: Session, budget_id: int, data: BudgetUpdate) -> Budget:
    budget = get_budget(session, budget_id)
    update_data = data.model_dump(exclude_unset=True)
    if "tag_id" in update_data:
        _ensure_tag(session, update_data["tag_id"])
    target_tag = update_data.get("tag_id", budget.tag_id)
    target_ccy = update_data.get("currency", budget.currency)
    target_active = update_data.get("active", budget.active)
    if target_active:
        _reject_duplicate(session, target_tag, target_ccy, exclude_id=budget.id)
    # Changing the rule's shape invalidates the alert band we last fired on.
    if any(k in update_data for k in ("amount", "period", "tag_id", "currency", "rollover", "active")):
        budget.last_alert_period = None
        budget.last_alert_level = 0
    for key, value in update_data.items():
        setattr(budget, key, value)
    budget.updated_at = datetime.utcnow()
    session.add(budget)
    session.commit()
    session.refresh(budget)
    return budget


def delete_budget(session: Session, budget_id: int) -> None:
    budget = get_budget(session, budget_id)
    session.delete(budget)
    session.commit()


def delete_budgets_for_tag(session: Session, tag_id: int) -> int:
    """Remove budgets pointing at a tag that's being deleted. Returns the count."""
    budgets = session.exec(select(Budget).where(Budget.tag_id == tag_id)).all()
    for b in budgets:
        session.delete(b)
    return len(budgets)


# ── Alerts (scheduler) ───────────────────────────────────────────

def check_budget_alerts(session: Session, today: date | None = None) -> int:
    """Fire a notification when a budget first crosses its threshold or 100% in
    the current period. Idempotent per band via last_alert_period/level."""
    from i18n import _

    today = today or date.today()
    fired = 0
    budgets = session.exec(select(Budget).where(Budget.active == True)).all()  # noqa: E712
    for b in budgets:
        threshold = b.alert_threshold_pct or 0
        if not threshold:  # 0 disables alerts entirely
            continue
        start, end = period_bounds(b.period, today)
        if not (start <= today <= end):
            continue

        st = budget_status(session, b, today)
        pkey = st["period_key"]

        level = 0
        if st["available"] > 0:
            if st["actual"] > st["available"]:
                level = 100
            elif st["spent_pct"] >= threshold:
                level = threshold

        last_level = b.last_alert_level if b.last_alert_period == pkey else 0
        if level <= last_level:
            continue

        tag = session.get(Tag, b.tag_id)
        name = tag.name if tag else "?"
        if level >= 100:
            session.add(Notification(
                type="warning",
                title=f"🚨 {name}",
                body=f"{_('budget_exceeded')}: {st['actual']:.2f} / {st['available']:.2f} {b.currency}",
                related_entity=f"budget:{b.id}",
            ))
        else:
            session.add(Notification(
                type="alert",
                title=f"⚠️ {name}",
                body=f"{_('budget_threshold_reached')} {threshold}% — {st['actual']:.2f} / {st['available']:.2f} {b.currency}",
                related_entity=f"budget:{b.id}",
            ))
        b.last_alert_period = pkey
        b.last_alert_level = level
        b.updated_at = datetime.utcnow()
        session.add(b)
        fired += 1

    session.commit()
    return fired
