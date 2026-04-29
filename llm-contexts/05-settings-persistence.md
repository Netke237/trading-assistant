# LLM Context — Settings Persistence (Workstream 05)

> **Self-contained.** Read this document fully before touching any code. Do not read any other file unless something is genuinely ambiguous after reading this document.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates one new file and makes one small wiring change in an existing file. No UI layout, no visual styling, no other page, no other store is touched.

**Goal:**
Persist the Settings page Custom tab's `customW` (score weights) and `customP` (indicator parameters) to `localStorage` using a new Zustand store (`settingsStore`) with `persist` middleware. The Settings page should hydrate these values from `localStorage` on load and write back on every change.

**What NOT to touch:**
- Any visual component, CSS class, or layout in `settings/page.tsx`
- The `WEIGHT_DEFAULTS`, `WEIGHT_HINTS`, `WEIGHT_PRESETS`, `METRICS_DEF`, `HORIZON_TABS` constants — they stay in the page file as-is
- `initCustomParams()` — stays in the page file; its output is used as the store default
- Any existing store (`scanStore`, `watchlistStore`, `watchedContractsStore`, `portfolioStore`)
- `types/domain.ts`, `styles/tokens.css`, `app/globals.css`, or any other file not in the owned list
- Any page other than `settings/page.tsx`

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/lib/settingsStore.ts` | **Create** | New Zustand store with `persist` middleware — holds `customW` and `customParams`, exposes setters and `resetToDefaults` |
| `frontend/app/(frame)/settings/page.tsx` | **Modify** | Replace the two `useState` calls for `customW` and `customP` inside `WeightsForm` with calls to `useSettingsStore()`; wire the Reset button in the footer to `resetToDefaults` |

These are the only two files you write. No other file is modified.

---

## Section 3 — Read-only references

| File | Why you read it |
|---|---|
| `frontend/lib/watchlistStore.ts` | Reference pattern for Zustand v5 `persist` with `version` + `migrate` |
| `frontend/app/(frame)/settings/page.tsx` | Current local state structure — read before modifying to understand `customW` and `customP` shape |

---

## Section 4 — Integration constraints

### Import statements for the new store

```ts
// frontend/lib/settingsStore.ts
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
```

### Zustand v5 `persist` middleware API

Zustand v5 uses a **double-call** pattern. The outer `()` after `create<T>` is required:

```ts
export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({ /* state + actions */ }),
    {
      name: 'bamendjou-settings',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      migrate: (persistedState, version) => { /* ... */ },
    }
  )
);
```

Do NOT use the v4 signature (`create(persist(...))` without the outer `()`). This project is on Zustand `^5.0.2` (confirmed in `frontend/package.json`).

### Current local state in `settings/page.tsx`

Inside `WeightsForm()`, the current state is:

```ts
// Line 325–326
const [customW, setCustomW] = useState<WeightMap>({ ...WEIGHT_DEFAULTS });
const [customP, setCustomP] = useState<CustomParams>(initCustomParams);
```

Where:
- `WeightMap` is `Record<WeightKey, number>` (five keys: `Trend | Pullback | Trigger | Event | Volatility`)
- `CustomParams` is `Record<WeightKey, Record<string, number>>` (same five keys; values are param-key → number maps)
- `WEIGHT_DEFAULTS` and `initCustomParams()` supply the defaults

### Exact replacement in `WeightsForm`

Replace the two `useState` lines with:

```ts
const { customW, customParams, setCustomW, setCustomParams, resetToDefaults } = useSettingsStore();
```

Then:
- Replace every `customP` reference with `customParams`
- Replace every `setCustomP` reference with `setCustomParams`
- The `resetCustom` function inside `WeightsForm` becomes a call to `resetToDefaults()`

### Footer Reset button

The outer `SettingsPage` has a sticky footer with a "Reset" button (line 62). Wire it to `resetToDefaults`:

```tsx
// In SettingsPage() — add this:
const { resetToDefaults } = useSettingsStore();

