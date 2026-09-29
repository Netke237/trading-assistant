# LLM Context — Round 4: Execution Parameters Panel (CR-02)

> **Historical snapshot** — calls Direction+Horizon "Step 2"; `05-step-reorder.md` later moved it to Step 3, matching CLAUDE.md's current `step-3-direction`. See `CLAUDE.md`.

**Workstream:** CR-02 — Add an "Execution Parameters" panel to the Direction + Horizon page (Step 2).
**Conflict class:** Medium — modifies `RunScanButton`, `api.ts`, and `scanStore.ts`. Do not change any exported type signatures beyond what is specified.

**Prerequisite:** Round 3 (CR-03 + CR-07) must be merged before starting this workstream. The Direction page and RunScanButton files will have additional content from that round.

---

## 1. Mission

The area below the horizon picker on Step 2 (Direction + Horizon) is partly used for the scan log panel (added in Round 3). Above that log panel, add a collapsible "Execution Parameters" panel. Each row shows one scoring/contract parameter, its default value for the selected horizon, and an editable override input. Overrides apply to the current scan only and never touch saved settings.

**The single most important constraint:** Do NOT touch `settingsStore.ts`, scoring rule components, or any file outside the owned-files list.

---

## 2. Owned files

| File path | Status | Purpose |
|---|---|---|
| `frontend/app/(frame)/screener/step-2-direction/page.tsx` | Modify | Add execution params panel UI |
| `frontend/app/(frame)/screener/step-2-direction/page.module.css` | Modify | CSS for params panel |
| `frontend/lib/scanStore.ts` | Modify | Add `scanOverrides` field + `setScanOverrides` action |
| `frontend/lib/api.ts` | Modify | Add `overrides` parameter to `postScan` |
| `frontend/components/organisms/RunScanButton/index.tsx` | Modify | Read `scanOverrides` from store, pass to `api.postScan` |
| `frontend/e2e/tests/ws-d-execution-params.spec.ts` | Create | Playwright spec (6 tests) |

---

## 3. Read-only references

| File | Why |
|---|---|
| `frontend/lib/scanStore.ts` | Existing interface — add fields, do not change existing ones |
| `frontend/components/organisms/RunScanButton/index.tsx` | Existing `api.postScan` call — update to pass overrides |
| `frontend/app/(frame)/screener/step-2-direction/page.module.css` | Existing `.logSection` CSS — place params panel above it |
| `frontend/styles/tokens.css` | All CSS variables |
| `backend/config/scoring_rules.yaml` | Defaults per horizon — values listed inline in Section 9 |
| `backend/config/contract_rules.yaml` | Contract parameter defaults — values listed inline in Section 9 |

---

## 4. Integration constraints

### `scanStore.ts` additions (minimal — add only these)

```ts
// Add to ScanStoreState interface:
scanOverrides: Record<string, number | boolean>;
setScanOverrides: (o: Record<string, number | boolean>) => void;

// Add to create() initial state:
scanOverrides: {},

// Add to create() actions:
setScanOverrides: (o) => set({ scanOverrides: o }),
```

### `api.ts` — update `postScan` signature

```ts
// Current (before this workstream):
postScan: (universe: string[], direction: string, horizon: string, filters?) =>
  post<ScanResult>(
    '/api/scan',
    { universe, direction, horizon, overrides: {}, ...filters },
  ),

// After this workstream:
postScan: (universe: string[], direction: string, horizon: string, filters?, overrides?: Record<string, number | boolean>) =>
  post<ScanResult>(
    '/api/scan',
    { universe, direction, horizon, overrides: overrides ?? {}, ...filters },
  ),
```

### `RunScanButton/index.tsx` — read overrides before postScan call

```ts
// Read overrides at click-time (same .getState() pattern already used for other stores):
const scanOverrides = useScanStore.getState().scanOverrides;

// Pass to api.postScan (add as 5th argument):
api.postScan(universe, direction, horizon, filters, scanOverrides)
```

### Direction page — panel sync

The panel is a collapsible section. When the user changes any param input, call:
```ts
useScanStore.getState().setScanOverrides({ ...currentOverrides, [key]: value });
```

When the user changes the horizon, re-initialise the override inputs to the new horizon's defaults (but DO NOT call `setScanOverrides` until a user edits a value — initial defaults should not appear as "overrides").

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
- No font-weight 600 on form labels — use `weight={400}`
- No card shadows — `border: 1px solid var(--border-subtle)`

---

## 7. Domain types (relevant subset)

```ts
// From frontend/lib/scanStore.ts (existing):
export interface ScanContext {
  universe:  string;
  direction: Direction;
  horizon:   string;   // "Swing (5–15d)"
}

// New additions to ScanStoreState (you add these):
scanOverrides: Record<string, number | boolean>;
setScanOverrides: (o: Record<string, number | boolean>) => void;
```

---

## 8. Zustand stores

### `scanStore.ts` (modify — add only `scanOverrides` + `setScanOverrides`)

