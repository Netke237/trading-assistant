# A5 — the Analysis page mirrors the stock scan (Step-3 overrides included)

**Decision (Kenneth, 2026-09-24): "the analysis should mirror the scan."**
Answers the open question logged by 2C round 1: Analysis is a *mirror of the
scan*, not a defaults view. Decision id: `A5-ANALYSIS-MIRRORS-SCAN-2026-09-24`.

## The defect (measured on main 22c4942)

- `frontend/lib/analysisStore.ts` `analyze()` — the sole caller of
  `POST /api/analyze-stock` — hand-builds a request with direction / horizon /
  strategy and 11 strategy params. It sends **none** of: the Step-3 score
  `overrides` dict, `regime_headwind_caution_pct` / `_reject_pct`,
  `fundamentals_caution_above` / `_reject_above`, `confidence_caution_below` /
  `_reject_below`, the ATR barrier pair, `bt_min_trades` / `bt_min_win_rate`,
  `pullback_require_reversal`, `require_choppy_regime`, mean-reversion-multi params.
  The stock scan sends all of them via `buildStockScanRequestBody`
  (`frontend/lib/resolveStockScanRequest.ts`).
- `backend/app/routers/stock_scan.py` `_analyze_core` (:438) reads the
  `regime_gate` YAML block raw — even a request that did carry the two headwind
  keys would be ignored. The scan resolves them through
  `services/regime_gate.resolve_regime_gate` (:812).
- `_analyze_core` applies `confidence_reject_below` (as a flag) but not
  `confidence_caution_below`; the scan caps the card at CAUTION on it (:980).
- **Found while reading, same mechanism:** `_backtest_key` (:316) hashes
  symbol/strategy/direction/bars/params/commission but **not** `min_trades` /
  `min_win_rate`, while the cached `BacktestResult.passes_gate` is decided on
  them, TTL 24h. The Analysis page and the scan share `_BACKTEST_CACHE`. Today
  Analysis always runs at the schema defaults (5 / 0.45); a scan at the user's
  Step-3 thresholds within 24h of an Analysis of the same symbol is served the
  defaults' `passes_gate` — the scan drops or keeps a symbol on thresholds the
  user did not set. Same after a Step-3 threshold edit between two scans.
  Mirroring the request narrows but does not close this, so it is fixed here.

Consequence (the gate): with "Headwind reject %" at -10 the scan REJECTs a
symbol while Analysis shows a PASS regime rule; any score-weight override moves
the scan's score and not Analysis's; a stale `passes_gate` changes which names
the scan returns.

## Changes

### F1 — frontend: Analysis replays the LAST STOCK SCAN'S OWN REQUEST
**Revised after plan round 1 (F-1: the Step-4 Run button scans with unsaved
local param edits — `step-4-stocks/page.tsx:130,195` → `runStockScan(selected,
params)` merges them over the saved store — so building from the live stores
still disagrees with the scan). Kenneth, 2026-09-24, asked: mirror *the last
scan run*, not current settings (decision `A5-MIRROR-LAST-SCAN-RUN-2026-09-24`).**

