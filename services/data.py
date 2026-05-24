import io
import json
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

from packaging.version import Version, InvalidVersion
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, select

from models.budget import Budget
from models.exchange_rate import ExchangeRate
from models.goal import Goal, GoalAllocation
from models.movement import Movement, MovementAttachment, MovementTag
from models.notification import Notification
from models.portfolio import Holding, HoldingPriceSnapshot, Portfolio
from models.recurring import RecurringItem
from models.saving import Saving, SavingTag
from models.setting import Setting
from models.source import Source
from models.tag import Tag
from models.whim import Whim

# Core tables in dependency order (parents first for insert; reverse for delete).
# Keep this list complete — every SQLModel core table must appear here, otherwise
# export/reset silently skip it and it gets misclassified as a plugin table
# (which breaks reset with FK errors and corrupts full-archive restores).
_CORE_TABLES_INSERT_ORDER = [
    ("sources", Source),
    ("tags", Tag),
    ("exchange_rates", ExchangeRate),
    ("movements", Movement),
    ("movement_tag", MovementTag),
    ("movement_attachments", MovementAttachment),
    ("recurring_items", RecurringItem),
    ("notifications", Notification),
    ("settings", Setting),
    ("whims", Whim),
    ("budgets", Budget),
    ("portfolios", Portfolio),
    ("holdings", Holding),
    ("holding_price_snapshots", HoldingPriceSnapshot),
    ("goals", Goal),
    ("goal_allocations", GoalAllocation),
    ("savings", Saving),
    ("saving_tag", SavingTag),
]

# Per-table date/datetime field specs for import parsing (ISO strings → objects).
# datetime_mode=True means a model's "date_fields" are actually datetimes.
_TABLE_FIELD_SPECS: dict[str, dict] = {
    "sources": {"date_fields": ["created_at", "updated_at"], "datetime_mode": True},
    "tags": {"date_fields": ["created_at", "updated_at"], "datetime_mode": True},
    "exchange_rates": {"datetime_fields": ["updated_at"]},
    "movements": {"date_fields": ["date"], "datetime_fields": ["created_at", "updated_at"]},
    "movement_tag": {},
    "movement_attachments": {"datetime_fields": ["created_at"]},
    "recurring_items": {
        "date_fields": ["start_date", "end_date", "next_due_date", "last_fired_date", "last_alert_date"],
        "datetime_fields": ["created_at", "updated_at"],
    },
    "notifications": {"datetime_fields": ["created_at"]},
    "settings": {"datetime_fields": ["created_at", "updated_at"]},
    "whims": {"datetime_fields": ["created_at", "updated_at", "purchased_at"]},
    "budgets": {"date_fields": ["start_date"], "datetime_fields": ["created_at", "updated_at"]},
    "portfolios": {"datetime_fields": ["created_at", "updated_at"]},
    "holdings": {"datetime_fields": ["created_at", "updated_at", "last_price_at"]},
    "holding_price_snapshots": {"date_fields": ["date"], "datetime_fields": ["created_at"]},
    "goals": {"date_fields": ["target_date"], "datetime_fields": ["created_at", "updated_at"]},
    "goal_allocations": {"date_fields": ["date"], "datetime_fields": ["created_at"]},
    "savings": {"date_fields": ["date"], "datetime_fields": ["created_at", "updated_at"]},
    "saving_tag": {},
}

_CORE_TABLE_NAMES = {name for name, _ in _CORE_TABLES_INSERT_ORDER}


