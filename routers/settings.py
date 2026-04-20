import logging
import socket

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from database import get_session
from i18n import _

_logger = logging.getLogger(__name__)
from schemas.setting import SettingRead, SettingUpdate
from services import settings as settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


# --- Password schemas ---

class SetPasswordBody(BaseModel):
    password: str


class ChangePasswordBody(BaseModel):
    current_password: str
    new_password: str


class RemovePasswordBody(BaseModel):
    current_password: str


@router.get("", response_model=SettingRead)
def get_settings(session: Session = Depends(get_session)):
    return settings_service.get_settings(session)


@router.put("", response_model=SettingRead)
def update_settings(data: SettingUpdate, session: Session = Depends(get_session)):
    return settings_service.update_settings(session, data)


@router.get("/lan-info")
def lan_info(request: Request):
    """Return the local network IP and port for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        _logger.debug("Could not determine local IP", exc_info=True)
        local_ip = "127.0.0.1"
    port = request.url.port or 8000
    scheme = request.url.scheme or "http"
    return {"ip": local_ip, "port": port, "scheme": scheme}


# --- Port configuration ---

class SetPortBody(BaseModel):
    port: int


@router.get("/port")
def get_port():
    from security import get_auth_config
    config = get_auth_config()
    port = config.get("port", 8000) if config else 8000
    return {"port": port}


@router.put("/port")
def set_port(body: SetPortBody):
    from security import get_auth_config, save_auth_config
    if body.port < 1024 or body.port > 65535:
        return JSONResponse(status_code=422, content={"detail": _("invalid_port")})
    config = get_auth_config() or {}
    config["port"] = body.port
    save_auth_config(config)
    _logger.info("Port changed to %d (restart required)", body.port)
    return {"ok": True, "port": body.port}


# --- Password management ---

@router.get("/password-status")
def password_status():
    """Check whether a password is currently set."""
    from security import is_password_set
    return {"password_set": is_password_set()}


@router.post("/password")
def set_password_endpoint(body: SetPasswordBody):
    """Set a password for the first time."""
    from security import is_password_set, set_password

    if is_password_set():
        return JSONResponse(status_code=400, content={"detail": _("password_already_set")})
    if not body.password:
        return JSONResponse(status_code=422, content={"detail": _("password_empty")})

    set_password(body.password)
    return {"ok": True, "message": _("password_set_success")}


@router.put("/password")
def change_password_endpoint(body: ChangePasswordBody):
    """Change the current password."""
    from security import is_password_set, change_password

    if not is_password_set():
        return JSONResponse(status_code=400, content={"detail": _("no_password_set")})
    if not body.new_password:
        return JSONResponse(status_code=422, content={"detail": _("password_empty")})

    if not change_password(body.current_password, body.new_password):
        return JSONResponse(status_code=401, content={"detail": _("login_wrong_password")})

    return {"ok": True, "message": _("password_changed_success")}


@router.delete("/password")
def remove_password_endpoint(body: RemovePasswordBody):
    """Remove the password and disable encryption."""
    from security import is_password_set, remove_password

    if not is_password_set():
        return {"ok": True}

    if not remove_password(body.current_password):
        return JSONResponse(status_code=401, content={"detail": _("login_wrong_password")})

    return {"ok": True, "message": _("password_removed_success")}


@router.post("/revoke-sessions")
def revoke_all_sessions(request: Request):
    """Invalidate all sessions by regenerating the session secret."""
    from security import is_password_set, get_auth_config, save_auth_config
    import secrets

    if not is_password_set():
        return JSONResponse(status_code=400, content={"detail": _("no_password_set")})

    config = get_auth_config()
    if not config:
        return JSONResponse(status_code=400, content={"detail": _("no_password_set")})

    new_secret = secrets.token_hex(32)
    config["session_secret"] = new_secret
    save_auth_config(config)

    # Update the live SessionMiddleware signer so existing cookies
    # are immediately rejected without requiring a restart.
    from main import app as _app
    mw = _app.middleware_stack
    while mw is not None:
        if hasattr(mw, "update_secret"):
            mw.update_secret(new_secret)
            _logger.info("Session secret rotated — all sessions invalidated")
            break
        mw = getattr(mw, "app", None)

    # Clear current session too
    request.session.clear()

    return {"ok": True, "message": _("sessions_revoked")}


# --- Log download ---

@router.get("/logs/download")
def download_logs():
    """Download the application log file."""
    from main import LOG_FILE
    if not LOG_FILE.exists():
        return JSONResponse(status_code=404, content={"detail": _("no_logs")})
    return FileResponse(
        path=str(LOG_FILE),
        filename="yfine.log",
        media_type="text/plain",
    )


@router.delete("/logs")
def clear_logs():
    """Clear the log file."""
    from main import LOG_FILE
    if LOG_FILE.exists():
        LOG_FILE.write_text("")
        _logger.info("Log file cleared by user")
    return {"ok": True}


@router.delete("/data")
def reset_all_data(session: Session = Depends(get_session)):
    """Delete all user data (sources, movements, tags, recurring, savings, whims, notifications).

    User preferences and plugin tables are preserved; default tags are re-seeded.
    """
    from services import data as data_service
    data_service.reset_all_data(session)
    _logger.info("All user data reset by user")
    return {"detail": "All data cleared"}
