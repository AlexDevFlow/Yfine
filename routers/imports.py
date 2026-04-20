"""REST endpoints for importing bank statements and other-app exports.

Non-destructive: always ADDS movements to an existing or newly-created Source.
Core routes (all under /api/imports):
  GET    /formats                  - List supported parsers
  GET    /presets                  - List bundled bank/app presets
  GET    /presets/{preset_id}      - Full preset payload
  POST   /preview                  - Parse file, cache result, return preview
  POST   /commit                   - Commit previewed rows into the DB
  DELETE /undo                     - Revert a recent commit using a signed token
"""
import io
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from database import get_session
from models.source import Source
from schemas.imports import (
    FormatInfo,
    ImportCommitRequest,
    ImportCommitResponse,
    ImportPreviewResponse,
    ImportUndoRequest,
    ImportUndoResponse,
    PresetInfo,
    PreviewRow,
)
from schemas.source import SourceCreate
from services import sources as source_service
from services.importers import (
    MAX_UPLOAD_BYTES,
    detect_format,
    get_parser,
    list_formats,
)
from services.importers import cache as preview_cache
from services.importers import commit as commit_service
from services.importers import dedupe, presets, undo
from services.importers.base import ParsedMovement

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.get("/formats", response_model=list[FormatInfo])
def api_list_formats():
    return list_formats()


@router.get("/presets", response_model=list[PresetInfo])
def api_list_presets(format: str | None = None):
    return presets.list_presets(format)


@router.get("/presets/{preset_id}")
def api_get_preset(preset_id: str):
    preset = presets.get_preset(preset_id)
    if preset is None:
        raise HTTPException(status_code=404, detail="Preset not found")
    return preset


def _extract_csv_headers(raw: bytes) -> list[str]:
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        return []
    if text.startswith("\ufeff"):
        text = text[1:]
    first_line = text.splitlines()[0] if text else ""
    for delim in (",", ";", "\t", "|"):
        if delim in first_line:
            return [h.strip().strip('"') for h in first_line.split(delim)]
    return []


@router.post("/preview", response_model=ImportPreviewResponse)
async def api_preview(
    file: UploadFile = File(...),
    format: str | None = Form(default=None),
    preset_id: str | None = Form(default=None),
    options: str | None = Form(default=None),
    source_id: int | None = Form(default=None),
    session: Session = Depends(get_session),
):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file")

    filename = file.filename or ""

    detected_format = format or detect_format(filename, raw)
    if not detected_format:
        raise HTTPException(
            status_code=422,
            detail={"code": "format_not_detected", "message": "Cannot detect file format"},
        )

    try:
        parser = get_parser(detected_format)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    preset_payload = None
    if preset_id:
        preset_payload = presets.get_preset(preset_id)
        if preset_payload is None:
            raise HTTPException(status_code=404, detail="Preset not found")
    else:
        csv_headers = _extract_csv_headers(raw) if detected_format == "csv" else None
        preset_payload = presets.detect_preset(detected_format, raw, csv_headers)

    user_options = {}
    if options:
        try:
            user_options = json.loads(options)
            if not isinstance(user_options, dict):
                raise ValueError("options must be a JSON object")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid options JSON: {exc}")

    parse_options: dict = {}
    if preset_payload and preset_payload.get("options"):
        parse_options.update(preset_payload["options"])
    parse_options.update(user_options)

    try:
        result = parser.parse(raw, parse_options)
    except Exception:
        _logger.exception("Parser %s failed", detected_format)
        raise HTTPException(status_code=422, detail="Failed to parse file")

    needs_mapping = any(w.startswith("needs_mapping:") for w in result.warnings)
    headers: list[str] | None = None
    if needs_mapping:
        for w in result.warnings:
            if w.startswith("needs_mapping:"):
                headers = w.split(":", 1)[1].split(",")
                break

    dup_flags = dedupe.mark_duplicates(session, source_id, result.movements)
    default_include = [i for i, is_dup in enumerate(dup_flags) if not is_dup]

    rows = [
        PreviewRow(
            index=i,
            date=m.date,
            amount=m.amount,
            direction=m.direction,
            note=m.note,
            currency=m.currency,
            is_duplicate=bool(dup_flags[i]),
        )
        for i, m in enumerate(result.movements)
    ]

    total_in = round(sum(m.amount for m in result.movements if m.direction == "in"), 2)
    total_out = round(sum(m.amount for m in result.movements if m.direction == "out"), 2)

    preview_id = preview_cache.put({
        "format": detected_format,
        "movements": result.movements,
        "preset_id": preset_payload["id"] if preset_payload else None,
        "source_id_hint": source_id,
    })

    preset_info = None
    if preset_payload:
        preset_info = PresetInfo(
            id=preset_payload["id"],
            display_name=preset_payload.get("display_name", preset_payload["id"]),
            bank=preset_payload.get("bank"),
            format=preset_payload.get("format", detected_format),
            currency_hint=preset_payload.get("currency_hint"),
            source_hint=preset_payload.get("source_hint"),
        )

    return ImportPreviewResponse(
        preview_id=preview_id,
        detected_format=detected_format,
        detected_preset=preset_info,
        row_count=len(result.movements),
        total_in=total_in,
        total_out=total_out,
        detected_currency=result.detected_currency,
        detected_source_hint=result.detected_source_hint,
        duplicate_count=sum(1 for f in dup_flags if f),
        default_include=default_include,
        warnings=[w for w in result.warnings if not w.startswith("needs_mapping:")],
        rows=rows,
        needs_mapping=needs_mapping and not result.movements,
        headers=headers,
    )


