# Multi-year retuning readiness

The corrected Phase A optimizer is available, including independent clean review of OOS fold selection and aggregation. No new strategy parameters or R/R floor have been adopted during this stage.

Required evidence: adjusted settled daily bars covering the configured three-year lookback, configured transaction costs, out-of-sample trade counts and consistency, direction-specific proposals. Empty or incomplete provider results must not be represented as a completed tune.

This environment currently has no stored OHLCV daily table/history in its local application database and no injected Alpaca or Tiingo credential binding. The repository's four candle fixtures (AAPL, MSFT, NVDA, SPY) each contain 251 bars from 2024-04-30 through 2025-04-30: one year, insufficient for the requested multi-year tune. They are test fixtures, not a substitute for the missing lookback.

Yahoo history access returned HTTP 403 from the environment proxy. Additive domains query1.finance.yahoo.com, query2.finance.yahoo.com and fc.yahoo.com were saved to the cloud environment draft while preserving the known existing domains. Saving the draft does not apply it to this running instance. Apply those additions in environment settings, then verify provider retrieval before running optimization. Alternatively, bind an existing supported provider credential securely in environment settings; never supply secret values in chat.

After data access is restored: initialize the local OHLCV model's metadata through the repository-supported application initialization; fetch and inspect settled adjusted history; run the configured strategy basket, windows, costs and both directions; preserve complete proposals and input dates/counts; review OOS eligibility and net expectancy before adoption. The configurable min_signal_rr remains 0.0 until the retune produces reviewable evidence. This document records a concrete external blocker, not a completed retune.
