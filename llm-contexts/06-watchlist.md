# Bamendjou — LLM Context: Watchlist Page + ContextRail

> **Workstream:** Watchlist page (Stocks tab + Contracts tab) and its ContextRail slot.
> **Read this document fully before touching any code.**
> All work lives in `frontend/`. Path alias `@/` maps to `frontend/`.

---

## Section 1 — Mission

**Conflict class: Medium.**
The watchlist page files live inside the shared `(frame)` parent shell, but this workstream only touches its own page files. The Zustand stores (`watchlistStore.ts`, `watchedContractsStore.ts`) are **read-only** — do NOT modify their interfaces, actions, or state shape.

**Goal:** Polish the Watchlist page to a production-quality state.

The page has two tabs:

- **Stocks tab:** Sortable table of `WatchlistRow` items from `MOCK_WATCHLIST`. Columns: star (`WatchStar`), symbol, company name, price, direction pill, horizon, score (with `StatusBadge`), rank delta (`RankDelta`), next event (`EventFlag`). Clicking a row opens the inline chart panel (`InlineChartPanel`). A `ScoreBar` is NOT currently shown inline in the row — this may be a polish opportunity (see Section 10).
- **Contracts tab:** Sortable table of `OptionContract` items resolved from `watchedContractsStore.ids` via `MOCK_CONTRACT_INDEX`. Columns: star (`ContractStar`), symbol, contract label, DTE progress bar, price, delta, IV rank, theta, score + status badge. Shows an empty-state message when no contracts are starred.

**Do NOT touch:**
- `frontend/app/(frame)/layout.tsx`
- `frontend/styles/tokens.css` or `frontend/app/globals.css`
- `frontend/lib/watchlistStore.ts`
- `frontend/lib/watchedContractsStore.ts`
- Any other page outside this workstream

---

## Section 2 — Owned files

Every file this workstream may create or edit:

```
frontend/app/(frame)/watchlist/
  page.tsx                          # Main Watchlist page (Stocks + Contracts tabs)
  page.module.css                   # CSS Modules for the watchlist page

frontend/app/(frame)/@contextRail/watchlist/
  page.tsx                          # ContextRail slot for /watchlist
  page.module.css                   # CSS Modules for the ContextRail slot
```

If you need new sub-components (e.g. a `ScoreBar` row variant), they go in the correct component hierarchy level under `frontend/components/`, not in the page folder. Prefer using existing atoms/molecules before creating new components.

---

## Section 3 — Read-only references

This workstream imports from but must NOT modify:

**Mock files:**
- `frontend/mocks/watchlist.ts` — exports `MOCK_WATCHLIST: WatchlistRow[]`
- `frontend/mocks/contracts.ts` — exports `MOCK_CONTRACTS`, `MOCK_CONTRACT_INDEX`, `contractLabel`, `contractId`, `OptionContract`, `OptionRight`
- `frontend/mocks/events.ts` — used internally by `watchlist.ts` via `nextEventFor()`

**Store files (read-only):**
- `frontend/lib/watchlistStore.ts` — `useWatchlistStore`
- `frontend/lib/watchedContractsStore.ts` — `useWatchedContractsStore`

**Status helper:**
- `frontend/lib/status.ts` — `statusForScore`, `Status` type

**Component files (may use, do not modify):**
- `frontend/components/primitives/` — `Text`, `Title`, `Data`
- `frontend/components/atoms/WatchStar/index.tsx`
- `frontend/components/atoms/ContractStar/index.tsx`
- `frontend/components/atoms/StatusBadge/index.tsx`
- `frontend/components/atoms/RankDelta/index.tsx`
- `frontend/components/atoms/ScoreBar/index.tsx`
- `frontend/components/atoms/EventFlag/index.tsx`
- `frontend/components/molecules/TableRow/index.tsx`
- `frontend/components/molecules/DTEProgressBar/index.tsx`
- `frontend/components/organisms/InlineChartPanel/index.tsx`
- `frontend/components/organisms/ContextRail/index.tsx` — exports `RailSection`
- `frontend/components/organisms/ContextRail/QuickLook.tsx` — exports `RailQuickLook`

**Domain types:**
- `frontend/types/domain.ts` — `WatchlistRow`, `Direction`, `Horizon`, `Status`

