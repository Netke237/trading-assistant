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

### F1 — frontend: Analysis builds its request with the scan's builder
`analysisStore.analyze()` calls `buildStockScanRequestBody` with exactly the
inputs `runStockScan` passes (`lib/stockScan.ts:~300`): `params` =
`useScanParamsStore.getState()`, `requireReversal` =
`scanOverrides.pullback_require_reversal ?? false`, `scanOverrides` =
`scanStore.scanOverrides`, `confidenceGate` = `settingsStore.confidenceGate`,
`accountSize` 50_000, `riskPct` 0.01 (unused by analysis; passed for parity),
`strategy` = `activeStrategy ?? 'pullback_ema'` (unchanged), direction
unchanged. Then drops `universe`, adds `symbol`, and keeps `horizon` =
`_horizonEnum(ctx.horizon)` (the backend enum; equals the scan's
`split(' ')[0]` for every real label and is safe for a malformed one).
`AnalyzeStockRequest` in `lib/api.ts` becomes
`Omit<StockScanRequestBody,'universe'|'horizon'> & {symbol; horizon: enum}` so
the type cannot drift from the scan body again.

Not refactoring `runStockScan` to share a context helper: it is the hot,
heavily-commented scan path and out of scope. Parity is pinned by a test
instead (T-F1) that runs `runStockScan` and `analyze` on the same store state
and asserts the two bodies are equal except `universe`/`symbol`/`horizon`.

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
- T-F1 parity (runStockScan body vs analyze body, non-default Step-3 overrides,
  regime keys, confidence gate enabled, reversal true).
- T-F2 analyze sends `overrides`, both regime keys, confidence thresholds.
- T-B1 `_analyze_core` with `regime_headwind_reject_pct` set tighter than YAML:
  card regime rule REJECT and headwind flag appears at the overridden caution
  threshold; without the keys, YAML behaviour unchanged.
- T-B2 caution cap (PASS → CAUTION + flag; REJECT stays REJECT; unset → no-op).
- T-B3 `_backtest_key` differs on min_trades and on min_win_rate; a scan after
  an analysis at different thresholds recomputes (not served the cached result).
- Mutation checks: revert each of B1/B2/B3/F1 in turn; the matching test fails.
- Full backend + frontend suites; `npm run typecheck`.
