import importlib
import importlib.util
import json
import logging
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator

from plugins.registry import PluginInfo, register_plugin, unregister_plugin, get_plugin
from plugins.state import is_plugin_enabled, remove_plugin_state, set_plugin_enabled

from database import DATA_DIR

_logger = logging.getLogger(__name__)

# When frozen, plugins are installed to the writable data directory.
# When running from source, use the project-local plugins/installed/ directory.
PLUGINS_DIR = DATA_DIR / "plugins" / "installed" if getattr(sys, "frozen", False) else Path(__file__).parent / "installed"
MAX_UNCOMPRESSED_SIZE = 200 * 1024 * 1024  # 200 MB

_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

_RESERVED_IDS = frozenset({
    "core", "api", "static", "templates", "plugins", "app",
    "database", "admin", "auth", "settings", "system",
    "yfine", "installed", "scheduler", "i18n",
})


class PluginManifest(BaseModel):
    """Strict schema for plugin manifest.json."""
    model_config = {"extra": "forbid", "strict": True}

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    icon: str = "bx bx-plug"
    menu_label: str | None = None
    url: str | None = None
    has_models: bool = False
    has_routes: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _PLUGIN_ID_RE.match(v):
            raise ValueError(
                f"Invalid plugin ID '{v}': must be lowercase alphanumeric "
                "with underscores, starting with a letter, 2-64 characters"
            )
        if v in _RESERVED_IDS:
            raise ValueError(f"Plugin ID '{v}' is reserved and cannot be used")
        return v

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        if not re.match(r"^\d+\.\d+(\.\d+)?(-[\w.]+)?$", v):
            raise ValueError(f"Invalid version '{v}': expected semver format (e.g. 1.0.0)")
        return v


def _load_manifest(plugin_dir: Path) -> dict:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"No manifest.json found in {plugin_dir.name}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_plugin_id(plugin_id: str) -> None:
    """Ensure plugin ID is a safe identifier (lowercase alnum + underscores, 2-64 chars)."""
    if not _PLUGIN_ID_RE.match(plugin_id):
        raise ValueError(
            f"Invalid plugin ID '{plugin_id}': must be lowercase alphanumeric "
            "with underscores, starting with a letter, 2-64 characters"
        )
    if plugin_id in _RESERVED_IDS:
        raise ValueError(f"Plugin ID '{plugin_id}' is reserved and cannot be used")


def _manifest_to_info(manifest: dict, plugin_dir: Path) -> PluginInfo:
    parsed = PluginManifest(**manifest)
    return PluginInfo(
        id=parsed.id,
        name=parsed.name,
        version=parsed.version,
        description=parsed.description,
        author=parsed.author,
        path=plugin_dir,
        icon=parsed.icon,
        menu_label=parsed.menu_label or parsed.id,
        url=parsed.url or f"/{parsed.id.replace('_', '-')}",
        has_models=parsed.has_models,
        has_routes=parsed.has_routes,
    )


