# Single-Stock Analysis Page — Design Spec

**Date:** 2026-06-29
**Status:** Approved for planning

## Problem

Today a stock can only be analysed if it passes the scanner's gates (universe membership, price filters, score/direction/backtest/regime/confidence gates). A stock that fails any gate returns `{symbol, reason}` and shows nothing. The user wants to analyse **any** ticker or index on demand — outside a scan — and see its regime (OMM/HMM), market sentiment, fundamentals, sector context, and full score breakdown, even when it would not pass the scanner.

## Goals

- New top-level **Analysis** page, reachable from the NavRail.
- Search bar accepts **any stock or index/ETF**, not limited to the scan universe.
- Reuse the Stock Ranking layout wholesale (chart + table + per-component score cards), adapted to a single symbol.
- Top section borrows from the Market Regime page but **tailored to the analysed symbol**.
- Gates are **bypassed** (any valid symbol returns a full result) but the analysis still **honors the screener's selected horizon / direction / strategy / params**.
- Gate failures surface as **advisory flags**, not blockers.

## Non-Goals

- No change to the existing scan flow or Stock Ranking page.
- No new trading/execution actions on this page (analysis only).
- No persistence of analysis results across reloads.

## Approach

Reuse `_process_stock()` in `backend/app/routers/stock_scan.py`, which already computes score, OMM + directional HMM regime signal, fundamentals, sentiment/conviction, and sector RS for a single symbol. Refactor its gate early-returns so that, under a new `bypass_gates=True` mode, each gate records an advisory flag and continues instead of returning. This avoids duplicating ~250 lines of orchestration that would otherwise drift out of sync.

## Backend

### New endpoint
`POST /api/analyze-stock`

Request: `{ symbol: str, horizon, direction, strategy, ...strategy/param overrides }` — same param shape the scan request already accepts (single symbol).

Response: `StockAnalysisOut`:
- All existing `PositionCardOut` fields: score, status, backtest, strategy signal, fundamentals, sentiment, sector_rs_pct, confidence, next_event.
- `gate_flags: list[{ gate: str, status: 'PASS'|'CAUTION'|'REJECT', detail: str }]` — which gates it passed / would have failed (score, direction_conviction, backtest, regime_headwind, confidence). Advisory only.
- `ema_trend: { state: 'Above'|'Below', slope: float, status }` — stock's own 200-EMA trend.
- `iv_rank: float | None` — stock's own IV rank (None / N/A for indices and symbols without options data).
- `regime_by_horizon: { intraday, swing, position }` — each an OMM+HMM block (state, p_stay, stability, regime_age_days, avg_regime_duration, conviction_pct, conviction_label, hmm_state, alignment, transition odds) computed on the **stock's own** price series for that horizon. Reuses `compute_omm` + `compute_directional_hmm` per horizon timeframe.
- `sector: { name, etf, change_pct }` — the single sector the stock belongs to.
- `sector_rs: { d1, w1, m1 }` — stock return minus sector return over 1-day / 1-week / 1-month windows (relative strength strip).
- `market_backdrop: { overall, direction, vix }` — macro chip from the existing market-regime computation (reuse the regime service / cached result).
- `is_index: bool` — true for indices/ETFs; drives N/A panels (fundamentals, IV rank, backtest may be N/A).

### Refactor
`_process_stock(...)` gains a `bypass_gates: bool = False` param. Each early-return gate (`price<min`, `price>max`, `REJECT score`, `direction_conviction`, `regime headwind`, `backtest gate`, `confidence REJECT`) becomes:
- if `bypass_gates`: append to a `gate_flags` accumulator and continue.
- else: existing early-return behaviour (scan path unchanged).

For indices/ETFs (`is_index`): skip fundamentals fetch and IV rank (return None), and tolerate backtest/strategy-signal absence (N/A rather than reject).

Honors screener params: the endpoint reads horizon/direction/strategy/params from the request body, which the frontend populates from `scanStore` + `scanParamsStore`.

## Frontend

### Nav
New **Analysis** item in the NavRail (top-level, alongside Screener / Watchlist / Portfolio).

### Page
`frontend/app/(frame)/analysis/page.tsx` + `page.module.css`, cloned from the Stock Ranking layout. Reuses the existing interactive candlestick/MACD chart component, the per-component score-breakdown cards, and the table row styling.

### Store
`lib/analysisStore.ts` (Zustand, **not** persisted): `{ symbol, result, loading, error, analyze(symbol) }`. `analyze()` reads horizon/direction/strategy/params from `scanStore` + `scanParamsStore`, calls `api.analyzeStock(...)`, sets result.

### Layout (top → bottom)
1. **Search bar** — any ticker/index; Enter triggers analyze. Not-found → inline error.
2. **Header strip** — symbol · company · price · Stock Regime badge (PASS/CAUTION + Bullish/Bearish) · market-backdrop chip (macro PASS/CAUTION + VIX).
3. **Regime context row** (tailored to the symbol):
   - **EMA / IV card** — stock's own 200-EMA trend + stock's own IV rank (N/A for index).
   - **Regime by Horizon** — Intraday / Swing / Position cards on the stock's own series (OMM state, HMM state, p_stay, transition odds).
   - **Market sentiment** — stock's own OMM conviction (tailwind/headwind) + macro backdrop.
   - **Fundamental Health** — Growth / Quality / Risk (from the trade card); N/A for index.
   - **Sector tile** — the stock's own sector + change %, plus a **1D / 1W / 1M relative-strength strip**.
4. **Chart + table region** (cloned ranking layout) — single-row table for the symbol (score, win%, trades, return, max DD, health, gate badges shown but **not** filtering/sorting away) + interactive chart on the right + per-component score breakdown cards below.
5. **News** — stock-specific headlines block, with general market news below.

### Table behaviour
Gate badges are **informational only**. The row always renders, even when score/backtest/regime gates would normally reject the symbol. This is the core feature.

## Data flow
1. User types ticker → `analysisStore.analyze(symbol)` reads horizon/direction/strategy/params from `scanStore`/`scanParamsStore`, POSTs `/api/analyze-stock`.
2. Backend runs `_process_stock(..., bypass_gates=True)`, plus all-three-horizon regime, EMA trend, IV rank, sector tile + 1D/1W/1M RS, and the cached market backdrop.
3. Response populates `analysisStore.result`; page renders.
4. After the analysis resolves, the page fetches stock-specific news + general market news in parallel via existing `lib/api.ts` helpers.

## Error handling
- Unknown/invalid ticker → 404 → inline "No data for SYMBOL."
- Index/ETF → fundamentals, IV rank, and backtest panels render explicit **N/A** (`is_index=true`), not an error.
- Insufficient history (<60 bars) → partial result: regime/EMA render; backtest panel shows "insufficient history."
- Backend down → existing "is the backend running?" message.

## Testing
- Backend: new `backend/tests/test_analyze_stock.py` — (a) a gated stock still returns a full card; (b) `gate_flags` populated correctly; (c) index returns `is_index=True` with N/A fundamentals/IV.
- Frontend: `npm run typecheck` clean; Jest test for `analysisStore` (mocked api) and N/A-panel rendering.

## Open risks
- IV rank source for arbitrary symbols may be unavailable → degrade gracefully to N/A.
- Market backdrop reuse must not trigger a second heavy regime computation per request — prefer the cached regime result.
