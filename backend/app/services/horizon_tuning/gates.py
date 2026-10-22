"""Replayable live-scan gates per bar — STOCKS-HORIZON-T1 H8.

``gate_mask(...)[t]`` is True when a stock scan run at bar t's close, on the
bars up to t, would have kept the symbol on the gates the tuner can replay
(decision STOCKS-HORIZON-T1-DESIGN-2026-10-05), in the scan's order
(``routers/stock_scan._process_stock``):

1. bar t's close within ``[min_price, max_price]`` (``None`` = no bound);
2. ``score_stock`` on the last 120 bars, ``scoring_mode="stock"``, no regime
   signal, no fundamentals, no earnings or dividend date, no overrides, the
   benchmark aligned as the scan aligns it: status is not ``REJECT``;
3. the scan's own ``_direction_conviction_drop`` returns ``None``.

Everything else the live scan applies is not replayed and is named in every
report (``horizon_tuning.NOT_APPLIED``).
"""
from __future__ import annotations

from app.routers.stock_scan import _aligned_benchmark, _direction_conviction_drop
from app.scoring.stock_scorer import score_stock
from app.services.config_loader import load_direction_conviction_min_trend

# routers/stock_scan.py: score_stock(bars=bars[-120:], ...)
SCORER_WINDOW_BARS = 120
_SYMBOL = "TUNE"   # score_stock and the drop helper only echo it back


def scoring_horizon_for(tuned_horizon: str) -> str:
    """The scorer horizon a tuned horizon scans under: Swing for Swing,
    Position for the four longer horizons."""
    return "Swing" if tuned_horizon == "Swing" else "Position"


def gate_mask(
    bars: list[dict],
    direction: str,
    scoring_horizon: str,
    *,
    min_price: float | None,
    max_price: float | None,
    benchmark: list[dict] | None,
) -> list[bool]:
    """One bool per bar (see the module docstring)."""
    min_trend = load_direction_conviction_min_trend(direction, scoring_horizon)
    out: list[bool] = []
    for t in range(len(bars)):
        close = float(bars[t]["close"])
        if (min_price is not None and close < min_price) or (max_price is not None and close > max_price):
            out.append(False)
            continue
        window = bars[max(0, t + 1 - SCORER_WINDOW_BARS): t + 1]
        card = score_stock(
            symbol=_SYMBOL,
            direction=direction,
            horizon=scoring_horizon,
            bars=window,
            scoring_mode="stock",
            regime_signal=None,
            regime_gate=None,
            fundamentals=None,
            fundamentals_gate=None,
            overrides=None,
            benchmark_candles=_aligned_benchmark(benchmark, window),
        )
        if card.status == "REJECT":
            out.append(False)
            continue
        out.append(_direction_conviction_drop(_SYMBOL, card, min_trend, direction, scoring_horizon) is None)
    return out
