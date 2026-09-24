# A5b — a stock scan started from Step 5 uses the shared request builder (plan)

Date: 2026-09-24. Planned against main at `c3460b7`. Frontend only, one commit.

Kenneth's decision `A5B-A5C-LOCKED-2026-09-24`, item (1): Step 5's `runScan` hand-builds the
`POST /api/stock-scan` body and so drops every Step-3 setting. Fix it by building the body with
`buildStockScanRequestBody` (`frontend/lib/resolveStockScanRequest.ts`), overlaying only the picked
strategy and Step 5's own fields, and delete the hand-built body. Pin: a Step-5 body equals the
Step-3/4 body apart from the strategy fields.

---

## 1. Defect, verified on today's tree

`frontend/app/(frame)/screener/step-5-strategy/page.tsx` `runScan` (`:210-265`) posts a literal
object. Compared field by field with what `runStockScan` (`frontend/lib/stockScan.ts:264`, the
Step-3 and Step-4 buttons) sends through `buildStockScanRequestBody`, the Step-5 body is **missing**:

| Missing field | Effect on a Step-5 scan (backend falls back to its default) |
|---|---|
| `overrides` (Step-3 score weights / indicator params, filtered by `STOCKS_SCORER_KEYS`) | scores computed with YAML defaults, not the user's Step-3 weights → **wrong score and status on every row** |
| `confidence_caution_below`, `confidence_reject_below` | **no confidence gate at all** — a candidate the gate would REJECT is shown PASS |
| `confidence_atr_mult_target`, `confidence_atr_mult_stop` | backtest target/stop multiples ignore the Step-3 ATR pair and the per-horizon settings pair → wrong win rate / expectancy |
| `regime_headwind_caution_pct`, `regime_headwind_reject_pct` | regime headwind thresholds ignore Step 3 |
| `fundamentals_caution_above`, `fundamentals_reject_above` | fundamentals thresholds ignore Step 3 |
| `require_choppy_regime` | the Step-5 panel's own setting is never sent (backend default `false`) |

Every one of these can put a wrong number (score, status, win rate, expectancy) in front of the
user, so this is inside the audit gate.

