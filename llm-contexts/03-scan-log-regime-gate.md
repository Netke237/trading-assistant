# LLM Context — Round 3: Scan Log Panel + Regime REJECT Gate (CR-03 + CR-07)

**Workstream:** CR-03 (persistent scan log on Direction page) + CR-07 (regime REJECT gate on scan execution)
**Conflict class:** Medium — modifies shared `RunScanButton` organism; do not add new exports to it.

---

## 1. Mission

Two features implemented together because both involve the Direction + Horizon page and RunScanButton, and they share no conflicts with any other open workstream.

**CR-03:** The Direction + Horizon page (Step 2) permanently hosts a scan log panel in its lower section. Before any scan it shows a placeholder. After a scan it shows: a rejection breakdown table, a stage summary, and a DTE recommendation. The log persists across navigation; resets when a new scan starts (already handled by RunScanButton clearing `rejectedLog` before calling the API).

**CR-07:** When `scanStore.regime === 'REJECT'`, show a persistent warning badge on the Direction page header. When the user clicks RunScanButton with a conflicting scan setup (Bullish direction + REJECT regime), block and show a confirmation dialog before proceeding.

**The single most important constraint:** Do NOT touch any file outside the owned-files list below. `scanStore.ts`, `universeStore.ts`, `StepNavBar`, and all other stores/components are read-only.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/app/(frame)/screener/step-2-direction/page.tsx` | Modify | Add regime badge + scan log panel |
| `frontend/app/(frame)/screener/step-2-direction/page.module.css` | Modify | CSS for scan log panel and regime badge |
| `frontend/components/organisms/RunScanButton/index.tsx` | Modify | Add regime confirmation dialog |
| `frontend/components/organisms/RunScanButton/index.module.css` | Modify | CSS for confirmation dialog overlay |
| `frontend/e2e/tests/ws-c-scan-log-regime-gate.spec.ts` | Create | Playwright spec (8 tests) |

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/lib/scanStore.ts` | Read `regime`, `rejectedLog`, `scanResult`, `context` — do not modify |
| `frontend/app/(frame)/screener/screener.module.css` | Shared `.main` / `.stepHeader` classes |
| `frontend/components/organisms/StepNavBar/index.tsx` | Reference the existing REJECT dialog pattern (overlay + dialog CSS); do not copy, just reference for style consistency |
| `frontend/components/organisms/StepNavBar/StepNavBar.module.css` | Reference overlay/dialog CSS tokens |
| `frontend/styles/tokens.css` | All CSS variables — full list in Section 5 |

---

## 4. Integration constraints

### `scanStore` (read-only)

```ts
// Import:
import { useScanStore } from '@/lib/scanStore';

// Fields relevant to CR-03:
const rejectedLog = useScanStore((s) => s.rejectedLog);  // { symbol: string; reason: string }[]
const scanResult  = useScanStore((s) => s.scanResult);   // ScanResult | null
const context     = useScanStore((s) => s.context);      // ScanContext | null

// Fields relevant to CR-07:
const regime = useScanStore((s) => s.regime);  // Status: 'PASS'|'CAUTION'|'REJECT'|'PENDING'|'NO_DATA'

// In RunScanButton (getState pattern — already used there):
const regime = useScanStore.getState().regime;
```

### CR-03: Scan log data derivation (no new store fields needed)

The existing `rejectedLog: { symbol: string; reason: string }[]` has all the data. Derive in the component:

```ts
// Group by reason → count
const byReason = rejectedLog.reduce<Record<string, number>>((acc, e) => {
  acc[e.reason] = (acc[e.reason] ?? 0) + 1;
  return acc;
}, {});

// Infer stage from reason string
function inferStage(reason: string): 'stock' | 'contract' | 'filter' {
  if (reason.includes('contract') || reason.includes('delta') || reason.includes('DTE') || reason.includes('spread')) return 'contract';
  if (reason.includes('price') || reason.includes('cap')) return 'filter';
  return 'stock';
}

// DTE recommendation from horizon
function dteRecommendation(horizon: string | undefined): string {
  if (!horizon) return '';
  if (horizon.startsWith('Intraday')) return 'For Intraday 0–2d: target DTE 7–14d';
  if (horizon.startsWith('Swing'))    return 'For Swing 5–15d: target DTE 21–45d (2–3× hold period to reduce theta drag)';
  if (horizon.startsWith('Position')) return 'For Position 15–45d: target DTE 45–90d';
  // Custom: parse days from "Custom (X–Yd)" format
  const m = horizon.match(/(\d+)–(\d+)/);
  if (m) {
    const max = Number(m[2]);
    return `For this horizon: target DTE ${max * 2}–${max * 3}d`;
  }
  return '';
}
```

