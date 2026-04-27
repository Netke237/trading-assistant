# Bamendjou — LLM Context Document

> **How to use this file**
> You are working on the Bamendjou options screener (Next.js 15, TypeScript).
> This file is the single source of truth for every convention, default value, and design decision in the project.
> Read this file fully before touching any code. When in doubt about a value, a name, or a pattern — come back here.
> All work lives in `frontend/`. The project root only contains this file and `CLAUDE.md`.

---

## 1. What the app is

A 7-step options screener for an individual trader (Kenneth).
The user picks a universe and direction in steps 1–2, validates market regime in step 3,
ranks candidates in step 4, checks volatility and event risk in step 5,
selects a contract in step 6, and reviews a full trade card in step 7.

There is no backend yet. Everything runs on deterministic mocks. FastAPI will replace mocks later.

---

## 2. Stack

| Layer | Choice | Version |
|---|---|---|
| Framework | Next.js (App Router, `'use client'` where needed) | ^15.1.0 |
| Language | TypeScript — strict, path alias `@/` → `frontend/` | ^5.7.0 |
| Styling | CSS Modules only — **no Tailwind, no inline style objects except one-off `style={}` props** | — |
| Charts | lightweight-charts (TradingView) | ^5.0.0 |
| Animation | framer-motion — minimal use | ^11.15.0 |
| State | Zustand | ^5.0.2 |
| Data | Deterministic mocks in `mocks/` | — |
| TypeCheck | `npm run typecheck` (`tsc --noEmit`) — **must be clean before every commit** | — |

---

## 3. Folder layout

```
frontend/
  app/
    globals.css               # imports tokens.css + reset.css
    styles/
      tokens.css              # ALL CSS custom properties — single source
      reset.css
    (frame)/
      layout.tsx              # Persistent shell (TopBar, NavRail, ContextRail)
      screener/
        layout.tsx            # Adds StepNavBar at bottom
        screener.module.css   # Shared .main / .stepHeader / .stepBody classes
        step-1-universe/
        step-2-direction/
        step-3-regime/
        step-4-ranking/
        step-5-vol-events/
        step-6-contracts/
        step-7-trade-card/
      dashboard/
      watchlist/
      portfolio/
      calendar/
      settings/
  components/
    primitives/               # Text, Title, Data — font/tone/size only
    atoms/                    # Single-purpose UI: StatusBadge, WatchStar, RankDelta, EventFlag…
    molecules/                # Composed: TableRow, SymbolHeader, CandidateNav…
    organisms/                # Full sections: TopBar, StepNavBar, TradeCard, SendToBrokerDialog…
  lib/                        # Zustand stores + pure helpers
  mocks/                      # Deterministic fixture data
  styles/                     # tokens.css + reset.css (also imported by globals.css)
  types/
    domain.ts                 # Shared domain types
    chart.ts                  # Candle type
```

---

## 4. Design tokens (CSS custom properties)

All tokens come from `frontend/styles/tokens.css`. Never hardcode colors or spacing.

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

## 5. Status system

```ts
// lib/status.ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA';
```

**Score → Status thresholds** (used by `statusForScore`):
- `score >= 70` → `PASS`
- `score >= 50` → `CAUTION`
- `score < 50`  → `REJECT`

**Event proximity → Status** (used by `eventProximity` in `lib/date.ts`):
- `days <= 3`  → `'imminent'` → gate becomes `REJECT`
- `days <= 7`  → `'near'`     → gate becomes `CAUTION`
- `days > 7`   → `'distant'`  → gate inherits IV status

**IV rank → Status** (Step 5 logic):
- `rank >= 60` → `PASS`
- `rank >= 35` → `CAUTION`
- `rank < 35`  → `REJECT`

**Step 5 gate** = worst of (IV status, event proximity status).

**Status label display names:**
```
PASS    → "PASS"
CAUTION → "CAUTION"
REJECT  → "REJECT"
PENDING → "PENDING"
NO_DATA → "NO DATA"
```

**DO NOT** invent labels like "LONG", "SHORT", "Active". Those are Direction/position-state concepts.

---

## 6. Primitive components

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

---

## 7. Component conventions

- **Atoms → Molecules → Organisms** — never skip levels.
- Each component lives in its own folder: `ComponentName/index.tsx` + `ComponentName.module.css`.
- **No card shadows** — use `border: 1px solid var(--border-subtle)` instead.
- Status tints use `color-mix(in srgb, var(--pass/caution/reject) N%, var(--bg-surface))`.
- CSS variables from `styles/tokens.css` — never hardcode colours.

