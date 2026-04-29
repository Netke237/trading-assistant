# LLM Context — Portfolio Page + ContextRail

> **How to use this file**
> You are working on the Bamendjou options screener (Next.js 15, TypeScript).
> This document is self-contained. Read every section before writing a single line of code.
> All work lives in `frontend/`. The path alias `@/` resolves to `frontend/`.
> Run `npm run typecheck` before every commit — it must be clean.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream owns only the files listed in Section 2. It does not touch any other page, store, or shared infrastructure.

**Goal:** Build a production-quality Portfolio page showing open options positions with P&L, Greeks, DTE progress bars, and status indicators. The ContextRail slot (300px right column) shows a compact aggregate P&L and Greeks summary.

**What NOT to touch:**
- `frontend/lib/portfolioStore.ts` — read-only; do not change its TypeScript interface
- `frontend/styles/tokens.css` — read-only; consume tokens, never modify them
- Any screener step page, watchlist page, dashboard page, calendar page, or settings page
- Any existing atom, molecule, or organism component (use them; do not modify them)
- `frontend/mocks/portfolio.ts` — import it; do not modify it
- `frontend/types/domain.ts` — import types from it; do not modify it
- `frontend/lib/date.ts` — import helpers from it; do not modify it

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `frontend/app/(frame)/portfolio/page.tsx` | Modify | Full portfolio positions table with edit drawer and totals footer |
| `frontend/app/(frame)/portfolio/page.module.css` | Modify | Portfolio-specific CSS Module styles |
| `frontend/app/(frame)/@contextRail/portfolio/page.tsx` | Modify | Compact aggregate P&L + Greeks summary in the 300px ContextRail |

These files already exist. Modify them; do not delete and recreate.

---

## Section 3 — Read-only references

| File | Role | Notes |
|---|---|---|
| `frontend/mocks/portfolio.ts` | Data source | Import `MOCK_PORTFOLIO`; do not modify |
| `frontend/types/domain.ts` | Type definitions | `PortfolioPosition`, `Direction`, `Status` |
| `frontend/lib/portfolioStore.ts` | Zustand store | `usePortfolioStore`; read-only interface |
| `frontend/lib/date.ts` | DTE helpers | `dteFillPct`, `dteStatus` |
| `frontend/lib/status.ts` | Status type | `type Status` |
| `frontend/components/primitives/` | `<Text>`, `<Title>`, `<Data>` | Font/tone/size primitives |
| `frontend/components/atoms/StatusBadge/` | `<StatusBadge>` | Status-colored badge |
| `frontend/components/molecules/DTEProgressBar/` | `<DTEProgressBar>` | DTE progress bar molecule |
| `frontend/components/molecules/TableRow/` | `<TableRow>` | Status-tinted grid row |
| `frontend/components/organisms/ContextRail/` | `RailSection`, `RailQuickLook` | Rail layout helpers |

---

## Section 4 — Integration constraints

### Exact import statements

```tsx
// Domain type
import type { PortfolioPosition } from '@/types/domain';

// Store — read positions and mutation methods
import { usePortfolioStore } from '@/lib/portfolioStore';
// Usage:
const positions      = usePortfolioStore((s) => s.positions);
const updatePosition = usePortfolioStore((s) => s.updatePosition);
const closeInStore   = usePortfolioStore((s) => s.closePosition);

// DTE helpers
import { dteFillPct, dteStatus } from '@/lib/date';

// Primitives
import { Title, Text, Data } from '@/components/primitives';

// Atoms
import { StatusBadge } from '@/components/atoms/StatusBadge';

// Molecules
import { DTEProgressBar } from '@/components/molecules/DTEProgressBar';
import { TableRow } from '@/components/molecules/TableRow';

// ContextRail organisms (use in @contextRail/portfolio/page.tsx)
import { RailSection } from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

// Mock data (use in @contextRail/portfolio/page.tsx — server component, no store)
import { MOCK_PORTFOLIO } from '@/mocks/portfolio';
```

### What the frame layout already provides

The persistent shell (`frontend/app/(frame)/layout.tsx`) renders:
- `TopBar` — fixed 48px top bar (`--frame-topbar-h`)
- `NavRail` — fixed 64px left rail (`--frame-navrail-w`)
- `ContextRail` — fixed 300px right column (`--frame-contextrail-w`) — populated by the `@contextRail` parallel route slot

