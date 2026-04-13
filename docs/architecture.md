# Architecture Outline

This document captures the initial architecture for the Options Screener and Recommendation Assistant.

## Core components

- Backend: FastAPI service for scan orchestration, portfolio state, trade-card generation, and alert evaluation.
- Frontend: Next.js UI for scan control, ranked stock review, contract detail, trade cards, watchlist, and portfolio monitoring.
- Configuration: central settings file for all thresholds, risk limits, alert behavior, and workflow defaults.
- Persistence: state files for watchlist, portfolio, and audit trail.
- Testing: unit and integration tests for workflow correctness and reproducibility.
