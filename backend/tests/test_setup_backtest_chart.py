"""SETUP-BACKTEST-CHART (#391): Verification tests for Pre-Breakout & Fib Pullback chart evidence.

Pins:
1. Pinned numerical invariance: run_strategy_backtest produces 100% byte-identical
   metrics with and without detail_collector for setup strategies.
2. Detail evidence structure: collect_setup_details produces a DetailedBacktestResult
   with reconciled equity curve, trade records, and benchmark index starting at 100.
3. Zero-trades and insufficient history handling: zero trades produces a successful
   result with empty trades and flat equity at 100; <100 bars produces status "insufficient_history".
4. Persistence and retrieval: setup backtest details roundtrip through save_artifact
   and get_artifact with schema_version=1 and provenance="original".
5. Scan integration: Pre-Breakout and Fib Pullback scan results attach backtest_artifact_id
   and backtest_artifact_status="available".
"""
import copy
from datetime import date, timedelta
import math
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models.scan_report import ScanReportBase
from app.routers.stock_scan import (
    PreBreakoutScanRequest,
    FibPullbackScanRequest,
    _prebreakout_scan_core,
    _fib_pullback_scan_core,
)
from app.services import backtest_artifacts as artifacts
from app.services.strategy_backtest import (
    BacktestResult,
    run_strategy_backtest,
    run_strategy_backtest_detailed,
)
from app.services.strategy_backtest_details import (
    DetailedBacktestResult,
    ENGINE_CONTRACT_VERSION,
)
from app.services.setup_entries import setup_params
from tests.test_prebreakout_params import _make_bars
from tests.test_strategy_engine_fib import _impulse_then_retrace


def _synthetic_bars(n: int = 120, base_price: float = 100.0) -> list[dict]:
    """Synthetic oscillating bars."""
    bars = []
    start_date = date(2025, 1, 1)
    for i in range(n):
        step = math.sin(i / 5.0) * 2.0
        p = base_price + step
        bars.append({
            "time": (start_date + timedelta(days=i)).isoformat(),
            "open": p - 0.5,
            "high": p + 1.5,
            "low": p - 1.5,
            "close": p + 0.2,
            "volume": 1000.0 + (i % 10) * 100.0,
        })
    return bars


def _contracting_bars_with_breakout(n: int = 120) -> list[dict]:
    """Bars engineered to trigger breakout_setup and generate trade records."""
    bars = []
    start_date = date(2025, 1, 1)
    for i in range(80):
        bars.append({
            "time": (start_date + timedelta(days=i)).isoformat(),
            "open": 98.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 2000.0,
        })
    for i in range(80, 106):
        bars.append({
            "time": (start_date + timedelta(days=i)).isoformat(),
            "open": 103.5,
            "high": 104.5,
            "low": 103.0,
            "close": 104.0,
            "volume": 500.0,
        })
    for i in range(106, n):
        bars.append({
            "time": (start_date + timedelta(days=i)).isoformat(),
            "open": 104.8,
            "high": 112.0,
            "low": 104.2,
            "close": 111.0,
            "volume": 4000.0,
        })
    return bars


def _fib_bars_with_time(n_base: int = 80) -> list[dict]:
    """Bars engineered to trigger fibonacci_pullback setup."""
    bars = _impulse_then_retrace(swing_pct=0.15, retrace_bars=15, n_base=n_base)
    start_date = date(2025, 1, 1)
    for i, b in enumerate(bars):
        b["time"] = (start_date + timedelta(days=i)).isoformat()
    return bars