Your page content renders in the space between NavRail and ContextRail. You do not need to render any of these shell components.

### ContextRail width

300px, defined by `--frame-contextrail-w`. Content inside the rail must fit within this constraint without horizontal overflow.

### `'use client'` directive

`frontend/app/(frame)/portfolio/page.tsx` requires `'use client'` because it uses `usePortfolioStore` (a Zustand hook) and `useState`.

`frontend/app/(frame)/@contextRail/portfolio/page.tsx` is a Server Component — it imports `MOCK_PORTFOLIO` directly. Do NOT add `'use client'` to it. Do not use Zustand hooks in this file.

---

## Section 5 — CSS tokens (complete)

All tokens live in `frontend/styles/tokens.css`. Import them via `frontend/app/globals.css` — they are already globally available. Never hardcode hex values.

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
Rule: No `weight={600}` on form labels — use `weight={400}`.

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
Monospace, tabular-nums. **Use for all prices, scores, and percentages.**

### Key atoms

| Component | Import path | Props | Notes |
|---|---|---|---|
| `StatusBadge` | `@/components/atoms/StatusBadge` | `status: Status`, `label?: string` | PASS/CAUTION/REJECT/PENDING/NO_DATA |
| `EventFlag` | `@/components/atoms/EventFlag` | `days: number`, `title?: string` | Calendar icon + days; colored by proximity |
| `WatchStar` | `@/components/atoms/WatchStar` | `symbol: string`, `size?: 'sm'|'md'` | Writes to watchlistStore |
| `RankDelta` | `@/components/atoms/RankDelta` | `delta: number`, `context?: string` | Arrow + number |
| `ScoreBar` | `@/components/atoms/ScoreBar` | `score: number`, `max?: number` | Fill colored by statusForScore |
| `StatusDot` | `@/components/atoms/StatusDot` | `status: Status` | Small circle indicator |

### Key molecules — most relevant to portfolio

| Component | Import path | Props | Notes |
|---|---|---|---|
| `DTEProgressBar` | `@/components/molecules/DTEProgressBar` | `daysRemaining: number`, `totalDays: number`, `className?: string` | DTE visual with colored fill |
| `TableRow` | `@/components/molecules/TableRow` | `status: Status`, `columns: string`, `selected?: boolean`, `onClick?: () => void` | Status-tinted CSS grid row |
| `SectionCard` | `@/components/molecules/SectionCard` | — | Surface card with border |

### ContextRail organisms

| Component | Import path | Notes |
|---|---|---|
| `RailSection` | `@/components/organisms/ContextRail` | Props: `title: string`, `children: ReactNode`. Renders a titled section in the rail. |
| `RailQuickLook` | `@/components/organisms/ContextRail/QuickLook` | Watchlist quick-look panel; render at end of rail. |

---

## Section 7 — Domain types

```ts
// frontend/lib/status.ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';

// frontend/types/domain.ts
export type Direction = 'Bullish' | 'Bearish';
export type Horizon   = 'Swing' | 'Position';
export type OrderType = 'Limit' | 'Market' | 'Stop';

export interface PortfolioPosition {
  symbol:        string;
  contract:      string;       // e.g. "AAPL 220C 05/16"
  direction:     Direction;
  entryDate:     string;       // ISO date e.g. "2026-04-08"
  expiry:        string;       // ISO date e.g. "2026-05-16"
  dteRemaining:  number;
  dteTotal:      number;
  entryPrice:    number;
  currentPrice:  number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number;
  target:        number;
  status:        Status;
  // Options-specific — all optional; show "—" when absent
  ivRank?:       number;       // 0–100, current IV vs 52-week range
  delta?:        number;       // option delta (–1..+1)
  theta?:        number;       // $/day time decay (negative for longs)
  vega?:         number;       // $/vol point
  contracts?:    number;       // number of option contracts held
  /** 'broker' | 'manual' — show "MANUAL" badge when manual */
  source?:       'broker' | 'manual';
  /** ISO timestamp of when the order was created */
  orderedAt?:    string;
}
```

**Contract canonical ID format:** `SYMBOL|STRIKE|EXPIRY|C/P`
Example: `AAPL|185|2025-05-16|C`

