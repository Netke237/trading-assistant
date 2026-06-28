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
