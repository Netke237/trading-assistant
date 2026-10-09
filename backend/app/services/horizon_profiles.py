"""Tuned holding horizons and the hold a stock backtest uses (STOCKS-HORIZON-T1).

A tuned horizon is a holding period with its own strategy parameters. The names
are the frontend ``HorizonKey`` spelling (``frontend/lib/horizonPresets.ts``).
"""
from __future__ import annotations

from typing import Literal

from app.scoring.stock_scorer import DEFAULT_HOLD_MAX

TunedHorizon = Literal["Swing", "Position", "Quarterly", "SemiAnnual", "Annual"]

TUNED_HORIZONS: tuple[TunedHorizon, ...] = ("Swing", "Position", "Quarterly", "SemiAnnual", "Annual")

# Calendar days. Mirrors HORIZON_PRESETS[].holdMax in frontend/lib/horizonPresets.ts;
# tests/test_horizon_profiles.py reads both files and fails if they differ.
HOLD_MAX_DAYS: dict[str, int] = {
    "Swing": 15,
    "Position": 45,
    "Quarterly": 60,
    "SemiAnnual": 105,
    "Annual": 200,
}

# Strategies backtested on intraday bars: a calendar-day hold does not apply.
_INTRADAY_STRATEGIES = frozenset({"mean_reversion_vwap"})

# Upper hold bound at or below which a Custom range scores as Intraday
# (horizonPresets.ts scoringHorizonForHold).
_INTRADAY_HOLD_MAX = 4


def tuned_params_horizon(hold_max_days: int) -> TunedHorizon | None:
    """The tuned horizon whose parameters a hold of ``hold_max_days`` reads.

    ``None`` when the hold scores as Intraday (``<= 4`` days). Otherwise the
    tuned horizon minimising ``|hold_max_days - HOLD_MAX_DAYS[h]|``; a tie goes
    to the shorter horizon (30 -> Swing).
    """
    if hold_max_days <= _INTRADAY_HOLD_MAX:
        return None
    best: TunedHorizon = TUNED_HORIZONS[0]
    for h in TUNED_HORIZONS[1:]:
        if abs(hold_max_days - HOLD_MAX_DAYS[h]) < abs(hold_max_days - HOLD_MAX_DAYS[best]):
            best = h
    return best


def hold_for_backtest(horizon: str, strategy: str, hold_max_days: int | None) -> int | None:
    """The ``hold_max_days`` a stock backtest runs with; ``None`` = no time exit.

    ``None`` for the Intraday scoring horizon and for intraday strategies;
    else the request's hold, or the scoring horizon's preset hold
    (``stock_scorer.DEFAULT_HOLD_MAX``) when the request carries none.
    """
    if horizon == "Intraday" or strategy in _INTRADAY_STRATEGIES:
        return None
    if hold_max_days is not None:
        return hold_max_days
    return DEFAULT_HOLD_MAX[horizon]
