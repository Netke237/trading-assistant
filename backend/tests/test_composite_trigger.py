"""Tests for composite trigger evaluator."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from app.services.composite_trigger_evaluator import evaluate_from_context, evaluate_scheduled


def _make_trigger(
    model="OMM",
    to_state="Choppy",
    conviction_min=50,
    p_stay_min=0.5,
    confirmations=None,
    min_confirmations=1,
):
    return {
        "primary": {
            "model": model,
            "to_state": to_state,
            "conviction_min": conviction_min,
            "p_stay_min": p_stay_min,
            "p_transition_min": 0.3,
        },
        "confirmations": confirmations or [],
        "min_confirmations": min_confirmations,
        "horizon": "swing",
    }


def _make_omm(state="Choppy", conviction_pct=75.0, p_stay=0.8):
    omm = MagicMock()
    omm.state = state
    omm.conviction_pct = conviction_pct
    omm.p_stay = p_stay
    return omm


def test_evaluate_from_context_primary_met_zero_confirmations():
    """Primary met + min_confirmations=0 → True."""
    trigger = _make_trigger(to_state="Choppy", conviction_min=50, min_confirmations=0)
    assert evaluate_from_context(trigger, _make_omm("Choppy", 75), [], {}) is True


def test_evaluate_from_context_conviction_too_low():
    """OMM conviction below threshold → False."""
    trigger = _make_trigger(conviction_min=80, min_confirmations=0)
    assert evaluate_from_context(trigger, _make_omm("Choppy", 60), [], {}) is False


def test_evaluate_from_context_wrong_state():
    """OMM in 'Bull' when 'Choppy' required → False."""
    trigger = _make_trigger(to_state="Choppy", min_confirmations=0)
    assert evaluate_from_context(trigger, _make_omm("Bull", 80), [], {}) is False


def test_evaluate_from_context_omm_none():
    """None OmmResult → False."""
    trigger = _make_trigger(min_confirmations=0)
    assert evaluate_from_context(trigger, None, [], {}) is False


def test_evaluate_from_context_confirmations_met():
    """Primary met + 2/3 confirmations with min=2 → True."""
    trigger = _make_trigger(
        min_confirmations=2,
        confirmations=[
            {"type": "structure", "signal_kind": "FVG", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "CHoCH", "direction": "Bullish", "min_confidence": 60},
        ],
    )
    structure_signals = [
        {"kind": "FVG", "direction": "bullish", "confidence": 80},
        {"kind": "BOS", "direction": "bullish", "confidence": 70},
    ]
    assert evaluate_from_context(trigger, _make_omm(), structure_signals, {}) is True


def test_evaluate_from_context_confirmations_not_met():
    """Only 1/3 confirmations with min=2 → False."""
    trigger = _make_trigger(
        min_confirmations=2,
        confirmations=[
            {"type": "structure", "signal_kind": "FVG", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 60},
        ],
    )
    structure_signals = [{"kind": "FVG", "direction": "bullish", "confidence": 80}]
    assert evaluate_from_context(trigger, _make_omm(), structure_signals, {}) is False


def test_evaluate_from_context_any_model_skips_primary():
    """model='any' with min_confirmations=0 → True regardless of omm_result."""
    trigger = _make_trigger(model="any", min_confirmations=0)
    assert evaluate_from_context(trigger, None, [], {}) is True


def test_evaluate_from_context_strategy_confirmations_missing_bars_fails_closed():
    """strategy_confirmations configured but no bars passed → treated as not met."""
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
    }
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=[], bars_intraday=[]) is False
    # Also cover the case where the caller omits the new kwargs entirely (defaults) —
    # a plausible production call shape, distinct from explicitly passing empty lists.
    assert evaluate_from_context(trigger, None, [], {}) is False


def test_evaluate_from_context_strategy_confirmations_met_with_bars(monkeypatch):
    """strategy_confirmations configured, bars_daily supplied, strategy fn confirms → True."""
    from unittest.mock import MagicMock
    import app.services.strategy_engine as strategy_engine
    monkeypatch.setattr(
        strategy_engine, "mean_reversion_rsi_signal",
        lambda bars, direction="Bullish": MagicMock(),
    )
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
        "direction": "Bullish",
    }
    bars_daily = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
        for _ in range(70)
    ]
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars_daily, bars_intraday=[]) is True


def test_evaluate_from_context_strategy_confirmations_not_met_with_bars(monkeypatch):
    """strategy_confirmations configured, bars_daily supplied, strategy fn does not confirm → False."""
    import app.services.strategy_engine as strategy_engine
    monkeypatch.setattr(
        strategy_engine, "mean_reversion_rsi_signal",
        lambda bars, direction="Bullish": None,
    )
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi"],
        "min_strategy_confirmations": 1,
        "direction": "Bullish",
    }
    bars_daily = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
        for _ in range(70)
    ]
    assert evaluate_from_context(trigger, None, [], {}, bars_daily=bars_daily, bars_intraday=[]) is False


def test_evaluate_from_context_no_strategy_confirmations_configured_unaffected():
    """No strategy_confirmations key at all — behavior identical to before this change."""
    trigger = _make_trigger(to_state="Choppy", conviction_min=50, min_confirmations=0)
    assert evaluate_from_context(trigger, _make_omm("Choppy", 75), [], {}) is True


def test_evaluate_scheduled_returns_bool():
    """evaluate_scheduled returns a bool (mock bars — may return False due to insufficient data)."""
    trigger = _make_trigger(model="OMM", to_state="Choppy", min_confirmations=0)
    bars = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
            for _ in range(30)]
    result = evaluate_scheduled("TEST", trigger, bars_daily=bars, bars_intraday=[])
    assert isinstance(result, bool)


def test_describe_match_reports_matched_structure_names():
    from app.services.composite_trigger_evaluator import describe_match, format_composite_reason
    trigger = _make_trigger(
        min_confirmations=2,
        confirmations=[
            {"type": "structure", "signal_kind": "FVG", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "BOS", "direction": "Bullish", "min_confidence": 60},
            {"type": "structure", "signal_kind": "CHoCH", "direction": "Bullish", "min_confidence": 60},
        ],
    )
    structure_signals = [
        {"kind": "FVG", "direction": "bullish", "confidence": 80},
        {"kind": "BOS", "direction": "bullish", "confidence": 70},
    ]
    detail = describe_match(trigger, structure_signals=structure_signals)
    assert detail["structure_matched"] == ["FVG", "BOS"]
    assert detail["structure_total"] == 3
    reason = format_composite_reason("Choppy", detail)
    assert reason == "Composite Markov trigger: Choppy regime — 2/3 structures matched (FVG, BOS)"


def test_describe_match_reports_matched_strategy_names():
    from app.services.composite_trigger_evaluator import describe_match, format_composite_reason
    trigger = {
        "primary": {"model": "any"},
        "confirmations": [],
        "min_confirmations": 0,
        "strategy_confirmations": ["mean_reversion_rsi", "mean_reversion_bb"],
        "min_strategy_confirmations": 1,
    }
    detail = describe_match(trigger, bars_daily=[], bars_intraday=[])
    assert detail["strategy_total"] == 2
    assert detail["strategy_matched"] == []  # empty bars → nothing can fire
    reason = format_composite_reason(None, detail)
    assert reason == "Composite Markov trigger: any regime"  # no matches to report yet


def test_format_composite_reason_combines_structure_and_strategy():
    from app.services.composite_trigger_evaluator import format_composite_reason
    detail = {
        "structure_matched": ["BOS"],
        "structure_total": 2,
        "strategy_matched": ["mean_reversion_vwap"],
        "strategy_total": 1,
    }
    reason = format_composite_reason("Bull", detail)
    assert reason == (
        "Composite Markov trigger: Bull regime — 1/2 structures matched (BOS) — "
        "1/1 mean-reversion strategies fired (mean_reversion_vwap)"
    )
