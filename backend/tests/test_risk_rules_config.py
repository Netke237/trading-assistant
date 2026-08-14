import yaml
from pathlib import Path

RISK_YAML = Path(__file__).parent.parent / "config" / "risk_rules.yaml"


def test_dead_keys_stay_removed():
    """Guard against reintroducing keys confirmed to have zero read sites.

    Phase D config cleanup (M10) originally removed default_contracts,
    bullish_invalidation_pct, and bearish_invalidation_pct as dead config.
    The latter two stopped being dead afterward: trade_plan.py's
    invalidation_price calculation reads rr_cfg["bullish_invalidation_pct"]/
    ["bearish_invalidation_pct"] directly (fixing what its own comment
    describes as a "pre-existing bug" where they were documented but never
    read) — removing them now would raise a KeyError on every trade-plan
    build. default_contracts remains genuinely unused (verified: zero read
    sites in backend/app/) and stays removed."""
    cfg = yaml.safe_load(RISK_YAML.read_text())
    assert "default_contracts" not in cfg["sizing"]
    assert "bullish_invalidation_pct" in cfg["reward_risk"]
    assert "bearish_invalidation_pct" in cfg["reward_risk"]


def test_gap_threshold_pct_is_intentionally_reserved():
    """auto_trade.gap_threshold_pct has no read site by design — see comment in risk_rules.yaml.
    This test exists so a future cleanup pass doesn't re-flag it as accidental dead config."""
    cfg = yaml.safe_load(RISK_YAML.read_text())
    assert "gap_threshold_pct" in cfg["auto_trade"]
    assert 0 < cfg["auto_trade"]["gap_threshold_pct"] < 1
