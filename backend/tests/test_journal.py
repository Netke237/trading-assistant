# backend/tests/test_journal.py
"""CRUD tests for /journal — mirroring test_symbol_notes.py's async-client
harness, plus the migration upgrade/downgrade smoke test pattern from
test_backfill_zero_stop_migration.py."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from httpx import AsyncClient, ASGITransport

_MIGRATION_PATH = (
    Path(__file__).parent.parent / "migrations" / "versions"
    / "2bf3bf834b29_add_journal_entries_table.py"
)


def _load_migration():
    # The migration's filename starts with a digit, which isn't a valid
    # module name for a plain `import` -- load it by file path instead
    # (same approach as test_backfill_zero_stop_migration.py).
    spec = importlib.util.spec_from_file_location("add_journal_entries_table_migration", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


async def _make_app():
    from fastapi import FastAPI
    from app.database import Base, get_db
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.models.journal import JournalEntryModel  # noqa: F401 — registers table with Base.metadata

    engine = create_async_engine('sqlite+aiosqlite:///:memory:', connect_args={'check_same_thread': False})
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with Session() as session:
            yield session

    from app.routers.journal import router as journal_router

    app = FastAPI()
    app.include_router(journal_router)
    app.dependency_overrides[get_db] = override_get_db
    return app


def _trade_payload(**overrides):
    payload = {
        'entry_type': 'trade',
        'entry_date': '2026-08-01T00:00:00Z',
        'symbol': 'AAPL',
        'instrument_type': 'stock',
        'direction': 'long',
        'entry_price': 190.0,
        'exit_price': None,
        'position_size': 100.0,
        'stop_loss': 185.0,
        'risk_dollars': 500.0,
        'net_pnl': None,
        'thesis': 'Pullback to 20ema in uptrend.',
        'strategy_tag': 'pullback_ema',
        'mistake_tags': None,
        'execution_grade': None,
        'status': 'open',
        'lessons_learned': None,
        'notes': None,
        'position_id': None,
    }
    payload.update(overrides)
    return payload


def _note_payload(**overrides):
    payload = {
        'entry_type': 'note',
        'entry_date': '2026-08-01T00:00:00Z',
        'notes': 'Stayed disciplined today, no revenge trades.',
    }
    payload.update(overrides)
    return payload


# ── CRUD round-trip ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_get_trade_entry():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload())
        assert resp.status_code == 201
        data = resp.json()
        assert data['symbol'] == 'AAPL'
        assert data['entry_type'] == 'trade'
        assert data['id']

        resp2 = await client.get(f"/journal/entries/{data['id']}")
        assert resp2.status_code == 200
        assert resp2.json()['symbol'] == 'AAPL'


@pytest.mark.asyncio
async def test_get_entry_missing_returns_404():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.get('/journal/entries/does-not-exist')
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_entry_full_replace():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        created = (await client.post('/journal/entries', json=_trade_payload())).json()
        updated_payload = _trade_payload(net_pnl=250.0, status='closed', exit_price=195.0)
        resp = await client.put(f"/journal/entries/{created['id']}", json=updated_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'closed'
        assert data['net_pnl'] == 250.0
        assert data['exit_price'] == 195.0


@pytest.mark.asyncio
async def test_update_entry_missing_returns_404():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.put('/journal/entries/does-not-exist', json=_trade_payload())
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_entry():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        created = (await client.post('/journal/entries', json=_trade_payload())).json()
        resp = await client.delete(f"/journal/entries/{created['id']}")
        assert resp.status_code == 204

        resp2 = await client.get(f"/journal/entries/{created['id']}")
        assert resp2.status_code == 404


@pytest.mark.asyncio
async def test_delete_entry_missing_returns_404():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.delete('/journal/entries/does-not-exist')
        assert resp.status_code == 404


# ── List / filter params ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_entries_default_sort_entry_date_desc():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/journal/entries', json=_trade_payload(symbol='AAPL', entry_date='2026-08-01T00:00:00Z'))
        await client.post('/journal/entries', json=_trade_payload(symbol='MSFT', entry_date='2026-08-03T00:00:00Z'))
        await client.post('/journal/entries', json=_trade_payload(symbol='TSLA', entry_date='2026-08-02T00:00:00Z'))

        resp = await client.get('/journal/entries')
        assert resp.status_code == 200
        symbols = [e['symbol'] for e in resp.json()]
        assert symbols == ['MSFT', 'TSLA', 'AAPL']


@pytest.mark.asyncio
async def test_list_entries_filter_by_symbol_strategy_status_type():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/journal/entries', json=_trade_payload(symbol='AAPL', strategy_tag='pullback_ema', status='open'))
        await client.post('/journal/entries', json=_trade_payload(symbol='MSFT', strategy_tag='breakout_base', status='closed', net_pnl=100.0))
        await client.post('/journal/entries', json=_note_payload())

        resp = await client.get('/journal/entries', params={'symbol': 'AAPL'})
        assert [e['symbol'] for e in resp.json()] == ['AAPL']

        resp = await client.get('/journal/entries', params={'strategy_tag': 'breakout_base'})
        assert [e['symbol'] for e in resp.json()] == ['MSFT']

        resp = await client.get('/journal/entries', params={'status': 'closed'})
        assert [e['symbol'] for e in resp.json()] == ['MSFT']

        resp = await client.get('/journal/entries', params={'entry_type': 'note'})
        data = resp.json()
        assert len(data) == 1
        assert data[0]['entry_type'] == 'note'


@pytest.mark.asyncio
async def test_list_entries_filter_by_date_range():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        await client.post('/journal/entries', json=_trade_payload(symbol='AAPL', entry_date='2026-08-01T00:00:00Z'))
        await client.post('/journal/entries', json=_trade_payload(symbol='MSFT', entry_date='2026-08-10T00:00:00Z'))
        await client.post('/journal/entries', json=_trade_payload(symbol='TSLA', entry_date='2026-08-20T00:00:00Z'))

        resp = await client.get('/journal/entries', params={
            'date_from': '2026-08-05T00:00:00Z', 'date_to': '2026-08-15T00:00:00Z',
        })
        assert [e['symbol'] for e in resp.json()] == ['MSFT']


# ── (a)-(c): entry_type validator ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_note_entry_with_trade_only_field_rejected():
    """A `note` entry carrying any trade-only field is rejected (422)."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_note_payload(symbol='AAPL'))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_note_entry_with_each_trade_only_field_rejected():
    """Every one of the 14 trade-only fields independently triggers the
    rejection, not just `symbol`."""
    trade_only_overrides = {
        'symbol': 'AAPL', 'direction': 'long', 'entry_price': 1.0, 'exit_price': 1.0,
        'position_size': 1.0, 'stop_loss': 1.0, 'risk_dollars': 1.0, 'net_pnl': 1.0,
        'status': 'open', 'instrument_type': 'stock', 'position_id': 'REC-1',
        'strategy_tag': 'pullback_ema', 'execution_grade': 3, 'thesis': 'x',
    }
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for field, value in trade_only_overrides.items():
            resp = await client.post('/journal/entries', json=_note_payload(**{field: value}))
            assert resp.status_code == 422, f'field {field} should be forbidden on a note entry'


