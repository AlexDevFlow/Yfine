import logging as _logging
import os
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
import itsdangerous


class RevocableSessionMiddleware(SessionMiddleware):
    """SessionMiddleware whose secret can be rotated at runtime."""

    def update_secret(self, new_secret: str):
        self.signer = itsdangerous.TimestampSigner(new_secret)

from database import init_db, BASE_DIR, DATA_DIR
from i18n import get_translator, set_locale, get_locale, set_date_format, get_date_format, currency_flag, format_date
from scheduler import start_scheduler, shutdown_scheduler

# ---------------------------------------------------------------------------
# Centralized file logging (works in both desktop and server mode)
# ---------------------------------------------------------------------------
LOG_FILE = DATA_DIR / "yfine.log"

# Only configure if desktop.py hasn't already done so
if not _logging.root.handlers:
    _logging.basicConfig(
        level=_logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            _logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            _logging.StreamHandler(),
        ],
    )
elif not any(isinstance(h, _logging.FileHandler) for h in _logging.root.handlers):
    # Desktop mode already configured, but ensure the file handler exists
    _fh = _logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    _fh.setFormatter(_logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logging.root.addHandler(_fh)

_logger = _logging.getLogger(__name__)

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}


class LocalhostOnlyPluginMiddleware(BaseHTTPMiddleware):
    """Restrict plugin management endpoints to localhost only (F-03)."""

    async def dispatch(self, request: Request, call_next):
        is_plugin_mgmt = (
            request.url.path.startswith("/api/plugins") and request.method != "GET"
        )
        # Restrict only the legacy full-backup import (/api/import, /api/import/preview)
        # but NOT the granular /api/imports/* endpoints (multi-format bank import).
        path = request.url.path
        is_legacy_import = (
            request.method == "POST" and (
                path == "/api/import" or path.startswith("/api/import/") and not path.startswith("/api/imports")
            )
        )
        if is_plugin_mgmt or is_legacy_import:
            client_host = request.client.host if request.client else None
            if client_host not in _LOCALHOST_IPS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Plugin management is only allowed from localhost"},
                )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """Require authentication when a password is set."""

    _OPEN_PREFIXES = ("/static", "/login", "/api/auth/", "/api/settings/password-status")

    async def dispatch(self, request: Request, call_next):
        from security import is_password_set

        path = request.url.path

        # Always allow static assets, login page, and auth endpoints
        for prefix in self._OPEN_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        if not is_password_set():
            return await call_next(request)

        # Check session cookie
        if request.session.get("authenticated"):
            return await call_next(request)

        # Not authenticated
        if path.startswith("/api"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )
        return RedirectResponse("/login", status_code=302)


# ---------------------------------------------------------------------------
# App initialization helper  (called from lifespan or after login)
# ---------------------------------------------------------------------------

def _load_settings_into_i18n():
    """Read settings from DB and push values into the i18n module."""
    from sqlmodel import Session
    from database import engine
    from services.settings import get_settings
    from i18n import set_theme, set_hide_net_worth, set_last_source_id, set_mobile_nav_mode

    with Session(engine) as session:
        settings = get_settings(session)
        set_locale(settings.locale)
        set_date_format(settings.date_format)
        set_theme(settings.theme)
        set_hide_net_worth(settings.hide_net_worth)
        set_last_source_id(settings.last_source_id)
        set_mobile_nav_mode(settings.mobile_nav_mode)
        return settings


