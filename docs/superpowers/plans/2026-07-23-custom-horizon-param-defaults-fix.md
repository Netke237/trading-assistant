# Custom-Horizon Execution-Parameter Defaults Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task, **in the numbered order below — do not reorder or parallelize across tasks.** Task 2 (the new e2e tests) must run and be confirmed FAILING before Tasks 3-5 (the actual code fixes) are applied; landing the code fixes first would silently turn Task 2's "verify it fails" step into a no-op that proves nothing. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Step 3's horizon is `Custom`, both the displayed Execution-Parameter defaults and the actual `scanOverrides` sent to the backend must resolve against the horizon that `scoringHorizonForHold(holdMax)` actually derives (Intraday/Swing/Position), not against the static `PARAM_DEFAULTS_PER_HORIZON.Custom` table entry — which is a fixed Swing-mirror regardless of the selected day range.

**Architecture:** One small shared helper, not a duplicated ternary. `frontend/lib/horizonPresets.ts` already owns `scoringHorizonForHold` and is the single source of truth for horizon resolution. Adding one pure function there — `resolveParamsHorizon(hz, holdMax)` — and calling it from every site that needs this decision means none of them can drift apart from each other again (they share one implementation), and the pure function is trivially unit-testable without spinning up a browser.

**Tech Stack:** TypeScript, Jest (unit), Playwright (e2e) — frontend only, no backend changes.

---

## Ground truth (confirmed by reading source directly)

