from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

Outcome = Literal["win", "loss", "flat"]


@dataclass
class ConfidenceResult:
    confidence: int | None     # 0-100, or None if insufficient samples
    hit_rate: float            # wins / (wins + losses)
    sample_size: int           # wins + losses (flats excluded)
    flats: int

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


def aggregate(outcomes: list[str], *, min_samples: int) -> ConfidenceResult:
    wins = sum(1 for o in outcomes if o == "win")
    losses = sum(1 for o in outcomes if o == "loss")
    flats = sum(1 for o in outcomes if o == "flat")
    decisive = wins + losses
    if decisive == 0:
        return ConfidenceResult(None, 0.0, 0, flats)
    hit_rate = wins / decisive
    if decisive < min_samples:
        return ConfidenceResult(None, round(hit_rate, 4), decisive, flats)
    # Win and loss are both atr_mult*ATR by construction -> payoff_ratio = 1.0.
    # confidence = 100 * hit_rate * min(1, payoff_ratio)  (formula per spec; tunable)
    payoff_ratio = 1.0
    confidence = round(100 * hit_rate * min(1.0, payoff_ratio))
    confidence = max(0, min(100, confidence))
    return ConfidenceResult(confidence, round(hit_rate, 4), decisive, flats)


Status = Literal["PASS", "CAUTION", "REJECT"]


def status_cap(confidence: int | None, gate: dict) -> Status:
    """The *most permissive* status this confidence allows. Demote-only:
    callers combine this with the raw status and take the worse of the two."""
    if not gate.get("enabled", True) or confidence is None:
        return "PASS"
    if confidence < gate["rejectBelow"]:
        return "REJECT"
    if confidence < gate["cautionBelow"]:
        return "CAUTION"
    return "PASS"


def interpret(confidence: int | None, *, sample_size: int, symbol: str) -> str:
    if confidence is None:
        return (
            f"Not enough history to judge this setup on {symbol} "
            f"({sample_size} past occurrences). Confidence not applied."
        )
    if confidence >= 70:
        return (
            f"Strong history — this setup worked {confidence}% of the time on "
            f"{symbol} across {sample_size} past occurrences."
        )
    if confidence >= 50:
        return (
            f"Mixed history — worked {confidence}% of the time on {symbol} "
            f"({sample_size} occurrences). Treat with normal caution."
        )
    return (
        f"Weak history — only {confidence}% reliable on {symbol} "
        f"({sample_size} occurrences). Verdict capped down."
    )


def compute_confidence(
    bars: list[dict],
    *,
    direction: str,
    horizon: str,
    atr_mult: float | None = None,
) -> ConfidenceResult:
    """Replay the entry signal across history and score its reliability.

    A 'fire' = score_stock(...).status == 'PASS' on bars up to and including i,
    using only price-derived rules (no event/iv inputs in the historical replay).

    `atr_mult` overrides the configured ATR multiple for the win/loss barriers;
    when None, the per-horizon default from config is used.
    """
    from app.scoring.stock_scorer import score_stock, _atr  # reuse existing helpers

    bt = load_backtest_cfg(horizon)
    n_days = int(bt["n_days"])
    atr_mult = float(atr_mult) if atr_mult is not None else float(bt["atr_mult"])
    atr_period = int(bt["atr_period"])
    min_samples = int(bt["min_samples"])

    warmup = 60  # need enough bars for MAs/ADX before the first meaningful score
    outcomes: list[str] = []
    last = len(bars) - n_days
    for i in range(warmup, last):
        window = bars[: i + 1]
        card = score_stock(
            symbol="_bt", direction=direction, horizon=horizon, bars=window
        )
        if card.status != "PASS":
            continue
        atr = _atr(window, atr_period)
        forward = bars[i + 1 : i + 1 + n_days]
        outcomes.append(
            evaluate_fire(window, forward, direction=direction, atr=atr, atr_mult=atr_mult)
        )
    return aggregate(outcomes, min_samples=min_samples)
