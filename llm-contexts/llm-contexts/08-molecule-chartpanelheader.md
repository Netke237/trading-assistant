# LLM Context — ChartPanelHeader molecule

> Read this document fully before touching any code.
> It is the single source of truth for the ChartPanelHeader workstream.

---

## Section 1 — Mission

**Conflict class: Zero conflict** — this workstream owns only `components/molecules/ChartPanelHeader/`.

**Goal:** Complete and polish the `ChartPanelHeader` molecule. The component currently renders correctly for its one active usage site (`InlineChartPanel`) but has a narrow props interface (`symbol` + `onClose` only). The task is to:

1. Audit the current props shape against every usage site.
2. Decide whether the interface needs extending (e.g., a `label` prop to replace the hardcoded `"Chart"` title, a `timeframe` prop to replace the hardcoded `"1D · 120 bars"` subtitle).
3. Fix any issues found — missing prop, hardcoded string, token violation, layout gap — **inside the molecule only**.
4. Ensure the CSS module is complete and uses only CSS custom properties.

**Do NOT touch the files that use ChartPanelHeader** (e.g., `InlineChartPanel`, step-3, step-4). Only fix `index.tsx` and `ChartPanelHeader.module.css`.

---

## Section 2 — Owned files

| File | Action |
|---|---|
| `frontend/components/molecules/ChartPanelHeader/index.tsx` | Modify / complete |
| `frontend/components/molecules/ChartPanelHeader/ChartPanelHeader.module.css` | Modify / complete |

These are the **only two files you may edit**.

---

## Section 3 — Read-only references

The following files import `ChartPanelHeader`. Understand them for context; do not modify them.

| File | How it uses ChartPanelHeader |
|---|---|
| `frontend/components/organisms/InlineChartPanel/index.tsx` | Passes `symbol` (string) and `onClose` (function) — no other props. |

**Step 3 (`step-3-regime/page.tsx`) does NOT import ChartPanelHeader.** Step 3 builds its own inline index-chart headers manually (`<header className={pageStyles.indexHeader}>`). That is intentional — the index cards are display-only and have no close action. The molecule is not used there.

**Step 4 (`step-4-ranking/page.tsx`) does NOT import ChartPanelHeader.** Step 4 uses a `SymbolHeader` molecule in its right panel and `CandlestickChart` directly.

The only consumer of `ChartPanelHeader` in the current codebase is `InlineChartPanel`.

---

## Section 4 — Integration constraints

### Import path

```ts
import { ChartPanelHeader } from '@/components/molecules/ChartPanelHeader';
```

### Current props interface (read from `index.tsx`)

```ts
interface ChartPanelHeaderProps {
  symbol:  string;       // required — ticker shown in <Data> + passed to WatchStar
  onClose: () => void;  // required — fires when the X button is clicked
}
```

### Recommended extended interface

The current hardcoded strings `"Chart"` (title) and `"1D · 120 bars"` (subtitle) are not configurable. Any future consumer that wants a different label or timeframe descriptor must fork the component or override via CSS. The recommended enhancement is:

```ts
interface ChartPanelHeaderProps {
  symbol:     string;          // required — ticker label + WatchStar key
  onClose:    () => void;      // required — close button handler
  label?:     string;          // optional — panel title, default "Chart"
  timeframe?: string;          // optional — descriptor, default "1D · 120 bars"
}
```

### Atoms and primitives used internally

| Import | Role |
|---|---|
| `Text` (primitive) | Panel title ("Chart") and timeframe label ("1D · 120 bars") |
| `Data` (primitive) | Ticker symbol — monospace, tabular-nums |
| `IconButton` (atom) | Close button — ghost 32 × 32, aria-label required |
| `WatchStar` (atom) | Star toggle for the symbol; size="sm" |

### How the one host passes props

```tsx
// InlineChartPanel/index.tsx
<ChartPanelHeader symbol={symbol} onClose={onClose} />
// symbol is a string from InlineChartPanelProps (e.g. "AAPL")
// onClose is the prop passed down from the parent page
```

No label or timeframe is passed — so both must default gracefully if you extend the interface.

---

## Section 5 — CSS tokens