// Then on the Reset button:
<button type="button" className={styles.btn} onClick={resetToDefaults}>Reset</button>
```

### localStorage key

```
'bamendjou-settings'
```

This key must be exact — note: no colon prefix (the watchlist store uses `bamendjou:watchlist` with a colon; the settings store uses a hyphen to follow a slightly different convention intentionally established here).

### What does NOT change

- No new JSX, no new CSS classes, no new props
- The `horizon` tab state stays as `useState<WeightHorizon>` inside `WeightsForm` — it is not persisted
- The `WEIGHT_DEFAULTS`, `METRICS_DEF`, and `initCustomParams()` stay in the page file — the store imports only the types, not the constants

---

## Section 5 — CSS tokens

Complete token set from `frontend/styles/tokens.css`. Never hardcode colors.

### Dark theme (default — `[data-theme="dark"]` or `:root`)

```css
/* Backgrounds */
--bg-base:          #131722;
--bg-surface:       #1E2335;
--bg-surface-2:     #252B43;
--bg-surface-3:     #2A3152;

/* Borders */
--border-subtle:    #2A2E42;
--border-strong:    #363B54;

/* Text */
--text-primary:     #D1D4DC;
--text-secondary:   #787B86;
--text-dim:         #434651;

/* Status — PASS */
--pass:             #26A69A;
--pass-bg:          #0D201F;
--pass-border:      #1A3533;

/* Status — CAUTION */
--caution:          #F59F00;
--caution-bg:       #1F1A0D;
--caution-border:   #352E1A;

/* Status — REJECT */
--reject:           #EF5350;
--reject-bg:        #1F0E0D;
--reject-border:    #352020;

/* Status — NEUTRAL / PENDING */
--neutral:          #4A5568;
--neutral-bg:       #1A202C;

/* Accent */
--accent:           #2962FF;
--accent-hover:     #1E53E5;
--accent-dim:       #142B7A;
--accent-text:      #FFFFFF;

/* Spacing (4px base) */
--space-1:  4px;
--space-2:  8px;
--space-3:  12px;
--space-4:  16px;
--space-5:  20px;
--space-6:  24px;
--space-8:  32px;
--space-12: 48px;

/* Radius */
--radius-sm: 4px;
--radius-md: 6px;
--radius-lg: 10px;

