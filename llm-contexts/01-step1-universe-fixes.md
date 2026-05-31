# LLM Context — Stream A: Step 1 Universe Fixes (CR-05 + WS-51)

**Workstream:** CR-05 (universe bug fixes) + WS-51 (Step 1 UX polish)
**Conflict class:** Medium — modifies shared `RunScanButton` organism and `universeStore` store; do not add new exports to either.

---

## 1. Mission

Fix two confirmed bugs in the universe selection flow and apply cosmetic UX polish to Step 1. All changes are frontend-only — no backend work.

**The single most important constraint:** Do NOT touch any file outside the owned-files list below.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/lib/universeStore.ts` | Modify | Remove `RUSSELL2000` from the `Universe` union type |
| `frontend/app/(frame)/screener/step-1-universe/page.tsx` | Modify | Remove Russell 2000 card; fix pluralization; fix warning banner; add aria |
| `frontend/app/(frame)/screener/step-1-universe/page.module.css` | Modify | Add `.filterWarning` class for styled warning banner |
| `frontend/components/organisms/RunScanButton/index.tsx` | Modify | Expand `'Watchlist'` pick to actual starred symbols before scan |

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/lib/watchlistStore.ts` | Need `useWatchlistStore.getState().added` to get starred symbols |
| `frontend/lib/scanStore.ts` | Understand `useScanStore.getState()` call pattern (already used in RunScanButton) |
| `frontend/app/(frame)/screener/screener.module.css` | Shared `.main` / `.stepHeader` classes — do not re-define |
| `frontend/styles/tokens.css` | All CSS variables — full list in Section 5 below |

---

## 4. Integration constraints

### `useWatchlistStore` (read-only, inside a callback)
```ts
// Import:
import { useWatchlistStore } from '@/lib/watchlistStore';

// Inside the onClick useCallback in RunScanButton — NOT as a hook call, use .getState():
const watchlistSymbols = useWatchlistStore.getState().added;  // string[]
```

### `universeStore` — `Universe` type is exported and used in:
- `frontend/app/(frame)/screener/step-1-universe/page.tsx` — has its own local `type Universe` (must also update)
- `frontend/components/organisms/RunScanButton/index.tsx` — uses `useUniverseStore` but does not import the `Universe` type directly

**After removing `RUSSELL2000`:** the store default is `'SP500'` — no migration needed.

### `RunScanButton` — existing pattern for store access inside callbacks:
```ts
// Pattern already used in the file — follow this exactly:
useScanStore.getState().setRejectedLog([]);       // ← already in file
useWatchlistStore.getState().added                 // ← add this for Watchlist case
```

---

## 5. CSS tokens (full list)

```css
/* Dark theme (default) */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;
--border-subtle:    #2A2E42;
--border-strong:    #363B54;
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;
--neutral:          #4A5568;
--neutral-bg:       #1A202C;
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Light theme overrides */
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--bg-surface-3:   #EBF0FF;
--border-subtle:  #DDE1F0;
--border-strong:  #C5CCE6;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
--reject:         #D32F2F;
--reject-bg:      #FEECEC;
--reject-border:  #F5BCBC;
```

---

## 6. Primitives & component reference

```tsx
<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />
<Title as="h1|h2|h3" size={18|20|24} />
<Data size={11|12|13|14|16|18|20|24} weight={500|600} tone="pass|caution|reject" />
```

- `<Text>` default: `size=13`, `tone="primary"`, `weight=400`
- `<Data>` is monospace, tabular-nums — use for symbol counts, prices
- No font-weight 600 on form labels — use `weight={400}`
- No card shadows — `border: 1px solid var(--border-subtle)`
- Status tints: `color-mix(in srgb, var(--reject) 10%, var(--bg-surface))`

---

## 7. Domain types (relevant subset)

Not needed for this workstream — no domain types used in Step 1 page or RunScanButton changes.

---

## 8. Zustand stores

### `universeStore.ts` (modify — remove RUSSELL2000)
```ts
export type Universe =
  | 'SP500'
  | 'NDX100'
  | 'DOW30'
  | 'RUSSELL2000'   // ← DELETE THIS LINE
  | 'SPY'
  | 'Watchlist'
  | 'Custom';

// Default seed values (do not change):
pick:        'SP500'
customRaw:   ''
minPriceRaw: ''
maxPriceRaw: ''
minCapRaw:   ''
maxCapRaw:   ''
capUnit:     'B'
```

