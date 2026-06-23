import yaml
from pathlib import Path

CFG = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"

def test_regime_config_blocks_present():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["regime"]["intraday"]["timeframe"] == "15min"
    assert cfg["regime"]["swing"]["timeframe"] == "daily"
    assert cfg["regime_gate"]["headwind_caution_pct"] == -15
    assert cfg["regime_gate"]["headwind_reject_pct"] == -40
    assert cfg["regime_sizing"]["enabled"] is True


# ---------------------------------------------------------------------------
# A7: Regime demote-only gate inside score_stock
# ---------------------------------------------------------------------------

from datetime import date
from app.scoring.stock_scorer import score_stock


def _flat_bars(n=200):
    return [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1_000_000} for _ in range(n)]


def test_regime_gate_demotes_on_strong_headwind_and_adds_no_points():
    gate = {"enabled": True, "headwind_caution_pct": -15, "headwind_reject_pct": -40,
            "require_stable_for_reject": True}
    signal = {"state": "Bear", "p_stay": 0.85, "stability": "Stable", "regime_age_days": 10,
               "avg_regime_duration": 6.0, "conviction_pct": -50, "conviction_label": "Strong headwind",
               "interpretation": "...", "hmm_state": "Bear", "alignment": "Aligned",
               "timeframe": "daily", "horizon": "Swing"}
    card = score_stock("X", "Bullish", "Swing", _flat_bars(),
                       regime_signal=signal, regime_gate=gate, scoring_mode="stock")
    assert card.status == "REJECT"                      # strong headwind + stable -> reject cap
    reg = [r for r in card.rules if r.name == "regime"][0]
    # gate row must exist
    assert reg is not None
    # demote-only: zero points added - score must equal a no-gate run
    base = score_stock("X", "Bullish", "Swing", _flat_bars(), scoring_mode="stock")
    assert card.score == base.score                     # demote-only: zero points added


def test_regime_gate_caution_on_mild_headwind():
    gate = {"enabled": True, "headwind_caution_pct": -15, "headwind_reject_pct": -40,
            "require_stable_for_reject": True}
    signal = {"state":"Bear","p_stay":0.7,"stability":"Fragile","regime_age_days":5,
              "avg_regime_duration":4.0,"conviction_pct":-20,"conviction_label":"Mild headwind",
              "interpretation":"...","hmm_state":None,"alignment":"Unavailable",
              "timeframe":"daily","horizon":"Swing"}
    card = score_stock("X","Bullish","Swing",_flat_bars(),
                       regime_signal=signal, regime_gate=gate, scoring_mode="stock")
    # Regime rule must exist with CAUTION status for this conviction range
    reg = [r for r in card.rules if r.name == "regime"][0]
    assert reg.status == "CAUTION"
    # Overall card status is capped at CAUTION or lower (never higher than the gate)
    assert card.status != "PASS"


def test_regime_gate_bypassed_when_disabled():
    gate = {"enabled": False, "headwind_caution_pct": -15, "headwind_reject_pct": -40,
            "require_stable_for_reject": True}
    signal = {"state":"Bear","p_stay":0.9,"stability":"Stable","regime_age_days":20,
              "avg_regime_duration":15.0,"conviction_pct":-60,"conviction_label":"Strong headwind",
              "interpretation":"...","hmm_state":"Bear","alignment":"Aligned",
              "timeframe":"daily","horizon":"Swing"}
    base = score_stock("X","Bullish","Swing",_flat_bars(), scoring_mode="stock")
    card = score_stock("X","Bullish","Swing",_flat_bars(),
                       regime_signal=signal, regime_gate=gate, scoring_mode="stock")
    # Gate disabled → status unchanged, score unchanged, but "regime" rule still appended with PASS
    assert card.score == base.score
    assert card.status == base.status


# ---------------------------------------------------------------------------
# A8: SentimentData schema + conviction/alignment fields
# ---------------------------------------------------------------------------

def test_sentiment_schema_constructs():
    from app.schemas import SentimentData, ScoreBreakdown, MarketRegime
    s = SentimentData(horizon="Swing", timeframe="daily", state="Bull", p_stay=0.7,
                      stability="Stable", regime_age_days=5, avg_regime_duration=8.0,
                      conviction_pct=40, conviction_label="Strong tailwind",
                      interpretation="x", alignment="Aligned")
    assert s.conviction_pct == 40
    sb = ScoreBreakdown(trend=1, pullback=1, trigger=1, event=1, volatility=1, sentiment=s)
    assert sb.sentiment.state == "Bull"