- `frontend/lib/horizonPresets.ts:50-54` — `scoringHorizonForHold(holdMax)`: `holdMax <= 4` → `'Intraday'`, `<= 20` → `'Swing'`, else `'Position'`.
- `frontend/lib/executionParamDefaults.ts` — `PARAM_DEFAULTS_PER_HORIZON.Custom` is a static object that mirrors `Swing`'s values (`rsi_floor: 38`, `iv_rank_pass_max: 34`, `additive_ma_period: 20`, ...). `Position`'s values differ (`rsi_floor: 37`, `iv_rank_pass_max: 44`, `additive_ma_period: 50`).
- Two call sites in `frontend/app/(frame)/screener/step-3-direction/page.tsx` are the actual bugs — they index the table with the raw key instead of resolving Custom dynamically:
  - **Site A — `page.tsx:748`**: `const defaults = PARAM_DEFAULTS_PER_HORIZON[hz];` — feeds `displayDefaults` (the panel's shown default column, `page.tsx:750`), `countActiveOverrides` (override-count badges, `page.tsx:880/894/916/928`), and the `trend_method` fallback (`page.tsx:886`).
  - **Site B — `page.tsx:712`** inside `handleHzChange`: `const hd = PARAM_DEFAULTS_PER_HORIZON[h];` — feeds the explicit `setScanOverrides({...})` block (`page.tsx:713-731`) that is written into `scanStore.scanOverrides`.
- **`scanStore.scanOverrides` (the thing Site B writes) has two independent downstream consumers, both affected by this bug, confirmed by reading each file directly:**
  1. `frontend/components/organisms/RunScanButton/index.tsx:131-146` — forwards `scanOverrides` near-verbatim as the Options-mode `/api/scan` payload's `overrides` field.
  2. `frontend/lib/stockScan.ts:44-64,94` — `runStockScan`'s `STOCKS_SCORER_KEYS` set includes every field Site B writes (`ma_type`, `fast_ema`, `slow_ema`, `trend_method`, `additive_ma_period`, `additive_ma_type`, `additive_slope_lookback`, `additive_adx_period`, `additive_adx_pass`, `additive_adx_caution`, `additive_price_max`, `additive_slope_max`, `additive_adx_max`, `rs_period`, `rs_pass_threshold`, `rs_caution_threshold`, `rs_benchmark`), filters `store.scanOverrides` down to those keys, and forwards them as `overrides: stocksOverrides` to `api.postStockScan` (`/api/stock-scan`). Same button (`RunScanButton`) dispatches to `runStockScan` instead of `api.postScan` when `screenerMode === 'stocks'` (`RunScanButton/index.tsx:78-80`) — Step 3 is shared across modes, so this is reachable from the same page without navigating anywhere.
  Both paths must be covered by regression tests, not just the Options one.
- **Four more sites** do the identical Custom-vs-not decision, independently — none is a bug (all four already resolve Custom correctly today), but all four are parallel, independently-maintained copies of the exact same ternary that this plan's shared-helper approach exists to eliminate. These were found only progressively, across three separate repo-wide sweeps during this plan's own audit — the first sweep missed two of them, and the second sweep still missed one, which is itself the reason a *fourth*, deliberately exhaustive `grep -rn "scoringHorizonForHold"` across the whole `frontend/` tree (not a `page.tsx`-scoped read) was run to confirm this is now the complete list:
  - `page.tsx:758`: `const weightsKey = hz === 'Custom' ? scoringHorizonForHold(holdMax) : presetByKey(hz).scoringHorizon;` (used for `ScanLogSection`'s `horizonKey` prop, `page.tsx:993`).
  - `page.tsx:688`, inside `syncToStore`: `const scoringHz = newHz === 'Custom' ? scoringHorizonForHold(newMax) : presetByKey(newHz).scoringHorizon;` (used only to build the persisted `context.horizon` display string via `horizonDisplayString(scoringHz, newMin, newMax)`, `page.tsx:692`).
  - `frontend/components/organisms/RunScanButton/index.tsx:109-111`: `const horizon: string = presetKey === 'Custom' ? scoringHorizonForHold(holdMax) : presetByKey(presetKey).scoringHorizon;` — feeds `api.postScan`'s `horizon` field (the Options scan request).
  - `frontend/lib/scanStore.ts:227-229`, inside the persisted store's `migrate` callback's `version < 10` branch: `const scoringHz = legacy.horizonPreset === 'Custom' ? scoringHorizonForHold(legacy.holdMax) : presetByKey(legacy.horizonPreset).scoringHorizon;` — runs once per user, upgrading a pre-v10 persisted `context.horizon` string. Covered by the existing `frontend/lib/__tests__/scanStoreHorizonMigration.test.ts`.

  All four are provably equivalent to `presetByKey(resolveParamsHorizon(key, holdMaxValue)).scoringHorizon`: for a non-Custom key, `resolveParamsHorizon` returns it unchanged, reproducing the existing branch exactly; for `'Custom'`, `resolveParamsHorizon` returns `scoringHorizonForHold(...)`, and since `Intraday`/`Swing`/`Position`'s own `HORIZON_PRESETS` entries each have `scoringHorizon` equal to their own key (`horizonPresets.ts:35-37`), `presetByKey(X).scoringHorizon === X` for those three — reproducing the existing Custom branch exactly. Tasks 3, 4, and 5 consolidate all six sites (two bugs, four already-correct duplicates, across three files: `page.tsx`, `RunScanButton/index.tsx`, `scanStore.ts`) onto the shared helper.
- `ScoringHorizon` (`'Intraday' | 'Swing' | 'Position'`) is a subset of `HorizonKey`, so a function returning `HorizonKey` can return a `ScoringHorizon` value without a cast.

**Deliberately out of scope:** `handleMinChange`/`handleMaxChange` (`page.tsx:733-745`) don't touch `scanOverrides` at all when the user drags the Custom day-range inputs after Custom is already selected — `scanOverrides` for the "sticky" trend/indicator block is only (re)written on a preset-button click (`handleHzChange`). Whether adjusting the day range in place should re-derive those overrides is a separate design question from this bug (which is specifically about the *wrong table entry* being read), and changing it risks clobbering a user's manual per-field overrides on every keystroke. Not touched by this plan.

---

## Task 1: Add the shared resolver helper + unit tests

**Files:**
- Modify: `frontend/lib/horizonPresets.ts`
- Modify: `frontend/lib/__tests__/horizonPresets.test.ts`

- [ ] **Step 1: Add `resolveParamsHorizon` to `horizonPresets.ts`**

Add immediately after `scoringHorizonForHold` (after `frontend/lib/horizonPresets.ts:54`):
```ts
/**
 * Which row of PARAM_DEFAULTS_PER_HORIZON (frontend/lib/executionParamDefaults.ts)
 * to read for a given horizon selection. Custom has no fixed row of its own — it
 * must resolve to whichever scoring horizon the current hold-days range actually
 * falls into, same boundaries as scoringHorizonForHold. Every other key passes
 * through unchanged, preserving its own distinct table row (e.g. Quarterly stays
 * Quarterly, even though it happens to share values with Position today).
 */
export function resolveParamsHorizon(hz: HorizonKey, holdMax: number): HorizonKey {
  return hz === 'Custom' ? scoringHorizonForHold(holdMax) : hz;
}
```

- [ ] **Step 2: Add unit tests, including the boundary values `scoringHorizonForHold` already guards**

Add to `frontend/lib/__tests__/horizonPresets.test.ts`, after the existing `describe('scoringHorizonForHold', ...)` block, and add `resolveParamsHorizon` to the top import:
```ts
import {
  HORIZON_PRESETS,
  presetByKey,
  previewDteWindow,
  scoringHorizonForHold,
  resolveParamsHorizon,
  migrateLegacyHorizon,
  sanitizeHoldDays,
} from '../horizonPresets';
```
```ts
describe('resolveParamsHorizon', () => {
  it('resolves Custom to the scoring horizon derived from holdMax, at the same boundaries as scoringHorizonForHold', () => {
    expect(resolveParamsHorizon('Custom', 2)).toBe('Intraday');
    expect(resolveParamsHorizon('Custom', 4)).toBe('Intraday');
    expect(resolveParamsHorizon('Custom', 5)).toBe('Swing');
    expect(resolveParamsHorizon('Custom', 20)).toBe('Swing');
    expect(resolveParamsHorizon('Custom', 21)).toBe('Position');
    expect(resolveParamsHorizon('Custom', 200)).toBe('Position');
  });

  it('passes every non-Custom key through unchanged, preserving its own defaults-table row', () => {
    for (const key of ['Intraday', 'Swing', 'Position', 'Quarterly', 'SemiAnnual', 'Annual'] as const) {
      expect(resolveParamsHorizon(key, 999)).toBe(key);
    }
  });
});
```

- [ ] **Step 3: Run the new unit tests**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="horizonPresets"`
Expected: PASS (this tests the new pure helper in isolation, before it's wired into anything else).

---

## Task 2: Add e2e regression coverage — write and confirm FAILING before any bug fix lands

**Files:**
- Modify: `frontend/e2e/tests/ws-d-execution-params.spec.ts`

**This task must run before Task 3, 4, or 5's code edits are applied.** Its whole point is to prove the tests actually catch the bug — if the fixes land first, "verify it fails" degenerates into "verify a fixed page behaves correctly," which is a different and much weaker check. Task 1 (the helper function, unused by anything yet) is safe to have landed already; it changes no runtime behavior on its own.

All three new tests use the same setup: click **Annual** (165–200 days, resolves to Position) first, then click **Custom** — Custom inherits the current `holdMin`/`holdMax` (200) without the user touching the day inputs at all, so this isolates the two bug sites cleanly (no dependency on typing into the min/max number fields). Each test also asserts `aria-pressed="true"` on the Custom button before checking anything else, so a silently-failed click (e.g. a regression that leaves `hz` at `'Annual'`) fails the test instead of accidentally passing on Annual's already-correct values.

- [ ] **Step 1: Add the displayed-defaults regression test (will be fixed by Task 3's `defaults` change / Site A)**

Append to `ws-d-execution-params.spec.ts`, inside the `test.describe` block, after the existing `'switching horizon resets panel to new horizon defaults'` test:
```ts
  test('Custom horizon (inherited from a long preset) shows that horizon\'s defaults, not the static Custom table', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    await page.getByText('Execution Parameters').click();
    // Position's values (holdMax=200 resolves to Position via scoringHorizonForHold).
    // The static PARAM_DEFAULTS_PER_HORIZON.Custom entry mirrors Swing and would show 38/34 instead.
    await expect(page.locator('[data-param-key="rsi_floor"]').getByText('37', { exact: true })).toBeVisible();
    await expect(page.locator('[data-param-key="iv_rank_pass_max"]').getByText('44', { exact: true })).toBeVisible();
  });
```

- [ ] **Step 2: Add the Options-mode scan-overrides regression test (will be fixed by Task 4's Site B change, `/api/scan` path)**

Append immediately after the test from Step 1:
```ts
  test('Custom horizon (inherited from a long preset) sends that horizon\'s overrides to an Options-mode scan', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    const overrides = capturedBody?.overrides as Record<string, unknown> | undefined;
    // Position's values (executionParamDefaults.ts:34); the static Custom/Swing-mirrored
    // values (executionParamDefaults.ts:106,109) would be additive_ma_period:20, rs_period:20,
    // rs_benchmark:'NDX' instead. fast_ema/slow_ema happen to be equal across Position and
    // Custom (both 50/200) so aren't useful assertions here.
    expect(overrides?.additive_ma_period).toBe(50);
    expect(overrides?.rs_period).toBe(50);
    expect(overrides?.rs_benchmark).toBe('SPX');
  });