### Key atoms

| Component | Props | Notes |
|---|---|---|
| `StatusBadge` | `status: Status`, `label?: string` | Use for gate/row status |
| `EventFlag` | `days: number`, `title?: string` | Calendar icon + Nd; colored by proximity |
| `WatchStar` | `symbol: string`, `size?: 'sm'|'md'` | Writes to watchlistStore |
| `ContractStar` | `contractId: string` | Writes to watchedContractsStore |
| `RankDelta` | `delta: number`, `context?: string` | Arrow + number |
| `ScoreBar` | `score: number`, `max?: number` | Fill colored by statusForScore |
| `StatusDot` | `status: Status` | Small circle indicator |

### Key molecules

| Component | Props | Notes |
|---|---|---|
| `TableRow` | `status`, `columns` (grid-template-columns string), `selected?`, `onClick?` | Status-tinted grid row |
| `SectionCard` | — | Surface card with border |
| `ScoreCardPanel` | — | Score breakdown display |
| `DTEProgressBar` | `daysRemaining`, `totalDays` | DTE visual |
| `CandidateNav` | — | Prev/Next/Pin for Step 7 |

### Key organisms

| Component | Notes |
|---|---|
| `TopBar` | Scan context, scan state pill, regime dot |
| `StepNavBar` | Back/Next + keyboard ←/→; REJECT gate on Step 3→4 |
| `TradeCard` | Full trade detail for Step 7 |
| `SendToBrokerDialog` | Confirmation dialog for order submission |
| `CandlestickChart` | lightweight-charts v5 wrapper |
| `InlineChartPanel` | Right-panel chart for Step 4 |

---

## 8. Domain types (`types/domain.ts`)

```ts
type Direction = 'Bullish' | 'Bearish';
type Horizon   = 'Swing' | 'Position';
type AlertKind = 'Info' | 'Action' | 'Critical';
type OrderType = 'Limit' | 'Market' | 'Stop';

interface ScoreBreakdown {
  trend:      number;   // 0–100
  pullback:   number;
  trigger:    number;
  event:      number;
  volatility: number;
}

interface ContractScoreBreakdown {
  dteFit:           number;
  delta:            number;
  ivAttractiveness: number;
  liquidity:        number;
  spread:           number;
}

interface WatchlistRow {
  symbol:         string;
  company:        string;
  price:          number;
  direction:      Direction;
  horizon:        Horizon;
  score:          number;          // 0–100
  rankDelta:      number;          // position change vs last scan
  scoreDelta?:    number;          // score pts change
  status:         Status;
  breakdown:      ScoreBreakdown;
  nextEventDays?: number;          // days to next earnings/FOMC/etc
  nextEventLabel?: string;         // "Earnings", "FOMC"
}

interface PortfolioPosition {
  symbol:        string;
  contract:      string;           // "AAPL 220C 05/16"
  direction:     Direction;
  entryDate:     string;           // ISO date
  expiry:        string;           // ISO date
  dteRemaining:  number;
  dteTotal:      number;
  entryPrice:    number;
  currentPrice:  number;
  pnlDollar:     number;
  pnlPct:        number;
  stop:          number;
  target:        number;
  status:        Status;
  ivRank?:       number;           // 0–100
  delta?:        number;           // –1..+1
  theta?:        number;           // $/day (negative for longs)
  vega?:         number;
  contracts?:    number;
  source?:       'broker' | 'manual';
  orderedAt?:    string;           // ISO timestamp
}
```

**Contract canonical ID format:** `SYMBOL|STRIKE|EXPIRY|C/P`
Example: `AAPL|185|2025-05-16|C`

---

## 9. Zustand stores (`lib/`)

### `scanStore.ts`

```ts
type ScanState = 'IDLE' | 'SCANNING' | 'COMPLETED' | 'FAILED';

interface ScanContext {
  universe:  string;    // "SP500" | "NAS100" | ...
  direction: Direction;
  horizon:   string;    // "Swing (5–15d)"
}

// Default seed values:
scanState: 'COMPLETED'
scanAt:    '2026-04-20T09:42:00'   // yesterday — shows TopBar date-prefix behaviour
context:   { universe: 'SP500', direction: 'Bullish', horizon: 'Swing (5–15d)' }
regime:    'PASS'
```