---

## Section 4 — Integration constraints

Use these exact import paths. Do not invent paths.

```tsx
// Primitives
import { Text, Title, Data } from '@/components/primitives';

// Atoms
import { WatchStar }     from '@/components/atoms/WatchStar';
import { ContractStar }  from '@/components/atoms/ContractStar';
import { StatusBadge }   from '@/components/atoms/StatusBadge';
import { RankDelta }     from '@/components/atoms/RankDelta';
import { ScoreBar }      from '@/components/atoms/ScoreBar';
import { EventFlag }     from '@/components/atoms/EventFlag';

// Molecules
import { TableRow }        from '@/components/molecules/TableRow';
import { DTEProgressBar }  from '@/components/molecules/DTEProgressBar';

// Organisms
import { InlineChartPanel } from '@/components/organisms/InlineChartPanel';
import { RailSection }      from '@/components/organisms/ContextRail';
import { RailQuickLook }    from '@/components/organisms/ContextRail/QuickLook';

// Stores
import { useWatchlistStore }         from '@/lib/watchlistStore';
import { useWatchedContractsStore }  from '@/lib/watchedContractsStore';

// Mocks
import { MOCK_WATCHLIST }                              from '@/mocks/watchlist';
import { MOCK_CONTRACT_INDEX, contractLabel,
         type OptionContract }                         from '@/mocks/contracts';

// Status
import { statusForScore } from '@/lib/status';

// Types
import type { WatchlistRow } from '@/types/domain';

// CSS Module
import styles from './page.module.css';
```

**Store return shapes (what selectors give you):**

```ts
// watchlistStore
const added        = useWatchlistStore((s) => s.added);        // string[] — uppercased symbols
const addSymbol    = useWatchlistStore((s) => s.addSymbol);    // (sym: string) => void
const removeSymbol = useWatchlistStore((s) => s.removeSymbol); // (sym: string) => void
const isWatched    = useWatchlistStore((s) => s.isWatched);    // (sym: string) => boolean
// WatchStar handles these internally — the page does NOT call them directly.

// watchedContractsStore
const ids      = useWatchedContractsStore((s) => s.ids);       // string[] — canonical contract ids
const toggle   = useWatchedContractsStore((s) => s.toggle);    // (id: string) => void
const isWatchedContract = useWatchedContractsStore((s) => s.isWatched); // (id: string) => boolean
// ContractStar handles toggle internally — the page calls ids to get the list of starred contracts.
```

**The page uses `watchedContractsStore` only to read `ids` and resolve them to `OptionContract` rows:**
```ts
const watchedIds = useWatchedContractsStore((s) => s.ids);
const watchedContracts = useMemo<OptionContract[]>(
  () => watchedIds.map((id) => MOCK_CONTRACT_INDEX[id]).filter((c): c is OptionContract => !!c),
  [watchedIds],
);
```

**Frame layout provides:** TopBar (48px), NavRail (64px), ContextRail (300px). Do not recreate any of these.

---

## Section 5 — CSS tokens

All tokens are in `frontend/styles/tokens.css`. Never hardcode colors or spacing. Use only these:

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

**Status tint pattern** (for row backgrounds, etc.):
```css
background: color-mix(in srgb, var(--pass) 8%, var(--bg-surface));
```

---

## Section 6 — Primitives & component reference

### Primitives

```tsx
// Text — body copy, labels, descriptions
<Text
  size={11 | 12 | 13 | 14}
  tone={'primary' | 'secondary' | 'dim' | 'pass' | 'caution' | 'reject'}
  weight={400 | 500 | 600}
/>
// Default: size=13, tone="primary", weight=400
// NEVER use weight=600 on form labels

// Title — headings
<Title as={'h1' | 'h2' | 'h3'} size={18 | 20 | 24} />

// Data — monospace tabular numbers (prices, scores, pct)
<Data
  size={11 | 12 | 13 | 14 | 16 | 18 | 20 | 24}
  weight={500 | 600}
  tone={'pass' | 'caution' | 'reject'}  // optional
/>
```

### Atoms used in this workstream

