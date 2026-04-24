import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine, select


def _get_base_dir() -> Path:
    """Return the directory containing bundled read-only assets (templates, static, locales).

    When frozen by PyInstaller this is sys._MEIPASS; otherwise the project root.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def _get_data_dir() -> Path:
    """Return a writable directory for the database, backups, and plugin state.

    Resolution order:
    1. YFINE_DATA_DIR env var (explicit override)
    2. Platform-specific app-data path when frozen
    3. Project root when running from source
    """
    env = os.environ.get("YFINE_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "yfine"
        elif sys.platform == "win32":
            return Path(os.environ.get("APPDATA", str(Path.home()))) / "yfine"
        else:
            return Path(
                os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
            ) / "yfine"
    return Path(__file__).parent


BASE_DIR = _get_base_dir()
DATA_DIR = _get_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "yfine.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

DEFAULT_TAGS = [
    "🛒 Groceries 🛒",
    "⛽ Fuel ⛽",
    "🚌 Transport 🚌",
    "🎉 Entertainment 🎉",
    "🛍️ Shopping 🛍️",
    "✈️ Travel ✈️",
    "📋 Subscription 📋",
    "💰 Salary 💰",
    "📈 Investment 📈",
    "🎁 Gift 🎁",
    "💼 Freelance 💼",
]


_BACKUPS_TO_KEEP = 20
_MIGRATION_WARNING_FILE = "migration_warning.txt"


def _backup_db():
    """Create a timestamped backup of the database before schema changes."""
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"yfine_{timestamp}.db"
        shutil.copy2(DB_PATH, backup_path)


def _prune_backups(keep: int = _BACKUPS_TO_KEEP) -> None:
    """Keep only the `keep` most recent backups to avoid unbounded growth."""
    try:
        backup_dir = DATA_DIR / "backups"
        if not backup_dir.exists():
            return
        backups = sorted(
            (p for p in backup_dir.iterdir() if p.is_file() and p.name.startswith("yfine_") and p.suffix == ".db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[keep:]:
            try:
                old.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _alembic_config():
    """Build an Alembic Config, or None if alembic.ini is not bundled."""
    from alembic.config import Config
    alembic_ini = BASE_DIR / "alembic.ini"
    if not alembic_ini.exists():
        return None
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    return cfg


def _current_alembic_revision() -> str | None:
    """Read the alembic_version row on the DB, or None if the table is
    missing/empty (legacy install that never stamped)."""
    from sqlalchemy import inspect, text
    try:
        insp = inspect(engine)
        if not insp.has_table("alembic_version"):
            return None
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _get_alembic_head() -> str | None:
    """Return the single head revision, or None if alembic can't be loaded
    or the script tree has multiple heads (which would mean a bad release)."""
    try:
        from alembic.script import ScriptDirectory
        cfg = _alembic_config()
        if cfg is None:
            return None
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:
        return None


def _run_migrations() -> bool:
    """Run `alembic upgrade head`. Returns True on success, False on any
    failure — callers use the return value to decide whether to fall back
    to auto-heal."""
    import logging
    import traceback
    _mig_logger = logging.getLogger("database.migrations")

    try:
        from alembic import command
        cfg = _alembic_config()
        if cfg is None:
            _mig_logger.info("No alembic.ini found — skipping migrations")
            return False
        command.upgrade(cfg, "head")
        _mig_logger.info("Migrations completed successfully")
        return True
    except Exception as e:
        _mig_logger.warning("Migration failed: %s\n%s", e, traceback.format_exc())
        return False


def _write_migration_warning(msg: str) -> None:
    """Leave a marker in DATA_DIR so the UI / user can tell that the upgrade
    path fell back to auto-heal instead of running real migrations."""
    import logging
    try:
        marker = DATA_DIR / _MIGRATION_WARNING_FILE
        with open(marker, "w", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}\n{msg}\n")
        logging.getLogger("database.migrations").warning("Migration warning written: %s", msg)
    except Exception:
        pass


def _clear_migration_warning() -> None:
    try:
        marker = DATA_DIR / _MIGRATION_WARNING_FILE
        if marker.exists():
            marker.unlink()
    except Exception:
        pass


def _auto_heal_schema() -> int:
    """Reconcile DB schema with SQLModel.metadata by adding missing columns
    to existing tables. Handles cases where an older install preserved its
    DB across an upgrade but `create_all` (which only creates *tables*, never
    ALTERs) + a broken migration chain left some columns missing. Returns
    the number of columns added so callers can decide whether to stamp
    Alembic to head.
    """
    import logging
    from sqlalchemy import inspect, text

    _mig_logger = logging.getLogger("database.migrations")
    insp = inspect(engine)
    added = 0
    try:
        with engine.begin() as conn:
            for table in SQLModel.metadata.sorted_tables:
                if not insp.has_table(table.name):
                    continue  # create_all already created it
                existing = {c["name"] for c in insp.get_columns(table.name)}
                for col in table.columns:
                    if col.name in existing:
                        continue
                    try:
                        col_type_sql = col.type.compile(engine.dialect)
                    except Exception:
                        _mig_logger.warning("auto-heal: cannot compile type for %s.%s", table.name, col.name)
                        continue

                    parts = [f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type_sql}']
                    default_added = False
                    if col.server_default is not None:
                        try:
                            arg = col.server_default.arg
                            default_text = getattr(arg, "text", None) or str(arg)
                            parts.append(f"DEFAULT ({default_text})")
                            default_added = True
                        except Exception:
                            pass
                    if not col.nullable and not default_added:
                        # SQLite requires a default when ALTERing a NOT NULL column
                        py_type = getattr(col.type, "python_type", None)
                        if py_type in (int, float, bool):
                            parts.append("DEFAULT 0")
                        else:
                            parts.append("DEFAULT ''")
                    if not col.nullable:
                        parts.append("NOT NULL")
                    sql = " ".join(parts)
                    try:
                        conn.execute(text(sql))
                        _mig_logger.info("auto-heal: added %s.%s", table.name, col.name)
                        added += 1
                    except Exception as e:
                        _mig_logger.warning("auto-heal: skipped %s.%s: %s", table.name, col.name, e)
    except Exception as e:
        _mig_logger.warning("auto-heal failed (non-fatal): %s", e)
    return added


def _stamp_alembic_head() -> None:
    """Set alembic_version to head — used after auto-heal so subsequent
    startups don't keep retrying migrations against a DB whose schema has
    already been reconciled to the latest state."""
    import logging
    _mig_logger = logging.getLogger("database.migrations")
    try:
        from alembic.config import Config
        from alembic import command
        alembic_ini = BASE_DIR / "alembic.ini"
        if not alembic_ini.exists():
            return
        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.stamp(cfg, "head")
        _mig_logger.info("Stamped alembic_version=head after schema repair")
    except Exception as e:
        _mig_logger.warning("Could not stamp alembic head: %s", e)


def init_db():
    # Handle crash recovery for encrypted DBs before touching the DB
    from security import handle_crash_recovery
    handle_crash_recovery()

    _backup_db()
    _prune_backups()
    import models  # noqa: F401 — ensure all models are registered
    SQLModel.metadata.create_all(engine)

    current = _current_alembic_revision()
    head = _get_alembic_head()

    if current and head and current == head:
        # Already at head. Still call upgrade so any hotfix migrations added
        # between releases get picked up; upgrade-to-head on head is a no-op.
        _run_migrations()

    elif current and head and current != head:
        # Known intermediate revision — real migrations (including data
        # transforms) must run. Try the proper path first; only fall back
        # to heal+stamp if alembic fails, and leave a warning so skipped
        # data steps are visible rather than silent.
        if not _run_migrations():
            # `_run_migrations` may have partially advanced alembic_version
            # before failing. Re-read it so the warning reflects where we
            # actually stopped, then heal + stamp so the next launch does
            # not loop on the same failing step.
            stalled_at = _current_alembic_revision() or current
            healed = _auto_heal_schema()
            _stamp_alembic_head()
            _write_migration_warning(
                f"Alembic upgrade {current} → {head} stopped at {stalled_at}. "
                f"Schema was reconciled by auto-heal (added {healed} column(s)) "
                f"and stamped to head, but any data-transform steps after "
                f"{stalled_at} were NOT executed. A pre-upgrade backup is in "
                f"DATA_DIR/backups/. See yfine.log for the traceback."
            )

    else:
        # Legacy path: alembic_version is missing/empty (DB predates Alembic
        # integration, or was only ever touched by create_all). Preserve the
        # behavior that has been shipping — heal columns, stamp head.
        healed = _auto_heal_schema()
        if healed > 0:
            _stamp_alembic_head()
            _write_migration_warning(
                f"Legacy database upgraded via auto-heal (added {healed} "
                f"column(s)) and stamped to head. Data-transform migrations "
                f"from earlier revisions did not run. A pre-upgrade backup "
                f"is in DATA_DIR/backups/."
            )
        else:
            # Schema already matches models. Try migrations once — if they
            # succeed, alembic_version gets set correctly; if they fail (e.g.
            # "table already exists" because create_all ran first), stamp
            # head to stop the retry loop.
            if not _run_migrations():
                _stamp_alembic_head()

    _seed_default_tags()


def _seed_default_tags():
    from models.tag import Tag

    with Session(engine) as session:
        existing = session.exec(select(Tag)).all()
        if existing:
            return  # Tags already exist, don't re-seed
        for name in DEFAULT_TAGS:
            session.add(Tag(name=name))
        session.commit()


def get_session():
    with Session(engine) as session:
        yield session
