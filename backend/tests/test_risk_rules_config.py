import yaml
from pathlib import Path

RISK_YAML = Path(__file__).parent.parent / "config" / "risk_rules.yaml"


def test_dead_keys_stay_removed():
    """Guard against reintroducing keys removed in Phase D config cleanup (M10)."""
    cfg = yaml.safe_load(RISK_YAML.read_text())
    assert "default_contracts" not in cfg["sizing"]
    assert "bullish_invalidation_pct" not in cfg["reward_risk"]
    assert "bearish_invalidation_pct" not in cfg["reward_risk"]


def test_gap_threshold_pct_is_intentionally_reserved():
    """auto_trade.gap_threshold_pct has no read site by design — see comment in risk_rules.yaml.
    This test exists so a future cleanup pass doesn't re-flag it as accidental dead config."""
    cfg = yaml.safe_load(RISK_YAML.read_text())
    assert "gap_threshold_pct" in cfg["auto_trade"]
    assert 0 < cfg["auto_trade"]["gap_threshold_pct"] < 1
