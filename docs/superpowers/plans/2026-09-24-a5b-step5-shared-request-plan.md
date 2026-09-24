# A5b — a stock scan started from Step 5 builds its request with the shared builder

**Decision (Kenneth, 2026-09-24): `A5B-A5C-LOCKED-2026-09-24`, part (1).**
Phase `A5B-STEP5-SHARED-REQUEST`. Frontend only. Process as A5: plan +
adversarial round, build + tests + mutation checks, code round, merge when clean.

**Plan round 1 (2026-09-24): NOT CLEAN — 2 blocking, 11 non-blocking. All folded
in below, tagged `[R1-n]`.** Precondition for the build: Kenneth answers Q1 [R1-2].

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
| `require_choppy_regime` | Step 5's own panel edits it (`params.requireChoppyRegime`, :114) but it is **never sent** — backend default `false`. **User-visible after the fix [R1-4]:** `stock_scan.py:170,172` pass it to `mean_reversion_rsi` / `mean_reversion_bb`, and the multi variant loop (:899-915) forwards it to its rsi/bb variants. With the box ticked, Step-5 scans of those three strategies will drop every symbol outside a Choppy regime (possibly zero results) where today they ignore the box. It has no backend effect on the other strategies. |

Fields it sends that the builder also sends, identically sourced: universe,
direction, horizon, strategy, the 11 strategy params, `pullback_require_reversal`,
`bt_min_trades`, `bt_min_win_rate`, `shortlist_max_candidates`, `risk_pct`
(0.01 both), and — for `mean_reversion_multi` only — the four variant fields
(Step 5 reads them live from `useScanParamsStore`; the builder reads
`params.meanReversionVariants` etc. from the same store via the `{...saved, ...overrides}`
merge, so they are the same values).

