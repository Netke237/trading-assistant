"""Frozen research exports use adjusted history and one read-only snapshot."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel
from app.services import historical_store
from app.services.horizon_tuning.cache import ohlcv_hash


def exporter():
    path = Path(__file__).resolve().parents[1] / "scripts/export_tuning_bars.py"
    spec = importlib.util.spec_from_file_location("export_tuning_bars", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
async def history(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'history.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(OhlcvBase.metadata.create_all)
        rows = [dict(symbol=s, date=date(2020, 1, d), open=101.1234 + i,
                     high=104.0 + i, low=99.0 + i, close=102.0 + i, volume=123 + i,
                     adj_factor=factor, source="tiingo")
                for i, s in enumerate(("AAA", "AAPL", "SPY", "QQQ"))
                for d, factor in ((3, None), (2, 0.33333333), (4, 1))]
        await conn.execute(insert(OhlcvDailyModel), rows)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_adjusted_export_snapshot_manifest_and_missing(history, tmp_path, monkeypatch):
    mod = exporter()
    monkeypatch.setattr(mod, "benchmark_mappings", lambda cells: {
        "swing": {"name": "SPX", "proxy": "SPY"}, "long": {"name": "NDX", "proxy": "QQQ"}})
    monkeypatch.setattr(historical_store, "get_bars", AsyncMock(side_effect=AssertionError("provider path")))
    trace = []
    event.listen(history.sync_engine, "before_cursor_execute", lambda c, cu, sql, p, ctx, many: trace.append(sql))
    async with async_sessionmaker(history)() as db:
        expected = await historical_store._read_bars("AAA", date(2020, 1, 2), date(2020, 1, 3), db)
    trace.clear()
    out = tmp_path / "frozen"
    manifest = await mod.export_bars(out=out, start=date(2020, 1, 2), end=date(2020, 1, 3),
                                     symbols=["AAA", "MISSING", "BIIB"], cells=mod.select_cells("Swing", "Bullish"),
                                     engine=history)
    assert json.loads((out / "AAA_candles.json").read_bytes()) == expected
    assert expected[0]["open"] == 33.7078 and expected[0]["volume"] == 123
    assert expected[1]["open"] == 101.1234
    assert manifest["bounds"] == {"start": "2020-01-02", "end": "2020-01-03", "end_inclusive": True}
    assert manifest["missing"] == ["BIIB", "MISSING", "MSFT", "NVDA"]
    assert manifest["universes"]["trade"] == ["AAA", "MISSING"]
    assert manifest["universes"]["fire"] == ["AAA", "MISSING", "BIIB"]
    assert manifest["available"] == ["AAA", "AAPL", "QQQ", "SPY"]
    assert manifest["benchmarks"]["long"]["proxy"] == "QQQ"
    assert json.loads((out / "SPY_candles.json").read_bytes()) != json.loads((out / "QQQ_candles.json").read_bytes())
    for sym, meta in manifest["files"].items():
        payload = (out / meta["file"]).read_bytes()
        assert meta["sha256"] == hashlib.sha256(payload).hexdigest()
        assert meta["ohlcv_hash"] == ohlcv_hash(json.loads(payload))
        assert meta["count"] == 2 and meta["first"] == "2020-01-02" and meta["last"] == "2020-01-03"
    assert manifest["provenance"]["bars_basis"]
    assert manifest["provenance"]["source_hashes"]
    assert manifest["provenance"]["git_commit"]
    assert not any("database_url" in k.lower() for k in manifest["provenance"])
    assert trace[0].strip().upper() == "BEGIN"
    assert all(sql.lstrip().upper().startswith(("BEGIN", "SELECT")) for sql in trace)
    assert sum(sql.lstrip().upper() == "BEGIN" for sql in trace) == 1
    async with history.connect() as conn:
        assert len((await conn.execute(select(OhlcvDailyModel))).all()) == 12


@pytest.mark.parametrize("symbol", ["../A", "A/B", "A\\B", ".", "CON", "A:stream", "", "A\nB"])
@pytest.mark.asyncio
async def test_unsafe_symbols_do_not_publish(history, tmp_path, symbol):
    with pytest.raises(ValueError):
        await exporter().export_bars(out=tmp_path / "out", end=date(2020, 1, 3), symbols=[symbol], engine=history)
    assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
async def test_existing_destination_empty_history_and_failure_are_immutable(history, tmp_path, monkeypatch):
    mod = exporter()
    out = tmp_path / "out"
    out.mkdir()
    sentinel = out / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(FileExistsError):
        await mod.export_bars(out=out, end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    assert sentinel.read_text() == "untouched"
    out2 = tmp_path / "empty"
    with pytest.raises(ValueError, match="trade-universe"):
        await mod.export_bars(out=out2, end=date(2020, 1, 3), symbols=["MISSING"], engine=history)
    assert not out2.exists()
    real = mod._write_json
    calls = []
    def broken(path, value):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(path, value)
    monkeypatch.setattr(mod, "_write_json", broken)
    with pytest.raises(OSError, match="disk full"):
        await mod.export_bars(out=tmp_path / "failed", end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".failed.*"))


@pytest.mark.asyncio
async def test_snapshot_setup_and_unsupported_dialect():
    mod = exporter()
    conn = SimpleNamespace(exec_driver_sql=AsyncMock())
    await mod._begin_snapshot(conn, "postgresql")
    conn.exec_driver_sql.assert_awaited_once_with("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    conn.exec_driver_sql.reset_mock()
    with pytest.raises(ValueError, match="dialect"):
        await mod._begin_snapshot(conn, "mysql")
    conn.exec_driver_sql.assert_not_awaited()


def test_required_fixed_end_and_new_destination_cli(tmp_path):
    mod = exporter()
    with pytest.raises(SystemExit):
        mod.main(["--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit):
        mod.main(["--end", "2020-01-03"])


@pytest.mark.asyncio
async def test_sqlite_snapshot_remains_consistent_during_writer_commit(history, tmp_path, monkeypatch):
    from sqlalchemy import update
    # WAL permits a concurrent writer while the exporter holds its read snapshot.
    async with history.connect() as conn:
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    mod = exporter()
    real = historical_store._read_bars
    observed = []
    monkeypatch.setattr(mod, "benchmark_mappings", lambda cells: {"Swing": {"name": "SPX", "proxy": "SPY"}})
    async def read(symbol, start, end, db):
        bars = await real(symbol, start, end, db)
        observed.append(symbol)
        if len(observed) == 1:
            async with history.begin() as writer:
                await writer.execute(update(OhlcvDailyModel).where(OhlcvDailyModel.symbol == "SPY").values(close=999))
        return bars
    monkeypatch.setattr(historical_store, "_read_bars", read)
    out = tmp_path / "concurrent"
    await mod.export_bars(out=out, end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    assert all(b["close"] != 999 for b in json.loads((out / "SPY_candles.json").read_bytes()))
    async with history.connect() as conn:
        assert (await conn.execute(select(OhlcvDailyModel.close).where(OhlcvDailyModel.symbol == "SPY"))).scalar() == 999


@pytest.mark.asyncio
async def test_serialization_failure_rolls_back_and_cleans_only_stage(history, tmp_path, monkeypatch):
    mod = exporter()
    real = historical_store._read_bars
    async def nonfinite(*a):
        bars = await real(*a)
        if bars:
            bars[0]["close"] = float("nan")
        return bars
    monkeypatch.setattr(historical_store, "_read_bars", nonfinite)
    with pytest.raises(ValueError, match="JSON"):
        await mod.export_bars(out=tmp_path / "bad", end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    assert not (tmp_path / "bad").exists()
    assert not list(tmp_path.glob(".bad.*"))
    async with history.connect() as conn:
        assert len((await conn.execute(select(OhlcvDailyModel))).all()) == 12


def test_publish_refuses_racing_empty_destination(tmp_path):
    mod = exporter()
    stage, out = tmp_path / "stage", tmp_path / "out"
    stage.mkdir()
    (stage / "manifest.json").write_text("completed")
    out.mkdir()  # Created after export's initial destination check.
    with pytest.raises(OSError):
        mod._publish(stage, out)
    assert stage.is_dir() and list(out.iterdir()) == []


@pytest.mark.asyncio
async def test_invalid_bounds_and_parent_do_not_open_database(tmp_path):
    mod = exporter()
    with pytest.raises(ValueError, match="start"):
        await mod.export_bars(out=tmp_path / "out", start=date(2021, 1, 1), end=date(2020, 1, 1))
    with pytest.raises(ValueError, match="parent"):
        await mod.export_bars(out=tmp_path / "missing/out", end=date(2020, 1, 1))


@pytest.mark.asyncio
async def test_snapshot_error_rolls_back_and_releases_connection(history, monkeypatch):
    mod = exporter()
    monkeypatch.setattr(historical_store, "_read_bars", AsyncMock(side_effect=RuntimeError("read failed")))
    with pytest.raises(RuntimeError, match="read failed"):
        await mod._snapshot(history, ["AAA"], date(2020, 1, 1), date(2020, 1, 3))
    async with history.begin() as conn:
        assert len((await conn.execute(select(OhlcvDailyModel))).all()) == 12


@pytest.mark.asyncio
async def test_postgres_snapshot_is_configured_before_every_read_and_rolled_back(monkeypatch):
    import sqlalchemy.ext.asyncio
    mod = exporter()
    trace = []
    class Connection:
        dialect = SimpleNamespace(name="postgresql")
        async def exec_driver_sql(self, sql):
            trace.append(sql)
        async def rollback(self):
            trace.append("ROLLBACK")
    conn = Connection()
    @asynccontextmanager
    async def connect():
        yield conn
        trace.append("CLOSE")
    @asynccontextmanager
    async def session(*, bind, autoflush):
        assert bind is conn and autoflush is False
        yield "one shared session"
    async def read(symbol, start, end, db):
        assert db == "one shared session"
        assert (start, end) == (date(2020, 1, 2), date(2020, 1, 3))
        trace.append("SELECT " + symbol)
        return []
    monkeypatch.setattr(sqlalchemy.ext.asyncio, "AsyncSession", session)
    monkeypatch.setattr(historical_store, "_read_bars", read)
    assert await mod._snapshot(SimpleNamespace(connect=connect), ["AAA", "BBB"], date(2020, 1, 2), date(2020, 1, 3)) == ({}, {})
    assert trace == ["SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY", "SELECT AAA", "SELECT BBB", "ROLLBACK", "CLOSE"]


def test_benchmark_resolution_uses_selected_scoring_horizons(monkeypatch):
    from app.scoring import stock_scorer
    mod = exporter()
    seen = []
    def resolve(h, overrides):
        seen.append(h)
        return "NDX" if h == "Swing" else "SPX"
    monkeypatch.setattr(stock_scorer, "resolve_rs_benchmark", resolve)
    mappings = mod.benchmark_mappings(mod.select_cells("pullback_ema:Swing,pullback_ema:Annual", "Bullish"))
    assert set(seen) == {"Swing", "Position"}
    assert mappings == {"Swing": {"name": "NDX", "proxy": "QQQ"}, "Position": {"name": "SPX", "proxy": "SPY"}}


@pytest.mark.asyncio
async def test_repeated_export_is_byte_identical_and_does_not_add_today(history, tmp_path):
    mod = exporter()
    first, second = tmp_path / "first", tmp_path / "second"
    a = await mod.export_bars(out=first, end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    b = await mod.export_bars(out=second, end=date(2020, 1, 3), symbols=["AAA"], engine=history)
    assert a == b
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {p.name: p.read_bytes() for p in second.iterdir()}


@pytest.mark.asyncio
async def test_legacy_null_fetch_timestamps_are_unknown_not_missing_bars(tmp_path):
    mod = exporter()
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    try:
        async with engine.begin() as conn:
            # Legacy schema permits NULL timestamps even though the current model does not.
            await conn.exec_driver_sql("CREATE TABLE ohlcv_daily (symbol TEXT, date DATE, open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC, volume BIGINT, adj_factor NUMERIC, split_factor NUMERIC, div_cash NUMERIC, source TEXT, fetched_at DATETIME)")
            await conn.exec_driver_sql("INSERT INTO ohlcv_daily VALUES ('AAA','2020-01-02',100,102,99,101,123,0.5,NULL,NULL,'tiingo',NULL)")
        out = tmp_path / "legacy"
        manifest = await mod.export_bars(out=out, end=date(2020, 1, 3), symbols=["AAA"], engine=engine)
        assert manifest["files"]["AAA"]["unknown_fetched_at"] == 1
        assert manifest["files"]["AAA"]["fetched_at_min"] is None
        assert manifest["files"]["AAA"]["fetched_at_max"] is None
        assert json.loads((out / "AAA_candles.json").read_bytes()) == [
            {"time": "2020-01-02", "open": 50.0, "high": 51.0, "low": 49.5, "close": 50.5, "volume": 123}]
    finally:
        await engine.dispose()


@pytest.mark.parametrize("help_only", [True, False])
def test_cold_export_cli_never_writes_configured_confidence_cache(tmp_path, help_only):
    sentinel = tmp_path / "sentinel.db"
    with sqlite3.connect(sentinel) as conn:
        conn.execute("CREATE TABLE confidence_cache (cache_key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL)")
        conn.execute("INSERT INTO confidence_cache VALUES ('expired-sentinel', '{}', 0)")
    before = sentinel.read_bytes()
    script = Path(__file__).resolve().parents[1] / "scripts/export_tuning_bars.py"
    env = dict(os.environ, BAMENDJOU_CONFIDENCE_CACHE_DB=str(sentinel))
    if help_only:
        command = [sys.executable, str(script), "--help"]
    else:
        command = [sys.executable, "-c", "import os, runpy, sys; original=os.environ['BAMENDJOU_CONFIDENCE_CACHE_DB']; runpy.run_path(sys.argv[1], run_name='export_import_test'); assert os.environ['BAMENDJOU_CONFIDENCE_CACHE_DB']==original", str(script)]
    result = subprocess.run(command, env=env, cwd=script.parents[2], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert sentinel.read_bytes() == before
    with sqlite3.connect(sentinel) as conn:
        assert conn.execute("SELECT cache_key FROM confidence_cache").fetchall() == [("expired-sentinel",)]


def test_export_import_preserves_already_loaded_cache_state(monkeypatch, tmp_path):
    from app.data import confidence_cache
    original_target = confidence_cache._DB_PATH
    original_store = confidence_cache._store.copy()
    original_generation = confidence_cache._generation
    monkeypatch.setenv("BAMENDJOU_CONFIDENCE_CACHE_DB", str(tmp_path / "unused.db"))
    exporter()
    assert confidence_cache._DB_PATH == original_target
    assert confidence_cache._store == original_store
    assert confidence_cache._generation == original_generation
    assert os.environ["BAMENDJOU_CONFIDENCE_CACHE_DB"] == str(tmp_path / "unused.db")
    assert not (tmp_path / "unused.db").exists()