```
Before writing this, double check `PARAM_DEFAULTS_POSITION.rs_period`/`rs_benchmark` (`executionParamDefaults.ts:34`, expect `50`/`'SPX'`) and `PARAM_DEFAULTS_PER_HORIZON.Custom.rs_period`/`rs_benchmark` (`executionParamDefaults.ts:109`, expect `20`/`'NDX'`) are actually different — if a future edit to the table made them equal, this assertion would stop being a useful regression guard and should be swapped for still-different fields.

- [ ] **Step 3: Add the Stocks-mode scan-overrides regression test (will be fixed by Task 4's Site B change, `/api/stock-scan` path — the gap the plan's first draft missed entirely)**

**This cannot be done from Step 3's own "Run Stock Scan" button.** That button (`RunScanButton/index.tsx:78-80`) does `if (!activeStrategy) return; void runStockScan(activeStrategy);` — `activeStrategy` defaults to `null` (`scanStore.ts:183`) and nothing on Step 3 or the mode toggle sets it, so the click would silently no-op (confirmed against the existing `RunScanButton/__tests__/RunScanButton.test.tsx:84`, which has to seed `activeStrategy` via `useScanStore.setState(...)` before exercising this exact path — not possible from a Playwright e2e test without a test-only hook, which doesn't exist here). Instead, drive it through Step 4-stocks' own strategy-card + "Run Stock Scan" button (`app/(frame)/screener/step-4-stocks/page.tsx:152-177,197-233`), which calls `runStockScan(selected, params)` directly — no dependency on the global `activeStrategy` store field. Navigate there via the **StepNavBar "Next" button** (`components/organisms/StepNavBar/index.tsx:38-40`, `router.push` — client-side navigation), not `page.goto`, because `scanOverrides` is deliberately excluded from `scanStore`'s persisted subset (`scanStore.ts:242-259`, `partialize` — it's absent from that list) and would reset to `{}` on a full page reload. A client-side route change keeps the same in-memory Zustand store instance, so `scanOverrides` (written by Task 4's fixed `handleHzChange`) survives the navigation to Step 4-stocks.

Append immediately after the test from Step 2:
```ts
  test('Custom horizon (inherited from a long preset) sends that horizon\'s overrides to a Stocks-mode scan too', async ({ page }) => {
    let capturedBody: Record<string, unknown> | undefined;
    await stubApis(page);
    await page.route('**/api/stock-scan', async (route) => {
      try { capturedBody = route.request().postDataJSON() as Record<string, unknown>; } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-3-direction');
    await page.getByRole('button', { name: 'Stocks' }).click();
    await page.getByRole('button', { name: /Annual/ }).click();
    const customBtn = page.getByRole('button', { name: /Custom/ });
    await customBtn.click();
    await expect(customBtn).toHaveAttribute('aria-pressed', 'true');
    // Client-side nav to Step 4-stocks — scanOverrides isn't persisted, so a page.goto here would lose it.
    await page.getByRole('button', { name: /^Next/ }).click();
    await expect(page).toHaveURL(/step-4-stocks/);
    await page.getByRole('button', { name: /Pullback/ }).click();
    await page.getByRole('button', { name: 'Run Stock Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    const overrides = capturedBody?.overrides as Record<string, unknown> | undefined;
    expect(overrides?.additive_ma_period).toBe(50);
    expect(overrides?.rs_period).toBe(50);
  });
```
The "Stocks" mode-toggle button is in the shared screener layout (`frontend/app/(frame)/screener/layout.tsx:36-42`, plain text label `Stocks`). `getSteps('stocks')` (`components/organisms/Stepper/index.tsx:33-36`) puts `step-4-stocks` (label `Stocks`) directly after `step-3-direction`, so the Next button's accessible name is `Next: Stocks` — matched here with `/^Next/` rather than the exact label, so the test doesn't break if that label copy changes. The strategy card's accessible name is `${bearish ? 'Bounce' : 'Pullback'} to ${params.pullbackEmaPeriod}-${params.pullbackMaType}` (`step-4-stocks/page.tsx:118-119`); default direction is `'Bullish'` (`scanStore.ts`'s `context` defaults to `null`, and `step-3-direction/page.tsx:637`'s local state falls back to `context?.direction ?? 'Bullish'`), so `/Pullback/` matches. `runStockScan` (`frontend/lib/stockScan.ts:68`) sets `scanState: 'SCANNING'` the same way the Options path does, so the same `getByText('SCANNING')` wait works. No extra network stub is needed for Step 4-stocks itself — it has no data-fetching `useEffect`, only the `onRun` handler's `runStockScan` call (verified by reading the full file). The floating `RunScanButton` (also labelled "Run Stock Scan" in stocks mode) is not rendered on this page — only on the dashboard, Step 1, and Step 3 — so there's no ambiguity with Step 4-stocks' own inline button of the same name.

- [ ] **Step 4: Run all three new tests to verify they FAIL against the current, unfixed code**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npx playwright test e2e/tests/ws-d-execution-params.spec.ts -g "inherited from a long preset"`
Expected: all three FAIL. If any of them pass at this point, stop — either the test isn't actually exercising the bug, or Tasks 3-5's edits were applied out of order. Do not proceed to Task 3 until this step genuinely shows three failures.

---

## Task 3: Fix Site A — displayed defaults, and consolidate the two correct-but-duplicated sites in the same file (`page.tsx:687-758`)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`

- [ ] **Step 1: Import `resolveParamsHorizon`, drop the now-unused direct `scoringHorizonForHold` import**

After Steps 2-3 below, every remaining call to `scoringHorizonForHold` in `page.tsx` goes through `resolveParamsHorizon` instead — so the direct import becomes dead (Task 4's Site B fix doesn't touch a `scoringHorizonForHold` call at all — that bug is a raw `PARAM_DEFAULTS_PER_HORIZON[h]` index with no ternary — so it has no bearing on this import). Confirm with a grep after Steps 2-3 land: `grep -n "scoringHorizonForHold" "frontend/app/(frame)/screener/step-3-direction/page.tsx"` should show zero matches (it's still used inside `resolveParamsHorizon` itself, but that lives in `horizonPresets.ts`, not here).

At `page.tsx:22-25`, change:
```ts
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, scoringHorizonForHold, horizonDisplayString,
  type HorizonKey,
} from '@/lib/horizonPresets';
```
to:
```ts
import {
  HORIZON_PRESETS, presetByKey, previewDteWindow, horizonDisplayString,
  resolveParamsHorizon, type HorizonKey, type ScoringHorizon,
} from '@/lib/horizonPresets';
```

- [ ] **Step 2: Consolidate `syncToStore`'s `scoringHz` onto the same helper (not a bug — already correct — but the same duplicated decision this plan is eliminating)**

At `page.tsx:687-688`, change:
```ts
  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    const scoringHz = newHz === 'Custom' ? scoringHorizonForHold(newMax) : presetByKey(newHz).scoringHorizon;
```
to:
```ts
  function syncToStore(newDir: Direction, newHz: HorizonKey, newMin: number, newMax: number) {
    // Provably equivalent to the old ternary for every newHz value (see Ground truth).
    const scoringHz = presetByKey(resolveParamsHorizon(newHz, newMax)).scoringHorizon;
```

- [ ] **Step 3: Use the helper for `defaults` (the actual Site A bug fix), and consolidate `weightsKey` onto it too**

At `page.tsx:747-748`, change:
```ts
  const custom = hz === 'Custom';
  const defaults = PARAM_DEFAULTS_PER_HORIZON[hz];
```
to:
```ts
  const custom = hz === 'Custom';
  const defaults = PARAM_DEFAULTS_PER_HORIZON[resolveParamsHorizon(hz, holdMax)];
```

At `page.tsx:758`, change:
```ts
  const weightsKey = hz === 'Custom' ? scoringHorizonForHold(holdMax) : presetByKey(hz).scoringHorizon;
```
to:
```ts
  // Provably equivalent to the line above for every hz value (see Ground truth) —
  // consolidated onto the same helper `defaults` above uses, closing this
  // independent copy of the decision instead of leaving it to drift on its own.
  const weightsKey: ScoringHorizon = presetByKey(resolveParamsHorizon(hz, holdMax)).scoringHorizon;
```
(`type ScoringHorizon` was already added to the import in Step 1.)

- [ ] **Step 4: Typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean. (`Quarterly`/`SemiAnnual`/`Annual`/other non-Custom keys are unaffected — `resolveParamsHorizon` returns them unchanged, and `presetByKey(...).scoringHorizon` reproduces `weightsKey`'s old value exactly for every input.)

- [ ] **Step 5: Confirm Task 2 Step 1's test now passes**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npx playwright test e2e/tests/ws-d-execution-params.spec.ts -g "shows that horizon's defaults"`
Expected: PASS (it failed in Task 2 Step 4; this fix should make it pass).

---

## Task 4: Fix Site B — `handleHzChange`'s scan overrides (`page.tsx:704-732`)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx`

- [ ] **Step 1: Use the same helper in `handleHzChange`**

At `page.tsx:704-712`, change:
```ts
  const handleHzChange = (h: HorizonKey) => {
    const p = presetByKey(h);
    const nextMin = h === 'Custom' ? holdMin : p.holdMin;
    const nextMax = h === 'Custom' ? holdMax : p.holdMax;
    setHz(h);
    setHoldMin(nextMin);
    setHoldMax(nextMax);
    syncToStore(dir, h, nextMin, nextMax);
    const hd = PARAM_DEFAULTS_PER_HORIZON[h];
```
to:
```ts
  const handleHzChange = (h: HorizonKey) => {
    const p = presetByKey(h);
    const nextMin = h === 'Custom' ? holdMin : p.holdMin;
    const nextMax = h === 'Custom' ? holdMax : p.holdMax;
    setHz(h);
    setHoldMin(nextMin);
    setHoldMax(nextMax);
    syncToStore(dir, h, nextMin, nextMax);
    // Same resolution as `defaults` in Task 3 — both call sites now share one
    // implementation, so they cannot drift apart from each other again.
    const hd = PARAM_DEFAULTS_PER_HORIZON[resolveParamsHorizon(h, nextMax)];
```

- [ ] **Step 2: Typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Confirm Task 2 Steps 2-3's tests now pass**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npx playwright test e2e/tests/ws-d-execution-params.spec.ts -g "sends that horizon's overrides"`
Expected: both PASS (Options-mode and Stocks-mode tests — both failed in Task 2 Step 4; this fix should make both pass).

---

## Task 5: Consolidate the two remaining independent copies of the same decision (not bugs — already correct — found on repeated repo-wide sweeps)

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx`
- Modify: `frontend/lib/scanStore.ts`

Two later repo-wide sweeps during this plan's own audit each found one more site doing the identical `hz === 'Custom' ? scoringHorizonForHold(x) : presetByKey(hz).scoringHorizon` ternary, both already correct, neither caught by the initial `page.tsx`-scoped read: `RunScanButton/index.tsx:109-111` (feeds the Options scan's `horizon` field) and `scanStore.ts:227-229` (a one-time `version < 10` persisted-store migration branch that upgrades a legacy `context.horizon` string). Both get consolidated here.

- [ ] **Step 1: `RunScanButton` — use the shared helper instead of the local ternary**

At `frontend/components/organisms/RunScanButton/index.tsx:109-111`, change:
```ts
    const horizon: string = presetKey === 'Custom'
      ? scoringHorizonForHold(holdMax)
      : presetByKey(presetKey).scoringHorizon;
```
to:
```ts
    // Provably equivalent to the old ternary for every presetKey value (same
    // reasoning as page.tsx's weightsKey/scoringHz — see Ground truth).
    const horizon: string = presetByKey(resolveParamsHorizon(presetKey, holdMax)).scoringHorizon;
```

- [ ] **Step 2: `RunScanButton` — update the import**

At `frontend/components/organisms/RunScanButton/index.tsx:24`, change:
```ts
import { presetByKey, scoringHorizonForHold, sanitizeHoldDays } from '@/lib/horizonPresets';
```
to:
```ts
import { presetByKey, resolveParamsHorizon, sanitizeHoldDays } from '@/lib/horizonPresets';
```
(`scoringHorizonForHold` was only used at the line changed in Step 1 — confirm with `grep -n "scoringHorizonForHold" "frontend/components/organisms/RunScanButton/index.tsx"` showing zero matches after this edit.)

- [ ] **Step 3: `scanStore.ts` — use the shared helper in the `version < 10` migration branch**

At `frontend/lib/scanStore.ts:227-229`, change:
```ts
                  const scoringHz = legacy.horizonPreset === 'Custom'
                    ? scoringHorizonForHold(legacy.holdMax)
                    : presetByKey(legacy.horizonPreset).scoringHorizon;
```
to:
```ts
                  // Provably equivalent to the old ternary for every horizonPreset
                  // value (same reasoning as page.tsx's weightsKey/scoringHz and
                  // RunScanButton's horizon — see the plan's Ground truth section).
                  const scoringHz = presetByKey(resolveParamsHorizon(legacy.horizonPreset, legacy.holdMax)).scoringHorizon;
```

- [ ] **Step 4: `scanStore.ts` — update the import**

At `frontend/lib/scanStore.ts:10`, change:
```ts
import { migrateLegacyHorizon, scoringHorizonForHold, presetByKey, horizonDisplayString } from './horizonPresets';
```
to:
```ts
import { migrateLegacyHorizon, presetByKey, horizonDisplayString, resolveParamsHorizon } from './horizonPresets';
```
(`scoringHorizonForHold` was only used at the line changed in Step 3 — `presetByKey` is still needed, unlike in `RunScanButton`, since the new expression still calls it. Confirm with `grep -n "scoringHorizonForHold" "frontend/lib/scanStore.ts"` showing zero matches after this edit.)

- [ ] **Step 5: Typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean.

- [ ] **Step 6: Run the existing test suites touching both files to confirm no behavior change**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="RunScanButton|scanStoreHorizonMigration"`
Expected: all pre-existing tests still pass unchanged — this is a pure refactor of already-correct logic in both files, not a behavior change, so nothing here should need updating. (`scanStoreHorizonMigration.test.ts` — `frontend/lib/__tests__/scanStoreHorizonMigration.test.ts` — is the existing test file covering the `version < 10` migration branch touched in Step 3; `RunScanButton.test.tsx:140-158` already exercises `Custom` + `holdMax=185` and asserts `horizon === 'Position'`, which is unchanged by this refactor.)

---

## Task 6: Full verification and commit

- [ ] **Step 1: Run all three new e2e tests together, expect PASS**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npx playwright test e2e/tests/ws-d-execution-params.spec.ts -g "inherited from a long preset"`
Expected: all three PASS (this re-confirms Tasks 3-4's per-task checks, now with Task 5's consolidation also in place).

- [ ] **Step 2: Run the full spec file (minus the two known pre-existing broken tests — see separate cleanup below), expect no new regressions**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npx playwright test e2e/tests/ws-d-execution-params.spec.ts`
Expected: the 4 previously-passing tests still pass, the 3 new tests pass. (The 2 pre-existing failures — `'panel expands to show parameter rows'` and `'reset to defaults clears overrides'` — are being deleted in a separate, unrelated cleanup per Kenneth's explicit instruction; not this plan's concern.)

- [ ] **Step 3: Run the unit test suite for touched areas**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run test -- --testPathPattern="horizonPresets|paramDefaults|RunScanButton|scanStoreHorizonMigration"`
Expected: all pass, including the new `resolveParamsHorizon` tests from Task 1.

- [ ] **Step 4: Full typecheck**

Run: `cd "F:\Git\GitHub\Trading assistant\frontend" && npm run typecheck`
Expected: clean, zero errors.

- [ ] **Step 5: Commit**

```bash
git add "frontend/lib/horizonPresets.ts" \
  "frontend/lib/__tests__/horizonPresets.test.ts" \
  "frontend/app/(frame)/screener/step-3-direction/page.tsx" \
  "frontend/components/organisms/RunScanButton/index.tsx" \
  "frontend/lib/scanStore.ts" \
  "frontend/e2e/tests/ws-d-execution-params.spec.ts"
git commit -m "$(cat <<'EOF'
fix(screener): Custom horizon resolves execution-param defaults dynamically

Step 3's Custom horizon always read the static PARAM_DEFAULTS_PER_HORIZON.Custom
table entry (a fixed Swing-mirror) for both the displayed panel defaults and the
scanOverrides written to the store — which feeds both the Options scan payload
and the Stocks scan payload (runStockScan's STOCKS_SCORER_KEYS filter) — instead
of resolving to whichever horizon the actual hold-days range maps to via
scoringHorizonForHold. Added a shared resolveParamsHorizon() helper and
consolidated all six sites (across page.tsx, RunScanButton, and scanStore.ts's
persisted-store migration) that independently re-implemented this same
Custom-vs-not decision onto it, and added unit + e2e coverage across both the
Options and Stocks scan paths.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes (spec coverage)

- Confirmed by reading source directly (not grep alone): `scoringHorizonForHold`'s boundaries, all six sites re-implementing the Custom-vs-not decision (two buggy, four already-correct — found progressively across three repo-wide sweeps during this plan's own audit, not all caught by the initial `page.tsx`-scoped read), and both downstream consumers of `scanStore.scanOverrides` (`RunScanButton` for Options, `stockScan.ts`'s `runStockScan` for Stocks) — establishing that Site B is a functional bug affecting two real scan pipelines, not just cosmetic and not just one pipeline.
- Introduced one shared `resolveParamsHorizon` helper and consolidated every site (buggy or not) onto it, proving equivalence algebraically for the four already-correct sites before touching them, backed by existing tests that already exercise the equivalence empirically (`RunScanButton.test.tsx:140-158` and `scanStoreHorizonMigration.test.ts` both assert `Custom + holdMax:185 → 'Position'`-derived outcomes that are unchanged by the refactor) — this makes every one of the six call sites structurally unable to drift apart from each other again.
- **Task ordering is deliberate and load-bearing**: Task 2 (write the three e2e tests, confirm all three FAIL) comes *before* Tasks 3-5 (the actual code changes), not after. An earlier draft of this plan had the tests as the last task, which meant a sequential task-by-task executor would apply every code fix first and only then "verify" the tests fail — which they no longer would, silently defeating the regression check. Each of Tasks 3 and 4 now ends with a step confirming its own slice of Task 2's tests flips from failing to passing, so there's a real red→green signal per fix, not just a final bulk PASS at the end.
- Chose the "Annual → Custom" click sequence for the new tests specifically because it changes zero day-input state (Custom inherits the prior preset's `holdMin`/`holdMax` unchanged), isolating the fix from the `handleMinChange`/`handleMaxChange` day-range-typing code path entirely. Added an explicit `aria-pressed="true"` assertion on the Custom button in every new test so a no-op click (component regression, not this bug) fails loudly instead of silently passing on Annual's already-correct values.
- The Stocks-mode e2e test goes through Step 4-stocks's own strategy-card + Run button, not Step 3's "Run Stock Scan" button — the latter requires a global `activeStrategy` that nothing in that flow sets, confirmed against the existing `RunScanButton.test.tsx`'s own setup requirement for that exact code path.
- `Quarterly`/`SemiAnnual`/`Annual` are unaffected — `resolveParamsHorizon` passes any non-Custom key through unchanged.
- Deliberately left `handleMinChange`/`handleMaxChange` untouched — see "Deliberately out of scope" above.
- No backend changes — this is purely how the frontend selects which row of its own (already-correct) hardcoded table to read.
