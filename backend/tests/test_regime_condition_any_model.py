from types import SimpleNamespace
from app.services.alert_evaluator import _evaluate_regime_condition


def _cond(model, state, min_conviction=None):
    # Mirror the RegimeCondition shape _evaluate_regime_condition consumes.
    return SimpleNamespace(kind="regime", model=model, state=state, min_conviction=min_conviction)


def test_any_model_matches_when_only_directional_is_bear():
    # OMM says Bull, directional HMM says Bear. A model='any' + 'Bear' condition
    # must fire because at least one model (directional) is Bear.
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM": {"state": "Trending", "conviction": 80},
        "HMM_directional": {"state": "Bear", "conviction": 75},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear"), regime_by_model)
    assert fired is True


def test_any_model_no_match_when_no_model_is_bear():
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM": {"state": "Trending", "conviction": 80},
        "HMM_directional": {"state": "Bull", "conviction": 75},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear"), regime_by_model)
    assert fired is False


def test_any_model_conviction_gate_blocks_directional_bear_below_threshold():
    # HMM_directional is Bear at conviction 60; a min_conviction of 70 must block it
    # (HMM_directional is NOT sign-flipped — only OMM-Bear is). Exercises the
    # conviction branch, not just state matching.
    regime_by_model = {
        "OMM": {"state": "Bull", "conviction": 80},
        "HMM_directional": {"state": "Bear", "conviction": 60},
    }
    fired, _ = _evaluate_regime_condition(_cond("any", "Bear", min_conviction=70), regime_by_model)
    assert fired is False
