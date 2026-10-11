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


# StockScanRequest's strategy fields (STOCKS-HORIZON-T1 H4). Optional, default
# None: an omitted field takes the backend profile for direction x params
# horizon. `pullback_require_reversal` is a UI toggle, not tuned, and is not
# listed.
STRATEGY_REQUEST_FIELDS: tuple[str, ...] = (
    "pullback_tolerance_pct", "pullback_ema_period", "pullback_trend_ema", "pullback_ma_type",
    "ma_crossover_fast", "ma_crossover_slow", "ma_crossover_lookback", "breakout_volume_mult",
    "rsi_period", "rsi_oversold", "rsi_overbought", "rsi_trend_sma", "require_choppy_regime",
    "mean_reversion_variants", "mean_reversion_min_confirmations", "vwap_lookback",
    "vwap_deviation_pct",
)


def resolve_params_horizon(
    params_horizon: str | None, scoring_horizon: str, hold_max_days: int | None,
) -> str | None:
    """Which tuned horizon's parameters a stocks request reads: its explicit
    ``params_horizon``, else ``tuned_params_horizon(hold_max_days)`` when the
    request carries a hold and the scoring horizon is not Intraday, else None
    (the direction baseline)."""
    if params_horizon is not None:
        return params_horizon
    if hold_max_days is None or scoring_horizon == "Intraday":
        return None
    return tuned_params_horizon(hold_max_days)


def migrate_saved_stock_request(request: dict) -> dict:
    """One-off migration of a SAVED stocks request (a scan schedule's
    ``resolved_request``, the last stock scan's request): drop the strategy
    fields, which old clients always sent at their frozen defaults (0.08, 1.1,
    ...) and which would otherwise override the profile forever, and record
    the params horizon the request's hold maps to. Idempotent; returns a new
    dict."""
    out = {k: v for k, v in request.items() if k not in STRATEGY_REQUEST_FIELDS}
    if out.get("params_horizon") is None:
        hold = out.get("hold_max_days")
        horizon = (resolve_params_horizon(None, out.get("horizon", ""), hold)
                   if isinstance(hold, int) and not isinstance(hold, bool) else None)
        if horizon is not None:
            out["params_horizon"] = horizon
    return out
