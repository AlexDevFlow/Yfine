import json
import zipfile
from io import BytesIO

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response
from sqlmodel import Session

from sqlmodel import select, col

from database import get_session
from models.movement import Movement
from models.source import Source
from models.tag import Tag
from services import dashboard as dashboard_service
from services import data as data_service
from services.excel_export import export_excel, EXPORTABLE_SECTIONS
from services.pdf_export import export_pdf, EXPORTABLE_SECTIONS as PDF_SECTIONS

router = APIRouter(prefix="/api", tags=["data"])

_MAX_ARCHIVE_SIZE = 100 * 1024 * 1024  # 100 MB


@router.get("/export")
def export_data(
    mode: str = Query(default="core", pattern="^(core|all)$"),
    session: Session = Depends(get_session),
):
    if mode == "all":
        archive_bytes = data_service.export_archive(session)
        return Response(
            content=archive_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="yfine-export-full.yfine"'
            },
        )
    return data_service.export_all(session, mode=mode)


@router.post("/import/preview")
async def import_preview(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > _MAX_ARCHIVE_SIZE:
        from fastapi import HTTPException
        raise HTTPException(413, "File too large (max 100 MB)")

    if zipfile.is_zipfile(BytesIO(raw)):
        return data_service.preview_archive(raw)
    else:
        data = json.loads(raw)
        return data_service.preview_json(data)


@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    raw = await file.read()
    if len(raw) > _MAX_ARCHIVE_SIZE:
        from fastapi import HTTPException
        raise HTTPException(413, "File too large (max 100 MB)")

    if zipfile.is_zipfile(BytesIO(raw)):
        return data_service.import_archive(session, raw)
    else:
        data = json.loads(raw)
        data_service.import_all(session, data)
        return {"detail": "Import successful", "requires_restart": False}


@router.get("/export/excel")
def export_excel_file(
    sections: str = Query(
        default=",".join(EXPORTABLE_SECTIONS),
        description="Comma-separated list of sections to include",
    ),
    session: Session = Depends(get_session),
):
    selected = [s.strip() for s in sections.split(",") if s.strip() in EXPORTABLE_SECTIONS]
    xlsx_bytes = export_excel(session, selected)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="yfine-export.xlsx"'
        },
    )


@router.get("/export/pdf")
def export_pdf_file(
    sections: str = Query(
        default=",".join(PDF_SECTIONS),
        description="Comma-separated list of sections to include",
    ),
    session: Session = Depends(get_session),
):
    selected = [s.strip() for s in sections.split(",") if s.strip() in PDF_SECTIONS]
    pdf_bytes = export_pdf(session, selected)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="yfine-report.pdf"'
        },
    )


@router.get("/dashboard")
def get_dashboard(session: Session = Depends(get_session)):
    stats = dashboard_service.get_dashboard_stats(session)
    # Serialize for JSON
    return {
        "net_worth": stats["net_worth"],
        "source_count": stats["source_count"],
        "movement_count": stats["movement_count"],
        "unread_notifications": stats["unread_notifications"],
    }


@router.get("/monthly-movements")
def get_monthly_movements(
    direction: str = Query(...),
    session: Session = Depends(get_session),
):
    return dashboard_service.get_monthly_movements(session, direction)


@router.get("/monthly-totals")
def get_monthly_totals(session: Session = Depends(get_session)):
    return dashboard_service.get_monthly_totals(session)


@router.get("/net-worth/history")
def get_net_worth_history(
    range: str = Query(default="all", alias="range"),
    session: Session = Depends(get_session),
):
    return dashboard_service.get_net_worth_history(session, range)


@router.get("/monthly-comparison")
def get_monthly_comparison(
    months: int = Query(default=12, ge=2, le=36),
    session: Session = Depends(get_session),
):
    return dashboard_service.get_monthly_comparison(session, months)


