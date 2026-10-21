# Adversarial Plan Audit (Round 1): APP-AUDIT-MONITORING (#355)

**Review Target:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md`  
**Phase ID:** `APP-AUDIT-MONITORING`  
**Branch:** `board/app-audit-monitoring-7fb31a2c`  
**Reviewer:** Independent Adversarial Subagent (`bmad-review-adversarial-general`)  
**Standard:** Project Numeric & Persistence Gate (finding blocks if it puts a wrong number in front of user/broker, corrupts persisted data, or misstates mechanism such that a competent reader acting on it writes a wrong change).  
**Status:** **NOT CLEAN (17 Gate-Level Findings)**

---

### Audit Report Summary

A rigorous adversarial review of `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` against the real codebase across Watchlist, Alerts, Strategy Watch, Auto-Trade, Notification Dispatch, and Schedulers revealed 17 gate-level findings. The plan suffers from widespread mechanism confusion between stores (confusing portfolio alerts with chart alert rules), misstated API endpoints, phantom store schemas/methods, hallucinated state-machine transitions and unsupported strategies, incorrect pre-trade safety gate classifications, and omission of key background schedulers.

Below is the complete list of findings in the required 4-field format.

---

### Findings (Round 1)

1.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:44-48, 154-155` (Section 2.A & Task 2)
- **trigger_condition:** Plan asserts `useWatchedContractsStore` is schema `version: 1` with methods `addContract`, `removeContract`, `toggleContract`, `hasContract`, and omits the `grading` map.
- **guard_snippet:** Update plan to reflect schema `version: 3`, methods `add(id, grading)`, `remove(id)`, `clearGrading(id)`, `isWatched(id)`, and audit `grading: Record<string, ContractGrading>` persistence and migration (`version < 3 ? {} : grading`).
- **potential_consequence:** A competent implementer or auditor writing tests for `watchedContractsStore` will test non-existent methods and assert on an incorrect schema version, failing to verify the v3 contract grading persistence required by #168 (`WATCHLIST-SCAN-CONTRACT-RULES`), risking corrupted or discarded contract grading upon store migration.

2.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:42` (Section 2.A)
- **trigger_condition:** Plan asserts `useWatchlistStore` has symmetric operations `addSymbol`, `removeSymbol`, `toggleSymbol`, `hasSymbol`.
- **guard_snippet:** Correct the operation list in the plan to `addSymbol`, `removeSymbol`, `isWatched`, and `syncFromBackend`.
- **potential_consequence:** Test suites authored according to the plan will call `toggleSymbol` and `hasSymbol`, causing immediate runtime `TypeError: store.toggleSymbol is not a function`.

3.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:49` (Section 2.A)
- **trigger_condition:** Plan claims `useWatchlistUiStore` (`frontend/lib/watchlistUiStore.ts`) manages UI tab selection (`'stocks' | 'contracts'`).
- **guard_snippet:** Specify that `useWatchlistUiStore` exclusively manages ephemeral `selectedSymbol: string | null` for context rail synchronization, while tab selection (`'stocks' | 'contracts' | 'composite'`) is local state in `frontend/app/(frame)/watchlist/page.tsx`.
- **potential_consequence:** Implementers or testers will write code attempting to set or observe tab selection through `useWatchlistUiStore`, causing state divergence and broken tab test assertions.

4.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:35-37` (Section 2.A)
- **trigger_condition:** Plan misstates Watchlist tabs and columns (asserts Stocks tab shows market cap, sector, day change %; asserts Contracts tab shows bid/ask, gamma, vega; completely omits the Composite Alerts tab).
- **guard_snippet:** Update plan to document all 3 tabs (`stocks`, `contracts`, `composite`) and correct rendered columns: Stocks (`SYMBOL`, `NAME`, `PRICE`, `DIR`, `HORIZON`, `SCORE`, `RANK Δ`, `SCORE Δ`, `NEXT EVENT`); Contracts (`SYMBOL`, `CONTRACT`, `DTE`, `PRICE`, `DELTA`, `IV`, `Θ/DAY`, `SCORE`).
- **potential_consequence:** Audit tests will assert on non-existent columns (market cap, sector, bid/ask, gamma, vega) absent from `WatchlistRow` and `WatchedContractRow`, generating false-positive failures and leaving the Composite Alerts tab completely unverified.

5.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:50-51` (Section 2.A)
- **trigger_condition:** Plan asserts `@contextRail/watchlist/page.tsx` renders summary metrics: watchlist market cap distribution, portfolio overlap count, and quick scan button.
- **guard_snippet:** Correct context rail inventory to: Status breakdown (`PASS`, `CAUTION`, `REJECT` counts), Flags (`Events ≤ 7d`, `Total`), `SymbolNotes` on active selection, and `RailQuickLook`.
- **potential_consequence:** Test harnesses asserting on market cap distribution, portfolio overlap, and quick scan buttons in the context rail will fail against production code.

