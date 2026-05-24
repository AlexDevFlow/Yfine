"""Regression: auto-heal schema drift on an older DB missing new columns.

Reproduces the scenario where a user upgraded Yfine from an earlier release
whose alembic chain never applied `c4d5e6f7a8b9_add_portfolios_and_price_settings`.
On boot, `main._load_settings_into_i18n` fails with
`sqlite3.OperationalError: no such column: settings.portfolio_prices_enabled`
and the server never finishes starting.
"""
import importlib
import os
import sqlite3


def test_auto_heal_fills_missing_settings_columns(tmp_path, monkeypatch):
    db_file = tmp_path / "yfine.db"
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            locale TEXT NOT NULL DEFAULT 'en',
            date_format TEXT NOT NULL DEFAULT 'dd/mm/yyyy',
            base_currency TEXT,
            theme TEXT DEFAULT 'light',
            hide_net_worth BOOLEAN DEFAULT 0,
            last_source_id INTEGER,
            mobile_nav_mode TEXT DEFAULT 'sidebar',
            lan_access BOOLEAN DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO settings (id, locale, created_at, updated_at)
            VALUES (1, 'en', '2024-01-01', '2024-01-01');
        CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('b9f2c3d4e5f6');
    """)
    conn.commit()
    conn.close()

    monkeypatch.setenv("YFINE_DATA_DIR", str(tmp_path))
    import database
    importlib.reload(database)
    try:
        database.init_db()

        conn = sqlite3.connect(db_file)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(settings)").fetchall()}
        assert "portfolio_prices_enabled" in cols
        assert "portfolio_prices_prompted" in cols
        row = conn.execute(
            "SELECT portfolio_prices_enabled, portfolio_prices_prompted FROM settings WHERE id=1"
        ).fetchone()
        assert row == (0, 0)
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        # The healed DB must be stamped to the *current* head, whatever it
        # is — hard-coding a revision turns this into a chore every release.
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config("alembic.ini")
        cfg.set_main_option("script_location", "alembic")
        head = ScriptDirectory.from_config(cfg).get_current_head()
        assert version == head
        conn.close()
    finally:
        # Restore the default engine for the rest of the suite
        os.environ.pop("YFINE_DATA_DIR", None)
        importlib.reload(database)


def test_auto_heal_adds_missing_notnull_varchar_columns(tmp_path, monkeypatch):
    """Regression: auto-heal must not abort on NOT NULL VARCHAR columns.

    SQLModel's AutoString exposes a `python_type` *property* that raises
    NotImplementedError; a naive `getattr(col.type, "python_type", None)` does
    not swallow it, so a single such column used to abort the entire heal in one
    rolled-back transaction — leaving the DB stamped at head but missing columns,
    which then 500s on login when settings are read.
    """
    db_file = tmp_path / "yfine.db"
    conn = sqlite3.connect(db_file)
    # Minimal legacy settings table missing many columns, incl. NOT NULL VARCHARs.
    conn.executescript("""
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY,
            locale TEXT NOT NULL DEFAULT 'en',
            created_at TEXT,
            updated_at TEXT
        );
        INSERT INTO settings (id, locale) VALUES (1, 'en');
        CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY);
        INSERT INTO alembic_version VALUES ('b9f2c3d4e5f6');
    """)
    conn.commit()
    conn.close()

    monkeypatch.setenv("YFINE_DATA_DIR", str(tmp_path))
    import database
    importlib.reload(database)
    try:
        database.init_db()
        conn = sqlite3.connect(db_file)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(settings)").fetchall()}
        # All of these are NOT NULL VARCHAR — they used to be lost when the heal
        # aborted on the first one.
        for c in ("ui_scale", "hotkeys_json", "nav_layout_json",
                  "saved_views_json", "movement_templates_json"):
            assert c in cols, f"auto-heal failed to add {c}"
        conn.close()
    finally:
        os.environ.pop("YFINE_DATA_DIR", None)
        importlib.reload(database)
