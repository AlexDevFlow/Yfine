import logging
import math
from datetime import date
from itertools import groupby as itertools_groupby

_logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, Request, Query
from sqlmodel import Session, col, select, func

from database import get_session
from i18n import _
from models.movement import Movement, MovementTag
from models.saving import SavingTag
from services import dashboard as dashboard_service
from services import movements as movement_service
from services import notifications as notif_service
from services import recurring as recurring_service
from services import settings as settings_service
from services import sources as source_service
from services import tags as tag_service
from services import whims as whim_service
from services import savings as saving_service
from services import portfolios as portfolio_service

router = APIRouter(tags=["pages"])


def _templates():
    from main import templates
    return templates


# --- Dashboard ---
@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    stats = dashboard_service.get_dashboard_stats(session)
    # Enrich recent movements with source names (batch)
    recent = movement_service.enrich_movements_with_sources(session, stats["recent_movements"])

    # Enrich sources with current balance (batch query)
    balances = source_service.get_balances_batch(session, list(stats["sources"]))
    sources = []
    for s in stats["sources"]:
        sources.append({
            "id": s.id,
            "name": s.name,
            "currency": s.currency,
            "current_balance": balances.get(s.id, s.starting_balance),
        })

    month_start = date.today().replace(day=1).isoformat()

    # Enrich upcoming recurring with days_left (batch)
    upcoming_enriched = recurring_service.enrich_recurring_items(session, list(stats["upcoming_recurring"]))
    # Map days_until -> days_left for template compatibility
    upcoming = [{**r, "days_left": r.pop("days_until")} for r in upcoming_enriched]

    current_settings = settings_service.get_settings(session)
    portfolio_counts = portfolio_service.get_counts(session)
    return _templates().TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "recent_movements": recent,
        "upcoming_recurring": upcoming,
        "sources": sources,
        "month_start": month_start,
        "portfolio_prices_enabled": current_settings.portfolio_prices_enabled,
        "portfolio_prices_prompted": current_settings.portfolio_prices_prompted,
        "portfolio_count": portfolio_counts["portfolios"],
    })


# --- Sources ---
@router.get("/sources")
def sources_index(request: Request, session: Session = Depends(get_session)):
    # Savings funds with `hidden_from_sources=True` are intentionally kept out
    # of the main listing; they're still usable everywhere via pickers.
    items = source_service.list_sources(session, include_hidden=False)
    # Batch balance calculation (2 queries instead of 2*N)
    balances = source_service.get_balances_batch(session, items)
    # Batch movement counts (1 query instead of N)
    source_ids = [s.id for s in items]
    mov_count_rows = session.exec(
        select(Movement.source_id, func.count(Movement.id))
        .where(Movement.source_id.in_(source_ids))  # type: ignore
        .group_by(Movement.source_id)
    ).all() if source_ids else []
    mov_counts = {sid: int(cnt) for sid, cnt in mov_count_rows}
    # Portfolio market value per source, grouped by base_currency
    portfolio_values = portfolio_service.portfolio_value_by_source(session)
    sources = []
    for s in items:
        cash = balances.get(s.id, s.starting_balance)
        pf_same = portfolio_values.get(s.id, {}).get(s.currency, 0.0)
        pf_other = {
            cur: val for cur, val in portfolio_values.get(s.id, {}).items()
            if cur != s.currency
        }
        sources.append({
            "id": s.id,
            "name": s.name,
            "currency": s.currency,
            "starting_balance": s.starting_balance,
            "current_balance": cash,
            "portfolio_value_same_ccy": round(pf_same, 2),
            "portfolio_value_other_ccy": pf_other,
            "total_with_portfolios": round(cash + pf_same, 2),
            "movement_count": mov_counts.get(s.id, 0),
        })
    return _templates().TemplateResponse("sources/index.html", {
        "request": request,
        "sources": sources,
    })


@router.get("/sources/new")
def sources_new(request: Request, session: Session = Depends(get_session)):
    return _templates().TemplateResponse("sources/form.html", {
        "request": request,
        "source": None,
    })