| Component | Props | Usage in Watchlist |
|---|---|---|
| `WatchStar` | `symbol: string`, `size?: 'sm'|'md'` | First column of Stocks tab rows |
| `ContractStar` | `contractId: string`, `size?: 'sm'|'md'` | First column of Contracts tab rows |
| `StatusBadge` | `status: Status`, `label?: string` | Score cell + contracts tab score cell |
| `RankDelta` | `value: number`, `context?: string` | Rank delta column in Stocks tab |
| `ScoreBar` | `label: string`, `value: number`, `max?: number`, `displayValue?: string` | Not currently in rows — potential polish for ContextRail or score tooltip |
| `EventFlag` | `days: number`, `title?: string` | Next event column in Stocks tab |

### Key molecules used here

| Component | Props | Usage |
|---|---|---|
| `TableRow` | `status: Status`, `columns: string` (grid-template-columns), `selected?: boolean`, `onClick?: () => void` | Every data row in both tabs |
| `DTEProgressBar` | `daysRemaining: number`, `totalDays: number` | DTE column in Contracts tab |

### Key organism used here

| Component | Props | Usage |
|---|---|---|
| `InlineChartPanel` | `open: boolean`, `symbol: string`, `onClose: () => void` | Opens below Stocks table when a row is selected |

### ContextRail helpers

```tsx
import { RailSection }   from '@/components/organisms/ContextRail';
import { RailQuickLook } from '@/components/organisms/ContextRail/QuickLook';

// RailSection renders a titled box in the right rail
<RailSection title="Status breakdown">
  {/* children */}
</RailSection>

// RailQuickLook renders a standard quick-look footer (no props needed)
<RailQuickLook />
```

---

## Section 7 — Domain types

### `WatchlistRow` (from `frontend/types/domain.ts`)

```ts
type Direction = 'Bullish' | 'Bearish';
type Horizon   = 'Swing' | 'Position';

interface ScoreBreakdown {
  trend:      number;   // 0–100
  pullback:   number;
  trigger:    number;
  event:      number;
  volatility: number;
}

interface WatchlistRow {
  symbol:          string;
  company:         string;
  price:           number;
  direction:       Direction;
  horizon:         Horizon;
  score:           number;          // 0–100
  rankDelta:       number;          // position change vs last scan (positive = moved up)
  scoreDelta?:     number;          // score pts change vs last scan
  status:          Status;          // derived from statusForScore(score)
  breakdown:       ScoreBreakdown;
  nextEventDays?:  number;          // days to next earnings/FOMC/etc
  nextEventLabel?: string;          // "Earnings", "FOMC", etc.
}
```

### `OptionContract` (from `frontend/mocks/contracts.ts`)

```ts
type OptionRight = 'C' | 'P';

interface OptionContract {
  id:           string;         // canonical: "SYMBOL|STRIKE|YYYY-MM-DD|RIGHT" — 4 segments; RIGHT is 'C' or 'P'
  symbol:       string;
  strike:       number;
  expiry:       string;         // YYYY-MM-DD
  right:        OptionRight;    // 'C' | 'P'
  dte:          number;         // days to expiry from now
  dteTotal:     number;         // days from position open → expiry
  price:        number;         // mid premium, $
  delta:        number;         // option delta
  theta:        number;         // $/day (negative for long options)
  ivRank:       number;         // 0–100
  ivPercentile: number;         // 0–100
  spread:       number;         // bid/ask width, $
  volume:       number;         // contracts traded today
  score:        number;         // 0–100
}
```

**Canonical ID format:** `SYMBOL|STRIKE|YYYY-MM-DD|RIGHT` — exactly **4 pipe-separated segments**.
`RIGHT` is a single character: `C` or `P`. Examples: `AAPL|190|2026-05-15|C`, `AAPL|185|2026-04-24|P`.
> WARNING: The source file comment reads `C|P` (misleading). The actual `contractId()` function is `${symbol}|${strike}|${expiry}|${right}` — RIGHT is always one character, never two segments.

**Helper functions from `@/mocks/contracts`:**
```ts
contractId(symbol, strike, expiry, right): string   // builds canonical id
contractLabel(c): string                            // e.g. "AAPL 190C 05/15"
```

---

## Section 8 — Zustand stores

