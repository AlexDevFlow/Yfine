import tempfile
import time
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from pydantic import BaseModel

from plugins.manager import (
    PluginManifest,
    install_plugin,
    uninstall_plugin,
    update_plugin,
    safe_extractall,
)
from plugins.registry import get_all_plugins, get_plugin
from plugins.scanner import scan_plugin
from plugins.state import set_plugin_enabled

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

MAX_ZIP_SIZE = 50 * 1024 * 1024  # 50 MB
_PENDING_MAX_ENTRIES = 5
_PENDING_TTL_SECONDS = 600  # 10 minutes

# Temporary storage for scanned zips awaiting confirmation
# Each value is (zip_data, scan_report_dict, timestamp)
_pending_installs: dict[str, tuple[bytes, dict, float]] = {}
_pending_lock = threading.Lock()


def _pending_set(plugin_id: str, zip_data: bytes, report_dict: dict) -> None:
    """Store a scanned zip + report with TTL. Evict expired entries and enforce max size."""
    now = time.time()
    with _pending_lock:
        # Evict expired entries
        expired = [k for k, (_, _, ts) in _pending_installs.items()
                   if now - ts > _PENDING_TTL_SECONDS]
        for k in expired:
            del _pending_installs[k]
        # Enforce max entries (evict oldest if full)
        while len(_pending_installs) >= _PENDING_MAX_ENTRIES:
            oldest = min(_pending_installs, key=lambda k: _pending_installs[k][2])
            del _pending_installs[oldest]
        _pending_installs[plugin_id] = (zip_data, report_dict, now)


def _pending_pop(plugin_id: str) -> tuple[bytes, dict] | None:
    """Retrieve and remove a pending entry if it exists and hasn't expired."""
    now = time.time()
    with _pending_lock:
        entry = _pending_installs.pop(plugin_id, None)
        if entry is None:
            return None
        data, report, ts = entry
        if now - ts > _PENDING_TTL_SECONDS:
            return None
        return data, report


def _pending_peek(plugin_id: str) -> tuple[bytes, dict] | None:
    """Read a pending entry without removing it (for re-store on blocked install)."""
    now = time.time()
    with _pending_lock:
        entry = _pending_installs.get(plugin_id)
        if entry is None:
            return None
        data, report, ts = entry
        if now - ts > _PENDING_TTL_SECONDS:
            del _pending_installs[plugin_id]
            return None
        return data, report


@router.get("")
def list_plugins():
    return [
        {
            "id": p.id,
            "name": p.name,
            "version": p.version,
            "description": p.description,
            "author": p.author,
            "icon": p.icon,
            "enabled": p.enabled,
        }
        for p in get_all_plugins()
    ]


