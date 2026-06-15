import yaml
from pathlib import Path

CFG = Path(__file__).parent.parent / "config" / "scoring_rules.yaml"

def test_regime_config_blocks_present():
    cfg = yaml.safe_load(CFG.read_text())
    assert cfg["regime"]["intraday"]["timeframe"] == "15min"
    assert cfg["regime"]["swing"]["timeframe"] == "daily"
    assert cfg["regime_gate"]["headwind_caution_pct"] == -15
    assert cfg["regime_gate"]["headwind_reject_pct"] == -40
    assert cfg["regime_sizing"]["enabled"] is False


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