### `useWatchlistStore` (from `frontend/lib/watchlistStore.ts`)

```ts
interface WatchlistState {
  added: string[];               // all watched symbols, uppercased; seeded with all 10 MOCK_WATCHLIST symbols
  addSymbol:    (sym: string) => void;
  removeSymbol: (sym: string) => void;
  isWatched:    (sym: string) => boolean;
}
```

- Persisted to `localStorage` under key `bamendjou:watchlist`, version 1.
- Seeded on first run with all MOCK_WATCHLIST symbols (all 10 will be starred by default).
- `WatchStar` calls `addSymbol` / `removeSymbol` internally. The page does NOT call these directly.
- This workstream MUST NOT add new actions or modify the interface.

### `useWatchedContractsStore` (from `frontend/lib/watchedContractsStore.ts`)

```ts
interface WatchedContractsState {
  ids: string[];                   // canonical contract ids; starts empty
  add:       (id: string) => void;
  remove:    (id: string) => void;
  toggle:    (id: string) => void; // ContractStar calls this
  isWatched: (id: string) => boolean;
}
```

- Persisted to `localStorage` under key `bamendjou:watched-contracts`, version 1.
- Starts empty — user must star contracts from Step 6 first.
- `ContractStar` calls `toggle` internally. The page reads `ids` to resolve which contracts to display.
- This workstream MUST NOT add new actions or modify the interface.

**Workstream-allowed store interactions:**
- Read `useWatchedContractsStore((s) => s.ids)` — to get the list of starred contract ids.
- Pass `contractId` to `<ContractStar contractId={c.id} />` — the atom handles the toggle.
- Pass `symbol` to `<WatchStar symbol={row.symbol} />` — the atom handles add/remove.

---

## Section 9 — Mock data (exact values)

### MOCK_WATCHLIST — 10 rows

`nextEventDays` and `nextEventLabel` are computed by `nextEventFor(symbol)` at module load time, relative to reference date `2026-04-20`. The events mock uses `Math.ceil()` for day counts.

Note: all symbols that have no specific event fall back to the earliest `'—'`-symbol event (FOMC on `2026-04-23` = **3 days**).

| Symbol | Company | Price | Direction | Horizon | Score | Status | rankDelta | scoreDelta | nextEventDays | nextEventLabel |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | Apple Inc | 185.20 | Bullish | Swing | 82 | PASS | 2 | 3 | 8 | Earnings |
| NVDA | NVIDIA Corp | 903.10 | Bullish | Swing | 79 | PASS | 1 | -2 | 1 | Earnings |
| MSFT | Microsoft Corp | 417.50 | Bullish | Position | 74 | PASS | 0 | 0 | 10 | Earnings |
| META | Meta Platforms | 512.80 | Bullish | Swing | 71 | PASS | -1 | 1 | 9 | Earnings |
| GOOGL | Alphabet Inc | 156.20 | Bullish | Swing | 68 | CAUTION | 1 | -4 | 3 | FOMC |
| AMZN | Amazon.com Inc | 184.30 | Bullish | Position | 64 | CAUTION | 0 | 2 | 3 | FOMC |
| AMD | Adv Micro Devices | 158.40 | Bullish | Swing | 61 | CAUTION | 2 | 5 | 3 | FOMC |
| TSLA | Tesla Inc | 172.90 | Bearish | Swing | 55 | CAUTION | -2 | -3 | 0 | Earnings |
| NFLX | Netflix Inc | 610.20 | Bullish | Position | 52 | CAUTION | 0 | 0 | 3 | FOMC |
| INTC | Intel Corp | 35.10 | Bearish | Position | 42 | REJECT | -3 | -6 | 3 | FOMC |

Score breakdowns (for reference — used by InlineChartPanel):

| Symbol | trend | pullback | trigger | event | volatility |
|---|---|---|---|---|---|
| AAPL | 88 | 78 | 85 | 72 | 74 |
| NVDA | 92 | 62 | 80 | 70 | 71 |
| MSFT | 82 | 70 | 68 | 78 | 70 |
| META | 78 | 68 | 70 | 65 | 74 |
| GOOGL | 72 | 66 | 64 | 68 | 70 |
| AMZN | 66 | 62 | 60 | 66 | 66 |
| AMD | 68 | 55 | 60 | 62 | 60 |
| TSLA | 44 | 60 | 55 | 58 | 58 |
| NFLX | 58 | 48 | 50 | 54 | 50 |
| INTC | 30 | 48 | 40 | 50 | 42 |