`scanStore.regime` is set by Step 3 on mount. StepNavBar reads it to show the REJECT gate when navigating from Step 3 → Step 4.

### `watchlistStore.ts`
Starred stock symbols. Symmetric add/remove.

### `watchedContractsStore.ts`
Starred contracts by canonical ID.

### `portfolioStore.ts`
Open positions. `addPosition` merges duplicate contracts.

---

## 10. Mocks (`mocks/`)

All mocks live in `frontend/mocks/`. They are replaced by `fetch()` calls when the FastAPI backend arrives.

### `watchlist.ts` — `MOCK_WATCHLIST: WatchlistRow[]`

10 rows (status derived from `statusForScore(score)`):

| Symbol | Company | Price | Direction | Horizon | Score | Status | rankDelta | scoreDelta | nextEventDays | nextEventLabel |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | Apple Inc | 185.20 | Bullish | Swing | 82 | PASS | +2 | +3 | 14 | Earnings |
| NVDA | NVIDIA Corp | 903.10 | Bullish | Swing | 79 | PASS | +1 | -2 | 3 | Earnings |
| MSFT | Microsoft Corp | 417.50 | Bullish | Position | 74 | PASS | 0 | 0 | 21 | Earnings |
| META | Meta Platforms | 512.80 | Bullish | Swing | 71 | PASS | -1 | +1 | 10 | Earnings |
| GOOGL | Alphabet Inc | 156.20 | Bullish | Swing | 68 | CAUTION | +1 | -4 | 9 | Earnings |
| AMZN | Amazon.com Inc | 184.30 | Bullish | Position | 64 | CAUTION | 0 | +2 | 16 | Earnings |
| AMD | Adv Micro Devices | 158.40 | Bullish | Swing | 61 | CAUTION | +2 | +5 | 11 | Earnings |
| TSLA | Tesla Inc | 172.90 | Bearish | Swing | 55 | CAUTION | -2 | -3 | 2 | Earnings |
| NFLX | Netflix Inc | 610.20 | Bullish | Position | 52 | CAUTION | 0 | 0 | 8 | Earnings |
| INTC | Intel Corp | 35.10 | Bearish | Position | 42 | REJECT | -3 | -6 | 19 | Earnings |

### `regime.ts` — `MOCK_REGIME: MarketRegime`

```ts
overall: 'PASS'
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

### Other mocks

| File | Feeds |
|---|---|
| `contracts.ts` | Step 6 (12-col sortable table), Watchlist contracts tab |
| `candles.ts` | Steps 3 & 4 charts — seeded RNG (Mulberry32), stable across reloads |
| `sectors.ts` | Step 3 sector heatmap |
| `tradecards.ts` | Step 7 per-candidate trade cards |
| `portfolio.ts` | Portfolio page seed data |
| `alerts.ts` | Dashboard alert feed |
| `events.ts` | Calendar page |

---

## 11. Screener workflow — 7 steps

StepNavBar handles Back/Next navigation. Keyboard: ← Back, → Next.

| Step | Slug | Status | Description |
|---|---|---|---|
| 1 | `step-1-universe` | Done | Universe picker + price/cap min-max filters |
| 2 | `step-2-direction` | Done | Directional bias (Bullish/Bearish) + horizon preset tiles |
| 3 | `step-3-regime` | Done | Banner, explainer, SPX/NDX charts, metric grid (trend arrows), sector heatmap, REJECT dialog |
| 4 | `step-4-ranking` | Done | Sortable 6-col table (Δrank, Δscore), right-panel chart, score component cards |
| 5 | `step-5-vol-events` | Done | IV rank mini bar, IV percentile column, event proximity gate |
| 6 | `step-6-contracts` | Done | 12-col sortable table, ContractStar |
| 7 | `step-7-trade-card` | Done | CandidateNav (Prev/Next/Pin), basket, SendToBrokerDialog |

### Step 3 → Step 4 REJECT gate
If `scanStore.regime === 'REJECT'`, clicking Next shows a confirmation overlay before proceeding.
The overlay title is `"Regime flagged as REJECT"` (not CAUTION — only fires on REJECT).
Buttons: `Cancel` and `Proceed anyway →`.

### Step 5 column layout
```ts
const COLUMNS = '32px 72px 1fr 120px 70px 110px 80px';
// cols: [star] [symbol] [name] [IV rank+bar] [IV pctl] [next event] [gate]
```

IV rank is computed from a deterministic symbol hash (range 20–90).
IV percentile is correlated with rank but offset by ±10.

---

## 12. Shared screener layout classes

From `screener.module.css` (imported as `styles` in every step page):

```css
.main       { display: flex; flex-direction: column; gap: var(--space-4); padding: var(--space-6); }
.stepHeader { display: flex; flex-direction: column; gap: var(--space-1); }
.stepBody   { display: flex; flex-direction: column; gap: var(--space-3);
              padding: var(--space-5); background: var(--bg-surface);
              border: 1px solid var(--border-subtle); border-radius: var(--radius-lg);
              min-height: 280px; }