**"Strategy fields" (the pin's exception) — defined [R1-3].** The decision says
"overlaying only the picked strategy and Step 5's multi-variant fields". Read
literally, every StrategyParamsPanel edit would be silently ignored, which is
not what Step 5 does today or what the panel is for. This plan reads "strategy
fields" as `strategy` plus the 16 fields of Step 5's local `params`
(page.tsx:102-119: the 11 strategy params, `requireChoppyRegime`, `btMinTrades`,
`btMinWinRate`, `eventFilter`, `stockShortlistMax`) — exactly the set the Step-4
Run button already overlays via `runStockScan(selected, params)`. This is an
interpretation of "only", stated so the code round can hold the plan to it.

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

Body = the current `runStockScan` lines that compute `saved`, `p`,
`context`, `requireReversal`, `confidenceGate`, `rawOverrides` and call
`buildStockScanRequestBody` — not a verbatim move [R1-6]: those lines read
`runStockScan`'s local `store` (stockScan.ts:272, :296-300); the helper reads
`useScanStore.getState()` itself at call time. Equivalent inside `runStockScan`
because none of the four preceding writes (`setActiveStrategy`,
`setStockScanResult(null)`, `setStockScanError(null)`, `setScanState`) touches
`context` or `scanOverrides`. Then `accountSize: opts.accountSize ?? 50_000`,
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
It passes type-check (non-literal argument, no excess-property check — Step 4
already passes the same 16-field object). The merge takes Step 5's local value,
not the saved one; it is harmless only because the builder never reads
`eventFilter` [R1-12].

`lib/__tests__/scanStoreCardEdits.test.ts:102` cites `step-5-strategy/page.tsx:245`;
update the line reference in the same change (Step 5 still bypasses
`runStockScan`, so the comment's point stands) [R1-13].

Imports: add `manualStockScanRequest` from `@/lib/stockScan`. `useRiskStore`
stays (portfolioValue). No now-unused imports expected; typecheck confirms.

### Not changed (non-goals)

- `analysisStore.analysisRequestFor`'s no-snapshot fallback builds the same body
  a third time (analysisStore.ts:~43). It already goes through
  `buildStockScanRequestBody` and is pinned by the A5 suite; folding it into
  `manualStockScanRequest` is a pure dedupe, not part of the locked fix.
- The `$50k` hardcode in `runStockScan` (Q1).
- Backend: no change. `StockScanRequest` already accepts every field.
- Hydration [R1-13]: Step 5 now reads `useSettingsStore.getState().confidenceGate`
  at click time; before settingsStore rehydrates it would send
  `DEFAULT_CONFIDENCE_GATE`. `runStockScan` has the same exposure today, so it is
  not a regression, but it is a new dependency for Step 5. Not addressed here.

## Q1 — `account_size` — BUILD GATE: Kenneth answers before any code [R1-2]

The answer is recorded as a decision in PROJECT_STATE.json before T1 is written;
T1 and mutation 3 follow the chosen option. The option below marked (a) is the
recommendation, not a default the build may assume.

The locked pin says "a Step-5 body equals the Step-3/4 body apart from the
strategy fields". Taken literally, Step 5 would start sending `50_000` instead of
the user's portfolio value, halving `shares` on Step-5 cards for a user at the
100 000 default. That is a sizing change a request-builder fix should not make
silently.

- **(a) recommended** — Step 5 keeps `portfolioValue`; the pin is
  "equal apart from strategy and `account_size`", and T1 asserts `account_size`
  is `portfolioValue` explicitly.
- (b) literal — Step 5 sends 50 000 like Steps 3/4. T1 then compares whole
  bodies with `toStrictEqual`; mutation 3 is dropped; F2 passes no `opts`.
- (c) fix the other side — `runStockScan` reads `portfolioValue` too (and
  `maxLossPerTradePct` for `risk_pct`?). Changes Step-3/4 sizing; its own decision.

## Tests — new suite `frontend/lib/__tests__/a5bStep5SharedRequest.test.tsx`

Setup mirrors `a5AnalysisMirrorsScan.test.tsx` (mocked `api`, `next/navigation`),
with its **own `beforeEach`** that resets `useScanStore`, `useScanParamsStore`,
`useSettingsStore` and `useRiskStore` to their initial state — the A5 suite's
`reset()` (:47-67) does not reset scanParams/risk, and this suite changes both
[R1-11]. Seeding rules [R1-11]:
- all store seeding happens **before `render`** — the page's `useState`
  initializer (page.tsx:132) captures scanParams; `skipHydration` means the
  hydration sync never fires in jsdom;
- riskStore: `setState({ limits: { ...getState().limits, portfolioValue: 123_456 } })`
  (nested, not a flat field).

Seeded non-default values: `scanOverrides = { weight_trend: 0.4, fast_ema: 12,
regime_headwind_caution_pct: -3, regime_headwind_reject_pct: -9,
fundamentals_caution_above: 55, fundamentals_reject_above: 75,
confidence_atr_mult_target: 2.5, confidence_atr_mult_stop: 1.25,
pullback_require_reversal: true }`, `confidenceGate.enabled = true` with
caution/reject 60/40, `scanParamsStore.requireChoppyRegime = true`,
context = `{ universe: 'NDX100', direction: 'Bearish', horizon: 'Position (…)' }`.

- **T1 — the pin.** Click the Step-5 `ma_crossover` card; capture the posted
  body. Reset the post mock; `await runStockScan('ma_crossover')` with the same
  stores; capture. Assert with **`toStrictEqual`** [R1-8] (explicit-`undefined`
  keys count): under Q1 (a) `{...step5, account_size: 0}` vs
  `{...step4, account_size: 0}` plus `step5.account_size === 123_456`; under (b)
  whole bodies.
- **T2 — every seeded value, hard-coded [R1-9].** T1 is circular (both sides go
  through the helper), so T2 pins the helper's output independently: the Step-5
  body has `universe: ['NDX100']`, `direction: 'Bearish'`, `horizon: 'Position'`,
  `confidence_caution_below: 60`, `confidence_reject_below: 40`,
  `confidence_atr_mult_target: 2.5`, `confidence_atr_mult_stop: 1.25`,
  `overrides: { weight_trend: 0.4, fast_ema: 12 }` (exactly — the non-scorer
  keys are filtered out), `regime_headwind_caution_pct: -3`,
  `regime_headwind_reject_pct: -9`, `fundamentals_caution_above: 55`,
  `fundamentals_reject_above: 75`, `pullback_require_reversal: true`,
  `require_choppy_regime: true`. Run once on the `ma_crossover` card and once on
  the `mean_reversion_bb` card [R1-4], where `require_choppy_regime` actually
  changes the backend's result.
- **T3 — horizon ATR pair and gate off [R1-7].** Seed the same, but **without**
  the two `confidence_atr_mult_*` overrides and with `confidenceGate.enabled = false`.
  Step-5 body: `confidence_atr_mult_target/stop` equal
  `atrMultForHorizon(DEFAULT_CONFIDENCE_GATE, 'Position')` (= the `position`
  pair), and both confidence thresholds are `undefined`. The ATR half fails on
  the old literal (it sent no pair), so T3 catches something.
- **T4 — Step 5's local edits still win.** Before clicking, change
  `getByLabelText(/MA crossover fast/i)` via `fireEvent.change` (the input sits
  in a closed `<details>`, StrategyParamsPanel/index.tsx:32, :115-128 —
  `fireEvent` still works) [R1-11]. Body carries the edited value and
  (toStrictEqual, per Q1) equals `runStockScan('ma_crossover', { maCrossoverFast: edited })`.
- **T5 — mean_reversion_multi through the panel [R1-10].** Change
  `minConfirmations` (and a variant toggle) through the rendered
  `MeanReversionConfirmPanel`, then click the multi card: the body carries the
  panel's values for all four fields. Click a non-multi card:
  `not.toHaveProperty('mean_reversion_variants')` (and the other three).
- **T6 — Step 5 throw path.** `useSettingsStore.setState({ confidenceGate: null })`
  → click: the error text renders, `postStockScan` not called, the loading text
  gone and the cards enabled again.
- **T7 — runStockScan throw path [R1-5].** Same null gate:
  `await runStockScan('ma_crossover')` returns `null`, `scanState === 'FAILED'`,
  `stockScanError` is set and does not contain `could not reach the backend`
  (`reachedRequest` false), `postStockScan` not called.
- Existing: `a5AnalysisMirrorsScan` "Step 5 writer" (stored request equals the
  posted body) and `lib/__tests__/stockScan.test.ts` must pass unchanged.

### Mutation checks (each must turn at least one new test red)

1. Restore the hand-built literal in Step 5 → T1, T2, T3 red.
2. In `manualStockScanRequest`, drop the `overrides` arg from the merge → T4 red.
3. (Q1 (a) only) Step 5 passes no `accountSize` → T1's `account_size` assertion red.
4. In the Step-5 page, disconnect `MeanReversionConfirmPanel`'s `onChange` from
   `setMeanReversionMinConfirm` → T5 red [R1-10].
5. Hoist the `manualStockScanRequest` call in `runStockScan` above the `try` → T7 red [R1-5].
6. Remove the two `confidence_*_below` lines from the builder path (e.g. force
   `confidenceGate.enabled` false inside the helper) → T2 red [R1-9].

## State file [R1-1]

`state.py` treats a `defect_marker` probe as "shipped" once the pattern is gone
(scripts/state.py:97-104) and reports drift when that disagrees with the status
(:626-637). So:
- Now (plan rounds): `active_phase` → `A5B-STEP5-SHARED-REQUEST`; phase status
  `in_progress`, `audit_rounds` bumped per round. The defect marker still
  matches, so no drift.
- **In the same commit that deletes the literal**: status → `shipped_unaudited`
  and `verify` → `{kind: "present", path: <step-5 page>, pattern:
  "manualStockScanRequest\\(stratKey"}`. Leaving it `in_progress` with the
  marker gone makes `state.py` exit 1.
- After a clean code round: `shipped`, `audit_clean: true`.
- Q1's answer recorded as a decision before the build.

## Verification

- `cd frontend && npx jest && npm run typecheck` — full suite, typecheck clean.
- Backend untouched; `python3 scripts/state.py` exit 0.
