# Bamendjou — Options Screener

Next.js 15 options screener for Kenneth. All work lives in `frontend/`.
Repo: github.com/Netke237/trading-assistant (private).

---

## Stack

| Layer | Choice |
|---|---|
| Framework | Next.js 15 (App Router, `'use client'` where needed) |
| Language | TypeScript 5.7 — strict, path alias `@/` → `frontend/` |
| Styling | CSS Modules only — no Tailwind, no inline style objects except one-offs |
| Charts | lightweight-charts v5 (TradingView) |
| Animation | framer-motion (minimal use) |
| State | Zustand v5 — one store per domain |
| Data | Deterministic mocks in `mocks/` — no backend yet |
| Typecheck | `npm run typecheck` (`tsc --noEmit`) — must be clean before every commit |

---

## Folder layout

```
frontend/
  app/
    (frame)/              # Persistent shell (TopBar, NavRail, ContextRail)
      layout.tsx          # Frame layout with parallel @contextRail slot
      screener/           # 7-step screener workflow
        layout.tsx        # Adds StepNavBar at bottom
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
    primitives/           # Text, Title, Data — font/tone/size only
    atoms/                # Single-purpose UI: StatusBadge, WatchStar, RankDelta, EventFlag…
    molecules/            # Composed: TableRow, SymbolHeader, CandidateNav…
    organisms/            # Full sections: TopBar, StepNavBar, TradeCard, SendToBrokerDialog…
  lib/                    # Zustand stores + pure helpers
  mocks/                  # Deterministic fixture data (replace with fetch() later)
  types/
    domain.ts             # Shared domain types (WatchlistRow, PortfolioPosition…)
    chart.ts              # Candle type
```

---

## Component conventions

- **Atoms → Molecules → Organisms** — never skip levels
- Each component lives in its own folder: `ComponentName/index.tsx` + `ComponentName.module.css`
- **No card shadows** — use `border: 1px solid var(--border-subtle)` instead
- **No font-weight 600 on form labels** — use `weight={400}`
- CSS variables come from the global token sheet (`app/globals.css`) — never hardcode colours
- Status tints use `color-mix(in srgb, var(--pass/caution/reject) N%, var(--bg-surface))`

---

## Primitives

```tsx
<Text size={11|12|13|14} tone="primary|secondary|dim|pass|caution|reject" weight={400|500|600} />
<Title as="h1|h2|h3" size={18|20|24} />
<Data size={11..24} weight={500|600} tone="pass|caution|reject" />  // monospace, tabular-nums
```

---

## Zustand stores (`lib/`)

| File | Purpose |
|---|---|
| `scanStore.ts` | Scan state, scan context (universe/direction/horizon), regime status |
| `watchlistStore.ts` | Starred symbols — symmetric add/remove, versioned migrate |
| `watchedContractsStore.ts` | Starred contracts |
| `portfolioStore.ts` | Open positions — `addPosition` merges duplicate contracts |

`scanStore.regime` is set by Step 3 on mount and read by StepNavBar for the REJECT gate.

---

## Mocks (`mocks/`)

| File | Feeds |
|---|---|
| `watchlist.ts` | Steps 4, 5; Watchlist page stocks tab |
| `contracts.ts` | Step 6; Watchlist contracts tab |
| `candles.ts` | Steps 3, 4 charts — seeded RNG (Mulberry32), stable across reloads |
| `regime.ts` | Step 3 banner + metric grid |
| `sectors.ts` | Step 3 sector heatmap |
| `tradecards.ts` | Step 7 per-candidate trade cards |
| `portfolio.ts` | Portfolio page seed data |
| `alerts.ts` | Dashboard alert feed |
| `events.ts` | Calendar page |

All mocks are replaced by `fetch()` calls when the FastAPI backend lands.
Contract canonical ID format: `SYMBOL|STRIKE|EXPIRY|C/P` (e.g. `AAPL|185|2025-05-16|C`).

---

## Screener workflow (7 steps)

| Step | Slug | Status |
|---|---|---|
| 1 | `step-1-universe` | Done — universe picker + price/cap min-max filters |
| 2 | `step-2-direction` | Done — directional bias + horizon preset tiles |
| 3 | `step-3-regime` | Done — banner, explainer, SPX/NDX charts, metric grid (trend arrows), sector heatmap, REJECT dialog |
| 4 | `step-4-ranking` | Done — sortable 6-col table (Δrank, Δscore), right-panel chart, score component cards |
| 5 | `step-5-vol-events` | Done — IV rank mini bar, IV percentile column, event proximity gate |
| 6 | `step-6-contracts` | Done — 12-col sortable table, ContractStar |
| 7 | `step-7-trade-card` | Done — CandidateNav (Prev/Next/Pin), basket, SendToBrokerDialog |

StepNavBar handles Back/Next navigation and keyboard shortcuts (←/→).
On Step 3, if `scanStore.regime === 'REJECT'`, clicking Next shows a confirmation overlay before proceeding to Step 4.

---

## Settings page

Sub-nav: Broker · Appearance · Score weights & parameters · Alerts.

**Score weights & parameters** has a 4-tab horizon strip:
- **Intraday / Swing / Position** — read-only preset weights + indicator parameters
- **Custom** — fully editable; stores `customW` (weights) + `customParams` (indicator params) in local state

Each component row has a collapsible "Metrics & parameters" section listing the metrics and their configurable values (MA periods, volume lookbacks, event buffers, etc.).

---

## Key patterns

### Status system
```ts
type Status = 'PASS' | 'CAUTION' | 'REJECT' | 'PENDING' | 'NO_DATA'
// lib/status.ts — statusForScore(score: number): Status
```

### Rank / score deltas
`WatchlistRow` carries both `rankDelta` (position change) and `scoreDelta` (score pts change).
`RankDelta` component accepts a `context` prop for tooltip text ("rank" → "Up 2 ranks since last scan").

### Watchlist
`WatchStar` (stocks) and `ContractStar` (contracts) write to their respective Zustand stores.
Watchlist page has Stocks / Contracts tabs.

---

## Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001 (3000 often occupied)
npm run typecheck    # must be clean — run before every commit
```

Min-width gate: 1200px (`MinWidthGate.tsx`) — shows a "rotate / resize" message below that.

---

## What's next

- Step 5 (Vol + Events) — review and polish
- Backend integration — FastAPI; replace mocks with `fetch()`
- Persist Settings (weights + custom params) to localStorage or backend
