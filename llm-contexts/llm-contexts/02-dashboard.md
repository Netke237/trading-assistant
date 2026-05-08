# Bamendjou — LLM Context: Dashboard Page + ContextRail

> **How to use this file**
> This is a self-contained scoped context document for implementing and polishing the Dashboard page and its ContextRail parallel-slot in the Bamendjou options screener.
> Read every section before touching any code. Sections 1–3 tell you what you own. Sections 4–11 give you every value, type, and import you need. Section 13 is the copy/paste prompt.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream owns only the Dashboard page files and its `@contextRail/dashboard` slot. No shared infrastructure, no other pages, no store modifications.

**Goal:** Build a production-quality Dashboard page showing a real-time-styled alert feed, regime status summary, watchlist preview, portfolio summary, and scan context overview. The ContextRail slot shows a compact scan summary with the most recent alert and portfolio risk numbers.

**Do NOT touch:**
- `frontend/app/(frame)/layout.tsx` — the shell (TopBar, NavRail, ContextRail) is already wired
- `frontend/styles/tokens.css` — CSS token source of truth; never edit
- `frontend/lib/scanStore.ts` — read-only from the dashboard's perspective
- Any screener step files, watchlist page, portfolio page, calendar page, or settings page
- Any existing atom, molecule, or organism component unless you are only *importing* it

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/app/(frame)/dashboard/page.tsx` | Modify | Full dashboard content — regime banner, bento layout, alert feed, watchlist preview, portfolio summary, scan context pill |
| `frontend/app/(frame)/dashboard/page.module.css` | Modify | Dashboard-specific CSS Module styles |
| `frontend/app/(frame)/@contextRail/dashboard/page.tsx` | Modify | Compact scan summary, most recent alert, portfolio risk numbers in the right rail |

---

## Section 3 — Read-only references

| File | How to use it |
|---|---|
| `frontend/mocks/alerts.ts` | Import `MOCK_ALERTS` and display it; do NOT modify the file |
| `frontend/types/domain.ts` | Type reference for `AlertItem`, `AlertKind`, `WatchlistRow`, `PortfolioPosition` |
| `frontend/lib/scanStore.ts` | Read `scanState`, `context`, `regime`, `scanAt` via the `useScanStore` hook; do NOT modify |
| `frontend/components/` | All existing atoms/molecules/organisms are available to import |
| `frontend/mocks/watchlist.ts` | Import `MOCK_WATCHLIST` for the watchlist preview card |
| `frontend/mocks/portfolio.ts` | Import `MOCK_PORTFOLIO` for portfolio summary card |
| `frontend/mocks/regime.ts` | Import `MOCK_REGIME` for the regime banner |
| `frontend/mocks/events.ts` | Import `MOCK_EVENTS` for the ContextRail upcoming events section |
| `frontend/lib/status.ts` | Import `Status` type if needed |

---

## Section 4 — Integration constraints

### Required imports — exact paths

```tsx
// Types
import type { AlertItem, AlertKind } from '@/types/domain';
import type { Status } from '@/lib/status';

// Zustand store (read-only from the dashboard)
import { useScanStore } from '@/lib/scanStore';
// Usage inside the component:
const { scanState, context, regime, scanAt } = useScanStore();

// Primitives
import { Title, Text, Data } from '@/components/primitives';

// Atoms
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { EventFlag }   from '@/components/atoms/EventFlag';
import { RankDelta }   from '@/components/atoms/RankDelta';
import { StatusDot }   from '@/components/atoms/StatusDot';

// Molecules
import { SectionCard } from '@/components/molecules/SectionCard';
import { TableRow }    from '@/components/molecules/TableRow';
import { AlertRow }    from '@/components/molecules/AlertRow';

// ContextRail organisms (for the @contextRail slot only)
// Confirmed: RailSection is exported from frontend/components/organisms/ContextRail/index.tsx
// Confirmed: QuickLook.tsx exists at frontend/components/organisms/ContextRail/QuickLook.tsx
import { RailSection }  from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

// Mocks
import { MOCK_ALERTS }    from '@/mocks/alerts';
import { MOCK_WATCHLIST } from '@/mocks/watchlist';
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
import { MOCK_REGIME }    from '@/mocks/regime';
import { MOCK_EVENTS }    from '@/mocks/events';

