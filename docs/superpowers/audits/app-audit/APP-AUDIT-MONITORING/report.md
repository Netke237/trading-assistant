# APP-AUDIT-MONITORING reconciliation report

**Programme:** APP-AUDIT (#348)  
**Phase ID:** `APP-AUDIT-MONITORING` (#355)  
**Worktree:** `.worktrees/app-audit-monitoring`  
**Branch:** `board/app-audit-monitoring-7fb31a2c`  
**Target Surfaces:** Watchlist (`frontend/app/(frame)/watchlist/`), Alerts (`frontend/app/(frame)/alerts/`), Strategy Watch (`frontend/app/(frame)/strategy-watch/`), Context Rails (`@contextRail/{watchlist,alerts,strategy-watch}/`), Zustand stores (`useWatchlistStore`, `useWatchedContractsStore`, `useWatchlistUiStore`, `useAlertStore`, `useChartAlertStore`, `useStrategyWatchStore`, `useAutoTradeStore`), backend routers (`alerts.py`, `chart_alerts.py`, `ws_alerts.py`, `strategy_watch.py`, `auto_trade.py`), backend evaluators (`strategy_watch_evaluator.py`, `chartAlertEngine.ts`, `alertEngine.ts`), notification dispatch (`notifications/dispatch.py`, `sent_log.py`), and background schedulers (`scan_schedule_scheduler.py`, `strategy_watch_scheduler.py`, `chart_alert_scheduler.py`, `tuning_scheduler.py`, `edgar_scheduler.py`, `sp500_scheduler.py`, `ingestion_scheduler.py`).  
**Baseline Commit:** Frozen at `origin/main` (`90969cf9`)  
**Status:** Audit Complete — Zero Gate Findings across indicator math, state machines, storage migrations, safety gates, and scheduler lifecycles; 3 non-gate follow-up defects cataloged.

---

## 1. Executive Summary

This reconciliation report delivers the comprehensive Lane G data, state machine, persistence, concurrency, and presentation audit across the monitoring, automated evaluation, and notification subsystems of the trading assistant:
1. **Watchlist Subsystem (`/watchlist`)** — Starred stock and contract tracking, schema migrations (`useWatchedContractsStore` v3 with `ids: string[]` and `grading: Record<string, ContractGrading>`), symmetric add/remove, and column presentation across Stocks, Contracts, and Composite tabs.
2. **Alerts Subsystem (`/alerts`)** — Clean architectural separation between portfolio position alerts (`useAlertStore` v3, `bamendjou-alerts-v2`) and chart indicator alert rules (`useChartAlertStore`, `bamendjou:alerts`). Condition evaluation across multi-bar candle sequences with exact crossing operators (`crosses_above`, `crosses_below`) and backend API parity (`/alerts/rules`).
3. **Strategy Watch Subsystem (`/strategy-watch`)** — State machine transitions between `phase: "idle"` and `phase: "armed"`, emitting 5 distinct event types (`entry`, `exit_stop`, `exit_target`, `time_stop`, `reversal`) across the 5 valid daily stock strategies (`pullback_ema`, `breakout_base`, `ma_crossover`, `mean_reversion_rsi`, `mean_reversion_bb`), strictly rejecting `mean_reversion_vwap` as intraday-only.
4. **Auto-Trade Controls & Pre-Trade Gates** — Pre-trade safety gates enforcing opposing-regime block (`RegimeHeadwindError`, HTTP 400), malformed config detection (`RegimeGateConfigError`, HTTP 500), event proximity veto over `max(reject_window, hold_bars)` days and unknown single-stock earnings, `useAutoTradeStore` partialize safety exclusion disarming on reload, single-worker serialization via `_FIRE_EXECUTOR`, and cancellation cleanup in `_log_unbooked`.
5. **Notification Dispatch & Delivery Audit Log** — Non-invasive verification of email and Telegram dispatch pipelines using fake transports. Verification of `sent_log.py` as an append-only JSONL delivery audit log, with upstream cooldowns and duplicate prevention in `alert_notifier.py` and `strategy_watch_evaluator.py`.
6. **Scheduled Automation Inventory** — Verification of all 7 background schedulers (`scan_schedule_scheduler.py`, `strategy_watch_scheduler.py`, `chart_alert_scheduler.py`, `tuning_scheduler.py`, `edgar_scheduler.py`, `sp500_scheduler.py`, `ingestion_scheduler.py`), validating error containment boundaries and non-blocking execution across market hours.

All evaluated mechanisms adhere strictly to the project's numerical and persistence gate: no formula presents an erroneous number to the user, no broker execution or state persistence is corrupted, and unpersisted state faithfully syncs with backend sources of truth.

---

## 2. Surface Inventory & Architecture Matrix

| Subsystem | UI Route / Component | Context Rail Slot | Zustand Store(s) | Persistence Key & Schema | Backend Routers / Services |
|---|---|---|---|---|---|
| **Watchlist** | `/watchlist`<br>`watchlist/page.tsx` | Dedicated rail:<br>`@contextRail/watchlist` | `useWatchlistStore`<br>`useWatchedContractsStore`<br>`useWatchlistUiStore` | `bamendjou-watchlist-v1` (v1)<br>`bamendjou-watched-contracts-v1` (v3)<br>Ephemeral rail sync | `backend/app/routers/watchlist.py`<br>`backend/app/routers/contract_rules.py` |
| **Alerts** | `/alerts`<br>`alerts/page.tsx`<br>`AlertRuleBuilder` | Fallback shim:<br>`@contextRail/alerts` | `useAlertStore`<br>`useChartAlertStore` | `bamendjou-alerts-v2` (v3)<br>`bamendjou:alerts` (unversioned) | `backend/app/routers/alerts.py`<br>`backend/app/routers/chart_alerts.py`<br>`backend/app/routers/ws_alerts.py` |
| **Strategy Watch** | `/strategy-watch`<br>`strategy-watch/page.tsx` | Fallback shim:<br>`@contextRail/strategy-watch` | `useStrategyWatchStore` | In-memory only<br>(fetches from backend) | `backend/app/routers/strategy_watch.py`<br>`strategy_watch_evaluator.py`<br>`strategy_watch_scheduler.py` |
| **Auto-Trade** | Screener Step 7 / TradeCard<br>`AutoTradeCard` | Inherits screener rail | `useAutoTradeStore` | `bamendjou-auto-trade` (v2)<br>*Excludes armed fields* | `backend/app/routers/auto_trade.py`<br>`backend/app/services/auto_trader.py` |
| **Notifications** | `/settings` (Notifications)<br>`alerts/page.tsx` | N/A | Settings store | `bamendjou-settings` | `backend/app/services/notifications/`<br>`dispatch.py`, `gmail.py`, `telegram.py`, `sent_log.py` |
| **Schedulers** | Background lifespan | N/A | N/A | Database & YAML | 7 schedulers running in background async tasks |

---

## 3. Data, State Machine & Arithmetic Parity Audit (The Gate)

### 3.1 Watchlist Subsystem

#### Store Persistence & Schema Migrations
- **`useWatchlistStore` (`frontend/lib/watchlistStore.ts`)**:
  - Storage Key: `bamendjou-watchlist-v1` (grandfathered hyphen format).
  - Version: 1.
  - State Shape: `added: string[]` (array of uppercase symbols).
  - Methods: `addSymbol(s)`, `removeSymbol(s)`, `isWatched(s)`, `syncFromBackend()`.
  - Invariant: Symmetric add/remove; idempotent operations; no ambiguous `toggleSymbol`.
- **`useWatchedContractsStore` (`frontend/lib/watchedContractsStore.ts`)**:
  - Storage Key: `bamendjou-watched-contracts-v1` (grandfathered hyphen format).
  - Version: 3.
  - Persisted State: `{ ids: string[], grading: Record<string, ContractGrading> }`.
  - Canonical Identity: `contractId(symbol, strike, expiry, right)` $\rightarrow$ `"AAPL|185|2025-05-16|C"`.
  - Migration Logic:
    ```typescript
    export function migrateWatchedContracts(persisted: unknown, version: number): Persisted {
      const { ids, grading } = sanitizePersisted(persisted);
      // v1/v2 -> v3: ids unchanged; stars made before gradings existed have none.
      return { ids, grading: version < 3 ? {} : grading };
    }
    ```
  - Grading Map: Step 6 assigns the `ContractGrading` snapshot when starred; if cleared via `clearGrading(id)` (e.g. 422 retry), the contract remains starred but reverts to `contract_rules.yaml` evaluation with a `YAML_MARKER` caution tint.
- **`useWatchlistUiStore` (`frontend/lib/watchlistUiStore.ts`)**:
  - Ephemeral store holding `selectedSymbol: string | null` for synchronizing the active row selection with the `@contextRail/watchlist` right rail.
  - Unlike `useChartStore` which defaults to `'AAPL'` and persists, `useWatchlistUiStore` initializes to `null`, correctly representing "no row selected".

#### Sub-Tabs & Rendered Columns
- **Stocks Tab (`tab === 'stocks'`)**:
  - Table grid columns: `COLUMNS = '32px 28px 72px 1.4fr 90px 80px 80px 90px 80px 60px 90px'`.
  - Exact Headers: `SYMBOL`, `NAME`, `PRICE`, `DIR`, `HORIZON`, `SCORE`, `RANK Δ`, `SCORE Δ`, `NEXT EVENT`.
  - Data formatting: Price formatted as `\$${row.price.toFixed(2)}`; Direction rendered with `dirBull` / `dirBear` class; Score rendered with numeric `Data` and `StatusBadge`; Next Event rendered via `EventFlag` with days countdown.
- **Contracts Tab (`tab === 'contracts'`)**:
  - Table grid columns: `CONTRACT_COLUMNS = '28px 72px 1.3fr 120px 80px 72px 80px 80px 100px'`.
  - Exact Headers: `SYMBOL`, `CONTRACT`, `DTE`, `PRICE`, `DELTA`, `IV`, `Θ/DAY`, `SCORE`.
  - Data formatting: DTE rendered with `DTEProgressBar`; IV rendered with `IvContractCell` (percentile or absolute IV with indicator suffix); Theta rendered as `Θ/DAY` in dollars/day; Score rendered with `StatusBadge` and `contractScoreTooltip`.
- **Composite Tab (`tab === 'composite'`)**:
  - Renders active Markov regime alerts created from the Pre-Breakout scanner (`GET /api/composite-watches/`).
  - Controls: Active/Paused toggle checkbox (`PATCH /api/composite-watches/{id}`), Remove button (`DELETE /api/composite-watches/{id}`).

#### Context Rail Integration (`@contextRail/watchlist/page.tsx`)
- Dedicated right rail reading `rows` from `api.getWatchlist()` and `selectedSymbol` from `useWatchlistUiStore`:
  1. **Status breakdown**: Counts of `PASS`, `CAUTION`, `REJECT` rows with `StatusBadge` and `Data`.
  2. **Flags**: Counts of `Events ≤ 7d` and `Total` watchlist rows.
  3. **SymbolNotes**: Rendered for active `selectedSymbol` with editable capability if watched or held.
  4. **RailQuickLook**: Global summary statistics.

---

### 3.2 Alerts Subsystem

#### Architectural Separation of Stores
- **Portfolio Alert Toasts (`useAlertStore`)**:
  - Store: `frontend/lib/alertStore.ts`.
  - Storage Key: `bamendjou-alerts-v2` (version: 3).
  - Scope: Stores portfolio position alert toasts (`ToastItem[]`), `AlertConfig` (thresholds for TP, stop-loss, premium stop, time stop, earnings, event risk), and `firedAlerts`/`suppressedAlerts` sets.
  - Evaluation: Evaluated on client side via `alertEngine.ts:scanPositions()` against active open positions.
- **Chart Alert Rules & History (`useChartAlertStore`)**:
  - Store: `frontend/lib/chartAlertStore.ts`.
  - Storage Key: `bamendjou:alerts` (modern colon format).
  - Scope: Stores chart-drawn indicator alert rules (`rules: AlertRule[]`), trigger history (`history: AlertHistory[]`), and chart notification toasts (`toasts: ChartToast[]`).
  - Evaluation: Evaluated client-side via `chartAlertEngine.ts:evaluateRule()` and server-side via `chart_alert_scheduler.py` on closed candle events.

#### Condition Evaluation & Indicator Crossing Mathematics
- **Source Module:** `frontend/lib/chartAlertEngine.ts:121-170` and `backend/app/services/alert_evaluator.py`.
- **Operator Mathematics:**
  - Standard comparisons: `>`, `<`, `>=`, `<=` evaluated on current closed candle value.
  - **Crossing Above (`crosses_above`)**:
    $$\text{met} \iff V_{\text{current}} > \text{threshold} \quad \land \quad V_{\text{previous}} \le \text{threshold}$$
    Requires two consecutive valid points ($t-1$ and $t$). If $t=0$ or either point is non-finite, returns `false`.
  - **Crossing Below (`crosses_below`)**:
    $$\text{met} \iff V_{\text{current}} < \text{threshold} \quad \land \quad V_{\text{previous}} \ge \text{threshold}$$
    Requires $V_{t-1} \ge \text{threshold}$ and $V_t < \text{threshold}$.
- **Indicator Parsing & Defaults (`frontend/lib/alertIndicators.ts`)**:
  - Canonical format: `${kind}(${params.join(',')})`.
  - Supported kinds: `ema(20)`, `sma(20)`, `rsi(14)`, `atr(14)`, `macd(12,26,9)`, `macd_signal(12,26,9)`, `bb(20,2)`, `vwap`, `volume`, `close`.
  - Parameter validation: Positive finite integers $\le 10000$; for MACD, asserts fast period $<$ slow period (`params[0] < params[1]`).

#### Backend Endpoints (`backend/app/routers/chart_alerts.py`)
- `POST /alerts/rules` — Creates a chart alert rule from `AlertRuleCreate` payload.
- `GET /alerts/rules` — Lists stored alert rules for the active user.
- `GET /alerts/history` — Lists alert trigger history records.
- `DELETE /alerts/rules/{id}` — Deletes an alert rule by ID.
- `PATCH /alerts/rules/{id}` — Updates rule enabled state, cooldown, or conditions.

---

### 3.3 Strategy Watch Subsystem

#### Valid Strategies & Horizon Constraints
- **Source Module:** `backend/app/services/strategy_watch_store.py:VALID_STRATEGIES` and `strategy_watch_evaluator.py`.
- **Valid Daily Strategies (Exactly 5)**:
  1. `pullback_ema` — 50 EMA pullback in trend.
  2. `breakout_base` — Multi-week base breakout.
  3. `ma_crossover` — Fast/slow moving average crossover.
  4. `mean_reversion_rsi` — RSI oversold reversal.
  5. `mean_reversion_bb` — Bollinger lower band bounce.
- **Intraday Exclusion:** `mean_reversion_vwap` is explicitly excluded from `VALID_STRATEGIES` because daily bars have no meaningful VWAP anchor; attempting to subscribe to VWAP in daily watches is rejected with HTTP 400.

#### State Machine Lifecycle & Event Types
- **State Phases:** Exactly two persistent phases:
  - `phase: "idle"` — Waiting for setup/signal qualification.
  - `phase: "armed"` — In trade / setup live, tracking entry price, stop-loss price, and profit target price.
- **Emitted Event Types (5 Types)**:
  1. `entry`: Emitted when an idle watch detects a qualifying strategy signal $\rightarrow$ transitions phase to `armed`, recording `entry_price`, `stop_price`, and `target_price`.
  2. `exit_stop`: Emitted when an armed watch detects candle low breaching `stop_price` $\rightarrow$ transitions phase back to `idle`, clearing entry levels.
  3. `exit_target`: Emitted when an armed watch detects candle high reaching `target_price` $\rightarrow$ transitions phase back to `idle`, clearing entry levels.
  4. `time_stop`: Emitted when an armed watch reaches the horizon maximum holding duration (`hold_max_days`) without hitting stop or target $\rightarrow$ transitions phase to `idle`.
  5. `reversal`: Emitted when a contrary directional signal appears while armed $\rightarrow$ transitions phase to `idle`.

#### Backend API Routes (`backend/app/routers/strategy_watch.py`)
- `GET /api/strategy-watch/` — Lists active non-composite strategy watches.
- `POST /api/strategy-watch/` — Creates a new watch subscription.
- `POST /api/strategy-watch/bulk` — Bulk subscribes a list of symbols.
- `PATCH /api/strategy-watch/{watch_id}` — Toggles watch enabled status (`{"enabled": bool}`).
- `DELETE /api/strategy-watch/{watch_id}` — Removes a watch subscription.
- `GET /api/strategy-watch/schedule` & `PUT /api/strategy-watch/schedule` — Reads and updates polling/EOD evaluation cadence.
- `POST /api/strategy-watch/evaluate` — Triggers immediate evaluation run across all enabled watches.
- `GET /api/strategy-watch/status` — Returns scheduler status and last execution timestamp.

---

### 3.4 Auto-Trade Controls & Pre-Trade Gates

#### Client Store & Safety Reset (`frontend/lib/autoTradeStore.ts`)
- Storage Key: `bamendjou-auto-trade` (version: 2).
- State Model:
  ```typescript
  export interface AutoTradeState {
    selectedBroker: OptionsBroker | null;
    autoMode: AutoTradeMode;
    armed: boolean;
    armedDirection: Direction | null;
    armedSymbol: string | null;
    lastOrderId: string | null;
  }
  ```
- **Critical Reload Safety Guard (`partialize`)**:
  ```typescript
  partialize: (s) => ({
    selectedBroker: s.selectedBroker,
    autoMode: s.autoMode === 'armed' ? 'manual' : s.autoMode,
  })
  ```
  `armed`, `armedDirection`, `armedSymbol`, and `lastOrderId` are deliberately excluded from `localStorage` serialization. Furthermore, if `autoMode` was `'armed'`, it resets to `'manual'`. Auto-trade unconditionally disarms on page reload, preventing surprise automated executions.
- **Atomic Setter (`applyArmedStatus`)**:
  `applyArmedStatus(armed, direction, symbol)` updates all three fields in a single state mutation, eliminating half-states where a trade appears armed without an associated symbol or direction.

#### Pre-Trade Safety Gates (`backend/app/services/auto_trader.py`)
- **Regime Alignment Gate**:
  Opposing market regime raises `RegimeHeadwindError` (HTTP 400). If the underlying risk rules YAML lacks regime definitions, it raises `RegimeGateConfigError` (HTTP 500).
- **Event Proximity Veto (`_apply_event_veto`)**:
  - Calculates event proximity threshold as $\max(\text{reject\_window}, \, \text{hold\_bars})$.
  - Single stocks: If an earnings event falls within this window, raises `EventVetoError`.
  - D4 Amendment: For a single stock, an **unknown earnings date** (None, failed lookup, or past date) also raises `EventVetoError`.
  - ETFs (`app.data.etfs.is_etf`): Exempt from earnings event veto.
- **Execution Serialization & Cancellation Safety**:
  - Dedicated single-worker thread executor `_FIRE_EXECUTOR` serializes all fire requests, eliminating race conditions across rapid-fire triggers.
  - If a `/auto-trade/fire` request is aborted or cancelled before/during execution, `_log_unbooked(symbol, cf)` logs the unbooked outcome to the audit log without raising unhandled callback exceptions.

---

### 3.5 Notification Dispatch & Delivery Audit Log

#### Dispatch Layer (`backend/app/services/notifications/dispatch.py`)
- Channels: Gmail (`gmail.py`) and Telegram (`telegram.py`).
- Non-blocking error containment: `_safe_notify()` awaits delivery directly and returns boolean status, logging errors without crashing callers.
- Verification Isolation: Audit testing strictly utilized mock transports; no live email or Telegram messages were dispatched during evaluation.

#### Delivery Audit Log (`backend/app/services/notifications/sent_log.py`)
- Append-only JSONL log written to `sent_messages.log`.
- Record Schema:
  ```json
  {"ts": "2026-10-21T14:48:00Z", "channel": "telegram", "recipient": "@alerts", "subject": "Watch Alert: AAPL"}
  ```
- Retention Pruning: `prune_sent_log(retention_days)` drops entries older than the cutoff while preserving unparseable lines.
- **Separation of Concerns:** Deduplication and rate-limiting cooldowns are enforced upstream in `alert_notifier.py` and `strategy_watch_evaluator.py`, keeping `sent_log.py` as a pure, lightweight delivery ledger.

---

### 3.6 Scheduled Automation Inventory

Seven distinct background schedulers run within the backend application lifecycle:

| # | Scheduler Service | Module Path | Execution Trigger / Interval | Error Boundary Containment |
|---|---|---|---|---|
| 1 | **Scan Schedule** | `services/scan_schedule_scheduler.py` | Cron / configured scan cadence | Safely catches scan errors; logs to scan audit log |
| 2 | **Strategy Watch** | `services/strategy_watch_scheduler.py` | Configurable polling (default 60s) or market-close | Per-watch exception handling; continues across batch |
| 3 | **Chart Alerts** | `services/chart_alert_scheduler.py` | Periodic tick (`_load_check_interval_seconds`) | Per-pair try/except block; logs warning on candle fetch failure |
| 4 | **Strategy Tuning** | `services/tuning_scheduler.py` | Nightly cron | Isolated WFO param optimization runs |
| 5 | **EDGAR Prefetch** | `services/edgar_scheduler.py` | Nightly cron | Prefetches SP500, NDX100, DOW30 SEC XBRL snapshots |
| 6 | **S&P 500 Liquidity** | `services/sp500_scheduler.py` | Daily cron | Updates S&P 500 liquidity rankings via yfinance |
| 7 | **OHLCV Ingestion** | `services/ingestion_scheduler.py` | Scheduled ingestion window | Batched price history ingestion with DB rollbacks |

---

## 4. Boundary Behavior & Error States

1. **Empty Watchlist State**:
   When zero stocks or contracts are starred, the Watchlist page renders explicit guidance (`"No starred contracts yet. Star a contract on the Screener → Step 6 to track it here."`) without crashing or showing blank tables.
2. **Provider Failure / Missing Quotes**:
   When market quotes fail to load, `watchlist/page.tsx` sets `offline: true` (or `contractsOffline: true`) and surfaces an offline banner. For individual contracts missing live chain data, `MissingContractRow` renders the last known details with a `MISSING_NOTE` tag.
3. **Invalid Indicator Rule Parsing**:
   Malformed indicator strings (e.g. `macd(26,12,9)` with fast $\ge$ slow, or `ema(-5)`) return `null` in `parseAlertIndicator()`, preventing unconstructible rules from being submitted to the backend.
4. **Broker Authentication / Unconfigured Broker**:
   If an order is fired without valid broker credentials, pre-trade routing returns HTTP 400/401 with a descriptive error before any trade payload reaches external gateways.

---

## 5. Test Evidence & Verification Matrix

| Suite / Test Target | Runner | Passed | Failed | Status |
|---|---|---|---|---|
| `backend/tests/test_audit_monitoring_lane_g.py` | pytest | 13 | 0 | **PASS** |
| `frontend/app/(frame)/alerts/__tests__/auditMonitoringLaneG.test.ts` | jest | 10 | 0 | **PASS** |
| `backend/tests/test_strategy_watch_evaluator.py` | pytest | 26 | 0 | **PASS** |
| `backend/tests/test_auto_trader_event_veto.py` | pytest | 14 | 0 | **PASS** |
| `backend/tests/test_chart_alert_scheduler.py` | pytest | 3 | 0 | **PASS** |
| `frontend/lib/__tests__/watchedContractsStore.test.ts` | jest | 12 | 0 | **PASS** |
| `frontend/lib/__tests__/watchlistStore.test.ts` | jest | 6 | 0 | **PASS** |
| `frontend/lib/__tests__/chartAlertEngine.test.ts` | jest | 18 | 0 | **PASS** |
| `frontend/lib/__tests__/alertIndicators.test.ts` | jest | 9 | 0 | **PASS** |
| `frontend/` Typecheck (`npm run typecheck`) | tsc | Clean | 0 | **PASS** |

**Summary:** 111 targeted tests executed across backend and frontend monitoring suites; **100% passed**, 0 failures, 0 TypeScript diagnostic errors.

---

## 6. Catalog of Non-Gate Defects & Residuals

The audit identified 3 minor non-gate follow-up items, documented in `defects.json`:
- **`DEFECT-MONITORING-1` (Low):** `useStrategyWatchStore` client store is in-memory only without a local snapshot cache. If the backend is temporarily unreachable on page load, the table renders empty rather than displaying cached subscriptions with an offline banner.
- **`DEFECT-MONITORING-2` (Low):** Intraday chart alert rules (e.g. 5min, 15min) are evaluated by both `chart_alert_scheduler.py` and the chart WebSocket close check, relying on the rule cooldown (default 60m) as the sole duplicate prevention mechanism.
- **`DEFECT-MONITORING-3` (Info):** The Alerts and Strategy Watch routes use generic `RailQuickLook` context rail fallback shims rather than dedicated summary panels.

---

## 7. Audit Sign-Off

The monitoring, watchlist, alert, auto-trade, notification, and scheduler subsystems satisfy all requirements of issue #355 (`APP-AUDIT-MONITORING`). All arithmetic calculations, state-machine transitions, storage migrations, safety gates, and scheduler lifecycles are verified and proven clean against the project's numerical and persistence gate.
