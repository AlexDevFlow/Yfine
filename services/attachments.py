import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlmodel import Session, select

from database import DATA_DIR
from models.movement import Movement, MovementAttachment

MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PER_MOVEMENT = 5
ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}
# Fallback extension lookup by filename when mime type is ambiguous
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".pdf"}


def _attachments_dir() -> Path:
    d = Path(DATA_DIR) / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extension_for(mime_type: str, filename: str) -> str:
    mapped = ALLOWED_MIME.get(mime_type)
    if mapped:
        return mapped
    # Fall back to the uploaded filename's extension if the mime-type mapping
    # didn't hit (browsers sometimes send application/octet-stream for PDFs).
    ext = Path(filename).suffix.lower()
    return ext if ext in ALLOWED_EXT else ""


def _ensure_movement(session: Session, movement_id: int) -> Movement:
    m = session.get(Movement, movement_id)
    if not m:
        raise HTTPException(status_code=404, detail="Movement not found")
    return m


def list_attachments(session: Session, movement_id: int) -> list[MovementAttachment]:
    _ensure_movement(session, movement_id)
    return list(
        session.exec(
            select(MovementAttachment)
            .where(MovementAttachment.movement_id == movement_id)
            .order_by(MovementAttachment.created_at)
        ).all()
    )


def get_attachment(session: Session, attachment_id: int) -> MovementAttachment:
    att = session.get(MovementAttachment, attachment_id)
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return att


def attachment_path(att: MovementAttachment) -> Path:
    # stored_name is a UUID4 + whitelisted extension produced by us — never
    # trust the original filename for disk paths.
    return _attachments_dir() / att.stored_name


async def create_attachment(
    session: Session, movement_id: int, upload: UploadFile
) -> MovementAttachment:
    _ensure_movement(session, movement_id)

    existing_count = session.exec(
        select(MovementAttachment).where(MovementAttachment.movement_id == movement_id)
    ).all()
    if len(existing_count) >= MAX_PER_MOVEMENT:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_PER_MOVEMENT} attachments per movement",
        )

    mime_type = (upload.content_type or "").lower()
    ext = _extension_for(mime_type, upload.filename or "")
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PNG, JPEG, WebP, HEIC, PDF",
        )

    # Read and size-check the upload. We stream to detect oversize without
    # buffering everything past the limit.
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File too large (max 10 MB)")
        chunks.append(chunk)

    if total == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = _attachments_dir() / stored_name
    with open(path, "wb") as f:
        for chunk in chunks:
            f.write(chunk)

    att = MovementAttachment(
        movement_id=movement_id,
        filename=(upload.filename or stored_name)[:255],
        stored_name=stored_name,
        # Normalize mime type: if the browser sent something weird but the
        # extension matched, store the canonical mime for that extension.
        mime_type=mime_type if mime_type in ALLOWED_MIME else _mime_for_ext(ext),
        size_bytes=total,
        created_at=datetime.utcnow(),
    )
    session.add(att)
    session.commit()
    session.refresh(att)
    return att


def delete_attachment(session: Session, attachment_id: int) -> None:
    att = get_attachment(session, attachment_id)
    path = attachment_path(att)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    session.delete(att)
    session.commit()


def delete_attachments_for_movement(session: Session, movement_id: int) -> None:
    """Used when a movement is deleted — remove files too."""
    items = session.exec(
        select(MovementAttachment).where(MovementAttachment.movement_id == movement_id)
    ).all()
    for att in items:
        path = attachment_path(att)
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        session.delete(att)


def _mime_for_ext(ext: str) -> str:
    for m, e in ALLOWED_MIME.items():
        if e == ext:
            return m
    return "application/octet-stream"
