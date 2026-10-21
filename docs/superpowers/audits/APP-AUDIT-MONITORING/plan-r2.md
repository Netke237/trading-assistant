# Adversarial Plan Audit (Round 2): APP-AUDIT-MONITORING (#355)

**Review Target:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md`  
**Phase ID:** `APP-AUDIT-MONITORING`  
**Branch:** `board/app-audit-monitoring-7fb31a2c`  
**Worktree:** `.worktrees/app-audit-monitoring`  
**Diff Reviewed:** `git -C .worktrees/app-audit-monitoring diff 96437d4f..HEAD -- docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md`  
**Reviewer:** Independent Adversarial Subagent (`bmad-review-adversarial-general`)  
**Standard:** Project Numeric & Persistence Gate (finding blocks if it puts a wrong number in front of user/broker, corrupts persisted data, or misstates mechanism such that a competent reader acting on it writes a wrong change).  
**Status:** **NOT CLEAN (2 Gate-Level Findings)**

---

### Audit Evaluation of Round 1 Fixes (F-1 through F-17)

1. **F-1 (`watchedContractsStore.ts` schema, methods, migration)**: Partially addressed. The plan correctly updated schema `version: 3`, methods `add(id, grading)`, `remove(id)`, `clearGrading(id)`, `isWatched(id)`, and the migration rule `version < 3 ? { ...state, grading: {} } : state`. However, line 50 introduced a new false claim asserting persisted state is `contracts: string[]`, whereas the real store and its `partialize` configuration persist `ids: string[]` (Finding 1).
2. **F-2 (`watchlistStore.ts` operations)**: Correctly addressed. Updated to `addSymbol`, `removeSymbol`, `isWatched`, `syncFromBackend` (removed `toggleSymbol`).
3. **F-3 (`useWatchlistUiStore` separation)**: Correctly addressed. Documented that `useWatchlistUiStore` manages ephemeral `selectedSymbol: string | null`, and tab state (`'stocks' | 'contracts' | 'composite'`) is local state in `watchlist/page.tsx`.
4. **F-4 (Watchlist tab columns)**: Correctly addressed. Exact columns for Stocks (`SYMBOL`, `NAME`, `PRICE`, `DIR`, `HORIZON`, `SCORE`, `RANK Δ`, `SCORE Δ`, `NEXT EVENT`), Contracts (`SYMBOL`, `CONTRACT`, `DTE`, `PRICE`, `DELTA`, `IV`, `Θ/DAY`, `SCORE`), and Composite tab are documented.
5. **F-5 (`@contextRail/watchlist` sections)**: Correctly addressed. Status breakdown (`PASS`/`CAUTION`/`REJECT`), Flags (`Events ≤ 7d`, `Total`), `SymbolNotes`, and `RailQuickLook` verified.
6. **F-6 (Alert stores separation)**: Correctly addressed. `useAlertStore` (`bamendjou-alerts-v2`, `version: 3`) documented for portfolio toasts and config; `useChartAlertStore` (`bamendjou:alerts`) documented for `rules`, `history`, and `toasts`.
7. **F-7 (Alert engines separation)**: Correctly addressed. `chartAlertEngine.ts` identified for multi-bar candle conditions and crossing operators; `alertEngine.ts:scanPositions` identified for portfolio position stop/target evaluation.
8. **F-8 (Chart alert backend endpoints)**: Correctly addressed. Updated to `POST /alerts/rules`, `GET /alerts/rules`, `GET /alerts/history`, `DELETE /alerts/rules/{id}` in `backend/app/routers/chart_alerts.py`.
9. **F-9 (Strategy Watch toggle endpoint)**: Correctly addressed. Updated to `PATCH /api/strategy-watch/{watch_id}` with `{"enabled": bool}`.
10. **F-10 (Strategy Watch state machine phases & events)**: Correctly addressed. Verified `phase: "idle"` and `phase: "armed"`, with emitted event types `entry`, `exit_stop`, `exit_target`, `time_stop`, `reversal`.
11. **F-11 (5 valid daily strategies)**: Correctly addressed. Documented `pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb` from `strategy_watch_store.py:VALID_STRATEGIES`, explicitly noting `mean_reversion_vwap` is excluded as intraday-only.
12. **F-12 (Auto-trade state model)**: Correctly addressed. Model documented as `selectedBroker`, `autoMode: 'manual' | 'post_scan' | 'armed'`, `armed`, `armedDirection`, `armedSymbol`, `lastOrderId`.
13. **F-13 (`useAutoTradeStore` partialize safety guard)**: Correctly addressed. Verified `partialize` omits `armed`, `armedDirection`, and `armedSymbol` so the store disarms unconditionally on reload.
14. **F-14 (Auto-trade pre-trade safety gates)**: Correctly addressed. Distinguishes `RegimeHeadwindError` (HTTP 400) from `RegimeGateConfigError` (HTTP 500), and defines event veto as `max(YAML reject_window, hold_bars)` or unknown single-stock earnings.
15. **F-15 (Notification logging in `sent_log.py`)**: Correctly addressed. Clarifies `sent_log.py` is an append-only JSONL delivery audit log, while deduplication and cooldowns are enforced upstream in `alert_notifier.py` and `strategy_watch_evaluator.py`.
16. **F-16 (`chart_alert_scheduler.py` in scheduled automation)**: Correctly addressed. Added as scheduler #3 out of 7 total schedulers.
17. **F-17 (Alerts & Strategy Watch context rails)**: Correctly addressed. Clarified as generic fallback shims rendering `RailQuickLook` via `default.tsx`.

---

### Findings (Round 2)

1.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:50` (Section 2.A)
- **trigger_condition:** Fix F-1 introduced a false claim asserting that `useWatchedContractsStore` persisted state has shape `contracts: string[], grading: Record<string, ContractGrading>`, whereas the actual Zustand state and `partialize` implementation persist `ids: string[]`.
- **guard_snippet:** Update line 50 to: `- Persisted state: ids: string[], grading: Record<string, ContractGrading>.`
- **potential_consequence:** An implementer or auditor writing persistence verification tests for Task 2 will assert on `state.contracts` (or `parsed.state.contracts`), which is undefined in production; or if an engineer attempts to align the store with the plan by migrating to `contracts`, `sanitizePersisted()` will fail to find `ids`, wiping all starred contracts from existing users' `localStorage`.

2.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:95-96` (Section 2.C)
- **trigger_condition:** Plan asserts Strategy Watch schedule configuration uses `POST /api/strategy-watch/schedule` and manual evaluation uses `POST /api/strategy-watch/evaluate-now`, but the actual backend routes in `backend/app/routers/strategy_watch.py` and client calls in `frontend/lib/api.ts` are `PUT /api/strategy-watch/schedule` and `POST /api/strategy-watch/evaluate`.
- **guard_snippet:** Correct endpoint paths to:
  `- GET /api/strategy-watch/schedule & PUT /api/strategy-watch/schedule (polling vs EOD schedule).`
  `- POST /api/strategy-watch/evaluate (triggers immediate evaluation).`
- **potential_consequence:** Automated API verification tests following the plan will issue `POST` to `/api/strategy-watch/schedule` (receiving HTTP 405 Method Not Allowed) and `POST` to `/api/strategy-watch/evaluate-now` (receiving HTTP 404 Not Found), failing the audit.

---

### Conclusion

The plan is **NOT CLEAN** (2 Gate-Level Findings). Remediate finding 1 (`ids: string[]` in `watchedContractsStore.ts` persisted state) and finding 2 (Strategy Watch `PUT /schedule` and `POST /evaluate` endpoints) in `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` before re-auditing in Round 3.
