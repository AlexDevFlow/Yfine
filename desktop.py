"""Launch Yfine as a desktop application."""

import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
import traceback

# Set desktop flag BEFORE importing the app so templates can detect it
os.environ["YFINE_DESKTOP"] = "1"

# Log to file so errors are visible even with --windowed
from database import DATA_DIR

_log_file = DATA_DIR / "yfine.log"
logging.basicConfig(
    filename=str(_log_file),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_logger = logging.getLogger("desktop")

import uvicorn
import webview

from main import app


DEFAULT_PORT = 8000


def _get_preferred_port() -> int:
    """Read user-configured port from auth config, or use default."""
    try:
        from security import get_auth_config
        config = get_auth_config()
        if config and "port" in config:
            return int(config["port"])
    except Exception:
        pass
    return DEFAULT_PORT


def _is_port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False


def find_free_port(host: str = "127.0.0.1") -> int:
    preferred = _get_preferred_port()
    if _is_port_available(host, preferred):
        return preferred
    _logger.warning("Port %d is busy, finding a free one", preferred)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


_server_error = None


def _get_lan_access() -> bool:
    """Read lan_access — first from auth config (works even when DB is encrypted),
    then fall back to DB."""
    # 1. Try auth config file (always available)
    try:
        from security import get_auth_config
        config = get_auth_config()
        if config is not None and "lan_access" in config:
            val = bool(config["lan_access"])
            _logger.info("lan_access from auth config = %s", val)
            return val
    except Exception:
        _logger.warning("Failed to read lan_access from auth config", exc_info=True)

    # 2. Fall back to DB
    try:
        from sqlmodel import Session
        from database import engine
        from services.settings import get_settings
        with Session(engine) as session:
            settings = get_settings(session)
            _logger.info("lan_access from DB = %s", settings.lan_access)
            return settings.lan_access
    except Exception as e:
        _logger.error("Failed to read lan_access: %s", e)
        return False


def start_server(port: int):
    global _server_error
    try:
        lan = _get_lan_access()
        host = "0.0.0.0" if lan else "127.0.0.1"
        _logger.info("Starting uvicorn on %s:%d (LAN=%s)", host, port, lan)
        uvicorn.run(app, host=host, port=port, log_level="warning")
    except Exception as e:
        _server_error = traceback.format_exc()
        _logger.error("Server failed to start:\n%s", _server_error)


def wait_for_server(port: int, timeout: float = 30.0):
    start = time.time()
    while time.time() - start < timeout:
        if _server_error:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class Api:
    def __init__(self, win, server_port):
        self._window = win
        self._port = server_port

    def save_export(self, mode="core"):
        """Run export via the service layer and save via native file dialog."""
        from sqlmodel import Session
        from database import engine
        from services import data as data_service

        with Session(engine) as session:
            if mode == "all":
                data = data_service.export_archive(session)
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename="yfine-export-full.yfine",
                    file_types=("Yfine Archive (*.yfine)",),
                )
                if result:
                    path = result if isinstance(result, str) else result[0]
                    with open(path, "wb") as f:
                        f.write(data)
                    return True
            else:
                payload = data_service.export_all(session, mode=mode)
                result = self._window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename="yfine-export.json",
                    file_types=("JSON Files (*.json)",),
                )
                if result:
                    path = result if isinstance(result, str) else result[0]
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, default=str, ensure_ascii=False)
                    return True
        return False

    def save_excel_export(self, sections):
        """Run Excel export via the service layer and save via native file dialog."""
        from sqlmodel import Session
        from database import engine
        from services.excel_export import export_excel, EXPORTABLE_SECTIONS

        selected = [s.strip() for s in sections.split(",") if s.strip() in EXPORTABLE_SECTIONS]
        with Session(engine) as session:
            data = export_excel(session, selected)

        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="yfine-export.xlsx",
            file_types=("Excel Files (*.xlsx)",),
        )
        if result:
            path = result if isinstance(result, str) else result[0]
            with open(path, "wb") as f:
                f.write(data)
            return True
        return False

    def save_pdf_export(self, sections):
        """Run PDF export via the service layer and save via native file dialog."""
        from sqlmodel import Session
        from database import engine
        from services.pdf_export import export_pdf, EXPORTABLE_SECTIONS

        selected = [s.strip() for s in sections.split(",") if s.strip() in EXPORTABLE_SECTIONS]
        with Session(engine) as session:
            data = export_pdf(session, selected)

        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="yfine-report.pdf",
            file_types=("PDF Files (*.pdf)",),
        )
        if result:
            path = result if isinstance(result, str) else result[0]
            with open(path, "wb") as f:
                f.write(data)
            return True
        return False

    def open_external(self, url):
        """Open a URL in the system's default browser rather than the pywebview
        window. Accepts absolute URLs (http/https) or app-relative paths like
        `/api/movements/attachments/42` — relative paths get the local server
        prefix so the system browser can fetch them.
        """
        import webbrowser

        if not isinstance(url, str) or not url:
            return False
        if url.startswith("/"):
            url = f"http://127.0.0.1:{self._port}{url}"
        elif not (url.startswith("http://") or url.startswith("https://")):
            # Reject unusual schemes (javascript:, file:, data:) to avoid the
            # attachment link being abused for local file access.
            return False
        try:
            webbrowser.open(url, new=2)  # new=2 → new tab if possible
            return True
        except Exception:
            _logger.exception("open_external failed for %s", url)
            return False

    def save_logs(self):
        """Save the Yfine log file via native file dialog."""
        if not _log_file.exists():
            return False
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="yfine.log",
            file_types=("Log Files (*.log)", "All Files (*.*)"),
        )
        if not result:
            return False
        path = result if isinstance(result, str) else result[0]
        try:
            with open(_log_file, "rb") as src, open(path, "wb") as dst:
                dst.write(src.read())
            return True
        except OSError:
            _logger.exception("save_logs copy failed")
            return False


