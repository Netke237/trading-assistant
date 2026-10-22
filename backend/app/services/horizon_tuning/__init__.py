"""Per-horizon strategy tuning (STOCKS-HORIZON-T1, ADR 0001).

H8 core: ``signals`` (one signal series per symbol x strategy x direction x
params), ``simulate`` (trades per horizon and cost, parity-tested against
``strategy_backtest.run_strategy_backtest_trades``), ``gates`` (the replayable
live-scan gates per bar), ``cache`` (both on disk) and ``basket`` (the sector
sample and the fire-rate / trade universes).

Not applied by the tuner, named in every report (decision
STOCKS-HORIZON-T1-DESIGN-2026-10-05): regime gate, regime filter,
fundamentals, IV, earnings dates, confidence replay, ``min_stock_score``, the
per-symbol backtest gate. Also: the live scan passes the live quote as
``current_price`` to ``pullback_ema``; the tuner uses the close.
"""

NOT_APPLIED: tuple[str, ...] = (
    "regime gate",
    "regime filter",
    "fundamentals",
    "IV",
    "earnings dates",
    "confidence replay",
    "min_stock_score",
    "per-symbol backtest gate",
    "pullback_ema current_price: live scans pass the live quote, the tuner uses the close",
)
