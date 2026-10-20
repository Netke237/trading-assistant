# E2E Coverage Plan — Mocked 7-Step Screener Flow & RANK-Basis Volatility (#175, #176)

**Phase IDs:** `DECISION-25-DISABLED-E2E`, `DECISION-27-RANK-COVERAGE`
**Branch:** `board/decision-25-disabled-e2e-e4cf6675`
**Tracking Issues:** #175, #176 (built together in single PR per Board #151 item 15)
**Touches:** `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts`, `frontend/e2e/tests/iv-basis-rendering.spec.ts`

---

## 1. Goal

1. **#175 Disabled E2E**:
   - Rewrite Test 1 in `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` (`full 7-step screener flow — AAPL candidate`) from `test.fixme` to an active `@smoke` test reflecting the current step order (Step 1: Regime, Step 2: Universe, Step 3: Direction, Step 4: Ranking, Step 5: Vol/Events, Step 6: Contracts, Step 7: Trade Card).
   - Remove obsolete Test 2 in `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` (`Step 3 scan log shows all-passed state when no rejections`), per Kenneth's approved recommendation 2A (the badge grid is covered by `ws-c-scan-log-regime-gate.spec.ts`).

2. **#176 RANK-Basis E2E**:
   - Add a mocked `@smoke` test to `frontend/e2e/tests/iv-basis-rendering.spec.ts` validating that when a candidate and contracts carry a non-null `ivRank` (true percentile), Steps 5 and 6 display the figure under "IV rank" with the `'rank'` suffix, the Step 5 threshold sentence quotes the rank threshold set (`IV rank ≤ 34 → PASS`), and Step 6 column header renders `'IV RANK'`.

---

## 2. Design & Implementation Details

### Task 1: Add RANK-basis coverage in `frontend/e2e/tests/iv-basis-rendering.spec.ts` (#176)

- In `frontend/e2e/tests/iv-basis-rendering.spec.ts`:
  - Define `seedCompletedRankScan(page: Page)` helper (or parameterize `seedCompletedScan`) where the candidate carries `ivRank: 20` and `iv: 42`.
  - Override `/api/contracts` route to return contracts with `ivRank: 20`.
  - Add test: `test('Step 5 and Step 6 render IV rank on the rank basis, and gate on the rank set', async ({ page }) => { ... })`:
    - **Step 5**:
      - Navigate to Step 5 (`new ScreenerPage(page).goto(5)`).
      - Assert `page.locator('[title^="IV rank"]')` is visible and contains `'20'` and suffix `'rank'`.
      - Assert absolute label `page.locator('[title^="Implied volatility"]')` is absent (`toHaveCount(0)`).
      - Assert gate sentence quotes the rank threshold set: `await expect(page.getByText(/IV rank ≤ 34 → PASS/)).toBeVisible();`.
      - Assert absolute sentence `await expect(page.getByText(/^IV ≤ \d+ → PASS/)).toHaveCount(0);`.
    - **Step 6**:
      - Navigate to Step 6 (`new ScreenerPage(page).goto(6)`).
      - Assert the column header reads `'IV RANK'` (via `ivColumnLabel(['rank'])`).
      - Assert per-contract cells display the rank figure with suffix `'rank'` and title starting with `'IV rank'`.

### Task 2: Rewrite Happy-Path Mocked E2E Flow in `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` (#175)

- In `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts`:
  - Update `test.fixme('full 7-step screener flow — AAPL candidate', ...)` to `test('full 7-step screener flow — AAPL candidate', ...)`:
    - **Step 1: Regime** (`/screener/step-1-regime`):
      - `await screener.goto(1);`
      - `await expect(page).toHaveURL(/step-1-regime/);`
      - `await screener.clickNext();`
    - **Step 2: Universe** (`/screener/step-2-universe`):
      - `await expect(page).toHaveURL(/step-2-universe/);`
      - Select S&P 500 universe tile (`await screener.selectUniverse('S&P 500');`).
      - `await screener.clickNext();`
    - **Step 3: Direction** (`/screener/step-3-direction`):
      - `await expect(page).toHaveURL(/step-3-direction/);`
      - Select Bullish direction (`await screener.selectDirection('Bullish');`).
      - Run scan:
        ```ts
        const scanResponsePromise = page.waitForResponse(
          (res) => res.url().includes('/api/scan') && res.request().method() === 'POST',
          { timeout: 8000 },
        );
        await screener.clickRunScan();
        await scanResponsePromise;
        ```
      - Assert scan completes.
      - `await screener.clickNext();`
    - **Step 4: Ranking** (`/screener/step-4-ranking`):
      - `await expect(page).toHaveURL(/step-4-ranking/);`
      - Assert candidate `AAPL` is visible in table.
      - `await screener.clickNext();`
    - **Step 5: Vol / Events** (`/screener/step-5-vol-events`):
      - `await expect(page).toHaveURL(/step-5-vol-events/);`
      - Assert candidate `AAPL` and absolute IV 42.0% (default mocked fixture) are visible.
      - `await screener.clickNext();`
    - **Step 6: Contracts** (`/screener/step-6-contracts`):
      - `await expect(page).toHaveURL(/step-6-contracts/);`
      - Assert contract row / group header for AAPL is visible.
      - `await screener.clickNext();`
    - **Step 7: Trade Card** (`/screener/step-7-trade-card`):
      - `await expect(page).toHaveURL(/step-7-trade-card/);`
      - Assert Trade Card heading and candidate AAPL are visible.
  - Delete obsolete `test.fixme('Step 3 scan log shows all-passed state when no rejections')`.

---

## 3. Verification & Acceptance Criteria

- [ ] `cd frontend && npx playwright test tests/iv-basis-rendering.spec.ts tests/ws-g-happy-path-mocked.spec.ts` passes with 0 failures and 0 skipped/fixme tests.
- [ ] `cd frontend && npm run typecheck` passes with 0 errors.
- [ ] `cd frontend && npm run test` passes.
- [ ] `python scripts/state.py` passes with no drift.
- [ ] Independent plan audit clean (cap 3).
- [ ] Independent code audit clean (cap 3).
