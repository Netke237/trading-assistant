import asyncio
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base
from app.models.daily_risk import DailyRiskBudget, DailyRiskAttempt, DailyRiskLoss
from app.models.closed_position import ClosedPositionModel
from app.services.daily_risk import DailyRiskService, DailyRiskError, MAX_CENTS


@pytest.fixture
async def ledger(tmp_path):
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/ledger.db')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    config = {'portfolio': {'portfolio_value': 1000}, 'auto_trade': {'max_daily_loss_pct': .1}}
    history = []
    now = [datetime(2026, 10, 3, 12, tzinfo=timezone.utc)]
    service = DailyRiskService(sessions, config_provider=lambda: config, history_provider=lambda: history, clock=lambda: now[0])
    yield service, sessions, config, history, now
    await engine.dispose()


async def reserve(service, identity='a', price=60, **kwargs):
    return await service.reserve(identity, instrument='AAPL|STOCK', quantity=1, price=price, source='manual', **kwargs)


async def totals(sessions, day='2026-10-03'):
    async with sessions() as db:
        row = await db.get(DailyRiskBudget, day)
        return row.reserved_cents, row.loss_cents


@pytest.mark.asyncio
async def test_concurrent_openers_cannot_both_spend_remaining_budget(ledger):
    service, sessions, *_ = ledger
    results = await asyncio.gather(reserve(service, 'manual'), reserve(service, 'auto'), return_exceptions=True)
    assert sum(isinstance(r, DailyRiskError) for r in results) == 1
    assert await totals(sessions) == (6000, 0)


@pytest.mark.asyncio
async def test_idempotent_reserve_release_and_released_ids_cannot_dispatch(ledger):
    service, sessions, *_ = ledger
    first = await reserve(service, price=60)
    assert await reserve(service, price=60.0) == first
    with pytest.raises(DailyRiskError, match='different'):
        await reserve(service, price=61)
    await service.resolve('a', definitely_not_submitted=False, outcome='accepted')
    assert await totals(sessions) == (6000, 0)
    await asyncio.gather(*(service.resolve('a', definitely_not_submitted=True, outcome='rejected') for _ in range(2)))
    assert await totals(sessions) == (0, 0)
    with pytest.raises(DailyRiskError, match='Released'):
        await reserve(service)


@pytest.mark.asyncio
async def test_restart_and_utc_rollover(ledger):
    service, sessions, config, history, now = ledger
    await reserve(service)
    restarted = DailyRiskService(sessions, config_provider=lambda: config, history_provider=lambda: history, clock=lambda: now[0])
    with pytest.raises(DailyRiskError, match='exhausted'):
        await reserve(restarted, 'b')
    now[0] += timedelta(days=1)
    await reserve(restarted, 'next')
    assert await totals(sessions, '2026-10-04') == (6000, 0)
    assert await totals(sessions) == (6000, 0)


@pytest.mark.asyncio
async def test_cent_ceiling_and_allowance_floor(ledger):
    service, sessions, config, *_ = ledger
    config['portfolio']['portfolio_value'] = 1.009
    config['auto_trade']['max_daily_loss_pct'] = 1
    await reserve(service, price=.99001)
    assert await totals(sessions) == (100, 0)
    with pytest.raises(DailyRiskError):
        await reserve(service, 'b', price=.0001)


@pytest.mark.parametrize('bad', [True, float('nan'), float('inf'), -1, 0, 'nonsense', MAX_CENTS])
@pytest.mark.asyncio
async def test_invalid_opening_money_fails_closed(ledger, bad):
    with pytest.raises(DailyRiskError):
        await reserve(ledger[0], price=bad)


@pytest.mark.parametrize('fraction', [True, float('nan'), float('inf'), -1, 1.1, 'oops'])
@pytest.mark.asyncio
async def test_invalid_daily_limits_fail_closed(ledger, fraction):
    service, sessions, config, *_ = ledger
    config['auto_trade']['max_daily_loss_pct'] = fraction
    with pytest.raises(DailyRiskError):
        await reserve(service)


def closed(identity, pnl, now):
    return ClosedPositionModel(id=identity, rec_id='position', symbol='AAPL', contract='AAPL|STOCK', direction='Bullish', entry_price=10, exit_price=9, exit_date='1900-01-01', qty_closed=1, realized_pnl_dollar=pnl, realized_pnl_pct=-10, closed_at=now)