@router.get("/sources/{source_id}")
def sources_detail(source_id: int, request: Request, session: Session = Depends(get_session)):
    source = source_service.get_source(session, source_id)
    balance = source_service.get_balance(session, source_id)
    movements_raw = movement_service.list_movements(session, source_id=source_id, limit=200)

    # Enrich and group via service
    movements = movement_service.enrich_movements_with_sources(session, movements_raw)
    grouped = movement_service.group_movements_hierarchically(movements)

    portfolios = portfolio_service.list_portfolios_by_source(session, source_id)
    # Sum portfolio market value that matches the source currency so we can
    # show a "cash + investments" total; other-currency portfolios are shown
    # only in their own card.
    portfolios_value_same_ccy = round(
        sum((p.get("total_value") or 0.0) for p in portfolios if p.get("base_currency") == source.currency),
        2,
    )
    portfolios_value_other_ccy = [
        {"currency": p.get("base_currency"), "total_value": p.get("total_value") or 0.0}
        for p in portfolios if p.get("base_currency") != source.currency
    ]

    return _templates().TemplateResponse("sources/detail.html", {
        "request": request,
        "source": source,
        "balance": balance,
        "grouped_movements": grouped,
        "portfolios": portfolios,
        "portfolios_value_same_ccy": portfolios_value_same_ccy,
        "portfolios_value_other_ccy": portfolios_value_other_ccy,
        "total_with_portfolios": round(balance + portfolios_value_same_ccy, 2),
    })


@router.get("/sources/{source_id}/edit")
def sources_edit(source_id: int, request: Request, session: Session = Depends(get_session)):
    source = source_service.get_source(session, source_id)
    return _templates().TemplateResponse("sources/form.html", {
        "request": request,
        "source": source,
    })


# --- Movements ---
@router.get("/movements")
def movements_index(
    request: Request,
    source_id: int | None = Query(default=None),
    tag_ids: list[int] = Query(default_factory=list),
    direction: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    amount_min: float | None = Query(default=None),
    amount_max: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
):
    per_page = 50
    skip = (page - 1) * per_page
    filter_kwargs = dict(
        source_id=source_id, tag_ids=tag_ids or None, direction=direction,
        date_from=date_from, date_to=date_to,
        amount_min=amount_min, amount_max=amount_max,
        exclude_transfer_in=True,
    )
    total_count = movement_service.count_movements(session, **filter_kwargs)
    total_pages = max(1, math.ceil(total_count / per_page))
    movements_raw = movement_service.list_movements(session, skip=skip, limit=per_page, **filter_kwargs)

    # Batch-fetch sources for name lookup
    all_source_ids = set()
    transfer_pair_ids = set()
    for m in movements_raw:
        if m.source_id:
            all_source_ids.add(m.source_id)
        if m.transfer_pair_id:
            transfer_pair_ids.add(m.transfer_pair_id)

    # Batch-fetch transfer partners
    from models.movement import Movement as MovementModel
    from sqlmodel import col as _col
    partners_by_id = {}
    if transfer_pair_ids:
        partners = session.exec(select(MovementModel).where(_col(MovementModel.id).in_(transfer_pair_ids))).all()
        for p in partners:
            partners_by_id[p.id] = p
            if p.source_id:
                all_source_ids.add(p.source_id)

    from models.source import Source as SourceModel
    sources_by_id = {}
    if all_source_ids:
        source_objs = session.exec(select(SourceModel).where(_col(SourceModel.id).in_(all_source_ids))).all()
        sources_by_id = {s.id: s.name for s in source_objs}

    # Batch-fetch attachment counts per movement in this page
    from models.movement import MovementAttachment as _Attachment
    from sqlalchemy import func as _func
    movement_ids = [m.id for m in movements_raw]
    attach_counts: dict[int, int] = {}
    if movement_ids:
        rows = session.exec(
            select(_Attachment.movement_id, _func.count(_Attachment.id))
            .where(_col(_Attachment.movement_id).in_(movement_ids))
            .group_by(_Attachment.movement_id)
        ).all()
        attach_counts = {mid: cnt for mid, cnt in rows}

    movements = []
    for m in movements_raw:
        tags = movement_service.get_movement_tags(session, m.id)
        source_name = _("external")
        if m.source_id:
            source_name = sources_by_id.get(m.source_id, _("deleted"))
        transfer_source_name = None
        if m.transfer_pair_id:
            partner = partners_by_id.get(m.transfer_pair_id)
            if partner and partner.source_id:
                transfer_source_name = sources_by_id.get(partner.source_id, _("deleted"))
            elif partner:
                transfer_source_name = _("external")
        movements.append({
            "id": m.id,
            "date": m.date,
            "source_name": source_name,
            "amount": m.amount,
            "direction": m.direction,
            "note": m.note,
            "transfer_pair_id": m.transfer_pair_id,
            "transfer_source_name": transfer_source_name,
            "tags": tags,
            "attachment_count": attach_counts.get(m.id, 0),
        })
    grouped_movements = movement_service.group_movements_hierarchically(movements)

    sources = source_service.list_sources(session)
    all_tags = tag_service.list_tags(session)
    return _templates().TemplateResponse("movements/index.html", {
        "request": request,
        "grouped_movements": grouped_movements,
        "sources": sources,
        "tags": all_tags,
        "filter_source_id": source_id,
        "filter_tag_ids": tag_ids,
        "filter_direction": direction,
        "filter_date_from": date_from,
        "filter_date_to": date_to,
        "filter_amount_min": amount_min,
        "filter_amount_max": amount_max,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "per_page": per_page,
    })