**Status display names** (StatusBadge handles this):
- `PASS` → "PASS"
- `CAUTION` → "CAUTION"
- `REJECT` → "REJECT"
- `PENDING` → "PENDING"
- `NO_DATA` → "NO DATA"

Do NOT invent labels like "Active", "Open", "Long", "Short".

---

## Section 8 — Zustand store (portfolioStore)

```ts
// frontend/lib/portfolioStore.ts

interface PortfolioStoreState {
  positions:      PortfolioPosition[];
  addPosition:    (p: PortfolioPosition) => void;
  updatePosition: (contract: string, patch: Partial<PortfolioPosition>) => void;
  closePosition:  (contract: string) => void;
}

export const usePortfolioStore = create<PortfolioStoreState>((set) => ({
  positions: MOCK_PORTFOLIO,   // seeded from mocks/portfolio.ts on init
  addPosition: (p) => set((s) => {
    // If same contract exists, merge contract counts, keep earlier entry
    const existingIdx = s.positions.findIndex((x) => x.contract === p.contract);
    if (existingIdx >= 0) { /* merge */ }
    return { positions: [...s.positions, p] };
  }),
  updatePosition: (contract, patch) =>
    set((s) => ({
      positions: s.positions.map((r) => (r.contract === contract ? { ...r, ...patch } : r)),
    })),
  closePosition: (contract) =>
    set((s) => ({ positions: s.positions.filter((r) => r.contract !== contract) })),
}));
```

**Usage in page.tsx:**
```tsx
const positions      = usePortfolioStore((s) => s.positions);
const updatePosition = usePortfolioStore((s) => s.updatePosition);
const closeInStore   = usePortfolioStore((s) => s.closePosition);
```

**Important:**
- Do NOT change the store's TypeScript interface.
- Do NOT add new actions to the store.
- The `@contextRail/portfolio/page.tsx` is a Server Component — import `MOCK_PORTFOLIO` directly; do not use `usePortfolioStore` there.
- Sorting state (sort column, sort direction) lives in local `useState` in `page.tsx`, not in Zustand.

---

## Section 9 — Mock data (exact values)

```ts
// frontend/mocks/portfolio.ts
// Status is computed by dteStatus(dteRemaining, dteTotal):
//   pct >= 50 → PASS | pct >= 20 → CAUTION | pct < 20 → REJECT
// where pct = (dteRemaining / dteTotal) * 100

export const MOCK_PORTFOLIO: PortfolioPosition[] = [
  {
    symbol: 'AAPL', contract: 'AAPL 190C 05/16',
    direction: 'Bullish',
    entryDate: '2026-04-08', expiry: '2026-05-16',
    dteRemaining: 28, dteTotal: 38,
    // pct = (28/38)*100 = 73.7% → status: 'PASS'
    entryPrice: 4.15, currentPrice: 5.02,
    pnlDollar: 870, pnlPct: 20.96,
    stop: 180.00, target: 198.00,
    ivRank: 42, delta: 0.58, theta: -0.08, vega: 0.22, contracts: 2,
    status: 'PASS',
  },
  {
    symbol: 'NVDA', contract: 'NVDA 920C 04/25',
    direction: 'Bullish',
    entryDate: '2026-04-14', expiry: '2026-04-25',
    dteRemaining: 7, dteTotal: 11,
    // pct = (7/11)*100 = 63.6% → status: 'PASS'
    entryPrice: 12.80, currentPrice: 14.25,
    pnlDollar: 725, pnlPct: 11.33,
    stop: 875.00, target: 960.00,
    ivRank: 71, delta: 0.62, theta: -0.24, vega: 0.18, contracts: 1,
    status: 'PASS',
  },
  {
    symbol: 'MSFT', contract: 'MSFT 420C 06/20',
    direction: 'Bullish',
    entryDate: '2026-04-10', expiry: '2026-06-20',
    dteRemaining: 63, dteTotal: 71,
    // pct = (63/71)*100 = 88.7% → status: 'PASS'
    entryPrice: 8.20, currentPrice: 8.85,
    pnlDollar: 325, pnlPct: 7.93,
    stop: 408.00, target: 445.00,
    ivRank: 28, delta: 0.54, theta: -0.05, vega: 0.34, contracts: 2,
    status: 'PASS',
  },
  {
    symbol: 'META', contract: 'META 510C 05/02',
    direction: 'Bullish',
    entryDate: '2026-04-15', expiry: '2026-05-02',
    dteRemaining: 14, dteTotal: 17,
    // pct = (14/17)*100 = 82.4% → status: 'PASS'
    entryPrice: 9.40, currentPrice: 8.10,
    pnlDollar: -390, pnlPct: -13.83,
    stop: 498.00, target: 540.00,
    ivRank: 55, delta: 0.46, theta: -0.14, vega: 0.26, contracts: 1,
    status: 'PASS',
  },
  {
    symbol: 'TSLA', contract: 'TSLA 170P 04/22',
    direction: 'Bearish',
    entryDate: '2026-04-16', expiry: '2026-04-22',
    dteRemaining: 4, dteTotal: 6,
    // pct = (4/6)*100 = 66.7% → status: 'PASS'
    entryPrice: 3.10, currentPrice: 3.78,
    pnlDollar: 340, pnlPct: 21.94,
    stop: 180.00, target: 160.00,
    ivRank: 82, delta: -0.52, theta: -0.31, vega: 0.12, contracts: 3,
    status: 'PASS',
  },
];
```

