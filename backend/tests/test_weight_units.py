"""Unit tests for score-weight percent overrides unit normalization (#382, defect C4)."""
from unittest.mock import patch
import pytest
import yaml

from app.scoring import stock_scorer as scorer
from app.services.scan_schedule_store import ScanScheduleStore, _SCHEMA_VERSION


SCORES = {"trend": 80, "pullback": 60, "trigger": 40, "event": 20, "vol": 100}


def _mock_rule(name: str):
    def f(*args, **kw):
        r = scorer.RuleResult(name, "PASS", SCORES[name], {})
        return (r, False) if name == "trigger" else r
    return f


def _score(overrides=None, horizon="Swing", mode="options"):
    with patch.multiple(scorer, **{"_rule_" + k: _mock_rule(k) for k in SCORES}):
        return scorer.score_stock(
            "FIXTURE",
            "Bullish",
            horizon,
            [{"close": 100, "volume": 100}],
            overrides=overrides,
            scoring_mode=mode,
        )


def test_baseline_swing_score():
    """Baseline Swing untouched sum is 59 (24 + 12 + 10 + 3 + 10)."""
    card = _score()
    assert card.score == 59
    assert card.explanation["unrounded_score"] == pytest.approx(59.0)


@pytest.mark.parametrize("key,expected_score,expected_contrib", [
    ("weight_trend", 67, 32.0),     # 32 + 12 + 10 + 3 + 10 = 67
    ("weight_pullback", 71, 24.0),  # 24 + 24 + 10 + 3 + 10 = 71
    ("weight_trigger", 65, 16.0),   # 24 + 12 + 16 + 3 + 10 = 65
    ("weight_event", 64, 8.0),      # 24 + 12 + 10 + 8 + 10 = 64
    ("weight_vol", 89, 40.0),       # 24 + 12 + 10 + 3 + 40 = 89
])
def test_all_five_weight_overrides_at_40_percent(key, expected_score, expected_contrib):
    card = _score({key: 40})
    assert card.score == expected_score
    component_name = key.replace("weight_", "")
    assert card.explanation["components"][component_name]["contribution"] == pytest.approx(expected_contrib)


def test_stocks_mode_renormalization_with_40_percent_trend():
    """Stocks mode zeros event weight and renormalizes remaining weights.

    With weight_trend: 40, weights are:
    trend: 0.40, pullback: 0.20, trigger: 0.25, event: 0.0 (zeroed), vol: 0.10.
    Total remaining = 0.40 + 0.20 + 0.25 + 0.10 = 0.95.
    Unnormalized sum = 80*0.4 + 60*0.2 + 40*0.25 + 100*0.10 = 32 + 12 + 10 + 10 = 64.
    Renormalized score = 64 / 0.95 = 67.368 -> rounded to 67.
    """
    card = _score({"weight_trend": 40}, mode="stock")
    assert card.score == 67
    assert card.explanation["unrounded_score"] == pytest.approx(64.0 / 0.95, rel=1e-4)


def test_normalize_weight_direct_caller_inputs():
    """Direct Python callers passing fractions or percentages are correctly normalized."""
    assert scorer._normalize_weight(None) == 0.0
    assert scorer._normalize_weight(0) == 0.0
    assert scorer._normalize_weight(40) == pytest.approx(0.40)
    assert scorer._normalize_weight(100) == pytest.approx(1.0)
    assert scorer._normalize_weight(0.01) == pytest.approx(0.01)
    assert scorer._normalize_weight(0.40) == pytest.approx(0.40)
    assert scorer._normalize_weight(1.0) == pytest.approx(1.0)
    assert scorer._normalize_weight(0.123) == pytest.approx(0.123)


def test_scan_schedule_migration_v2_to_v3(tmp_path):
    """ScanScheduleStore upgrades v2 entries with percentage weights to v3 fractions."""
    v2_content = {
        "version": 2,
        "entries": [
            {
                "id": "e_options",
                "mode": "options",
                "label": "Options Schedule",
                "resolved_request": {
                    "universe": ["SP500"],
                    "direction": "Bullish",
                    "horizon": "Swing",
                    "overrides": {
                        "weight_trend": 40,
                        "weight_event": 1,
                        "weight_vol": 100,
                        "fast_ema": 12,
                    },
                },
            },
            {
                "id": "e_stocks",
                "mode": "stocks",
                "label": "Stocks Schedule",
                "resolved_request": {
                    "universe": ["AAPL"],
                    "direction": "Bullish",
                    "horizon": "Swing",
                    "hold_min_days": 5,
                    "hold_max_days": 15,
                    "overrides": {
                        "weight_trend": 30,
                        "weight_pullback": 20,
                    },
                },
            },
        ],
    }

    yaml_file = tmp_path / "scan_schedule.yaml"
    yaml_file.write_text(yaml.safe_dump(v2_content), encoding="utf-8")

    store = ScanScheduleStore(path=yaml_file)
    assert store.load_error is None

    # Check in-memory loaded state
    e_opt = store.get("e_options")
    assert e_opt is not None
    ov_opt = e_opt["resolved_request"]["overrides"]
    assert ov_opt["weight_trend"] == pytest.approx(0.40)
    assert ov_opt["weight_event"] == pytest.approx(0.01)
    assert ov_opt["weight_vol"] == pytest.approx(1.0)
    assert ov_opt["fast_ema"] == 12

    e_stk = store.get("e_stocks")
    assert e_stk is not None
    ov_stk = e_stk["resolved_request"]["overrides"]
    assert ov_stk["weight_trend"] == pytest.approx(0.30)
    assert ov_stk["weight_pullback"] == pytest.approx(0.20)

    # Check migrated file on disk has version 3 and backup was created
    disk_content = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
    assert disk_content["version"] == _SCHEMA_VERSION == 3

    backups = list(tmp_path.glob("scan_schedule.bak.*.yaml"))
    assert len(backups) == 1