def discover_plugins() -> list[PluginInfo]:
    """Scan installed plugins directory and return PluginInfo list."""
    if not PLUGINS_DIR.exists():
        PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
        return []

    plugins = []
    for item in sorted(PLUGINS_DIR.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        try:
            manifest = _load_manifest(item)
            info = _manifest_to_info(manifest, item)
            info.enabled = is_plugin_enabled(info.id)
            register_plugin(info)
            plugins.append(info)
        except Exception as e:
            _logger.warning("Failed to load plugin %s: %s", item.name, e)
    return plugins


def _import_module_from_path(module_name: str, file_path: Path):
    """Import a Python module from an arbitrary file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_plugin_models(plugin: PluginInfo):
    """Import plugin's models.py so SQLModel registers the tables."""
    models_path = plugin.path / "models.py"
    if models_path.exists():
        _import_module_from_path(f"plugins.installed.{plugin.id}.models", models_path)


def load_plugin_routes(plugin: PluginInfo):
    """Import plugin's routes.py and return the FastAPI router."""
    routes_path = plugin.path / "routes.py"
    if not routes_path.exists():
        return None
    module = _import_module_from_path(f"plugins.installed.{plugin.id}.routes", routes_path)
    router = getattr(module, "router", None)
    if router is None:
        raise ValueError(f"Plugin {plugin.id} routes.py has no 'router' attribute")
    return router


def load_plugin_i18n(plugin: PluginInfo, locale: str):
    """Load plugin locale file and merge into app translations."""
    from i18n import merge_translations

    locale_dir = plugin.path / "locales"
    if not locale_dir.exists():
        return

    # Try requested locale first, fall back to en
    for loc in [locale, "en"]:
        locale_file = locale_dir / f"{loc}.json"
        if locale_file.exists():
            with open(locale_file, "r", encoding="utf-8") as f:
                extra = json.load(f)
            merge_translations(extra)
            return


def _safe_extract_path(zip_path: str, dest: Path) -> Path:
    """Prevent zip-slip: ensure extracted path stays within dest."""
    resolved = (dest / zip_path).resolve()
    if not str(resolved).startswith(str(dest.resolve())):
        raise ValueError(f"Zip entry {zip_path} would escape target directory")
    return resolved


def safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip safely: validate paths, reject symlinks, stream-check size."""
    dest.mkdir(parents=True, exist_ok=True)
    cumulative_size = 0

    for info in zf.infolist():
        # Reject symlinks (F-10)
        unix_attrs = info.external_attr >> 16
        if unix_attrs and (unix_attrs & 0o170000) == stat.S_IFLNK:
            raise ValueError(f"Zip contains symlink: {info.filename}")

        # Validate path doesn't escape destination (F-05)
        target = _safe_extract_path(info.filename, dest)

        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue

        # Quick reject using declared size (may lie, but catches obvious bombs)
        cumulative_size += info.file_size
        if cumulative_size > MAX_UNCOMPRESSED_SIZE:
            raise ValueError(
                f"Zip uncompressed size exceeds limit "
                f"({MAX_UNCOMPRESSED_SIZE / 1024 / 1024:.0f} MB) — possible zip bomb"
            )

        # Stream-extract and count actual bytes written
        target.parent.mkdir(parents=True, exist_ok=True)
        actual_bytes = 0
        with zf.open(info) as src, open(target, "wb") as dst:
            while True:
                chunk = src.read(65536)
                if not chunk:
                    break
                actual_bytes += len(chunk)
                if cumulative_size - info.file_size + actual_bytes > MAX_UNCOMPRESSED_SIZE:
                    dst.close()
                    target.unlink(missing_ok=True)
                    raise ValueError(
                        "Zip actual uncompressed size exceeds limit — possible zip bomb"
                    )
                dst.write(chunk)

        # Update cumulative with actual bytes (may differ from declared)
        cumulative_size = cumulative_size - info.file_size + actual_bytes


def _strip_bytecode(directory: Path) -> None:
    """Remove __pycache__ dirs and .pyc/.pyo files from a plugin directory."""
    for cache_dir in list(directory.rglob("__pycache__")):
        shutil.rmtree(cache_dir, ignore_errors=True)
    for pyc in list(directory.rglob("*.pyc")):
        pyc.unlink(missing_ok=True)
    for pyo in list(directory.rglob("*.pyo")):
        pyo.unlink(missing_ok=True)


_NATIVE_EXTENSIONS = (".so", ".pyd", ".dll", ".dylib")


def _reject_native_extensions(directory: Path) -> None:
    """Raise if any compiled native extension files are found."""
    for ext in _NATIVE_EXTENSIONS:
        found = list(directory.rglob(f"*{ext}"))
        if found:
            names = ", ".join(str(f.relative_to(directory)) for f in found[:5])
            raise ValueError(
                f"Plugin contains native compiled extension(s): {names} "
                "— these cannot be analyzed and are not allowed"
            )


def _reject_orphan_bytecode(directory: Path) -> None:
    """Raise if any .pyc exists without a corresponding .py source file."""
    for pyc in directory.rglob("*.pyc"):
        # Standard layout: __pycache__/foo.cpython-311.pyc → ../foo.py
        stem = pyc.stem.split(".")[0]  # e.g. "foo" from "foo.cpython-311"
        parent_of_cache = pyc.parent.parent if pyc.parent.name == "__pycache__" else pyc.parent
        if not (parent_of_cache / f"{stem}.py").exists():
            raise ValueError(
                f"Compiled file {pyc.relative_to(directory)} has no matching "
                f".py source — this may be an attempt to bypass the security scanner"
            )


def install_plugin(zip_data: bytes, *, _scanned: bool = False) -> PluginInfo:
    """Extract plugin zip, validate, and install to plugins/installed/.

    When called via the API router, _scanned=True indicates the plugin was
    already scanned and the user reviewed the report. When called directly
    (e.g. from a script), an inline scan runs as a safety net.
    """
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "plugin.zip"
        zip_path.write_bytes(zip_data)

        if not zipfile.is_zipfile(zip_path):
            raise ValueError("Uploaded file is not a valid zip archive")

        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extractall(zf, tmp_path / "extracted")

        # Find the plugin directory (must be exactly one)
        extracted = tmp_path / "extracted"
        dirs = [d for d in extracted.iterdir() if d.is_dir()]
        if len(dirs) != 1:
            raise ValueError("Zip must contain exactly one plugin directory")

        plugin_dir = dirs[0]

        # Reject orphan bytecode and native extensions before stripping
        _reject_orphan_bytecode(plugin_dir)
        _reject_native_extensions(plugin_dir)

        # Strip all compiled bytecode — force source-only install
        _strip_bytecode(plugin_dir)

        # Validate manifest
        manifest = _load_manifest(plugin_dir)
        info = _manifest_to_info(manifest, plugin_dir)

        # Safety net: run an inline scan if caller didn't go through the API scan flow
        if not _scanned:
            _logger.warning(
                "install_plugin() called without prior scan — running inline scan"
            )
            from plugins.scanner import scan_plugin
            report = scan_plugin(plugin_dir, info.id)
            if report.critical_count > 0:
                raise ValueError(
                    f"Plugin has {report.critical_count} critical security finding(s). "
                    "Scan and confirm via the API before installing."
                )

        # Check for conflicts
        target = PLUGINS_DIR / info.id
        if target.exists():
            raise ValueError(
                f"Plugin '{info.id}' is already installed. "
                "Uninstall it first or use update."
            )

        # Copy to installed directory
        shutil.copytree(plugin_dir, target)
        info.path = target

        # New plugins start disabled — user must explicitly enable
        set_plugin_enabled(info.id, False)

    return info


def create_plugin_zip(plugin_id: str) -> bytes:
    """Create an in-memory ZIP of an installed plugin directory (for export)."""
    _validate_plugin_id(plugin_id)
    target = PLUGINS_DIR / plugin_id
    if not target.exists():
        raise ValueError(f"Plugin '{plugin_id}' is not installed")

    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(target.rglob("*")):
            if "__pycache__" in file_path.parts:
                continue
            if file_path.is_file():
                arcname = str(Path(plugin_id) / file_path.relative_to(target))
                zf.write(file_path, arcname)
    return buf.getvalue()


def uninstall_plugin(plugin_id: str) -> bool:
    """Remove plugin directory. Does NOT drop DB tables."""
    _validate_plugin_id(plugin_id)
    target = PLUGINS_DIR / plugin_id
    if not target.exists():
        return False
    shutil.rmtree(target)
    unregister_plugin(plugin_id)
    remove_plugin_state(plugin_id)
    return True


def update_plugin(zip_data: bytes, *, _scanned: bool = False) -> PluginInfo:
    """Uninstall old version and install new one from zip.

    Backs up the old plugin first; if install fails, the backup is restored.
    """
    # Peek at manifest to get plugin id
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "plugin.zip"
        zip_path.write_bytes(zip_data)

        with zipfile.ZipFile(zip_path, "r") as zf:
            safe_extractall(zf, tmp_path / "extracted")

        extracted = tmp_path / "extracted"
        dirs = [d for d in extracted.iterdir() if d.is_dir()]
        if len(dirs) != 1:
            raise ValueError("Zip must contain exactly one plugin directory")

        manifest = _load_manifest(dirs[0])
        plugin_id = manifest.get("id")
        if plugin_id:
            _validate_plugin_id(plugin_id)

        # Backup old plugin before removing it
        old_dir = PLUGINS_DIR / plugin_id if plugin_id else None
        backup_dir = tmp_path / "backup"
        has_backup = False

        if old_dir and old_dir.exists():
            shutil.copytree(old_dir, backup_dir)
            has_backup = True

        if plugin_id:
            uninstall_plugin(plugin_id)

        try:
            return install_plugin(zip_data, _scanned=_scanned)
        except Exception:
            # Restore from backup on failure
            if has_backup and old_dir:
                shutil.copytree(backup_dir, old_dir)
                # Re-register the old plugin in the registry
                try:
                    old_manifest = _load_manifest(old_dir)
                    old_info = _manifest_to_info(old_manifest, old_dir)
                    register_plugin(old_info)
                except Exception as restore_err:
                    _logger.error(
                        "Failed to re-register plugin %s after update rollback: %s",
                        plugin_id, restore_err,
                    )
            raise