def _serialize_date(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


def _to_dict(obj):
    d = {}
    for key, value in obj.__dict__.items():
        if key.startswith("_"):
            continue
        d[key] = _serialize_date(value)
    return d


def _get_plugin_tables(session: Session) -> list[str]:
    """Return table names in the DB that are not core tables."""
    inspector = inspect(session.bind)
    all_tables = set(inspector.get_table_names())
    return sorted(all_tables - _CORE_TABLE_NAMES - {"alembic_version"})


def _validate_identifier(name: str) -> str:
    """Validate that a name is a safe SQL identifier (alphanumeric + underscore)."""
    import re
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _export_raw_table(session: Session, table_name: str) -> list[dict]:
    """Export all rows from a table as dicts using raw SQL."""
    safe_name = _validate_identifier(table_name)
    result = session.exec(text(f'SELECT * FROM "{safe_name}"'))
    columns = result.keys()
    rows = []
    for row in result.fetchall():
        rows.append({
            col: _serialize_date(val)
            for col, val in zip(columns, row)
        })
    return rows


def export_all(session: Session, mode: str = "core") -> dict:
    """Export data. mode='core' for native only, 'all' to include plugin tables."""
    data = {}
    for table_name, model_cls in _CORE_TABLES_INSERT_ORDER:
        items = session.exec(select(model_cls)).all()
        data[table_name] = [_to_dict(item) for item in items]

    if mode == "all":
        plugin_tables = _get_plugin_tables(session)
        if plugin_tables:
            data["_plugin_tables"] = {}
            for table_name in plugin_tables:
                data["_plugin_tables"][table_name] = _export_raw_table(session, table_name)

    data["_export_mode"] = mode
    return data


def reset_all_data(session: Session) -> None:
    """Delete all user data (sources, movements, tags, recurring, savings, whims,
    notifications, budgets, portfolios, exchange rates, …).

    User preferences (settings) and plugin tables are preserved. Default tags are
    re-seeded after the wipe so the app looks like a fresh install. Tables are
    wiped children-first (reverse dependency order) so foreign-key constraints
    hold — driven by _CORE_TABLES_INSERT_ORDER so a new model is never missed.
    """
    from services.attachments import attachment_path as _att_path

    # Remove attachment files from disk first; their rows are dropped in the loop.
    for att in session.exec(select(MovementAttachment)).all():
        p = _att_path(att)
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass

    for table_name, model_cls in reversed(_CORE_TABLES_INSERT_ORDER):
        if table_name == "settings":
            continue  # user preferences survive a reset
        for row in session.exec(select(model_cls)).all():
            session.delete(row)
    session.commit()

    # Re-seed default tags (opens its own session, safe after commit)
    from database import _seed_default_tags
    _seed_default_tags()


def import_all(session: Session, data: dict) -> None:
    """Import data. Handles both core-only and full exports.

    Wipes every core table then re-inserts from `data`, all in one transaction so
    a failure rolls the whole thing back (no half-imported state). Tables are
    deleted children-first and inserted parents-first, both driven by
    _CORE_TABLES_INSERT_ORDER so a newly added model is never silently skipped.
    """
    # Delete core data, children first (reverse dependency order).
    # (Attachment files on disk are handled separately during archive import.)
    for table_name, model_cls in reversed(_CORE_TABLES_INSERT_ORDER):
        for row in session.exec(select(model_cls)).all():
            session.delete(row)
    session.flush()

    # Defer FK checks to COMMIT for the rest of this transaction. Transfer
    # movements reference each other (movements.transfer_pair_id forms a cycle),
    # so no row-by-row insert order can satisfy immediate FK enforcement —
    # without this, restoring any backup containing a transfer fails. Must be set
    # while a transaction is already active (the deletes above started one),
    # otherwise it runs in autocommit and resets immediately. SQLite clears it on
    # the next COMMIT, by which point every referenced row exists.
    session.exec(text("PRAGMA defer_foreign_keys=ON"))

    # Re-insert core data, parents first. Flush after each table so every parent
    # row is persisted before the next (child) table references it under FK ON.
    for table_name, model_cls in _CORE_TABLES_INSERT_ORDER:
        _import_model(session, data, table_name, model_cls,
                      **_TABLE_FIELD_SPECS.get(table_name, {}))
        session.flush()

    # Import plugin tables if present
    plugin_tables = data.get("_plugin_tables", {})
    if plugin_tables:
        inspector = inspect(session.bind)
        existing_tables = set(inspector.get_table_names())
        for table_name, rows in plugin_tables.items():
            if table_name not in existing_tables:
                continue  # Table doesn't exist (plugin not installed), skip
            # Validate table name is a safe identifier
            safe_table = _validate_identifier(table_name)
            # Get valid column names from the actual table schema
            valid_columns = {c["name"] for c in inspector.get_columns(safe_table)}
            # Clear existing data
            session.exec(text(f'DELETE FROM "{safe_table}"'))
            # Insert rows
            for row in rows:
                # Only use columns that actually exist in the table
                safe_row = {k: v for k, v in row.items() if k in valid_columns}
                if not safe_row:
                    continue
                for col_name in safe_row:
                    _validate_identifier(col_name)
                cols = ", ".join(f'"{k}"' for k in safe_row.keys())
                placeholders = ", ".join(f":{k}" for k in safe_row.keys())
                session.exec(
                    text(f'INSERT INTO "{safe_table}" ({cols}) VALUES ({placeholders})'),
                    params=safe_row,
                )

    session.commit()


def _import_model(session: Session, data: dict, key: str, model_cls,
                  date_fields: list[str] | None = None,
                  datetime_fields: list[str] | None = None,
                  datetime_mode: bool = False):
    """Import rows for a model, handling date/datetime parsing."""
    for row_data in data.get(key, []):
        row_data.pop("_sa_instance_state", None)
        # Parse date fields
        for field in (date_fields or []):
            if field in row_data and isinstance(row_data[field], str):
                if datetime_mode:
                    row_data[field] = datetime.fromisoformat(row_data[field])
                else:
                    row_data[field] = date.fromisoformat(row_data[field])
        # Parse datetime fields
        for field in (datetime_fields or []):
            if field in row_data and isinstance(row_data[field], str):
                row_data[field] = datetime.fromisoformat(row_data[field])
        session.add(model_cls(**row_data))


# ---------------------------------------------------------------------------
# .yfine archive (ZIP) — full export/import with plugin packages
# ---------------------------------------------------------------------------


def _compare_versions(v1: str, v2: str) -> str:
    """Compare two version strings. Returns 'newer', 'older', or 'same'."""
    try:
        a, b = Version(v1), Version(v2)
    except InvalidVersion:
        # Fallback: plain string comparison
        if v1 == v2:
            return "same"
        return "newer" if v1 > v2 else "older"
    if a > b:
        return "newer"
    if a < b:
        return "older"
    return "same"


def export_archive(session: Session) -> bytes:
    """Export all data + installed plugin packages as a .yfine ZIP archive."""
    from plugins.manager import create_plugin_zip
    from plugins.registry import get_all_plugins

    # 1. Core + plugin table data
    data = export_all(session, mode="all")

    # 2. Collect plugin metadata
    plugins = get_all_plugins()
    manifest = {
        "format": "yfine-archive",
        "version": 1,
        "created_at": datetime.utcnow().isoformat(),
        "plugins": [
            {
                "id": p.id,
                "name": p.name,
                "version": p.version,
                "has_models": p.has_models,
            }
            for p in plugins
        ],
    }

    # 3. Build the ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("data.json", json.dumps(data, indent=2, default=str))
        for p in plugins:
            plugin_zip_bytes = create_plugin_zip(p.id)
            zf.writestr(f"plugins/{p.id}.zip", plugin_zip_bytes)
        # 4. Bundle movement attachment files so the archive is self-contained
        from services.attachments import attachment_path as _att_path
        for att in session.exec(select(MovementAttachment)).all():
            src = _att_path(att)
            if src.exists():
                try:
                    zf.write(src, arcname=f"attachments/{att.stored_name}")
                except OSError:
                    pass

    return buf.getvalue()


def preview_archive(archive_bytes: bytes) -> dict:
    """Parse a .yfine archive and return a preview of what will happen on import."""
    from plugins.manager import safe_extractall, PLUGINS_DIR
    from plugins.registry import get_plugin
    from plugins.scanner import scan_plugin

    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != "yfine-archive":
            raise ValueError("Invalid archive: missing yfine-archive format marker")

        data = json.loads(zf.read("data.json"))

        # Core table record counts
        core_tables = {}
        for table_name, _ in _CORE_TABLES_INSERT_ORDER:
            core_tables[table_name] = len(data.get(table_name, []))

        # Plugin analysis
        plugins_preview = []
        requires_restart = False

        for plugin_meta in manifest.get("plugins", []):
            pid = plugin_meta["id"]
            archive_ver = plugin_meta["version"]
            has_models = plugin_meta.get("has_models", False)

            installed = get_plugin(pid)
            installed_ver = installed.version if installed else None
            plugin_dir_exists = (PLUGINS_DIR / pid).exists()

            # Determine action
            if installed:
                cmp = _compare_versions(archive_ver, installed_ver)
                if cmp == "same":
                    action = "skip"
                elif cmp == "newer":
                    action = "update"
                else:
                    action = "skip"  # installed is newer, keep it
            elif plugin_dir_exists:
                action = "reinstall"
            else:
                action = "install"

            # Run security scan on plugins that will be installed/updated
            scan_report = None
            if action in ("install", "update", "reinstall"):
                requires_restart = True
                plugin_zip_name = f"plugins/{pid}.zip"
                if plugin_zip_name in zf.namelist():
                    plugin_zip_bytes = zf.read(plugin_zip_name)
                    with tempfile.TemporaryDirectory() as tmp:
                        tmp_path = Path(tmp)
                        with zipfile.ZipFile(io.BytesIO(plugin_zip_bytes), "r") as pzf:
                            safe_extractall(pzf, tmp_path)
                        # Find the plugin directory inside extracted
                        dirs = [d for d in tmp_path.iterdir() if d.is_dir()]
                        if dirs:
                            scan_report = scan_plugin(dirs[0], pid).to_dict()

            plugins_preview.append({
                "id": pid,
                "name": plugin_meta.get("name", pid),
                "archive_version": archive_ver,
                "installed_version": installed_ver,
                "action": action,
                "has_models": has_models,
                "scan": scan_report,
            })

    return {
        "format": "yfine-archive",
        "format_version": manifest.get("version", 1),
        "created_at": manifest.get("created_at"),
        "core_tables": core_tables,
        "plugins": plugins_preview,
        "requires_restart": requires_restart,
    }


def preview_json(data: dict) -> dict:
    """Return a simple preview for legacy JSON import files."""
    core_tables = {}
    for table_name, _ in _CORE_TABLES_INSERT_ORDER:
        core_tables[table_name] = len(data.get(table_name, []))
    plugin_tables = data.get("_plugin_tables", {})
    return {
        "format": "json",
        "core_tables": core_tables,
        "plugin_tables": {k: len(v) for k, v in plugin_tables.items()},
        "plugins": [],
        "requires_restart": False,
    }


def import_archive(session: Session, archive_bytes: bytes) -> dict:
    """Import a .yfine archive: install/update plugins, create tables, import data."""
    from database import engine
    from plugins.manager import (
        install_plugin, update_plugin, uninstall_plugin,
        safe_extractall, load_plugin_models, PLUGINS_DIR,
    )
    from plugins.registry import get_plugin, register_plugin

    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != "yfine-archive":
            raise ValueError("Invalid archive: missing yfine-archive format marker")

        data = json.loads(zf.read("data.json"))

        plugins_installed = []
        plugins_updated = []
        requires_restart = False

        # Phase 1: Install/update plugins
        for plugin_meta in manifest.get("plugins", []):
            pid = plugin_meta["id"]
            archive_ver = plugin_meta["version"]
            has_models = plugin_meta.get("has_models", False)

            installed = get_plugin(pid)
            plugin_dir_exists = (PLUGINS_DIR / pid).exists()

            # Determine action
            if installed:
                cmp = _compare_versions(archive_ver, installed.version)
                if cmp == "newer":
                    action = "update"
                else:
                    action = "skip"
            elif plugin_dir_exists:
                action = "reinstall"
            else:
                action = "install"

            if action == "skip":
                continue

            plugin_zip_name = f"plugins/{pid}.zip"
            if plugin_zip_name not in zf.namelist():
                continue

            plugin_zip_bytes = zf.read(plugin_zip_name)
            requires_restart = True

            if action == "update":
                info = update_plugin(plugin_zip_bytes)
                register_plugin(info)
                plugins_updated.append(pid)
            elif action == "reinstall":
                # Directory exists but plugin not registered — remove and reinstall
                uninstall_plugin(pid)
                info = install_plugin(plugin_zip_bytes)
                register_plugin(info)
                plugins_installed.append(pid)
            else:  # install
                info = install_plugin(plugin_zip_bytes)
                register_plugin(info)
                plugins_installed.append(pid)

            # Phase 2: Create tables for newly installed plugins with models
            if has_models:
                load_plugin_models(info)
                SQLModel.metadata.create_all(engine)

    # Phase 3: Import all data (core + plugin tables)
    import_all(session, data)

    # Phase 4: Restore attachment files. The rows reference stored_name, so
    # we only need to drop the blobs into DATA_DIR/attachments/. We also
    # clean up any file on disk whose row wasn't restored (orphans from the
    # previous install).
    from services.attachments import _attachments_dir as _att_dir
    attach_dir = _att_dir()
    known = {
        a.stored_name for a in session.exec(select(MovementAttachment)).all()
    }
    # Remove orphans
    for existing in attach_dir.iterdir():
        if existing.is_file() and existing.name not in known:
            try:
                existing.unlink()
            except OSError:
                pass
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        for name in zf.namelist():
            if not name.startswith("attachments/") or name == "attachments/":
                continue
            stored = Path(name).name
            if not stored or stored not in known:
                continue  # DB has no row for it — skip
            target = attach_dir / stored
            with zf.open(name) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(64 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)

    return {
        "detail": "Import successful",
        "plugins_installed": plugins_installed,
        "plugins_updated": plugins_updated,
        "requires_restart": requires_restart,
    }