@pytest.mark.asyncio
async def test_loss_inside_close_transaction_idempotent_wins_do_not_refund(ledger):
    service, sessions, _, _, now = ledger
    await reserve(service, price=50)
    loss = closed('partial1', -25.001, now[0])
    async with sessions() as db:
        async with db.begin():
            db.add(loss)
            await service.record_realized_loss(db, loss)
            await service.record_realized_loss(db, loss)
            await service.record_realized_loss(db, closed('win', 100, now[0]))
    assert await totals(sessions) == (5000, 2501)
    with pytest.raises(RuntimeError, match='abort'):
        async with sessions() as db:
            async with db.begin():
                await service.record_realized_loss(db, closed('aborted', -10, now[0]))
                raise RuntimeError('abort')
    assert await totals(sessions) == (5000, 2501)
    async with sessions() as db:
        await db.execute(delete(ClosedPositionModel))
        await db.commit()
    with pytest.raises(DailyRiskError):
        await reserve(service, 'b', price=25)
    assert await totals(sessions) == (5000, 2501)


@pytest.mark.asyncio
async def test_bootstrap_existing_losses_and_auto_history_after_manual_reservation(ledger):
    service, sessions, _, history, now = ledger
    await reserve(service, 'manual', price=10)
    history.append({'attempt_id': 'old-auto', 'timestamp': now[0].isoformat(), 'premium_at_risk': 60, 'status': 'unknown', 'symbol': 'AAPL'})
    async with sessions() as db:
        db.add(closed('legacy-loss', -20, now[0]))
        await db.commit()
    with pytest.raises(DailyRiskError):
        await reserve(service, 'refused', price=15)
    # Imports survive refusal and do not double count on retry or history deletion.
    assert await totals(sessions) == (7000, 2000)
    history.clear()
    async with sessions() as db:
        await db.execute(delete(ClosedPositionModel))
        await db.commit()
    await reserve(service, 'remaining', price=10)
    assert await totals(sessions) == (8000, 2000)


@pytest.mark.asyncio
async def test_lowered_limit_used_for_next_dispatch(ledger):
    service, sessions, config, *_ = ledger
    await reserve(service, price=50)
    config['auto_trade']['max_daily_loss_pct'] = .05
    with pytest.raises(DailyRiskError):
        await reserve(service, 'b', price=.01)


@pytest.mark.asyncio
async def test_bootstrap_repeats_do_not_charge_twice_and_ignores_older_utc_days(ledger):
    service, sessions, _, history, now = ledger
    history.extend([
        {'attempt_id': 'today', 'timestamp': now[0].isoformat(), 'premium_at_risk': 30, 'status': 'accepted'},
        {'attempt_id': 'yesterday', 'timestamp': (now[0] - timedelta(days=1)).isoformat(), 'premium_at_risk': 90, 'status': 'accepted'},
    ])
    await reserve(service, 'manual', price=10)
    await reserve(service, 'second', price=10)
    assert await totals(sessions) == (5000, 0)


def test_migration_upgrade_downgrade_and_postgres_atomic_statement(tmp_path):
    from importlib.util import spec_from_file_location, module_from_spec
    from pathlib import Path
    from sqlalchemy import create_engine, inspect, update
    from sqlalchemy.dialects import postgresql
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'migrations/versions/f62a9e1b4c70_add_daily_risk_budget.py'
    spec = spec_from_file_location('daily_risk_migration', path)
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f'sqlite:///{tmp_path}/migration.db')
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert set(inspect(connection).get_table_names()) == {'daily_risk_attempts', 'daily_risk_budgets', 'daily_risk_losses'}
        migration.downgrade()
        assert inspect(connection).get_table_names() == []
    sql = str(update(DailyRiskBudget).where(DailyRiskBudget.day == '2026-10-03', DailyRiskBudget.reserved_cents + DailyRiskBudget.loss_cents <= 10000 - 6000).values(reserved_cents=DailyRiskBudget.reserved_cents + 6000).compile(dialect=postgresql.dialect()))
    assert 'reserved_cents + daily_risk_budgets.loss_cents <=' in sql
    assert 'UPDATE daily_risk_budgets SET reserved_cents=' in sql
    engine.dispose()


@pytest.mark.asyncio
async def test_legacy_known_rejections_do_not_import_risk(ledger):
    service, sessions, _, history, now = ledger
    history.append({'attempt_id': 'rejected', 'timestamp': now[0].isoformat(), 'premium_at_risk': 90, 'status': 'Rejected'})
    await reserve(service, price=60)
    assert await totals(sessions) == (6000, 0)