### MOCK_CONTRACTS — 6 contracts (all AAPL)

All expiry dates are 2026 Friday monthlies. DTE values computed against 2026-04-21.

| id | symbol | strike | expiry | right | dte | dteTotal | price | delta | theta | ivRank | ivPctl | spread | volume | score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL\|190\|2026-05-15\|C | AAPL | 190 | 2026-05-15 | C | 24 | 38 | 4.85 | 0.45 | -0.11 | 42 | 51 | 0.05 | 8420 | 82 |
| AAPL\|195\|2026-05-15\|C | AAPL | 195 | 2026-05-15 | C | 24 | 38 | 3.10 | 0.38 | -0.10 | 45 | 54 | 0.06 | 6180 | 78 |
| AAPL\|190\|2026-06-19\|C | AAPL | 190 | 2026-06-19 | C | 59 | 71 | 7.90 | 0.48 | -0.07 | 38 | 46 | 0.08 | 3250 | 73 |
| AAPL\|200\|2026-05-15\|C | AAPL | 200 | 2026-05-15 | C | 24 | 38 | 1.85 | 0.32 | -0.09 | 48 | 58 | 0.07 | 4710 | 67 |
| AAPL\|185\|2026-04-24\|C | AAPL | 185 | 2026-04-24 | C | 3 | 17 | 1.20 | 0.58 | -0.25 | 61 | 68 | 0.04 | 11850 | 54 |
| AAPL\|210\|2026-05-15\|C | AAPL | 210 | 2026-05-15 | C | 24 | 38 | 0.72 | 0.22 | -0.08 | 52 | 62 | 0.12 | 1940 | 42 |

`MOCK_CONTRACT_INDEX` is a `Record<string, OptionContract>` keyed by `id`.

`contractLabel(c)` produces short labels: `"AAPL 190C 05/15"`, `"AAPL 195C 05/15"`, etc.

---

## Section 10 — Task spec

### What is already implemented correctly

Reading `frontend/app/(frame)/watchlist/page.tsx` (current state):

1. **Tab state** — `useState<Tab>('stocks')` with correct switching between 'stocks' and 'contracts'. Tab buttons have correct `role="tab"` + `aria-selected`. Count badges are live.
2. **Sort state** — `useState<SortKey>` + `useState<SortDir>` with `useMemo` sort. `toggleSort` correctly flips direction on same key, resets to logical default (`asc` for symbol, `desc` for everything else) on key change.
3. **Stocks table** — `TableRow` with correct `status` prop, 9-column grid (`COLUMNS = '32px 72px 1.4fr 90px 80px 80px 90px 80px 90px'`), `WatchStar`, `RankDelta`, `EventFlag`, `StatusBadge`, direction pills.
4. **Contracts tab** — resolves `watchedContractsStore.ids` → `MOCK_CONTRACT_INDEX` → `OptionContract[]`. Renders `ContractStar`, `DTEProgressBar`, `contractLabel()`. Shows empty state when 0 contracts starred.
5. **InlineChartPanel** — opens on row click, closes on second click or via `onClose`.
6. **ContextRail** (`@contextRail/watchlist/page.tsx`) — status breakdown (PASS/CAUTION/REJECT counts), flags section (earnings ≤ 7d, total), `RailQuickLook`.
7. **CSS module** — `.tableWrap`, `.tableHeader`, `.tableBody`, `.tabs`, `.tab`, `.tabActive`, `.tabCount`, `.empty`, `.dirBull`, `.dirBear`, `.scoreCell`, `.sortBtn`, `.sortActive`, `.sortRight`, `.right` are all defined.

### What is missing, broken, or needs polish

After reading the current implementation:

1. **No `ScoreBar` in Stocks rows** — The CLAUDE.md spec says columns should include `score (with ScoreBar)`, but the current implementation shows score as `<Data>` + `<StatusBadge>` only. A mini `ScoreBar` beneath the score number would match the spec. Decide: add it inline in the `scoreCell`, or remove the spec mention. Either is acceptable — just be consistent.