@router.get("/movements/new")
def movements_new(
    request: Request,
    transfer: int = Query(default=0),
    source_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
):
    sources = source_service.list_sources(session)
    tags = tag_service.list_tags(session)
    return _templates().TemplateResponse("movements/form.html", {
        "request": request,
        "movement": None,
        "movement_tag_ids": [],
        "sources": sources,
        "tags": tags,
        "is_transfer": bool(transfer),
        "preselect_source_id": source_id,
        "transfer_from_source_id": None,
        "transfer_to_source_id": None,
        "transfer_out_id": None,
    })


@router.get("/movements/{movement_id}/edit")
def movements_edit(movement_id: int, request: Request, session: Session = Depends(get_session)):
    movement = movement_service.get_movement(session, movement_id)
    tags_list = movement_service.get_movement_tags(session, movement_id)
    tag_ids = [t.id for t in tags_list]
    sources = source_service.list_sources(session)
    all_tags = tag_service.list_tags(session)

    is_transfer = movement.transfer_pair_id is not None
    transfer_from_source_id = None
    transfer_to_source_id = None
    transfer_out_id = None

    if is_transfer:
        partner = movement_service.get_movement(session, movement.transfer_pair_id)
        if movement.direction == "out":
            transfer_from_source_id = movement.source_id
            transfer_to_source_id = partner.source_id
            transfer_out_id = movement.id
        else:
            transfer_from_source_id = partner.source_id
            transfer_to_source_id = movement.source_id
            transfer_out_id = partner.id

    return _templates().TemplateResponse("movements/form.html", {
        "request": request,
        "movement": movement,
        "movement_tag_ids": tag_ids,
        "sources": sources,
        "tags": all_tags,
        "is_transfer": is_transfer,
        "preselect_source_id": None,
        "transfer_from_source_id": transfer_from_source_id,
        "transfer_to_source_id": transfer_to_source_id,
        "transfer_out_id": transfer_out_id,
    })