### `watchlistStore.ts` (read-only — do not modify)
```ts
interface WatchlistState {
  added: string[];   // uppercase symbol strings, e.g. ['AAPL', 'NVDA']
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  isWatched:    (sym: string) => boolean;
}
// Access inside callback: useWatchlistStore.getState().added
```

---

## 9. Mock data

Not applicable — Step 1 has no data fetching and no mocks.

---

## 10. Task spec

### Fix A — Remove Russell 2000 (CR-05 Bug 2)

**In `frontend/lib/universeStore.ts`:**
- Remove `'RUSSELL2000'` from the `Universe` type union (line 14).

**In `frontend/app/(frame)/screener/step-1-universe/page.tsx`:**
- The file has its own local `type Universe` (lines 19–27) — remove `'RUSSELL2000'` from it.
- Remove the Russell 2000 entry from the `OPTIONS` array (currently line 95):
  ```ts
  { key: 'RUSSELL2000', label: 'Russell 2000', count: 2000, desc: '...' }
  ```
- After removal, OPTIONS will have 6 cards: S&P 500, Nasdaq-100, Dow 30, SPY ETF, My Watchlist, Custom list. This is correct.

**Acceptance criteria:**
- `tsc --noEmit` clean after removal.
- The Step 1 page renders 6 cards, not 7.
- No TypeScript error on `universeStore` or `RunScanButton`.

---

### Fix B — Watchlist expansion in RunScanButton (CR-05 Bug 1)

**In `frontend/components/organisms/RunScanButton/index.tsx`:**

Current code (line 59):
```ts
const universe = pick === 'Custom' ? parseSymbols(customRaw) : [pick];
```

Replace with:
```ts
const universe =
  pick === 'Custom'
    ? parseSymbols(customRaw)
    : pick === 'Watchlist'
    ? useWatchlistStore.getState().added
    : [pick];
```

Add the import at the top of the file (it is not currently imported):
```ts
import { useWatchlistStore } from '@/lib/watchlistStore';
```

**Edge case:** If `useWatchlistStore.getState().added` is empty and the user clicks Run Scan with Watchlist selected, the backend receives an empty array `[]` — this is acceptable; the backend will return no candidates. Do not add UI validation for this; it is out of scope.

**Acceptance criteria:**
- When `pick === 'Watchlist'`, the scan API receives the actual starred symbols array, not `['Watchlist']`.
- `tsc --noEmit` clean.

---

### Fix C — Pluralization (WS-51)

**In `frontend/app/(frame)/screener/step-1-universe/page.tsx`:**

Current code (around line 135):
```tsx
{typeof o.count === 'number' ? `${o.count} symbols` : o.count}
```

Replace with:
```tsx
{typeof o.count === 'number'
  ? `${o.count} ${o.count === 1 ? 'symbol' : 'symbols'}`
  : o.count}
```

**Acceptance criteria:** SPY ETF card shows "1 symbol" (not "1 symbols"). All other cards show "N symbols" (plural).

---

### Fix D — Warning banner styling (WS-51)

**In `frontend/app/(frame)/screener/step-1-universe/page.module.css`:**

Add a new class at the end of the file:
```css
.filterWarning {
  padding: var(--space-2) var(--space-3);
  background: color-mix(in srgb, var(--reject) 10%, var(--bg-surface));
  border: 1px solid var(--reject-border);
  border-radius: var(--radius-sm);
}
```

**In `frontend/app/(frame)/screener/step-1-universe/page.tsx`:**

Current banner block (around line 254):
```tsx
{(priceInvalid || capInvalid) && (
  <Text size={12} tone="reject">Fix filter range before proceeding — minimum is above maximum.</Text>
)}
```

Replace with:
```tsx
{(priceInvalid || capInvalid) && (
  <div
    id="filter-warning"
    className={formStyles.filterWarning}
    role="alert"
  >
    <Text size={12} tone="reject">
      {priceInvalid && capInvalid
        ? 'Fix filter ranges before proceeding — both minimums are above their maximums.'
        : 'Fix filter range before proceeding — minimum is above maximum.'}
    </Text>
  </div>
)}
```

**Acceptance criteria:**
- Banner has a visible red-tinted background and border — not plain text.
- When only one filter is invalid: "Fix filter range …" (singular).
- When both are invalid: "Fix filter ranges …" (plural).

---