/* Frame sizes */
--frame-topbar-h:            48px;
--frame-navrail-w:           64px;
--frame-navrail-w-expanded:  200px;
--frame-contextrail-w:       300px;
--frame-stepnav-h:           52px;
```

### Light theme override (`[data-theme="light"]`)

```css
--bg-base:        #F0F3FA;
--bg-surface:     #FFFFFF;
--bg-surface-2:   #F5F7FF;
--bg-surface-3:   #EBF0FF;
--border-subtle:  #DDE1F0;
--border-strong:  #C5CCE6;
--text-primary:   #131722;
--text-secondary: #5A6070;
--text-dim:       #9BA3B8;
--pass:           #1A9188;
--pass-bg:        #EDF7F6;
--pass-border:    #B3E0DC;
--caution:        #D4890A;
--caution-bg:     #FEF6E6;
--caution-border: #F5D38A;
--reject:         #D32F2F;
--reject-bg:      #FEECEC;
--reject-border:  #F5BCBC;
--neutral:        #64748B;
--neutral-bg:     #F1F5F9;
```

---

## Section 6 — Primitives & component reference

Included for completeness. The settings UI is not changing, so these are reference-only.

### `<Text>`
```tsx
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
```
Default: `size=13`, `tone="primary"`, `weight=400`.
No font-weight 600 on form labels — use `weight={400}`.

### `<Title>`
```tsx
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />
```

### `<Data>`
```tsx
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}   // optional
/>
```
Monospace, tabular-nums. Use for prices, scores, percentages.

### Component conventions
- Atoms → Molecules → Organisms — never skip levels.
- Each component lives in its own folder: `ComponentName/index.tsx` + `ComponentName.module.css`.
- No card shadows — use `border: 1px solid var(--border-subtle)`.
- Status tints use `color-mix(in srgb, var(--pass/caution/reject) N%, var(--bg-surface))`.
- CSS variables from `styles/tokens.css` — never hardcode colours.

---

## Section 7 — Domain types

These types must match the local state currently used in `settings/page.tsx` exactly.

### `WeightKey` (defined in `settings/page.tsx`, re-export from store)

```ts
type WeightKey = 'Trend' | 'Pullback' | 'Trigger' | 'Event' | 'Volatility';
```

### `CustomWeights`

This is the `WeightMap` type from `settings/page.tsx`:

```ts
type CustomWeights = Record<WeightKey, number>;
// Shape: { Trend: number; Pullback: number; Trigger: number; Event: number; Volatility: number }
```

### `CustomParams`

This is the `CustomParams` type from `settings/page.tsx`:

```ts
type CustomParams = Record<WeightKey, Record<string, number>>;
// Shape:
// {
//   Trend:      { longMa: number; medMa: number; adxPeriod: number }
//   Pullback:   { shortMa: number; rsiPeriod: number }
//   Trigger:    { volLookback: number; volMultiplier: number }
//   Event:      { earningsBuffer: number; fomcBuffer: number; divBuffer: number }
//   Volatility: { ivRankLookback: number; hvLookback: number }
// }
```

Note: only metrics that have both a `param` AND a `presets` field contribute a key to `CustomParams`. Metrics without `presets` (e.g. "Higher-highs pattern", "Long MA buffer") are excluded. See Section 9 for the exact default values.

### `SettingsState`

```ts
interface SettingsState {
  customW:      CustomWeights;
  customParams: CustomParams;
  setCustomW:        (w: CustomWeights) => void;
  setCustomParams:   (p: CustomParams) => void;
  resetToDefaults:   () => void;
}
```

---

## Section 8 — Zustand stores

### Existing store pattern summary

All stores follow the same import shape:
```ts
import { create } from 'zustand';
// Persisted stores also import:
import { persist, createJSONStorage } from 'zustand/middleware';
```

Stores that persist use the double-call pattern (`create<T>()(persist(...))`). Stores that do not persist use the single-call pattern (`create<T>((...) => ...)`).

### NEW: `settingsStore.ts` — complete implementation

```ts
/*
 * Settings store — Zustand with localStorage persistence.
 *
 * Persists the Custom tab's score weights (customW) and indicator
 * parameters (customParams) across page refreshes. All other settings
 * tabs (Broker, Appearance, Alerts) use local component state and are
 * NOT persisted here.
 *
 * Default values mirror the Swing preset so Custom starts populated.
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

export const SETTINGS_STORAGE_KEY = 'bamendjou-settings';

export type WeightKey = 'Trend' | 'Pullback' | 'Trigger' | 'Event' | 'Volatility';
export type CustomWeights = Record<WeightKey, number>;
export type CustomParams  = Record<WeightKey, Record<string, number>>;

// Default weights — mirror WEIGHT_DEFAULTS in settings/page.tsx
const DEFAULT_WEIGHTS: CustomWeights = {
  Trend:      25,
  Pullback:   20,
  Trigger:    20,
  Event:      15,
  Volatility: 20,
};

// Default params — mirror initCustomParams() output (Swing preset values)
const DEFAULT_PARAMS: CustomParams = {
  Trend:      { longMa: 200, medMa: 50, adxPeriod: 14 },
  Pullback:   { shortMa: 20, rsiPeriod: 14 },
  Trigger:    { volLookback: 20, volMultiplier: 1.5 },
  Event:      { earningsBuffer: 7, fomcBuffer: 3, divBuffer: 3 },
  Volatility: { ivRankLookback: 252, hvLookback: 20 },
};

interface SettingsState {
  customW:      CustomWeights;
  customParams: CustomParams;
  setCustomW:        (w: CustomWeights) => void;
  setCustomParams:   (p: CustomParams) => void;
  resetToDefaults:   () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      customW:      { ...DEFAULT_WEIGHTS },
      customParams: structuredClone(DEFAULT_PARAMS),
      setCustomW: (w) => set({ customW: w }),
      setCustomParams: (p) => set({ customParams: p }),
      resetToDefaults: () => set({
        customW:      { ...DEFAULT_WEIGHTS },
        customParams: structuredClone(DEFAULT_PARAMS),
      }),
    }),
    {
      name: SETTINGS_STORAGE_KEY,
      storage: createJSONStorage(() => localStorage),
      version: 1,
      migrate: (persistedState, version) => {
        const prev = (persistedState as Partial<SettingsState> | null) ?? {};
        if (version < 1) {
          return {
            customW:      prev.customW      ?? { ...DEFAULT_WEIGHTS },
            customParams: prev.customParams ?? structuredClone(DEFAULT_PARAMS),
          } as SettingsState;
        }
        return prev as SettingsState;
      },
    }
  )
);
```

---

## Section 9 — Mock data (exact default values)

These are the exact default values extracted from `settings/page.tsx`. The store must use these same values when `localStorage` is empty.

### `customW` defaults (from `WEIGHT_DEFAULTS` constant)

| Key | Default value |
|---|---|
| `Trend` | `25` |
| `Pullback` | `20` |
| `Trigger` | `20` |
| `Event` | `15` |
| `Volatility` | `20` |

Sum = 100.

### `customParams` defaults (from `initCustomParams()` — uses `presets.Swing` for each metric)

| Component | Param key | Default value (Swing preset) |
|---|---|---|
| `Trend` | `longMa` | `200` |
| `Trend` | `medMa` | `50` |
| `Trend` | `adxPeriod` | `14` |
| `Pullback` | `shortMa` | `20` |
| `Pullback` | `rsiPeriod` | `14` |
| `Trigger` | `volLookback` | `20` |
| `Trigger` | `volMultiplier` | `1.5` |
| `Event` | `earningsBuffer` | `7` |
| `Event` | `fomcBuffer` | `3` |
| `Event` | `divBuffer` | `3` |
| `Volatility` | `ivRankLookback` | `252` |
| `Volatility` | `hvLookback` | `20` |

Note: `initCustomParams()` only records params where `m.param && m.presets` are both defined. Metrics without a `presets` field ("Higher-highs pattern", "Long MA buffer", "Volume on retrace", "Candle pattern", "Breakout close", "IV Percentile", "Term structure") contribute no key to `customParams`.

---

## Section 10 — Task spec

### Step-by-step

**Step 1 — Create `frontend/lib/settingsStore.ts`**

Create the file using the complete implementation shown in Section 8. Verify:
- `SETTINGS_STORAGE_KEY = 'bamendjou-settings'`
- `DEFAULT_WEIGHTS` matches Section 9 exactly
- `DEFAULT_PARAMS` matches Section 9 exactly
- The `persist` middleware uses `version: 1` and a `migrate` stub

**Step 2 — Derive types from the page (they are already in the store)**

The types `WeightKey`, `CustomWeights`, `CustomParams` are defined in the store file (Section 8). They must match the shapes used in `settings/page.tsx` exactly. Do not duplicate these types — the page will import them from the store.

**Step 3 — Modify `frontend/app/(frame)/settings/page.tsx`**

Make these surgical changes only:

1. Add an import at the top of the file:
   ```ts
   import { useSettingsStore } from '@/lib/settingsStore';
   import type { WeightKey, CustomWeights, CustomParams } from '@/lib/settingsStore';
   ```

2. Remove the type aliases `WeightMap` and `CustomParams` that are currently declared in the page file (lines ~185, ~216), since they are now imported from the store. Note: `WeightKey` is also declared in the page — remove it too.

3. In `WeightsForm()`, replace:
   ```ts
   const [customW, setCustomW] = useState<WeightMap>({ ...WEIGHT_DEFAULTS });
   const [customP, setCustomP] = useState<CustomParams>(initCustomParams);
   ```
   With:
   ```ts
   const { customW, customParams, setCustomW, setCustomParams, resetToDefaults } = useSettingsStore();
   ```

4. In `WeightsForm()`, replace the inline `resetCustom` function and its usages:
   - Remove: `function resetCustom() { setCustomW(...); setCustomP(...); }`
   - Replace `onClick={resetCustom}` on the "Reset to Swing defaults" button with `onClick={resetToDefaults}`

5. Replace every `customP` reference with `customParams`, and every `setCustomP` reference with `setCustomParams`. References to find:
   - `isCustom ? customP : ...` → `isCustom ? customParams : ...`
   - `setCustomP((prev) => ...)` inside `handleParamChange` → `setCustomParams((prev) => ...)`
   - `customP[compKey]?.[m.param.key]` inside `getParamValue` → `customParams[compKey]?.[m.param.key]`

6. In the outer `SettingsPage()` component, wire the footer Reset button:
   ```tsx
   // Add at the top of SettingsPage():
   const { resetToDefaults } = useSettingsStore();
   
   // Change the footer Reset button from:
   <button type="button" className={styles.btn}>Reset</button>
   // To:
   <button type="button" className={styles.btn} onClick={resetToDefaults}>Reset</button>
   ```

7. The `WeightMap` type alias in the page file is used by `WEIGHT_PRESETS`. Since `CustomWeights` is now imported and has the same shape as `WeightMap`, replace the `WeightMap` type alias throughout with `CustomWeights`. If this causes issues (e.g. `WEIGHT_PRESETS` uses `WeightMap`), simply alias: `type WeightMap = CustomWeights;` until the rename is complete.

**Step 4 — Verify persistence**

Manual test:
1. Navigate to `/settings`
2. Click the "Custom" horizon tab
3. Drag the Trend weight slider to a new value (e.g. 35)
4. Change a parameter (e.g. set Long-term MA period to 100)
5. Refresh the page (F5)
6. Navigate back to `/settings` → Custom tab
7. Confirm the slider shows 35 and the MA period shows 100

**Step 5 — Verify Reset**

1. Change a Custom weight
2. Click the "Reset" button in the sticky footer
3. Confirm all weights return to defaults (Trend=25, Pullback=20, Trigger=20, Event=15, Volatility=20)
4. Refresh — confirm the reset values persisted

### Acceptance criteria

- Custom weights survive a page refresh (localStorage key `bamendjou-settings`)
- Custom params survive a page refresh
- Other tabs (Broker, Appearance, Alerts) are unaffected
- `npm run typecheck` is clean — no type errors
- No changes to any UI component or visual layout in the settings page

---

## Section 11 — Hard rules

These rules are non-negotiable. Violating any of them will break the project.

1. **No Tailwind, styled-components, or CSS-in-JS.** Use CSS Modules only.
2. **No inline `style={{}}` objects** except computed one-off values like `style={{ width: \`${pct}%\` }}`.
3. **No hardcoded colors.** Always use CSS custom properties from `tokens.css`.
4. **No invented Status labels.** The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. **No font-weight 600 on form labels.** Use `weight={400}`.
6. **No card box-shadows.** Use `border: 1px solid var(--border-subtle)`.
7. **Never skip component hierarchy levels** (atom → molecule → organism).
8. **Do not commit with a failing `npm run typecheck`.** Run it before every commit.
9. **Do not touch `node_modules/` or `package-lock.json`** unless explicitly asked.
10. **Use Zustand v5 `persist` from `zustand/middleware`.** The project is on `^5.0.2`. Use the double-call pattern `create<T>()(persist(...))`.
11. **Do NOT change any visual component in `settings/page.tsx`** — only replace `useState` calls with store calls. No JSX changes beyond the Reset button's `onClick`.
12. **Do NOT add a new store for anything other than `settingsStore`.** This workstream creates exactly one new file.
13. **localStorage key must be exactly `'bamendjou-settings'`** (hyphen, no colon).
14. **The store must have `version: 1`** and a `migrate` function for future-proofing.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev       # starts on localhost:3001 — navigate to /settings

npm run typecheck  # must be clean — run before committing

# Manual persistence test:
# 1. Open /settings → click Custom tab
# 2. Change Trend slider to a non-default value
# 3. Refresh page (F5 or Ctrl+R)
# 4. Confirm value persisted in Custom tab
# 5. Click Reset → confirm weights return to defaults
# 6. Refresh → confirm reset values also persisted
```

---

## Section 13 — Copy/paste prompt

Paste this entire block to the implementing LLM:

---

You are working on the Bamendjou options screener — a Next.js 15 / TypeScript / Zustand project.

Your task document is at: `llm-contexts/05-settings-persistence.md` in the project root.
Read that file fully before writing any code.

**Summary of what you must do (details and exact code in the context doc):**

You own exactly two files:
1. **Create** `frontend/lib/settingsStore.ts` — a new Zustand v5 store with `persist` middleware that holds `customW` (score weights) and `customParams` (indicator parameters), persisted to `localStorage` under the key `'bamendjou-settings'`.
2. **Modify** `frontend/app/(frame)/settings/page.tsx` — replace the two `useState` calls for `customW` and `customP` inside `WeightsForm` with calls to `useSettingsStore()`. Wire the footer Reset button to `resetToDefaults`. Do not change any JSX layout, CSS class, or visual element beyond these wiring changes.

**Critical rules:**
- Zustand v5: use `create<T>()(persist(...))` — the double-call pattern.
- localStorage key: `'bamendjou-settings'` (exact — no colon, hyphen only).
- Store version: `version: 1` with a `migrate` stub.
- Do NOT touch any file outside the two owned files.
- After modifying, run `npm run typecheck` from `frontend/` and fix any errors before finishing.
- The default values for `customW` and `customParams` are documented in section 9 of the context doc — use those exact values.

Start by reading `llm-contexts/05-settings-persistence.md`.

---