# --- Tags ---
@router.get("/tags")
def tags_index(request: Request, session: Session = Depends(get_session)):
    tags = tag_service.list_tags(session)
    # Count usage per tag (movements + savings)
    mov_counts = dict(session.exec(
        select(MovementTag.tag_id, func.count()).group_by(MovementTag.tag_id)
    ).all())
    sav_counts = dict(session.exec(
        select(SavingTag.tag_id, func.count()).group_by(SavingTag.tag_id)
    ).all())
    tags_enriched = []
    for t in tags:
        tags_enriched.append({
            "id": t.id,
            "name": t.name,
            "color": t.color,
            "usage_count": mov_counts.get(t.id, 0) + sav_counts.get(t.id, 0),
        })
    return _templates().TemplateResponse("tags/index.html", {
        "request": request,
        "tags": tags_enriched,
    })


# --- Recurring ---
@router.get("/recurring")
def recurring_index(
    request: Request,
    frequency: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
):
    per_page = 20
    skip = (page - 1) * per_page
    total_count = recurring_service.count_recurring(session, frequency=frequency, direction=direction)
    total_pages = max(1, math.ceil(total_count / per_page))
    items = recurring_service.list_recurring(session, skip=skip, limit=per_page, frequency=frequency, direction=direction)
    enriched = recurring_service.enrich_recurring_items(session, items)
    summary = recurring_service.monthly_summary(session)
    return _templates().TemplateResponse("recurring/index.html", {
        "request": request,
        "items": enriched,
        "filter_frequency": frequency,
        "filter_direction": direction,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "per_page": per_page,
        "summary": summary,
    })


@router.get("/recurring/new")
def recurring_new(request: Request, session: Session = Depends(get_session)):
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("recurring/form.html", {
        "request": request,
        "item": None,
        "sources": sources,
    })


@router.get("/recurring/{recurring_id}/edit")
def recurring_edit(recurring_id: int, request: Request, session: Session = Depends(get_session)):
    item = recurring_service.get_recurring(session, recurring_id)
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("recurring/form.html", {
        "request": request,
        "item": item,
        "sources": sources,
    })


# --- Notifications ---
@router.get("/notifications")
def notifications_index(
    request: Request,
    filter: str | None = Query(default=None, alias="filter"),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
):
    per_page = 20
    skip = (page - 1) * per_page
    is_read = False if filter == "unread" else None
    type_filter = filter if filter in ("alert", "info", "warning") else None
    total_count = notif_service.count_notifications(session, is_read=is_read, type_filter=type_filter)
    total_pages = max(1, math.ceil(total_count / per_page))
    notifications = notif_service.list_notifications(session, skip=skip, limit=per_page, is_read=is_read, type_filter=type_filter)

    return _templates().TemplateResponse("notifications/index.html", {
        "request": request,
        "notifications": notifications,
        "filter_type": filter,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "per_page": per_page,
    })


