# backend/tests/test_confidence_gate_stocks.py
import asyncio
import dataclasses
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.stock_scan import StockScanRequest


def test_stock_scan_request_accepts_confidence_gate_fields():
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_caution_below=50.0,
        confidence_reject_below=35.0,
        confidence_atr_mult_target=3.0,
        confidence_atr_mult_stop=1.5,
    )
    assert req.confidence_caution_below == 50.0
    assert req.confidence_reject_below == 35.0
    assert req.confidence_atr_mult_target == 3.0
    assert req.confidence_atr_mult_stop == 1.5


def test_confidence_gate_fields_default_to_none():
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema"
    )
    assert req.confidence_caution_below is None
    assert req.confidence_reject_below is None
    assert req.confidence_atr_mult_target is None
    assert req.confidence_atr_mult_stop is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_bars(n: int = 130) -> list[dict]:
    """Return n minimal OHLCV bar dicts with plausible values."""
    return [{"time": f"2024-01-{i:02d}", "open": 150.0, "high": 155.0,
             "low": 148.0, "close": 152.0, "volume": 1_000_000} for i in range(1, n + 1)]


def _make_fake_card(status: str = "PASS", score: int = 70):
    """Return a real StockScoreCard dataclass instance."""
    from app.scoring.stock_scorer import StockScoreCard, RuleResult
    return StockScoreCard(
        symbol="AAPL",
        direction="Bullish",
        horizon="Swing",
        score=score,
        status=status,
        rules=[RuleResult(name="trend", status="PASS", score=60, detail={})],
    )


def _make_fake_signal():
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.entry_price = 152.0
    sig.stop_price = 148.0
    sig.target_price = 160.0
    sig.targets = [160.0]
    sig.rr_ratio = 2.0
    sig.atr = 3.0
    sig.detail = {}
    return sig


def _make_fake_bt():
    bt = MagicMock()
    bt.passes_gate = True
    bt.n_trades = 10
    bt.win_rate = 0.60
    bt.total_return_pct = 15.0
    bt.max_drawdown_pct = 5.0
    bt.expectancy = 1.2
    bt.sharpe = 1.5
    bt.confidence = 65
    bt.summary_text = "ok"
    bt.n_time_exits = 0     # a real int: BacktestOut reads it (F2)
    return bt


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

def _run_process_stock(req, conf_val: float):
    """Run _process_stock with all heavy I/O patched out; returns the raw result."""
    import app.routers.stock_scan as _router_mod

    fake_bars = _make_fake_bars()
    fake_card = _make_fake_card(status="PASS", score=70)
    fake_signal = _make_fake_signal()
    fake_bt = _make_fake_bt()
    conf_cache_hit = {"confidence": conf_val, "sample_size": 50}
    fake_signal_fns = {"pullback_ema": lambda *a, **kw: fake_signal}

    async def run():
        with patch("app.routers.stock_scan.get_historical_bars", new=AsyncMock(return_value=fake_bars)), \
             patch("app.routers.stock_scan.fetch_company_name_async", new=AsyncMock(return_value="Apple Inc")), \
             patch("app.routers.stock_scan.fetch_price_async", new=AsyncMock(return_value=152.0)), \
             patch("app.routers.stock_scan.score_stock", return_value=fake_card), \
             patch("app.routers.stock_scan.compute_omm", return_value=None), \
             patch("app.routers.stock_scan._get_fundamentals", new=AsyncMock(return_value=None)), \
             patch.object(_router_mod, "_SIGNAL_FNS", fake_signal_fns), \
             patch("app.routers.stock_scan._get_backtest_cached", return_value=fake_bt), \
             patch("app.routers.stock_scan.get_cached", return_value=conf_cache_hit):
            from app.routers.stock_scan import _process_stock
            return await _process_stock("AAPL", req, "scan-1", {}, [])

    return asyncio.run(run())


def test_confidence_gate_reject_excludes_low_confidence_symbol():
    """When conf_val < reject_below, _process_stock must return a 'reason' dict."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_reject_below=35.0,
    )
    result = _run_process_stock(req, conf_val=30.0)
    assert "reason" in result, f"Expected exclusion dict with 'reason', got: {result}"
    assert "confidence gate REJECT" in result["reason"]


def test_confidence_gate_caution_caps_pass_to_caution():
    """When reject_below <= conf_val < caution_below, status must be capped at CAUTION."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        confidence_caution_below=50.0,
        confidence_reject_below=35.0,
    )
    result = _run_process_stock(req, conf_val=40.0)
    # Must not be rejected
    assert "reason" not in result, f"Unexpected rejection: {result}"
    # Result is a PositionCardOut; its stock_status must be CAUTION
    from app.schemas.stock_scan import PositionCardOut
    assert isinstance(result, PositionCardOut), f"Expected PositionCardOut, got: {result}"
    assert result.stock_status == "CAUTION", \
        f"Expected CAUTION status, got: {result.stock_status}"


def test_confidence_gate_disabled_preserves_pass_status():
    """When both confidence gate fields are None, the gate is skipped entirely
    and a PASS card must come through as a PositionCardOut with status PASS."""
    req = StockScanRequest(
        universe=["AAPL"], direction="Bullish", horizon="Swing", strategy="pullback_ema",
        # confidence_caution_below, confidence_reject_below both default to None
    )
    result = _run_process_stock(req, conf_val=20.0)  # very low conf_val — gate must not fire
    assert "reason" not in result, (
        f"Gate should be disabled when all confidence fields are None, "
        f"but got exclusion: {result}"
    )
    from app.schemas.stock_scan import PositionCardOut
    assert isinstance(result, PositionCardOut), (
        f"Expected PositionCardOut when gate is disabled, got: {result}"
    )
    assert result.stock_status == "PASS", (
        f"PASS card must be preserved when gate is disabled, got: {result.stock_status}"
    )


async def test_stock_scan_atr_override_cache_key_is_distinct_from_default():
    """stock_scan.py's call sites resolve req.confidence_atr_mult_target/_stop
    (both-or-neither) and pass them through to conf_cache_key exactly as
    routers/stock_scan.py itself does — a per-scan override must key
    distinctly from a default (no-override) scan, or two different Settings
    per-horizon pairs would silently share a cached confidence value."""
    import app.data.confidence_cache as cc
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        original = cc._DB_PATH
        cc._DB_PATH = db_path
        cc._init_db()
        cc.clear_cache()

        default_key = cc.cache_key("AAPL", "Bullish", "Swing", scoring_mode="stock")
        override_key = cc.cache_key("AAPL", "Bullish", "Swing", 3.0, 1.5, scoring_mode="stock")
        assert default_key != override_key

        await cc.set_cached(default_key, {"confidence": 70, "sample_size": 50})
        await cc.set_cached(override_key, {"confidence": 40, "sample_size": 50})
        assert cc.get_cached(default_key)["confidence"] == 70
        assert cc.get_cached(override_key)["confidence"] == 40
    finally:
        cc._DB_PATH = original
        os.unlink(db_path)
