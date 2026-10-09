"""Only an exact verified history seam exempts the two-provider basis boundary."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.ohlcv_daily import OhlcvBase, OhlcvDailyModel, OhlcvHistoryStateModel
from app.services.historical_store import find_stale_adjustment, stale_reasons
from app.services.history_basis import seam_signature

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from evidence._bars import load_basis_rows, load_history_states  # noqa: E402
from evidence.bar_basis_check import build_report  # noqa: E402


def _rows(old_source="tiingo"):
    return [
        (date(2024, 1, 2) + timedelta(days=i), 100.0 / factor, factor, 1.0, 0.0,
         old_source if i < 2 else "alpaca", datetime(2024, 2, 1 if i < 2 else 2, tzinfo=timezone.utc))
        for i, factor in enumerate([0.98, 0.98, 1.0, 1.0])
    ]


def _seam(rows, old_source="tiingo"):
    return {"seam_date": rows[2][0], "old_source": old_source,
            "seam_signature": seam_signature(rows[1], rows[2])}


def _replace(rows, index, field, value):
    row = list(rows[index])
    row[field] = value
    rows[index] = tuple(row)


@pytest.mark.parametrize("source", ["tiingo", "yfinance"])
def test_exact_verified_partition_suppresses_only_its_source_mix_and_batch_step(source):
    rows = _rows(source)
    assert stale_reasons(rows).reasons == ["batch_step", "mixed_basis"]
    assert stale_reasons(rows, _seam(rows, source)) is None


@pytest.mark.parametrize("bad_seam", [None, {}, {"seam_date": date(2020, 1, 1)},
                                     {"seam_date": date(2024, 1, 4), "old_source": "tiingo",
                                      "seam_signature": "incorrect"}])
def test_missing_or_invalid_proof_does_not_exempt_source_partition(bad_seam):
    assert stale_reasons(_rows(), bad_seam).reasons == ["batch_step", "mixed_basis"]


@pytest.mark.parametrize("index,field,value", [
    (1, 0, date(2024, 1, 1)), (2, 0, date(2024, 1, 8)),
    (1, 1, 103.0), (2, 1, 101.0), (1, 2, 0.99), (2, 2, 1.01),
    (1, 5, "yfinance"), (2, 5, "tiingo"),
    (1, 6, datetime(2024, 2, 3, tzinfo=timezone.utc)),
    (2, 6, datetime(2024, 2, 3, tzinfo=timezone.utc)),
])
def test_changed_boundary_invalidates_recorded_proof(index, field, value):
    rows = _rows()
    seam = _seam(rows)
    _replace(rows, index, field, value)
    assert "mixed_basis" in stale_reasons(rows, seam).reasons


@pytest.mark.parametrize("factor", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_any_nonpositive_or_null_or_nonfinite_factor_invalidates_exemption(factor):
    rows = _rows()
    seam = _seam(rows)
    _replace(rows, 0, 2, factor)
    assert "mixed_basis" in stale_reasons(rows, seam).reasons


def test_additional_source_outside_boundary_cannot_hide_behind_valid_boundary_signature():
    rows = _rows()
    seam = _seam(rows)
    _replace(rows, 0, 5, "yfinance")
    assert "mixed_basis" in stale_reasons(rows, seam).reasons


def test_null_fetch_timestamp_outside_boundary_invalidates_partition():
    rows = _rows()
    seam = _seam(rows)
    _replace(rows, 0, 6, None)
    assert "mixed_basis" in stale_reasons(rows, seam).reasons


def test_verified_boundary_still_reports_real_adjusted_jump_at_that_boundary():
    rows = _rows()
    _replace(rows, 2, 1, 200.0)
    _replace(rows, 3, 1, 200.0)
    assert stale_reasons(rows, _seam(rows)).reasons == ["jump"]


def test_verified_boundary_still_reports_fetch_before_corporate_action():
    rows = _rows()
    _replace(rows, 0, 6, datetime(2024, 1, 2, tzinfo=timezone.utc))
    _replace(rows, 3, 4, 0.5)
    assert stale_reasons(rows, _seam(rows)).reasons == ["pre_action_fetch"]


@pytest.mark.parametrize("index", [1, 3], ids=["older-same-source-step", "current-same-source-step"])
def test_verified_boundary_does_not_exempt_another_same_source_batch_step(index):
    rows = _rows()
    factor = 0.96 if index == 1 else 1.02
    _replace(rows, index, 1, 100.0 / factor)
    _replace(rows, index, 2, factor)
    _replace(rows, index, 6, datetime(2024, 2, 3, tzinfo=timezone.utc))
    assert stale_reasons(rows, _seam(rows)).reasons == ["batch_step"]


def test_same_source_partition_cannot_be_marked_as_an_exempt_seam():
    rows = _rows("alpaca")
    assert stale_reasons(rows, _seam(rows, "alpaca")).reasons == ["batch_step"]


@pytest_asyncio.fixture
async def stored_history():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(OhlcvBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        for symbol in ["VERIFIED", "UNVERIFIED", "BIIB"]:
            for row in _rows():
                day, close, factor, split, div, source, fetched = row
                db.add(OhlcvDailyModel(symbol=symbol, date=day, open=close, high=close * 1.01,
                                      low=close * 0.99, close=close, volume=1000,
                                      adj_factor=factor, split_factor=split, div_cash=div,
                                      source=source, fetched_at=fetched))
        await db.commit()
    rows = await load_basis_rows(["VERIFIED", "BIIB"], session_factory=factory)
    async with factory() as db:
        for symbol in rows:
            db.add(OhlcvHistoryStateModel(symbol=symbol, **_seam(rows[symbol])))
        await db.commit()
    statements = []

    def record_statement(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip())

    event.listen(engine.sync_engine, "before_cursor_execute", record_statement)
    yield factory, statements
    await engine.dispose()


@pytest.mark.asyncio
async def test_find_stale_reads_matching_symbol_metadata_in_same_session(stored_history):
    factory, statements = stored_history
    async with factory() as db:
        assert await find_stale_adjustment("VERIFIED", db) is None
        assert (await find_stale_adjustment("UNVERIFIED", db)).reasons == ["batch_step", "mixed_basis"]
    assert statements and all(statement.upper().startswith("SELECT") for statement in statements)
    assert sum("ohlcv_history_state" in statement for statement in statements) == 2


@pytest.mark.asyncio
async def test_evidence_separate_state_loader_preserves_seven_tuples_and_select_only(stored_history):
    factory, statements = stored_history
    symbols = ["VERIFIED", "UNVERIFIED", "BIIB", "ABSENT"]
    rows = await load_basis_rows(symbols, session_factory=factory)
    states = await load_history_states(symbols, session_factory=factory)
    assert set(states) == {"VERIFIED", "BIIB"}
    assert rows["ABSENT"] == []
    assert all(len(row) == 7 for values in rows.values() for row in values)
    assert stale_reasons(rows["VERIFIED"], states["VERIFIED"]) is None
    assert statements and all(statement.upper().startswith("SELECT") for statement in statements)
    async with factory() as db:
        assert len((await db.execute(select(OhlcvDailyModel))).scalars().all()) == 12
        assert len((await db.execute(select(OhlcvHistoryStateModel))).scalars().all()) == 2


def test_build_report_optional_states_suppress_only_verified_symbols_and_keep_all_symbols():
    rows = {symbol: _rows() for symbol in ["VERIFIED", "UNVERIFIED", "BIIB"]}
    bars = {symbol: [{"time": row[0].isoformat(), "open": 100.0, "close": 100.0,
                      "high": 101.0, "low": 99.0} for row in values]
            for symbol, values in rows.items()}
    assert "Symbols flagged by `stale_reasons`: 3 of 3" in build_report(bars, rows, "Header")
    report = build_report(bars, rows, "Header", {"VERIFIED": _seam(rows["VERIFIED"]),
                                                "BIIB": _seam(rows["BIIB"])})
    assert "Symbols flagged by `stale_reasons`: 1 of 3" in report
    assert "| VERIFIED | 4 | 0 | 0 | 0.00% | 0 | - | - | - |" in report
    assert "| BIIB | 4 | 0 | 0 | 0.00% | 0 | - | - | - |" in report
    assert "| UNVERIFIED | 4 | 0 | 0 | 0.00% | 0 | batch_step, mixed_basis |" in report


@pytest.mark.asyncio
async def test_evidence_cli_passes_full_span_metadata_without_exclusion_filter(monkeypatch):
    from evidence import bar_basis_check as evidence

    symbols = ["BIIB", "CTVA", "VERIFIED"]
    seen = []

    async def all_symbols():
        return symbols

    async def bars(requested, start, end):
        seen.append(("bars", requested))
        return {symbol: [] for symbol in requested}

    async def rows(requested):
        seen.append(("rows", requested))
        return {symbol: _rows() for symbol in requested}

    async def states(requested):
        seen.append(("states", requested))
        return {symbol: _seam(_rows()) for symbol in requested}

    monkeypatch.setattr(evidence, "stored_symbols", all_symbols)
    monkeypatch.setattr(evidence, "load_bars", bars)
    monkeypatch.setattr(evidence, "load_basis_rows", rows)
    monkeypatch.setattr(evidence, "load_history_states", states)
    report = await evidence._main(evidence.common_parser("basis").parse_args([]))
    assert seen == [("bars", symbols), ("rows", symbols), ("states", symbols)]
    assert "Symbols flagged by `stale_reasons`: 0 of 3" in report
    assert "Stale-reason rows: full stored row set per symbol (not date-bounded)" in report
