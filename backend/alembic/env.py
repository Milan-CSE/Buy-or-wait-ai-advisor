import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Ensure root is in sys.path
sys.path.insert(0, os.path.abspath("."))

# Interpret the config file for Python logging.
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# Import models Base for autogenerate support
from backend.database.session import Base
import backend.database.models  # load all models

target_metadata = Base.metadata


def get_url():
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    cfg_url = context.config.get_main_option("sqlalchemy.url")
    if cfg_url:
        return cfg_url
    return "sqlite:///d:/hacker_rank_projectt/buyorwait_dev.db"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = context.config.get_section(context.config.config_ini_section)
    if not configuration:
        configuration = {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
