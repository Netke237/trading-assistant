"""WATCH-DIRECTION-TO-EVALUATOR: a composite watch's own saved direction is the
fallback for evaluate_scheduled's OMM direction and strategy-confirmation
direction when its trigger_def carries none, and the watch's describe_match
lists strategies in the same direction the gate judged.

Plan: docs/superpowers/plans/2026-09-30-watch-direction-to-evaluator-plan.md
(tests 1-5 there).
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.composite_trigger_evaluator as cte
import app.services.regime_omm as regime_omm
from app.services.composite_trigger_evaluator import (
    evaluate_scheduled, omm_direction, strategy_direction,
)
from app.services.strategy_watch_evaluator import evaluate_all


def _bars(close: float = 100.0, n: int = 260) -> list[dict]:
    return [{"time": f"2025-01-{(i % 28) + 1:02d}", "open": close, "high": close + 1,
             "low": close - 1, "close": close, "volume": 1_000_000} for i in range(n)]


# ── test 1: omm_direction / strategy_direction ───────────────────────────────

@pytest.mark.parametrize("td, fallback, expected", [
    ({"direction": "Bearish"}, "Bullish", "Bearish"),      # trigger wins
    ({"direction": "Bullish"}, "Bearish", "Bullish"),      # trigger wins
    ({}, "Bearish", "Bearish"),
    ({"direction": None}, "Bearish", "Bearish"),
    ({"direction": ""}, "Bearish", "Bearish"),
    ({"direction": "bullish"}, "Bearish", "Bearish"),      # malformed trigger -> fallback
    ({"direction": "Neutral"}, "Bearish", "Bearish"),
    ({}, None, "Bullish"),
    ({}, "bearish", "Bullish"),                            # fallback not normalised
    ({}, "any", "Bullish"),
    ({}, 5, "Bullish"),
    (None, "Bearish", "Bearish"),                          # non-dict trigger_def
    ("x", None, "Bullish"),
])
def test_omm_direction_fallback(td, fallback, expected):
    """Mutations: fallback wins over a valid trigger; fallback not validated."""
    assert omm_direction(td, fallback) == expected


def test_omm_direction_one_argument_unchanged():
    assert omm_direction({"direction": "Bearish"}) == "Bearish"
    assert omm_direction({}) == "Bullish"
    assert omm_direction({"direction": "bearish"}) == "Bullish"


@pytest.mark.parametrize("td, fallback, expected", [
    ({"direction": "Bullish"}, "Bearish", "Bullish"),
    ({"direction": "bearish"}, "Bullish", "bearish"),      # truthy raw value kept, as before
    ({}, "Bearish", "Bearish"),
    ({"direction": None}, "Bearish", "Bearish"),
    ({}, None, "Bullish"),
    ({}, "Neutral", "Bullish"),
])
def test_strategy_direction(td, fallback, expected):
    assert strategy_direction(td, fallback) == expected


# ── test 2: the OMM line uses the fallback ───────────────────────────────────

def _spy_omm(monkeypatch):
    seen: list[str] = []

    def fake(closes, *, direction="Bullish", **kw):
        seen.append(direction)
        return None

    monkeypatch.setattr(regime_omm, "compute_omm", fake)
    return seen


@pytest.mark.parametrize("td, fallback, expected", [
    ({"primary": {"model": "OMM"}}, "Bearish", "Bearish"),
    ({"primary": {"model": "OMM"}}, None, "Bullish"),
    ({"primary": {"model": "OMM"}, "direction": "Bullish"}, "Bearish", "Bullish"),
    ({"primary": {"model": "OMM"}}, "bullish", "Bullish"),
    ({"primary": {"model": "OMM"}}, "Neutral", "Bullish"),
])
def test_evaluate_scheduled_omm_direction(monkeypatch, td, fallback, expected):
    """Mutation: ignore fallback_direction on the OMM line."""
    seen = _spy_omm(monkeypatch)
    evaluate_scheduled("AAPL", td, _bars(), [], fallback_direction=fallback)
    assert seen == [expected]


def test_evaluate_scheduled_omm_default_is_bullish(monkeypatch):
    seen = _spy_omm(monkeypatch)
    evaluate_scheduled("AAPL", {"primary": {"model": "OMM"}}, _bars(), [])
    assert seen == ["Bullish"]


# ── test 3: the strategy gate uses the fallback only without a trigger direction ─

@pytest.mark.parametrize("trig_dir, fallback, expected", [
    (None, "Bearish", "Bearish"),
    ("Bullish", "Bearish", "Bullish"),
    ("bearish", "Bullish", "bearish"),
    (None, None, "Bullish"),
])
def test_evaluate_scheduled_strategy_gate_direction(monkeypatch, trig_dir, fallback, expected):
    """Mutations: fallback overrides a present trigger direction; gate ignores it."""
    seen: list = []

    def fake_check(keys, daily, intraday, direction="Bullish", **kw):
        seen.append(direction)
        return 0

    monkeypatch.setattr(cte, "_check_strategy_signals", fake_check)
    td = {"primary": {"model": "any"}, "strategy_confirmations": ["mean_reversion_rsi"],
          "min_strategy_confirmations": 1, "min_confirmations": 0}
    if trig_dir is not None:
        td["direction"] = trig_dir
    evaluate_scheduled("AAPL", td, _bars(), [], fallback_direction=fallback)
    assert seen == [expected]


# ── test 5: the decision itself follows the fallback ─────────────────────────

@dataclass
class _Omm:
    state: str
    conviction_pct: float
    p_stay: float


def test_legacy_bearish_watch_decides_on_bearish_conviction(monkeypatch):
    """A reading that clears conviction_min only in the Bearish direction fires a
    Bearish legacy watch and not a Bullish one. Mutation: drop the fallback."""
    def fake(closes, *, direction="Bullish", **kw):
        return _Omm("bear_trend", 80.0 if direction == "Bearish" else 20.0, 0.9)

    monkeypatch.setattr(regime_omm, "compute_omm", fake)
    td = {"primary": {"model": "OMM", "to_state": "bear_trend", "conviction_min": 50},
          "min_confirmations": 0}
    assert evaluate_scheduled("AAPL", td, _bars(), [], fallback_direction="Bearish") is True
    assert evaluate_scheduled("AAPL", td, _bars(), [], fallback_direction="Bullish") is False
    assert evaluate_scheduled("AAPL", td, _bars(), []) is False


# ── tests 4 / 4b: the watch path passes its direction ────────────────────────

def _composite_watch(direction, trigger_def):
    return {"id": "wch_dir_1", "symbol": "AAPL", "watch_type": "composite",
            "direction": direction, "enabled": True, "interval": "1D",
            "trigger_def": trigger_def, "last_state": {"phase": "idle"}}


async def _run(watch):
    store = MagicMock()
    store.list_watches.return_value = [watch]
    with patch("app.services.strategy_watch_evaluator.strategy_watch_store", store), \
         patch("app.services.strategy_watch_evaluator.get_bars",
               new_callable=AsyncMock, return_value=_bars()), \
         patch("app.services.composite_trigger_evaluator.evaluate_scheduled",
               return_value=True) as sched, \
         patch("app.services.composite_trigger_evaluator.describe_match",
               return_value={"structure_matched": [], "strategy_matched": []}) as desc:
        await evaluate_all()
    return sched, desc


@pytest.mark.asyncio
@pytest.mark.parametrize("wdir", ["Bearish", "Bullish"])
async def test_watch_passes_its_direction_to_evaluate_scheduled(wdir):
    """Mutation: the caller does not pass fallback_direction."""
    sched, _ = await _run(_composite_watch(wdir, {"primary": {"model": "OMM"}}))
    assert sched.call_args.kwargs["fallback_direction"] == wdir


@pytest.mark.asyncio
@pytest.mark.parametrize("trig_dir, wdir, expected", [
    ("Bullish", "Bearish", "Bullish"),   # the gate judged Bullish -> list Bullish matches
    (None, "Bearish", "Bearish"),
    ("Bearish", "Bullish", "Bearish"),
])
async def test_watch_describe_match_follows_the_gate(trig_dir, wdir, expected):
    """Mutation: pass wdir to describe_match."""
    td = {"primary": {"model": "any"}, "strategy_confirmations": ["mean_reversion_rsi"],
          "min_strategy_confirmations": 1}
    if trig_dir is not None:
        td["direction"] = trig_dir
    _, desc = await _run(_composite_watch(wdir, td))
    assert desc.call_args.kwargs["direction"] == expected
