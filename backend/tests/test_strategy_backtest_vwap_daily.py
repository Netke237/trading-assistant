"""TRADING-REVIEW-PHASE-C-HYGIENE T3: mean_reversion_vwap_daily runs in the backtest
and the evidence harness.

The evidence scripts are added to sys.path the same way tests/test_evidence_harness.py
does it.
"""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from app.services.strategy_backtest import run_strategy_backtest  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "AAPL_candles.json"


def test_vwap_daily_backtest_is_a_known_strategy():
    bars = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(bars) >= 100

    result = run_strategy_backtest(bars, strategy="mean_reversion_vwap_daily", direction="Bullish")

    assert "Unknown strategy" not in result.summary_text
    assert result.strategy == "mean_reversion_vwap_daily"


def test_vwap_daily_is_in_the_evidence_harness_strategies():
    from evidence import gate_persistence

    assert "mean_reversion_vwap_daily" in gate_persistence.DAILY_STRATEGIES