2. **No `scoreDelta` column in Stocks tab** — The `WatchlistRow` carries `scoreDelta` and the CLAUDE.md spec mentions "Δrank, Δscore" columns, but the current page only renders `rankDelta` via `RankDelta`. A `scoreDelta` display (similar to `RankDelta` but for score points) is missing.

3. **Contracts tab has no sort** — The contracts table header has static `<Text>` labels (not `SortBtn`). The current sort state variables (`sortKey`, `sortDir`) only apply to the Stocks tab. Contracts tab would benefit from at least score-descending default display and ideally sortable columns (use local state, not Zustand).

4. **`RankDelta` prop name mismatch** — The current page passes `value={row.rankDelta}` but the `RankDelta` component signature expects `value: number`. This is correct — confirm `RankDelta` is not expecting a prop named `delta`.

5. **ContextRail counts MOCK_WATCHLIST statically** — The "Earnings ≤ 7d" count in the ContextRail uses `(r.nextEventDays ?? 999) <= 7`. Given the actual event data (NVDA=1d, TSLA=0d, GOOGL/AMZN/AMD/NFLX/INTC=3d FOMC), the count will be **7** (not matching the LLM_CONTEXT.md table which was written with different event values). This is correct behavior — the ContextRail accurately reflects the live mock data.

6. **ContextRail does not reflect Contracts tab state** — When the user switches to the Contracts tab, the ContextRail still shows stock status breakdown. There is no dynamic update. This is a known limitation for a parallel route slot — acceptable to leave as-is or add a note.

7. **Tab count badge on active tab** — The `.tabActive .tabCount` rule uses `var(--accent-bg, var(--bg-surface-2))`. The token `--accent-bg` does not exist in `tokens.css` (only `--accent-dim` exists). This will silently fall back to `--bg-surface-2` which is fine visually, but the CSS variable reference should be cleaned up.

8. **Header/subheader layout** — The `.heading` div uses `justify-content: space-between` with `align-items: baseline`. The subtitle text changes between tabs (shows sort info for stocks, count for contracts). This is correct and good.

### Acceptance criteria (testable)

- [ ] Navigating to `/watchlist` shows the Stocks tab by default with 10 rows.
- [ ] Clicking each sortable column header changes sort order; clicking the same header again reverses direction. The active column header is visually distinguished.
- [ ] Each row shows: star icon, symbol (monospace), company name, price with `$` prefix, direction pill (green/red), horizon text, score number, status badge, rank delta arrow, event flag.
- [ ] Clicking a row opens `InlineChartPanel` below the table. Clicking the same row again closes it.
- [ ] `WatchStar` state persists across page navigations (localStorage-backed store).
- [ ] Switching to the Contracts tab shows the correct count in the tab badge.
- [ ] Contracts tab shows empty state with correct message when no contracts are starred.
- [ ] Contracts tab shows rows for each starred contract with all columns populated.
- [ ] `ContractStar` in the contracts tab can toggle a contract on/off; the row disappears when un-starred.
- [ ] `npm run typecheck` passes with zero errors.
- [ ] No hardcoded hex colors anywhere in page.tsx or page.module.css.
- [ ] No inline `style={{}}` except for computed values (e.g. `style={{ gridTemplateColumns: COLUMNS }}`).
- [ ] `--accent-bg` fallback in `.tabActive .tabCount` is replaced with a valid token (e.g. `--accent-dim`).

---

## Section 11 — Hard rules

