"""Quick-add movement templates and saved filter views.

Both are stored as JSON-setting blobs (movement_templates_json / saved_views_json),
written whole via PUT /api/settings. These read helpers parse defensively and
prune references to sources/tags that no longer exist, mirroring
i18n.get_nav_items' tolerance of stale layout data.
"""
import json

from sqlmodel import Session, select

from models.source import Source
from models.tag import Tag
from services.settings import get_settings


def _parse_list(raw: str | None) -> list:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    return data if isinstance(data, list) else []


def list_templates(session: Session) -> list[dict]:
    """Parsed quick-add templates with stale source_id/tag_ids pruned."""
    items = _parse_list(get_settings(session).movement_templates_json)
    valid_sources = {s.id for s in session.exec(select(Source)).all()}
    valid_tags = {t.id for t in session.exec(select(Tag)).all()}
    clean: list[dict] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        sid = it.get("source_id")
        if sid is not None and sid not in valid_sources:
            sid = None
        amount = it.get("amount")
        try:
            amount = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount = None
        clean.append({
            "name": str(it.get("name"))[:200],
            "direction": it.get("direction") if it.get("direction") in ("in", "out") else "out",
            "source_id": sid,
            "amount": amount,
            "tag_ids": [t for t in (it.get("tag_ids") or []) if t in valid_tags],
            "note": it.get("note") or None,
        })
    return clean


def list_saved_views(session: Session) -> list[dict]:
    """Parsed saved filter views. Params are passed through; stale source/tag
    ids in params simply return fewer rows when applied (acceptable)."""
    items = _parse_list(get_settings(session).saved_views_json)
    clean: list[dict] = []
    for it in items:
        if isinstance(it, dict) and it.get("name") and isinstance(it.get("params"), dict):
            clean.append({"name": str(it["name"])[:200], "params": it["params"]})
    return clean