### CR-07: Regime conflict check

Show the gate when **both** conditions are true:
1. `regime === 'REJECT'`
2. `direction === 'Bullish'` (scan context or local direction state)

The existing `RunScanButton` reads direction from `context?.direction`. Use `useScanStore.getState().regime` inside the `useCallback` (same pattern as other `.getState()` calls already there).

### RunScanButton existing shape (read before modifying)

```tsx
// Current onClick flow (simplified):
const onClick = useCallback(() => {
  if (scanning) return;
  // ... universe / direction / horizon derivation ...
  if (universe.length === 0) { /* toast + return */ }
  // ... filters ...
  setScanState('SCANNING');
  useScanStore.getState().setRejectedLog([]);
  api.postScan(...)
    .then(...)
    .catch(...);
}, [...deps]);
```

**Insert the regime check AFTER the universe guard and BEFORE `setScanState('SCANNING')`:**

```tsx
const currentRegime = useScanStore.getState().regime;
if (currentRegime === 'REJECT' && direction === 'Bullish' && !regimeConfirmed) {
  setShowRegimeConfirm(true);
  return;
}
```

Where `regimeConfirmed` is a `useRef<boolean>` (not state, to avoid re-render loop):

```tsx
const regimeConfirmedRef = useRef(false);

// In "Proceed anyway" handler:
regimeConfirmedRef.current = true;
onClick();  // re-trigger; confirmed = true this time
regimeConfirmedRef.current = false;
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

- `<Data>` is monospace, tabular-nums — use for symbol names, counts, reasons
- No card shadows — `border: 1px solid var(--border-subtle)`
- Status tints: `color-mix(in srgb, var(--reject) 10%, var(--bg-surface))`

---

## 7. Domain types (relevant subset)

```ts
// From frontend/lib/scanStore.ts:
export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED' | 'PARTIAL' | 'CANCELLED';

export interface ScanContext {
  universe:  string;
  direction: Direction;   // 'Bullish' | 'Bearish'
  horizon:   string;      // "Swing (5–15d)"
}

export interface ScanResult {
  scan_id: string;
  timestamp: string;
  candidates: TradeCardData[];
  rejected?: { symbol: string; reason: string }[];
}

// From frontend/lib/status.ts:
export type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';
```

---

## 8. Zustand stores (read-only)

### `scanStore.ts` — do NOT modify

```ts
interface ScanStoreState {
  scanState:       ScanState;        // 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED' ...
  regime:          Status;           // 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'
  scanResult:      ScanResult | null;
  context:         ScanContext | null;
  rejectedLog:     { symbol: string; reason: string }[];
  // Actions (read-only from this workstream):
  setRejectedLog:  (entries: { symbol: string; reason: string }[]) => void;
  // Default values:
  // scanState: 'IDLE', regime: 'PENDING', scanResult: null, rejectedLog: []
}
```

---

## 9. Mock data (scan log test data)

For Playwright tests, stub the scan API to return a realistic rejection payload:

```ts
const MOCK_SCAN_RESULT = {
  scan_id: 'test-001',
  timestamp: new Date().toISOString(),
  candidates: [],
  rejected: [
    { symbol: 'AAPL', reason: 'stock score 23 — below pass threshold' },
    { symbol: 'TSLA', reason: 'stock score 31 — below pass threshold' },
    { symbol: 'NVDA', reason: 'contract spread 0.45 — above max_bid_ask_spread_pct' },
    { symbol: 'MSFT', reason: 'stock score 40 — caution zone' },
    { symbol: 'AMD', reason: 'event reject — earnings in 3 days' },
  ],
};
```

---

## 10. Task spec

### CR-03 — Scan log panel on Direction page

The `logSection` div in `step-2-direction/page.tsx` currently renders only when `rejectedLog.length > 0`. Replace it with a permanent section that always renders:

**Before first scan** (`scanResult === null`):
```
SCAN LOG
No scan run yet.
```

**After scan with rejections** (`scanResult !== null && rejectedLog.length > 0`):
```
SCAN LOG                             [count badge]
REJECTION BREAKDOWN
Reason                               Count
stock score 23 — below pass threshold    47
event reject — earnings in N days        12
contract spread > 0.20                    8

STAGE SUMMARY
Stock scoring: 59 rejected   Contract scoring: 8 rejected   Pre-filter: 0 rejected