**Aggregate totals (for verification):**
- Total positions: 5
- Total pnlDollar: 870 + 725 + 325 + (−390) + 340 = **+$1,870**
- Best position by pnlDollar: AAPL (+$870)
- Worst position by pnlDollar: META (−$390)
- Deployed capital (currentPrice × 100 × contracts):
  - AAPL: 5.02 × 100 × 2 = $1,004
  - NVDA: 14.25 × 100 × 1 = $1,425
  - MSFT: 8.85 × 100 × 2 = $1,770
  - META: 8.10 × 100 × 1 = $810
  - TSLA: 3.78 × 100 × 3 = $1,134
  - Total deployed: **$6,143**
- Winners (pnlDollar > 0): 4 (AAPL, NVDA, MSFT, TSLA)
- Losers (pnlDollar < 0): 1 (META)

---

## Section 10 — Task spec

### Portfolio page (`portfolio/page.tsx`)

The page is a `'use client'` component. It reads positions from `usePortfolioStore`.

#### 1. Page heading
```tsx
<div className={styles.heading}>
  <Title as="h1" size={24}>Portfolio</Title>
  <Text size={13} tone="secondary">{positions.length} open positions</Text>
</div>
```

#### 2. Positions table

Use a single `<div className={styles.tableWrap}>` with:
- A header row (`<div className={styles.tableHeader} style={{ gridTemplateColumns: COLUMNS }}>`)
- A body (`<div className={styles.tableBody}>`) containing one row per position
- A sticky totals footer

**Column layout constant:**
```ts
const COLUMNS = '72px 1.6fr 72px 1fr 110px 104px 60px 56px 60px 90px 40px';
```

**Table header columns (left to right):**
```
SYMBOL | CONTRACT | DIR | DTE | ENTRY → NOW | P&L | IV RK | Δ | Θ/DAY | STATUS | [edit btn]
```

**Per-row data mapping:**

| Column | Component | Value |
|---|---|---|
| Symbol | `<Data size={13} weight={500}>` | `p.symbol` |
| Contract | `<Text size={12} tone="secondary">` | `p.contract`; if `p.source === 'manual'` also show "MANUAL" badge |
| Dir | Styled `<span>` | "Bull" for Bullish (pass color), "Bear" for Bearish (reject color) |
| DTE | `<DTEProgressBar daysRemaining={p.dteRemaining} totalDays={p.dteTotal} />` | See DTE formula below |
| Entry → Now | Two `<Data size={12}>` separated by arrow | `$${p.entryPrice.toFixed(2)}` → `$${p.currentPrice.toFixed(2)}` |
| P&L | `<Data size={13} weight={500} tone={...}>` | `+$X` or `-$X` (dollar); `+X.X%` or `-X.X%` (pct) below it |
| IV RK | `<Data size={12} tone={ivRankTone(p.ivRank)}>` | `p.ivRank` or `'—'` |
| Δ | `<Data size={12}>` | `p.delta?.toFixed(2)` or `'—'` |
| Θ/DAY | `<Data size={12} tone="reject">` | `p.theta?.toFixed(2)` or `'—'` (theta is always negative for longs) |
| Status | `<StatusBadge status={p.status} />` | — |
| Edit | `<button>` pencil icon | Toggles inline edit drawer |