# --- Whims (Sfizi) ---
@router.get("/whims")
def whims_index(
    request: Request,
    priority: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    from models.goal import Goal, GoalAllocation
    from sqlmodel import func as _func
    all_whims = whim_service.list_whims(session, limit=500)
    # Fetch linked goals for all whims in one batch.
    linked_ids = [w.linked_goal_id for w in all_whims if w.linked_goal_id]
    goals_by_id: dict[int, Goal] = {}
    allocated_by_goal: dict[int, float] = {}
    if linked_ids:
        goals_by_id = {
            g.id: g
            for g in session.exec(select(Goal).where(col(Goal.id).in_(linked_ids))).all()
        }
        rows = session.exec(
            select(GoalAllocation.goal_id, _func.coalesce(_func.sum(GoalAllocation.amount), 0.0))
            .where(col(GoalAllocation.goal_id).in_(linked_ids))
            .group_by(GoalAllocation.goal_id)
        ).all()
        allocated_by_goal = {int(gid): round(float(amt or 0.0), 2) for gid, amt in rows}

    def enrich(w):
        g = goals_by_id.get(w.linked_goal_id) if w.linked_goal_id else None
        return {
            "id": w.id,
            "name": w.name,
            "amount": w.amount,
            "currency": w.currency,
            "priority": w.priority,
            "source_id": w.source_id,
            "status": w.status,
            "note": w.note,
            "url": w.url,
            "purchased_at": w.purchased_at,
            "created_at": w.created_at,
            "linked_goal_id": g.id if g else None,
            "linked_goal_allocated": allocated_by_goal.get(g.id, 0.0) if g else None,
            "linked_goal_status": g.status if g else None,
        }
    pending = [enrich(w) for w in all_whims if w.status == "pending"]
    achieved = [enrich(w) for w in all_whims if w.status == "purchased"]
    dismissed = [enrich(w) for w in all_whims if w.status == "dismissed"]

    # Apply priority filter
    if priority:
        pending = [w for w in pending if w["priority"] == priority]

    # Sort pending items
    if sort == "amount_asc":
        pending.sort(key=lambda w: w["amount"])
    elif sort == "amount_desc":
        pending.sort(key=lambda w: w["amount"], reverse=True)
    elif sort == "newest":
        pending.sort(key=lambda w: w["created_at"] or "", reverse=True)
    elif sort == "oldest":
        pending.sort(key=lambda w: w["created_at"] or "")
    elif sort == "name":
        pending.sort(key=lambda w: w["name"].lower())

    # Sort achieved by purchase date descending
    achieved.sort(key=lambda w: w["purchased_at"] or "", reverse=True)

    sources = source_service.list_sources(session)
    all_tags = tag_service.list_tags(session)
    return _templates().TemplateResponse("whims/index.html", {
        "request": request,
        "pending": pending,
        "achieved": achieved,
        "dismissed": dismissed,
        "sources": sources,
        "all_tags": all_tags,
        "filter_priority": priority,
        "filter_sort": sort,
    })


@router.get("/whims/new")
def whims_new(request: Request, session: Session = Depends(get_session)):
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("whims/form.html", {
        "request": request,
        "item": None,
        "sources": sources,
    })


@router.get("/whims/{whim_id}/edit")
def whims_edit(whim_id: int, request: Request, session: Session = Depends(get_session)):
    item = whim_service.get_whim(session, whim_id)
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("whims/form.html", {
        "request": request,
        "item": item,
        "sources": sources,
    })


# --- Savings (Risparmio) ---
@router.get("/savings")
def savings_index(
    request: Request,
    currency: str | None = Query(default=None),
    tag_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    session: Session = Depends(get_session),
):
    from services import goals as goal_service
    from services import savings_fund as fund_service
    from services import savings_migration as wizard_service

    per_page = 50
    skip = (page - 1) * per_page
    filter_kwargs = dict(
        currency=currency, tag_id=tag_id,
        date_from=date_from, date_to=date_to,
    )
    total_count = saving_service.count_savings(session, **filter_kwargs)
    total_pages = max(1, math.ceil(total_count / per_page))
    # list_savings returns dict-shaped views already; no further enrichment.
    items = saving_service.list_savings(session, skip=skip, limit=per_page, **filter_kwargs)

    # Group by month (YYYY-MM)
    grouped_savings = []
    for month_key, group in itertools_groupby(items, key=lambda s: s['date'].strftime('%Y-%m')):
        group_list = list(group)
        month_totals: dict[str, float] = {}
        for s in group_list:
            month_totals[s['currency']] = round(month_totals.get(s['currency'], 0) + s['amount'], 2)
        grouped_savings.append({
            'month': month_key,
            'savings': group_list,
            'totals': month_totals,
        })

    # Period totals
    today = date.today()
    first_of_month = today.replace(day=1)
    if first_of_month.month == 1:
        first_of_last_month = first_of_month.replace(year=first_of_month.year - 1, month=12)
    else:
        first_of_last_month = first_of_month.replace(month=first_of_month.month - 1)
    last_day_of_last_month = first_of_month - __import__('datetime').timedelta(days=1)

    if first_of_month.month == 12:
        last_day_of_month = first_of_month.replace(day=31)
    else:
        last_day_of_month = first_of_month.replace(month=first_of_month.month + 1) - __import__('datetime').timedelta(days=1)
    this_month_totals = saving_service.total_saved_period(session, first_of_month, last_day_of_month)
    last_month_totals = saving_service.total_saved_period(session, first_of_last_month, last_day_of_last_month)
    totals = saving_service.total_saved(session)

    # Chart data: contributions trend + running fund balance
    trend_data = saving_service.monthly_trend(session, months=12)
    fund_balance_trend = saving_service.fund_balance_trend(session, months=12)

    # Current fund balance per currency (for the Fondo card)
    funds = fund_service.list_funds(session)
    fund_balances: dict[str, float] = {}
    if funds:
        batch = source_service.get_balances_batch(session, funds)
        for f in funds:
            fund_balances[f.currency] = round(batch.get(f.id, f.starting_balance), 2)

    all_tags = tag_service.list_tags(session)

    default_currency = saving_service.most_used_currency(session)
    if not default_currency:
        settings = settings_service.get_settings(session)
        default_currency = settings.base_currency or "EUR"

    # Sources for pickers — include hidden so fund-to-goal pickers work.
    sources = source_service.list_sources(session, limit=500)
    source_currencies = list({s.currency for s in sources})

    # Pre-serialize sources for the JS layer (tojson) so Chart.js & modal
    # pickers don't choke on datetime attributes from the ORM object.
    sources_js = [
        {
            "id": s.id,
            "name": s.name,
            "currency": s.currency,
            "is_savings_fund": s.is_savings_fund,
            "hidden_from_sources": s.hidden_from_sources,
        }
        for s in sources
    ]

    # Goals (active + completed, sorted by service)
    goals_rows = goal_service.list_goals(session)
    goals_enriched = [goal_service.to_read(session, g) for g in goals_rows]
    # Map source names for display.
    sources_by_id = {s.id: s for s in sources}
    for g in goals_enriched:
        src = sources_by_id.get(g["source_id"])
        g["source_name"] = src.name if src else None
        g["is_fund"] = bool(src and src.is_savings_fund)
        # Strip non-JSON types so Jinja tojson is happy.
        g["target_date"] = g["target_date"].isoformat() if g["target_date"] else None
        g["created_at"] = g["created_at"].isoformat() if g.get("created_at") else None
        g["updated_at"] = g["updated_at"].isoformat() if g.get("updated_at") else None

    wizard_needed = wizard_service.needs_wizard(session)
    wizard_preview = wizard_service.preview(session) if wizard_needed else None

    import datetime as dt_mod
    today_first_of_month = today.replace(day=1).isoformat()
    thirty_days_ago = (today - dt_mod.timedelta(days=30)).isoformat()

    return _templates().TemplateResponse("savings/index.html", {
        "request": request,
        "items": items,
        "grouped_savings": grouped_savings,
        "totals": totals,
        "this_month_totals": this_month_totals,
        "last_month_totals": last_month_totals,
        "fund_balances": fund_balances,
        "trend_data": trend_data,
        "fund_balance_trend": fund_balance_trend,
        "all_tags": all_tags,
        "default_currency": default_currency,
        "sources": sources,
        "sources_js": sources_js,
        "source_currencies": source_currencies,
        "goals": goals_enriched,
        "wizard_needed": wizard_needed,
        "wizard_preview": wizard_preview,
        "filter_currency": currency,
        "filter_tag_id": tag_id,
        "filter_date_from": date_from,
        "filter_date_to": date_to,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "per_page": per_page,
        "today_first_of_month": today_first_of_month,
        "thirty_days_ago": thirty_days_ago,
    })


@router.get("/savings/new")
def savings_new(request: Request, session: Session = Depends(get_session)):
    all_tags = tag_service.list_tags(session)
    default_currency = saving_service.most_used_currency(session)
    if not default_currency:
        settings = settings_service.get_settings(session)
        default_currency = settings.base_currency or "EUR"
    # Pickable sources for "from" — exclude funds (saving from a fund makes no sense).
    sources = [
        s for s in source_service.list_sources(session, limit=500)
        if not s.is_savings_fund
    ]
    return _templates().TemplateResponse("savings/form.html", {
        "request": request,
        "item": None,
        "all_tags": all_tags,
        "saving_tag_ids": [],
        "default_currency": default_currency,
        "sources": sources,
    })


@router.get("/savings/{saving_id}/edit")
def savings_edit(saving_id: int, request: Request, session: Session = Depends(get_session)):
    item = saving_service.get_saving(session, saving_id)  # dict view
    all_tags = tag_service.list_tags(session)
    saving_tag_ids = [t["id"] for t in item["tags"]]
    sources = [
        s for s in source_service.list_sources(session, limit=500)
        if not s.is_savings_fund
    ]
    return _templates().TemplateResponse("savings/form.html", {
        "request": request,
        "item": item,
        "all_tags": all_tags,
        "saving_tag_ids": saving_tag_ids,
        "default_currency": item["currency"],
        "sources": sources,
    })


# --- Portfolios ---
@router.get("/portfolios")
def portfolios_index(request: Request, session: Session = Depends(get_session)):
    items = portfolio_service.list_portfolios(session)
    portfolios = [portfolio_service.summarize_portfolio(session, p) for p in items]
    # Group by source for display (every portfolio has a source now)
    sources = source_service.list_sources(session)
    sources_by_id = {s.id: s for s in sources}
    groups: list[dict] = []
    groups_by_source: dict[int, dict] = {}
    for p in portfolios:
        sid = p.get("source_id")
        src = sources_by_id.get(sid)
        if sid not in groups_by_source:
            g = {
                "source_id": sid,
                "source_name": src.name if src else None,
                "source_currency": src.currency if src else p.get("base_currency"),
                "portfolios": [],
                "total_value": 0.0,
            }
            groups_by_source[sid] = g
            groups.append(g)
        groups_by_source[sid]["portfolios"].append(p)
        groups_by_source[sid]["total_value"] = round(
            groups_by_source[sid]["total_value"] + (p.get("total_value") or 0.0), 2
        )
    prices_enabled = settings_service.get_settings(session).portfolio_prices_enabled
    return _templates().TemplateResponse("portfolios/index.html", {
        "request": request,
        "portfolios": portfolios,
        "groups": groups,
        "prices_enabled": prices_enabled,
    })


@router.get("/portfolios/new")
def portfolios_new(
    request: Request,
    source_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
):
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("portfolios/form.html", {
        "request": request,
        "portfolio": None,
        "sources": sources,
        "preselect_source_id": source_id,
    })


@router.get("/portfolios/{portfolio_id}")
def portfolios_detail(portfolio_id: int, request: Request, session: Session = Depends(get_session)):
    p = portfolio_service.get_portfolio(session, portfolio_id)
    summary = portfolio_service.summarize_portfolio(session, p)
    linked_source = None
    if summary.get("source_id"):
        linked_source = source_service.get_source(session, summary["source_id"])
    prices_enabled = settings_service.get_settings(session).portfolio_prices_enabled
    return _templates().TemplateResponse("portfolios/detail.html", {
        "request": request,
        "portfolio": summary,
        "linked_source": linked_source,
        "prices_enabled": prices_enabled,
    })


@router.get("/portfolios/{portfolio_id}/edit")
def portfolios_edit(portfolio_id: int, request: Request, session: Session = Depends(get_session)):
    p = portfolio_service.get_portfolio(session, portfolio_id)
    sources = source_service.list_sources(session)
    return _templates().TemplateResponse("portfolios/form.html", {
        "request": request,
        "portfolio": p,
        "sources": sources,
    })


# --- Settings ---
@router.get("/settings")
def settings_page(request: Request, session: Session = Depends(get_session)):
    from plugins.registry import get_all_plugins
    from services.importers import list_formats
    from services.importers.presets import list_presets
    current = settings_service.get_settings(session)
    sources_list = source_service.list_sources(session, limit=500)
    return _templates().TemplateResponse("settings/index.html", {
        "request": request,
        "settings": current,
        "plugins": get_all_plugins(),
        "import_formats": list_formats(),
        "import_presets": list_presets(),
        "import_sources": sources_list,
    })
