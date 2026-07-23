# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Bamendjou — Stock & Options Screener

Next.js 15 screener (stocks + options) for Kenneth. Frontend lives in `frontend/`, backend in `backend/`.
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
| Data | FastAPI backend via `frontend/lib/api.ts`; Jest mocks in `frontend/__mocks__/` |
| Typecheck | `npm run typecheck` (`tsc --noEmit`) — must be clean before every commit |

---

## Folder layout

```
frontend/
  app/
    (frame)/              # Persistent shell (TopBar, NavRail, ContextRail)
      layout.tsx          # Frame layout with parallel @contextRail slot
      screener/           # Multi-mode screener (Options / Stocks toggle in layout)
        layout.tsx        # Mode toggle + StepNavBar
        step-1-regime/    # Market regime (Markov/HMM, SPX/NDX charts, sector heatmap)
        step-2-universe/  # Universe picker + price/cap filters
        step-3-direction/ # Direction + horizon + Execution Parameters panel
        step-4-stocks/    # [Stocks mode] Stock scan results table, StockPositionCard
        step-4-ranking/   # [Options mode] Sortable ranked candidates table
        step-5-strategy/  # [Stocks mode] Strategy picker (pullback_ema, breakout_base…)
        step-5-vol-events/# [Options mode] IV rank, IV percentile, event proximity gate
        step-6-backtest/  # [Stocks mode] Backtest results + confidence gate
        step-6-contracts/ # [Options mode] 12-col sortable contracts table, ContractStar
        step-7-position-card/ # [Stocks mode] Position card + broker execution
        step-7-trade-card/    # [Options mode] CandidateNav, basket, SendToBrokerDialog
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
  types/
    domain.ts             # Shared domain types (WatchlistRow, PortfolioPosition…)
    stockDomain.ts        # Stock-mode types (PositionCardData, StockScoreCard…)
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
| `scanStore.ts` | Scan state, scan context (universe/direction/horizon), regime status, `screenerMode` ('options'\|'stocks') |
| `scanParamsStore.ts` | Execution parameters (strategy params, horizon preset) fed into stock scan |
| `settingsStore.ts` | Broker config (IBKR/Tradier/Alpaca paper+live), `premiumStopPct`, IV thresholds, `confidenceGate`, `fundamentalsGate`, `markov` config, shortlist/contract/price limits |
| `watchlistStore.ts` | Starred symbols — symmetric add/remove, versioned migrate |
| `watchedContractsStore.ts` | Starred contracts |
| `portfolioStore.ts` | Open positions — `addPosition` merges duplicate contracts |
| `riskStore.ts` | Risk settings (position sizing, max loss per trade) |
| `alertStore.ts` | Price/condition alerts |
| `chartAlertStore.ts` | Chart-drawn alert levels |
| `strategyWatchStore.ts` | Strategy watch subscriptions |
| `drawingStore.ts` | Chart drawings |
| `chartStore.ts` | Active chart symbol + interval |
| `performanceStore.ts` | Portfolio performance history |
| `autoTradeStore.ts` | Auto-trade state |
| `universeStore.ts` | Selected universe + custom symbols |
| `structureStore.ts` | Market structure cache |

`scanStore.regime` is set by Step 1 on mount and read by StepNavBar for the REJECT gate.
`scanStore.screenerMode` switches between the Options path (steps 4-ranking → 5-vol-events → 6-contracts → 7-trade-card) and the Stocks path (steps 4-stocks → 5-strategy → 6-backtest → 7-position-card).

---

## Backend (`backend/`)

Connected to the frontend via `frontend/lib/api.ts`.

| Layer | Choice |
|---|---|
| Framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| ORM / migrations | SQLAlchemy v2 + Alembic |
| Database | PostgreSQL via AsyncPG; aiosqlite fallback |
| Tests | pytest + pytest-asyncio |

Key paths: `backend/app/main.py` (entry), `backend/app/routers/` (endpoints), `backend/app/services/` (business logic), `backend/app/scoring/` (scoring algorithms), `backend/app/data/` (data adapters), `backend/config/*.yaml` (contract_rules, risk_rules, scoring_rules, strategy_params, strategy_watches, settings).

Test fixtures live in `backend/tests/fixtures/` (OHLCV JSON files per symbol).

---

## Screener workflow

The screener has two modes toggled in the layout header: **Options** and **Stocks**.
Steps 1–3 are shared; steps 4–7 diverge per mode.

### Shared steps

| Step | Slug | Description |
|---|---|---|
| 1 | `step-1-regime` | Market regime — Markov/HMM banner, SPX/NDX charts, EMA/VIX metric grid, horizon regime card, sector heatmap, market news |
| 2 | `step-2-universe` | Universe picker (SP500, NDX100, DOW30, custom) + price/cap min-max filters |
| 3 | `step-3-direction` | Direction (Bullish/Bearish) + horizon preset, Execution Parameters panel (34 params), Run Scan button |

### Options path (steps 4–7)

| Step | Slug | Description |
|---|---|---|
| 4 | `step-4-ranking` | Sortable ranked candidates table (Δrank, Δscore), right-panel candlestick chart, per-component score cards |
| 5 | `step-5-vol-events` | IV rank mini bar, IV percentile column, event proximity gate (per-horizon reject/caution window fetched from `/api/config/event-thresholds`, e.g. Swing reject <21d / caution <45d) |
| 6 | `step-6-contracts` | 12-col sortable contracts table, ContractStar |
| 7 | `step-7-trade-card` | CandidateNav (Prev/Next/Pin), basket, SendToBrokerDialog, AlternativeContractRow |

### Stocks path (steps 4–7)

| Step | Slug | Description |
|---|---|---|
| 4 | `step-4-stocks` | Stock scan results table (status tint, score, WatchStar), StockPositionCard preview, StockSendDialog |
| 5 | `step-5-strategy` | Strategy picker (pullback_ema, breakout_base, ma_crossover, mean_reversion_rsi) + StrategyParamsPanel |
| 6 | `step-6-backtest` | Backtest results per candidate — confidence gate (pass/fail), win rate, expectancy |
| 7 | `step-7-position-card` | Position card with ConfidenceBadge + broker execution mode selector (IBKR/Tradier/Alpaca paper) |

StepNavBar handles Back/Next navigation and keyboard shortcuts (←/→).
If `scanStore.regime === 'REJECT'`, clicking Next on Step 1 shows a confirmation overlay.

---

## Stock scanner pipeline

All stock-mode logic lives in `backend/app/`:

| Module | Path | Role |
|---|---|---|
| `stock_scorer` | `scoring/stock_scorer.py` | 5-rule weighted scorer (trend, pullback, trigger, event, vol) → `StockScoreCard` (0–100) |
| `fundamentals_scorer` | `scoring/fundamentals_scorer.py` | EDGAR-sourced health score (growth 35%, quality 35%, risk 30%) → `FundamentalHealth` (0–100) |
| `signal_confidence` | `scoring/signal_confidence.py` | Backtest-based confidence layer |
| `entry_quality` | `scoring/entry_quality.py` | Entry quality sub-score |
| `reward_risk` | `scoring/reward_risk.py` | Reward/risk ratio scoring |
| `strategy_engine` | `services/strategy_engine.py` | Four named signal functions: `pullback_ema_signal`, `breakout_base_signal`, `ma_crossover_signal`, `mean_reversion_rsi_signal` |
| `strategy_backtest` | `services/strategy_backtest.py` | Vectorised backtest runner over OHLCV bars — returns win rate, expectancy, passes_gate |
| `walk_forward` | `services/walk_forward.py` | Rolling + anchored WFO fold construction over strategy_backtest |
| `strategy_param_optimizer` | `services/strategy_param_optimizer.py` | Grid-search param tuning driven by WFO |
| `strategy_watch_evaluator` | `services/strategy_watch_evaluator.py` | State-machine evaluator — emits transition events (idle→entry, armed→exit) for strategy watches |
| `fundamentals_gate` | `services/fundamentals_gate.py` | Applies `fundamentalsGate` thresholds (caution/reject/D-E cap) as a status cap |

Config: `scoring_rules.yaml` (scorer weights/thresholds), `strategy_params.yaml` (strategy defaults), `strategy_watches.yaml` (per-symbol watch subscriptions).

---

## Integrations

### Data adapters (`backend/app/data/`)

| Adapter | File | Notes |
|---|---|---|
| EDGAR | `edgar.py` | Pulls SEC XBRL fundamentals → `FundamentalsSnapshot`; nightly prefetch via `edgar_scheduler.py` |
| Tradier | `tradier_paper.py`, `tradier_stream.py` | Paper trading + streaming quotes |
| IBKR | `ibkr.py`, `ibkr_paper.py` | Client Portal API paper trading |
| Alpaca | `alpaca.py`, `alpaca_paper_execution.py` | Paper trading |
| Tiingo | `tiingo.py` | EOD/intraday price data |

Credentials stored via `credential_store.py`; broker routing via `broker_router.py`.

### Scheduled jobs

| Job | Scheduler | Trigger |
|---|---|---|
| EDGAR nightly prefetch | `edgar_scheduler.py` | Cron; prefetches SP500+NDX100+DOW30 fundamentals |
| S&P 500 liquidity update | `sp500_scheduler.py` | Cron; updates `sp500.csv` via yfinance |
| Strategy tuning | `tuning_scheduler.py` | Cron; runs WFO param optimizer |
| Strategy watch evaluation | `strategy_watch_scheduler.py` | Periodic; evaluates all enabled watches, dispatches notifications |
| Scan | `scan_scheduler.py` | On-demand + scheduled stock scans |
| Ingestion | `ingestion_scheduler.py` | Historical OHLCV ingestion |

### Notifications (`backend/app/services/notifications/`)

Dispatch layer supports Gmail, Telegram, and in-app websocket alerts (`ws_alerts` router).

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

### Theme system
- Store: `lib/theme.ts` — `'dark' | 'light'`, persisted to `localStorage` as `'bamendjou:theme'`
- Applied via `<html data-theme="...">` attribute, set by `ThemeProvider/index.tsx`
- `app/layout.tsx` contains an inline no-flash script that reads localStorage before React hydrates — do not remove it

### @contextRail parallel route
- `app/(frame)/@contextRail/` is a Next.js parallel route slot; its segments mirror the main route tree
- Each segment has a `default.tsx` (shown when no page matches) and optionally a `page.tsx`
- The frame layout receives `{ children, contextRail }` and renders the rail in the right column

### AlternativeContract (FR-28)
- `TradeCardData.alternatives?: AlternativeContract[]` — runner-up contracts attached to each trade card
- Each entry carries all standard contract fields plus `reason: string` (plain-text trade-off explanation)
- Step 6 badge shows the count; Step 7 renders them in a collapsible section via `AlternativeContractRow`

### Domain type helpers
```ts
// lib/status.ts
statusForScore(score: number): Status      // 0–100 → PASS / CAUTION / REJECT
worstStatus(...statuses: Status[]): Status

// types/domain.ts
contractId(symbol, strike, expiry, right): string  // "AAPL|185|2025-05-16|C"
contractLabel(c): string                           // "AAPL 185C 05/16"
```

### Zustand persistence
Some stores use `persist()` with versioned `migrate()` callbacks. When adding a new persisted field, bump the `version` number and add a migration branch — do not rely on Zustand's default merge for breaking shape changes. Storage key prefix: `'bamendjou:'`.

---

## Dev workflow

```bash
cd frontend
npm run dev          # localhost:3001 (3000 often occupied)
npm run typecheck    # must be clean — run before every commit
npm run test         # Jest (all frontend tests)
npm run test -- --testPathPattern=StatusBadge  # single test file
```

Backend tests (from repo root):
```bash
cd backend && pytest                              # all tests
pytest tests/test_alternatives.py                # single module
```

Min-width gate: 1200px (`MinWidthGate.tsx`) — shows a "rotate / resize" message below that.