**P&L coloring rule:**
- `pnlDollar > 0` → `tone="pass"` on both dollar and pct `<Data>` components
- `pnlDollar < 0` → `tone="reject"`
- `pnlDollar === 0` → no tone prop

**IV rank tone helper:**
```ts
function ivRankTone(rk: number | undefined): 'pass' | 'caution' | 'reject' | undefined {
  if (rk === undefined) return undefined;
  if (rk >= 70) return 'reject';   // very rich IV
  if (rk >= 40) return 'caution';  // moderate IV
  return 'pass';                   // cheap IV
}
```

**DTE progress bar formula:**
```
fill% = (dteRemaining / dteTotal) * 100
```
The `DTEProgressBar` molecule accepts `daysRemaining` and `totalDays` and computes this internally via `dteFillPct` from `lib/date.ts`. You just pass the raw values:
```tsx
<DTEProgressBar daysRemaining={p.dteRemaining} totalDays={p.dteTotal} />
```

Color thresholds (handled inside DTEProgressBar automatically):
- fill >= 50% → PASS color (`--pass`)
- fill >= 20% → CAUTION color (`--caution`)
- fill < 20%  → REJECT color (`--reject`)

#### 3. Edit drawer (inline, below each row)

Toggled by the pencil icon button. Renders as a collapsible panel below the row.
Fields: Stop (step 0.05), Target (step 0.05), Contracts (step 1, min 1), Current price (step 0.05).
Changing Current price must also recompute pnlDollar and pnlPct:
```ts
const pnlDollar = (newPrice - position.entryPrice) * 100 * (position.contracts ?? 1);
const pnlPct    = ((newPrice - position.entryPrice) / position.entryPrice) * 100;
```
"Close position" button calls `closeInStore(contract)` and collapses the drawer.

Use local `useState<string | null>(null)` for `editing` — the currently open contract string.

#### 4. Totals footer

Always visible at the bottom of the table.

```ts
const deployed   = positions.reduce((s, p) => s + p.currentPrice * 100 * (p.contracts ?? 1), 0);
const openPnL    = positions.reduce((s, p) => s + p.pnlDollar, 0);
const openPnLPct = deployed > 0 ? (openPnL / deployed) * 100 : 0;
const winners    = positions.filter((p) => p.pnlDollar > 0).length;
const losers     = positions.filter((p) => p.pnlDollar < 0).length;
```

Display four groups: Deployed, Open P&L, Return, W / L.
Apply `tone="pass"` / `tone="reject"` to P&L and Return values using the same positive/negative rule as rows.

### ContextRail (`@contextRail/portfolio/page.tsx`)

Server Component — no `'use client'`, no Zustand hooks. Import `MOCK_PORTFOLIO` directly.

Structure (render in order):
1. `<RailSection title="Totals">` — Deployed, Open P&L, Positions count
2. `<RailSection title="Aggregate Greeks">` — sum of delta (sign-aware), theta, vega
3. `<RailQuickLook />` — at the end

**Aggregate Greeks computation (match existing implementation):**
```ts
const deployed = MOCK_PORTFOLIO.reduce((s, p) => s + p.currentPrice * 100, 0);
const openPnL  = MOCK_PORTFOLIO.reduce((s, p) => s + p.pnlDollar, 0);
// Simplified mock aggregate Greeks (real computation in Phase 6):
const delta = MOCK_PORTFOLIO
  .reduce((s, p) => s + (p.direction === 'Bullish' ? 0.45 : -0.42), 0)
  .toFixed(2);
const theta = (-(MOCK_PORTFOLIO.length * 3.8)).toFixed(1);
const vega  = (MOCK_PORTFOLIO.length * 5.4).toFixed(1);
```

Use `<Text size={12} tone="secondary">` for labels and `<Data size={12}>` for values.
Theta displays with `tone="reject"` (time decay costs money).
Open P&L applies pass/reject tone as appropriate.

Use inline `style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}` for row layout inside RailSections (this is an acceptable one-off — the `Row` helper pattern already exists in the file).

### Acceptance criteria

