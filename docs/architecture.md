# Architecture Outline

This document captures the initial architecture for the Options Screener and Recommendation Assistant.

## Core components

- Backend: FastAPI service for scan orchestration, portfolio state, trade-card generation, and alert evaluation.
- Frontend: Next.js UI for scan control, ranked stock review, contract detail, trade cards, watchlist, and portfolio monitoring.
- Configuration: central settings file for all thresholds, risk limits, alert behavior, and workflow defaults.
- Persistence: state files for watchlist, portfolio, and audit trail.
- Testing: unit and integration tests for workflow correctness and reproducibility.

## Risk rules

Source of truth: `backend/config/risk_rules.yaml`, enforced by `check_position_risk` in `backend/app/services/portfolio_risk.py`. Settings > Risk rewrites that YAML on save and drops its comments, so rules are recorded here and in code comments, not in the YAML.

- **Option single-position cap = `min(max_single_position_pct, max_loss_per_trade_pct)`** (review fix #4, decision D5). The auto-trader and the direct send place no protective order, so a long option can lose its whole premium. The per-trade loss limit is therefore a premium cap too: with the shipped values (5% and 3.75%) an option is sized to at most 3.75% of the portfolio. `check_position_risk` shrinks `adjusted_size` to fit, and refuses with `single_trade_exposure_too_high` when one contract does not fit. The frontend mirror is `checkTradeRisk` in `frontend/lib/risk.ts`. The auto-trader fire goes through the same function (`AutoTrader._check_exposure`).
- **Stocks are unchanged**: they carry a stop and are judged against their own caps (`max_single_stock_position_pct`, `max_total_stock_exposure_pct`).
- The stop-based loss check (`max_loss_per_trade_exceeded`, loss at the exit-plan final stop) stays a separate, per-position-overridable check.