def _initialize_plugins(app_instance, settings_locale: str):
    """Discover, validate, and register plugins."""
    from plugins.manager import (
        discover_plugins, load_plugin_models, load_plugin_routes,
        load_plugin_i18n,
    )
    from plugins.state import auto_disable_plugin

    discovered = discover_plugins()
    enabled = [p for p in discovered if p.enabled]
    failed: set[str] = set()

    # Load plugin models
    for p in enabled:
        if p.has_models:
            try:
                load_plugin_models(p)
            except Exception:
                _logger.exception("Plugin %s model loading failed — skipping", p.id)
                failed.add(p.id)
    enabled = [p for p in enabled if p.id not in failed]

    # Load plugin i18n
    for p in enabled:
        try:
            load_plugin_i18n(p, settings_locale)
        except Exception:
            _logger.exception("Plugin %s i18n loading failed — skipping", p.id)
            failed.add(p.id)
    enabled = [p for p in enabled if p.id not in failed]

    # Collect core paths for collision detection
    core_paths = {route.path for route in app_instance.routes if hasattr(route, "path")}
    plugin_paths: dict[str, str] = {}

    # Register plugin routes
    for p in enabled:
        if p.has_routes:
            try:
                router = load_plugin_routes(p)
            except Exception:
                _logger.exception("Plugin %s route loading failed — skipping", p.id)
                failed.add(p.id)
                continue
            if router:
                prefix = getattr(router, "prefix", "")
                collision = False
                for route in router.routes:
                    rpath = getattr(route, "path", None)
                    if rpath:
                        full = prefix + rpath
                        if full in core_paths or full in plugin_paths:
                            _logger.error("Plugin %s route %s collides — rejected", p.id, full)
                            collision = True
                            break
                if not collision:
                    app_instance.include_router(router)
                    for route in router.routes:
                        rpath = getattr(route, "path", None)
                        if rpath:
                            plugin_paths[prefix + rpath] = p.id
    enabled = [p for p in enabled if p.id not in failed]

    for pid in failed:
        auto_disable_plugin(pid)

    # Mount plugin static dirs
    for p in enabled:
        static_dir = p.path / "static"
        if static_dir.exists():
            app_instance.mount(
                f"/static/plugins/{p.id}",
                StaticFiles(directory=str(static_dir)),
                name=f"plugin_static_{p.id}",
            )

    # Add plugin template dirs
    registered_tpl: dict[str, str] = {}
    for p in enabled:
        tpl_dir = p.path / "templates"
        if not tpl_dir.exists():
            continue
        violation = False
        for tpl_file in tpl_dir.rglob("*.html"):
            rel = tpl_file.relative_to(tpl_dir)
            parts = rel.parts
            if not parts or parts[0] != p.id:
                _logger.error("Plugin %s template %s outside namespace — rejected", p.id, rel)
                violation = True
                break
            rel_str = str(rel)
            if rel_str in registered_tpl:
                _logger.error("Plugin %s template %s collides — rejected", p.id, rel_str)
                violation = True
                break
        if violation:
            continue
        for tpl_file in tpl_dir.rglob("*.html"):
            registered_tpl[str(tpl_file.relative_to(tpl_dir))] = p.id
        templates.env.loader.searchpath.append(str(tpl_dir))


def do_full_init(app_instance):
    """Run the full initialization sequence (DB + settings + plugins + scheduler).
    Called from lifespan when no encryption, or after login when encrypted.
    """
    _initialize_plugins(app_instance, "en")  # pre-load plugin models before init_db
    init_db()
    settings = _load_settings_into_i18n()

    # Sync locale and lan_access to auth config so they survive DB encryption
    from security import get_auth_config, save_auth_config
    _cfg = get_auth_config()
    if _cfg is not None:
        _cfg["locale"] = settings.locale
        _cfg["lan_access"] = settings.lan_access
        save_auth_config(_cfg)

    # Re-run plugin i18n with correct locale
    from plugins.manager import discover_plugins, load_plugin_i18n
    for p in discover_plugins():
        if p.enabled:
            try:
                load_plugin_i18n(p, settings.locale)
            except Exception:
                _logger.warning("Plugin %s i18n reload failed", p.id, exc_info=True)
    start_scheduler()
    app_instance.state.db_ready = True


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from security import is_db_encrypted, register_shutdown_encryption

    register_shutdown_encryption()

    if is_db_encrypted():
        # DB is encrypted — don't init anything, wait for login
        app.state.db_ready = False
        _logger.info("Database is encrypted — waiting for login")
        # Load locale from auth config so the login page is translated
        from security import get_auth_config
        _cfg = get_auth_config()
        if _cfg and "locale" in _cfg:
            set_locale(_cfg["locale"])
    else:
        # Normal startup
        do_full_init(app)

    yield

    # --- Shutdown ---
    if app.state.db_ready:
        shutdown_scheduler()

    # Re-encryption is handled by the atexit handler registered in
    # register_shutdown_encryption().  Doing it here as well would
    # double-encrypt (the second call encrypts the .enc file itself,
    # corrupting the archive).  We only rely on atexit.


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(title="Yfine", lifespan=lifespan)
app.state.db_ready = True  # default, overridden in lifespan if encrypted

