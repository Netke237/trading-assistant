# Adversarial Code Audit — Round 1
**Target:** `APP-AUDIT-BROKER-PORTFOLIO` (Tracking Issue #354 / Programme #348)  
**Date:** 2026-10-21  
**Reviewer:** Subagent `968b046c-ea50-4d50-939b-869b29981fac` (Independent Adversarial Reviewer applying `bmad-review-adversarial-general`)  
**Diff Reviewed:** `git -C .worktrees/app-audit-broker-portfolio-c4b17ff3 diff origin/main..HEAD`  
**Gate:** Project Numerical & Persistence Gate

---

### Findings (6 Gate Findings, 6 Observations/Nits)

1. **Gate Finding 1 (Realized P&L Test Tautology & Multiplier Error):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:600-613`
   - **Trigger:** `test_realized_pnl_calculation` tested pure Python arithmetic in local variables with an erroneous `* 100` multiplier for stocks and bypassed `app.services.portfolio_performance.realized_pnl` and `app.routers.portfolio.is_short_stock_position`.
   - **Consequence:** Could mask sign inversion or multiplier calculation defects in production.

2. **Gate Finding 2 (Weighted Entry Arithmetic Test Tautology):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:572-583`
   - **Trigger:** `test_weighted_average_price_arithmetic` computed entry price in local variables without invoking `app.services.portfolio_exposure.weighted_entry`.
   - **Consequence:** A regression in `weighted_entry` would go undetected.

3. **Gate Finding 3 (Rejection Zero-State Invariant Untested on Database):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:371-409`
   - **Trigger:** Asserted zero database positions after calling in-memory `BrokerRouter` without verifying exposure hold lifecycle or database rollback.
   - **Consequence:** Unverified exposure hold release and rollback invariants on preflight order refusal.

4. **Gate Finding 4 (Portfolio Store Duplicate Merging Untested on Zustand Store):**
   - **Location:** `frontend/lib/__tests__/auditBrokerPortfolioLaneF.test.ts:130-141`
   - **Trigger:** Only created a mock position object without calling `usePortfolioStore.getState().addPosition()`.
   - **Consequence:** Regressions in `portfolioStore.ts` duplicate contract merging or contract count summation would not be caught.

5. **Gate Finding 5 (Target Rung Rescaling Runner Preservation Weak Assertion):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:584-599`
   - **Trigger:** Used `asked=60` with rungs summing to 60 (zero runner shares) and a loose inequality `<= 40`.
   - **Consequence:** Partial fill rung rescaling could miscalculate or drop runner protections.

6. **Gate Finding 6 (Added Fills Mechanism Misattribution in Report):**
   - **Location:** `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/report.md:136` and `reconciliation.json:124-132`
   - **Trigger:** Misattributed added fills logic to `position_writer.py` instead of `portfolio_exposure.py:weighted_entry`.
   - **Consequence:** Misstates the authoritative module and mechanism for added fill arithmetic.

7. **Observation / Nit 7:**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:568-570`
   - **Trigger:** Inline re-implementation of multiplier logic instead of `portfolio_performance._contract_multiplier`.

8. **Observation / Nit 8:**
   - **Location:** `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/report.md:148-153`
   - **Trigger:** Stated `ClosedPositionModel` executes realized P&L formulas rather than `portfolio_performance.realized_pnl` and `routers/portfolio.py:close_position`.

9. **Observation / Nit 9:**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:128-163`
   - **Trigger:** Missing test asserting governor pacing admission on `tradier_paper`.

10. **Observation / Nit 10:**
    - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:208-274`
    - **Trigger:** Tastytrade paper adapter tests omitted option leg resolution (`_resolve_leg`).

11. **Observation / Nit 11:**
    - **Location:** `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/provenance.json:5`
    - **Trigger:** `head_commit` preceded audit commits.

12. **Observation / Nit 12:**
    - **Location:** `docs/superpowers/PROJECT_STATE.json:4`
    - **Trigger:** Root `updated_by` field was not updated to reflect `APP-AUDIT-BROKER-PORTFOLIO`.

---

### Remediation Applied

- **F-1 / Nit 8:** Replaced inline P&L math with explicit calls to `app.services.portfolio_performance.realized_pnl`, `_contract_multiplier`, and `app.routers.portfolio.is_short_stock_position`, verifying long stock ($3000 / 20%), short stock ($2000 / 13.33%), and long option ($500 / 50%) calculations. Updated `report.md:148-153` accordingly.
- **F-2:** Replaced inline math in `test_weighted_average_price_arithmetic` with direct calls to `app.services.portfolio_exposure.weighted_entry`, testing 10 @ $150 + 5 @ $165 -> 15 @ $155.00 exact and 100 @ $100 + 50 @ $130 -> 150 @ $110.00 exact.
- **F-3:** Rewrote `test_rejection_zero_state_invariant` to verify SQLite `ExposureHold` allocation, preflight rejection via `OrderPreflightRefusedError`, and clean release via `release_hold`, leaving 0 active exposure holds and 0 DB positions.
- **F-4:** Added live `usePortfolioStore.getState().addPosition(pos, { skipPost: true })` test in `auditBrokerPortfolioLaneF.test.ts`, asserting duplicate position merging from 2 contracts + 3 contracts to 5 contracts and row length 1, as well as distinct contract separation.
- **F-5:** Rewrote `test_rung_share_rescaling_runner_preservation` with `asked=100`, `stored=50`, and two 30-share rungs (leaving 40 runner shares / 40%), asserting exact proportional scaling to `[15, 15]` (sum 30) and 20 runner shares preserved (40%).
- **F-6:** Updated `report.md:136` and `reconciliation.json` to correctly trace `confirmAddedFill` through `EditDrawer.tsx` -> `portfolioStore.ts:sendAddedFill` -> `routers/portfolio.py:update_position` -> `portfolio_exposure.py:weighted_entry`.
- **Nit 7:** In `test_schema_mapping_and_contract_string`, used `_contract_multiplier(pos.contract)` directly for options (100) and stock (1).
- **Nit 9:** Added rate-limit governor budget refusal test in `test_tradier_endpoint_and_side_mapping`, asserting `OrderAdmissionRefusedError` on governor rejection.
- **Nit 10:** Added `test_tastytrade_paper_option_leg_resolution` in `TestTask1BrokerAdapters`, testing missing OCC exception and successful leg building via mock option chain.
- **Nit 11:** Updated `provenance.json`'s `head_commit` and test suite counts (21 backend, 12 frontend).
- **Nit 12:** Updated `docs/superpowers/PROJECT_STATE.json` root `updated_by`.

---

### Status
- Gate Findings: 6 (all remediated)
- Observations/Nits: 6 (all remediated)
- Ready for Code Stage Round 2 audit.