@router.post("/scan")
async def api_scan_plugin(file: UploadFile = File(...)):
    """Upload a plugin zip for security scanning. Returns a report.
    The zip is held in memory — call /install with confirm=true to proceed."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    zip_data = await file.read(MAX_ZIP_SIZE + 1)
    if len(zip_data) > MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    # Extract to temp dir for scanning
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "plugin.zip"
            zip_path.write_bytes(zip_data)

            if not zipfile.is_zipfile(zip_path):
                raise ValueError("Not a valid zip archive")

            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, tmp_path / "extracted")

            extracted = tmp_path / "extracted"
            dirs = [d for d in extracted.iterdir() if d.is_dir()]
            if len(dirs) != 1:
                raise ValueError("Zip must contain exactly one plugin directory")

            plugin_dir = dirs[0]

            # Validate manifest exists
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("No manifest.json found in plugin")

            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Validate manifest through Pydantic model
            parsed = PluginManifest(**manifest)
            plugin_id = parsed.id

            # Run security scan
            report = scan_plugin(plugin_dir, plugin_id)

    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Store zip data + report for confirmed install (with TTL and size limit)
    report_dict = report.to_dict()
    _pending_set(plugin_id, zip_data, report_dict)

    return {
        "plugin_id": parsed.id,
        "plugin_name": parsed.name,
        "plugin_version": parsed.version,
        "scan": report_dict,
    }


@router.post("/install")
async def api_install_plugin(
    plugin_id: str = Query(...),
    accept_risk: bool = Query(False),
):
    """Install a previously scanned plugin. Requires a prior call to /scan.
    If the scan had critical findings, accept_risk=true is required."""
    entry = _pending_peek(plugin_id)
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="No pending scan found or scan expired. Upload and scan first.",
        )

    _, report = entry
    if report["counts"]["critical"] > 0 and not accept_risk:
        raise HTTPException(
            status_code=422,
            detail="Plugin has critical security findings. "
                   "Pass accept_risk=true to install anyway.",
            headers={"X-Scan-Report": "true"},
        )

    # Pop only after validation passes
    _pending_pop(plugin_id)

    try:
        info = install_plugin(zip_data=entry[0], _scanned=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "installed",
        "plugin_id": info.id,
        "plugin_name": info.name,
        "restart_required": True,
    }


@router.post("/scan-update")
async def api_scan_update_plugin(file: UploadFile = File(...)):
    """Upload a plugin zip for update. Runs security scan and stores the zip
    pending confirmation — mirrors the install flow (F-02 fix)."""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="File must be a .zip archive")

    zip_data = await file.read(MAX_ZIP_SIZE + 1)
    if len(zip_data) > MAX_ZIP_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            zip_path = tmp_path / "plugin.zip"
            zip_path.write_bytes(zip_data)

            if not zipfile.is_zipfile(zip_path):
                raise ValueError("Not a valid zip archive")

            with zipfile.ZipFile(zip_path, "r") as zf:
                safe_extractall(zf, tmp_path / "extracted")

            extracted = tmp_path / "extracted"
            dirs = [d for d in extracted.iterdir() if d.is_dir()]
            if len(dirs) != 1:
                raise ValueError("Zip must contain exactly one plugin directory")

            plugin_dir = dirs[0]
            manifest_path = plugin_dir / "manifest.json"
            if not manifest_path.exists():
                raise ValueError("No manifest.json found in plugin")

            import json
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            # Validate manifest through Pydantic model
            parsed = PluginManifest(**manifest)
            plugin_id = parsed.id
            report = scan_plugin(plugin_dir, plugin_id)

    except (ValueError, Exception) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Store zip + report pending user confirmation (same as install flow)
    report_dict = report.to_dict()
    _pending_set(f"update:{plugin_id}", zip_data, report_dict)

    return {
        "plugin_id": parsed.id,
        "plugin_name": parsed.name,
        "plugin_version": parsed.version,
        "scan": report_dict,
    }


@router.post("/confirm-update")
async def api_confirm_update_plugin(
    plugin_id: str = Query(...),
    accept_risk: bool = Query(False),
):
    """Confirm and apply a previously scanned plugin update.
    If the scan had critical findings, accept_risk=true is required."""
    key = f"update:{plugin_id}"
    entry = _pending_peek(key)
    if entry is None:
        raise HTTPException(
            status_code=400,
            detail="No pending update scan found or scan expired. Upload and scan first.",
        )

    _, report = entry
    if report["counts"]["critical"] > 0 and not accept_risk:
        raise HTTPException(
            status_code=422,
            detail="Plugin update has critical security findings. "
                   "Pass accept_risk=true to update anyway.",
            headers={"X-Scan-Report": "true"},
        )

    _pending_pop(key)

    try:
        info = update_plugin(zip_data=entry[0], _scanned=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "status": "updated",
        "plugin_id": info.id,
        "plugin_name": info.name,
        "restart_required": True,
    }


class PluginEnabledBody(BaseModel):
    enabled: bool


@router.patch("/{plugin_id}/enabled")
def api_toggle_plugin(plugin_id: str, body: PluginEnabledBody):
    """Enable or disable a plugin. Takes effect after restart."""
    plugin = get_plugin(plugin_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail="Plugin not found")
    set_plugin_enabled(plugin_id, body.enabled)
    plugin.enabled = body.enabled
    return {
        "plugin_id": plugin_id,
        "enabled": body.enabled,
        "restart_required": True,
    }


@router.delete("/{plugin_id}")
def api_uninstall_plugin(plugin_id: str):
    if not uninstall_plugin(plugin_id):
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {
        "status": "uninstalled",
        "plugin_id": plugin_id,
        "restart_required": True,
    }
