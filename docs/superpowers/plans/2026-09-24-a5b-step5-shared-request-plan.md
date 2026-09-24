# A5b — a stock scan started from Step 5 builds its request with the shared builder

**Decision (Kenneth, 2026-09-24): `A5B-A5C-LOCKED-2026-09-24`, part (1).**
Phase `A5B-STEP5-SHARED-REQUEST`. Frontend only. Process as A5: plan +
adversarial round, build + tests + mutation checks, code round, merge when clean.

## The defect (measured on main 48555b5)

`frontend/app/(frame)/screener/step-5-strategy/page.tsx` `runScan` (:210-265)
hand-builds the `POST /api/stock-scan` body (:217-245). Compared field-for-field
with `buildStockScanRequestBody` (`frontend/lib/resolveStockScanRequest.ts:89`),
which the Step-3 Run button and the Step-4 Run button both reach through
`runStockScan` (`frontend/lib/stockScan.ts:264`), the Step-5 body **omits**:

| Field(s) | Effect of the omission on a Step-5 scan |
|---|---|
| `confidence_caution_below`, `confidence_reject_below` | **No confidence gate at all** — the backend schema defaults are `None`, so no card is capped/rejected on backtest confidence. The headline bug. |
| `confidence_atr_mult_target`, `confidence_atr_mult_stop` | Confidence barrier falls back to backend defaults instead of the horizon's pair (`atrMultForHorizon`) or the Step-3 full-pair override. |
| `overrides` (Step-3 score weights / indicator params, `STOCKS_SCORER_KEYS`) | Scores computed on YAML defaults, not the user's Step-3 settings. |
| `regime_headwind_caution_pct`, `regime_headwind_reject_pct` | Step-3 headwind thresholds ignored. |
| `fundamentals_caution_above`, `fundamentals_reject_above` | Step-3 fundamentals thresholds ignored. |
| `require_choppy_regime` | Step 5's own panel edits it (`params.requireChoppyRegime`, :114) but it is **never sent** — backend default `false`. |

Fields it sends that the builder also sends, identically sourced: universe,
direction, horizon, strategy, the 11 strategy params, `pullback_require_reversal`,
`bt_min_trades`, `bt_min_win_rate`, `shortlist_max_candidates`, `risk_pct`
(0.01 both), and — for `mean_reversion_multi` only — the four variant fields
(Step 5 reads them live from `useScanParamsStore`; the builder reads
`params.meanReversionVariants` etc. from the same store via the `{...saved, ...overrides}`
merge, so they are the same values).

