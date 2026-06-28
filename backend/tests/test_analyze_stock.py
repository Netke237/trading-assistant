from app.schemas.stock_scan import (
    StockAnalysisOut, StockAnalysisRequest, GateFlag, RuleContribution,
    EmaTrendOut, RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)


def test_stock_analysis_out_minimal():
    out = StockAnalysisOut(
        symbol="AMD", company="Advanced Micro Devices Inc", price=100.0,
        direction="Bullish", stock_score=55, stock_status="PASS",
        is_index=False,
    )
    assert out.symbol == "AMD"
    assert out.is_index is False
    assert out.gate_flags == []
    assert out.regime_by_horizon == {}
    assert out.strategy is None      # optional — None when no signal
    assert out.backtest is None


def test_gate_flag_shape():
    g = GateFlag(gate="backtest", status="CAUTION", detail="win rate 0.41 < 0.50")
    assert g.gate == "backtest"
    assert g.status == "CAUTION"


def test_rule_contribution_matches_ruleresult_fields():
    r = RuleContribution(name="trend", status="PASS", score=80, detail={"adx": 34})
    assert r.name == "trend"
    assert r.status == "PASS"
    assert r.score == 80


def test_analysis_request_defaults():
    # StockAnalysisRequest must be constructible from symbol alone (defaults supply the rest).
    req = StockAnalysisRequest(symbol="AMD")
    assert req.symbol == "AMD"
    assert req.horizon == "Swing"
    assert req.direction == "Bullish"
    assert req.strategy == "pullback_ema"
    assert req.universe == []


import pytest


@pytest.mark.asyncio
async def test_analyze_core_low_score_still_returns(monkeypatch):
    """A symbol the scanner would REJECT still yields a core result + gate_flags."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    # Stub history + price so the test is deterministic & offline.
    bars = [{"time": i, "open": 100, "high": 101, "low": 99, "close": 100 + (i % 3), "volume": 1_000_000} for i in range(300)]

    async def _fake_bars(symbol, start, end):
        return bars

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})

    async def _fake_name(client, symbol):
        return "Test Co"

    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "fetch_intraday_candles", lambda *a, **k: [])

    req = StockAnalysisRequest(symbol="TEST", direction="Bullish", horizon="Swing",
                               strategy="pullback_ema")
    core = await ss._analyze_core("TEST", req)
    assert core.card is not None
    assert hasattr(core, "gate_flags")
    assert isinstance(core.gate_flags, list)
    # signal may be None (flat synthetic series → no setup); that is allowed.