@pytest.fixture
async def test_db_factory(tmp_path):
    """Temporary SQLite database factory with ScanReportBase tables."""
    from app.models.backtest_artifact import BacktestArtifact  # noqa: F401
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test_artifacts.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(ScanReportBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.mark.parametrize("strategy", ["breakout_setup", "fibonacci_pullback"])
def test_setup_backtest_chart(strategy):
    """PRESENCE PROBE & INVARIANCE: run_strategy_backtest preserves identical numbers with detail_collector."""
    if strategy == "breakout_setup":
        bars = _contracting_bars_with_breakout(120)
        params = setup_params(strategy, {"require_trend": False, "setup_expiry_bars": 5})
    else:
        bars = _fib_bars_with_time(80)
        params = setup_params(strategy, {"ema_filter_period": 0, "setup_expiry_bars": 5})

    # 1. Run without detail_collector
    without_details = run_strategy_backtest(
        bars,
        strategy=strategy,
        direction="Bullish",
        params=params,
        detail_collector=None,
    )

    # 2. Run with detail_collector
    collected: list[DetailedBacktestResult] = []
    with_details = run_strategy_backtest(
        bars,
        strategy=strategy,
        direction="Bullish",
        params=params,
        detail_collector=collected,
    )

    # Pinned numerical invariance: every summary metric matches exactly
    assert without_details.strategy == with_details.strategy == strategy
    assert without_details.direction == with_details.direction == "Bullish"
    assert without_details.n_trades == with_details.n_trades
    assert without_details.win_rate == with_details.win_rate
    assert without_details.total_return_pct == with_details.total_return_pct
    assert without_details.max_drawdown_pct == with_details.max_drawdown_pct
    assert without_details.expectancy == with_details.expectancy
    assert without_details.sharpe == with_details.sharpe
    assert without_details.confidence == with_details.confidence
    assert without_details.passes_gate == with_details.passes_gate
    assert without_details.summary_text == with_details.summary_text
    assert without_details.n_time_exits == with_details.n_time_exits

    # Detail collector captured exactly one DetailedBacktestResult
    assert len(collected) == 1
    detail = collected[0]
    assert detail.status == "success"
    assert detail.engine_contract_version == ENGINE_CONTRACT_VERSION
    assert detail.initial_equity == 100000.0

    # Candle alignment
    assert len(detail.candles) == len(bars)
    assert len(detail.input_candles) == len(bars)

    # Equity curve reconciliation:
    # 1. Curve begins at index 100.0 and benchmark 100.0
    assert len(detail.equity) == len(bars)
    assert detail.equity[0].strategy_index == 100.0
    assert detail.equity[0].benchmark_index == 100.0
    assert detail.equity[0].equity == 100000.0

    # 2. Ending strategy return matches summary.total_return_pct within float tolerance
    ending_return = detail.equity[-1].strategy_index - 100.0
    assert math.isclose(ending_return, with_details.total_return_pct, abs_tol=1e-7)

    # Trade records match
    assert len(detail.trades) == with_details.n_trades
    for tr in detail.trades:
        assert tr.entry_time > 0
        assert tr.exit_time >= tr.entry_time
        assert tr.entry_price > 0
        assert tr.exit_price > 0
        assert tr.exit_reason in ("target", "stop", "time", "unknown")
        assert math.isfinite(tr.net_return_pct)
        assert math.isfinite(tr.commission)


def test_setup_backtest_zero_trades():
    """Zero trades produces a successful DetailedBacktestResult with flat equity at 100."""
    bars = _synthetic_bars(110)
    # High resistance proximity threshold prevents breakout signals from firing
    params = setup_params("breakout_setup", {"require_trend": True, "resistance_proximity_pct": 0.0001})

    collected: list[DetailedBacktestResult] = []
    summary = run_strategy_backtest(
        bars,
        strategy="breakout_setup",
        direction="Bullish",
        params=params,
        detail_collector=collected,
    )

    assert summary.n_trades == 0
    assert len(collected) == 1
    detail = collected[0]
    assert detail.status == "success"
    assert len(detail.trades) == 0
    assert len(detail.open_positions) == 0
    assert len(detail.equity) == len(bars)
    # Equity curve is flat at 100
    for sample in detail.equity:
        assert sample.strategy_index == 100.0
        assert sample.equity == 100000.0
    assert detail.equity[-1].strategy_index - 100.0 == pytest.approx(0.0)


def test_setup_backtest_insufficient_history():
    """Bars < 100 produces an explicit 'insufficient_history' DetailedBacktestResult."""
    short_bars = _synthetic_bars(50)
    collected: list[DetailedBacktestResult] = []
    summary = run_strategy_backtest(
        short_bars,
        strategy="breakout_setup",
        direction="Bullish",
        detail_collector=collected,
    )

    assert summary.n_trades == 0
    assert summary.passes_gate is False
    assert len(collected) == 1
    detail = collected[0]
    assert detail.status == "insufficient_history"
    assert detail.trades == ()
    assert detail.equity == ()
    assert "insufficient" in detail.reason.lower() or "100" in detail.reason


@pytest.mark.asyncio
async def test_setup_backtest_artifact_persistence_roundtrip(test_db_factory):
    """Setup backtest details roundtrip cleanly via save_artifact and get_artifact."""
    bars = _contracting_bars_with_breakout(120)
    collected: list[DetailedBacktestResult] = []
    run_strategy_backtest(
        bars,
        strategy="breakout_setup",
        direction="Bullish",
        params={"require_trend": False},
        detail_collector=collected,
    )

    detail = collected[0]
    scan_id = str(uuid4())
    ident = {
        "scan_id": scan_id,
        "report_run_id": None,
        "symbol": "TESTSYM",
        "strategy": "breakout_setup",
        "direction": "Bullish",
        "horizon": "Swing",
        "interval": "1d",
        "bars_basis_version": "test-v1",
        "input_hash": "b" * 64,
        "engine_contract_version": ENGINE_CONTRACT_VERSION,
    }

    async with test_db_factory() as db:
        saved = await artifacts.save_artifact(db, detail=detail, identity=ident)

    assert saved["artifact_id"]
    assert saved["schema_version"] == 1
    assert saved["provenance"] == "original"

    async with test_db_factory() as db:
        retrieved = await artifacts.get_artifact(db, saved["artifact_id"], "TESTSYM")

    assert retrieved is not None
    assert retrieved["artifact_id"] == saved["artifact_id"]
    assert retrieved["schema_version"] == 1
    assert retrieved["provenance"] == "original"
    assert retrieved["identity"]["symbol"] == "TESTSYM"
    assert retrieved["identity"]["strategy"] == "breakout_setup"
    assert len(retrieved["detail"]["equity"]) == len(bars)
    assert retrieved["detail"]["equity"][0]["strategy_index"] == 100.0


@pytest.mark.asyncio
async def test_prebreakout_and_fib_scan_artifacts_attached(monkeypatch, test_db_factory):
    """Pre-Breakout and Fib Pullback scans attach backtest_artifact_id and backtest_artifact_status."""
    # Build bars for prebreakout candidate
    pre_bars = _make_bars(n=120, base=100.0, atr=0.5)
    start_date = date(2025, 1, 1)
    for i, b in enumerate(pre_bars):
        b["time"] = (start_date + timedelta(days=i)).isoformat()

    # Build bars for fib candidate
    fib_bars = _fib_bars_with_time(80)

    async def mock_get_historical_bars(symbol, *args, **kwargs):
        if symbol == "PRESYM":
            return copy.deepcopy(pre_bars)
        if symbol == "FIBSYM":
            return copy.deepcopy(fib_bars)
        return []

    monkeypatch.setattr("app.routers.stock_scan.get_historical_bars", mock_get_historical_bars)
    monkeypatch.setattr("app.routers.stock_scan.AsyncSessionLocal", test_db_factory)

    # 1. Test PreBreakout scan
    pre_req = PreBreakoutScanRequest(
        symbols=["PRESYM"],
        direction="Bullish",
        params_override={"require_trend": False},
    )
    pre_results = await _prebreakout_scan_core(pre_req)

    assert len(pre_results) >= 1
    cand = next(r for r in pre_results if r["symbol"] == "PRESYM")
    assert "backtest_artifact_id" in cand
    assert cand["backtest_artifact_id"] is not None
    assert cand["backtest_artifact_status"] == "available"

    # Verify candidate artifact can be retrieved from database
    async with test_db_factory() as db:
        art = await artifacts.get_artifact(db, cand["backtest_artifact_id"], "PRESYM")
    assert art is not None
    assert art["identity"]["symbol"] == "PRESYM"
    assert art["identity"]["strategy"] == "breakout_setup"
    assert art["detail"]["status"] == "success"

    # 2. Test Fib Pullback scan
    fib_req = FibPullbackScanRequest(
        symbols=["FIBSYM"],
        direction="Bullish",
        params_override={"fib_levels": [61.8], "fib_tolerance_pct": 0.03, "ema_filter_period": 0},
    )
    fib_results = await _fib_pullback_scan_core(fib_req)

    assert len(fib_results) >= 1
    fib_cand = next(r for r in fib_results if r["symbol"] == "FIBSYM")
    assert "backtest_artifact_id" in fib_cand
    assert fib_cand["backtest_artifact_id"] is not None
    assert fib_cand["backtest_artifact_status"] == "available"

    async with test_db_factory() as db:
        art_fib = await artifacts.get_artifact(db, fib_cand["backtest_artifact_id"], "FIBSYM")
    assert art_fib is not None
    assert art_fib["identity"]["symbol"] == "FIBSYM"
    assert art_fib["identity"]["strategy"] == "fibonacci_pullback"
    assert art_fib["detail"]["status"] == "success"
