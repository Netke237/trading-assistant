"""
Gaussian HMM for intraday session-state detection.

Fits a 3-component GaussianHMM on 15-min bar returns and decodes the
current session state via the forward algorithm (causal — no look-ahead bias).

States are labelled from emission parameters:
  Trending      — highest |mean| / std ratio (directional, low noise)
  Choppy        — lowest variance, lowest |mean|  (quiet, directionless)
  Mean-reverting — highest variance (whipsaw, large moves that reverse)
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

MIN_BARS = 200   # minimum 15-min bars to fit a reliable model
# 55d × ~26 bars/day ≈ 1430 bars under normal conditions; 200 is a safe floor
# for GaussianHMM with 3 components. Warn if between 200 and 500.
_BARS_LOW_WARN = 500


@dataclass
class HmmResult:
    state: str
    p_stay: float
    p_transition: list[dict]   # [{to: str, prob: float}] for prob > 0.05


def _assign_labels(means: np.ndarray, covars: np.ndarray) -> dict[int, str]:
    """
    Map HMM state indices to human labels using emission parameters.
    std = sqrt(diagonal of covariance matrix per state).
    signal_ratio = |mean| / std — higher = more directional.
    """
    n = len(means)
    stds = np.array([float(np.sqrt(np.diag(covars[i]).mean())) for i in range(n)])
    abs_means = np.array([float(np.abs(means[i]).mean()) for i in range(n)])
    ratios = abs_means / (stds + 1e-10)

    order = np.argsort(ratios)[::-1]  # descending signal ratio
    labels = {}
    raw_labels = ['Trending', 'Choppy', 'Mean-reverting']
    # Highest ratio → Trending; sort the remaining by variance desc
    labels[order[0]] = 'Trending'
    rest = list(order[1:])
    rest_by_var = sorted(rest, key=lambda i: stds[i])
    labels[rest_by_var[0]] = 'Choppy'
    labels[rest_by_var[1]] = 'Mean-reverting'
    return labels


def compute_intraday_hmm(bars: list[dict]) -> HmmResult | None:
    """
    Fit GaussianHMM on 15-min bar returns and return the current session state.
    Returns None if fewer than MIN_BARS bars are available.
    """
    if len(bars) < MIN_BARS:
        return None

    # Cap to most recent 800 bars — enough for reliable 3-state HMM while keeping fit fast
    bars = bars[-800:]

    if len(bars) < _BARS_LOW_WARN:
        logger.warning(
            "compute_intraday_hmm: only %d bars available (ideal ≥ %d); "
            "HMM fit may be less reliable",
            len(bars), _BARS_LOW_WARN,
        )

    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return None

    closes = np.array([float(b['close']) for b in bars], dtype=float)
    returns = np.diff(closes) / closes[:-1]
    X = returns.reshape(-1, 1)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        model = GaussianHMM(
            n_components=3,
            covariance_type='full',
            n_iter=100,
            random_state=42,
        )
        model.fit(X)

    labels = _assign_labels(model.means_, model.covars_)

    # Causal inference: predict_proba on the last 30 bars only.
    # No future data is used — the model was trained on history but the
    # current-state posterior is computed from the recent tail alone.
    tail = X[-30:]
    state_probs = model.predict_proba(tail)
    last_probs = state_probs[-1]   # shape (n_components,)

    current_idx = int(np.argmax(last_probs))
    current_label = labels[current_idx]

    trans_matrix = model.transmat_
    p_stay = float(trans_matrix[current_idx, current_idx])

    p_transition = []
    for j in range(3):
        if j != current_idx:
            prob = float(trans_matrix[current_idx, j])
            if prob > 0.05:
                p_transition.append({'to': labels[j], 'prob': round(prob, 4)})
    p_transition.sort(key=lambda x: x['prob'], reverse=True)

    return HmmResult(
        state=current_label,
        p_stay=round(p_stay, 4),
        p_transition=p_transition,
    )


def compute_intraday_hmm_series(candles: list[dict], max_bars: int = 252) -> list[dict]:
    """Compute per-bar HMM state and conviction for intraday chart overlay.

    DISPLAY ONLY — State labels are Viterbi-decoded over the full window and are
    not point-in-time. Do not use for live signal generation.

    Returns one entry per candle (up to max_bars) with state label and conviction.
    """
    window = candles[-max_bars:]
    if len(window) < MIN_BARS:
        return []

    try:
        from hmmlearn.hmm import GaussianHMM
    except ImportError:
        return []

    closes_arr = np.array([float(b['close']) for b in window], dtype=float)
    returns = np.diff(closes_arr) / closes_arr[:-1]
    X = returns.reshape(-1, 1)

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        model = GaussianHMM(
            n_components=3,
            covariance_type='full',
            n_iter=100,
            random_state=42,
        )
        model.fit(X)

    label_map = _assign_labels(model.means_, model.covars_)

    # Viterbi decode over full window — display only, not point-in-time
    states = model.predict(X)            # integer state index per bar, length n-1
    posteriors = model.predict_proba(X)  # shape (n-1, n_states)

    # X has n-1 rows (returns); align to window[1:] to pair each return with its bar
    result = []
    for i, bar in enumerate(window[1:]):
        state_idx = int(states[i])
        result.append({
            "time": bar["time"],
            "state": label_map[state_idx],
            "conviction": float(posteriors[i, state_idx]),
        })
    return result
