"""STOCKS-HORIZON-P0A A5: missing confidence is "Unvalidated" and caps at CAUTION.

Before: status_cap(None, gate) returned PASS ("gate not applied"), and the two
stocks sites in routers/stock_scan.py applied their thresholds only to a measured
confidence, so a card with fewer than min_samples non-overlapping past setups
could PASS on both paths.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import stock_scan as ss
from app.schemas.stock_scan import PositionCardOut, StockAnalysisRequest, StockScanRequest
from app.scoring.signal_confidence import ConfidenceResult, interpret, status_cap
from app.scoring.stock_scorer import score_stock

GATE_ON = {"enabled": True, "cautionBelow": 50, "rejectBelow": 35}
GATE_OFF = {"enabled": False, "cautionBelow": 50, "rejectBelow": 35}
_FIXTURES = Path(__file__).parent / "fixtures"


# ── 1. status_cap ────────────────────────────────────────────────────────────

def test_status_cap_none_is_caution_with_gate_enabled():
    assert status_cap(None, GATE_ON) == "CAUTION"


def test_status_cap_none_is_caution_with_gate_disabled():
    assert status_cap(None, GATE_OFF) == "CAUTION"


def test_disabled_gate_still_never_demotes_a_measured_confidence():
    assert status_cap(10, GATE_OFF) == "PASS"


def test_interpret_none_reads_unvalidated():
    txt = interpret(None, sample_size=12, symbol="AAPL", min_samples=20)
    assert txt == (
        "Unvalidated — fewer than 20 non-overlapping past setups on AAPL (12 found). "
        "Capped at CAUTION until there is enough history."
    )


def test_interpret_min_samples_defaults_to_20():
    assert "fewer than 20 " in interpret(None, sample_size=3, symbol="X")


# ── 2. score_stock (options path and every caller that passes the gate) ─────

def test_score_stock_none_confidence_caps_a_pass_card_at_caution():
    bars = json.loads((_FIXTURES / "NVDA_candles.json").read_text())
    base = score_stock(symbol="NVDA", direction="Bullish", horizon="Swing", bars=bars)
    assert base.status == "PASS"          # the fixture otherwise PASSes
    card = score_stock(symbol="NVDA", direction="Bullish", horizon="Swing", bars=bars,
                       confidence=None, confidence_gate=GATE_ON, confidence_sample_size=7)
    assert card.status == "CAUTION"
    cap = next(c for c in card.explanation["caps"] if c["name"] == "confidence")
    assert cap["status"] == "CAUTION" and cap["before"] == "PASS"
    rule = next(r for r in card.rules if r.name == "confidence")
    assert rule.detail["interpretation"].startswith("Unvalidated — fewer than 20 ")


# ── 3. /stock-scan per-symbol function ──────────────────────────────────────

def _fake_card(status: str = "PASS"):
    from app.scoring.stock_scorer import RuleResult, StockScoreCard
    return StockScoreCard(symbol="AAPL", direction="Bullish", horizon="Swing", score=70,
                          status=status,
                          rules=[RuleResult(name="trend", status="PASS", score=60, detail={})])


def _fake_signal():
    sig = MagicMock()
    sig.strategy = "pullback_ema"
    sig.entry_price, sig.stop_price, sig.target_price = 152.0, 148.0, 160.0
    sig.targets, sig.rr_ratio, sig.atr, sig.detail = [160.0], 2.0, 3.0, {}
    return sig


def _fake_bt():
    return MagicMock(passes_gate=True, n_trades=10, win_rate=0.6, total_return_pct=15.0,
                     max_drawdown_pct=5.0, expectancy=1.2, sharpe=1.5, confidence=65,
                     summary_text="ok", n_time_exits=0)


def _run_process_stock(req, *, card_status: str = "PASS"):
    bars = [{"time": f"2024-01-{i:02d}", "open": 150.0, "high": 155.0, "low": 148.0,
             "close": 152.0, "volume": 1_000_000} for i in range(1, 131)]

    async def run():
        with patch.object(ss, "get_historical_bars", new=AsyncMock(return_value=bars)), \
             patch.object(ss, "fetch_company_name_async", new=AsyncMock(return_value="Apple Inc")), \
             patch.object(ss, "fetch_price_async", new=AsyncMock(return_value=152.0)), \
             patch.object(ss, "score_stock", return_value=_fake_card(card_status)), \
             patch.object(ss, "compute_omm", return_value=None), \
             patch.object(ss, "_get_fundamentals", new=AsyncMock(return_value=None)), \
             patch.object(ss, "_SIGNAL_FNS", {"pullback_ema": lambda *a, **kw: _fake_signal()}), \
             patch.object(ss, "_get_backtest_cached", return_value=_fake_bt()), \
             patch.object(ss, "get_cached", return_value=None), \
             patch.object(ss, "set_cached", new=AsyncMock()), \
             patch.object(ss, "compute_confidence",
                          return_value=ConfidenceResult(None, 0.6, 12, 3)):
            return await ss._process_stock("AAPL", req, "scan-1", {}, [])

    return asyncio.run(run())


def test_stock_scan_unvalidated_pass_card_is_caution_and_kept():
    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema",
                           confidence_caution_below=50.0, confidence_reject_below=35.0)
    result = _run_process_stock(req)
    assert isinstance(result, PositionCardOut), f"symbol must not be dropped, got {result}"
    assert result.stock_status == "CAUTION"
    assert result.confidence is None
    assert result.confidence_text.startswith("Unvalidated")
    assert "(12 found)" in result.confidence_text


def test_stock_scan_unvalidated_caps_even_with_gate_fields_unset():
    req = StockScanRequest(universe=["AAPL"], direction="Bullish", horizon="Swing",
                           strategy="pullback_ema")
    result = _run_process_stock(req)
    assert isinstance(result, PositionCardOut)
    assert result.stock_status == "CAUTION"


# ── 4. _analyze_core / /analyze-stock ───────────────────────────────────────

_BARS = [{"time": 1_700_000_000 + i * 86400, "open": 100, "high": 101, "low": 99,
          "close": 100 + (i % 3), "volume": 1_000_000} for i in range(300)]


@dataclasses.dataclass
class _Card:
    score: int = 70
    status: str = "PASS"
    rules: list = dataclasses.field(default_factory=list)


def _offline_with_unvalidated_signal(monkeypatch, card_status: str = "PASS"):
    async def _fake_bars(symbol, start, end):
        return _BARS

    async def _fake_name(client, symbol):
        return "Test Co"

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: [])
    monkeypatch.setattr(ss, "compute_directional_hmm", lambda bars: None)
    omm = types.SimpleNamespace(
        state="Bull", p_stay=0.8, stability="Stable", regime_age_days=5,
        avg_regime_duration=10.0, conviction_pct=10, conviction_label="Tailwind",
        interpretation="", transition_row=[], state_order=[])
    monkeypatch.setattr(ss, "compute_omm", lambda *a, **k: omm)
    monkeypatch.setattr(ss, "score_stock", lambda **kw: _Card(status=card_status))
    sig = MagicMock(entry_price=100.0, stop_price=95.0, target_price=110.0, targets=[110.0],
                    rr_ratio=2.0, atr=2.0, detail={}, strategy="pullback_ema")
    monkeypatch.setitem(ss._SIGNAL_FNS, "pullback_ema", MagicMock(return_value=sig))
    monkeypatch.setattr(ss, "_get_backtest_cached", lambda key: _fake_bt())
    monkeypatch.setattr(ss, "get_cached", lambda key: {"confidence": None, "sample_size": 12})


@pytest.mark.asyncio
async def test_analyze_core_unvalidated_flags_caution(monkeypatch):
    _offline_with_unvalidated_signal(monkeypatch)
    core = await ss._analyze_core("TEST", StockAnalysisRequest(
        symbol="TEST", confidence_caution_below=50, confidence_reject_below=30))
    assert core.card.status == "CAUTION"
    flags = [g for g in core.gate_flags if g["gate"] == "confidence"]
    assert flags == [{"gate": "confidence", "status": "CAUTION",
                      "detail": "Unvalidated: 12 non-overlapping samples (< 20)"}]
    assert core.conf_txt.startswith("Unvalidated")


@pytest.mark.asyncio
async def test_analyze_core_unvalidated_never_lowers_a_reject(monkeypatch):
    _offline_with_unvalidated_signal(monkeypatch, card_status="REJECT")
    core = await ss._analyze_core("TEST", StockAnalysisRequest(symbol="TEST"))
    assert core.card.status == "REJECT"


@pytest.mark.asyncio
async def test_analyze_stock_endpoint_shows_the_unvalidated_flag(monkeypatch):
    _offline_with_unvalidated_signal(monkeypatch)

    async def _none():
        return None
    monkeypatch.setattr(ss, "_market_backdrop", _none)
    out = await ss.analyze_stock(StockAnalysisRequest(symbol="TEST"))
    assert out.stock_status == "CAUTION"
    flags = [g for g in out.gate_flags if g.gate == "confidence"]
    assert [(g.status, g.detail) for g in flags] == [
        ("CAUTION", "Unvalidated: 12 non-overlapping samples (< 20)")]
    assert out.confidence_text.startswith("Unvalidated")
