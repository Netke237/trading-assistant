# Adversarial Code/Report Audit (Round 1): APP-AUDIT-MONITORING (#355)

**Phase ID:** `APP-AUDIT-MONITORING`  
**Branch:** `board/app-audit-monitoring-7fb31a2c` in worktree `.worktrees/app-audit-monitoring`  
**Review Target:** Exact diff against `origin/main` (`git -C .worktrees/app-audit-monitoring diff origin/main..HEAD`), including:
- `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md`
- `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/defects.json`
- `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/provenance.json`
- `backend/tests/test_audit_monitoring_lane_g.py`
- `frontend/app/(frame)/alerts/__tests__/auditMonitoringLaneG.test.ts`
against the execution plan:
- `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md`  
**Reviewer:** Independent Adversarial Subagent (`bmad-review-adversarial-general`)  
**Standard:** Project Numeric & Persistence Gate (finding blocks if it puts a wrong number in front of user or on broker order, corrupts persisted data, or misstates mechanism such that a competent reader acting on it would write a wrong change).  
**Status:** **NOT CLEAN (3 Gate-Level Findings in Reconciliation Report)**

---

### Executive Evaluation

The code artifacts added in this phase — `backend/tests/test_audit_monitoring_lane_g.py` (13 tests) and `frontend/app/(frame)/alerts/__tests__/auditMonitoringLaneG.test.ts` (10 tests) — are functionally sound, execute cleanly, and pass 100%. All 55 relevant backend regression tests and 114 frontend unit tests pass without regressions, and TypeScript typechecking is clean.

However, a forensic adversarial review of `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md` revealed **3 gate-level mechanism misstatements** regarding:
1. `useChartAlertStore` (`bamendjou:alerts`) persistence schema versioning;
2. `strategy_watch_evaluator.py` state machine lifecycle on `reversal` events;
3. `strategy_watch_evaluator.py` exit evaluation math (`exit_stop` / `exit_target` evaluated on `close` vs candle `high`/`low`).

Because each of these misstatements misleads a competent reader into writing breaking changes or invalid assertions, they violate the Project Numeric & Persistence Gate and block sign-off until corrected in the report.

---

### Findings (Round 1)

1.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:32`
- **trigger_condition:** Section 2 Architecture Matrix asserts that `useChartAlertStore` persistence key and schema is `bamendjou:alerts (unversioned)`, whereas `frontend/lib/chartAlertStore.ts:560-561` explicitly configures schema `version: 2` with `migrate: migrateChartAlerts` (which sanitizes rules, resets toasts, and caps history to `HISTORY_LIMIT` for `version < 2`).
- **guard_snippet:** In `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:32`, update:
  `| **Alerts** | ... | useAlertStore<br>useChartAlertStore | bamendjou-alerts-v2 (v3)<br>bamendjou:alerts (v2) | ... |`
  and in Section 3.2, document `version: 2` with `migrateChartAlerts(persistedState, version)` and `partialize: (s) => ({ rules: s.rules, history: s.history })`.
- **potential_consequence:** A developer reading this report who evolves `AlertRule` persistence will assume the store is unversioned, setting `version: 1` or omitting `migrate()`, which would bypass or corrupt the existing `version: 2` migration for users with stored alert rules in `localStorage`.

2.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:150`
- **trigger_condition:** Section 3.3 asserts that on `reversal`, Strategy Watch transitions phase to `idle` ("transitions phase to idle"), whereas `backend/app/services/strategy_watch_evaluator.py:532-535` and `backend/tests/test_strategy_watch_evaluator.py:146-148` explicitly keep `phase: "armed"`, flipping `direction` to `opposite_dir` and updating entry, stop, and target prices to the new reversal signal levels.
- **guard_snippet:** Update line 150 of `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md` to:
  `5. reversal: Emitted when an opposite directional signal fires while armed -> flips direction to opposite_dir and remains in phase: "armed" with newly updated entry_price, stop_price, and target_price.`
- **potential_consequence:** A developer or maintainer reading this report will implement or modify strategy watch event consumers under the false belief that reversal resets the watch to `idle`, writing incorrect state transitions or test assertions that prematurely disarm watches on reversal signals and drop live tracking of the flipped position.