6.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:58-65, 154` (Section 2.B & Task 2)
- **trigger_condition:** Plan asserts `useAlertStore` (`bamendjou-alerts-v2`) stores `AlertRule` with indicators/operators, and that `useChartAlertStore` only holds chart lines.
- **guard_snippet:** Clarify that `useAlertStore` (`bamendjou-alerts-v2`, `version: 3`) stores portfolio position alert toasts (`ToastItem[]`), `AlertConfig`, and `firedAlerts`/`suppressedAlerts`. Clarify that `useChartAlertStore` (`bamendjou:alerts`) stores `rules: AlertRule[]`, `history: AlertHistory[]`, and `toasts: ChartToast[]`.
- **potential_consequence:** An implementer or auditor acting on the plan will write schema migrations or audit checks looking for `AlertRule` in `useAlertStore`, risking severe corruption of persisted portfolio toasts and leaving chart alert rules completely unverified.

7.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:60` (Section 2.B)
- **trigger_condition:** Plan asserts a flat `AlertRule` schema (`id`, `symbol`, `indicator`, `operator`, `threshold`, `enabled`, `createdAt`, `lastTriggered`, `cooldownMinutes`).
- **guard_snippet:** Update schema definition to match `types/alerts.ts`: `id`, `name`, `symbol`, `interval`, `enabled`, `group: ConditionGroup` (containing `conditions: Condition[]`), `cooldown_minutes`, `expiry_date`, `created_at`, `last_triggered_at`, `rule_type`, and `composite_def`.
- **potential_consequence:** Audit tests validating rule serialization will test flat fields instead of the composite `group.conditions` tree and snake_case properties, causing serialization/deserialization failures and invalid API payloads.

8.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:17, 66-69, 148` (Section 1, Section 2.B & Task 1)
- **trigger_condition:** Plan identifies `alertEngine.ts` as the multi-bar candle indicator and crossing operator evaluation engine.
- **guard_snippet:** Correct the target module to `chartAlertEngine.ts` for indicator condition evaluation and 2-bar crossing detection (`crosses_above`, `crosses_below`) against historical candles, and distinguish `alertEngine.ts` as the portfolio position alert evaluator (`scanPositions`).
- **potential_consequence:** Verification scripts will search `alertEngine.ts` for indicator evaluation and crossing logic, failing to find them or falsely reporting indicator evaluation as missing from the codebase.

9.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:72` (Section 2.B)
- **trigger_condition:** Plan asserts backend chart alert endpoints are `POST /chart/alerts` & `GET /chart/alerts`.
- **guard_snippet:** Correct endpoint paths to `POST /alerts/rules` and `GET /alerts/rules` (and `/alerts/history`) under router prefix `/alerts` in `backend/app/routers/chart_alerts.py`.
- **potential_consequence:** Automated integration tests following the plan will hit `POST /chart/alerts` and `GET /chart/alerts`, receiving HTTP 404 Not Found and failing the audit.

10.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:84` (Section 2.C)
- **trigger_condition:** Plan asserts Strategy Watch toggle endpoint is `PATCH /api/strategy-watch/{id}/enabled`.
- **guard_snippet:** Correct endpoint path to `PATCH /api/strategy-watch/{watch_id}` with request body `{"enabled": bool}`.
- **potential_consequence:** Audit tests targeting `PATCH /api/strategy-watch/{id}/enabled` will fail with HTTP 404 Not Found.

11.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:17, 89-94, 150` (Section 1, Section 2.C & Task 1)
- **trigger_condition:** Plan asserts Strategy Watch state machine transitions across 5 phases (`idle` $\rightarrow$ `armed` $\rightarrow$ `triggered` $\rightarrow$ `exit` $\rightarrow$ `closed`) across all 7 stock strategies.
- **guard_snippet:** Correct state machine phases to `idle` and `armed` (`phase: "idle" | "armed"`), with emitted event types `entry`, `exit_stop`, `exit_target`, `time_stop`, and `reversal`. Restrict evaluation to the 5 valid daily strategies in `strategy_watch_store.py:VALID_STRATEGIES` (`pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`), noting that `mean_reversion_vwap` is explicitly excluded as intraday-only.
- **potential_consequence:** Test harnesses constructed to verify non-existent states (`triggered`, `exit`, `closed`) and unsupported strategies will crash or produce invalid state machines, putting wrong lifecycle statuses in front of users.