Existing interface excerpt (do not change these):

```ts
interface ScanStoreState {
  scanState:       ScanState;
  context:         ScanContext | null;
  regime:          Status;
  scanResult:      ScanResult | null;
  rejectedLog:     { symbol: string; reason: string }[];
  // ... existing actions ...

  // ADD ONLY:
  scanOverrides: Record<string, number | boolean>;
  setScanOverrides: (o: Record<string, number | boolean>) => void;
}
```

Default seed: `scanOverrides: {}` (empty = use backend defaults).

---

## 9. Parameter defaults per horizon (from YAML — use these exact values)

### Keys for `scanOverrides` (camelCase — backend expects these key names)

| Parameter | Key | Intraday | Swing | Position | Unit |
|---|---|---|---|---|---|
| IV Rank pass threshold | `iv_rank_pass_max` | null (skip) | 34 | 44 | 0–100 |
| RSI floor | `rsi_floor` | 44 | 44 | 48 | 0–100 |
| MACD fast | `macd_fast` | 5 | 8 | 12 | int |
| MACD slow | `macd_slow` | 13 | 21 | 26 | int |
| MACD signal | `macd_signal` | 3 | 5 | 9 | int |
| EMA condition active | `ema_required` | false | true | true | bool |
| Max delta | `max_delta` | 0.85 | 0.85 | 0.85 | 0.00–1.00 |
| ATR caution max (candle body) | `atr_caution_max` | 2.5 | 2.5 | 2.5 | decimal |
| Swing high lookback (bars) | `swing_high_lookback_bars` | 20 | 40 | 75 | int |
| Bid-ask spread ceiling | `max_bid_ask_spread_pct` | 0.20 | 0.20 | 0.20 | 0.00–1.00 |
| Event reject days | `event_reject_days` | 1 | 7 | 30 | days |
| Event caution days | `event_caution_days` | 3 | 21 | 60 | days |

**Custom horizon:** Borrow Swing defaults (the most common preset).

**IV Rank for Intraday:** When `iv_rank_pass_max` is null for Intraday, do not render that row, or render it greyed-out as "N/A (not scored for Intraday)".

**EMA condition:** This is a boolean toggle (on/off), not a number input. When off, the EMA crossing check is skipped.

---

## 10. Task spec

### Panel placement

- Position: between the horizon picker section and the existing scan log panel
- Collapsed by default (show/hide toggle)
- Header: "Execution Parameters" with a small "▸ Expand" / "▾ Collapse" chevron button
- Collapsed state: just the header row is visible

### Panel layout

Each row: `[Parameter label]  [default value, dim]  [override input]`

- Label: `<Text size={12}>` left-aligned
- Default: `<Data size={11} tone="dim">` — shows the horizon's default value (e.g. "34")
- Input: `<input type="number">` for numeric params, a toggle button for boolean (EMA condition)

When the user edits a value: call `setScanOverrides({ ...current, [key]: parsedValue })`
When the user clears a value back to default: remove that key from overrides (`setScanOverrides({ ...current })` without the key).

### "Reset to defaults" button

At the bottom of the panel: a text button "Reset to defaults" that calls `setScanOverrides({})`.

### Horizon change resets inputs

When the user switches horizon (via the existing segment buttons), re-initialise the panel's local input state to the new horizon's defaults. Any overrides in the store are also cleared: `setScanOverrides({})`.

---

## 11. Hard rules

1. No Tailwind, styled-components, or CSS-in-JS.
2. No `style={{}}` except computed one-off values.
3. No hardcoded colours — always CSS custom properties.
4. No invented Status labels.
5. `npm run typecheck` must be clean after every file edit.
6. Do NOT touch `settingsStore.ts`, `universeStore.ts`, `watchlistStore.ts`, or any store besides `scanStore.ts`.
7. Do NOT change existing `ScanContext`, `ScanResult`, or `ScanState` interfaces.
8. Do NOT commit.

---

## 12a. Playwright spec

Create `frontend/e2e/tests/ws-d-execution-params.spec.ts`:

```typescript
import { test, expect } from '@playwright/test';

async function stubApis(page: import('@playwright/test').Page) {
  await page.route('**/api/regime',    (r) => r.fulfill({ json: { overall: 'PASS', headline: 'Test', metrics: [] } }));
  await page.route('**/api/watchlist', (r) => r.fulfill({ json: [] }));
  await page.route('**/api/alerts',    (r) => r.fulfill({ json: [] }));
  await page.route('**/api/news*',     (r) => r.fulfill({ json: [] }));
  await page.route('**/api/portfolio', (r) => r.fulfill({ json: [] }));
}

test.describe('WS-D: Execution Parameters Panel (CR-02)', () => {

  test('panel is collapsed by default on Step 2', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await expect(page.getByText('Execution Parameters')).toBeVisible();
    // Rows should be hidden (collapsed)
    await expect(page.getByText('IV Rank pass threshold')).not.toBeVisible();
  });

  test('panel expands to show parameter rows', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByText('Execution Parameters').click();
    await expect(page.getByText('IV Rank pass threshold')).toBeVisible();
    await expect(page.getByText('RSI floor')).toBeVisible();
    await expect(page.getByText('MACD fast')).toBeVisible();
  });

  test('default values shown for Swing horizon', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    // IV Rank default for Swing is 34
    await expect(page.getByText('34')).toBeVisible();
    // RSI floor default for Swing is 44
    await expect(page.getByText('44')).toBeVisible();
  });

  test('overrides are sent in scan request when user edits a value', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { capturedBody = route.request().postDataJSON(); } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-2-direction');
    await page.getByText('Execution Parameters').click();
    // Change RSI floor from 44 to 50
    const rsiInput = page.getByLabel(/RSI floor/i);
    await rsiInput.fill('50');
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    expect(capturedBody?.overrides).toBeDefined();
    expect((capturedBody?.overrides as Record<string, unknown>)['rsi_floor']).toBe(50);
  });

  test('reset to defaults clears overrides', async ({ page }) => {
    let lastBody: Record<string, unknown> | null = null;
    await stubApis(page);
    await page.route('**/api/scan', async (route) => {
      try { lastBody = route.request().postDataJSON(); } catch { /* ignore */ }
      await route.fulfill({ json: { scan_id: 't', timestamp: '', candidates: [], rejected: [] } });
    });
    await page.goto('/screener/step-2-direction');
    await page.getByText('Execution Parameters').click();
    await page.getByLabel(/RSI floor/i).fill('55');
    await page.getByRole('button', { name: /Reset to defaults/i }).click();
    await page.getByRole('button', { name: 'Run Scan' }).click();
    await expect(page.getByText('SCANNING')).not.toBeVisible({ timeout: 10000 });
    // After reset, overrides should be empty object
    expect(lastBody?.overrides).toEqual({});
  });

  test('switching horizon resets panel to new horizon defaults', async ({ page }) => {
    await stubApis(page);
    await page.goto('/screener/step-2-direction');
    await page.getByRole('button', { name: /Swing/ }).click();
    await page.getByText('Execution Parameters').click();
    // Swing: event_reject_days default = 7
    await expect(page.getByText('7')).toBeVisible();
    // Switch to Position: event_reject_days default = 30
    await page.getByRole('button', { name: /Position/ }).click();
    await expect(page.getByText('30')).toBeVisible();
    await expect(page.getByText('7')).not.toBeVisible();
  });

});
```

---

## 12b. Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001
npm run typecheck    # must be 0 errors after EVERY file edit
npx playwright test e2e/tests/ws-d-execution-params.spec.ts --reporter=list
```

---

## 13. Completion report

```
## CR-02 Completion Report

### Files changed
[paste: git diff --stat HEAD]

### Typecheck
[paste: full output of `npm run typecheck` from frontend/]

### Playwright results
[paste: full output of `npx playwright test e2e/tests/ws-d-execution-params.spec.ts --reporter=list`]

### Known issues / deviations
[any deviations from spec]
```

**Iron law:** You may NOT write "done", "passing", or "complete" without pasting the actual command output above.

---

## 14. Copy/paste prompt

```
Read `llm-contexts/04-execution-params.md` fully before writing any code.
It is your single source of truth — do not rely on memory or assumptions.

You are implementing Round 4 (CR-02) for the Bamendjou options screener
(Next.js 15, TypeScript strict, CSS Modules, Zustand v5).

PREREQUISITE: Round 3 (CR-03 + CR-07) must already be merged before you start.
Read the current state of your owned files before editing.

Your owned files:
- frontend/app/(frame)/screener/step-2-direction/page.tsx
- frontend/app/(frame)/screener/step-2-direction/page.module.css
- frontend/lib/scanStore.ts              (add scanOverrides field only)
- frontend/lib/api.ts                    (add overrides param to postScan only)
- frontend/components/organisms/RunScanButton/index.tsx   (read + pass overrides)

Also create (do not modify any other file):
- frontend/e2e/tests/ws-d-execution-params.spec.ts   ← Playwright spec from Section 12a

Do NOT touch settingsStore.ts or any file outside this list.

Task: Add a collapsible "Execution Parameters" panel on the Direction page showing
per-horizon scoring defaults with editable override inputs. Overrides are stored in
scanStore.scanOverrides and passed to api.postScan on each scan run.

VERIFICATION RULES (non-negotiable):
1. Run `npm run typecheck` from `frontend/` after EVERY file edit. Must stay 0 errors.
2. When all code changes are done, run the Playwright spec from Section 12a.
3. You may NOT claim anything is "done", "passing", or "complete" without pasting
   the actual command output. "Should work" is not evidence.
4. Produce the completion report from Section 13 with all outputs pasted inline.
5. Do NOT commit. Kenneth reviews the report and commits manually.
```