DTE RECOMMENDATION
For Swing 5–15d: target DTE 21–45d (2–3× your hold period to reduce theta drag)
```

**After scan with no rejections** (`scanResult !== null && rejectedLog.length === 0`):
```
SCAN LOG
All symbols passed all filters.
```

Implementation notes:
- Stage summary groups by `inferStage(reason)` — count each group
- The breakdown table uses `byReason` (grouped by reason string)
- DTE recommendation calls `dteRecommendation(context?.horizon)`
- No new store fields — derive everything in the component
- Section always rendered; use conditional content inside, not conditional render of the section

### CR-07 — Regime badge on Direction page header

In the `<div className={styles.stepHeader}>` block, add a reject-tone warning badge when regime is REJECT:

```tsx
{regime === 'REJECT' && (
  <div className={formStyles.regimeBadge}>
    <Text size={11} tone="reject" weight={500}>REGIME REJECT — confirm before scanning</Text>
  </div>
)}
```

Position it below the subtitle text.

### CR-07 — Confirmation dialog on RunScanButton

Add `const [showRegimeConfirm, setShowRegimeConfirm] = useState(false)` and a `regimeConfirmedRef = useRef(false)` to RunScanButton.

Insert this check inside `onClick`, after the empty-universe guard, before `setScanState('SCANNING')`:

```ts
const currentRegime = useScanStore.getState().regime;
const currentDir    = context?.direction ?? direction;
if (currentRegime === 'REJECT' && currentDir === 'Bullish' && !regimeConfirmedRef.current) {
  setShowRegimeConfirm(true);
  return;
}
```

Render the dialog:
```tsx
{showRegimeConfirm && (
  <div className={styles.regimeOverlay} role="dialog" aria-modal aria-labelledby="regime-run-title">
    <div className={styles.regimeDialog}>
      <p id="regime-run-title" className={styles.regimeDialogTitle}>Market regime is REJECT</p>
      <p className={styles.regimeDialogBody}>
        Running a Bullish scan in a REJECT regime carries elevated risk.
        Proceed anyway?
      </p>
      <div className={styles.regimeDialogActions}>
        <button type="button" className={styles.regimeCancelBtn}
          onClick={() => setShowRegimeConfirm(false)}>
          Cancel
        </button>
        <button type="button" className={styles.regimeProceedBtn}
          onClick={() => {
            setShowRegimeConfirm(false);
            regimeConfirmedRef.current = true;
            onClick();
          }}>
          Proceed anyway
        </button>
      </div>
    </div>
  </div>
)}
```

The overlay covers the viewport: `position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: grid; place-items: center; z-index: 50`.

---

## 11. Hard rules

1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` except computed one-off values.
3. No hardcoded colours — always CSS custom properties.
4. No invented Status labels — only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. No font-weight 600 on form labels — use `weight={400}`.
6. No card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Never skip component hierarchy: atom → molecule → organism.
8. `npm run typecheck` must be clean after every file edit.
9. Do NOT touch `scanStore.ts`, `universeStore.ts`, `api.ts`, or any file not in the owned-files list.
10. Do NOT commit.

---

## 12a. Playwright spec

