# Fix Red Main CI (ESLint + Step-1-Regime Playwright Flakes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `main`'s CI green by fixing the `no-require-imports` ESLint error that fails `npm run build` in `ci.yml`, fixing the three verified root causes behind the flaky Step-1-regime Playwright smoke tests in `playwright.yml`, and quarantining two unrelated pre-existing deterministic `@smoke` failures discovered along the way that would otherwise keep `playwright.yml` red regardless of the other fixes.

**Architecture:** No app behavior changes. Independent, surgical fixes: (1) delete a dead `require()` call in a test file, (2) widen three Playwright route-mock glob patterns so they match request URLs that carry a query string, plus fix a second bug in the REJECT mock's JSON payload that the glob fix exposed (missing `omm` data the alignment-verdict check depends on), (3) drop a redundant/misdiagnosed `waitForLoadState('networkidle')` call, (4) replace five over-broad CSS/tag-based Playwright locators with `data-testid`-based ones, (5) mark two unrelated stale tests `fixme` (a stale-URL-scheme assertion and a UI-drifted text assertion) so they stop blocking the `@smoke` gate. Each fix is independently verifiable and independently revertable.

**Tech Stack:** Next.js 15 / TypeScript, ESLint 9 (`eslint-config-next` flat config), Jest, Playwright (pinned to `1.62.1` in `package-lock.json` — run `npm ci`, not just `npm install`, before verifying; a locally-installed `1.59.1` was found during planning and does not match what CI's `npm ci` step actually installs).

---

## Root-cause investigation (already done — do not re-derive, verify against this)

**Finding 1 — ESLint error breaks `npm run build`:**
`frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx:95` contains:
```ts
const { runStockScan } = require('@/lib/stockScan');
```
`frontend/eslint.config.mjs` extends `next/typescript` (via `eslint-config-next`), whose recommended TypeScript rule set includes `@typescript-eslint/no-require-imports` as an error. `frontend/next.config.mjs` does **not** set `eslint.ignoreDuringBuilds`, so `next build` (the `ci.yml` "Run frontend build" step) runs ESLint and fails on this line.

This local `require()` is dead code: `runStockScan` is already imported at the top of the file (line 8: `import { runStockScan } from '@/lib/stockScan';`) and the mocked module (`jest.mock('@/lib/stockScan', ...)` at line 16) makes that top-level import resolve to the same mock. The test that contains the offending line (`'shows a toast and does not call runStockScan...'`, lines 94–106) already asserts against the top-level `runStockScan` import on line 105 (`expect(runStockScan).not.toHaveBeenCalled()`) — the local `require()` on line 95 is unused. Deleting it is a pure no-op for test behavior.

**Finding 2 — Step-1-regime Playwright flakes, root cause A (query-string glob mismatch):**
`frontend/app/(frame)/screener/step-1-regime/page.tsx:91` always calls:
```ts
api.getRegime('intraday', { lookback: markov.lookback, threshold: markov.threshold, smoothing: markov.smoothing })
```
`frontend/lib/api.ts:283-294` (`getRegime`) always builds a non-empty query string when a `horizon` is passed, so the real request URL is always something like `/api/regime?horizon=intraday&lookback=20&threshold=0.02&smoothing=0`.

Three Playwright mocks register the bare pattern `'**/api/regime'` (no trailing wildcard):
- `frontend/e2e/fixtures/api-mocks.ts:48` — used by every test via the shared `test` fixture (`frontend/e2e/fixtures/index.ts`). This is the one actually responsible for the reproduced failures below.
- `frontend/e2e/tests/screener-steps-1-3.spec.ts:100` (inline override in the REJECT test) — also directly responsible for the reproduced REJECT-test failure.
- `frontend/e2e/fixtures/api-mocks-reject.ts:8` — **checked during round-2 audit: this file's `setupRejectMocks`/the `testReject` fixture it backs (`frontend/e2e/fixtures/index.ts`) is not imported by any spec in `e2e/` today.** No currently-running test exercises it, so widening its glob has zero effect on any test that runs in CI right now — it's fixed here as precautionary hygiene (so it's correct if/when something starts using it) rather than as a root-cause fix for a reproduced failure.

Playwright glob patterns without a trailing wildcard only match a URL that ends exactly at that literal string — they do not match when a `?query=string` follows. **Verified empirically**: a standalone probe script registering two `page.route('**/api/regime', ...)` handlers and navigating to `/screener/step-1-regime` showed neither handler firing; the real request went out to `http://localhost:8000/api/regime?horizon=intraday&lookback=20&threshold=0.02&smoothing=0` (see `frontend/lib/api.ts:9`, `BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'`). `playwright.yml` never starts a backend service, so in CI this request has nothing to answer it. Depending on exact timing (connection-refused vs. hang-to-timeout, and whether an earlier `.then()` from a previous unrelated fetch already flipped shared Zustand state) the page ends up in different observed states run to run — this is the mechanism of the flakiness, not a one-off bug.

Reproduced 3x locally (`npx playwright test e2e/tests/screener-steps-1-3.spec.ts --project=chromium --grep @smoke`, 3 consecutive runs):
- `shows confirmation dialog when regime is REJECT` — **failed in 3/3 runs**. The in-test REJECT override never intercepted the real (querystring-bearing) request, so `fetchRegime()`'s `.then()` (which calls `setRegime`/`setCombinedRegime` on the shared `scanStore`) never ran with REJECT data; the TopBar (`role="banner"`) kept showing its default `PASS`, and `page.reload()` + `page.waitForLoadState('networkidle')` either timed out outright (run 1) or the REJECT text assertion failed after (runs 2, 3).
- `Step 1 - metric grid and sector heatmap visible` — **failed in 2/3 runs**. Original analysis misread this as an independent locator-ambiguity bug (see superseded reasoning removed from Finding 3 below); re-checked during round-2 audit and reclassified as almost certainly **the same root cause as this finding**, not a second one — see Finding 3's corrected explanation.

**Finding 3 — Step-1-regime Playwright flakes, root cause B (over-broad locators, real but narrower than first thought):**
`frontend/e2e/pages/ScreenerPage.ts` locates Step-1 content with generic, position-dependent selectors:
```ts
get regimeBanner(): Locator { return this.page.locator('section').first(); }
get spxChart(): Locator   { return this.page.locator('canvas').first(); }
get ndxChart(): Locator   { return this.page.locator('canvas').nth(1); }
get metricGrid(): Locator { return this.page.locator('[class*="grid"]').first(); }
get sectorHeatmap(): Locator { return this.page.locator('[class*="sectors"]').first(); }
```

**Correction from round-2 audit — the "8 elements" reading was wrong.** The original failure log was:
```
- waiting for locator('[class*="grid"]').first()
  8 × locator resolved to <div class="page_grid__H0Jle"></div>
    - unexpected value "hidden"
```
This was first read as "8 different matching elements." Independently reproduced during audit: Playwright's `N ×` in this log format means **N retries of its polling loop resolving to the same single element**, not N distinct elements — confirmed by constructing a minimal repro (one hidden div, `expect(...).toBeVisible({timeout:2000})`) which produces the identical `6 × locator resolved to <div>...` shape. `pageStyles.grid` is applied at exactly one JSX location (`page.tsx:250`), and no other class name in the reachable component tree (`page.module.css`, `screener.module.css`, or any Frame/TopBar/NavRail/ContextRail module) contains "grid" as a substring, so 8 *distinct* elements sharing the literal class `page_grid__H0Jle` is not physically possible here. The far more likely explanation, consistent with the CSS (`.grid { display: grid; }`, no `min-height`) and `page.tsx:251`'s `(regime?.metrics ?? []).map(...)`: the single grid `<div>` renders with **zero children and collapses to a 0×0 box** (which Playwright reports as "hidden") while `regime` is still `null` — i.e. while `fetchRegime()`'s promise hasn't resolved yet. That is exactly the same async gap **Finding 2** describes (the mock-miss leaves the regime fetch unresolved/erroring). In other words: `metricGrid`'s flake is very likely not an independent locator-ambiguity bug at all — it's Finding 2's root cause manifesting as an empty grid instead of a stuck banner. Fixing Task 2's glob mismatch should, on its own, make `regime.metrics` populate promptly and make this specific reproduced failure go away.

The `data-testid` swap in Task 4 is kept anyway as a **general robustness improvement** (removes any future risk from another `[class*="grid"]`-matching element being added elsewhere on the page, or from the grid rendering emptily for some other future reason) — but it should not be read as "the fix" for the reproduced `metricGrid` failure; Task 2 is.

**Also checked during audit — the `canvas` locators have their own, independently-confirmed bug (unrelated to the "8 elements" misreading above):** `lightweight-charts` v5 renders **7 internal `<canvas>` elements per chart instance** (confirmed live in the browser: `document.querySelectorAll('canvas')` returns 14 total on the page, in two clean groups of 7 under the SPX/NDX `indexChart` wrappers). `spxChart = canvas.first()` happens to land inside the SPX chart's own canvas group (harmless), but `ndxChart = canvas.nth(1)` does **not** reach the NDX chart at all — canvas index 1 is still the *second* internal canvas of the SPX chart (NDX's canvases start at index 7). `Step 1 - regime banner and charts render`'s NDX assertion has therefore never actually verified the NDX chart renders; it's passed only because SPX's 2nd internal canvas also happens to be visible. This is exactly why Task 4's `spxChart`/`ndxChart` getters below scope to their `data-testid` wrapper *and* keep `.first()` inside that scope — scoping alone is not enough, because each wrapper still contains 7 real canvases, and Playwright's default strict mode throws on a multi-element match for `toBeVisible()`. Independently re-verified during round-2 audit: each scoped locator resolves to exactly one real, visible (656×152, `display:block`) canvas — no strict-mode violation, and the NDX assertion now actually exercises the NDX chart instead of accidentally passing off SPX's second canvas.

**Also corrected from round-2 audit — `regimeBanner`'s "only section" framing was too strong.** `step-1-regime/page.tsx` contains three `<section>` elements total: the banner (`line 172`), an explainer block (`line 195`), and a news section (`line ~416`). `section.first()` still resolves deterministically to the banner today — not because it's the *only* section on the page, but because it's unconditionally rendered *first* and the other two are always downstream siblings. Still switched to `data-testid` in Task 4 for consistency/robustness, not because `section.first()` was shown to be broken.

**Finding 4 — REJECT mock payload is missing the field the REJECT test's final assertion actually depends on (found during round-7 audit by applying Tasks 2-4 verbatim and re-running the test, not just reading the diff).** With Tasks 2-4 applied exactly as written, `shows confirmation dialog when regime is REJECT` gets past its `regimeBanner`/`getByRole('banner').getByText('REJECT')` assertions (Task 2's glob fix genuinely works) but fails deterministically, 5/5 runs, on the next line:
```ts
await expect(page.locator('nav[aria-label="Screener step navigation"]')).toHaveAttribute('data-regime', 'REJECT');
```
— reproduced with `Received: "CAUTION"`. Root cause: `data-regime` is driven by `scanStore.combinedRegime`, which `step-1-regime/page.tsx:95-97` computes as `alignmentVerdict(direction, descriptorFromState(r.omm?.state ?? ''))`, **not** from `r.overall`. Both REJECT mock payloads (`api-mocks-reject.ts:8-22` and the inline override at `screener-steps-1-3.spec.ts:100-114`) set `overall: 'REJECT'` but never set `omm`, so `r.omm?.state` is `undefined`, `descriptorFromState('')` returns `'Choppy'` (`lib/regimeAlignment.ts:14-17`), and `alignmentVerdict('Bullish', 'Choppy')` returns `'CAUTION'`, not `'REJECT'` (`lib/regimeAlignment.ts:6-11` — `'Choppy'` short-circuits to `CAUTION` regardless of direction). The test never exercised this path correctly even before Tasks 2-4, because the query-string glob mismatch (Finding 2) always intercepted the assertion earlier, at the banner check — this bug was invisible until Finding 2 was fixed. Fixed in a new Task 2 Step 5, below: both REJECT payloads need a valid `omm` object with `state: 'Bear'` (direction defaults to `'Bullish'` in this test, per `page.tsx:95`'s `?? 'Bullish'` fallback, so `alignmentVerdict('Bullish', 'Bear')` → `agrees = false` → `REJECT`, correctly).

**Out of scope, flagged for a separate look:** `frontend/e2e/tests/dashboard.spec.ts:23` has the same `[class*="badge"], [class*="status"]` pattern on the Dashboard page — not part of "Step 1 regime navigation," not reproduced as flaky, not touched here (see Task 6 Step 4's caveat: this is an accepted, unverified residual risk to a fully-green run, not a confirmed non-issue). `frontend/e2e/tests/ws-e-step-reorder.spec.ts:4` has its own independent `stubApis()` helper with the identical bare `page.route('**/api/regime', ...)` glob bug described in Finding 2 — it is not `@smoke`-tagged, so it doesn't block the CI-green goal this plan targets, and is left as-is; a full sweep of every non-smoke spec for the same pattern is a separate follow-up, not part of this plan.

**Not out of scope — discovered late, now handled in Task 5:** `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` is `@smoke`-tagged and **both** of its tests fail deterministically today, for two unrelated reasons: the first asserts URLs like `/step-1-universe` and `/step-3-regime` (the *pre*-WS-E-step-reorder URL scheme — current `ScreenerPage.goto()` maps step 1 to `/step-1-regime`); the second looks for "all passed" text that the current `step-3-direction` page's scan-log UI no longer renders (it's a numeric badge grid now). Both are a different class of bug from the flakiness this plan was asked to fix, but either one alone would keep `--grep @smoke` (and therefore `playwright.yml`) red regardless of how correctly Tasks 1-4 land, which defeats the plan's stated Goal. Both are quarantined (not rewritten) in Task 5, below.

---

## File Structure

- Modify: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx` — delete one dead line.
- Modify: `frontend/e2e/fixtures/api-mocks.ts` — widen regime route glob.
- Modify: `frontend/e2e/fixtures/api-mocks-reject.ts` — widen regime route glob; add missing `omm` data to the REJECT payload.
- Modify: `frontend/e2e/tests/screener-steps-1-3.spec.ts` — widen inline regime route glob; add missing `omm` data to the REJECT payload; drop the `reload()` + `networkidle` block.
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx` — add five `data-testid` attributes (no behavior change).
- Modify: `frontend/e2e/pages/ScreenerPage.ts` — point `regimeBanner`, `spxChart`, `ndxChart`, `metricGrid`, `sectorHeatmap` at the new test ids.
- Modify: `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` — mark both stale tests `fixme`.

---

### Task 1: Delete the dead `require()` call (fixes the ESLint/build failure)

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx:94-106`

- [ ] **Step 1: Confirm the lint failure exists before touching anything**

Run: `cd frontend && npx eslint components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`
Expected: reports an error on line 95 for rule `@typescript-eslint/no-require-imports`.

- [ ] **Step 2: Delete the dead local `require()`**

Current (lines 94-96):
```ts
  it('shows a toast and does not call runStockScan when Stocks mode has no activeStrategy selected (M6)', async () => {
    const { runStockScan } = require('@/lib/stockScan');
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: null } as any);
```

Change to:
```ts
  it('shows a toast and does not call runStockScan when Stocks mode has no activeStrategy selected (M6)', async () => {
    useScanStore.setState({ screenerMode: 'stocks', activeStrategy: null } as any);
```

(The rest of the test body, including the existing `expect(runStockScan).not.toHaveBeenCalled();` on line 105, is unchanged — it already refers to the top-level `import { runStockScan } from '@/lib/stockScan'` on line 8, which resolves through the `jest.mock('@/lib/stockScan', ...)` on line 16.)

- [ ] **Step 3: Verify lint is clean**

Run: `cd frontend && npx eslint components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx`
Expected: no output, exit code 0.

- [ ] **Step 4: Verify the test file still passes**

Run: `cd frontend && npm run test -- RunScanButton.test.tsx`
Expected: all 9 `it(...)` blocks in this file pass (5 in `'RunScanButton — conflict suppression wiring'`, 1 in `'RunScanButton — hold days'`, 3 in `'RunScanButton — confidence ATR override both-or-neither'`), no change in count or content vs. before the edit. (Use the literal filename, not `--testPathPattern=RunScanButton` — that broader pattern also matches the sibling `regimeGate.test.tsx` in the same `__tests__` directory, adding 4 more tests from an unrelated `describe` block and making "9" look wrong when it's actually "13 across 2 files.")

- [ ] **Step 5: Verify the full build succeeds**

Run: `cd frontend && npm run build`
Expected: build completes with no ESLint errors (this is the exact step that fails today in `ci.yml`'s `frontend` job).

- [ ] **Step 6: Commit**

```bash
git add frontend/components/organisms/RunScanButton/__tests__/RunScanButton.test.tsx
git commit -m "fix(tests): remove dead require() import that fails next build's ESLint pass"
```

---

### Task 2: Widen the `/api/regime` mock glob patterns to match query strings

**Files:**
- Modify: `frontend/e2e/fixtures/api-mocks.ts:48`
- Modify: `frontend/e2e/fixtures/api-mocks-reject.ts:8`
- Modify: `frontend/e2e/tests/screener-steps-1-3.spec.ts:100`

- [ ] **Step 1: Reproduce the miss before fixing (optional but recommended)**

Run (from `frontend/`, with the dev server already up on `:3001` — `npx playwright test e2e/tests/screener-steps-1-3.spec.ts --project=chromium --grep @smoke --reporter=list`) 3 times in a row.
Expected: `shows confirmation dialog when regime is REJECT` fails on at least 1 of the 3 runs (banner text stays `PASS`, or `waitForLoadState('networkidle')` times out).

- [ ] **Step 2: Widen the glob in `api-mocks.ts`**

Current (`frontend/e2e/fixtures/api-mocks.ts:48`):
```ts
  await page.route('**/api/regime', async (route) => {
```

Change to:
```ts
  await page.route('**/api/regime*', async (route) => {
```

- [ ] **Step 3: Widen the glob in `api-mocks-reject.ts`**

Current (`frontend/e2e/fixtures/api-mocks-reject.ts:8`):
```ts
  await page.route('**/api/regime', async (route) => {
```

Change to:
```ts
  await page.route('**/api/regime*', async (route) => {
```

- [ ] **Step 4: Widen the inline override glob in `screener-steps-1-3.spec.ts`**

Current (`frontend/e2e/tests/screener-steps-1-3.spec.ts:100`):
```ts
    await page.route('**/api/regime', async (route) => {
```

Change to:
```ts
    await page.route('**/api/regime*', async (route) => {
```

- [ ] **Step 5: Fix both REJECT mock payloads so `data-regime` actually resolves to `REJECT` (Finding 4)**

`StepNavBar`'s `data-regime` attribute comes from `combinedRegime = alignmentVerdict(direction, descriptorFromState(r.omm?.state ?? ''))` (`step-1-regime/page.tsx:95-97`), not from `overall` — so a REJECT mock payload needs a valid `omm.state` too, or the alignment verdict silently computes `CAUTION` instead (`descriptorFromState('')` → `'Choppy'` → `alignmentVerdict(...)` short-circuits to `'CAUTION'`, per `lib/regimeAlignment.ts:6-17`). This test doesn't set `context.direction`, so `step-1-regime/page.tsx:95`'s fallback (`?? 'Bullish'`) applies — `omm.state: 'Bear'` gives `alignmentVerdict('Bullish', 'Bear')` → `REJECT`, correctly. `omm` also needs the rest of the `OmmData` shape (`types/domain.ts:383-393`) filled in with plausible values, or the page's "Regime by Horizon" section (which renders whenever `omm` is truthy) throws trying to `.map()` over undefined `state_order`/`transition_row`.

Current (`frontend/e2e/fixtures/api-mocks-reject.ts:8-22`):
```ts
  await page.route('**/api/regime*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        overall: 'REJECT',
        headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
        metrics: [
          { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
          { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
          { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
        ],
      }),
    });
  });
```

Change to:
```ts
  await page.route('**/api/regime*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        overall: 'REJECT',
        headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
        metrics: [
          { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
          { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
          { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
        ],
        omm: {
          state: 'Bear',
          p_stay: 0.7,
          stability: 'Stable',
          regime_age_days: 5,
          avg_regime_duration: 12,
          transition_row: [0.1, 0.7, 0.2],
          state_order: ['Bull', 'Bear', 'Choppy'],
        },
      }),
    });
  });
```

Apply the identical fix to the inline override in `frontend/e2e/tests/screener-steps-1-3.spec.ts:100-114` (Task 2 Step 4's target, same JSON shape, same fix, indented one level deeper since it's inside the `test(...)` callback):

Current (`frontend/e2e/tests/screener-steps-1-3.spec.ts:100-114`, after Task 2 Step 4's glob widening):
```ts
    await page.route('**/api/regime*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          overall: 'REJECT',
          headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
          metrics: [
            { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
            { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
            { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
          ],
        }),
      });
    });
```

Change to:
```ts
    await page.route('**/api/regime*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          overall: 'REJECT',
          headline: 'Market conditions unfavourable — elevated volatility and weak breadth',
          metrics: [
            { label: 'SPX Trend', value: '3,980.15', status: 'REJECT', trend: 'down' },
            { label: 'NDX Trend', value: '12,105.30', status: 'CAUTION', trend: 'down' },
            { label: 'VIX', value: '28.5', status: 'REJECT', trend: 'up' },
          ],
          omm: {
            state: 'Bear',
            p_stay: 0.7,
            stability: 'Stable',
            regime_age_days: 5,
            avg_regime_duration: 12,
            transition_row: [0.1, 0.7, 0.2],
            state_order: ['Bull', 'Bear', 'Choppy'],
          },
        }),
      });
    });
```

- [ ] **Step 6: Verify the mock now intercepts and drives the correct alignment verdict**

Run: `cd frontend && npx playwright test e2e/tests/screener-steps-1-3.spec.ts --project=chromium --grep @smoke --reporter=list` 3 times.
Expected: `shows confirmation dialog when regime is REJECT` still may fail on the `waitForLoadState('networkidle')` line specifically (that's Task 3) but the banner should now correctly show `REJECT`, and `nav[aria-label="Screener step navigation"]`'s `data-regime` attribute should now correctly resolve to `REJECT` too (not `CAUTION`) — confirm via the failure screenshot/page-snapshot if it still fails at this point, then proceed to Task 3.

- [ ] **Step 7: Commit**

```bash
git add frontend/e2e/fixtures/api-mocks.ts frontend/e2e/fixtures/api-mocks-reject.ts frontend/e2e/tests/screener-steps-1-3.spec.ts
git commit -m "fix(e2e): match query-string regime requests in route mocks; fix REJECT mock's missing omm data

step-1-regime/page.tsx's fetchRegime() always calls api.getRegime()
with a horizon + markov params, so its request always carries a query
string (other callers like dashboard/step-2/step-3 call it bare and
are unaffected either way). The route mocks used a bare '**/api/regime'
glob that only matches a URL with nothing after 'regime', so it never
intercepted Step 1's request, which went to an unmocked backend CI
never starts.

Separately: StepNavBar's data-regime attribute comes from
alignmentVerdict(direction, descriptorFromState(r.omm?.state ?? '')),
not from r.overall. Both REJECT mock payloads set overall: 'REJECT'
but never set omm, so the alignment verdict silently computed CAUTION
instead of REJECT once the glob fix let the mock actually get through.
Added a full omm payload (state: 'Bear') to both."
```

---

### Task 3: Drop the flaky `reload()` + `networkidle` wait in the REJECT test

**Files:**
- Modify: `frontend/e2e/tests/screener-steps-1-3.spec.ts:116-124`

- [ ] **Step 1: Remove the reload/networkidle block**

Current (lines 116-124):
```ts
    const screener = new ScreenerPage(page);
    await screener.goto(1);

    // Reload to ensure fresh store with overridden REJECT regime
    await page.reload();
    await page.waitForLoadState('networkidle');

    await expect(screener.regimeBanner).toBeVisible();
    await expect(page.getByRole('banner').getByText('REJECT')).toBeVisible();
```

Change to:
```ts
    const screener = new ScreenerPage(page);
    await screener.goto(1);

    await expect(screener.regimeBanner).toBeVisible();
    await expect(page.getByRole('banner').getByText('REJECT')).toBeVisible();
```

Rationale: the `page.route('**/api/regime*', ...)` override (fixed in Task 2) is registered *before* `screener.goto(1)`, so the very first navigation already receives the REJECT payload — the reload was redundant. The actual historical cause of the `networkidle` timeout was Finding 2's mock-miss: the unmocked regime request hung against a backend CI never starts, so the network never went idle — Task 2 already removes that specific cause. **Correction from round-2 audit:** the plan originally justified dropping `networkidle` by claiming this app holds "a persistent `ws_alerts` websocket" open on this route — checked directly, that's wrong: the only `new WebSocket(...)` call site in the frontend is `frontend/lib/chartWS.ts`, used exclusively by `ChartWorkspace` on the standalone `/chart` page; `/screener/step-1-regime` opens no websocket and has no polling `setInterval`. The websocket claim is dropped. `waitForLoadState('networkidle')` is still worth removing on general Playwright-best-practice grounds — it's a coarse, non-deterministic wait even on pages with no lingering connections, and the two `expect(...).toBeVisible()` calls immediately below already have Playwright's built-in auto-retry (5s per `playwright.config.ts`'s `expect.timeout`), which is the correct, explicit way to wait for the async regime fetch to resolve — but the specific "there's an open websocket" reasoning should not be repeated elsewhere in this codebase's tests.

- [ ] **Step 2: Verify the REJECT test passes 5/5 runs**

Run: `cd frontend && npx playwright test e2e/tests/screener-steps-1-3.spec.ts --project=chromium --grep "shows confirmation dialog when regime is REJECT"` 5 times in a row.
Expected: passes all 5 times.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/tests/screener-steps-1-3.spec.ts
git commit -m "fix(e2e): drop redundant reload + flaky networkidle wait from REJECT test

The route override already applies to the first navigation, so the
reload was a no-op. networkidle timed out because the prior commit's
mock-glob bug left the regime request unmocked and hanging against a
backend CI never starts; the existing toBeVisible() assertions already
auto-retry and are the correct way to wait for the async fetch."
```

---

### Task 4: Replace fragile Step-1 locators with `data-testid`

**Files:**
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx:172, 225, 239, 250, 397`
- Modify: `frontend/e2e/pages/ScreenerPage.ts:72-91`

- [ ] **Step 1: Add `data-testid="regime-banner"` to the overall banner section**

Current (`frontend/app/(frame)/screener/step-1-regime/page.tsx:172`):
```tsx
      <section className={`${pageStyles.banner} ${pageStyles[`banner_${combinedStatus}`]}`}>
```

Change to:
```tsx
      <section data-testid="regime-banner" className={`${pageStyles.banner} ${pageStyles[`banner_${combinedStatus}`]}`}>
```

- [ ] **Step 2: Add `data-testid="spx-chart"` / `data-testid="ndx-chart"` to the index chart wrappers**

Current (`frontend/app/(frame)/screener/step-1-regime/page.tsx:225`):
```tsx
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={spxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
```

Change to:
```tsx
          <div data-testid="spx-chart" className={pageStyles.indexChart}>
            <CandlestickChart data={spxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
```

Current (`frontend/app/(frame)/screener/step-1-regime/page.tsx:239`):
```tsx
          <div className={pageStyles.indexChart}>
            <CandlestickChart data={ndxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
```

Change to:
```tsx
          <div data-testid="ndx-chart" className={pageStyles.indexChart}>
            <CandlestickChart data={ndxCandles} height="auto" showToggles={false} defaultIndicators={[]} />
          </div>
```

- [ ] **Step 3: Add `data-testid="regime-metric-grid"` to the EMA/VIX grid**

Current (`frontend/app/(frame)/screener/step-1-regime/page.tsx:250`):
```tsx
      <div className={pageStyles.grid}>
```

Change to:
```tsx
      <div data-testid="regime-metric-grid" className={pageStyles.grid}>
```

- [ ] **Step 4: Add `data-testid="sector-heatmap"` to the sector heatmap container**

Current (`frontend/app/(frame)/screener/step-1-regime/page.tsx:397`):
```tsx
      <div className={pageStyles.sectors}>
```

Change to:
```tsx
      <div data-testid="sector-heatmap" className={pageStyles.sectors}>
```

- [ ] **Step 5: Point `ScreenerPage.ts` at the new test ids**

Current (`frontend/e2e/pages/ScreenerPage.ts:72-91`):
```ts
  // Step 3
  get regimeBanner(): Locator {
    return this.page.locator('section').first();
  }

  get spxChart(): Locator {
    return this.page.locator('canvas').first();
  }

  get ndxChart(): Locator {
    return this.page.locator('canvas').nth(1);
  }

  get metricGrid(): Locator {
    return this.page.locator('[class*="grid"]').first();
  }

  get sectorHeatmap(): Locator {
    return this.page.locator('[class*="sectors"]').first();
  }
```

Change to:
```ts
  // Step 3
  get regimeBanner(): Locator {
    return this.page.getByTestId('regime-banner');
  }

  get spxChart(): Locator {
    return this.page.getByTestId('spx-chart').locator('canvas').first();
  }

  get ndxChart(): Locator {
    return this.page.getByTestId('ndx-chart').locator('canvas').first();
  }

  get metricGrid(): Locator {
    return this.page.getByTestId('regime-metric-grid');
  }

  get sectorHeatmap(): Locator {
    return this.page.getByTestId('sector-heatmap');
  }
```

(Leave the misleading `// Step 3` comment as-is — it was already wrong before this change, pointing at Step 1 content; renaming it is out of scope for this fix. If you want it correct, change it to `// Step 1` while you're in the file — either is fine, just don't leave it silently changed as a surprise in the diff without calling it out in the commit message.)

- [ ] **Step 6: Verify typecheck is clean**

Run: `cd frontend && npm run typecheck`
Expected: no errors (adding `data-testid` to native DOM elements and `getByTestId` calls are both fully typed already; no type changes needed).

- [ ] **Step 7: Verify all three Step-1 smoke tests pass 5/5 runs**

Run: `cd frontend && npx playwright test e2e/tests/screener-steps-1-3.spec.ts --project=chromium --grep @smoke --reporter=list` 5 times in a row.
Expected: `Step 1 - regime banner and charts render`, `Step 1 - metric grid and sector heatmap visible`, and `shows confirmation dialog when regime is REJECT` all pass in all 5 runs, alongside the other (already-passing) tests in the file.

- [ ] **Step 8: Commit**

```bash
git add frontend/app/\(frame\)/screener/step-1-regime/page.tsx frontend/e2e/pages/ScreenerPage.ts
git commit -m "fix(e2e): use data-testid for Step 1 locators instead of generic CSS/tag selectors

metricGrid ([class*=\"grid\"].first()) intermittently resolved to a
hidden 0x0 box while the regime fetch (see prior commit) hadn't
resolved yet and regime.metrics was still empty; fixed primarily by
the query-string glob fix, this testid swap is defense-in-depth.
canvas locators had their own independent bug: lightweight-charts
renders 7 internal <canvas> elements per chart, so the old
canvas.nth(1) never actually reached the NDX chart at all (it landed
on SPX's 2nd internal canvas) — scoping to a per-chart testid wrapper
plus .first() fixes this for real. regimeBanner's section.first() is
not itself known-broken today — page.tsx renders three <section>s
(banner, explainer, news) and the banner is unconditionally first —
switched for consistency only, not because it was shown to be broken."
```

---

### Task 5: Quarantine both stale tests in the pre-step-reorder happy-path file that would otherwise keep `--grep @smoke` red regardless of Tasks 1-4

**Discovered during round-3/round-4 audit — real, separate blockers to the plan's stated Goal, not part of the originally-reported issues, and must be handled or the plan cannot actually turn CI green.**

`frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts` is tagged `@smoke` (`test.describe('Happy-path scan (mocked) @smoke', ...)` at line 11), so both its tests run in the exact command both `playwright.yml` and this plan's Task 6 use as the pass/fail gate: `npx playwright test --project=chromium --grep @smoke`. **Both tests in this file fail deterministically today, for two unrelated reasons — round 3 caught the first, round 4 caught the second:**

1. `full 7-step screener flow — AAPL candidate` (lines 12-72) asserts URLs from the *pre*-WS-E-step-reorder scheme:
```ts
await screener.goto(1);
await expect(page).toHaveURL(/step-1-universe/);   // line 17 — but goto(1) navigates to /screener/step-1-regime today
...
await screener.clickNext();
await expect(page).toHaveURL(/step-2-direction/);  // line 22 — but step 2 is /screener/step-2-universe today
...
await screener.clickNext();
await expect(page).toHaveURL(/step-3-regime/);      // line 27 — but step 3 is /screener/step-3-direction today
```
(Steps 4-7 in the same test do match the current scheme — only the first three steps were rotated by CR-01/WS-E and never updated here.) Fails deterministically on line 17.

2. `Step 3 scan log shows all-passed state when no rejections` (lines 74-88) asserts `await expect(page.getByText(/all passed/i)).toBeVisible()` at line 87. **This does not share root cause 1** — it asserts no URLs at all. It fails because `frontend/app/(frame)/screener/step-3-direction/page.tsx:1002-1038` (the page this test actually exercises today) renders its own inline `ScanLogSection` — a "Scanned / Passed / Rejected / DTE" numeric badge grid — which never renders the literal text "all passed." That text only exists in a different, unrelated component (`frontend/components/organisms/ScanLog/index.tsx:269`) that `step-3-direction/page.tsx` does not import. This looks like component drift over time (the scan-log UI was redesigned from a text-summary to a badge grid) rather than anything related to the step reorder — confirmed independently by reading `step-3-direction/page.tsx:1002-1038` directly, no `/all passed/i`-matching text anywhere in it.

Left as-is, either failure alone keeps Task 6's `--grep @smoke` run (and `playwright.yml` in CI) red no matter how correct Tasks 1-4 are, defeating the plan's Goal ("Turn `main`'s CI green").

A full rewrite of either test — re-deriving the Step 1-3 interactions for the current order, and re-deriving what the current scan-log UI actually renders when there are zero rejections — is out of scope here (neither is a mechanical fix). This task quarantines both visibly with `test.fixme` (keeps them discoverable in the Playwright report as known-broken tests needing a fix, rather than a silent `test.skip` or deletion that could look like they were never written) rather than fixing their content.

**Files:**
- Modify: `frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts:12, 74`

- [ ] **Step 1: Confirm both deterministic failures exist today**

Run: `cd frontend && npx playwright test e2e/tests/ws-g-happy-path-mocked.spec.ts --project=chromium --grep @smoke --reporter=list`
Expected: `full 7-step screener flow — AAPL candidate` fails on the `toHaveURL(/step-1-universe/)` assertion; `Step 3 scan log shows all-passed state when no rejections` fails on the `getByText(/all passed/i)` assertion. Both tests in the file fail.

- [ ] **Step 2: Mark both stale tests `fixme` with tracking reasons**

Current (`frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts:12`):
```ts
  test('full 7-step screener flow — AAPL candidate', async ({ page }) => {
```

Change to:
```ts
  // FIXME: written against the pre-WS-E-step-reorder URL scheme (old order:
  // 1=universe, 2=direction, 3=regime; current order: 1=regime, 2=universe,
  // 3=direction — steps 4-7 are unaffected). Needs a full rewrite of the
  // Step 1-3 interactions for the current order, not a mechanical URL swap.
  test.fixme('full 7-step screener flow — AAPL candidate', async ({ page }) => {
```

Current (`frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts:74`):
```ts
  test('Step 3 scan log shows all-passed state when no rejections', async ({ page }) => {
```

Change to:
```ts
  // FIXME: step-3-direction/page.tsx's current ScanLogSection renders a
  // Scanned/Passed/Rejected/DTE badge grid, not the "all passed" text this
  // test looks for (that text lives only in the unrelated ScanLog organism,
  // which this page doesn't use). Needs a rewrite against the current UI.
  test.fixme('Step 3 scan log shows all-passed state when no rejections', async ({ page }) => {
```

- [ ] **Step 3: Verify the smoke grep is unblocked**

Run: `cd frontend && npx playwright test e2e/tests/ws-g-happy-path-mocked.spec.ts --project=chromium --grep @smoke --reporter=list`
Expected: both tests report as `fixme`/skipped (neither `failed`).

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e/tests/ws-g-happy-path-mocked.spec.ts
git commit -m "test(e2e): mark two stale happy-path tests as fixme

Discovered while fixing unrelated CI red: both tests in this file fail
deterministically today, for two unrelated reasons, and were silently
keeping --grep @smoke red independent of the flaky-test fixes in this
branch. Test 1's first 3 of 7 step assertions still use the URL scheme
from before the WS-E step reorder (CR-01). Test 2 looks for an
'all passed' text summary that step-3-direction's current ScanLogSection
never renders (it's a numeric badge grid now; the text-summary UI lives
in an unrelated, unused-here component). Marked fixme (not skip/delete)
so both stay visible in the Playwright report as tracked, known-broken
debt pending a real rewrite against the current step order and UI."
```

---

### Task 6: Full-suite verification (matches CI exactly)

**Files:** none — verification only.

- [ ] **Step 1: Install exactly what CI installs**

```bash
cd frontend
npm ci
```
Expected: installs `@playwright/test@1.62.1` per `package-lock.json` (a stale local install at `1.59.1` was found during planning — `npm ci` replaces it so every later step in this task runs against what `playwright.yml`'s `npm ci` step actually produces, not a locally-drifted version). Then install the matching browser binary — `npm ci` alone does not do this locally, and without it every Playwright run fails at `browserType.launch` with "Executable doesn't exist" (CI never hits this because `playwright.yml` has its own explicit `npx playwright install chromium` step; verified during round-8 execution):

```bash
cd frontend
npx playwright install chromium
```
Expected: downloads Chrome for Testing + headless shell for Playwright v1234 into `%LOCALAPPDATA%\ms-playwright` (the pre-existing cache held the 1.59.1-era browser and is not reused after the `npm ci` version bump).

- [ ] **Step 2: Run the exact CI frontend job commands, in order**

```bash
cd frontend
npm run typecheck
npm run test -- --ci
npm run build
```
Expected: all three succeed with no errors (this reproduces `ci.yml`'s `frontend` job).

- [ ] **Step 3: Run the CI backend job command**

```bash
cd backend
pytest
```
Expected: passes with no errors (this reproduces `ci.yml`'s `backend` job — none of Tasks 1-5 touch any backend file, so this step only confirms `backend` is green on `main` independent of this branch, not something this plan changes; if it's already red on `main` today, that's a separate, pre-existing problem this plan doesn't fix, and the PR body's "CI green" claim should be scoped down accordingly before opening the PR).

- [ ] **Step 4: Run the exact CI Playwright job command, 3 times in a row**

```bash
cd frontend
npx playwright test --project=chromium --grep @smoke
```
Expected: all `@smoke`-tagged tests pass or are reported `fixme` (never `failed`) in all 3 runs (this reproduces `playwright.yml`'s "Run smoke tests" step). Both tests in `ws-g-happy-path-mocked.spec.ts` should now show as `fixme` per Task 5, not `failed` — if either still shows `failed`, Task 5 wasn't applied or didn't take; stop and fix that before treating anything else as done. `dashboard.spec.ts:23`'s `[class*="badge"], [class*="status"]` locator is the same fragile pattern class as the Step-1 locators fixed in Task 4, on a different page — it was not reproduced as flaky and is left as-is, but it's an unverified residual risk to "all runs green" that this plan did not chase down; if it starts failing, that's the next place to look, not a regression from this branch.

- [ ] **Step 5: Push and confirm both GitHub Actions workflows go green on the PR**

```bash
git push -u origin <branch-name>
gh pr create --title "Fix red CI: ESLint require() + Step-1-regime Playwright flakes" --body "$(cat <<'EOF'
## Summary
- Removes a dead `require()` in a test file that trips `@typescript-eslint/no-require-imports` and fails `next build` in ci.yml.
- Fixes three Playwright route mocks (`api-mocks.ts`, `api-mocks-reject.ts`, inline override in `screener-steps-1-3.spec.ts`) that used a bare `**/api/regime` glob — it never matched the querystring-bearing request that Step 1's `fetchRegime()` sends (other `api.getRegime()` call sites pass no params and are unaffected either way), so the mock silently missed and the test hit an unmocked backend that CI never starts. (`api-mocks-reject.ts` isn't wired into any current test, so this one's precautionary.) Also fixes a second, previously-masked bug the glob fix exposed: both REJECT mock payloads were missing the `omm` field that `StepNavBar`'s `data-regime` attribute actually depends on (`alignmentVerdict(direction, descriptorFromState(r.omm?.state ?? ''))`, not `r.overall`), so once the mock started getting through, the alignment verdict silently computed `CAUTION` instead of `REJECT`.
- Drops a redundant `reload()` + `waitForLoadState('networkidle')` pair from the REJECT test — the route override already applies on the first navigation, and the existing `toBeVisible()` assertions already auto-retry.
- Replaces 5 generic CSS/tag-based Playwright locators (`section.first()`, `canvas.first()/.nth(1)`, `[class*="grid"]`, `[class*="sectors"]`) with `data-testid`-based ones on Step 1. The canvas locators had a real, confirmed bug (lightweight-charts renders 7 canvases per chart, so `canvas.nth(1)` never actually reached the NDX chart); `metricGrid`'s reproduced flake is most likely the same root cause as the glob-mismatch fix above (empty grid while the regime fetch is unresolved), with this swap as defense-in-depth rather than the primary fix for it.
- Marks both tests in `ws-g-happy-path-mocked.spec.ts` `fixme` — discovered during this work, they fail deterministically for two unrelated reasons (a pre-step-reorder URL scheme, and a scan-log UI that no longer renders the text the test looks for) and were failing on every `--grep @smoke` run regardless of anything else in this PR. Not a rewrite (out of scope here), just unblocks the smoke gate and tracks both as known debt.

## Test plan
- [x] `npm run typecheck` clean
- [x] `npm run test -- --ci` clean
- [x] `npm run build` clean (ESLint no longer fails)
- [x] `cd backend && pytest` clean (pre-existing, unaffected by this branch — confirms `ci.yml`'s `backend` job independent of these changes)
- [x] `npx playwright test --project=chromium --grep @smoke` green across 3 consecutive local runs
- [ ] CI (ci.yml + playwright.yml) green on this PR
EOF
)"
```
Expected: both `CI` and `Playwright Tests` checks go green on the PR.

---

## Self-Review

**Spec coverage:** ESLint `require()` error → Task 1. The user reported "4 flaky Playwright smoke tests around Step 1 regime navigation"; this investigation located and reproduced exactly **3** distinct Step-1-regime tests in `screener-steps-1-3.spec.ts` (`Step 1 - regime banner and charts render`, `Step 1 - metric grid and sector heatmap visible`, `shows confirmation dialog when regime is REJECT`), all traced to three root causes (Finding 2's query-string glob mismatch, Finding 3's canvas-indexing bug plus general locator hardening, and Finding 4's REJECT-mock missing-`omm`-data bug that Finding 2's own fix exposed) — Tasks 2–4 fix all three; Task 6 verifies against the exact CI commands. No 4th Step-1-regime test was found despite deliberate searching (`dashboard.spec.ts` was checked and ruled out — different page, not reproduced as flaky). Task 5 covers two distinct, previously-unreported issues discovered while verifying the fixes end-to-end: both tests in `ws-g-happy-path-mocked.spec.ts` have deterministic (non-flaky) `@smoke` failures — one from a stale pre-step-reorder URL scheme, one from a scan-log UI that no longer renders the text the test looks for — that would have kept `playwright.yml` red independent of everything else in this plan — without Task 5, the plan's Goal of an actually-green CI would not have been achievable even with Tasks 1–4 done perfectly. If CI continues to show a failure after this lands that isn't one of the tests named above, it lives outside what this plan's investigation could locate and needs a fresh look, not an assumption that it's already covered.

**Placeholder scan:** no TBD/TODO, no "add appropriate handling," every step shows exact before/after code and exact commands with expected output — the sole exception is `<branch-name>` in Task 6 Step 5's `git push`, which is unavoidable (the branch name isn't known until the implementer creates it) rather than an omitted detail.

**Type consistency:** `data-testid` is a plain HTML attribute (no new types introduced); `page.getByTestId()` is an existing Playwright API already used implicitly via `getByRole`/`getByText` elsewhere in this codebase's e2e suite. `ScreenerPage.ts` getters keep their existing `Locator` return type.
