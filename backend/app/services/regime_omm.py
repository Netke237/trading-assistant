"""
Rolling Observable Markov Model for daily regime classification.

Labels each bar Bull / Bear / Choppy from a rolling 20-day return,
then counts transitions in a 500-day window to build a 3×3 matrix.
Returns None when fewer than 100 bars of the current state are observed.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

STATES = ['Bull', 'Bear', 'Choppy']
STATE_IDX = {s: i for i, s in enumerate(STATES)}

WINDOW = 500          # rolling trading days (~2 years)
RETURN_LOOKBACK = 20  # rolling return window in bars
BULL_THRESH = 0.02    # +2% rolling return → Bull
BEAR_THRESH = -0.02   # −2% rolling return → Bear
MIN_OBS = 100         # minimum observations of current state to publish OMM


@dataclass
class OmmResult:
    state: str
    p_stay: float
    stability: str           # 'Stable' | 'Fragile'
    regime_age_days: int
    avg_regime_duration: float
    transition_row: list[float]
    state_order: list[str]


def label_daily_states(closes: list[float]) -> list[str]:
    """Compute Bull/Bear/Choppy label for each bar from rolling 20d return."""
    labels: list[str] = []
    for i in range(len(closes)):
        if i < RETURN_LOOKBACK:
            labels.append('Choppy')
            continue
        ret = (closes[i] - closes[i - RETURN_LOOKBACK]) / closes[i - RETURN_LOOKBACK]
        if ret > BULL_THRESH:
            labels.append('Bull')
        elif ret < BEAR_THRESH:
            labels.append('Bear')
        else:
            labels.append('Choppy')
    return labels


def build_transition_matrix(labels: list[str], window: int = WINDOW) -> np.ndarray:
    """
    Count state → state transitions in the last `window` labels.
    Normalise each row; rows with 0 observations get uniform distribution.
    Returns a 3×3 float array indexed by STATE_IDX.
    """
    n = len(STATES)
    counts = np.zeros((n, n), dtype=float)
    recent = labels[-window:] if len(labels) > window else labels
    for i in range(len(recent) - 1):
        f, t = STATE_IDX.get(recent[i], -1), STATE_IDX.get(recent[i + 1], -1)
        if f >= 0 and t >= 0:
            counts[f, t] += 1

    matrix = np.zeros((n, n), dtype=float)
    for row in range(n):
        total = counts[row].sum()
        if total > 0:
            matrix[row] = counts[row] / total
        else:
            matrix[row] = 1.0 / n
    return matrix


def _regime_age(labels: list[str], current: str) -> int:
    """Count consecutive trailing bars in `current` state."""
    age = 0
    for lbl in reversed(labels):
        if lbl == current:
            age += 1
        else:
            break
    return age


def compute_omm(closes: list[float]) -> OmmResult | None:
    """
    Build rolling OMM from daily close prices.
    Returns None if the current state has fewer than MIN_OBS observations
    in the training window (matrix not reliable enough to publish).
    """
    if len(closes) < RETURN_LOOKBACK + 2:
        return None

    labels = label_daily_states(closes)
    current = labels[-1]
    current_idx = STATE_IDX[current]

    # Check observation count for current state within window
    window_labels = labels[-WINDOW:] if len(labels) > WINDOW else labels
    obs_count = window_labels.count(current)
    if obs_count < MIN_OBS:
        return None

    matrix = build_transition_matrix(labels)
    p_stay = float(matrix[current_idx, current_idx])
    transition_row = [float(matrix[current_idx, i]) for i in range(len(STATES))]

    denom = 1.0 - p_stay
    avg_duration = (1.0 / denom) if denom > 1e-9 else float('inf')
    avg_duration = min(avg_duration, 9999.0)

    stability = 'Fragile' if (1.0 - p_stay) > 0.25 else 'Stable'
    age = _regime_age(labels, current)

    return OmmResult(
        state=current,
        p_stay=round(p_stay, 4),
        stability=stability,
        regime_age_days=age,
        avg_regime_duration=round(avg_duration, 1),
        transition_row=[round(v, 4) for v in transition_row],
        state_order=list(STATES),
    )