All colour and spacing values come from `frontend/styles/tokens.css`. Never hardcode hex values.

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

## Section 6 — Primitives and component reference

### `<Text>`

```tsx
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
```

Default: `size=13`, `tone="primary"`, `weight=400`.
No font-weight 600 on form labels.

### `<Title>`

```tsx
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />
```

### `<Data>`

```tsx
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}  // optional
/>
```

Monospace, tabular-nums. Use for prices, scores, percentages, and tickers.

### Which primitives ChartPanelHeader uses internally

| Primitive | Usage in ChartPanelHeader |
|---|---|
| `Text` | Panel title label ("Chart") and timeframe descriptor ("1D · 120 bars") |
| `Data` | Ticker symbol (monospace) |

### Key atoms used by ChartPanelHeader

| Atom | Props used | Notes |
|---|---|---|
| `IconButton` | `aria-label`, `onClick`, children (SVG) | Default size `"md"` (32 × 32) — no override needed here |
| `WatchStar` | `symbol`, `size="sm"` | Writes to `watchlistStore`; renders only when `symbol` is truthy |

---

## Section 7 — Domain types

`ChartPanelHeader` is a display-only molecule. It does not depend on `WatchlistRow`, `PortfolioPosition`, or any other domain type from `types/domain.ts`.

Its entire type surface is its own props:

```ts
interface ChartPanelHeaderProps {
  symbol:     string;          // ticker; also the WatchStar key
  onClose:    () => void;      // close-button click handler
  label?:     string;          // panel title — default "Chart"
  timeframe?: string;          // subtitle descriptor — default "1D · 120 bars"
}
```

No domain types from `types/domain.ts` are required.

---

## Section 8 — Zustand stores

**This molecule does not use any Zustand store.**

`WatchStar` (used internally) writes to `watchlistStore`, but `ChartPanelHeader` itself holds no store subscriptions and no local state beyond what React handles via prop callbacks.

---

## Section 9 — Mock data (exact values)

The molecule is used through `InlineChartPanel`. An example invocation with real mock values from `MOCK_WATCHLIST` (as driven by Step 4 or a watchlist row):

```tsx
// Minimal usage — matches the current InlineChartPanel call:
<ChartPanelHeader
  symbol="AAPL"
  onClose={() => setChartOpen(false)}
/>

// Extended usage if label/timeframe props are added:
<ChartPanelHeader
  symbol="AAPL"
  label="Chart"
  timeframe="1D · 120 bars"
  onClose={() => setChartOpen(false)}
/>

// Another candidate from MOCK_WATCHLIST:
<ChartPanelHeader
  symbol="NVDA"
  onClose={() => setChartOpen(false)}
/>
```

The full mock symbol list (from `MOCK_WATCHLIST`) that can flow through this header:
`AAPL`, `NVDA`, `MSFT`, `META`, `GOOGL`, `AMZN`, `AMD`, `TSLA`, `NFLX`, `INTC`.

---

## Section 10 — Task spec

### Current state audit

**Component is functionally complete for its one usage site.** It renders correctly when `symbol` and `onClose` are provided. No TypeScript errors exist in the current form.

**Issues and polish items to address:**

1. **Hardcoded label "Chart"** — `<Text size={14} weight={600}>Chart</Text>` is hardcoded. Any future consumer (e.g., a watchlist slide-out panel) may need a different label. Add an optional `label?: string` prop with default `"Chart"`.

2. **Hardcoded timeframe "1D · 120 bars"** — hardcoded in `<Text size={11} tone="dim">1D · 120 bars</Text>`. Add an optional `timeframe?: string` prop with default `"1D · 120 bars"`.

3. **font-weight 600 on the title** — `<Text size={14} weight={600}>Chart</Text>` uses weight 600 on what is effectively a label. Project rules say "no font-weight 600 on form labels". While this is a panel heading (not a form label), consider dropping to `weight={500}` for consistency with the rest of the header typography pattern used in organisms.

4. **`titleGroup` uses `align-items: center`** — the `Data` ticker and `Text` timeframe have different font sizes (13 and 11). Baseline alignment (`align-items: baseline`) would look cleaner and is consistent with InlineChartPanel's own `.titleGroup` style which uses `align-items: baseline`. Note: InlineChartPanel's CSS module has a `.titleGroup { align-items: baseline }` rule while ChartPanelHeader's CSS uses `align-items: center`. These should agree — prefer `baseline` for text-mixed rows.