Create `frontend/e2e/tests/ws-c-scan-log-regime-gate.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

const MOCK_SCAN = {
  scan_id: 'test-001',
  timestamp: new Date().toISOString(),
  candidates: [],
  rejected: [
    { symbol: 'AAPL', reason: 'stock score 23 — below pass threshold' },
    { symbol: 'TSLA', reason: 'stock score 31 — below pass threshold' },
    { symbol: 'NVDA', reason: 'contract spread 0.45 — above max_bid_ask_spread_pct' },
    { symbol: 'MSFT', reason: 'stock score 40 — below pass threshold' },
    { symbol: 'AMD',  reason: 'event reject — earnings in 3 days' },
  ],
};

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
  await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
}

test.describe('WS-C: Scan Log + Regime Gate (CR-03 + CR-07)', () => {

  test('scan log shows placeholder before first scan', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText('No scan run yet.')).toBeVisible();
  });

  test('scan log shows rejection breakdown after scan', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText(/stock score/i)).toBeVisible();
    await expect(page.getByText(/contract spread/i)).toBeVisible();
  });

  test('scan log shows stage summary with stock and contract counts', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.goto('/screener/step-2-direction');
    // Stage summary must distinguish stock vs contract rejections
    await expect(page.getByText(/stock.*rejected|contract.*rejected/i)).toBeVisible();
  });

  test('DTE recommendation is shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText(/DTE.*21.*45|target DTE/i)).toBeVisible();
  });

  test('scan log resets when a new scan starts', async ({ page }) => {
    await stubApis(page);
    await page.route('**/api/scan', (r) => r.fulfill({ json: MOCK_SCAN }));
    await page.goto('/screener/step-1-universe');
    await page.getByRole('button', { name: /SPY ETF/ }).click();
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/stock score/i)).toBeVisible();
    // Start another scan — log should clear while scanning
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).toBeVisible();
    // While scanning, old log should not be visible
    await expect(page.getByText(/stock score/i)).not.toBeVisible();
  });

  test('CR-07: no regime badge when regime is PASS', async ({ page }) => {
    await stubApis(page); // regime: PASS
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText(/REGIME REJECT/i)).not.toBeVisible();
  });

  test('CR-07: regime badge visible on Direction page when regime is REJECT', async ({ page }) => {
    await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'REJECT', headline: 'Downtrend', metrics: [] } }));
    await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
    await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
    await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
    await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
    await page.goto('/screener/step-1-universe');
    // Trigger regime load (step 1 refreshes regime)
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText(/REGIME REJECT/i)).toBeVisible();
  });

  test('CR-07: confirmation dialog shown when scanning Bullish in REJECT regime', async ({ page }) => {
    await page.route('**/api/regime',   (r) => r.fulfill({ json: { overall: 'REJECT', headline: 'Downtrend', metrics: [] } }));
    await page.route('**/api/watchlist',(r) => r.fulfill({ json: [] }));
    await page.route('**/api/alerts',   (r) => r.fulfill({ json: [] }));
    await page.route('**/api/news*',    (r) => r.fulfill({ json: [] }));
    await page.route('**/api/portfolio',(r) => r.fulfill({ json: [] }));
    await page.goto('/screener/step-1-universe');
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Bullish/ }).click();
    // Stub scan so it doesn't actually fire
    await page.route('**/api/scan', (r) => r.fulfill({ json: { scan_id: 'x', timestamp: '', candidates: [], rejected: [] } }));
    await page.getByRole('button', { name: 'Run Scan' }).click();
    // Dialog must appear
    await expect(page.getByRole('dialog')).toBeVisible();
    await expect(page.getByText(/Market regime is REJECT/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Proceed anyway/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /Cancel/i })).toBeVisible();
  });

});
```

---

## 12b. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be 0 errors after EVERY file edit
npx playwright test e2e/tests/ws-c-scan-log-regime-gate.spec.ts --reporter=list
```

---

## 13. Completion report (paste all output before handing back)

```
## CR-03 + CR-07 Completion Report

### Files changed
[paste: git diff --stat HEAD]

### Typecheck
[paste: full output of `npm run typecheck` from frontend/]

### Playwright results
[paste: full output of `npx playwright test e2e/tests/ws-c-scan-log-regime-gate.spec.ts --reporter=list`]

### Screenshots produced
[list: e2e/screenshots/*.png]

### Known issues / deviations
[any deviations from spec]
```

**Iron law:** You may NOT write "done", "passing", or "complete" without pasting the actual command output above. "Should work" is not evidence.

---

## 14. Copy/paste prompt

```
Read `llm-contexts/03-scan-log-regime-gate.md` fully before writing any code.
It is your single source of truth — do not rely on memory or assumptions.

You are implementing Round 3 (CR-03 + CR-07) for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules, Zustand v5).

Your owned files:
- frontend/app/(frame)/screener/step-2-direction/page.tsx
- frontend/app/(frame)/screener/step-2-direction/page.module.css
- frontend/components/organisms/RunScanButton/index.tsx
- frontend/components/organisms/RunScanButton/index.module.css

Also create (do not modify any other file):
- frontend/e2e/tests/ws-c-scan-log-regime-gate.spec.ts   ← Playwright spec from Section 12a

Do NOT modify scanStore.ts, api.ts, universeStore.ts, or any file outside the list above.

Task: Add a persistent scan log panel to the Direction page (placeholder before scan,
rejection breakdown + stage summary + DTE recommendation after), and add a regime REJECT
warning badge + confirmation dialog gate to RunScanButton for Bullish scans.

VERIFICATION RULES (non-negotiable):
1. Run `npm run typecheck` from `frontend/` after EVERY file edit. Must stay 0 errors.
2. When all code changes are done, run the Playwright spec from Section 12a.
3. You may NOT claim anything is "done", "passing", or "complete" without pasting
   the actual command output. "Should work" is not evidence.
4. Produce the completion report from Section 13 with all outputs pasted inline.
5. Do NOT commit. Kenneth reviews the report and commits manually.
```