### Fix E — Suppress footer summary when warning is active (WS-51)

**In `frontend/app/(frame)/screener/step-1-universe/page.tsx`:**

The `filtersFooter` div (around line 258) shows active filter values. When a warning is visible, hide this footer to avoid showing broken filter values right below the warning.

Current:
```tsx
<div className={formStyles.filtersFooter}>
  {hasFilters ? ( ... ) : ( ... )}
</div>
```

Wrap the footer in a conditional:
```tsx
{!(priceInvalid || capInvalid) && (
  <div className={formStyles.filtersFooter}>
    {hasFilters ? ( ... ) : ( ... )}
  </div>
)}
```

**Acceptance criteria:** When either filter has min > max, the filter summary line at the bottom is hidden. When filters are valid, it still shows.

---

### Fix F — Aria linkage (WS-51)

**In `frontend/app/(frame)/screener/step-1-universe/page.tsx`:**

The price filter group div (outer `<div className={formStyles.filterGroup}>` for price range) needs `aria-describedby="filter-warning"` when the price filter is invalid.

Similarly for the cap filter group.

Update the price filter group opening tag:
```tsx
<div
  className={formStyles.filterGroup}
  {...(priceInvalid ? { 'aria-describedby': 'filter-warning' } : {})}
>
```

Update the cap filter group opening tag:
```tsx
<div
  className={formStyles.filterGroup}
  {...(capInvalid ? { 'aria-describedby': 'filter-warning' } : {})}
>
```

**Acceptance criteria:** Screen reader associates the warning banner with the invalid filter group.

---

## 11. Hard rules

1. **No Tailwind, no styled-components, no CSS-in-JS.**
2. **No `style={{}}` except computed one-offs** (e.g. `style={{ width: \`${pct}%\` }}`).
3. **No hardcoded colors** — always CSS custom properties from the token list in Section 5.
4. **No invented Status labels** — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. **No font-weight 600 on form labels** — use `weight={400}`.
6. **No card box-shadows** — use `border: 1px solid var(--border-subtle)`.
7. **Never skip atom → molecule → organism hierarchy.**
8. **`npm run typecheck` must be clean after every file edit.** Run it before moving to the next fix.
9. **Do not modify any file outside the owned-files list** (Section 2).
10. **Do NOT commit.** See Section 13 — produce a summary report instead.

---

## 12. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001 — keep running while editing
npm run typecheck    # run after EVERY file edit — must stay at 0 errors
```

---

## 12a. Playwright test file (write this before running)

**Create this file exactly as written:**
`frontend/e2e/ws-a-step1-universe-fixes.spec.ts`

```typescript
import { test, expect } from '@playwright/test';