- `scanStore` gains `stockScanRequest: StockScanRequestBody | null`, written
  **only inside `setStockScanResult`, in the same `set()` as the result**:
  `setStockScanResult(r, request?)` → `stockScanRequest = r ? (request ?? null) : null`.
  So the snapshot can never pair with a different result: any writer that does
  not pass a request (StoreHydration's backend recovery `StoreHydration:67`)
  stores null, and clearing the result clears it. The context-change reset
  (`scanStore.ts:~411`, which nulls `stockScanResult`) nulls it too.
  Persisted with the result (in `partialize`), version 16 → 17, migration adds
  `stockScanRequest: null`.
- Writers that pass it: `runStockScan` (`lib/stockScan.ts:322`, the
  `requestBody` it posted — both the Step-3 Run button and the Step-4 Run
  button go through here, the Step-4 local edits included) and Step 5's
  `runScan` (`step-5-strategy/page.tsx:245`, the body literal it posted, hoisted
  into a const).
- `analysisStore.analyze()`: if `stockScanRequest` is non-null, send
  `{...snapshot without universe, symbol, horizon: _horizonEnum(snapshot.horizon)}`
  — direction, strategy, every param, overrides, regime/fundamentals/confidence
  keys, ATR pair, bt thresholds exactly as the scan sent them. If null (no
  stock scan this context, or a recovered result with no known request): build
  from the live stores with `buildStockScanRequestBody` exactly as
  `runStockScan(activeStrategy)` would (params = `useScanParamsStore`,
  requireReversal = `scanOverrides.pullback_require_reversal ?? false`,
  scanOverrides, `settingsStore.confidenceGate`, 50_000 / 0.01, strategy =
  `activeStrategy ?? 'pullback_ema'`, direction from context).
- **Recovered results (plan round 2, F2-1).** StoreHydration recovers
  `stockScanResult` from `GET /api/stock-scan/last` with no request, so the
  snapshot would be null and Analysis would replay *current* settings against a
  result they did not produce (reload mid-scan, second device, cleared storage,
  and every persisted result right after the v17 migration). Fix:
  - B4 — new `GET /api/stock-scan/last-request` → `{scan_id, request}` or null.
    `request` = `_last_stock_request.model_dump(mode="json", exclude_none=True)`,
    `scan_id` = `_last_stock_result.scan_id`. **Served only when
    `_last_stock_status == "complete"`**, because that is the only state in which
    the two globals are from the same run: the "running" write
    (`run_stock_scan` → `_upsert_stock_session(req=req, result=_prev_result,
    status="running")`) pairs the NEW request with the OLD result, and
    `restore_stock_from_db` turns a persisted "running" row into "idle" with
    the same mismatch. The failure revert restores the previous pair and status.
    Scheduled runs never write these globals.
  - StoreHydration: after its result block, when `stockScanResult` is non-null
    and `stockScanRequest` is null, fetch it; attach **only if**
    `resp.scan_id === stockScanResult.scan_id` at write time (re-read the store
    then, so a scan that finished meanwhile is not overwritten). Else leave null.
  - Analysis records its basis: `basis: 'last-scan' | 'current-settings'`. The
    page shows one caption under the search row: "Settings: the last stock scan"
    or "Settings: current Step-3 settings — no stock scan request on record,
    re-run the scan to mirror it". So the one remaining fallback is labelled,
    never silently presented as the scan's mirror.
- `AnalyzeStockRequest` in `lib/api.ts` becomes
  `Omit<StockScanRequestBody,'universe'|'horizon'> & {symbol; horizon: enum}`.

Not refactoring `runStockScan`/Step 5 to share one builder: out of scope.
Step 5's hand-built body ignores the Step-3 overrides itself — a scan-side gap,
logged for Kenneth, not fixed here; Analysis mirrors whatever that scan sent.

### B1 — backend: `_analyze_core` resolves the regime gate like the scan
`_regime_gate = _resolve_regime_gate(full_cfg.get("regime_gate"),
req.regime_headwind_caution_pct, req.regime_headwind_reject_pct)` — the same
call as `_process_stock`. It feeds both `score_stock(regime_gate=…)` and the
`regime_headwind` CAUTION flag threshold, as today.

### B2 — backend: the confidence CAUTION cap
After confidence is computed, mirror `_process_stock`: if
`confidence_caution_below` is set and `conf_val` is below it, cap `card.status`
at CAUTION (never lowers a REJECT) and append a `confidence` CAUTION gate flag.
The existing `confidence_reject_below` flag is unchanged.

### B3 — backend: gate thresholds in the backtest cache key
`_backtest_key(..., min_trades, min_win_rate)` folded into the key at both
call sites (scan `_process_stock`, `_analyze_core`), passing the exact values
handed to `run_strategy_backtest`. No other caller (grep-verified at build).

## Scoped out (logged, not built)
- Scan-only *filters* that are not Step-3 overrides and that Analysis does not
  model as flags today: the direction-conviction floor, `regime_filter`,
  `require_choppy_regime`, `mean_reversion_multi` (Analysis has no multi
  signal path). Analysis stays gate-free by design (it shows why, it does not
  drop). Logged for Kenneth as whether Analysis should flag those too.
- Existing flag severities (e.g. backtest fail → CAUTION flag while the scan
  drops the symbol) unchanged.

## Tests
- T-F1 parity: `runStockScan(strategy, nonDefaultLocalParams)` with non-default
  Step-3 overrides, regime keys, confidence gate on, reversal true; then change
  the live stores; `analyze` body == scan body minus universe, plus symbol.
- T-F2 no snapshot → live-store body == what `runStockScan(activeStrategy)`
  would send; StoreHydration-style `setStockScanResult(r)` stores null;
  `setStockScanResult(null)` and the context reset clear it; failed scan leaves
  null. Step 5 success stores its body.
- T-F3 migration v16 → v17 adds `stockScanRequest: null`.
- T-F4 StoreHydration attaches the recovered request only on scan_id match
  (match, mismatch, null response, fetch failure, a local result + request
  already present → no fetch).
- T-F5 analyze sets basis; caption renders for each.
- T-B4 `/stock-scan/last-request`: complete → pair; running (new req + old
  result) → null; idle / no result → null; request dump replayed through
  `StockAnalysisRequest` validates.
- T-B1 `_analyze_core` with `regime_headwind_reject_pct` set tighter than YAML:
  card regime rule REJECT and headwind flag appears at the overridden caution
  threshold; without the keys, YAML behaviour unchanged.
- T-B2 caution cap (PASS → CAUTION + flag; REJECT stays REJECT; unset → no-op).
- T-B3 `_backtest_key` differs on min_trades and on min_win_rate; a scan after
  an analysis at different thresholds recomputes (not served the cached result).
- Mutation checks: revert each of B1/B2/B3/F1 in turn; the matching test fails.
- Full backend + frontend suites; `npm run typecheck`.