@pytest.mark.asyncio
async def test_b_trade_entry_missing_symbol_rejected():
    """A `trade` entry missing `symbol` is rejected (422)."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(symbol=None))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_entry_type_outside_trade_or_note_rejected():
    """`entry_type` is a Literal['trade', 'note'], not a bare `str` -- an
    unrecognized value must 422 rather than silently falling through both
    branches of the model_validator with zero validation applied (the
    validator only ever checks `== 'trade'` or `== 'note'`)."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(entry_type='garbage'))
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_c_note_entry_with_mistake_tags_and_lessons_learned_accepted():
    """A `note` entry with `mistake_tags`/`lessons_learned` set is accepted
    (201) -- confirms the permitted-exception path isn't over-blocked by (a)'s
    rule."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_note_payload(
            mistake_tags=['revenge_trade', 'oversized'],
            lessons_learned='Step away after a loss before re-entering.',
        ))
        assert resp.status_code == 201
        data = resp.json()
        assert data['mistake_tags'] == ['revenge_trade', 'oversized']
        assert data['lessons_learned'] == 'Step away after a loss before re-entering.'


# ── (d)-(g): r_multiple computed_field ───────────────────────────────────────

@pytest.mark.asyncio
async def test_d_r_multiple_computed_with_nonzero_risk_dollars():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(
            status='closed', net_pnl=250.0, risk_dollars=500.0,
        ))
        assert resp.status_code == 201
        assert resp.json()['r_multiple'] == 0.5


@pytest.mark.asyncio
async def test_e_r_multiple_none_when_risk_dollars_unset():
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(
            status='closed', net_pnl=250.0, risk_dollars=None,
        ))
        assert resp.status_code == 201
        assert resp.json()['r_multiple'] is None


@pytest.mark.asyncio
async def test_f_r_multiple_none_when_risk_dollars_zero_not_zero_division_error():
    """`r_multiple is None` -- not a ZeroDivisionError -- when
    `risk_dollars == 0`. Kept distinct from (e) since a guard written as
    `if risk_dollars is not None` (instead of `if risk_dollars`) would pass
    (e) while still raising here."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(
            status='closed', net_pnl=250.0, risk_dollars=0.0,
        ))
        assert resp.status_code == 201
        assert resp.json()['r_multiple'] is None