// Page CSS module
import styles from './page.module.css';
```

### Frame layout — what is already provided

The frame shell (`(frame)/layout.tsx`) renders:
- **TopBar** at the top (height `48px` = `--frame-topbar-h`) — shows scan context string, scan state pill, regime dot
- **NavRail** on the left (width `64px` = `--frame-navrail-w`, expands to `200px` on hover)
- **ContextRail** on the right (width `300px` = `--frame-contextrail-w`) — filled by the `@contextRail/dashboard/page.tsx` parallel slot
- The page content area fills the remaining space between NavRail and ContextRail

The dashboard `page.tsx` renders into the page content area only. Do not recreate the TopBar, NavRail, or ContextRail wrapper.

### ContextRail width constraint

The ContextRail is exactly `300px` wide (`var(--frame-contextrail-w)`). All content in `@contextRail/dashboard/page.tsx` must fit within that width. Use the `RailSection` organism wrapper which handles internal padding.

### `'use client'` directive

Both `dashboard/page.tsx` and `@contextRail/dashboard/page.tsx` must have `'use client'` at the top if they use hooks (`useScanStore`) or browser APIs.

---

## Section 5 — CSS tokens

All tokens come from `frontend/styles/tokens.css`. Never hardcode colors or spacing.

### Dark theme (default — `:root` / `[data-theme="dark"]`)

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

### Alert tint formula

Alert card backgrounds are computed with `color-mix`:

```css
/* Critical */
background: color-mix(in srgb, var(--reject) 15%, var(--bg-surface));

/* Action */
background: color-mix(in srgb, var(--caution) 15%, var(--bg-surface));

/* Info */
background: color-mix(in srgb, var(--neutral) 15%, var(--bg-surface));
```

Left border accent colors:
```css
/* Critical */ border-left: 3px solid var(--reject);
/* Action   */ border-left: 3px solid var(--caution);
/* Info     */ border-left: 3px solid var(--neutral);
```

---

## Section 6 — Primitives & component reference

### `<Text>`
```tsx
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
```
Default: `size=13`, `tone="primary"`, `weight=400`.
Do not use `weight={600}` on form labels.

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
Monospace, tabular-nums. Use for prices, scores, and percentages.

### Key atoms for the Dashboard

| Component | Import path | Props | Notes |
|---|---|---|---|
| `StatusBadge` | `@/components/atoms/StatusBadge` | `status: Status`, `label?: string` | Use for regime banner + alert kind |
| `EventFlag` | `@/components/atoms/EventFlag` | `days: number`, `title?: string` | Calendar icon + Nd; colored by proximity |
| `RankDelta` | `@/components/atoms/RankDelta` | `delta: number` (also `value` alias), `context?: string` | Arrow + number for watchlist preview |
| `StatusDot` | `@/components/atoms/StatusDot` | `status: Status`, `size?: 'sm'|'md'` | Small circle — use in ContextRail events list |

### Key molecules for the Dashboard

| Component | Import path | Notes |
|---|---|---|
| `SectionCard` | `@/components/molecules/SectionCard` | Surface card with border; use for each bento cell |
| `TableRow` | `@/components/molecules/TableRow` | Status-tinted grid row; use in watchlist preview |
| `AlertRow` | `@/components/molecules/AlertRow` | Pre-built alert list item with kind badge, symbol, reason, timestamp |

### Key organisms

| Component | Import path | Notes |
|---|---|---|
| `RailSection` | `@/components/organisms/ContextRail` | Section wrapper for the ContextRail slot |
| `RailQuickLook` | `@/components/organisms/ContextRail/QuickLook` | Quick-look widget; place at the bottom of the ContextRail |

### Component conventions (mandatory)

- Atoms → Molecules → Organisms — never skip levels.
- Each new component lives in its own folder: `ComponentName/index.tsx` + `ComponentName.module.css`.
- No card shadows — use `border: 1px solid var(--border-subtle)` instead.
- CSS variables from `styles/tokens.css` — never hardcode colours.
- Status tints: `color-mix(in srgb, var(--pass/caution/reject) N%, var(--bg-surface))`.

---

## Section 7 — Domain types

Full TypeScript definitions from `frontend/types/domain.ts`:

```ts
import type { Status } from '@/lib/status';

export type Direction = 'Bullish' | 'Bearish';
export type Horizon   = 'Swing' | 'Position';
export type AlertKind = 'Info' | 'Action' | 'Critical';
export type OrderType = 'Limit' | 'Market' | 'Stop';

export interface AlertItem {
  id:        string;
  kind:      AlertKind;
  symbol:    string;
  reason:    string;
  timestamp: string;  // "09:42" or ISO
}