Fields that **differ in source**: `account_size`. Step 5 sends
`useRiskStore.limits.portfolioValue` (default 100 000); `runStockScan` hardcodes
`50_000` (flagged in its own comment, stockScan.ts:~297, as a pre-existing gap
outside that plan's scope). `account_size` sizes `shares` on every card
(`stock_scan.py` `_position_size`, ~:1022), which StockSendDialog sends to the broker.

## Changes

### F1 — extract the store-reading half of `runStockScan` into one exported helper

In `frontend/lib/stockScan.ts`:

```ts
/** The body a manual stock scan posts: universe/direction/horizon from
 *  scanStore.context, params = saved scanParamsStore merged with the caller's
 *  per-run edits, Step-3 scanOverrides, settingsStore.confidenceGate.
 *  Shared by runStockScan (Step-3 / Step-4 Run) and Step 5's runScan so the two
 *  cannot drift again (A5b). Reads stores; may throw on a malformed persisted
 *  store — callers call it inside their try. */
export function manualStockScanRequest(
  strategy: string,
  overrides: StockScanParamOverrides = {},
  opts: { accountSize?: number } = {},
): StockScanRequestBody
```

Body = exactly the current `runStockScan` lines that compute `saved`, `p`,
`context`, `requireReversal`, `confidenceGate`, `rawOverrides` and call
`buildStockScanRequestBody`, with `accountSize: opts.accountSize ?? 50_000`,
`riskPct: 0.01`. The existing `account_size` comment moves with it.

`runStockScan` replaces those lines with
`const requestBody = manualStockScanRequest(strategy, overrides);` — **inside the
same `try`, at the same point** (after the four store writes, before
`reachedRequest = true`), so its throw/`reachedRequest` semantics are unchanged.

### F2 — Step 5 posts `manualStockScanRequest(...)`; the hand-built body is deleted

In `step-5-strategy/page.tsx` `runScan`, replace the literal (:216-245) with:

```ts
// A5b: the same builder the Step-3/4 Run buttons use (Step-3 overrides,
// confidence gate, headwind, fundamentals, ATR pair, require_choppy_regime).
// Step 5's local panel edits ride in as per-run overrides, exactly as Step 4's
// do; account_size keeps Step 5's existing source (see Q1).
const requestBody = manualStockScanRequest(stratKey, params, { accountSize: portfolioValue });
```

It stays inside the existing `try`, so a builder throw lands in `setError`
exactly like a post failure does today. `setStockScanResult(result, requestBody)`
is unchanged — the A5 snapshot follows automatically. Nothing else in `runScan`
changes (no `scanState` writes, no switch to `runStockScan`: Step 5 keeps its own
loading/error/navigation flow — changing that is not in the decision).

The mean-reversion variant fields no longer need a Step-5 overlay: the builder
emits them for `mean_reversion_multi` from `useScanParamsStore`, which is the
store `MeanReversionConfirmPanel` writes on every change (:311-316). Step 5's
local `params` does not carry them, so the merge cannot shadow them.

`params` contains `eventFilter`, which `StockScanParamOverrides` does not list.
It passes type-check (non-literal argument, no excess-property check) and the
builder never reads it; the merged value equals the saved one regardless.

Imports: add `manualStockScanRequest` from `@/lib/stockScan`. `useRiskStore`
stays (portfolioValue). No now-unused imports expected; typecheck confirms.

### Not changed (non-goals)

- `analysisStore.analysisRequestFor`'s no-snapshot fallback builds the same body
  a third time (analysisStore.ts:~43). It already goes through
  `buildStockScanRequestBody` and is pinned by the A5 suite; folding it into
  `manualStockScanRequest` is a pure dedupe, not part of the locked fix.
- The `$50k` hardcode in `runStockScan` (Q1).
- Backend: no change. `StockScanRequest` already accepts every field.

## Q1 — `account_size` (needs Kenneth's call; plan default is (a))

The locked pin says "a Step-5 body equals the Step-3/4 body apart from the
strategy fields". Taken literally, Step 5 would start sending `50_000` instead of
the user's portfolio value, halving `shares` on Step-5 cards for a user at the
100 000 default. That is a sizing change a request-builder fix should not make
silently.

- **(a) default in this plan** — Step 5 keeps `portfolioValue`; the pin is
  "equal apart from strategy and `account_size`", and T1 asserts `account_size`
  is `portfolioValue` explicitly.
- (b) literal — Step 5 sends 50 000 like Steps 3/4.
- (c) fix the other side — `runStockScan` reads `portfolioValue` too (and
  `maxLossPerTradePct` for `risk_pct`?). Changes Step-3/4 sizing; its own decision.

## Tests — new suite `frontend/lib/__tests__/a5bStep5SharedRequest.test.tsx`

Setup mirrors `a5AnalysisMirrorsScan.test.tsx` (mocked `api`, `next/navigation`).
Stores seeded with **non-default** values for every field the old body dropped:
`scanOverrides = { weight_trend: 0.4, fast_ema: 12, regime_headwind_caution_pct: -3,
regime_headwind_reject_pct: -9, fundamentals_caution_above: 55,
fundamentals_reject_above: 75, confidence_atr_mult_target: 2.5,
confidence_atr_mult_stop: 1.25, pullback_require_reversal: true }`,
`confidenceGate.enabled = true` with caution/reject 60/40,
`scanParamsStore.requireChoppyRegime = true`, `riskStore.limits.portfolioValue = 123_456`,
context = `{ universe: 'NDX100', direction: 'Bearish', horizon: 'Position (…)' }`.

- **T1 — the pin.** Click a Step-5 strategy card (`ma_crossover`); capture the
  posted body. Reset the post mock; `await runStockScan('ma_crossover')` with the
  same stores; capture. Assert
  `{...step5, account_size: X} toEqual {...step4, account_size: X}` and
  `step5.account_size === 123_456`. (Both bodies must be from the same stores —
  `runStockScan` is called with no per-run overrides, and Step 5's local params
  are the hydrated saved values.)
- **T2 — the headline field-by-field.** The Step-5 body has
  `confidence_caution_below: 60`, `confidence_reject_below: 40`,
  `confidence_atr_mult_target: 2.5`, `confidence_atr_mult_stop: 1.25`,
  `overrides.weight_trend: 0.4`, `regime_headwind_caution_pct: -3`,
  `fundamentals_reject_above: 75`, `require_choppy_regime: true`. (Readable
  failure when T1's diff is large.)
- **T3 — gate disabled.** `confidenceGate.enabled = false` → both confidence
  thresholds absent (undefined) in the Step-5 body, same as the builder.
- **T4 — Step 5's local edits still win.** Change a value in
  `StrategyParamsPanel` (e.g. MA-crossover fast) before clicking; body carries
  the edited value, and equals `runStockScan('ma_crossover', {maCrossoverFast: edited})`
  modulo `account_size`.
- **T5 — mean_reversion_multi.** Variants/minConfirm/vwap fields set via the
  store → the Step-5 multi body carries them; a non-multi body carries none.
- **T6 — throw path.** Make the builder throw (e.g. `settingsStore.confidenceGate`
  set to `null` via `setState`) → Step 5 shows the error text, `postStockScan`
  not called, loading cleared (button re-enabled).
- Existing: `a5AnalysisMirrorsScan` "Step 5 writer" (stored request equals the
  posted body) and `lib/__tests__/stockScan.test.ts` must pass unchanged.

### Mutation checks (each must turn at least one new test red)

1. Restore the hand-built literal in Step 5 → T1, T2 red.
2. In `manualStockScanRequest`, drop the `overrides` arg from the merge → T4 red.
3. Step 5 passes no `accountSize` → T1's `account_size` assertion red.
4. Remove the `mean_reversion_multi` spread from `buildStockScanRequestBody` → T5 red.

## State file

- Phase `A5B-STEP5-SHARED-REQUEST`: status `in_progress` while built; on a clean
  code round, `verify` changes from the defect marker to a presence probe,
  `pattern: "manualStockScanRequest\\(stratKey"` in the Step-5 page (the defect
  marker `pullback_tolerance_pct:\s+params\.pullbackTolerancePct` stops matching
  once the literal is deleted — that is the flip).
- Record Q1's answer as a decision.

## Verification

- `cd frontend && npx jest && npm run typecheck` — full suite, typecheck clean.
- Backend untouched; `python3 scripts/state.py` exit 0.