1. **No Tailwind, styled-components, or CSS-in-JS.** CSS Modules only.
2. **No inline `style={{}}` except computed one-offs** (e.g. `style={{ width: '${pct}%' }}` or `style={{ gridTemplateColumns: COLUMNS }}`).
3. **Never hardcode colors.** Always use CSS custom properties from `tokens.css`.
4. **Status labels:** only `PASS | CAUTION | REJECT | PENDING | NO_DATA`. Never invent labels like "Active", "Long", "Watch".
5. **No font-weight 600 on form labels.**
6. **No card box-shadows.** Use `border: 1px solid var(--border-subtle)`.
7. **Component hierarchy:** atom → molecule → organism. Never skip levels. Reuse existing components before creating new ones.
8. **`npm run typecheck` must be clean before every commit.** Fix all TypeScript errors before calling anything done.
9. **Do not touch `node_modules/` or `package-lock.json`.**
10. **Do NOT modify `watchlistStore.ts` or `watchedContractsStore.ts`.** Their interfaces and actions are frozen for this workstream.
11. **Do NOT add sorting state to Zustand.** Sort state lives in local React `useState` only.
12. **Stocks tab uses `MOCK_WATCHLIST` (10 rows). Contracts tab uses `MOCK_CONTRACT_INDEX` resolved from `watchedContractsStore.ids`.**
13. **`ContractStar` writes to `watchedContractsStore` using canonical ID format: `SYMBOL|STRIKE|EXPIRY|C/P`** (e.g. `AAPL|190|2026-05-15|C`). The `id` field on `OptionContract` is already in this format — pass `c.id` directly.

---

## Section 12 — Dev workflow

```bash
cd frontend
npm run dev       # localhost:3001 — navigate to /watchlist
npm run typecheck # tsc --noEmit — must be clean before every commit
npm run lint      # next lint
npm run build     # full production build check
```

After starting dev server, visit `http://localhost:3001/watchlist`.

Test Contracts tab by first going to `/screener/step-6-contracts` and starring one or more contracts, then returning to `/watchlist` and clicking the Contracts tab.

---

## Section 13 — Copy/paste prompt

Paste this verbatim to the implementing LLM. It is fully self-contained.

---

You are working on the Bamendjou options screener — a Next.js 15 / TypeScript / CSS Modules app. Read `llm-contexts/06-watchlist.md` in the project root before touching any code. That file is your complete source of truth for this task.

**Your task:** Polish the Watchlist page and its ContextRail slot to production quality.

**Owned files** (the only files you may edit or create):
- `frontend/app/(frame)/watchlist/page.tsx`
- `frontend/app/(frame)/watchlist/page.module.css`
- `frontend/app/(frame)/@contextRail/watchlist/page.tsx`
- `frontend/app/(frame)/@contextRail/watchlist/page.module.css`

**Do NOT modify:**
- Any Zustand store files (`watchlistStore.ts`, `watchedContractsStore.ts`)
- Any mock files
- `(frame)/layout.tsx`
- `styles/tokens.css` or `globals.css`
- Any other page outside the watchlist folder

**Polish targets in priority order:**

1. Fix the invalid CSS token reference `var(--accent-bg, ...)` in `page.module.css` — replace with `var(--accent-dim)`.
2. Add a `scoreDelta` display to the Stocks tab. The `WatchlistRow` type carries `scoreDelta?: number`. Add it as a column between `RankDelta` and the event flag. Match the visual style of `RankDelta` (green for positive, red for negative, dash for zero). Either reuse `RankDelta` with a different label or write a small inline helper. Update `COLUMNS` to fit.
3. Add sort capability to the Contracts tab. Add a `contractSortKey` and `contractSortDir` local state. Add `SortBtn` header buttons for score (default desc), DTE, and price. The sort logic mirrors the Stocks tab pattern.
4. Verify the `ScoreBar` usage question: the CLAUDE.md spec mentions "score (with ScoreBar)" for the Stocks tab columns. If adding a `ScoreBar` inline in the row score cell is feasible within the column grid without breaking alignment, add it as a mini bar below the score number. Otherwise, skip it and document why in a code comment.
5. Review the ContextRail slot. Confirm counts are accurate given the actual mock event data. If the "Earnings ≤ 7d" label is misleading (since FOMC events are also counted), either rename it to "Events ≤ 7d" or tighten the filter to only label-matched "Earnings" events.

**Constraints from `llm-contexts/06-watchlist.md`:**
- CSS Modules only — no Tailwind, no inline styles except computed values
- Never hardcode colors — CSS custom properties only
- Do NOT add sorting state to Zustand — local React state only
- Sort state for Contracts tab uses separate local state variables from the Stocks tab sort
- `npm run typecheck` must pass clean when you are done

Start by reading the current `page.tsx` and `page.module.css` files, then implement the changes. Run `npm run typecheck` after each significant change.

---
