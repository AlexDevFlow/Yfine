from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# Skip when frozen — logging is already configured by desktop.py
# and fileConfig can fail without a console on Windows.
import sys
if config.config_file_name is not None and not getattr(sys, "frozen", False):
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from sqlmodel import SQLModel
import models  # noqa: F401 — register all models
target_metadata = SQLModel.metadata


# --- Plugin table filter ---
# Core tables that Alembic should manage. Everything else (plugin tables,
# orphaned tables from uninstalled plugins) is ignored by autogenerate.
from models import __all__ as _model_names
_CORE_TABLES = set()
for _name in _model_names:
    _cls = getattr(models, _name)
    if hasattr(_cls, "__tablename__"):
        _CORE_TABLES.add(_cls.__tablename__)
    elif hasattr(_cls, "__table__"):
        _CORE_TABLES.add(_cls.__table__.name)


def _include_name(name, type_, parent_names):
    """Only include core tables in autogenerate — skip plugin tables."""
    if type_ == "table":
        return name in _CORE_TABLES
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=_include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=_include_name,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