5. **No `gap` customization** — the current `.titleGroup` gap is `var(--space-2)` (8 px). Between the `Data` ticker and the `WatchStar` icon, 8 px is correct. Between the `Text` title and the `Data` ticker, `var(--space-2)` also works. No change needed here.

6. **Missing `flex-shrink: 0`** — the `<header>` inside a flex column parent (`InlineChartPanel`'s `.panel`) can shrink if the panel height is constrained. The InlineChartPanel CSS already sets `flex-shrink: 0` on its own `.header` class, but since `ChartPanelHeader` renders its own `<header>` element, the host cannot apply `flex-shrink: 0` to it without a wrapper. Add `flex-shrink: 0` to `.root` in the CSS module.

### Acceptance criteria

- Component renders without TypeScript errors (`npm run typecheck` clean).
- All props are typed, with JSDoc comments for optional props showing their default values.
- CSS module uses only CSS custom properties — no hardcoded hex or px colours.
- Optional `label` and `timeframe` props default correctly so existing usage in `InlineChartPanel` (which passes neither) continues to work unchanged.
- `align-items` in `.titleGroup` is `baseline` (matches the InlineChartPanel CSS pattern).
- `.root` has `flex-shrink: 0`.
- The molecule is usable by any chart panel — no step-specific logic.

---

## Section 11 — Hard rules

1. Do not add Tailwind, styled-components, or any CSS-in-JS library.
2. Do not add `style={{}}` for anything other than computed one-off values (e.g., `style={{ width: \`${pct}%\` }}`).
3. Do not hardcode colours — always use CSS custom properties from `tokens.css`.
4. Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. Do not use font-weight 600 on form labels.
6. Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Do not skip component hierarchy levels (atom → molecule → organism).
8. Do not commit with a failing `npm run typecheck`.
9. Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
10. **The molecule must be usable by any chart panel — no hardcoded step-specific logic** (no references to step numbers, screener state, or scan context).
11. **Props must be fully typed** — no `any` types, no implicit `any`.
12. **Do not modify any file that uses ChartPanelHeader** — only `index.tsx` and `ChartPanelHeader.module.css` may be changed.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev       # localhost:3001 — open any Watchlist row to trigger InlineChartPanel
npm run typecheck # must be clean before every commit
```

To see `ChartPanelHeader` in context, open the Watchlist page and click any row's chart icon to open the `InlineChartPanel` slide-down. The header is the top bar of that panel (label, ticker, WatchStar, timeframe, close button).

There is no dedicated Step 4 or Step 3 usage — ChartPanelHeader is not rendered in those routes in the current codebase.

---

## Section 13 — Copy/paste prompt

```
You are working on the Bamendjou options screener (Next.js 15, TypeScript strict).
Read `llm-contexts/08-molecule-chartpanelheader.md` in full before writing any code.

Your task: polish the ChartPanelHeader molecule.

Owned files (the ONLY files you may edit):
  frontend/components/molecules/ChartPanelHeader/index.tsx
  frontend/components/molecules/ChartPanelHeader/ChartPanelHeader.module.css

Do NOT modify any file that imports ChartPanelHeader.

Changes required:
1. Add optional `label?: string` prop (default "Chart") — replace the hardcoded "Chart" text.
2. Add optional `timeframe?: string` prop (default "1D · 120 bars") — replace the hardcoded string.
3. Add JSDoc comments to all optional props showing their default values.
4. Change `weight={600}` on the panel title Text to `weight={500}`.
5. In ChartPanelHeader.module.css, change `.titleGroup { align-items: center }` to `align-items: baseline`.
6. In ChartPanelHeader.module.css, add `flex-shrink: 0` to `.root`.
7. Verify the CSS module contains no hardcoded hex colours — use only CSS custom properties.

After editing, run `npm run typecheck` and confirm it is clean.
The existing InlineChartPanel usage passes only `symbol` and `onClose` — your changes must not break it (both new props must remain optional with defaults).
```
