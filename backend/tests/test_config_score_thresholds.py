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