test.describe('WS-A: Step 1 Universe Fixes (CR-05 + WS-51)', () => {

  test('renders 6 cards — Russell 2000 absent', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await expect(page.getByText('Russell 2000')).not.toBeVisible();
    const cards = page.getByRole('button', {
      name: /S&P 500|Nasdaq-100|Dow 30|SPY ETF|My Watchlist|Custom list/,
    });
    await expect(cards).toHaveCount(6);
  });

  test('SPY card shows "1 symbol" not "1 symbols"', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await expect(page.getByText('1 symbol', { exact: false })).toBeVisible();
    await expect(page.getByText('1 symbols')).not.toBeVisible();
  });

  test('warning banner is styled (has background color) when price min > max', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    const banner = page.locator('#filter-warning');
    await expect(banner).toBeVisible();
    const bg = await banner.evaluate(
      (el) => getComputedStyle(el).backgroundColor,
    );
    expect(bg).not.toBe('rgba(0, 0, 0, 0)');
    expect(bg).not.toBe('transparent');
    await page.screenshot({ path: 'e2e/screenshots/ws-a-banner-styled.png', fullPage: false });
  });

  test('banner text singular when only price invalid', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await expect(page.locator('#filter-warning')).toContainText('Fix filter range before');
    await expect(page.locator('#filter-warning')).not.toContainText('ranges');
  });

  test('banner text plural when both price and cap invalid', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await page.getByLabel(/Minimum market cap/).fill('50');
    await page.getByLabel(/Maximum market cap/).fill('10');
    await expect(page.locator('#filter-warning')).toContainText('Fix filter ranges');
  });

  test('footer summary hidden when warning active', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await expect(page.getByText(/Filters: price/)).not.toBeVisible();
  });

  test('footer summary reappears after fixing invalid filter', async ({ page }) => {
    await page.goto('/screener/step-1-universe');
    await page.getByLabel('Minimum stock price in dollars').fill('200');
    await page.getByLabel('Maximum stock price in dollars').fill('100');
    await page.getByLabel('Maximum stock price in dollars').fill('300');
    await expect(page.locator('#filter-warning')).not.toBeVisible();
    await expect(page.getByText(/Filters: price/)).toBeVisible();
  });

  test('Watchlist pick sends actual symbols — not the string "Watchlist"', async ({ page }) => {
    let capturedUniverse: unknown = null;

    await page.route('**/api/scan', async (route) => {
      capturedUniverse = JSON.parse(route.request().postData() ?? '{}').universe;
      await route.fulfill({
        json: { scan_id: 'test', timestamp: new Date().toISOString(), candidates: [], rejected: [] },
      });
    });

    // Stub other API calls so page loads cleanly
    await page.route('**/api/**', async (route) => {
      if (!route.request().url().includes('/api/scan')) {
        await route.fulfill({ json: [] });
      }
    });

    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /My Watchlist/ }).click();
    // Trigger the scan from wherever RunScanButton is mounted
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await page.waitForTimeout(800);

    expect(capturedUniverse).not.toBeNull();
    expect(Array.isArray(capturedUniverse)).toBe(true);
    // Must NOT be the literal string array ['Watchlist']
    expect(capturedUniverse).not.toEqual(['Watchlist']);
  });

});
```

**Run the spec:**
```bash
cd frontend
npx playwright test e2e/ws-a-step1-universe-fixes.spec.ts --reporter=list
```

---

## 13. Completion report (produce before exiting — do NOT commit)

### Iron law: evidence before claims

**You may not write "PASS", "done", "complete", or any synonym without pasting the actual command output that proves it.**
Saying "tests pass" without showing the output is a false claim. Paste everything.

When all fixes are done, produce this report with **actual command output copy-pasted inline**:

---

```
## WS-A Completion Report

### git diff --stat (paste full output)
[paste output of: git diff HEAD --stat]

### typecheck output (paste full tsc output)
[paste output of: npm run typecheck]
→ Error count: [number]

### Playwright test output (paste full --reporter=list output)
[paste output of: npx playwright test e2e/ws-a-step1-universe-fixes.spec.ts --reporter=list]
→ Passed: [N] / Failed: [N]

### Screenshots produced
- e2e/screenshots/ws-a-banner-styled.png : EXISTS / MISSING

### Errors or deviations from spec
[describe anything that diverged, or write "None"]

### Ready for Kenneth review: YES / NO
[YES only if: typecheck = 0 errors AND playwright = 8/8 passed AND screenshots exist]
```

---

**If any test fails:** diagnose and fix before submitting the report. Do NOT submit a report with failing tests.
**If typecheck has errors:** fix them before submitting. A non-zero error count = not done.
**Do NOT run `git commit` or `git add`.** Kenneth reviews this report and commits.

---

## 14. Copy/paste prompt

```
Read `llm-contexts/01-step1-universe-fixes.md` fully before writing any code.
It is your single source of truth — do not rely on memory or assumptions.

You are implementing Stream A (CR-05 + WS-51) for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules, Zustand v5).

Your owned files:
- frontend/lib/universeStore.ts
- frontend/app/(frame)/screener/step-1-universe/page.tsx
- frontend/app/(frame)/screener/step-1-universe/page.module.css
- frontend/components/organisms/RunScanButton/index.tsx

Also create (do not modify any other file):
- frontend/e2e/ws-a-step1-universe-fixes.spec.ts   ← Playwright spec from Section 12a

Do NOT modify any file outside this list.

Task: Remove Russell 2000 from the universe picker, fix the Watchlist expansion bug
so the scan API receives actual starred symbols, and apply Step 1 UX polish
(pluralization, warning banner styling, footer suppression, aria).

VERIFICATION RULES (non-negotiable):
1. Run `npm run typecheck` from `frontend/` after EVERY file edit. Must stay 0 errors.
2. When all code changes are done, run the Playwright spec from Section 12a.
3. You may NOT claim anything is "done", "passing", or "complete" without pasting
   the actual command output. "Should work" is not evidence.
4. Produce the completion report from Section 13 with all outputs pasted inline.
5. Do NOT commit. Kenneth reviews the report and commits manually.
```