@pytest.mark.asyncio
async def test_g_r_multiple_none_for_open_trade_with_null_net_pnl():
    """`r_multiple is None` -- not a TypeError -- for a `status='open'` entry
    with `risk_dollars` set and `net_pnl` unset. The ordinary open-trade
    shape, and the specific case a `risk_dollars`-only guard would miss even
    though it passes (d)/(e)/(f)."""
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(
            status='open', net_pnl=None, risk_dollars=500.0,
        ))
        assert resp.status_code == 201
        assert resp.json()['r_multiple'] is None

        # Also confirm GET /entries (the list path) doesn't 500 on this shape.
        resp2 = await client.get('/journal/entries')
        assert resp2.status_code == 200
        assert resp2.json()[0]['r_multiple'] is None


# ── (h): execution_grade bounds ──────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize('bad_grade', [0, 6, -1, 10])
async def test_h_execution_grade_out_of_range_rejected(bad_grade):
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(execution_grade=bad_grade))
        assert resp.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize('good_grade', [1, 3, 5])
async def test_h_execution_grade_in_range_accepted(good_grade):
    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        resp = await client.post('/journal/entries', json=_trade_payload(execution_grade=good_grade))
        assert resp.status_code == 201
        assert resp.json()['execution_grade'] == good_grade


# ── (i): updated_at actually bumps on PUT ────────────────────────────────────

@pytest.mark.asyncio
async def test_i_updated_at_changes_after_put():
    """The Router section flags onupdate firing as a risk ('confirm the
    handler uses attribute assignment + commit... or set it explicitly') --
    assert it directly rather than trusting SQLAlchemy's onupdate fired."""
    import asyncio

    app = await _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        created = (await client.post('/journal/entries', json=_trade_payload())).json()
        original_updated_at = created['updated_at']

        # onupdate's lambda uses datetime.now(timezone.utc) -- guarantee the
        # second write lands in a distinguishable microsecond/second bucket.
        await asyncio.sleep(0.01)

        resp = await client.put(f"/journal/entries/{created['id']}", json=_trade_payload(status='closed', net_pnl=10.0))
        assert resp.status_code == 200
        new_updated_at = resp.json()['updated_at']

        assert new_updated_at != original_updated_at
        assert created['created_at'] == resp.json()['created_at']


# ── Migration upgrade/downgrade smoke test ───────────────────────────────────

def test_journal_entries_migration_upgrade_and_downgrade(tmp_path):
    """Runs the migration's own upgrade()/downgrade() against a bare sqlite
    engine -- this codebase's test DBs normally bootstrap via
    Base.metadata.create_all() and never execute Alembic (see
    test_alembic_heads.py's docstring), so there is no full alembic-upgrade
    harness to drive end-to-end; exercising the migration module directly is
    the established pattern (test_backfill_zero_stop_migration.py)."""
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'journal_migration.db'}")

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration.upgrade()

        insp = inspect(conn)
        assert 'journal_entries' in insp.get_table_names()
        cols = {c['name'] for c in insp.get_columns('journal_entries')}
        expected_cols = {
            'id', 'user_id', 'entry_type', 'entry_date', 'symbol', 'instrument_type',
            'direction', 'entry_price', 'exit_price', 'position_size', 'stop_loss',
            'risk_dollars', 'net_pnl', 'thesis', 'strategy_tag', 'mistake_tags',
            'execution_grade', 'status', 'lessons_learned', 'notes', 'position_id',
            'created_at', 'updated_at',
        }
        assert expected_cols <= cols

        idx_names = {i['name'] for i in insp.get_indexes('journal_entries')}
        assert 'ix_journal_entries_user_id_entry_date' in idx_names
        # No standalone entry_date index -- only the composite (user_id, entry_date).
        assert not any(
            set(i['column_names']) == {'entry_date'} for i in insp.get_indexes('journal_entries')
        )

        with Operations.context(ctx):
            migration.downgrade()

        insp2 = inspect(conn)
        assert 'journal_entries' not in insp2.get_table_names()
