"""PB-PRES-04 additive live evidence, without recalculation."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.routers import stock_scan as ss
from app.schemas import StockExplanation
from app.schemas.stock_scan import StockAnalysisOut, StockAnalysisRequest
from app.scoring.stock_scorer import score_stock


def test_old_analysis_payload_remains_valid():
    out = StockAnalysisOut(symbol="TEST", company="Test", price=10, direction="Bullish", stock_score=0, stock_status="REJECT")
    assert out.stock_explanation is None


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
@pytest.mark.parametrize("horizon", ["Intraday", "Swing", "Position"])
@pytest.mark.parametrize("evidence", ["valid", "absent", "invalid"])
async def test_analysis_projects_card_without_changing_result(monkeypatch, direction, horizon, evidence):
    bars = [{"time": i, "open": 100+i*.1, "high": 101+i*.1, "low": 99+i*.1, "close": 100+i*.1, "volume": 1000000} for i in range(300)]
    card = score_stock(symbol="TEST", direction=direction, horizon=horizon, bars=bars, scoring_mode="stock")
    original = deepcopy(card.explanation)
    card.explanation = original if evidence == "valid" else None if evidence == "absent" else {"version": 999}
    core = SimpleNamespace(card=card, company="Test Co", price=100, daily_bars=bars, daily_regime_bars=bars, intraday_bars=[], signal=None, bt_result=None, fundamentals=None, conf_val=None, conf_txt=None, regime_signal=None, next_event_days=None, next_event_label=None, earnings_days=None, earnings_veto=False, gate_flags=[{"gate":"backtest", "status":"REJECT", "detail":"No setup"}])
    async def fake_core(symbol, req): return core
    async def sector(*args): return None, None
    async def backdrop(): return None
    monkeypatch.setattr(ss, "_analyze_core", fake_core)
    monkeypatch.setattr(ss, "_sector_context", sector)
    monkeypatch.setattr(ss, "_market_backdrop", backdrop)
    results = [await ss.analyze_stock(StockAnalysisRequest(symbol="test", direction=direction, horizon=horizon, strategy=strategy)) for strategy in ["pullback_ema", "breakout_base"]]
    for out in results:
        assert out.stock_score == card.score and out.stock_status == card.status
        assert out.strategy is None and out.confidence is None
        assert out.gate_flags[0].status == "REJECT"
        assert out.stock_explanation == (StockExplanation.model_validate(original) if evidence == "valid" else None)
