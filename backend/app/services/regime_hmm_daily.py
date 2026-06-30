"""Directional Gaussian HMM, timeframe-agnostic (daily or intraday bars).

Fits a 3-state GaussianHMM on the returns of whatever bars are passed and
labels states Bull / Bear / Sideways by mean-return ordering, so the result
is directly comparable to the OMM's Bull/Bear/Choppy labels for alignment.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

MIN_OBS = 200


@dataclass
class DirectionalHmmResult:
    state: str            # Bull | Bear | Sideways
    p_stay: float
    transition_row: list[float]


def compute_directional_hmm(bars: list[dict], *, min_obs: int = MIN_OBS,
                            random_state: int = 42) -> DirectionalHmmResult | None:
    if len(bars) < min_obs:
        return None
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return None

    closes = np.array([float(b["close"]) for b in bars], dtype=float)
    returns = (np.diff(closes) / closes[:-1]).reshape(-1, 1)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = GaussianHMM(n_components=3, covariance_type="diag",
                            n_iter=200, random_state=random_state)
        model.fit(returns)

    means = np.array([model.means_[k][0] for k in range(3)])
    order = np.argsort(means)                       # lowest..highest mean return
    label_by_state = {int(order[0]): "Bear", int(order[1]): "Sideways", int(order[2]): "Bull"}

    # Decode on last 30 bars only (local Viterbi window); model is already fitted on the full series.
    current_idx = int(model.predict(returns[-30:])[-1])
    p_stay = float(model.transmat_[current_idx, current_idx])
    row = [float(model.transmat_[current_idx, j]) for j in range(3)]
    return DirectionalHmmResult(state=label_by_state[current_idx],
                                p_stay=round(p_stay, 4),
                                transition_row=[round(v, 4) for v in row])


def compute_directional_hmm_series(
    bars: list[dict],
    *,
    max_bars: int = 500,
    min_obs: int = MIN_OBS,
    random_state: int = 42,
) -> list[dict]:
    """Compute per-bar directional HMM state for chart background overlay (display only — Viterbi decoded).

    States: Bull | Bear | Sideways — directly comparable to OMM's Bull/Bear/Choppy labels.
    Returns one entry per bar (up to max_bars) with keys: time, state, conviction.
    """
    window = bars[-max_bars:] if len(bars) > max_bars else bars
    if len(window) < min_obs:
        return []
    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return []

    closes = np.array([float(b["close"]) for b in window], dtype=float)
    returns = (np.diff(closes) / closes[:-1]).reshape(-1, 1)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = GaussianHMM(n_components=3, covariance_type="diag",
                            n_iter=200, random_state=random_state)
        model.fit(returns)

    means = np.array([model.means_[k][0] for k in range(3)])
    order = np.argsort(means)
    label_by_state = {int(order[0]): "Bear", int(order[1]): "Sideways", int(order[2]): "Bull"}

    states = model.predict(returns)
    posteriors = model.predict_proba(returns)

    result = []
    for i, bar in enumerate(window[1:]):
        state_idx = int(states[i])
        result.append({
            "time": bar["time"],
            "state": label_by_state[state_idx],
            "conviction": round(float(posteriors[i, state_idx]), 4),
        })
    return result


def alignment(omm_state: str | None, hmm_state: str | None) -> str:
    if not omm_state or not hmm_state:
        return "Unavailable"

    def _norm(s: str) -> str:
        return "Sideways" if s in ("Choppy", "Sideways") else s

    return "Aligned" if _norm(omm_state) == _norm(hmm_state) else "Diverging"
