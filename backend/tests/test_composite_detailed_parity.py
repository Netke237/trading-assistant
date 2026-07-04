from unittest.mock import patch

from app.services.composite_trigger_evaluator import (
    evaluate_from_context, describe_match, evaluate_from_context_detailed,
)

TRIGGER = {
    "primary": {"model": "any"},
    "confirmations": [], "min_confirmations": 0,
    "strategy_confirmations": [], "min_strategy_confirmations": 0,
    "direction": "Bullish",
}


def test_detailed_matches_two_call_sequence_when_fired():
    fired_old = evaluate_from_context(TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[])
    detail_old = describe_match(TRIGGER, structure_signals=[], indicator_values={},
                                bars_daily=[], bars_intraday=[], direction="Bullish")
    fired_new, detail_new = evaluate_from_context_detailed(
        TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[], direction="Bullish",
    )
    assert fired_new == fired_old
    assert detail_new == detail_old


def test_detailed_returns_none_detail_when_not_fired():
    trig = {**TRIGGER, "primary": {"model": "OMM", "to_state": "Bull"}}
    # OMM primary required but omm_result is None -> should not fire, detail None.
    fired_new, detail_new = evaluate_from_context_detailed(
        trig, None, [], {}, bars_daily=[], bars_intraday=[], direction="Bullish",
    )
    assert fired_new is False
    assert detail_new is None


def test_detailed_threads_symbol_into_describe_match():
    # Locks in the finding-4 fix: the symbol kwarg must reach describe_match (it is
    # otherwise inert on the router path, so mock describe_match and assert directly).
    with patch("app.services.composite_trigger_evaluator.describe_match") as mock_desc:
        mock_desc.return_value = {
            "structure_matched": [], "structure_total": 0,
            "strategy_matched": [], "strategy_total": 0,
        }
        fired, _ = evaluate_from_context_detailed(
            TRIGGER, None, [], {}, bars_daily=[], bars_intraday=[],
            direction="Bullish", symbol="AAPL",
        )
    assert fired is True
    assert mock_desc.call_args.kwargs["symbol"] == "AAPL"
