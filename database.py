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


def _backup_db():
    """Create a timestamped backup of the database before schema changes."""
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        backup_dir = DATA_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"yfine_{timestamp}.db"
        shutil.copy2(DB_PATH, backup_path)


def _run_migrations():
    """Run Alembic migrations so existing databases get schema updates."""
    import logging
    _mig_logger = logging.getLogger("database.migrations")

    try:
        from alembic.config import Config
        from alembic import command

        alembic_ini = BASE_DIR / "alembic.ini"
        if not alembic_ini.exists():
            _mig_logger.info("No alembic.ini found at %s — skipping migrations", alembic_ini)
            return

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
        cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
        command.upgrade(cfg, "head")
        _mig_logger.info("Migrations completed successfully")
    except Exception as e:
        _mig_logger.warning("Migration failed (non-fatal, create_all already ran): %s", e)


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
    import models  # noqa: F401 — ensure all models are registered
    SQLModel.metadata.create_all(engine)
    healed = _auto_heal_schema()
    if healed > 0:
        # DB needed repair — sync Alembic to avoid retrying obsolete migrations
        _stamp_alembic_head()
    else:
        _run_migrations()
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
