# Stocks Step Merge — Stage 1 (one strategy picker) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Stocks path has exactly one place to pick a strategy and run a stock scan — Step 4 (`step-4-stocks`) — with every feature the Step 5 (`step-5-strategy`) picker had, and Step 5 is removed from the Stocks step list (6 steps instead of 7).

**Architecture:** Step 4's page is the base (decision Q2). The four things only Step 5 had are moved onto it: the readable "saved settings unreadable" error (moved into the shared `runStockScan`, so the Step 1–3 floating button gets it too), the scan-params hydration sync, the Pre-warm history row, and click-to-select persistence of `activeStrategy`. Step 5's route stays as a one-line redirect to Step 4 so bookmarks keep working. The results table and inline position card on Step 4 are **not** touched — that is Stage 2.

**Tech Stack:** Next.js 15 App Router, TypeScript 5.7 strict, Zustand v5, Jest + Testing Library, CSS Modules.

**Spec:** the grilling session of 2026-10-04 (Kenneth, "I agree with all your proposals" for Q1–Q5; "go with your recommendations" for Q6–Q12). The decisions are restated verbatim-in-substance in Task 0 so they travel with this plan; Task 0 records them in `docs/superpowers/PROJECT_STATE.json`.

## Global Constraints

- Frontend only. No backend, YAML or schema change. No change to the request body `POST /api/stock-scan` receives for any input that scans successfully today.
- `npm run typecheck` clean and `npm run test` green before every commit (run from `frontend/`).
- Python 3.11 is irrelevant here (no backend run) — do not touch backend pins.
- CSS Modules only; colours from `app/globals.css` tokens; no card shadows; form labels weight 400.
- Do not rename any persisted storage key. `scanStore` is `'bamendjou-scan-store'` (grandfathered) — no new persisted field is added, so **no `version` bump**.
- No feature from Step 4 or Step 5 may be lost (Kenneth's explicit constraint).
- Out of scope for Stage 1 (Stage 2 owns them): results table merge (Q9), auto-advance after Run (Q8), Step 7 → `StockPositionCard` (Q10), after-scan arm list into the store (Q11), basket button placement (Q12). **Step 4 keeps its results table, inline position card, auto-execute and Send basket exactly as today.**
- Audit gate (`PROJECT_STATE.json` → `audit_rule`, `.claude/skills/K-adversarial-audit-loop/SKILL.md`): this plan gets an independent adversarial PLAN round before any code; the code gets independent CODE rounds; cap three rounds per stage; only gate-level findings (a wrong number in front of the user or on a broker order, or corrupted persisted data) are fixed in-branch.

---

## Facts this plan rests on (verified against `main` @ `ba0bed95`)

| # | Fact | Where |
|---|---|---|
| F1 | Step 4 and Step 5 both list the same 7 strategies and both post through `buildStockScanRequestBody`; Step 4 via `runStockScan`, Step 5 via its own `runScan`. `a5bSharedRequest` T1 pins the two bodies equal for all 7. | `step-4-stocks/page.tsx:200`, `step-5-strategy/page.tsx:211-269`, `lib/stockScan.ts:302-389` |
| F2 | **Only Step 5** maps a throw while *building* the request (malformed persisted `confidenceGate`) to `STOCK_SCAN_SETTINGS_INVALID` and logs it with a prefix. `runStockScan` passes it through `stockScanFailureReason(err, false)`, which returns the raw `TypeError` text. | `step-5-strategy/page.tsx:250-255`, `lib/stockScan.ts:144-176` |
| F3 | **Only Step 5** re-syncs the panel params when `useScanParamsStore` finishes rehydrating (`skipHydration: true`). Step 4's `useState(() => ({ ...savedParams }))` can capture module defaults on a fresh load. | `step-5-strategy/page.tsx:138-170`, `step-4-stocks/page.tsx:132` |
| F4 | **Only Step 5** has the Pre-warm history row (`startHistoryPrefetch`, `getHistoryPrefetchStatus` poll every 5 s, `getLastDataRefresh`). | `step-5-strategy/page.tsx:190-291, 361-387` |
| F5 | `activeStrategy` is documented as "the user's currently selected strategy for the next scan"; `lastStockScanStrategy` is the backend's strategy of the last run. Today only a Run writes it. Readers: `RunScanButton` (runs it), `analysisStore` current-settings basis, `searchProfileSnapshot` save/load. | `lib/scanStore.ts:410-424` |
| F6 | Step 4 passes its local `selected` as `strategyKey` to `StockPositionCard` → `StockAutoTradeArm`, which calls `api.addStrategyWatch(symbol, strategyKey, direction)`. Selecting another card after a scan therefore arms a **persisted strategy watch with a strategy the row was not scanned with**. Pre-existing; Q5 makes it easier to hit. | `step-4-stocks/page.tsx:472`, `StockPositionCard/index.tsx:1362-1368`, `StockAutoTradeArm/index.tsx:40` |
| F7 | `scanStore.stockScanRequest` holds the exact body of the run whose result is on screen (A5), including `strategy`. | `lib/scanStore.ts:393, 576`, `lib/resolveStockScanRequest.ts:110` |
| F8 | `ScreenerStepGate` bounces any `step-*` slug not in the active mode's list to that mode's index-4 step — **only if the route exists**; a deleted folder is a Next 404 before the gate runs. | `ScreenerStepGate/index.tsx:97-114` |
| F9 | `StepNavBar` renders `STEP {current} OF {steps.length}` from `getSteps(mode)`; page headers hard-code "STEP n OF 7". | `StepNavBar/index.tsx:27,119`; `step-4-stocks/page.tsx:264`, `step-6-backtest/page.tsx:111`, `step-7-position-card/page.tsx:186` |
| F10 | Two `state.py` PRESENCE probes point at `step-5-strategy/page.tsx`: phase `A5B-STEP5-SHARED-REQUEST` (`buildStockScanRequestBody\(\{`) and `A5D-STEP5-READABLE-SCAN-ERROR` (`STOCK_SCAN_SETTINGS_INVALID`). Deleting the page makes `state.py` exit non-zero. | `PROJECT_STATE.json` `phases[37].verify`, `phases[50].verify` |
| F11 | Step 5 tests: `a5bSharedRequest` (T1 parity, T2–T5 literal pins), `a5dReadableScanError` (T1–T5), `p3aScanSizing` (also covers `runStockScan`, Analysis, Pre-Breakout). | `step-5-strategy/__tests__/` |
| F12 | Stepper test pins the Stocks list at 7 slugs incl. `step-5-strategy`. `ScreenerStepGate` tests use `/screener/step-5-strategy` as a **cross-mode** path in prebreakout mode — still valid after this change (it is still a `step-*` slug not in that mode's list). | `Stepper/__tests__/Stepper.test.tsx:36-45`, `ScreenerStepGate/__tests__/*` |

---

## File map

| File | Change | Responsibility after the change |
|---|---|---|
| `frontend/lib/stockScan.ts` | Modify `runStockScan` catch (~L302-389) | The one stock-scan runner; owns the readable pre-request message |
| `frontend/lib/__tests__/stockScan.test.ts` | Add a `describe` | Unit pins for the pre-request message |
| `frontend/lib/__tests__/stockScanRequestPins.test.ts` | Create (ported from `a5bSharedRequest` T2–T5) | Literal request-body pins on `runStockScan` |
| `frontend/lib/__tests__/p3aScanSizing.test.tsx` | Create by `git mv` from `step-5-strategy/__tests__/`, Step-5 block retargeted to Step 4 | P3a sizing pins for every manual path |
| `frontend/app/(frame)/screener/step-4-stocks/page.tsx` | Modify | Single strategy picker + run + (unchanged) results |
| `frontend/app/(frame)/screener/step-4-stocks/page.module.css` | Add `.prefetchRow/.prefetchLeft/.prefetchBtn` | — |
| `frontend/app/(frame)/screener/step-4-stocks/HistoryPrefetchRow.tsx` | Create | Pre-warm history row, moved verbatim from Step 5 |
| `frontend/app/(frame)/screener/step-4-stocks/__tests__/pickerSelection.test.tsx` | Create | Q5 + F6 pins |
| `frontend/app/(frame)/screener/step-4-stocks/__tests__/paramsHydration.test.tsx` | Create | F3 pin |
| `frontend/app/(frame)/screener/step-4-stocks/__tests__/historyPrefetch.test.tsx` | Create | F4 pin |
| `frontend/app/(frame)/screener/step-4-stocks/__tests__/readableScanError.test.tsx` | Create (ported from `a5dReadableScanError`) | F2 page-level pins |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | Replace with a redirect | Keeps old links working |
| `frontend/app/(frame)/screener/step-5-strategy/page.module.css`, `__tests__/` | Delete (after ports land) | — |
| `frontend/components/organisms/Stepper/index.tsx` + test | Modify | Stocks list = 6 steps |
| `frontend/app/(frame)/screener/step-6-backtest/page.tsx`, `step-7-position-card/page.tsx` | Header/empty-state text | Correct step numbers |
| `docs/superpowers/PROJECT_STATE.json`, `CLAUDE.md`, two code comments | Modify | Records + docs |

---

### Task 0: Branch, claim, record the decisions

**Files:**
- Modify: `docs/superpowers/PROJECT_STATE.json` (`decisions`, `phases`)

- [x] **Step 1: Branch and claim** (done 2026-10-04; on Windows use `python`, not `python3`)

```bash
git switch -c claude/stocks-step-merge-s1
python3 scripts/claim.py take STOCKS-STEP-MERGE-S1 -m "Stage 1: one Stocks strategy picker on Step 4, Step 5 removed"
```
Expected: claim exit 0. Exit 1 = taken → stop and tell Kenneth.

- [x] **Step 2: Add the decision record** to `decisions` with id `STOCKS-STEP-MERGE-2026-10-04`, text:

> Kenneth, 2026-10-04 (grilling): de-duplicate the Stocks path with zero feature loss. Q1 scope B in two audited stages (S1 picker; S2 results table + position card). Q2 Step 4 code is the picker base; port Step 5's readable settings error, params hydration sync and Pre-warm row. Q3 card click selects, Run button runs. Q4 multi-signal panel only when mean_reversion_multi is selected. Q5 selecting a card writes activeStrategy. Q6 Stocks path has 6 steps (Options keeps 7). Q7 keep slugs; step-5-strategy redirects to step-4-stocks. Q8 (S2) after a successful Run, go to the Backtest step; on failure stay. Q9 (S2) one results table with the union of Step 4 + Step 6 columns, event filter + hidden note, win-rate caution at the configured bt_min_win_rate (0.40 today; confirm). Q10 (S2) Position step = candidate nav + full StockPositionCard; Step 7's own order code retired (fixes: Step 7 has no method-pick selector, so its order buttons are dead unless a pick was made on Step 4). Q11 (S2) after-scan arm list moves to scanStore, in memory only (no persist). Q12 (S2) Send basket on Backtest and Position steps.

- [x] **Step 3: Add the phase** to `phases` (done 2026-10-04 on `claude/stocks-step-merge-s1`; also `active_phase` = this id):

```json
{
  "id": "STOCKS-STEP-MERGE-S1",
  "name": "Stocks path: one strategy picker (Step 4), Step 5 removed",
  "status": "not_started",
  "audit_rounds": 0,
  "audit_clean": false,
  "depends_on": [],
  "plan": "docs/superpowers/plans/2026-10-04-stocks-step-merge-stage1-plan.md",
  "verify": { "kind": "present", "path": "frontend/components/organisms/Stepper/index.tsx", "pattern": "index: 5, slug: 'step-6-backtest'", "note": "PRESENCE ONLY: Backtest is Stocks step 5, i.e. Step 5 (Strategy) is out of the Stocks step list." }
}
```
Correction made while recording it: `state.py`'s `"absent"` kind is the **same** presence test as `"present"` (found = shipped, see `probe()`), so an `absent` probe on `slug: 'step-5-strategy'` would have read as shipped *before* the change. The probe instead pins a string that exists only *after* Task 6. Valid statuses are `not_started` / `in_progress` / `shipped` (there is no `planned` or `built`).

- [ ] **Step 4: Verify and commit**

```bash
python3 scripts/state.py
```
Expected: exit 0, `STOCKS-STEP-MERGE-S1 not started`, no drift (the pattern is absent and the status says not started).

```bash
git add docs/superpowers/PROJECT_STATE.json docs/superpowers/plans/2026-10-04-stocks-step-merge-stage1-plan.md
git commit -m "docs(state): record STOCKS-STEP-MERGE decisions and stage 1 plan"
```

- [ ] **Step 5: PLAN audit round** — run `K-adversarial-audit-loop` in audit-only mode on this plan file with a fresh subagent applying `bmad-review-adversarial-general`, briefed on the gate. Do not start Task 1 until a plan round is clean (cap 3).

---

### Task 1: `runStockScan` shows the readable settings message (F2)

**Files:**
- Modify: `frontend/lib/stockScan.ts` (`runStockScan`, ~L302-389)
- Test: `frontend/lib/__tests__/stockScan.test.ts`
- Test (create): `frontend/app/(frame)/screener/step-4-stocks/__tests__/readableScanError.test.tsx`

**Interfaces:**
- Consumes: `STOCK_SCAN_SETTINGS_INVALID`, `ScanSizingError`, `SCAN_RISK_ZERO_MESSAGE` (all already exported from `lib/stockScan.ts`).
- Produces: `runStockScan(strategy, overrides)` unchanged signature; on a non-`ScanSizingError` throw **while building the request** it stores `STOCK_SCAN_SETTINGS_INVALID` in `scanStore.stockScanError` and calls `console.error('runStockScan: building the stock-scan request failed', err)`.

The boundary is **only the build** (reading stores + `scanSizingFromRisk` + `buildStockScanRequestBody`). A store write that throws *before* the build (`setStockScanResult(null)` etc. — a `QuotaExceededError`) must keep its own text; that is why a second flag is needed, not `!reachedRequest`.

- [ ] **Step 1: Write the failing unit tests** — append to `lib/__tests__/stockScan.test.ts` (it already mocks `@/lib/api` and resets stores in `describe('runStockScan')`'s `beforeEach`; put this block inside that `describe` so it inherits the reset):

```ts
  describe('a throw while building the request (moved from Step 5, A5d)', () => {
    let consoleError: jest.SpyInstance;
    beforeEach(() => { consoleError = jest.spyOn(console, 'error').mockImplementation(() => {}); });
    afterEach(() => consoleError.mockRestore());

    it('confidenceGate: null stores the settings message, posts nothing, logs once', async () => {
      useSettingsStore.setState({ confidenceGate: null } as never);
      expect(await runStockScan('breakout_base')).toBeNull();
      expect(api.postStockScan).not.toHaveBeenCalled();
      expect(useScanStore.getState().stockScanError).toBe(STOCK_SCAN_SETTINGS_INVALID);
      expect(useScanStore.getState().scanState).toBe('FAILED');
      expect(consoleError).toHaveBeenCalledTimes(1);
      expect(consoleError.mock.calls[0][0]).toBe('runStockScan: building the stock-scan request failed');
      expect(consoleError.mock.calls[0][1]).toBeInstanceOf(TypeError);
    });

    it('a malformed non-null gate { enabled: true } gets the same message', async () => {
      useSettingsStore.setState({ confidenceGate: { enabled: true } } as never);
      await runStockScan('breakout_base');
      expect(useScanStore.getState().stockScanError).toBe(STOCK_SCAN_SETTINGS_INVALID);
    });

    it('a 0% max loss keeps its own message and is not logged', async () => {
      useRiskStore.setState((s) => ({ limits: { ...s.limits, maxLossPerTradePct: 0 } }));
      try {
        await runStockScan('breakout_base');
        expect(useScanStore.getState().stockScanError).toBe(SCAN_RISK_ZERO_MESSAGE);
        expect(consoleError).not.toHaveBeenCalled();
      } finally {
        useRiskStore.setState((s) => ({ limits: { ...s.limits, maxLossPerTradePct: 0.01 } }));
      }
    });

    it('a store write failing BEFORE the build keeps its own text, not the settings message', async () => {
      const original = useScanStore.getState().setStockScanResult;
      useScanStore.setState({ setStockScanResult: () => { throw new Error('QuotaExceededError'); } } as never);
      try {
        await runStockScan('breakout_base');
        expect(useScanStore.getState().stockScanError).toBe('QuotaExceededError');
        expect(consoleError).not.toHaveBeenCalled();
      } finally {
        useScanStore.setState({ setStockScanResult: original } as never);
      }
    });
  });
```
Add to the file's imports: `STOCK_SCAN_SETTINGS_INVALID, SCAN_RISK_ZERO_MESSAGE` from `@/lib/stockScan`, and `import { useRiskStore } from '@/lib/riskStore';`. Before writing the 0% case, read `riskStore`'s default `maxLossPerTradePct` and restore **that** value in `finally`, not a guessed 0.01.

- [ ] **Step 2: Run, expect FAIL**

Run (from `frontend/`): `npm run test -- --testPathPattern=lib/__tests__/stockScan.test`
Expected: the two gate cases FAIL (stockScanError is a `Cannot read properties…` string); the 0% and pre-build cases PASS already.

- [ ] **Step 3: Implement** — in `runStockScan`:

```ts
  let reachedRequest = false;
  // True only while the request is being BUILT from the saved stores. A throw
  // in that window (not ScanSizingError, which carries its own message) is a
  // malformed saved setting -- A5d's STOCK_SCAN_SETTINGS_INVALID, moved here
  // from Step 5 so Step 4 and the floating Run button say it too. A store
  // write failing before the build is NOT that, hence a flag of its own.
  let building = false;
  try {
    store.setActiveStrategy(strategy);
    store.setStockScanResult(null);
    store.setStockScanError(null);
    store.setScanState('SCANNING');

    building = true;
    const saved = useScanParamsStore.getState();
    // ... unchanged through `const requestBody = buildStockScanRequestBody({...});`
    building = false;

    reachedRequest = true;
    // ... unchanged
  } catch (err) {
    const settingsUnreadable = building && !(err instanceof ScanSizingError);
    if (settingsUnreadable) console.error('runStockScan: building the stock-scan request failed', err);
    try {
      store.setStockScanError(
        settingsUnreadable ? STOCK_SCAN_SETTINGS_INVALID : stockScanFailureReason(err, reachedRequest),
      );
    } catch { /* see above — the null return is the signal that survives */ }
    try {
      store.setScanState('FAILED');
    } catch { /* ditto */ }
    return null;
  } finally {
```
Keep every existing comment in the catch.

- [ ] **Step 4: Run, expect PASS**

Run: `npm run test -- --testPathPattern=lib/__tests__/stockScan.test`
Expected: all PASS, including the pre-existing cases.

- [ ] **Step 5: Page-level port of A5d** — create `step-4-stocks/__tests__/readableScanError.test.tsx`. Copy `step-5-strategy/__tests__/a5dReadableScanError.test.tsx` and change exactly this:
  - `import Step4StocksPage from '../page';` instead of `Step5`; `usePathname: () => '/screener/step-4-stocks'`.
  - Add the mocks `scanFailureMessage.test.tsx` uses for heavy children: `StockPositionCard`, `StockSendDialog`, `ScanFunnel`, `WatchStar` → `() => null` (do **not** mock `StrategyParamsPanel` or `runStockScan`; this test needs the real ones).
  - Extend the `@/lib/api` mock with `startHistoryPrefetch`, `getHistoryPrefetchStatus` (Task 4 renders the row on Step 4).
  - `PREFIX = 'runStockScan: building the stock-scan request failed'`.
  - Replace `clickAndSettle` with: select the card, click Run, wait for `getLastStockScanStatus` to be called `calls` times and for the Run button to be enabled:
    ```ts
    function runButton() { return screen.getByRole('button', { name: /Run Stock Scan|Running backtest scan/ }) as HTMLButtonElement; }
    async function clickAndSettle(calls: number) {
      fireEvent.click(button());
      fireEvent.click(runButton());
      await waitFor(() => expect(m(api.getLastStockScanStatus)).toHaveBeenCalledTimes(calls));
      await waitFor(() => expect(runButton()).not.toBeDisabled());
    }
    ```
  - Step 4 prefixes its inline error: every `getByText(X)` for an error becomes `getByText(\`Scan failed — ${X}\`)`.
  - T5's last two assertions: drop `mockPush` (Step 4 does not navigate in Stage 1); keep `queryByText(STOCK_SCAN_SETTINGS_INVALID, { exact: false })` → `null`.

Run: `npm run test -- --testPathPattern=step-4-stocks/__tests__/readableScanError`
Expected: PASS (Task 1 code already landed).

- [ ] **Step 6: Typecheck, full suite, commit**

```bash
npm run typecheck
npm run test
git add frontend/lib/stockScan.ts frontend/lib/__tests__/stockScan.test.ts "frontend/app/(frame)/screener/step-4-stocks/__tests__/readableScanError.test.tsx"
git commit -m "fix(stock-scan): runStockScan shows the readable saved-settings message (A5d moved from Step 5)"
```

---

### Task 2: Selecting a card is the active strategy; the position card uses the scanned strategy (Q5, F5, F6)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (L95, L133, L188-189, L280-283, L310, L330-337, L472)
- Test (create): `frontend/app/(frame)/screener/step-4-stocks/__tests__/pickerSelection.test.tsx`

**Interfaces:**
- Consumes: `useScanStore` `activeStrategy`, `setActiveStrategy`, `stockScanRequest`, `lastStockScanStrategy`.
- Produces: Step 4 has **no local `selected` state**; selection == `scanStore.activeStrategy`. `StockPositionCard` receives `strategyKey = stockScanRequest?.strategy ?? lastStockScanStrategy ?? ''`.

- [ ] **Step 1: Write the failing tests**

```tsx
import '@testing-library/jest-dom';
import { render, screen, fireEvent, act } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';

const mockCardProps = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => '/screener/step-4-stocks',
}));
jest.mock('@/lib/stockScan', () => ({
  ...jest.requireActual('@/lib/stockScan'),
  runStockScan: jest.fn(),
}));
jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null })),
  API_BASE_URL: 'http://localhost:8000',
}));
jest.mock('@/components/organisms/StockPositionCard', () => ({
  StockPositionCard: (p: { strategyKey: string }) => { mockCardProps(p); return null; },
}));
jest.mock('@/components/organisms/StockSendDialog', () => ({ StockSendDialog: () => null }));
jest.mock('@/components/organisms/ScanFunnel', () => ({ ScanFunnel: () => null }));
jest.mock('@/components/atoms/WatchStar', () => ({ WatchStar: () => null }));

const card = (label: RegExp) =>
  screen.getAllByText(label).map((e) => e.closest('button')).find((b) => b !== null) as HTMLButtonElement;

const CANDIDATE = {
  symbol: 'AAPL', company: 'Apple', price: 100, direction: 'Bullish',
  strategy: { strategy: 'pullback_ema', entry_price: 100, stop_price: 95, target_price: 110, targets: [110], rr_ratio: 2, atr: 1, detail: '' },
  backtest: { n_trades: 20, win_rate: 0.55, total_return_pct: 10, max_drawdown_pct: -5, expectancy: 1, sharpe: 1, confidence: 60, passes_gate: true, summary_text: 'ok' },
  stock_score: 80, stock_status: 'PASS', shares: 10, dollar_risk: 50, dollar_size: 1000,
};

beforeEach(() => {
  mockCardProps.mockClear();
  useScanStore.setState({
    context: { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' },
    activeStrategy: null, stockScanResult: null, stockScanRequest: null,
    lastStockScanStrategy: null, scanState: 'IDLE', stockScanError: null,
  } as never);
});

it('clicking a card writes activeStrategy without running a scan', () => {
  const { runStockScan } = jest.requireMock('@/lib/stockScan');
  render(<Step4StocksPage />);
  fireEvent.click(card(/^Breakout from tight base$/));
  expect(useScanStore.getState().activeStrategy).toBe('breakout_base');
  expect(runStockScan).not.toHaveBeenCalled();
});

it('a strategy set elsewhere (search profile load) shows as selected', () => {
  render(<Step4StocksPage />);
  act(() => useScanStore.getState().setActiveStrategy('ma_crossover'));
  expect(screen.getByRole('button', { name: 'Run Stock Scan' })).toBeEnabled();
  expect(card(/^MA Crossover \d+\/\d+$/).className).toMatch(/cardActive/);
});

it('the position card gets the strategy the rows were scanned with, not the current selection', () => {
  useScanStore.setState({
    activeStrategy: 'pullback_ema',
    stockScanResult: { scan_id: 'S', timestamp: 't', candidates: [CANDIDATE], rejected: [] },
    stockScanRequest: { strategy: 'pullback_ema' },
  } as never);
  render(<Step4StocksPage />);
  fireEvent.click(card(/^Breakout from tight base$/));       // change selection after the scan
  fireEvent.click(screen.getByText('AAPL').closest('button')!); // open the row
  expect(mockCardProps).toHaveBeenLastCalledWith(expect.objectContaining({ strategyKey: 'pullback_ema' }));
});

it('falls back to lastStockScanStrategy when no request is on record', () => {
  useScanStore.setState({
    stockScanResult: { scan_id: 'S', timestamp: 't', candidates: [CANDIDATE], rejected: [] },
    stockScanRequest: null, lastStockScanStrategy: 'ma_crossover',
  } as never);
  render(<Step4StocksPage />);
  fireEvent.click(screen.getByText('AAPL').closest('button')!);
  expect(mockCardProps).toHaveBeenLastCalledWith(expect.objectContaining({ strategyKey: 'ma_crossover' }));
});
```
Before running, check `CANDIDATE` against `PositionCardData` in `types/stockDomain.ts` and `computeStockDeltas`/`splitStockRejected` inputs; add any field the page reads so the row renders.

- [ ] **Step 2: Run, expect FAIL**

Run: `npm run test -- --testPathPattern=step-4-stocks/__tests__/pickerSelection`
Expected: tests 1, 2 and 3 FAIL (selection is local; the card gets the selection). Test 4 FAILs too (strategyKey is `''` when nothing is selected).

- [ ] **Step 3: Implement** in `step-4-stocks/page.tsx`:

```tsx
  const activeStrategy    = useScanStore((s) => s.activeStrategy);
  const setActiveStrategy = useScanStore((s) => s.setActiveStrategy);
  // The strategy the rows on screen were scanned with — NOT the current
  // selection, which can change after the scan. StockAutoTradeArm persists a
  // strategy watch with this key, so it must name the scan's strategy.
  const scannedStrategy = useScanStore((s) => s.stockScanRequest?.strategy ?? s.lastStockScanStrategy ?? '');
```
- Delete `const [selected, setSelected] = useState<string | null>(activeStrategy);` and replace every `selected` with `activeStrategy` (L189, L282, L310, L330, L332, L334).
- Card `onClick={() => setActiveStrategy(s.key)}`.
- `onRun`: `if (!activeStrategy) return; … runStockScan(activeStrategy, params)`.
- `<StockPositionCard … strategyKey={scannedStrategy} />`.

- [ ] **Step 4: Run, expect PASS**; then run `scanFailureMessage`, `autoExecute.methodPickExempt`, `RunScanButton` and `searchProfile` suites:

`npm run test -- --testPathPattern="step-4-stocks|RunScanButton|searchProfile"`
Expected: PASS. If a pre-existing test set only local selection, update it to set `activeStrategy` in the store and say so in the commit body.

- [ ] **Step 5: Typecheck, commit**

```bash
npm run typecheck
git add "frontend/app/(frame)/screener/step-4-stocks/page.tsx" "frontend/app/(frame)/screener/step-4-stocks/__tests__/pickerSelection.test.tsx"
git commit -m "feat(step-4-stocks): selection is activeStrategy; position card uses the scanned strategy"
```

---

### Task 3: Step 4 panel params re-sync after scan-params hydration (F3)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (L101-110, L132)
- Test (create): `frontend/app/(frame)/screener/step-4-stocks/__tests__/paramsHydration.test.tsx`

**Interfaces:**
- Consumes: `useScanParamsStore.persist.hasHydrated()`, `.onFinishHydration(cb)`; `ScanParams` type from `lib/scanParamsStore.ts`; `StrategyParams` from `StrategyParamsPanel`.
- Produces: module-level `panelParamsOf(s: ScanParams): StrategyParams` in the page file, used by the selector, the reset and the hydration sync (one field list, not three).

- [ ] **Step 1: Write the failing test**

```tsx
import '@testing-library/jest-dom';
import { render, act, fireEvent, screen } from '@testing-library/react';
import Step4StocksPage from '../page';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';
import { runStockScan } from '@/lib/stockScan';
// (same next/navigation, @/lib/api, StockPositionCard, StockSendDialog, ScanFunnel, WatchStar mocks as pickerSelection.test.tsx)
jest.mock('@/lib/stockScan', () => ({ ...jest.requireActual('@/lib/stockScan'), runStockScan: jest.fn(() => Promise.resolve(null)) }));

it('a scan run after hydration finishes uses the persisted params, not the pre-hydration defaults', async () => {
  let finish: (() => void) | undefined;
  const persist = useScanParamsStore.persist;
  const hasHydrated = jest.spyOn(persist, 'hasHydrated').mockReturnValue(false);
  const onFinish = jest.spyOn(persist, 'onFinishHydration').mockImplementation((cb) => {
    finish = () => cb(useScanParamsStore.getState());
    return () => {};
  });
  try {
    useScanStore.setState({ activeStrategy: 'pullback_ema', scanState: 'IDLE' } as never);
    render(<Step4StocksPage />);
    act(() => { useScanParamsStore.setState({ pullbackEmaPeriod: 34 }); finish!(); });
    fireEvent.click(screen.getByRole('button', { name: 'Run Stock Scan' }));
    expect(runStockScan).toHaveBeenCalledWith('pullback_ema', expect.objectContaining({ pullbackEmaPeriod: 34 }));
  } finally {
    hasHydrated.mockRestore();
    onFinish.mockRestore();
  }
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `npm run test -- --testPathPattern=step-4-stocks/__tests__/paramsHydration`
Expected: FAIL — `pullbackEmaPeriod` is the value captured at first render.

- [ ] **Step 3: Implement**

```tsx
import { useScanParamsStore, type ScanParams } from '@/lib/scanParamsStore';

/** The panel's slice of the saved scan params. One list, used by the
 *  selector, Reset and the post-hydration sync, so they cannot drift. */
function panelParamsOf(s: ScanParams): StrategyParams {
  return {
    pullbackTolerancePct: s.pullbackTolerancePct, pullbackEmaPeriod: s.pullbackEmaPeriod,
    pullbackTrendEma: s.pullbackTrendEma, pullbackMaType: s.pullbackMaType,
    maCrossoverFast: s.maCrossoverFast, maCrossoverSlow: s.maCrossoverSlow,
    maCrossoverLookback: s.maCrossoverLookback, breakoutVolumeMult: s.breakoutVolumeMult,
    rsiPeriod: s.rsiPeriod, rsiOversold: s.rsiOversold, rsiTrendSma: s.rsiTrendSma,
    requireChoppyRegime: s.requireChoppyRegime ?? false,
    btMinTrades: s.btMinTrades, btMinWinRate: s.btMinWinRate,
    eventFilter: s.eventFilter, stockShortlistMax: s.stockShortlistMax,
  };
}
```
In the component: `const savedParams = useScanParamsStore(useShallow(panelParamsOf));` and add, moved from Step 5 with its comment:

```tsx
  // If this page mounts before useScanParamsStore finishes rehydrating from
  // localStorage (skipHydration: true — see StoreHydration), the useState
  // initializer captures the store's module defaults instead of the persisted
  // params. Sync once hydration actually finishes (moved from Step 5, which
  // fixed this as Critical finding #8, 2026-07-15 audit).
  useEffect(() => {
    const sync = () => setParams(panelParamsOf(useScanParamsStore.getState()));
    if (useScanParamsStore.persist.hasHydrated()) sync();
    return useScanParamsStore.persist.onFinishHydration(sync);
  }, []);
```
If `ScanParams` does not include every field `panelParamsOf` reads (e.g. the selector type is the store state, not `ScanParams`), use the store's state type instead — check `lib/scanParamsStore.ts` exports first; do not cast.

- [ ] **Step 4: Run, expect PASS**; run all `step-4-stocks` tests.

- [ ] **Step 5: Typecheck, commit**

```bash
npm run typecheck
git add "frontend/app/(frame)/screener/step-4-stocks/page.tsx" "frontend/app/(frame)/screener/step-4-stocks/__tests__/paramsHydration.test.tsx"
git commit -m "fix(step-4-stocks): re-sync panel params when scan params finish hydrating (moved from Step 5)"
```

---

### Task 4: Pre-warm history row on Step 4 (F4)

**Files:**
- Create: `frontend/app/(frame)/screener/step-4-stocks/HistoryPrefetchRow.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (render it under the Run row), `page.module.css`
- Test (create): `frontend/app/(frame)/screener/step-4-stocks/__tests__/historyPrefetch.test.tsx`

**Interfaces:**
- Consumes: `api.startHistoryPrefetch({ universe })`, `api.getHistoryPrefetchStatus()` → `{ status, done, total }`, `getLastDataRefresh()` → `{ last_refresh }`, `useScanStore` `context.universe`.
- Produces: `export function HistoryPrefetchRow(): JSX.Element` — no props.

- [ ] **Step 1: Write the failing test**

```tsx
import '@testing-library/jest-dom';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { HistoryPrefetchRow } from '../HistoryPrefetchRow';
import { useScanStore } from '@/lib/scanStore';
import { api, getLastDataRefresh } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: { startHistoryPrefetch: jest.fn(() => Promise.resolve()), getHistoryPrefetchStatus: jest.fn() },
  getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: '2026-10-03T22:00:00Z' })),
  API_BASE_URL: 'http://localhost:8000',
}));

beforeEach(() => {
  jest.useFakeTimers();
  useScanStore.setState({ context: { universe: 'NDX100', direction: 'Bullish', horizon: 'Swing (5–15d)' } } as never);
});
afterEach(() => jest.useRealTimers());

it('shows not pre-warmed and the last refresh, then warms the context universe and polls to ready', async () => {
  (api.getHistoryPrefetchStatus as jest.Mock)
    .mockResolvedValueOnce({ status: 'running', done: 3, total: 100 })
    .mockResolvedValueOnce({ status: 'completed', done: 100, total: 100 });
  render(<HistoryPrefetchRow />);
  expect(screen.getByText(/not pre-warmed/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText(/Last refresh:/)).toBeInTheDocument());
  expect(getLastDataRefresh).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole('button', { name: 'Pre-warm history' }));
  await waitFor(() => expect(api.startHistoryPrefetch).toHaveBeenCalledWith({ universe: ['NDX100'] }));
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(await screen.findByText(/warming up 3\/100/)).toBeInTheDocument();
  await act(async () => { jest.advanceTimersByTime(5_000); });
  expect(await screen.findByText(/Historical data:.*ready/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Re-warm' })).toBeInTheDocument();
});

it('stops polling on unmount', async () => {
  (api.getHistoryPrefetchStatus as jest.Mock).mockResolvedValue({ status: 'running', done: 1, total: 9 });
  const { unmount } = render(<HistoryPrefetchRow />);
  fireEvent.click(screen.getByRole('button', { name: 'Pre-warm history' }));
  await waitFor(() => expect(api.startHistoryPrefetch).toHaveBeenCalled());
  unmount();
  await act(async () => { jest.advanceTimersByTime(20_000); });
  expect(api.getHistoryPrefetchStatus).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run, expect FAIL** (module not found).

- [ ] **Step 3: Implement** — `HistoryPrefetchRow.tsx` is Step 5's `prefetchStatus`/`prefetchProgress`/`prefetchPollRef`/`lastRefreshTs` state, its two `useEffect`s, `startPrefetch()` and the `prefetchRow` JSX (`step-5-strategy/page.tsx:190-209, 271-291, 361-387`), moved **verbatim** apart from: `'use client';` at the top, reading `context` via `useScanStore((s) => s.context)`, and importing `styles` from `./page.module.css`. Append to `step-4-stocks/page.module.css` the `.prefetchRow`, `.prefetchLeft`, `.prefetchBtn`, `.prefetchBtn:hover` rules verbatim from `step-5-strategy/page.module.css:19-47`. In `page.tsx`, render `<HistoryPrefetchRow />` directly after the closing `</div>` of `styles.runRow`.

- [ ] **Step 4: Run, expect PASS**; run all `step-4-stocks` tests (their `@/lib/api` mocks now need `getLastDataRefresh` — the existing `scanFailureMessage` and `autoExecute.methodPickExempt` tests: add `getLastDataRefresh: jest.fn(() => Promise.resolve({ last_refresh: null }))` and the two `api` fns to their `@/lib/api` mock if they mock it, or mock `../HistoryPrefetchRow` to `() => null` if they don't).

- [ ] **Step 5: Typecheck, commit**

```bash
npm run typecheck
git add "frontend/app/(frame)/screener/step-4-stocks/"
git commit -m "feat(step-4-stocks): Pre-warm history row (moved from Step 5)"
```

---

### Task 5: Port the remaining Step 5 pins (F11)

**Files:**
- Create: `frontend/lib/__tests__/stockScanRequestPins.test.ts`
- Move: `step-5-strategy/__tests__/p3aScanSizing.test.tsx` → `frontend/lib/__tests__/p3aScanSizing.test.tsx`

- [ ] **Step 1: `stockScanRequestPins.test.ts`** — copy `a5bSharedRequest.test.tsx` and change:
  - Drop the `Step5` import, `next/navigation` mock, `STRATEGY_LABELS`, `strategyButton`, `step5Body` and **T1** (there is one path now; parity is structural).
  - Keep `STEP3`, `reset()`, `step34Body()`; replace every `await step5Body(key)` with `await step34Body(key)`.
  - **T4** becomes: `const b = await step34Body('pullback_ema', { pullbackEmaPeriod: 34 }); expect(useScanParamsStore.getState().pullbackEmaPeriod).toBe(21); expect(b.pullback_ema_period).toBe(34);` — the overrides argument is how Step 4 passes the panel's unsaved edits (`runStockScan(activeStrategy, params)`).
  - Header comment: "A5b literal pins, moved from step-5-strategy on its removal (STOCKS-STEP-MERGE-S1)".

- [ ] **Step 2: `p3aScanSizing`**

```bash
git mv "frontend/app/(frame)/screener/step-5-strategy/__tests__/p3aScanSizing.test.tsx" frontend/lib/__tests__/p3aScanSizing.test.tsx
```
Then: replace `import Step5 from '../page';` with `import Step4StocksPage from '@/app/(frame)/screener/step-4-stocks/page';` and `import PreBreakout from '../../step-4-prebreakout/page';` with `import PreBreakout from '@/app/(frame)/screener/step-4-prebreakout/page';` (confirm the `@/` alias resolves `app/` in `jest.config` first; otherwise use the relative path `../../app/(frame)/screener/...`). Add the heavy-child mocks (`StockPositionCard`, `StockSendDialog`, `ScanFunnel`, `WatchStar`, `../HistoryPrefetchRow` path as resolved from this file). Rename `describe('Step 5', …)` to `describe('Step 4 Stocks', …)`; its `pick` becomes "click the Breakout card, then click `Run Stock Scan`"; the 0% case expects `findByText(\`Scan failed — ${SCAN_RISK_ZERO_MESSAGE}\`)`. Update the file header's path list ("Steps 3/4 runStockScan, Step 4 Stocks page, Analysis, Pre-Breakout").

- [ ] **Step 3: Run both, expect PASS**

`npm run test -- --testPathPattern="stockScanRequestPins|p3aScanSizing"`

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/__tests__/stockScanRequestPins.test.ts frontend/lib/__tests__/p3aScanSizing.test.tsx
git commit -m "test: move Step 5's request and sizing pins onto runStockScan / Step 4"
```

---

### Task 6: Remove Step 5 from the Stocks path (Q6, Q7, F8, F9, F12)

**Files:**
- Modify: `frontend/components/organisms/Stepper/index.tsx:32-40`, `Stepper/__tests__/Stepper.test.tsx:36-45`
- Replace: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`
- Delete: `step-5-strategy/page.module.css`, `step-5-strategy/__tests__/a5bSharedRequest.test.tsx`, `a5dReadableScanError.test.tsx`
- Modify: header/empty-state text in `step-4-stocks/page.tsx:264-271`, `step-6-backtest/page.tsx:83,111`, `step-7-position-card/page.tsx:118,186`
- Test (create): `frontend/app/(frame)/screener/step-5-strategy/__tests__/redirect.test.ts`

- [ ] **Step 1: Failing tests** — in `Stepper.test.tsx`'s `SCREENER_STEPS_STOCKS` block:

```ts
    expect(SCREENER_STEPS_STOCKS).toHaveLength(6);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.slug)).toEqual([
      'step-1-regime', 'step-2-universe', 'step-3-direction',
      'step-4-stocks', 'step-6-backtest', 'step-7-position-card',
    ]);
    expect(SCREENER_STEPS_STOCKS.map((s) => s.index)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(SCREENER_STEPS_STOCKS[3].label).toBe('Strategy');
```
and `step-5-strategy/__tests__/redirect.test.ts`:

```ts
import { redirect } from 'next/navigation';
import Step5Redirect from '../page';
jest.mock('next/navigation', () => ({ redirect: jest.fn() }));

it('sends the retired Step 5 URL to the Stocks strategy step', () => {
  Step5Redirect();
  expect(redirect).toHaveBeenCalledWith('/screener/step-4-stocks');
});
```

- [ ] **Step 2: Run, expect FAIL.**

- [ ] **Step 3: Implement**

`Stepper/index.tsx`:
```ts
export const SCREENER_STEPS_STOCKS: ScreenerStep[] = [
  { index: 1, slug: 'step-1-regime',        label: 'Market Regime' },
  { index: 2, slug: 'step-2-universe',      label: 'Universe'      },
  { index: 3, slug: 'step-3-direction',     label: 'Direction'     },
  { index: 4, slug: 'step-4-stocks',        label: 'Strategy'      },
  { index: 5, slug: 'step-6-backtest',      label: 'Backtest'      },
  { index: 6, slug: 'step-7-position-card', label: 'Position'      },
];
```
Before this edit, grep for any consumer that derives a step from its **slug number** rather than `index` (`grep -rn "slug.match\|step-(\\\\d" frontend/components frontend/lib frontend/app`) and list them in the commit body; the gate uses `index === 4`, which still resolves to `step-4-stocks`.

`step-5-strategy/page.tsx` (whole file, server component):
```tsx
import { redirect } from 'next/navigation';

/** Step 5 (Strategy) was merged into Step 4 (decision STOCKS-STEP-MERGE-2026-10-04).
 *  The route stays so old links and bookmarks land on the picker. In Options or
 *  Pre-Breakout mode, ScreenerStepGate then bounces step-4-stocks to that
 *  mode's own step 4. */
export default function Step5Redirect(): never {
  redirect('/screener/step-4-stocks');
}
```

Text changes:
- `step-4-stocks`: `STEP 4 OF 6`; `Title` → `Strategy`; subtitle unchanged.
- `step-6-backtest`: `STEP 5 OF 6`; empty state → `No stock scan result. Go back to Step 4 (Strategy) and run a scan.`
- `step-7-position-card`: `STEP 6 OF 6`; empty state → `No passing candidates. Go back to Step 5 (Backtest).`

Delete the two Step 5 tests and the CSS:
```bash
git rm "frontend/app/(frame)/screener/step-5-strategy/page.module.css" "frontend/app/(frame)/screener/step-5-strategy/__tests__/a5bSharedRequest.test.tsx" "frontend/app/(frame)/screener/step-5-strategy/__tests__/a5dReadableScanError.test.tsx"
```

- [ ] **Step 4: Run** `npm run test -- --testPathPattern="Stepper|ScreenerStepGate|step-5-strategy|StepNavBar"` → PASS. Then full `npm run typecheck` and `npm run test`; grep the remaining tests for `step-5-strategy` and `STEP 5 OF 7`/`STEP 6 OF 7`/`STEP 7 OF 7` in Stocks pages and fix any assertion that pinned the old text.

- [ ] **Step 5: Commit**

```bash
git add -A "frontend/components/organisms/Stepper" "frontend/app/(frame)/screener"
git commit -m "feat(screener): Stocks path is 6 steps; Step 5 redirects to the Step 4 strategy picker"
```

---

### Task 7: Records and docs

**Files:**
- Modify: `docs/superpowers/PROJECT_STATE.json`, `CLAUDE.md`, `frontend/lib/searchProfileSnapshot.ts` (comments L39-44, L96-99), `frontend/components/organisms/JournalEntryForm/index.tsx` (comment L17)

- [ ] **Step 1: Re-point the two probes (F10)** — do not delete history:
  - `A5B-STEP5-SHARED-REQUEST.verify` → `{"kind":"present","path":"frontend/lib/stockScan.ts","pattern":"buildStockScanRequestBody\\(\\{","note":"PRESENCE ONLY. Re-pointed 2026-10-04 (STOCKS-STEP-MERGE-S1): Step 5 was merged into Step 4, so runStockScan is the only manual Stocks path. Behavioural pins: lib/__tests__/stockScanRequestPins.test.ts."}`
  - `A5D-STEP5-READABLE-SCAN-ERROR.verify` → `{"kind":"present","path":"frontend/lib/stockScan.ts","pattern":"settingsUnreadable \\? STOCK_SCAN_SETTINGS_INVALID","note":"PRESENCE ONLY. Re-pointed 2026-10-04 (STOCKS-STEP-MERGE-S1): moved into runStockScan. Behavioural pins: lib/__tests__/stockScan.test.ts ('a throw while building the request'), step-4-stocks/__tests__/readableScanError.test.tsx."}`
  - `STOCKS-STEP-MERGE-S1.status` → `in_progress` (built, not yet code-audited; `shipped` only after merge with `audit_clean: true`).

- [ ] **Step 2: `CLAUDE.md`** — folder layout: drop the `step-5-strategy/` line and change `step-4-stocks/` to `# [Stocks mode] Strategy picker + scan + results table, StockPositionCard`; Stocks path table: step 4 = `step-4-stocks` "Strategy picker (7 strategies, StrategyParamsPanel, Pre-warm history) + Run + results table, StockPositionCard, StockSendDialog", remove the step-5 row, renumber Backtest to 5 and Position to 6; the `strategy_engine` row: "the 7 exposed by the `step-4-stocks` picker"; the Screener workflow intro: "Options continues through steps 4–7; Stocks through steps 4–6".

- [ ] **Step 3: Comments** — `searchProfileSnapshot.ts` and `JournalEntryForm`: "Step 5" / `step-5-strategy` → "Step 4" / `step-4-stocks` (comments only).

- [ ] **Step 4: Verify and commit**

```bash
python3 scripts/state.py
```
Expected: exit 0, no drift.
```bash
git add docs/superpowers/PROJECT_STATE.json CLAUDE.md frontend/lib/searchProfileSnapshot.ts frontend/components/organisms/JournalEntryForm/index.tsx
git commit -m "docs: Stocks path is 6 steps; re-point A5b/A5d probes to runStockScan"
```

---

### Task 8: Verify in the running app, then the CODE audit

- [ ] **Step 1:** `npm run typecheck` and `npm run test` from `frontend/` — record the suite/test counts.
- [ ] **Step 2:** Run the app (`run` skill / `.claude/launch.json`) and check by hand, in Stocks mode:
  1. The stepper shows 6 steps; Step 4 reads "STEP 4 OF 6 — Strategy".
  2. Clicking a card highlights it without scanning; the floating Run button on Step 3 then runs that strategy.
  3. Run Stock Scan works; results, inline card, auto-execute toggle and Send basket behave as before.
  4. After a scan, select a different card, open a row: the card's "Watch SYMBOL — strategy" button names the **scanned** strategy.
  5. `/screener/step-5-strategy` lands on Step 4 (Stocks) and on step-4-ranking (Options).
  6. Pre-warm history starts and its status updates.
  7. In devtools, set `bamendjou-settings` → `confidenceGate: null`, reload, Run: the message is "Scan failed — Couldn't read your saved scan settings…". Restore the setting.
- [ ] **Step 3:** `python3 scripts/state.py` exit 0; `python3 scripts/claim.py renew` if > 2 h.
- [ ] **Step 4: CODE audit** — `K-adversarial-audit-loop` on the diff `main..claude/stocks-step-merge-s1` with a fresh subagent applying `bmad-review-adversarial-general`, briefed on the gate. Record reviewer, diff range, findings, fixes in `STOCKS-STEP-MERGE-S1`. Cap 3 code rounds. `audit_clean: true` only after a zero-gate-finding round.
- [ ] **Step 5:** Only when clean: open the PR to `main`, then `python3 scripts/claim.py release STOCKS-STEP-MERGE-S1`. Stage 2 gets its own plan.

---

## Self-review (done while writing)

- **Spec coverage:** Q1 (stage split) — Global Constraints + Task 0; Q2 — Tasks 1, 3, 4; Q3 — unchanged Step 4 behaviour, pinned by Task 2 test 1; Q4 — Step 4 already conditional (L310), kept; Q5 — Task 2; Q6 — Task 6; Q7 — Task 6 redirect; Q8–Q12 — recorded in Task 0 for Stage 2, explicitly out of scope here. Kenneth's "lose nothing": every Step-5-only item in F2–F4 has a task; Step 5's "always-visible multi panel" is intentionally changed by Q4; Step 5's click-to-run is intentionally changed by Q3; Step 5's auto-navigation to Backtest is intentionally deferred to Stage 2 (Q8).
- **Known behaviour change beyond the decisions:** the readable settings message now also reaches the Step 1–3 floating Run button's toast (it shares `runStockScan`). It is the same message Step 5 already showed, on the same condition.
- **Placeholders:** none. Three steps say "check X first" (riskStore default, `PositionCardData` fields, `@/` alias for `app/`); each names the file to read and what to do with the answer.
- **Type/name consistency:** `panelParamsOf`, `HistoryPrefetchRow`, `scannedStrategy`, `settingsUnreadable`, `building` are each defined once and used under the same name; the Task 7 probe pattern `settingsUnreadable \? STOCK_SCAN_SETTINGS_INVALID` matches the Task 1 code line.
