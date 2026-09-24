import yaml
from pathlib import Path

CONFIG_DIR = Path(__file__).parent.parent / "config"


def test_contract_rules_has_contract_score_thresholds():
    cfg = yaml.safe_load((CONFIG_DIR / "contract_rules.yaml").read_text())
    assert "contract_score_thresholds" in cfg
    assert set(cfg["contract_score_thresholds"].keys()) == {"pass", "caution"}
    assert cfg["contract_score_thresholds"]["pass"] > cfg["contract_score_thresholds"]["caution"]


def test_scoring_rules_has_stock_score_thresholds():
    cfg = yaml.safe_load((CONFIG_DIR / "scoring_rules.yaml").read_text())
    assert "stock_score_thresholds" in cfg
    assert set(cfg["stock_score_thresholds"].keys()) == {"pass", "caution"}
    assert cfg["stock_score_thresholds"]["pass"] > cfg["stock_score_thresholds"]["caution"]


def test_stop_premium_thresholds_are_coherent():
    """One threshold, two outcomes (PASS / CAUTION) — per D8 the gate never
    REJECTs and never paints red, so there is deliberately no reject_fraction.
    Asserted where the value lives, each horizon's `stop_premium` block in
    scoring_rules.yaml: exactly one key, so a re-added reject_fraction fails
    here instead of being silently ignored by the scorer. The value the gate
    actually reads, via pass_max_fraction_for, is a fraction of premium in
    (0, 1]."""
    from app.scoring.stop_cost import pass_max_fraction_for
    from app.services.config_loader import load_scoring_cfg

    horizons = load_scoring_cfg()["horizons"]
    for label, key in [("Intraday", "intraday"), ("Swing", "swing"), ("Position", "position")]:
        block = horizons[key]["stop_premium"]
        assert set(block) == {"pass_max_fraction"}, f"{label}: unexpected keys {set(block)}"
        frac = pass_max_fraction_for(label)
        assert 0 < frac <= 1.0, f"{label}: pass_max_fraction={frac}"
