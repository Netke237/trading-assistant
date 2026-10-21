# APP-AUDIT-MONITORING — Lane G Execution Plan

**Tracking:** Issue #355, Programme #348  
**Phase ID:** `APP-AUDIT-MONITORING`  
**Branch:** `board/app-audit-monitoring-7fb31a2c`  
**Worktree:** `.worktrees/app-audit-monitoring`  
**Source Baseline:** Frozen at `origin/main` commit `90969cf9`  
**Report Destination:** `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md`  

---

## 1. Goal and Deliverables

Verify Watchlist, Alerts, Strategy Watch, Auto-Trade controls, and Scheduled Automation end to end across frontend pages (`frontend/app/(frame)/{watchlist,alerts,strategy-watch}/`), parallel context rails (`@contextRail/{watchlist,alerts,strategy-watch}/`), Zustand stores, backend routers (`alerts.py`, `chart_alerts.py`, `ws_alerts.py`, `strategy_watch.py`, `auto_trade.py`), background schedulers, state-machine evaluators, and notification dispatch pipelines.

The audit establishes:
1. **Mathematical, Indicator & State Machine Parity**: Independent verification of chart alert condition logic (`chartAlertEngine.ts`, `alertIndicators.ts`), indicator smoothing (Wilder vs EMA vs SMA), threshold comparisons (`>`, `<`, `crosses_above`, `crosses_below`), portfolio position alert evaluation (`alertEngine.ts:scanPositions`), Strategy Watch state-machine transitions between `phase: "idle"` and `phase: "armed"` emitting events (`entry`, `exit_stop`, `exit_target`, `time_stop`, `reversal`) across the 5 valid daily strategies, and auto-trade pre-trade safety gates (`RegimeHeadwindError`, event veto `_apply_event_veto`, conviction sizing).
2. **State & Persistence Integrity**: Storage key conventions (`bamendjou-watchlist-v1`, `bamendjou-watched-contracts-v1`, `bamendjou-alerts-v2`, `bamendjou:alerts`, `bamendjou-auto-trade`), versioned schema migrations (`watchedContractsStore` v3 with `grading`, `alertStore` v3 with portfolio toasts), symmetric add/remove, partialize safety exclusions (`useAutoTradeStore` disarming on reload), backend YAML/DB synchronization (`strategy_watches.yaml`, `PortfolioPositionModel.alert_state`), and restart restoration.
3. **Automated Action & Event Stub Verification**: Verification of Strategy Watch transition event emissions, auto-trade pre-trade gates, and notification dispatch attempts strictly via fake transports, mocked broker stubs, and deterministic clocks. No real broker orders, emails, or Telegram messages are dispatched.
4. **Concurrency, Cancellation & Real-Time Stream Safety**: Concurrency serialization in auto-trade (`_FIRE_EXECUTOR`), cancellation cleanup (`_log_unbooked`), WebSocket alert streaming (`/ws/alerts`), heartbeat, client reconnection, and scheduler thread safety across market hours.
5. **Boundary & Error Behavior**: Handling of empty watchlists, missing quotes, unauthenticated broker states, invalid rule configurations, stale asynchronous data, network interruptions, and background scheduler recovery (`chart_alert_scheduler.py`, `strategy_watch_scheduler.py`, etc.).
6. **Reconciliation with Lane A**: Alignment with route, store, and scheduled job inventories from `APP-AUDIT-INVENTORY` (#349), linking with #168 (`WATCHLIST-RESIDUALS`) and #178 (`DECISION-34-WATCH-DELIVERY-RESIDUALS`).

**Audit Boundaries:**
- Audit and report scope only. No application code, algorithm weights, or database schemas are modified during this audit phase.
- Discovered defects are cataloged into structured findings (`defects.json`); each actionable defect becomes a separate board remediation ticket.
- No live broker orders, external emails, Telegram dispatches, destructive database operations, or unisolated background jobs are triggered.

---

## 2. Scope & Target Surfaces

### A. Surface 1: Watchlist Subsystem
- **User Interface**: `frontend/app/(frame)/watchlist/page.tsx` & `@contextRail/watchlist/page.tsx` (dedicated rail).
- **Sub-Tabs & Columns (local state in `watchlist/page.tsx`)**:
  - **Stocks Tab (`tab === 'stocks'`)**: Renders starred symbols via `useWatchlistStore`. Columns: `SYMBOL`, `NAME`, `PRICE`, `DIR`, `HORIZON`, `SCORE`, `RANK Δ`, `SCORE Δ`, `NEXT EVENT`.
  - **Contracts Tab (`tab === 'contracts'`)**: Renders starred option contracts via `useWatchedContractsStore`. Columns: `SYMBOL`, `CONTRACT`, `DTE`, `PRICE`, `DELTA`, `IV`, `Θ/DAY`, `SCORE`.
  - **Composite Tab (`tab === 'composite'`)**: Renders active composite watch subscriptions and summaries.
- **Zustand Persistence & State Models**:
  - `useWatchlistStore` (`frontend/lib/watchlistStore.ts`):
    - Persisted key: `bamendjou-watchlist-v1` (`WATCHLIST_STORAGE_KEY`, grandfathered hyphen format).
    - Versioned schema migration (`version: 1`).
    - Operations: `addSymbol`, `removeSymbol`, `isWatched`, `syncFromBackend`.
    - Backend sync: `POST /api/watchlist` and `GET /api/watchlist`.
  - `useWatchedContractsStore` (`frontend/lib/watchedContractsStore.ts`):
    - Persisted key: `bamendjou-watched-contracts-v1` (`WATCHED_CONTRACTS_STORAGE_KEY`, grandfathered hyphen format).
    - Versioned schema migration (`version: 3`). Migration rule: `version < 3 ? { ...state, grading: {} } : state`.
    - Methods: `add(id, grading)`, `remove(id)`, `clearGrading(id)`, `isWatched(id)`.
    - Canonical contract identity: `contractId(symbol, strike, expiry, right)` $\rightarrow$ `"AAPL|185|2025-05-16|C"`.
    - Persisted state: `contracts: string[]`, `grading: Record<string, ContractGrading>`.
  - `useWatchlistUiStore` (`frontend/lib/watchlistUiStore.ts`):
    - Ephemeral UI store managing active `selectedSymbol: string | null` for cross-component rail synchronization.
- **Context Rail Integration (`@contextRail/watchlist/page.tsx`)**:
  - Dedicated domain-specific rail sections:
    - Status breakdown (`PASS`, `CAUTION`, `REJECT` counts across active watchlist).
    - Flags summary (`Events ≤ 7d` count, `Total` count).
    - `SymbolNotes` on active `selectedSymbol`.
    - `RailQuickLook` for summary statistics.
- **Linkage with #168 (`WATCHLIST-RESIDUALS`)**:
  - Auditing contract rule evaluations and watchlist refresh gap residuals.

### B. Surface 2: Alerts Subsystem & Rule Engine
- **User Interface**: `frontend/app/(frame)/alerts/page.tsx`, `AlertRuleBuilder`, `CompositeAlertDialog`, `@contextRail/alerts/page.tsx`.
- **Zustand Persistence & State Separation**:
  - `useAlertStore` (`frontend/lib/alertStore.ts`):
    - Persisted key: `bamendjou-alerts-v2` (grandfathered hyphen format).
    - Schema `version: 3`. Stores portfolio position alert toasts (`ToastItem[]`), `AlertConfig`, and `firedAlerts`/`suppressedAlerts`.
    - Evaluated by `alertEngine.ts:scanPositions` against portfolio positions and live quotes.
  - `useChartAlertStore` (`frontend/lib/chartAlertStore.ts`):
    - Persisted key: `bamendjou:alerts` (modern colon format).
    - Stores `rules: AlertRule[]`, `history: AlertHistory[]`, and `toasts: ChartToast[]`.
    - Schema: `AlertRule` (`id`, `name`, `symbol`, `interval`, `enabled`, `group: ConditionGroup` with nested `conditions: Condition[]`, `cooldown_minutes`, `expiry_date`, `created_at`, `last_triggered_at`, `rule_type`, `composite_def`).
    - Indicators: `rsi`, `sma`, `ema`, `macd`, `bb`, `atr`, `price`, `volume`.
    - Operators: `>`, `<`, `>=`, `<=`, `crosses_above`, `crosses_below`.
- **Chart Alert Evaluation Engine (`frontend/lib/chartAlertEngine.ts` & `alertIndicators.ts`)**:
  - Multi-bar indicator evaluation against historical candle series.
  - Cross-condition detection: requires comparing bar $t-1$ and bar $t$ to establish genuine crossing events (`crosses_above = prev <= thresh && curr > thresh`).
  - Python 3.11 numerical parity verification (`frontend/lib/__tests__/fixtures/alert_indicator_python311.json`).
- **Backend Alert Evaluation & WebSockets**:
  - `GET /api/alerts`: Position alerts, portfolio stop levels, and `PREMIUM_STOP` evaluation (`backend/app/routers/alerts.py:21-60`).
  - `POST /alerts/rules` & `GET /alerts/rules` (and `GET /alerts/history`, `DELETE /alerts/rules/{id}`) in `backend/app/routers/chart_alerts.py`.
  - WebSocket Streaming (`/ws/alerts` in `backend/app/routers/ws_alerts.py`):
    - Real-time alert push to active browser clients.
    - Connection management, ping/pong heartbeat, client disconnect/reconnect handling.

### C. Surface 3: Strategy Watch Subsystem & State Machine
- **User Interface**: `frontend/app/(frame)/strategy-watch/page.tsx` & `@contextRail/strategy-watch/page.tsx`.
- **Frontend Store**: `useStrategyWatchStore` (`frontend/lib/strategyWatchStore.ts`):
  - In-memory API-backed store (no client-side `persist`), backed by backend endpoints:
    - `GET /api/strategy-watch/` (lists non-composite strategy watches).
    - `POST /api/strategy-watch/` (creates watch with `symbol`, `strategy_key`, `direction`, `params_horizon`).
    - `POST /api/strategy-watch/bulk` (bulk subscription).
    - `PATCH /api/strategy-watch/{watch_id}` with body `{"enabled": bool}` (toggles enabled state).
    - `DELETE /api/strategy-watch/{id}` (removes watch).
    - `GET /api/strategy-watch/schedule` & `POST /api/strategy-watch/schedule` (polling vs EOD schedule).
    - `POST /api/strategy-watch/evaluate-now` (triggers immediate evaluation).
- **Backend State Machine Evaluator (`backend/app/services/strategy_watch_evaluator.py`)**:
  - Evaluates the 5 valid daily stock strategies (`VALID_STRATEGIES` in `strategy_watch_store.py`):
    1. `pullback_ema`
    2. `breakout_base`
    3. `ma_crossover`
    4. `mean_reversion_rsi`
    5. `mean_reversion_bb`
    *(Note: `mean_reversion_vwap` is explicitly excluded from daily watches as an intraday-only strategy).*
  - State Machine Lifecycle:
    - Maintained phases: `phase: "idle"` and `phase: "armed"`.
    - Emitted Event Types:
      - `entry`: Signal triggers entry while in `idle` phase $\rightarrow$ transitions to `armed`.
      - `exit_stop`: Stop-loss breached while `armed` $\rightarrow$ resets to `idle`.
      - `exit_target`: Profit target reached while `armed` $\rightarrow$ resets to `idle`.
      - `time_stop`: Holding duration exceeds horizon bar limit while `armed` $\rightarrow$ resets to `idle`.
      - `reversal`: Opposing trend signal fired while `armed` $\rightarrow$ resets to `idle`.
  - Time Stop Logic (`TIME_STOP`): Horizon-dependent maximum holding period (e.g. 10 bars for Swing, 5 bars for Momentum).
- **Backend Scheduler & Storage**:
  - `strategy_watch_scheduler.py`: Background evaluation loop based on schedule configuration (`eod` at 16:15 or `poll` every N hours).
  - Persistence: `backend/app/services/strategy_watch_store.py` reading/writing `backend/config/strategy_watches.yaml`.
- **Linkage with #178 (`DECISION-34-WATCH-DELIVERY-RESIDUALS`)**:
  - Per-channel watch delivery, stuck-alert handling, un-deliverable event resend queue.

### D. Surface 4: Auto-Trade Controls & Pre-Trade Safety Gates
- **User Interface**: `AutoTradeCard` (`frontend/components/organisms/AutoTradeCard/index.tsx`).
- **Frontend Store**: `useAutoTradeStore` (`frontend/lib/autoTradeStore.ts`):
  - Persisted key: `bamendjou-auto-trade` (grandfathered hyphen format).
  - State model: `selectedBroker`, `autoMode: 'manual' | 'post_scan' | 'armed'`, `armed: boolean`, `armedDirection`, `armedSymbol`, `lastOrderId`.
  - **Critical Reload Disarming Safety**: The `partialize` configuration explicitly excludes `armed`, `armedDirection`, and `armedSymbol` from localStorage persistence, ensuring auto-trade unconditionally disarms on page refresh/restart.
- **Backend Execution Engine (`backend/app/routers/auto_trade.py` & `backend/app/services/auto_trader.py`)**:
  - Endpoints:
    - `POST /auto-trade/arm`: Arms auto-trader with strategy parameters.
    - `DELETE /auto-trade/arm`: Disarms active strategy.
    - `POST /auto-trade/fire`: Executes order for armed strategy.
    - `GET /auto-trade/status`: Returns current arming status, regime, sizing, and `last_order`.
  - Concurrency Serialization: `_FIRE_EXECUTOR` (single-worker `ThreadPoolExecutor`) serializing all `/fire` calls to prevent concurrent execution races.
  - Pre-Trade Safety Gates:
    1. **Regime Alignment Gate**: Blocks trade if market regime opposes direction (`RegimeHeadwindError` $\rightarrow$ HTTP 400). Note: `RegimeGateConfigError` ($\rightarrow$ HTTP 500) indicates malformed YAML configuration.
    2. **Event Proximity Gate (`_apply_event_veto`)**: Vetoes candidates within `max(YAML reject_window, hold_bars)` or unknown single-stock earnings, NOT the caution window.
    3. **Conviction Sizing Gate**: Validates portfolio value, maximum risk dollar bounds, and allocation caps (`SizingConfigError`).
    4. **Unvalidated Bearish Strategy Gate**: Rejects bearish strategies on unvalidated regimes.
  - Failure & Cancellation Handling:
    - If request is cancelled before execution: `_log_unbooked` logs warning, nothing sent.
    - Fired order booking: `book_fired_order` records position directly into `PortfolioPositionModel`.
    - IBKR confirmation handling: `AUTOTRADE-IBKR-CONFIRM-NOT-SUBMITTED` guards.

### E. Surface 5: Notification Dispatch & Delivery Attempts
- **Source Modules**: `backend/app/services/notifications/dispatch.py`, `gmail.py`, `telegram.py`, `sent_log.py`, `alert_notifier.py`.
- **Channels**:
  - `gmail`: Sends email via SMTP / Gmail API using configured sender and credentials.
  - `telegram`: Dispatches message via Telegram Bot API (`sendMessage`).
- **Configuration & Failure Safety**:
  - `read_notification_config()` reads `backend/config/settings.yaml`. A missing or malformed configuration gracefully falls back to empty channels without crashing.
  - `_safe_notify`: Catches all network/API exceptions; returns `False` and logs structured error.
  - `sent_log.py`: Append-only JSONL delivery audit log (`log_sent`, `prune_sent_log`) recording timestamp, channel, recipient, and subject hash.
  - Upstream Cooldown Enforcement: Cooldowns and deduplication are strictly enforced upstream in `alert_notifier.py` and `strategy_watch_evaluator.py` before reaching `sent_log.py`.
- **Testing Standard**:
  - Strictly verified using fake transports and in-memory mocks. No live emails or Telegram dispatches are executed.

### F. Surface 6: Scheduled Automation Systems
- **Scheduler Inventory**:
  1. `scan_schedule_scheduler.py`: Scheduled stock/option scans at configured cadence.
  2. `strategy_watch_scheduler.py`: Periodic evaluation of enabled strategy watches.
  3. `chart_alert_scheduler.py`: Background scheduler evaluating chart alert rules across closed candles outside browser sessions.
  4. `tuning_scheduler.py`: Walk-forward optimization parameter tuning jobs.
  5. `edgar_scheduler.py`: Nightly SEC EDGAR financial statement ingest.
  6. `sp500_scheduler.py`: S&P 500 liquidity and constituent updates.
  7. `ingestion_scheduler.py`: Historical OHLCV bar ingestion from Tiingo/YFinance (`backend/config/ingestion_schedule.yaml`).
- **Lifecycle & Operational Safety**:
  - Concurrency guards, cancellation token propagation, timezone anchoring (UTC vs US/Eastern), error logging boundaries, and safe recovery across server restarts.

---

## 3. Execution Plan & Tasks

### Task 1: Mathematical, Indicator & State Machine Parity Verification
- [ ] Independently derive indicator algorithms in `alertIndicators.ts` and `chartAlertEngine.ts` (RSI, SMA, EMA, MACD, Bollinger Bands, ATR); verify exact boundary calculations against Python 3.11 golden references.
- [ ] Verify crossing operator logic (`crosses_above`, `crosses_below`) against 2-bar sequential state transitions.
- [ ] Verify portfolio position alert evaluation in `alertEngine.ts:scanPositions` against stop prices and profit targets.
- [ ] Verify Strategy Watch state machine transitions between `idle` and `armed` phases and emitted event types (`entry`, `exit_stop`, `exit_target`, `time_stop`, `reversal`) across the 5 valid daily strategies.
- [ ] Verify auto-trade pre-trade safety gates: `RegimeHeadwindError` on opposing regime, event veto on `max(reject, hold)` days, and conviction sizing limits.

### Task 2: Persistence, Migration & Storage Key Audit
- [ ] Audit localStorage storage keys: verify exact key strings (`bamendjou-watchlist-v1`, `bamendjou-watched-contracts-v1`, `bamendjou-alerts-v2`, `bamendjou:alerts`, `bamendjou-auto-trade`).
- [ ] Verify versioned `migrate` callbacks:
  - `watchedContractsStore.ts` (`version: 3` with `grading: Record<string, ContractGrading>`).
  - `watchlistStore.ts` (`version: 1`).
  - `alertStore.ts` (`version: 3` with portfolio toasts).
- [ ] Verify `useAutoTradeStore` partialize configuration: confirm `armed`, `armedDirection`, and `armedSymbol` are deliberately omitted so auto-trade disarms on reload.
- [ ] Verify backend persistence in `strategy_watches.yaml` and database `alert_state` fields: verify data roundtrips across simulated server restarts.
- [ ] Verify that unpersisted stores (`useStrategyWatchStore`) faithfully synchronize with backend endpoints without stale local caching.

### Task 3: Concurrency, Cancellation & Real-Time Event Audit
- [ ] Verify auto-trade single-worker serialization via `_FIRE_EXECUTOR` and cancellation protection via `_log_unbooked`.
- [ ] Verify WebSocket `/ws/alerts` streaming lifecycle: client connection, subscription, broadcast reception, heartbeat timeout, and reconnection backoff.
- [ ] Verify upstream notification cooldowns and deduplication in `alert_notifier.py` and `strategy_watch_evaluator.py`, plus append-only audit logging in `sent_log.py`.
- [ ] Verify background scheduler concurrency and lifecycle: test `chart_alert_scheduler.py`, `strategy_watch_scheduler.py`, and `scan_schedule_scheduler.py` for safe debouncing and error boundary containment.

### Task 4: UI Presentation, Boundary & Accessibility Audit
- [ ] Test all 3 Watchlist tabs (`stocks`, `contracts`, `composite`) and verify exact rendered columns.
- [ ] Test empty states across all monitoring pages: Watchlist with 0 symbols/contracts, Alerts with 0 rules, Strategy Watch with 0 subscriptions.
- [ ] Verify dedicated parallel context rail `@contextRail/watchlist` (Status breakdown, Flags, SymbolNotes, RailQuickLook) vs generic fallback shims on Alerts and Strategy Watch.
- [ ] Verify keyboard navigation, ARIA attributes, and toggle switch accessibility across AlertRuleBuilder and StrategyWatch tables.
- [ ] Verify theme tokens (`--bg-surface`, `--border-subtle`, `--text-primary`, `--pass`, `--caution`, `--reject`) and zero card shadow conventions.

### Task 5: Inventory Reconciliation & Defect Catalog
- [ ] Reconcile every monitoring route, store, and scheduled job against `APP-AUDIT-INVENTORY` (#349).
- [ ] Author comprehensive audit report at `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/report.md`.
- [ ] Catalog all discovered defects in `docs/superpowers/audits/app-audit/APP-AUDIT-MONITORING/defects.json`.
- [ ] Record execution provenance in `provenance.json`.

---

## 4. Verification & Testing Methodology

- **Automated Backend Tests**:
  - Run existing test suites: `test_strategy_watch_*.py`, `test_auto_trade*.py`, `test_autotrade_*.py`, `test_alerts.py`, `test_chart_alert_scheduler.py`.
  - Author dedicated Lane G audit test suites pinning state machine transitions, alert indicator math, and notification attempt logging.
- **Automated Frontend Tests**:
  - Run existing test suites: `watchlistStore.test.ts`, `watchedContractsStore.test.ts`, `alertStore.test.ts`, `alertEngine.test.ts`, `alertIndicators.test.ts`, `strategyWatchStore.test.ts`, `alerts/page.test.tsx`, `watchlist/page.test.tsx`.
  - Author dedicated frontend audit test suites.
- **Typecheck & Lint**:
  - `npm run typecheck` (`tsc --noEmit`) in frontend.
  - Python type/syntax verification on backend routers and services.
- **State Integrity**:
  - Zero drift in `python scripts/state.py`.