```

Step header always renders:
```tsx
<Text size={11} tone="dim" weight={500}>STEP N OF 7</Text>
<Title as="h1" size={24}>{Page title}</Title>
<Text size={13} tone="secondary">{One-line description}</Text>
```

---

## 13. Settings page

Sub-nav: **Broker · Appearance · Score weights & parameters · Alerts**

**Score weights & parameters** tab has a 4-tab horizon strip:
- `Intraday` / `Swing` / `Position` — read-only preset weights + indicator parameters
- `Custom` — fully editable; stores `customW` (weights) + `customParams` (indicator params) in local state

Each component row has a collapsible "Metrics & parameters" section.

---

## 14. What is done

- All 7 screener steps — fully implemented with mocks
- StepNavBar keyboard nav + REJECT gate overlay
- StatusBadge, EventFlag, WatchStar, ContractStar, RankDelta, ScoreBar atoms
- TradeCard + SendToBrokerDialog
- CandidateNav (Prev/Next/Pin)
- Portfolio page with DTE bars, Greeks columns
- Watchlist page — Stocks + Contracts tabs
- Dashboard — regime banner, alert feed
- Calendar page — upcoming events
- Settings page — all 4 tabs including editable Custom weights
- Dark/light theme toggle (ThemeProvider + ModeToggle)
- MinWidthGate — blocks viewports below 1200px
- KeyboardShortcuts component
- Zustand stores: scanStore, watchlistStore, watchedContractsStore, portfolioStore

---

## 15. What still needs to be done

### Immediate polish

- **Step 5 review** — verify IV rank bar widths match spec; confirm gate logic is correct for all 10 mock rows; check NEXT EVENT column alignment at narrow widths.
- **Responsive audit** — all steps tested only at 1440px; check 1200px (the min gate).

### Backend integration (FastAPI — not started)

- Replace every `MOCK_*` import with `fetch()` / SWR / React Query calls.
- Persist `scanStore.context` and `regime` from real API responses.
- Wire `portfolioStore.addPosition` to a POST endpoint.
- Persist Settings custom weights to localStorage or a user-preferences endpoint.

### Features not yet built

- **Real candle data** — current charts use seeded RNG; hook up to a market-data provider.
- **Alerts** — dashboard feed is static; needs a WebSocket or polling channel.
- **Broker integration** — `SendToBrokerDialog` shows a UI but does not call any broker API.
- **Screener Step 1 universe filter** — price/cap filters exist in UI but don't actually filter `MOCK_WATCHLIST`.
- **Screener Step 2 direction/horizon** — selection is stored in `scanStore.context` but does not filter downstream steps.
- **Auth / user accounts** — no login, no session management.

### Known tech debt

- None currently. Previous items (mock file consolidation, event data unification, any casts) have been resolved.

---

## 16. Dev commands

```bash
cd frontend
npm run dev          # localhost:3001 (3000 often taken)
npm run typecheck    # tsc --noEmit — must be clean before every commit
npm run lint         # next lint
npm run build        # full production build
```

---

## 17. Rules — what NOT to do

- Do not add Tailwind, styled-components, or any CSS-in-JS library.
- Do not add inline `style={{}}` for anything other than computed one-off values (e.g. `style={{ width: \`${pct}%\` }}`).
- Do not hardcode colours — always use CSS custom properties from `tokens.css`.
- Do not invent new Status labels. The only valid values are `PASS | CAUTION | REJECT | PENDING | NO_DATA`.
- Do not use font-weight 600 on form labels.
- Do not add card box-shadows — use `border: 1px solid var(--border-subtle)`.
- Do not skip component hierarchy levels (atom → molecule → organism).
- Do not commit with a failing `npm run typecheck`.
- Do not touch `node_modules/` or `package-lock.json` unless explicitly asked.
