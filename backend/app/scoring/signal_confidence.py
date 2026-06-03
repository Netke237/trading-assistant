from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

Outcome = Literal["win", "loss", "flat"]

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@lru_cache(maxsize=1)
def _cfg() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def load_backtest_cfg(horizon: str) -> dict:
    return _cfg()["confidence_backtest"][horizon.lower()]


def load_gate_cfg() -> dict:
    return _cfg()["confidence_gate"]


def evaluate_fire(
    history: list[dict],
    forward: list[dict],
    *,
    direction: str,
    atr: float,
    atr_mult: float,
) -> Outcome:
    """Decide if a signal fire was a win/loss/flat over the forward window.

    Win  = favorable atr_mult*ATR reached before adverse atr_mult*ATR.
    Loss = adverse reached first. Flat = neither within the window.
    Intrabar tie (both hit same bar) resolves as loss (conservative).
    """
    if atr <= 0 or not forward:
        return "flat"
    entry = history[-1]["close"]
    move = atr_mult * atr
    if direction == "Bullish":
        target, stop = entry + move, entry - move
        for b in forward:
            if b["low"] <= stop:
                return "loss"
            if b["high"] >= target:
                return "win"
    else:
        target, stop = entry - move, entry + move
        for b in forward:
            if b["high"] >= stop:
                return "loss"
            if b["low"] <= target:
                return "win"
    return "flat"
