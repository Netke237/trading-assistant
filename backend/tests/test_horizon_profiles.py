"""Tuned horizons, their hold, and the hold a backtest uses (STOCKS-HORIZON-T1 H2)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services.horizon_profiles import (
    HOLD_MAX_DAYS,
    TUNED_HORIZONS,
    hold_for_backtest,
    tuned_params_horizon,
)

_PRESETS_TS = Path(__file__).resolve().parents[2] / "frontend" / "lib" / "horizonPresets.ts"


def test_tuned_horizons_order():
    assert TUNED_HORIZONS == ("Swing", "Position", "Quarterly", "SemiAnnual", "Annual")


def test_hold_max_matches_frontend_presets():
    """HOLD_MAX_DAYS mirrors frontend/lib/horizonPresets.ts HORIZON_PRESETS holdMax."""
    text = _PRESETS_TS.read_text(encoding="utf-8")
    ts = {
        m.group(1): int(m.group(2))
        for m in re.finditer(r"key:\s*'(\w+)'[^}]*?holdMax:\s*(\d+)", text)
    }
    assert {h: ts[h] for h in TUNED_HORIZONS} == HOLD_MAX_DAYS
    assert set(HOLD_MAX_DAYS) == set(TUNED_HORIZONS)


@pytest.mark.parametrize("hold, expected", [
    (185, "Annual"),       # Custom 60-185
    (30, "Swing"),         # |30-15| = |30-45| = 15, tie -> the shorter horizon
    (3, None),             # Custom 0-3 scores as Intraday
    (4, None),
    (5, "Swing"),
    (15, "Swing"),
    (45, "Position"),
    (60, "Quarterly"),
    (105, "SemiAnnual"),
    (200, "Annual"),
    (500, "Annual"),
])
def test_tuned_params_horizon(hold, expected):
    assert tuned_params_horizon(hold) == expected


@pytest.mark.parametrize("horizon, strategy, hold, expected", [
    ("Swing", "pullback_ema", None, 15),
    ("Position", "pullback_ema", None, 45),
    ("Position", "mean_reversion_rsi", 60, 60),
    ("Swing", "ma_crossover", 30, 30),
    ("Intraday", "pullback_ema", None, None),
    ("Intraday", "pullback_ema", 2, None),
    ("Swing", "mean_reversion_vwap", None, None),
    ("Position", "mean_reversion_vwap", 45, None),
])
def test_hold_for_backtest(horizon, strategy, hold, expected):
    assert hold_for_backtest(horizon, strategy, hold) == expected
