"""Evidence-only PATCH interleaving against a fresh in-memory SQLite database.
Run from repo root: backend/.venv/bin/python docs/superpowers/measurements/broker-path-residuals/risk_probe.py
No network or production database access. No application code changes.
"""
import asyncio
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'backend'))
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from app.models.portfolio import PortfolioPositionModel as Position
from app.routers.portfolio import update_position
from app.schemas import PortfolioPositionUpdate
from app.services.portfolio_risk import _load_config


async def main():
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.run_sync(Position.__table__.create)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        for symbol in ('AAA', 'BBB'):
            db.add(Position(rec_id=symbol, symbol=symbol, contract=f'{symbol}|STOCK',
                            direction='Bullish', entry_price=10, qty=1,
                            entry_date='2026-10-13', stop=9, targets=[]))
        await db.commit()
    arrived = 0
    barrier = asyncio.Event()

    class InterleavedSession:
        def __init__(self, db):
            self.db = db
            self.reads = 0
        async def execute(self, query):
            nonlocal arrived
            result = await self.db.execute(query)
            self.reads += 1
            if self.reads == 2:
                # Both actual risk snapshots have been read before either writes.
                arrived += 1
                if arrived == 2:
                    barrier.set()
                await barrier.wait()
            return result
        async def commit(self):
            await self.db.commit()
        async def refresh(self, row):
            await self.db.refresh(row)

    cfg = _load_config()
    cfg = {**cfg, 'portfolio': {**cfg['portfolio'], 'portfolio_value': 10000,
           'max_total_stock_exposure_pct': .015, 'max_single_stock_position_pct': .2}}
    with patch('app.routers.portfolio.account_value', return_value=10000), \
         patch('app.services.portfolio_risk._load_config', return_value=cfg):
        async with factory() as a, factory() as b:
            responses = await asyncio.gather(
                update_position('AAA', PortfolioPositionUpdate(qty=10), InterleavedSession(a)),
                update_position('BBB', PortfolioPositionUpdate(qty=10), InterleavedSession(b)))
        async with factory() as db:
            rows = (await db.execute(select(Position))).scalars().all()
            total = sum(row.entry_price * row.qty for row in rows)
            cap = 10000 * .015
            print(f'PATCH accepted quantities: {[r.qty for r in responses]}')
            print(f'Persisted combined exposure: {total:.2f}; configured total cap: {cap:.2f}')
            assert total == 200 and total > cap
            row = next(r for r in rows if r.rec_id == 'AAA')
            print(f'Quantity changed 1 -> {row.qty}; entry remains {row.entry_price:.2f}')
            # Positive, wrong-side underlying stop is accepted by PATCH today.
            response = await update_position('AAA', PortfolioPositionUpdate(stop=11), db)
            print(f'Bullish stored entry {row.entry_price:.2f}; PATCH accepted stop {response.stop:.2f}')
            assert response.stop == 11
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