3.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:146-148`
- **trigger_condition:** Section 3.3 asserts that `exit_stop` evaluates "candle low breaching stop_price" and `exit_target` evaluates "candle high reaching target_price", whereas `backend/app/services/strategy_watch_evaluator.py:469-474` evaluates strictly against candle `close` (`close <= stop_price` / `close >= target_price` for Bullish; `close >= stop_price` / `close <= target_price` for Bearish).
- **guard_snippet:** Update lines 146-148 of `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md` to:
  `2. exit_stop: Emitted when an armed watch detects candle close breaching stop_price (close <= stop for Bullish, close >= stop for Bearish) -> transitions phase back to idle, clearing entry levels.`
  `3. exit_target: Emitted when an armed watch detects candle close reaching target_price (close >= target for Bullish, close <= target for Bearish) -> transitions phase back to idle, clearing entry levels.`
- **potential_consequence:** A developer or quant trader reading the reconciliation report will assume the state machine exits on intra-day wick breaches (low/high), misidentifying the exit trigger mechanism and writing conflicting automated trading assumptions or invalid unit tests.

4.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:102`
- **trigger_condition:** Section 3.2 lists `toasts: ChartToast[]` in the store scope without clarifying that `toasts` are excluded from `localStorage` persistence via `partialize: (state) => ({ rules: state.rules, history: state.history })` and re-initialized to `[]` on load.
- **guard_snippet:** Explicitly document in Section 3.2 that `toasts` are transient in-memory notifications and excluded from `localStorage` persistence by `partialize`.
- **potential_consequence:** Engineers might incorrectly expect chart alert toasts to persist across browser restarts.

5.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/provenance.json:5`
- **trigger_condition:** `head_commit` is recorded as `"91548b82"` (the commit that closed the plan audit stage) rather than the commit that introduced the report and test suites (`30a33dac`).
- **guard_snippet:** Update `head_commit` in `provenance.json` to `"30a33dac"`.
- **potential_consequence:** Provenance audit trail cites the pre-authoring plan commit instead of the audit deliverable commit.

6.
- **location:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md:257-258` and `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/provenance.json:42,49`
- **trigger_condition:** Test counts recorded for `test_strategy_watch_evaluator.py` (26) and `test_auto_trader_event_veto.py` (14) diverge from the actual pytest collected test counts (23 and 30, respectively).
- **guard_snippet:** Update the test count metrics in `report.md` and `provenance.json` to 23 for `test_strategy_watch_evaluator.py` and 30 for `test_auto_trader_event_veto.py`.
- **potential_consequence:** Metric reporting in the reconciliation report diverges from test runner execution counts.

7.
- **location:** `frontend/app/(frame)/alerts/__tests__/auditMonitoringLaneG.test.ts:120-130`
- **trigger_condition:** Alert store separation tests only assert `expect(useAlertStore).toBeDefined()` and that `useChartAlertStore` has array properties, omitting assertions on the actual persistence storage keys (`bamendjou-alerts-v2` and `bamendjou:alerts`) and schema versions (`v3` and `v2`).
- **guard_snippet:** Add assertions verifying `useAlertStore.persist.getOptions().name === 'bamendjou-alerts-v2'`, `useAlertStore.persist.getOptions().version === 3`, `useChartAlertStore.persist.getOptions().name === 'bamendjou:alerts'`, and `useChartAlertStore.persist.getOptions().version === 2`.
- **potential_consequence:** The test suite passes even if a future refactor inadvertently alters the store names or schema versions.

---

### Verification Summary

- `pytest tests/test_audit_monitoring_lane_g.py`: **13 passed, 0 failed**
- `jest auditMonitoringLaneG.test.ts`: **10 passed, 0 failed**
- Regression suites:
  - `pytest tests/test_strategy_watch_evaluator.py tests/test_auto_trader_event_veto.py tests/test_chart_alert_scheduler.py`: **55 passed, 0 failed**
  - `jest watchedContractsStore|watchlistStore|chartAlertEngine|alertIndicators`: **114 passed, 0 failed**
- `npm run typecheck`: **Clean (0 errors)**
- `python scripts/state.py`: **No drift**

### Conclusion

The code and test suites are verified, but the reconciliation report `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md` is **NOT CLEAN** due to 3 gate-blocking mechanism misstatements (Findings 1, 2, and 3). Please remediate these findings in `report.md`, `provenance.json`, and `auditMonitoringLaneG.test.ts` before requesting Round 2.
