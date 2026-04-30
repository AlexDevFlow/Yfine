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