Fields the Step-5 body sends that the builder also sends, with the **same** values: universe,
direction, horizon, strategy, the pullback / MA-crossover / breakout / RSI params, `bt_min_*`,
`shortlist_max_candidates`, `risk_pct: 0.01`, and the four `mean_reversion_multi` fields (only when
the strategy is `mean_reversion_multi`, same as the builder's branch).

One field differs on purpose and **stays** different: `account_size`. Step 5 sends
`riskStore.limits.portfolioValue`; `runStockScan` sends a hardcoded `50_000` (flagged in its own
comment as a pre-existing, separate concern). Changing Step 5 to `50_000` would make a correct
number wrong; changing `runStockScan` is outside this decision. So Step 5 keeps
`accountSize: portfolioValue`, and the pin sets `portfolioValue` to `50_000` when it compares the
two bodies, plus a separate test that Step 5 still sends a non-50k `portfolioValue`.

## 2. Change

In `runScan(stratKey)`, replace the literal with:

```ts
const scan = useScanStore.getState();
const ctx = scan.context;
const requestBody = buildStockScanRequestBody({
  universe: ctx?.universe ? [ctx.universe] : ['SP500'],
  direction: ctx?.direction ?? 'Bullish',
  horizon: (ctx?.horizon ?? 'Swing (5–15d)').split(' ')[0],
  strategy: stratKey,
  // Saved params (incl. the mean-reversion fields, which the page edits
  // straight into the store) overlaid with the panel's unsaved local edits —
  // the same `{ ...saved, ...overrides }` merge runStockScan does.
  params: { ...useScanParamsStore.getState(), ...params },
  requireReversal:
    (scan.scanOverrides.pullback_require_reversal as boolean | undefined) ?? false,
  scanOverrides: scan.scanOverrides,
  confidenceGate: useSettingsStore.getState().confidenceGate,
  accountSize: portfolioValue,  // Step 5's shipped behaviour — see plan §1
  riskPct: 0.01,
});
```

- Reads the stores with `getState()` at click time, as `runStockScan` does, so the two paths read
  the same moment's values.
- `requireReversal` / `scanOverrides` were already read from the hook; the hook reads stay for the
  render-time labels (`entryLabel` uses `requireReversal`).
- The four `mean_reversion_multi` hook reads (`meanReversionVariants` etc.) stay — the
  `MeanReversionConfirmPanel` and the disabled-button check use them — but no longer feed the body;
  the builder reads the same store values from `params`.
- Everything else in `runScan` is untouched: `setStockScanResult(result, requestBody)` (A5), the
  `router.push`, the error text, the last-status refresh.
- Imports: `buildStockScanRequestBody`, `useSettingsStore`.
- The existing A5 comment (`// A5: hoisted so the exact body travels with its result`) stays.

Not changed: `runStockScan`, `buildStockScanRequestBody`, the backend. No persisted shape changes.

## 3. Tests — new file `frontend/app/(frame)/screener/step-5-strategy/__tests__/a5bSharedRequest.test.tsx`

Harness: same mocks as `lib/__tests__/a5AnalysisMirrorsScan.test.tsx` (next/navigation, `@/lib/api`
with `postStockScan` resolving a result). State set up with: a non-default context
(`Bearish`, `Position (1–6m)`, `NDX100`); Step-3 `scanOverrides` carrying a stocks scorer key
(`weight_trend`), an options-only key (`max_delta` — must be filtered out), both headwind pcts,
both fundamentals thresholds, a full ATR pair and `pullback_require_reversal: true`; the settings
`confidenceGate` enabled with non-default `cautionBelow` / `rejectBelow`; scan params with
non-default values; `riskStore.limits.portfolioValue = 50_000`.

- **T1 — parity, all 7 strategies.** For each strategy key: click its Step-5 button, capture the
  posted body; reset; call `runStockScan(key)`, capture its body. `expect(step5).toEqual(step34)`
  — full equality, not a subset. `mean_reversion_multi` is run with a non-empty variant list so
  its button is enabled and its four extra fields are in both bodies.
- **T2 — literal pins** (one strategy), so T1 cannot pass by both paths being wrong the same way:
  `overrides` equals `{ weight_trend: … }` exactly (no `max_delta`), both confidence thresholds equal
  the gate's, the ATR pair equals the override pair, both headwind and both fundamentals values
  equal the Step-3 values, `pullback_require_reversal === true`, `require_choppy_regime` equals the
  stored value.
- **T3 — gate disabled** → both confidence thresholds are absent (undefined) in the Step-5 body.
- **T4 — the panel's unsaved edits win.** Change one StrategyParamsPanel input (e.g. the RSI
  oversold field) without saving; the posted body carries the edited value, and differs from the
  `runStockScan` body in that one field only.
- **T5 — account size.** `portfolioValue = 123_456` → Step-5 body `account_size === 123_456`.
- **T6 — the stored request is the posted body** (the A5 pin, already in `a5AnalysisMirrorsScan`,
  kept there; no duplicate).

### Mutation checks (each must turn at least one test red, then be reverted)

| # | Mutation | Expected red |
|---|---|---|
| M1 | restore the hand-built literal body | T1, T2 |
| M2 | `scanOverrides: {}` | T1, T2 |
| M3 | `confidenceGate: { ...gate, enabled: false }` | T1, T2 |
| M4 | `params: useScanParamsStore.getState()` (drop local edits) | T4 |
| M5 | `params: params` (drop the store merge → mean-reversion fields missing) | T1 (multi) |
| M6 | `accountSize: 50_000` | T5 |
| M7 | `strategy: 'pullback_ema'` | T1 |
| M8 | read `scanOverrides` from an empty object for `requireReversal` only | T2 |

## 4. Verification

`npm run typecheck`, the full Jest suite, `python3 scripts/state.py`. Backend untouched (not re-run
beyond a sanity import, none needed).

## 5. State

Phase `A5B-STEP5-SHARED-REQUEST`: status/audit fields per round; its `defect_marker`
(`pullback_tolerance_pct:\s+params\.pullbackTolerancePct` in the Step-5 page) disappears with the
literal body, so the verify entry is switched to a presence probe on
`buildStockScanRequestBody\(` in the Step-5 page.

## 6. What this changes for the user (to say in the handoff)

A Step-5 scan now honours Step 3: the confidence gate applies (rows it would REJECT are now
REJECT), scores use the Step-3 weights, the ATR pair and headwind/fundamentals thresholds apply.
Results from Step 5 and from Step 3/4 for the same strategy become identical.
