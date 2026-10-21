# Adversarial Code Audit — Round 2
**Target:** `APP-AUDIT-BROKER-PORTFOLIO` (Tracking Issue #354 / Programme #348)  
**Date:** 2026-10-21  
**Reviewer:** Fresh Independent Subagent `be197276-64dd-4efa-91c4-2c94a86397ae` applying `bmad-review-adversarial-general`  
**Diff Reviewed:** `git -C .worktrees/app-audit-broker-portfolio-c4b17ff3 diff 3a449185..49a701cc`  
**Gate:** Project Numerical & Persistence Gate

---

### Findings (4 Gate Findings, 8 Observations/Nits)

1. **Gate Finding 1 (Rejection Zero-State Automatic Release Invariant):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:486-497`
   - **Trigger:** `test_rejection_zero_state_invariant` called `release_hold` manually instead of verifying that `_dispatch_order` automatically invokes `exposure_hooks.release` via `_release_open_risk` upon `OrderPreflightRefusedError`.
   - **Remediation:** Rewrote test to execute `_dispatch_order` with mock hooks, asserting that catching `OrderPreflightRefusedError` automatically triggers `exposure_hooks.release("att_rej_test")` and `hooks.resolve("att_rej_test", definitely_not_submitted=True, outcome="not_submitted")`.

2. **Gate Finding 2 (Plan Round 3 Clean Commit Subject Canonical Pattern):**
   - **Location:** `scripts/state.py:686-697, 815-825`
   - **Trigger:** `_clean_plan_round_re(3)` regex expects `plan round 3 clean` or `plan r3 clean`.
   - **Remediation:** Emitted canonical commit with subject `docs(audit): APP-AUDIT-BROKER-PORTFOLIO plan round 3 clean` to guarantee unambiguous regex satisfaction.

3. **Gate Finding 3 & 4 (Report & Provenance Synchronization):**
   - **Location:** `report.md:205-234`, `provenance.json:5, 27`
   - **Trigger:** Test count was 20 in `report.md` instead of 21, and `head_commit` was stale.
   - **Remediation:** Updated `report.md` with complete 21-test pytest log (including `test_tastytrade_paper_option_leg_resolution`) and updated Jest log. Updated `provenance.json` with current head commit.

4. **Observation / Nit 5 (ClosedPositionModel Zero-Row Assertion):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:489-497`
   - **Trigger:** Verified `PortfolioPositionModel` count is 0, but omitted `ClosedPositionModel`.
   - **Remediation:** Added `assert (await db.execute(select(func.count()).select_from(ClosedPositionModel))).scalar_one() == 0` before and after rejection.

5. **Observation / Nit 6 & 7 (Realized P&L Signing Helper & Zero-Entry Guard):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:690-725`
   - **Trigger:** Manual conditional sign inversion in test body and untested zero entry price.
   - **Remediation:** Encapsulated in `_calc_closed_pnl` matching `close_position` production logic; added test verifying `entry_price = 0.0` returns `dollar == 1500.0, pct == 0.0` without zero-division error.

6. **Observation / Nit 8 (Target Rung Rescaling Fractional Remainder Tie-Breaker):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:650-672`
   - **Trigger:** Only tested zero-leftover case.
   - **Remediation:** Added 3-rung tie-breaker test (`25/25/25` of 100 with 50 stored -> `13/12/12` of 37, preserving 13 runner shares and verifying earliest-index tie-break).

7. **Observation / Nit 9 & 10 (Tastytrade Option Leg Failure & Stock Leg Resolution):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:293-332`
   - **Trigger:** Omitted chain miss test and stock leg resolution in `_resolve_leg`.
   - **Remediation:** Added contract-not-found `ValueError` test and `Equity.get` stock leg test.

8. **Observation / Nit 11 (Frontend Duplicate Merging Initial Fill Price):**
   - **Location:** `frontend/lib/__tests__/auditBrokerPortfolioLaneF.test.ts:148-158`
   - **Trigger:** Omitted assertion on entry price during store duplicate merging.
   - **Remediation:** Added `expect(positions[0].entryPrice).toBe(3.50)` confirming initial entry price preservation.

9. **Observation / Nit 12 (Tradier Governor Call Arguments):**
   - **Location:** `backend/tests/test_audit_broker_portfolio_lane_f.py:172-180`
   - **Trigger:** Did not verify governor key and timeout arguments.
   - **Remediation:** Added `mock_gov.admit_sync.assert_called_once_with("tradier_paper", admit_timeout=10.0)`.

---

### Status
- Gate Findings: 4 (all resolved)
- Observations/Nits: 8 (all resolved)
- Ready for Code Stage Round 3 audit.