- All 5 positions from `MOCK_PORTFOLIO` render in the table
- Total footer shows: Deployed $6,143, Open P&L +$1,870, W/L 4/1
- META row shows P&L in reject tone (−$390 / −13.83%)
- TSLA row shows "Bear" badge in reject color (direction Bearish)
- NVDA ivRank=71 shows in reject tone (≥70 = rich IV)
- MSFT ivRank=28 shows in pass tone (<40 = cheap IV)
- DTE bars fill correctly for each position (all happen to be PASS status at current values)
- Status badge renders for each row
- Edit drawer opens/closes on pencil click without page reload
- Closing a position removes it from the list (store update)
- ContextRail shows totals and Greeks without TypeScript errors
- `npm run typecheck` passes with zero errors

---

## Section 11 — Hard rules

1. **No Tailwind, no styled-components, no CSS-in-JS.** CSS Modules only.
2. **No inline `style={{}}` except for computed one-off values** (e.g. `style={{ width: '${pct}%' }}`). The `Row` helper in the ContextRail rail file uses an inline style — that existing pattern is acceptable; do not add new general-purpose inline styles.
3. **No hardcoded colors.** Always use CSS custom properties from `tokens.css`.
4. **No invented Status labels.** Only `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
5. **No font-weight 600 on form labels.** Use `weight={400}`.
6. **No card box-shadows.** Use `border: 1px solid var(--border-subtle)`.
7. **No skipping component hierarchy levels.** Atoms → Molecules → Organisms.
8. **No committing with a failing `npm run typecheck`.**
9. **No touching `node_modules/` or `package-lock.json`.**
10. **Do not change the `portfolioStore.ts` interface.** Read-only.
11. **Use `<Data>` for all prices and percentages.** It is monospace, tabular-nums.
12. **P&L coloring:** positive → `tone="pass"`, negative → `tone="reject"`, zero → no tone prop.
13. **Do not add sorting state to Zustand.** Use local `useState` in `page.tsx` only.
14. **`@contextRail/portfolio/page.tsx` is a Server Component.** No `'use client'`, no hooks.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev        # starts at localhost:3001 — navigate to /portfolio
npm run typecheck  # tsc --noEmit — must pass clean before every commit
npm run lint       # next lint
npm run build      # full production build (optional verification)
```

The portfolio route is `/portfolio`. The ContextRail slot is populated automatically by Next.js parallel routes from `app/(frame)/@contextRail/portfolio/page.tsx`.

---

## Section 13 — Copy/paste prompt

Paste the following block verbatim to the implementing LLM. It is self-contained.

---

```
You are implementing the Portfolio page and its ContextRail slot for the Bamendjou options screener (Next.js 15, TypeScript strict, CSS Modules, Zustand v5).

Read the full context document at llm-contexts/03-portfolio.md before writing any code. It contains all CSS tokens, exact import paths, mock data values, component specs, and acceptance criteria.

Your job is to modify (not recreate) these three files:
1. frontend/app/(frame)/portfolio/page.tsx — 'use client'; full positions table with edit drawer and totals footer
2. frontend/app/(frame)/portfolio/page.module.css — portfolio-specific CSS Module styles
3. frontend/app/(frame)/@contextRail/portfolio/page.tsx — Server Component; compact P&L + Greeks summary using RailSection

CRITICAL RULES (from the context doc, section 11):
- CSS Modules only — no Tailwind, no inline styles except computed one-offs (e.g. style={{ width: `${pct}%` }})
- Never hardcode colors — always use CSS custom properties from tokens.css
- Use <Data> for all prices and percentages (monospace, tabular-nums)
- P&L coloring: positive → tone="pass", negative → tone="reject", zero → no tone
- Do NOT change portfolioStore.ts — read-only
- Do NOT add sorting state to Zustand — use local useState only
- @contextRail/portfolio/page.tsx must remain a Server Component — no 'use client', no hooks
- npm run typecheck must pass clean

VERIFICATION (check against section 9 mock values):
- 5 positions total
- Total P&L: +$1,870 (AAPL +870, NVDA +725, MSFT +325, META -390, TSLA +340)
- META row must show reject-tone P&L
- TSLA direction is Bearish — show "Bear" badge
- DTE bar formula: fill% = (dteRemaining / dteTotal) * 100 (handled inside DTEProgressBar)
- ContextRail totals: Deployed ≈$6,143, Open P&L +$1,870, 5 positions

All exact import paths, type definitions, CSS tokens, and component APIs are in llm-contexts/03-portfolio.md. Do not guess — look them up in the document.
```