if __name__ == "__main__":
    multiprocessing.freeze_support()

    _logger.info("Yfine desktop starting (frozen=%s)", getattr(sys, "frozen", False))

    port = find_free_port()

    server_thread = threading.Thread(target=start_server, args=(port,), daemon=True)
    server_thread.start()

    # Show a loading screen immediately, navigate once the server is up
    window = webview.create_window(
        "Yfine",
        html="<html><body style='background:#f5f5f9;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-family:sans-serif;color:#697a8d'><div style='text-align:center'><svg width='64' height='64' viewBox='0 0 32 32' fill='none' xmlns='http://www.w3.org/2000/svg'><rect width='32' height='32' rx='8' fill='#696CFF'/><path d='M8 8L14.5 18V25H17.5V18L24 8H20.5L16 16L11.5 8H8Z' fill='white'/></svg><p>Loading...</p></div></body></html>",
        width=1280,
        height=820,
        min_size=(800, 600),
    )

    def on_loaded():
        if wait_for_server(port):
            window.load_url(f"http://127.0.0.1:{port}")
        else:
            err = _server_error or "Server did not start in time."
            _logger.error("Failed to connect: %s", err)
            window.load_html(
                f"<html><body style='background:#f5f5f9;padding:2em;font-family:sans-serif;color:#697a8d'>"
                f"<h2>Yfine failed to start</h2>"
                f"<pre style='white-space:pre-wrap;background:#fff;padding:1em;border-radius:8px'>{err}</pre>"
                f"<p>Log file: {_log_file}</p></body></html>"
            )

    api = Api(window, port)
    window.expose(api.save_export)
    window.expose(api.save_excel_export)
    window.expose(api.save_pdf_export)
    window.expose(api.open_external)
    window.expose(api.save_logs)

    threading.Thread(target=on_loaded, daemon=True).start()
    # Force Qt backend on Windows/Linux to avoid pywebview's WinForms path
    # (pythonnet/clr_loader fails to init inside PyInstaller bundles). macOS
    # keeps its native Cocoa/WebKit backend via pyobjc.
    _gui = None if sys.platform == "darwin" else "qt"
    webview.start(gui=_gui)
