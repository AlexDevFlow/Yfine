from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from database import get_session
from i18n import _
from models.source import Source
from schemas.attachment import AttachmentRead
from schemas.movement import (
    BulkDelete, BulkExclude, BulkResult, BulkSource, BulkTags, MakeRecurring,
    MovementCreate, MovementRead, MovementUpdate, TransferCreate, TransferUpdate,
)
from schemas.tag import TagRead
from services import attachments as attachment_service
from services import movements as movement_service

router = APIRouter(prefix="/api/movements", tags=["movements"])


def _to_attachment_read(att) -> AttachmentRead:
    return AttachmentRead(
        id=att.id,
        movement_id=att.movement_id,
        filename=att.filename,
        mime_type=att.mime_type,
        size_bytes=att.size_bytes,
        created_at=att.created_at,
    )


def _to_read(session: Session, m) -> MovementRead:
    tags = movement_service.get_movement_tags(session, m.id)
    source = session.get(Source, m.source_id) if m.source_id else None
    return MovementRead(
        id=m.id,
        source_id=m.source_id,
        source_name=source.name if source else _("external"),
        amount=m.amount,
        direction=m.direction,
        date=m.date,
        note=m.note,
        transfer_pair_id=m.transfer_pair_id,
        tags=[TagRead(id=t.id, name=t.name, created_at=t.created_at, updated_at=t.updated_at) for t in tags],
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


@router.get("", response_model=list[MovementRead])
def list_movements(
    skip: int = 0,
    limit: int = 50,
    source_id: int | None = Query(default=None),
    tag_ids: list[int] = Query(default_factory=list),
    direction: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    amount_min: float | None = Query(default=None),
    amount_max: float | None = Query(default=None),
    q: str | None = Query(default=None),
    tag_match: str = Query(default="or"),
    session: Session = Depends(get_session),
):
    items = movement_service.list_movements(
        session, skip, limit, source_id, tag_ids or None,
        direction, date_from, date_to, amount_min, amount_max,
        q=q, tag_match=tag_match,
    )
    return [_to_read(session, m) for m in items]


@router.post("", response_model=MovementRead, status_code=201)
def create_movement(data: MovementCreate, session: Session = Depends(get_session)):
    m = movement_service.create_movement(session, data)
    return _to_read(session, m)


@router.get("/{movement_id}", response_model=MovementRead)
def get_movement(movement_id: int, session: Session = Depends(get_session)):
    m = movement_service.get_movement(session, movement_id)
    return _to_read(session, m)


@router.put("/{movement_id}", response_model=MovementRead)
def update_movement(
    movement_id: int, data: MovementUpdate, session: Session = Depends(get_session)
):
    m = movement_service.update_movement(session, movement_id, data)
    return _to_read(session, m)


@router.delete("/{movement_id}", status_code=204)
def delete_movement(movement_id: int, session: Session = Depends(get_session)):
    movement_service.delete_movement(session, movement_id)


# ---------------------------------------------------------------------------
# Bulk operations
# ---------------------------------------------------------------------------


@router.post("/bulk/delete", response_model=BulkResult)
def bulk_delete(data: BulkDelete, session: Session = Depends(get_session)):
    return BulkResult(**movement_service.bulk_delete(session, data.ids))


@router.post("/bulk/tags", response_model=BulkResult)
def bulk_tags(data: BulkTags, session: Session = Depends(get_session)):
    return BulkResult(**movement_service.bulk_set_tags(session, data.ids, data.tag_ids, data.mode))


@router.post("/bulk/source", response_model=BulkResult)
def bulk_source(data: BulkSource, session: Session = Depends(get_session)):
    return BulkResult(**movement_service.bulk_set_source(session, data.ids, data.source_id))


@router.post("/bulk/exclude", response_model=BulkResult)
def bulk_exclude(data: BulkExclude, session: Session = Depends(get_session)):
    return BulkResult(**movement_service.bulk_set_exclude(session, data.ids, data.exclude_from_stats))


@router.post("/{movement_id}/make-recurring", status_code=201)
def make_recurring(
    movement_id: int, data: MakeRecurring, session: Session = Depends(get_session)
):
    from routers.recurring import _to_read as recurring_to_read
    item = movement_service.make_recurring_from_movement(
        session, movement_id, data.frequency, data.apply_mode
    )
    return recurring_to_read(session, item)


@router.post("/transfer", response_model=list[MovementRead], status_code=201)
def create_transfer(data: TransferCreate, session: Session = Depends(get_session)):
    out_m, in_m = movement_service.create_transfer(session, data)
    return [_to_read(session, out_m), _to_read(session, in_m)]


@router.put("/transfer/{movement_id}", response_model=list[MovementRead])
def update_transfer(
    movement_id: int, data: TransferUpdate, session: Session = Depends(get_session)
):
    out_m, in_m = movement_service.update_transfer(session, movement_id, data)
    return [_to_read(session, out_m), _to_read(session, in_m)]


@router.get("/calendar/trend")
def movements_calendar_trend(
    months: int = Query(default=12, ge=1, le=36),
    session: Session = Depends(get_session),
):
    """Monthly totals (in/out) for calendar view."""
    from sqlmodel import select, func
    from models.movement import Movement
    from models.source import Source
    from dateutil.relativedelta import relativedelta
    cutoff = date.today().replace(day=1) - relativedelta(months=months - 1)
    rows = session.exec(
        select(
            func.strftime("%Y-%m", Movement.date).label("month"),
            Movement.direction,
            func.sum(Movement.amount),
        )
        .where(Movement.date >= cutoff, Movement.transfer_pair_id.is_(None))
        .group_by("month", Movement.direction)
        .order_by("month")
    ).all()
    return [{"month": r[0], "direction": r[1], "total": round(float(r[2]), 2)} for r in rows]


@router.get("/calendar/{year_month}")
def movements_by_month(
    year_month: str,
    session: Session = Depends(get_session),
):
    """Get all movements for a given month (YYYY-MM)."""
    from calendar import monthrange
    parts = year_month.split("-")
    year, month = int(parts[0]), int(parts[1])
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    items = movement_service.list_movements(
        session, skip=0, limit=500,
        date_from=first, date_to=last, exclude_transfer_in=True,
    )
    result = []
    for m in items:
        tags = movement_service.get_movement_tags(session, m.id)
        source = session.get(Source, m.source_id) if m.source_id else None
        result.append({
            "id": m.id,
            "date": m.date.isoformat(),
            "amount": m.amount,
            "direction": m.direction,
            "source_name": source.name if source else _("external"),
            "note": m.note,
            "transfer_pair_id": m.transfer_pair_id,
            "tags": [{"id": t.id, "name": t.name} for t in tags],
        })
    return result


@router.post("/{movement_id}/exclude")
def toggle_exclude_from_stats(movement_id: int, session: Session = Depends(get_session)):
    m = movement_service.toggle_exclude_from_stats(session, movement_id)
    return {"id": m.id, "exclude_from_stats": m.exclude_from_stats}


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------


@router.get("/{movement_id}/attachments", response_model=list[AttachmentRead])
def list_movement_attachments(
    movement_id: int, session: Session = Depends(get_session)
):
    items = attachment_service.list_attachments(session, movement_id)
    return [_to_attachment_read(a) for a in items]


@router.post(
    "/{movement_id}/attachments",
    response_model=AttachmentRead,
    status_code=201,
)
async def upload_movement_attachment(
    movement_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    att = await attachment_service.create_attachment(session, movement_id, file)
    return _to_attachment_read(att)


@router.get("/attachments/{attachment_id}")
def download_movement_attachment(
    attachment_id: int,
    session: Session = Depends(get_session),
):
    att = attachment_service.get_attachment(session, attachment_id)
    path = attachment_service.attachment_path(att)
    if not path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File missing on disk")
    # inline so browser renders images / PDFs instead of forcing download
    headers = {
        "Content-Disposition": f'inline; filename="{att.filename}"',
    }
    return FileResponse(str(path), media_type=att.mime_type, headers=headers)


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_movement_attachment(
    attachment_id: int,
    session: Session = Depends(get_session),
):
    attachment_service.delete_attachment(session, attachment_id)
