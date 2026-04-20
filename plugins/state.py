"""
Persistent plugin state (enabled/disabled) stored as a simple JSON file.

No DB dependency — the state file lives alongside the installed plugins.
"""

import contextlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from database import DATA_DIR

_logger = logging.getLogger(__name__)

_PLUGIN_DATA = DATA_DIR / "plugins"
_STATE_FILE = _PLUGIN_DATA / "plugin_state.json"
_LOCK_FILE = _PLUGIN_DATA / ".plugin_state.lock"


@contextlib.contextmanager
def _state_lock():
    """Exclusive file lock to prevent concurrent read-modify-write races."""
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import msvcrt
        with open(_LOCK_FILE, "w") as lock_fd:
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        with open(_LOCK_FILE, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)


def _read_state() -> dict[str, bool] | None:
    """Read plugin state. Returns None on corruption (callers should default to safe)."""
    if not _STATE_FILE.exists():
        return {}
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _logger.warning(
            "Plugin state file is corrupt or unreadable (%s) — "
            "all plugins will default to DISABLED for safety", e,
        )
        return None


def _write_state(state: dict[str, bool]) -> None:
    """Write state atomically: temp file then os.replace()."""
    parent = _STATE_FILE.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, _STATE_FILE)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def is_plugin_enabled(plugin_id: str) -> bool:
    """Return whether a plugin is enabled (defaults to True, or False if state is corrupt)."""
    state = _read_state()
    if state is None:
        return False
    return state.get(plugin_id, False)


def set_plugin_enabled(plugin_id: str, enabled: bool) -> None:
    """Persist the enabled state for a plugin."""
    with _state_lock():
        state = _read_state() or {}
        state[plugin_id] = enabled
        _write_state(state)


def remove_plugin_state(plugin_id: str) -> None:
    """Remove state entry when a plugin is uninstalled."""
    with _state_lock():
        state = _read_state() or {}
        state.pop(plugin_id, None)
        _write_state(state)


def auto_disable_plugin(plugin_id: str) -> None:
    """Disable a plugin that failed to load, preventing repeated crashes on restart."""
    _logger.warning(
        "Auto-disabling plugin %s after load failure — "
        "re-enable manually via settings after fixing the issue",
        plugin_id,
    )
    set_plugin_enabled(plugin_id, False)