export interface WatchlistRow {
  symbol:         string;
  company:        string;
  price:          number;
  direction:      Direction;
  horizon:        Horizon;
  score:          number;          // 0–100
  rankDelta:      number;          // +2 / -1 / 0
  scoreDelta?:    number;
  status:         Status;
  breakdown:      ScoreBreakdown;
  nextEventDays?: number;
  nextEventLabel?: string;
}

export interface PortfolioPosition {
  symbol:        string;
  contract:      string;           // "AAPL 220C 05/16"
  direction:     Direction;
  entryDate:     string;
  expiry:        string;
  dteRemaining:  number;
  dteTotal:      number;
  entryPrice:    number;
  currentPrice:  number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number;
  target:        number;
  status:        Status;
  ivRank?:       number;
  delta?:        number;
  theta?:        number;
  vega?:         number;
  contracts?:    number;
  source?:       'broker' | 'manual';
  orderedAt?:    string;
}

export interface UpcomingEvent {
  date:    string;
  symbol:  string;
  label:   string;
  status:  Status;
}
```

The `Status` type (from `frontend/lib/status.ts`):

```ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';
```

---

## Section 8 — Zustand stores

### `scanStore.ts` — full interface

```ts
// frontend/lib/scanStore.ts

import { create } from 'zustand';
import type { Status } from './status';
import type { Direction } from '@/types/domain';

export type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

export interface ScanContext {
  universe:  string;    // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;    // "Swing (5–15d)"
}