@router.get("/search")
def global_search(
    q: str = Query(min_length=2, max_length=100),
    types: str | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=25),
    session: Session = Depends(get_session),
):
    """Search across the whole app. Returns grouped, enriched results.

    types: optional comma-separated filter
      (sources, movements, tags, savings, whims, recurring). Omit for all.
    """
    from datetime import date as _date
    from models.movement import MovementTag
    from models.recurring import RecurringItem
    from models.saving import Saving
    from models.whim import Whim

    term = f"%{q}%"
    wanted = None
    if types:
        wanted = {t.strip() for t in types.split(",") if t.strip()}

    # Try parsing the query as a number so "45.50" can match exact amounts.
    numeric: float | None = None
    try:
        numeric = float(q.replace(",", ".").strip())
    except (ValueError, AttributeError):
        numeric = None

    result: dict = {}

    # --- Sources ---
    if wanted is None or "sources" in wanted:
        src_rows = session.exec(
            select(Source).where(col(Source.name).ilike(term)).limit(limit)
        ).all()
        if src_rows:
            result["sources"] = [
                {"id": s.id, "name": s.name, "currency": s.currency}
                for s in src_rows
            ]

    # --- Tags ---
    if wanted is None or "tags" in wanted:
        tag_rows = session.exec(
            select(Tag).where(col(Tag.name).ilike(term)).limit(limit)
        ).all()
        if tag_rows:
            # include a usage count for context in the UI
            tag_ids = [t.id for t in tag_rows]
            from sqlalchemy import func as _func
            counts = dict(session.exec(
                select(MovementTag.tag_id, _func.count(MovementTag.movement_id))
                .where(col(MovementTag.tag_id).in_(tag_ids))
                .group_by(MovementTag.tag_id)
            ).all())
            result["tags"] = [
                {"id": t.id, "name": t.name, "color": t.color, "count": counts.get(t.id, 0)}
                for t in tag_rows
            ]

    # --- Movements ---
    if wanted is None or "movements" in wanted:
        mov_query = select(Movement).where(col(Movement.note).ilike(term))
        if numeric is not None and numeric > 0:
            from sqlalchemy import or_
            mov_query = select(Movement).where(
                or_(
                    col(Movement.note).ilike(term),
                    Movement.amount == numeric,
                )
            )
        mov_rows = session.exec(
            mov_query.order_by(col(Movement.date).desc()).limit(limit)
        ).all()
        if mov_rows:
            # Enrich with source name + tags in a single batch
            src_ids = {m.source_id for m in mov_rows if m.source_id}
            names_by_id: dict[int, str] = {}
            if src_ids:
                names_by_id = {
                    s.id: s.name
                    for s in session.exec(
                        select(Source).where(col(Source.id).in_(src_ids))
                    ).all()
                }
            mov_ids = [m.id for m in mov_rows]
            tag_map: dict[int, list[dict]] = {mid: [] for mid in mov_ids}
            if mov_ids:
                rows = session.exec(
                    select(MovementTag.movement_id, Tag)
                    .join(Tag, Tag.id == MovementTag.tag_id)
                    .where(col(MovementTag.movement_id).in_(mov_ids))
                ).all()
                for mid, tg in rows:
                    tag_map.setdefault(mid, []).append(
                        {"id": tg.id, "name": tg.name, "color": tg.color}
                    )
            result["movements"] = [
                {
                    "id": m.id,
                    "amount": m.amount,
                    "direction": m.direction,
                    "note": m.note,
                    "date": str(m.date),
                    "source_name": names_by_id.get(m.source_id) if m.source_id else None,
                    "is_transfer": m.transfer_pair_id is not None,
                    "tags": tag_map.get(m.id, []),
                }
                for m in mov_rows
            ]

    # --- Savings ---
    # Post-refactor, savings are Movement rows with is_savings_contribution=True
    # landing in a per-currency fund. Legacy Saving rows only linger on DBs that
    # haven't run the migration wizard yet — we search both for continuity.
    if wanted is None or "savings" in wanted:
        from sqlalchemy import or_
        sav_mov_rows = session.exec(
            select(Movement, Source)
            .join(Source, Movement.source_id == Source.id)
            .where(
                Movement.is_savings_contribution == True,  # noqa: E712
                col(Movement.note).ilike(term),
            )
            .order_by(col(Movement.date).desc())
            .limit(limit)
        ).all()
        savings_payload: list[dict] = [
            {
                "id": m.id,
                "amount": m.amount,
                "currency": s.currency,
                "description": m.note,
                "note": None,
                "date": str(m.date),
            }
            for m, s in sav_mov_rows
        ]
        legacy_rows = session.exec(
            select(Saving).where(
                or_(
                    col(Saving.description).ilike(term),
                    col(Saving.note).ilike(term),
                )
            ).order_by(col(Saving.date).desc()).limit(limit)
        ).all()
        savings_payload.extend(
            {
                "id": s.id,
                "amount": s.amount,
                "currency": s.currency,
                "description": s.description,
                "note": s.note,
                "date": str(s.date),
            }
            for s in legacy_rows
        )
        if savings_payload:
            result["savings"] = savings_payload[:limit]

    # --- Whims ---
    if wanted is None or "whims" in wanted:
        from sqlalchemy import or_
        whim_rows = session.exec(
            select(Whim).where(
                or_(
                    col(Whim.name).ilike(term),
                    col(Whim.note).ilike(term),
                )
            ).limit(limit)
        ).all()
        if whim_rows:
            result["whims"] = [
                {
                    "id": w.id,
                    "name": w.name,
                    "amount": w.amount,
                    "currency": w.currency,
                    "status": w.status,
                    "priority": w.priority,
                }
                for w in whim_rows
            ]

    # --- Recurring ---
    if wanted is None or "recurring" in wanted:
        rec_rows = session.exec(
            select(RecurringItem).where(col(RecurringItem.name).ilike(term)).limit(limit)
        ).all()
        if rec_rows:
            result["recurring"] = [
                {
                    "id": r.id,
                    "name": r.name,
                    "amount": r.amount,
                    "currency": r.currency,
                    "direction": r.direction,
                    "frequency": r.frequency,
                    "next_due_date": str(r.next_due_date) if r.next_due_date else None,
                }
                for r in rec_rows
            ]

    return result
