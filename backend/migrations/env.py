import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from dotenv import load_dotenv

# Alembic never imports app.main, which is where load_dotenv() normally runs, so
# without this the root .env is never read: app.config then falls back to its
# sqlite dev default and migrations silently apply to a stray backend/dev.db
# instead of Postgres, exiting 0 as if they had succeeded.
load_dotenv()

from app.config import get_settings
from app.models.base import Base
from app.database import Base as DatabaseBase
from app.models.scan_session import ScanSessionBase
from app.models.scan_report import ScanReportBase
from app.models.backtest_artifact import BacktestArtifact  # noqa: F401
from app.models.ohlcv_daily import OhlcvBase
from app.models.scheduled_scan_run import ScheduledScanRunBase

# Load all ORM models so both metadata registries are populated before autogenerate.
from app.models.audit_event import AuditEventModel  # noqa: F401
from app.models.portfolio import PortfolioPositionModel  # noqa: F401
from app.models.watchlist import WatchlistSymbolModel  # noqa: F401
from app.models.watched_contracts import WatchedContractModel  # noqa: F401
from app.models.alert import AlertRuleModel, AlertHistoryModel  # noqa: F401
from app.models.drawing import DrawingModel  # noqa: F401
from app.models.fundamentals import FundamentalsModel  # noqa: F401
from app.models.position_alert import PositionAlertHistoryModel  # noqa: F401
from app.models.daily_risk import DailyRiskBudget, DailyRiskAttempt, DailyRiskLoss  # noqa: F401

settings = get_settings()
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = [Base.metadata, DatabaseBase.metadata, ScanSessionBase.metadata, OhlcvBase.metadata, ScheduledScanRunBase.metadata, ScanReportBase.metadata]

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
