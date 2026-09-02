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


def test_stop_premium_thresholds_endpoint_mirrors_yaml():
    """The stop-vs-premium gate's per-horizon threshold is served from
    scoring_rules.yaml, not hardcoded on the client — same single-source-of-truth
    contract as /event-thresholds and /iv-thresholds."""
    from app.routers.config import get_stop_premium_thresholds
    from app.services.config_loader import load_scoring_cfg

    out = get_stop_premium_thresholds()
    horizons = load_scoring_cfg()["horizons"]

    assert set(out) == {"Intraday", "Swing", "Position"}
    for label, key in [("Intraday", "intraday"), ("Swing", "swing"), ("Position", "position")]:
        assert out[label]["pass_max_fraction"] == horizons[key]["stop_premium"]["pass_max_fraction"]


def test_stop_premium_thresholds_are_coherent():
    """One threshold, two outcomes (PASS / CAUTION) — per D8 the gate never
    REJECTs and never paints red, so there is deliberately no reject_fraction.
    The payload shape is asserted exactly: HorizonStopPremiumThresholds on the
    client declares this single key, so a second one reappearing here would
    drift the two apart silently. The value is a fraction of premium in (0, 1].
    """
    from app.routers.config import get_stop_premium_thresholds

    for label, pair in get_stop_premium_thresholds().items():
        assert set(pair) == {"pass_max_fraction"}, f"{label}: unexpected keys {set(pair)}"
        frac = pair["pass_max_fraction"]
        assert 0 < frac <= 1.0, f"{label}: pass_max_fraction={frac}"
