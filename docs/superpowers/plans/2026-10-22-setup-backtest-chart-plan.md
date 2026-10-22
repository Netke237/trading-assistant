# Implementation Plan: SETUP-BACKTEST-CHART (#391)

## 1. Context & Goal

In the Screener's Pre-Breakout mode (`/screener/step-4-prebreakout`), users scan for three types of setups:
1. **Pre-Breakout** (consolidation coils via `breakout_setup_signal`)
2. **Fib Pullback** (Fibonacci retracements via `fibonacci_pullback_detail`)
3. **Pullback to EMA** (EMA trend pullbacks via `runStockScan({category: 'pullback', strategy: 'pullback_ema'})`)

Currently, clicking the external chart icon (↗) on a candidate row:
- On **Pullback to EMA**, passes the `pullback_ema` backtest artifact and displays historical candlestick markers and equity curves.
- On **Pre-Breakout** and **Fib Pullback**, is blocked by hard-coded `unsupported` guards in `frontend/lib/candidateChart.ts` and `frontend/lib/useOriginalBacktest.ts`, displaying a raw `"Original backtest unavailable: unsupported"` message.

However, the underlying setup backtest engine for `breakout_setup` and `fibonacci_pullback` is **already built** (STOCKS-HORIZON-T4, #118 / PR #325), and the chart workspace is **already built** (CANDIDATE-BACKTEST-CHART, #288 / PR #333).

**Goal:**
When Kenneth clicks ↗ on a **Pre-Breakout** or **Fib Pullback** candidate:
1. The Chart page opens and displays that row's original backtest curve (candlesticks with entry/exit markers, plus an equity panel with the strategy curve and buy-and-hold benchmark, both starting at 100).
2. It looks and works exactly like Stocks candidates today.
3. If an artifact is unavailable, the Chart page displays the reason in plain language.
4. All existing scanner candidate scores, confidence values, gates, and row rankings remain 100% byte-identical.

---

## 2. The Three Missing Links & Technical Architecture

### Link 1: Engine Chart Evidence Handover
In `backend/app/services/strategy_backtest.py`:
- `_run_backtest` (lines 229–236) delegates `strategy in ("breakout_setup", "fibonacci_pullback")` to `app.services.setup_backtest.run_setup_backtest`.
- However, it returns before inspecting or filling `detail_collector: list[DetailedBacktestResult] | None`.
- **Solution:**
  - Create `collect_setup_details` in `backend/app/services/strategy_backtest_details.py`.
  - When `detail_collector is not None`, call `collect_setup_details(result, records, bars=bars, strategy=strategy, direction=direction, params=params, commission=commission, entry_start=entry_start, entry_end=entry_end, hold_max_days=hold_max_days, min_trades=min_trades, min_win_rate=min_win_rate)` and append the resulting `DetailedBacktestResult` to `detail_collector`.
  - If detail collection fails, catch the exception and append `DetailedBacktestResult(result, "invalid_evidence", str(exc))` so that evidence collection never raises or alters the `BacktestResult`.
  - In `backend/app/services/strategy_backtest.py`, add `size: int = 1` default to `TradeRecord`. In `backend/app/services/horizon_tuning/simulate.py`, record `size=size` into `TradeRecord` so individual trade execution size is preserved in the detailed trade inspector.

### Link 2: Per-Row Execution in Pre-Breakout & Fib Pullback Scans
In `backend/app/routers/stock_scan.py`:
- In `_prebreakout_scan_core` and `_fib_pullback_scan_core`:
  - When a symbol produces a valid setup (`signal is not None` in prebreakout, or `level_hit is not None` and passes EMA filter in fib-pullback):
  - Execute `_run_backtest_with_details` using `_BACKTEST_POOL` (or asyncio thread executor) with:
    - Prebreakout: `strategy="breakout_setup"`, `params=base_params`, `direction=body.direction`, `hold_max_days=hold_for_backtest("Swing", "breakout_setup", None)` (15 days), `commission=_backtest_commission()`.
    - Fib Pullback: `strategy="fibonacci_pullback"`, `params=scan_params`, `direction=body.direction`, `hold_max_days=hold_for_backtest("Swing", "fibonacci_pullback", None)` (15 days), `commission=_backtest_commission()`.
  - Call `_original_artifact` with `_detail`, `scan_id=scan_id`, `symbol=sym`, `strategy=_bt_strategy`, `direction=body.direction`, `horizon="Swing"`, `interval="1d"`, `detail_key=_detail_identity`.
  - Unpack `**_artifact` into the returned candidate dictionary, adding `backtest_artifact_id` (when available) and `backtest_artifact_status`.
  - If backtest execution or artifact persistence fails or raises, catch it defensively and set `backtest_artifact_status="storage_unavailable"` or `"failed"`; **never drop the candidate row or alter its confidence or metrics**.

### Link 3: Candidate Chart Routing & Plain-Language UI
1. **Frontend Chart Route Parameters (`frontend/lib/candidateChart.ts`):**
   - In `buildCandidateChartHref`: Remove `const setup = source === 'prebreakout' || source === 'fib'; const status = setup ? 'unsupported' : ...`. Allow `prebreakout` and `fib` rows with `backtest_artifact_status === 'available'` to pass `backtest_artifact_id` and `backtest_artifact_status` to `/chart`.
   - In `parseCandidateChartContext`: Remove `if (source === 'prebreakout' || source === 'fib') return {source, symbol, artifactId: null, status: 'unsupported'};`.
2. **Frontend Artifact Hook (`frontend/lib/useOriginalBacktest.ts`):**
   - Remove `if (context.source === 'prebreakout' || context.source === 'fib') return {status: 'unavailable', reason: 'unsupported'};`.
3. **Plain-Language Unavailable Explanations (`frontend/components/organisms/CandidateChartWorkspace/index.tsx`):**
   - Add a mapping helper `formatUnavailableReason(reason: OriginalBacktestUnavailableReason): string` that formats raw enum reasons into readable prose:
     - `'unsupported'` → `'unsupported (this setup type does not provide a backtest curve)'`
     - `'insufficient_history'` → `'insufficient history (not enough price bars to run the backtest)'`
     - `'storage_unavailable'` → `'storage unavailable (database error saving backtest artifact)'`
     - `'capture_unavailable'` → `'capture unavailable (backtest details were not captured during scan)'`
     - `'original_unavailable'` → `'original unavailable (no original backtest artifact was recorded)'`
     - `'invalid_evidence'` → `'invalid evidence (backtest output could not be reconciled)'`
     - `'invalid_input'` → `'invalid input (malformed candidate parameters)'`
     - `'failed'` → `'failed (engine error during backtest execution)'`
     - `'missing'` → `'missing (artifact record was not found)'`
     - `'expired'` → `'expired (backtest artifact has expired)'`
     - `'context_mismatch'` → `'context mismatch (symbol does not match candidate context)'`
   - Render: `Original backtest unavailable: ${formatUnavailableReason(state.reason)}. Live chart below; no historical result has been substituted.` This maintains exact backward compatibility with existing tests checking `Original backtest unavailable: ${reason}` while providing human-readable explanations.
4. **Types (`frontend/types/stockDomain.ts`):**
   - Update `PreBreakoutResultRow` and `FibPullbackResultRow` to include `backtest_artifact_id?: string | null;` and `backtest_artifact_status?: BacktestArtifactStatus | null;`.

---

## 3. Mathematical, Numeric, and Persistence Invariants

1. **Backtest Summary Invariance:**
   - `run_strategy_backtest(strategy="breakout_setup" | "fibonacci_pullback")` MUST produce the exact same `BacktestResult` values (`n_trades`, `win_rate`, `total_return_pct`, `max_drawdown_pct`, `expectancy`, `sharpe`, `passes_gate`, `summary_text`, `n_time_exits`) whether `detail_collector` is `None` or provided.
   - Pinned tests verify equality down to 1e-9 tolerance.
2. **Reconciliation Invariant:**
   - In `collect_setup_details`:
     - The first equity value (or 100,000 baseline) serves as `baseline`.
     - `((float(eq.iloc[-1]) / baseline - 1.0) * 100.0)` must match `summary.total_return_pct` within `1e-9`.
     - `EquitySample` values must be finite and normalized: `strategy_index = 100 * equity / baseline`, `benchmark_index = 100 * close / benchmark_baseline`.
3. **Scan Candidate Invariance:**
   - Candidate discovery, confidence scores, swing levels, metrics, and ranking order in `/scan/prebreakout` and `/scan/fib-pullback` MUST be identical to baseline.
   - Adding backtest execution and artifact persistence MUST NOT drop any candidate or alter its metrics.
4. **Zero-Trades Handling:**
   - If a candidate setup backtest yields 0 trades (e.g. coil never broke out or entry conditions not triggered in history):
   - The result is NOT an error or unavailable status; it is a successful backtest (`status: "success"`) with `trades: ()` and a flat equity curve at 100.
   - `CandidateBacktestWorkspace` displays: *"Successful result: zero closed trades. The recorded equity and benchmark remain visible."*
5. **Artifact Isolation & Expiration:**
   - Schema version 1, `provenance: "original"`.
   - Stored in `BacktestArtifact` with 30-day retention (`RETENTION_SECONDS = 30 * 86400`).
   - Querying `GET /api/backtest-artifacts/{id}?symbol={sym}` strictly validates that `symbol` matches the artifact's `identity.symbol`.

---

## 4. Implementation Details by File

### 4.1 Backend
- **`backend/app/services/strategy_backtest.py`:**
  - In `TradeRecord`, add `size: int = 1`.
  - In `_run_backtest`, when `strategy in ("breakout_setup", "fibonacci_pullback")`:
    - After `run_setup_backtest`, if `detail_collector is not None`: call `collect_setup_details(...)` and append to `detail_collector`.
- **`backend/app/services/horizon_tuning/simulate.py`:**
  - In `simulate_trades`, pass `size=size` into `TradeRecord` construction at line 138.
- **`backend/app/services/strategy_backtest_details.py`:**
  - Implement `collect_setup_details(summary, records, *, bars, strategy, direction, params, commission, entry_start, entry_end, hold_max_days, min_trades, min_win_rate)`.
  - Build `input_candles`, `candles`, `equity` (`EquitySample`), `trades` (`DetailedTrade`), `open_positions` (`()`), `initial_equity`, `configuration`, and `effective_params` from `setup_params(strategy, params)`.
  - If `records` lacks equity or bars < 100: construct `DetailedBacktestResult` with status `"insufficient_history"` or `"failed"`.
- **`backend/app/routers/stock_scan.py`:**
  - Update `PreBreakoutResult` model to include `backtest_artifact_id: str | None = None` and `backtest_artifact_status: str | None = None`.
  - In `_prebreakout_scan_core`:
    - Compute `scan_id = new_rec_id()`.
    - For each candidate found: execute backtest in `_BACKTEST_POOL`, call `_original_artifact`, and include `**_artifact` in candidate dict.
  - In `_fib_pullback_scan_core`:
    - Compute `scan_id = new_rec_id()`.
    - For each candidate found: execute backtest in `_BACKTEST_POOL`, call `_original_artifact`, and include `**_artifact` in candidate dict.

### 4.2 Frontend
- **`frontend/types/stockDomain.ts`:**
  - Add `backtest_artifact_id?: string | null;` and `backtest_artifact_status?: BacktestArtifactStatus | null;` to `PreBreakoutResultRow` and `FibPullbackResultRow`.
- **`frontend/lib/candidateChart.ts`:**
  - Update `buildCandidateChartHref` to pass `backtest_artifact_id` and `backtest_artifact_status` unconditionally when available.
  - In `parseCandidateChartContext`, remove the guard that hard-coded `prebreakout` and `fib` to `unsupported`.
- **`frontend/lib/useOriginalBacktest.ts`:**
  - Remove `if (context.source === 'prebreakout' || context.source === 'fib') return {status: 'unavailable', reason: 'unsupported'};`.
- **`frontend/components/organisms/CandidateChartWorkspace/index.tsx`:**
  - Add `formatUnavailableReason` helper and update status text to explain unavailable reasons in plain words while preserving the token substring for test compatibility.

---

## 5. Verification Strategy

### 5.1 Backend Tests (`backend/tests/test_setup_backtest_chart.py`)
1. **Engine Pinned Invariance:**
   - Verify `run_strategy_backtest` returns identical `BacktestResult` numbers with and without `detail_collector` for both `breakout_setup` and `fibonacci_pullback`.
2. **Detail Evidence Structure:**
   - Verify `collect_setup_details` generates valid `DetailedBacktestResult` with:
     - `status == "success"`, valid `input_candles`, `candles`, `equity` matching `summary.total_return_pct`.
     - `trades` with entry/exit times, prices, and `exit_reason`.
     - Zero-trades case: produces valid `DetailedBacktestResult` with `trades: ()` and `equity` matching 100 baseline.
     - Insufficient bars (<100): produces `status == "insufficient_history"`.
3. **Scan Endpoint Integration:**
   - Execute `/scan/prebreakout` on fixture bars: candidates return with `backtest_artifact_id` and `backtest_artifact_status == "available"`.
   - Execute `/scan/fib-pullback` on fixture bars: candidates return with `backtest_artifact_id` and `backtest_artifact_status == "available"`.
   - Verify candidate confidence scores and ordering match baseline.
   - Fetch artifact via `GET /api/backtest-artifacts/{id}?symbol={sym}` and verify payload, schema version 1, and detail contents.

### 5.2 Frontend Tests
1. **`frontend/lib/__tests__/candidateChart.test.ts`:**
   - Test `buildCandidateChartHref` and `parseCandidateChartContext` for `prebreakout` and `fib` with `available` artifacts.
2. **`frontend/lib/__tests__/useOriginalBacktest.test.ts`:**
   - Test `useOriginalBacktest` transitions from `loading` to `ready` for `prebreakout` and `fib` sources when artifact is returned.
3. **`frontend/components/organisms/CandidateChartWorkspace/__tests__/CandidateChartWorkspace.test.tsx`:**
   - Verify plain-language unavailable reasons render in the status role.
4. **`frontend/app/(frame)/screener/step-4-prebreakout/__tests__/auditPrebreakoutLaneE.test.ts`:**
   - Update tests to reflect that `prebreakout` and `fib` now support candidate backtest artifacts when available.

### 5.3 Playwright E2E Test (`frontend/tests/setup-backtest-chart.spec.ts`)
1. Navigate to `/screener/step-4-prebreakout`.
2. Run Pre-Breakout scan, click ↗ on candidate row -> opens `/chart` with candidate context.
3. Verify Chart page displays candlestick series with historical markers, equity curve panel with strategy and benchmark curves, and trade inspector.
4. Repeat for Fib Pullback and Pullback to EMA.

---

## 6. Audit & Release Gates
- `PROJECT_STATE.json` tracks phase `SETUP-BACKTEST-CHART`.
- Mandatory independent subagent adversarial plan audit (cap 3).
- Implementation and test suite green (`pytest`, `npm run typecheck`, Jest, Playwright).
- Mandatory independent subagent adversarial code audit (cap 3).
- Pull request opened, exact-head CI green on all workflows (`backend`, `frontend`, `test`).
- Self-merge under `docs/agents/board.md` step 7, close issue #391, update board issue #151, Telegram notify, release claim.