# Middleware execution order: LocalhostOnly → Auth → CSRF → Session → App
# add_middleware() prepends, so we add in reverse execution order:
app.add_middleware(LocalhostOnlyPluginMiddleware)
app.add_middleware(AuthMiddleware)
from csrf import CSRFMiddleware
app.add_middleware(CSRFMiddleware)
from security import get_session_secret
app.add_middleware(RevocableSessionMiddleware, secret_key=get_session_secret())

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["_"] = get_translator()
templates.env.globals["flag"] = currency_flag
templates.env.filters["fdate"] = format_date
templates.env.globals["is_desktop"] = os.environ.get("YFINE_DESKTOP") == "1"
templates.env.globals["get_date_format"] = get_date_format
templates.env.globals["get_locale"] = get_locale
from i18n import get_theme, get_hide_net_worth, get_last_source_id, get_mobile_nav_mode
templates.env.globals["get_theme"] = get_theme
templates.env.globals["get_hide_net_worth"] = get_hide_net_worth
templates.env.globals["get_last_source_id"] = get_last_source_id
templates.env.globals["get_mobile_nav_mode"] = get_mobile_nav_mode

from plugins.registry import get_menu_items
templates.env.globals["plugin_menu_items"] = get_menu_items
templates.env.globals["cache_bust"] = str(int(time.time()))

def _get_csrf_token_from_request(request):
    """Get CSRF token from request.state (set by CSRFMiddleware)."""
    return getattr(getattr(request, "state", None), "csrf_token", "")
templates.env.globals["get_csrf_token"] = _get_csrf_token_from_request


# ---------------------------------------------------------------------------
# Auth routes  (login / logout)
# ---------------------------------------------------------------------------

@app.get("/login")
def login_page(request: Request):
    from security import is_password_set
    if not is_password_set():
        return RedirectResponse("/", status_code=302)
    if request.session.get("authenticated"):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


# ---------------------------------------------------------------------------
# Login rate limiting  (per-IP, in-memory)
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[float]] = defaultdict(list)
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _check_rate_limit(client_ip: str) -> int | None:
    """Return seconds until retry if rate-limited, else None."""
    now = time.time()
    attempts = _login_attempts[client_ip]
    # Prune old attempts
    _login_attempts[client_ip] = [t for t in attempts if now - t < _LOGIN_WINDOW_SECONDS]
    attempts = _login_attempts[client_ip]
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        oldest = attempts[0]
        return int(_LOGIN_WINDOW_SECONDS - (now - oldest)) + 1
    return None


def _record_attempt(client_ip: str):
    _login_attempts[client_ip].append(time.time())


@app.post("/api/auth/login")
async def api_login(request: Request):
    from security import (
        get_auth_config, verify_password, is_db_encrypted,
        decrypt_db_file, set_runtime_password,
    )

    client_ip = request.client.host if request.client else "unknown"
    retry_after = _check_rate_limit(client_ip)
    if retry_after is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Too many login attempts. Try again in {retry_after}s."},
            headers={"Retry-After": str(retry_after)},
        )

    body = await request.json()
    password = body.get("password", "")

    config = get_auth_config()
    if not config or not config.get("password_hash"):
        return JSONResponse(status_code=400, content={"detail": "No password set"})

    if not verify_password(password, config["password_hash"], config["password_salt"]):
        _record_attempt(client_ip)
        return JSONResponse(status_code=401, content={"detail": get_translator()("login_wrong_password")})

    # Successful login — clear attempts for this IP
    _login_attempts.pop(client_ip, None)

    # Decrypt DB and initialize if this is the first login since startup
    if not getattr(app.state, "db_ready", False):
        if is_db_encrypted():
            if not decrypt_db_file(password):
                return JSONResponse(status_code=500, content={"detail": get_translator()("login_decrypt_failed")})
        do_full_init(app)

    set_runtime_password(password)
    request.session["authenticated"] = True
    return {"ok": True}


@app.post("/api/auth/logout")
async def api_logout(request: Request):
    request.session.clear()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback as _tb
    tb_str = _tb.format_exc()
    _logger.error(
        "Unhandled exception on %s %s\n%s",
        request.method, request.url.path, tb_str,
    )
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
    return templates.TemplateResponse(
        "error.html",
        {
            "request": request,
            "error": "An unexpected error occurred",
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": tb_str,
        },
        status_code=500,
    )


# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------
from routers import pages, sources, movements, tags, recurring, notifications, data, settings, whims, savings, exchange_rates, portfolios, imports, goals  # noqa: E402
from routers import plugins as plugins_router  # noqa: E402

app.include_router(pages.router)
app.include_router(sources.router)
app.include_router(movements.router)
app.include_router(tags.router)
app.include_router(recurring.router)
app.include_router(notifications.router)
app.include_router(data.router)
app.include_router(settings.router)
app.include_router(whims.router)
app.include_router(savings.router)
app.include_router(goals.router)
app.include_router(exchange_rates.router)
app.include_router(portfolios.router)
app.include_router(imports.router)
app.include_router(plugins_router.router)