12.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:104-106` (Section 2.D)
- **trigger_condition:** Plan asserts `useAutoTradeStore` controls `armed`, `executionMode: 'paper' | 'live'`, `maxTradesPerDay`, `maxAllocationPct`.
- **guard_snippet:** Correct state model to `selectedBroker`, `autoMode` (`'manual' | 'post_scan' | 'armed'`), `armed`, `armedDirection`, `armedSymbol`, `lastOrderId`. Emphasize that `armed`, `armedDirection`, and `armedSymbol` are deliberately excluded from localStorage persistence via `partialize` to prevent dangerous resumption across reloads.
- **potential_consequence:** Tests attempting to mutate or verify persistence of `maxTradesPerDay`, `maxAllocationPct`, or `executionMode` on `useAutoTradeStore` will fail, and asserting persistence of `armed` would violate the safety requirement that auto-trade must disarm on reload.

13.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:108` (Section 2.D)
- **trigger_condition:** Plan asserts auto-trade endpoints include `POST /auto-trade/disarm` and `GET /auto-trade/history`.
- **guard_snippet:** Correct endpoints to `DELETE /auto-trade/arm` for disarm and `GET /auto-trade/status` (which returns `last_order`).
- **potential_consequence:** Audit test scripts issuing `POST /auto-trade/disarm` or `GET /auto-trade/history` will receive HTTP 405 Method Not Allowed / HTTP 404 Not Found.

14.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:111-112` (Section 2.D)
- **trigger_condition:** Plan confuses `RegimeGateConfigError` with market alignment rejection and asserts the Event Proximity Gate checks the horizon caution window.
- **guard_snippet:** Correct gate definitions: market regime opposition raises `RegimeHeadwindError` (HTTP 400), whereas `RegimeGateConfigError` (HTTP 500) indicates malformed YAML configuration. Event Proximity Gate (`_apply_event_veto`) rejects candidates within `max(YAML reject, hold)` or unknown single-stock earnings, NOT the caution window.
- **potential_consequence:** An auditor writing verification tests would expect HTTP 500 for regime rejection or expect trades in the caution window to be vetoed, mischaracterizing correct broker order admission/refusal behavior.

15.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:128, 162` (Section 2.E & Task 3)
- **trigger_condition:** Plan asserts `sent_log.py` enforces notification cooldowns and duplicate prevention via subject hashes.
- **guard_snippet:** Clarify that `sent_log.py` is an append-only JSONL delivery audit log (`log_sent`, `prune_sent_log`), while notification cooldowns and deduplication are enforced upstream in `alert_notifier.py` and `strategy_watch_evaluator.py`.
- **potential_consequence:** Test authors will write assertions against `sent_log.py` expecting cooldown throttling, which will fail because `sent_log.py` unconditionally appends every record it receives.

16.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:133-140` (Section 2.F)
- **trigger_condition:** Plan omits `chart_alert_scheduler.py` from the scheduled automation inventory.
- **guard_snippet:** Add `chart_alert_scheduler.py` (`backend/app/services/chart_alert_scheduler.py`) to Section 2.F and Task 3 as the background scheduler evaluating chart alert rules across closed candles outside browser sessions.
- **potential_consequence:** The audit will completely skip verification of background chart alert evaluation, leaving background rule execution and catch-up candle logic unverified.

17.
- **location:** `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md:167` (Task 4)
- **trigger_condition:** Plan asserts dedicated parallel context rails for `@contextRail/alerts` and `@contextRail/strategy-watch`.
- **guard_snippet:** Note that `@contextRail/alerts/page.tsx` and `@contextRail/strategy-watch/page.tsx` are generic shims exporting `RailQuickLook` via `default.tsx`, whereas `@contextRail/watchlist` is the only dedicated rail with domain-specific sections (`Status breakdown`, `Flags`, `SymbolNotes`).
- **potential_consequence:** UI audit tasks will search for bespoke rail components on Alerts and Strategy Watch, leading to spurious defect reports for standard fallback layouts.

---

### Conclusion

The plan is **NOT CLEAN** (17 findings). All findings must be remediated in `docs/superpowers/plans/2026-10-21-app-audit-monitoring-plan.md` before proceeding to Plan Round 2.
