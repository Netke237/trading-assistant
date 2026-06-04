import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.models.base import Base
from app.database import Base as DatabaseBase
from app.models.scan_session import ScanSessionBase
from app.models.ohlcv_daily import OhlcvBase   # noqa: F401

# Load all ORM models so both metadata registries are populated before autogenerate.
from app.models.admin import Admin  # noqa: F401
from app.models.child import Child  # noqa: F401
from app.models.quest import Quest  # noqa: F401
from app.models.time_log import TimeLog  # noqa: F401
from app.models.override_log import OverrideLog  # noqa: F401
from app.models.audit_event import AuditEventModel  # noqa: F401
from app.models.portfolio import PortfolioPositionModel  # noqa: F401
from app.models.watchlist import WatchlistSymbolModel  # noqa: F401
from app.models.watched_contracts import WatchedContractModel  # noqa: F401
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401

settings = get_settings()
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = [Base.metadata, DatabaseBase.metadata, ScanSessionBase.metadata, OhlcvBase.metadata]

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