@router.post("/commit", response_model=ImportCommitResponse)
def api_commit(
    payload: ImportCommitRequest,
    session: Session = Depends(get_session),
):
    cached = preview_cache.get(payload.preview_id)
    if cached is None:
        raise HTTPException(status_code=410, detail="Preview expired or invalid")
    parsed: list[ParsedMovement] = cached["movements"]

    if payload.source_id is None and payload.new_source is None:
        raise HTTPException(status_code=400, detail="source_id or new_source is required")
    if payload.source_id is not None and payload.new_source is not None:
        raise HTTPException(status_code=400, detail="Provide either source_id OR new_source, not both")

    if payload.new_source:
        source = source_service.create_source(session, SourceCreate(
            name=payload.new_source.name,
            currency=payload.new_source.currency.upper(),
            starting_balance=float(payload.new_source.starting_balance or 0.0),
        ))
        source_id = source.id
    else:
        existing = session.get(Source, payload.source_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Source not found")
        source_id = existing.id

    if not parsed:
        raise HTTPException(status_code=400, detail="No movements to import")

    indices = set(payload.include_indices or [])
    if not indices:
        raise HTTPException(status_code=400, detail="No rows selected for import")
    include_flags = [i in indices for i in range(len(parsed))]

    result = commit_service.commit(
        session=session,
        parsed=parsed,
        source_id=source_id,
        include_flags=include_flags,
        tag_ids=payload.tag_ids,
        exclude_from_stats=payload.exclude_from_stats,
    )

    token = undo.make_undo_token(source_id, result.created_from, result.created_to)
    preview_cache.invalidate(payload.preview_id)

    from datetime import timedelta
    expires_at = result.created_to + timedelta(seconds=undo.undo_ttl_seconds())

    return ImportCommitResponse(
        imported=result.imported,
        skipped=result.skipped,
        source_id=source_id,
        undo_token=token,
        undo_expires_at=expires_at,
    )


@router.delete("/undo", response_model=ImportUndoResponse)
def api_undo(
    payload: ImportUndoRequest,
    session: Session = Depends(get_session),
):
    deleted = undo.delete_batch(session, payload.undo_token)
    if deleted is None:
        raise HTTPException(status_code=410, detail="Undo token expired or invalid")
    return ImportUndoResponse(deleted=deleted)