@pytest.mark.asyncio
async def test_limit_is_read_after_waiting_for_bootstrap_and_day_lock(ledger):
    service, sessions, config, *_ = ledger
    bootstrap = service._bootstrap
    async def lowered(db, day):
        await bootstrap(db, day)
        config['auto_trade']['max_daily_loss_pct'] = .01
    service._bootstrap = lowered
    with pytest.raises(DailyRiskError, match='exhausted'):
        await reserve(service, price=60)
    assert await totals(sessions) == (0, 0)


@pytest.mark.parametrize('wait_on_lock', [1, 2])
@pytest.mark.asyncio
async def test_waiter_crossing_midnight_uses_new_days_remaining_budget(ledger, wait_on_lock):
    service, sessions, _, _, now = ledger
    now[0] = datetime(2026, 10, 4, 0, 0, 1, tzinfo=timezone.utc)
    await reserve(service, 'already-today', price=60)
    now[0] = datetime(2026, 10, 3, 23, 59, 59, tzinfo=timezone.utc)
    lock = service._lock_day
    calls = 0
    async def waited(db, day):
        nonlocal calls
        calls += 1
        await lock(db, day)
        if calls == wait_on_lock:
            now[0] = datetime(2026, 10, 4, 0, 0, 1, tzinfo=timezone.utc)
    service._lock_day = waited
    with pytest.raises(DailyRiskError, match='exhausted'):
        await reserve(service, 'crossing', price=60)
    assert await totals(sessions, '2026-10-04') == (6000, 0)
    async with sessions() as db:
        previous = await db.get(DailyRiskBudget, '2026-10-03')
        assert previous is None or previous.reserved_cents == 0
        assert await db.get(DailyRiskAttempt, 'crossing') is None


@pytest.mark.asyncio
async def test_midnight_retry_bootstraps_each_days_history_without_double_charge(ledger):
    service, sessions, _, history, now = ledger
    now[0] = datetime(2026, 10, 3, 23, 59, 59, tzinfo=timezone.utc)
    history.extend([
        {'attempt_id': 'old-auto', 'timestamp': now[0].isoformat(), 'premium_at_risk': 30, 'status': 'accepted'},
        {'attempt_id': 'new-auto', 'timestamp': '2026-10-04T00:00:00+00:00', 'premium_at_risk': 20, 'status': 'accepted'},
    ])
    lock = service._lock_day
    calls = 0
    async def waited(db, day):
        nonlocal calls
        calls += 1
        await lock(db, day)
        if calls == 2:
            now[0] = datetime(2026, 10, 4, 0, 0, 1, tzinfo=timezone.utc)
    service._lock_day = waited
    result = await reserve(service, 'crossing', price=60)
    assert result.day == '2026-10-04'
    assert await totals(sessions) == (3000, 0)
    assert await totals(sessions, '2026-10-04') == (8000, 0)


@pytest.mark.asyncio
async def test_midnight_during_attempt_flush_rolls_back_old_day_charge(ledger, monkeypatch):
    service, sessions, _, _, now = ledger
    original_flush = sessions.class_.flush
    crossed = False
    async def midnight_flush(db, *args, **kwargs):
        nonlocal crossed
        await original_flush(db, *args, **kwargs)
        if not crossed:
            crossed = True
            now[0] += timedelta(days=1)
    monkeypatch.setattr(sessions.class_, 'flush', midnight_flush)
    result = await reserve(service, price=60)
    assert result.day == '2026-10-04'
    assert await totals(sessions) == (0, 0)
    assert await totals(sessions, '2026-10-04') == (6000, 0)


@pytest.mark.asyncio
async def test_prior_day_attempt_id_cannot_authorize_new_day_dispatch(ledger):
    service, sessions, _, _, now = ledger
    await reserve(service, 'same-id', price=60)
    now[0] += timedelta(days=1)
    with pytest.raises(DailyRiskError, match='earlier UTC day'):
        await reserve(service, 'same-id', price=60)
    assert await totals(sessions, '2026-10-04') == (0, 0)


@pytest.mark.asyncio
async def test_repeated_day_changes_have_bounded_fail_closed_retry(ledger):
    service, sessions, _, _, now = ledger
    lock = service._lock_day
    calls = 0
    async def changing_clock(db, day):
        nonlocal calls
        calls += 1
        await lock(db, day)
        now[0] += timedelta(days=1)
    service._lock_day = changing_clock
    with pytest.raises(DailyRiskError, match='changed repeatedly'):
        await reserve(service)
    assert calls == 3
    async with sessions() as db:
        assert (await db.execute(select(DailyRiskAttempt))).scalars().all() == []
        assert (await db.execute(select(DailyRiskBudget))).scalars().all() == []
