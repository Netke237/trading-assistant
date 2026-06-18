import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.scoring.stock_scorer import score_stock
from app.scoring.fundamentals_scorer import FundamentalHealth

_GATE = {"enabled": True, "cautionBelow": 45, "rejectBelow": 30,
         "cautionAbove": 70, "rejectAbove": 80}

def _flat_bars(n=260, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1_000_000, "time": i} for i in range(n)]

def _health(score: int):
    return FundamentalHealth(
        score=score,
        quality_label="Neutral",
        risk_label="Medium",
        growth_score=score,
        quality_score=score,
        risk_score=score,
        safety_flags=[],
        detail={},
    )

def _fund_rule(card):
    return next(r for r in card.rules if r.name == "fundamentals")

def test_bearish_demotes_strong_fundamentals():
    card = score_stock("AAPL", direction="Bearish", horizon="Swing",
                       bars=_flat_bars(), fundamentals=_health(90),
                       fundamentals_gate=_GATE)
    assert _fund_rule(card).status in ("CAUTION", "REJECT")

def test_bearish_passes_weak_fundamentals():
    card = score_stock("XYZ", direction="Bearish", horizon="Swing",
                       bars=_flat_bars(), fundamentals=_health(20),
                       fundamentals_gate=_GATE)
    assert _fund_rule(card).status == "PASS"