interface ScanStoreState {
  scanState:    ScanState;
  scanAt:       string | null;   // ISO-ish local timestamp, no TZ suffix
  context:      ScanContext | null;
  regime:       Status;
  setScanState: (s: ScanState, at?: string) => void;
  setContext:   (c: ScanContext | null) => void;
  setRegime:    (r: Status) => void;
}
```

**Seed values (what the store starts with on page load):**

```ts
scanState: 'COMPLETED'
scanAt:    '2026-04-20T09:42:00'
context:   { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
regime:    'PASS'
```

**Usage in the dashboard — read-only:**

```tsx
'use client';
import { useScanStore } from '@/lib/scanStore';

export default function DashboardPage() {
  const { scanState, context, regime, scanAt } = useScanStore();
  // Never call setScanState, setContext, or setRegime from the dashboard.
  // ...
}
```

The dashboard never writes to this store. TopBar already displays scan context and regime dot; the dashboard may echo those values for additional context cards.

---

## Section 9 — Mock data (exact values)

### `MOCK_ALERTS` (complete, from `frontend/mocks/alerts.ts`)

```ts
import type { AlertItem } from '@/types/domain';

export const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', kind: 'Critical', symbol: 'META', reason: 'Broke trail stop',                    timestamp: '09:38' },
  { id: 'a2', kind: 'Action',   symbol: 'NVDA', reason: 'Earnings in 3 days — roll or close', timestamp: '09:41' },
  { id: 'a3', kind: 'Action',   symbol: 'AAPL', reason: 'Target 80% reached',                  timestamp: '09:47' },
  { id: 'a4', kind: 'Info',     symbol: 'SPY',  reason: 'Regime flipped to PASS',              timestamp: '09:15' },
  { id: 'a5', kind: 'Info',     symbol: 'TSLA', reason: 'IV rank > 70',                         timestamp: '09:02' },
];
```

**AlertKind → color mapping:**

| kind | CSS variable | Tint formula |
|---|---|---|
| `Critical` | `--reject` | `color-mix(in srgb, var(--reject) 15%, var(--bg-surface))` |
| `Action` | `--caution` | `color-mix(in srgb, var(--caution) 15%, var(--bg-surface))` |
| `Info` | `--neutral` | `color-mix(in srgb, var(--neutral) 15%, var(--bg-surface))` |

### `scanStore` seed values

```ts
scanState: 'COMPLETED'
scanAt:    '2026-04-20T09:42:00'
context:   { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
regime:    'PASS'
```

### `MOCK_REGIME` summary (from `frontend/mocks/regime.ts`)

```ts
overall:  'PASS'
headline: 'Trend + breadth constructive; VIX contained'
metrics: [
  { label: 'SPX trend (200 EMA)', value: 'Above',  status: 'PASS',    trend: 'up'   },
  { label: 'NDX trend (200 EMA)', value: 'Above',  status: 'PASS',    trend: 'up'   },
  { label: 'Breadth (A/D)',       value: '+412',   status: 'PASS',    trend: 'up'   },
  { label: 'VIX',                 value: '14.8',   status: 'PASS',    trend: 'down' },
  { label: '10Y yield',           value: '4.28%',  status: 'CAUTION', trend: 'up'   },
  { label: 'DXY (USD)',           value: '104.6',  status: 'PASS',    trend: 'flat' },
  { label: 'HY credit spread',    value: '312 bp', status: 'CAUTION', trend: 'up'   },
  { label: 'Put/Call (5d avg)',   value: '0.84',   status: 'PASS',    trend: 'down' },
]
```

### `MOCK_WATCHLIST` — top 5 rows displayed in dashboard

| Symbol | Company | Price | Score | Status | rankDelta | nextEventDays | nextEventLabel |
|---|---|---|---|---|---|---|---|
| AAPL | Apple Inc | 185.20 | 82 | PASS | +2 | 8 | Earnings |
| NVDA | NVIDIA Corp | 903.10 | 79 | PASS | +1 | 1 | Earnings |
| MSFT | Microsoft Corp | 417.50 | 74 | PASS | 0 | 10 | Earnings |
| META | Meta Platforms | 512.80 | 71 | PASS | -1 | 10 | Earnings |
| GOOGL | Alphabet Inc | 156.20 | 68 | CAUTION | +1 | 9 | Earnings |

---

## Section 10 — Task spec

### Dashboard page (`page.tsx`) must show

**1. Page heading area**
- `<Title as="h1" size={24}>Dashboard</Title>`
- Sub-text with last scan timestamp derived from `scanAt` in `useScanStore()`
- Use `<Text size={13} tone="secondary">` for the timestamp line

**2. Regime banner**
- Full-width banner below the heading
- Left side: `<StatusBadge status={MOCK_REGIME.overall} label={`REGIME ${MOCK_REGIME.overall}`} />` + headline text
- Right side: compact metric grid from `MOCK_REGIME.metrics` (label + value toned by status)
- Banner has a colored left-border accent: PASS → `--pass`, CAUTION → `--caution`, REJECT → `--reject`
- Banner background: `var(--bg-surface)`, border: `1px solid var(--border-subtle)`

**3. Bento row (3 columns)**

Column 1 — Watchlist preview card (`SectionCard` with title "Watchlist (Top 5)"):
- Show top 5 rows from `MOCK_WATCHLIST`
- Grid columns: `60px 1fr 60px 64px 64px` (SYM | NAME | SCORE | RANK Δ | NEXT)
- Header row of `<Text size={11} tone="dim">` labels
- Each row: `<TableRow status={row.status} columns={WL_COLUMNS}>` containing `<Data>` symbol, `<Text>` company name, `<Data>` score, `<RankDelta>`, `<EventFlag>`
- Card action: "View all →" navigates to `/watchlist`

Column 2 — Portfolio summary card (`SectionCard` with title "Portfolio"):
- 2×2 stat grid: Deployed ($), Open P&L ($, toned pass/reject), Return (%, toned), Positions (count)
- Stats computed from `MOCK_PORTFOLIO`: `reduce` over `currentPrice * 100` for deployed, sum `pnlDollar` for P&L
- Divider, then up to 3 position rows: symbol | contract | P&L
- Card action: "View all →" navigates to `/portfolio`

Column 3 — Alert feed card (`SectionCard` with title "Alerts", count = `MOCK_ALERTS.length`):
- Render all 5 `MOCK_ALERTS` using `<AlertRow kind={a.kind} symbol={a.symbol} reason={a.reason} timestamp={a.timestamp} />`
- If `AlertRow` is not available, build inline: each alert card has a tinted background and left-border accent per the AlertKind color mapping in Section 9
- Critical tint: `color-mix(in srgb, var(--reject) 15%, var(--bg-surface))`
- Action tint: `color-mix(in srgb, var(--caution) 15%, var(--bg-surface))`
- Info tint: `color-mix(in srgb, var(--neutral) 15%, var(--bg-surface))`

**4. Scan context pill**
- Below the bento row or inside the heading area
- Shows `context.universe` + `context.direction` + `context.horizon` from `useScanStore()`
- Visual: small pill/chip with secondary text, `background: var(--bg-surface-2)`, `border-radius: var(--radius-sm)`
- Only render if `context !== null`

### ContextRail slot (`@contextRail/dashboard/page.tsx`) must show

Use `<RailSection>` for each section. Sections from top to bottom:

**1. Scan summary**
- Title: "Last Scan"
- Content: scanState badge/pill, formatted `scanAt` time, context string (universe + direction + horizon)
- Read from `useScanStore()`

**2. Most recent alert**
- Title: "Latest Alert"
- Show only `MOCK_ALERTS[0]` (the first, most recent item: Critical, META, "Broke trail stop", 09:38)
- Kind badge, symbol in `<Data size={12} weight={500}>`, reason in `<Text size={12}>`, timestamp in `<Text size={11} tone="dim">`

**3. Portfolio risk**
- Title: "Portfolio Risk"
- Three rows: Deployed | Open P&L (toned pass/reject) | Positions count
- Computed from `MOCK_PORTFOLIO`

**4. `<RailQuickLook />`** at the bottom

### Acceptance criteria

- Alert feed renders all 5 alerts from `MOCK_ALERTS`
- Critical alerts use `--reject` color tint
- Action alerts use `--caution` color tint
- Info alerts use `--neutral` color tint
- Color tints follow: `color-mix(in srgb, var(--[status]) 15%, var(--bg-surface))`
- Regime banner shows `MOCK_REGIME.overall` status with correct colored left-border
- Watchlist preview shows top 5 from `MOCK_WATCHLIST` with status-tinted `TableRow`
- Portfolio summary shows computed totals from `MOCK_PORTFOLIO`
- ContextRail shows scan summary, latest alert, and portfolio risk
- No TypeScript errors (`npm run typecheck` is clean)
- No hardcoded color values — all colors from CSS custom properties

---

## Section 11 — Hard rules

1. Do not add Tailwind, styled-components, or any CSS-in-JS library.
2. Do not add inline `style={{}}` for anything other than computed one-off values (e.g. `style={{ width: `${pct}%` }}`).
3. Do not hardcode colours — always use CSS custom properties from `tokens.css`.
4. Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. Do not use font-weight 600 on form labels.
6. Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
7. Do not skip component hierarchy levels (atom → molecule → organism).
8. Do not commit with a failing `npm run typecheck`.
9. Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
10. Do not modify `(frame)/layout.tsx` — the shell is already wired and must not be touched.
11. Do not create a new Zustand store — read from `scanStore` only. The dashboard is read-only with respect to all stores.
12. AlertKind color mapping is fixed: `Critical` → `--reject`, `Action` → `--caution`, `Info` → `--neutral`.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev       # starts on localhost:3001 — navigate to /dashboard
npm run typecheck # tsc --noEmit — must be clean before every commit
npm run lint      # next lint
npm run build     # full production build
```

Navigate to `http://localhost:3001/dashboard` to see the page.

The ContextRail slot is the `@contextRail/dashboard` parallel route — it renders automatically in the right rail when you are on `/dashboard`.

---

## Section 13 — Copy/paste prompt

Paste the following to the implementing LLM. It is fully self-contained.

---

```
You are implementing the Dashboard page and its ContextRail slot for the Bamendjou options screener.
Read the full context document at llm-contexts/02-dashboard.md before writing any code.

Project root: F:\Git\GitHub\Trading assistant
Frontend root: F:\Git\GitHub\Trading assistant\frontend
Path alias `@/` resolves to `frontend/`.

Stack: Next.js 15, TypeScript strict, CSS Modules only, Zustand v5.
No Tailwind. No inline styles except computed one-offs. No hardcoded colors.

You own exactly three files:
1. frontend/app/(frame)/dashboard/page.tsx           — Modify
2. frontend/app/(frame)/dashboard/page.module.css    — Modify
3. frontend/app/(frame)/@contextRail/dashboard/page.tsx — Modify

Do NOT touch any other file.

--- TYPES ---

// frontend/types/domain.ts
export type AlertKind = 'Info' | 'Action' | 'Critical';

export interface AlertItem {
  id:        string;
  kind:      AlertKind;
  symbol:    string;
  reason:    string;
  timestamp: string;
}

// frontend/lib/status.ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

--- MOCK DATA (complete, do not fetch) ---

// frontend/mocks/alerts.ts
export const MOCK_ALERTS: AlertItem[] = [
  { id: 'a1', kind: 'Critical', symbol: 'META', reason: 'Broke trail stop',                    timestamp: '09:38' },
  { id: 'a2', kind: 'Action',   symbol: 'NVDA', reason: 'Earnings in 3 days — roll or close', timestamp: '09:41' },
  { id: 'a3', kind: 'Action',   symbol: 'AAPL', reason: 'Target 80% reached',                  timestamp: '09:47' },
  { id: 'a4', kind: 'Info',     symbol: 'SPY',  reason: 'Regime flipped to PASS',              timestamp: '09:15' },
  { id: 'a5', kind: 'Info',     symbol: 'TSLA', reason: 'IV rank > 70',                         timestamp: '09:02' },
];

// Scan store seed (read-only from useScanStore):
//   scanState: 'COMPLETED'
//   scanAt:    '2026-04-20T09:42:00'
//   context:   { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
//   regime:    'PASS'

--- IMPORTS (exact paths) ---

import { Title, Text, Data }        from '@/components/primitives';
import { StatusBadge }               from '@/components/atoms/StatusBadge';
import { EventFlag }                 from '@/components/atoms/EventFlag';
import { RankDelta }                 from '@/components/atoms/RankDelta';
import { StatusDot }                 from '@/components/atoms/StatusDot';
import { SectionCard }               from '@/components/molecules/SectionCard';
import { TableRow }                  from '@/components/molecules/TableRow';
import { AlertRow }                  from '@/components/molecules/AlertRow';
import { RailSection }               from '@/components/organisms/ContextRail';
import { RailQuickLook }             from '@/components/organisms/ContextRail/QuickLook';
import { useScanStore }              from '@/lib/scanStore';
import { MOCK_ALERTS }               from '@/mocks/alerts';
import { MOCK_WATCHLIST }            from '@/mocks/watchlist';
import { MOCK_PORTFOLIO }            from '@/mocks/portfolio';
import { MOCK_REGIME }               from '@/mocks/regime';
import { MOCK_EVENTS }               from '@/mocks/events';

Zustand hook usage inside a component:
  const { scanState, context, regime, scanAt } = useScanStore();
The dashboard NEVER calls setScanState, setContext, or setRegime.

--- CSS TOKEN REFERENCE ---

Color tint formula for alert cards:
  Critical → background: color-mix(in srgb, var(--reject) 15%, var(--bg-surface)); border-left: 3px solid var(--reject);
  Action   → background: color-mix(in srgb, var(--caution) 15%, var(--bg-surface)); border-left: 3px solid var(--caution);
  Info     → background: color-mix(in srgb, var(--neutral) 15%, var(--bg-surface)); border-left: 3px solid var(--neutral);

Regime banner left-border accent:
  PASS    → border-left: 3px solid var(--pass);
  CAUTION → border-left: 3px solid var(--caution);
  REJECT  → border-left: 3px solid var(--reject);

Key tokens:
  --bg-surface, --bg-surface-2, --border-subtle, --border-strong
  --text-primary, --text-secondary, --text-dim
  --pass, --caution, --reject, --neutral
  --space-1 (4px) through --space-8 (32px)
  --radius-sm (4px), --radius-md (6px), --radius-lg (10px)

--- WHAT TO BUILD ---

dashboard/page.tsx:
1. Heading: <Title as="h1" size={24}>Dashboard</Title> + last scan timestamp from useScanStore().scanAt
2. Regime banner: StatusBadge + headline + 8 metric chips from MOCK_REGIME; colored left-border by overall status
3. Bento row (3 columns, CSS grid):
   - Col 1: Watchlist preview — top 5 MOCK_WATCHLIST rows in a TableRow grid (60px 1fr 60px 64px 64px)
   - Col 2: Portfolio summary — computed Deployed, Open P&L, Return, Positions count from MOCK_PORTFOLIO
   - Col 3: Alert feed — all 5 MOCK_ALERTS rendered with AlertRow (or inline if AlertRow is absent), color-tinted by kind
4. Scan context pill showing context.universe + context.direction + context.horizon (from useScanStore)

@contextRail/dashboard/page.tsx:
1. RailSection "Last Scan": scanState, formatted scanAt, context string
2. RailSection "Latest Alert": MOCK_ALERTS[0] only — kind badge, symbol, reason, timestamp
3. RailSection "Portfolio Risk": Deployed, Open P&L, Positions — computed from MOCK_PORTFOLIO
4. <RailQuickLook /> at the bottom

--- HARD RULES ---
- 'use client' at top of both files if using hooks
- CSS Modules only — no Tailwind, no inline style objects for static values
- No hardcoded hex colors — use CSS custom properties exclusively
- No card box-shadows — use border: 1px solid var(--border-subtle)
- No new Zustand stores — read only from useScanStore
- AlertKind→color: Critical=reject, Action=caution, Info=neutral
- Run npm run typecheck and fix all errors before finishing
- Do NOT modify layout.tsx, tokens.css, scanStore.ts, or any other page
```
