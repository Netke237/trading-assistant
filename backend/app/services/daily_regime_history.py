"""Read-only, settled database history shared by daily symbol regime consumers."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.ohlcv_daily import OhlcvDailyModel
from app.services.historical_store import last_settle_boundary
from app.services.money_config import RegimeConfigError, validate_regime_block


def daily_regime_bar_count(full_doc: Mapping) -> int:
    """Validate contributing config and select one count for all daily horizons."""
    if not isinstance(full_doc, Mapping):
        raise RegimeConfigError([('regime', 'scoring configuration must be a mapping')])
    regime = full_doc.get('regime')
    horizons = {'swing', 'position'}
    if isinstance(regime, Mapping):
        horizons.update(h for h, block in regime.items()
                        if isinstance(block, Mapping) and block.get('timeframe') == 'daily')
    validate_regime_block(full_doc, sorted(horizons))
    return max([800] + [regime[h]['window'] + regime[h]['lookback']
                        for h in horizons if regime[h]['timeframe'] == 'daily'])


def _validate_read(count: int, now: datetime | None) -> datetime:
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError('daily regime count must be a positive integer')
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('daily regime observation time must be timezone aware')
    return now


async def get_daily_regime_bars(
    symbol: str, count: int, *, now: datetime | None = None, sessions=None,
) -> list[dict]:
    """Return newest settled rows, chronologically, without healing or writing.

    Empty history returns []; query errors propagate. Resolve request-loop
    sessions at invocation so this reader never owns a pooled application engine.
    """
    now = _validate_read(count, now)
    end = last_settle_boundary(now).date()
    if sessions is None:
        from app.database import AsyncSessionLocal
        sessions = AsyncSessionLocal
    async with sessions() as db:
        result = await db.execute(
            select(OhlcvDailyModel)
            .where(OhlcvDailyModel.symbol == symbol, OhlcvDailyModel.date <= end)
            .order_by(OhlcvDailyModel.date.desc())
            .limit(count)
        )
        rows = result.scalars().all()
        bars = []
        for row in reversed(rows):
            adj = float(row.adj_factor) if row.adj_factor is not None else None

            def price(raw):
                value = float(raw)
                return round(value * adj, 6) if adj is not None else value

            bars.append({'time': row.date.isoformat(), 'open': price(row.open),
                         'high': price(row.high), 'low': price(row.low),
                         'close': price(row.close), 'volume': int(row.volume)})
        return bars


def get_daily_regime_bars_sync(
    symbol: str, count: int, *, now: datetime | None = None,
    database_url: str | None = None,
) -> list[dict]:
    """Worker-thread adapter with a private nonpooled engine, disposed per read."""
    now = _validate_read(count, now)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError('synchronous daily regime reader cannot run on an event loop thread')
    if database_url is None:
        from app.config import get_settings
        database_url = get_settings().DATABASE_URL

    async def read():
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
            return await get_daily_regime_bars(symbol, count, now=now, sessions=sessions)
        finally:
            await engine.dispose()

    return asyncio.run(read())
