# Production Readiness Audit — Trading Assistant Options Screener

**Date**: 2026-05-05  
**Auditor**: opencode (bmad-review-adversarial-general skill)  
**Standards**: PRD compliance, No mock/fake data, No dead UI  

> **Historical snapshot** — this report reflects the app's state on 2026-05-05
> and is preserved as-is; it is not updated to track later changes. Its
> architecture references (route slugs like `step-3-regime`/`step-1-universe`,
> the mode list) predate the current Stocks/Pre-Breakout modes and the
> Tastytrade integration and no longer match the live app. For the current
> state, see `TRADING_QUALITY_BENCHMARK.md`.

---

## Executive Summary

**Backend**: 13/13 checks pass. All routers return empty arrays, no mock fallbacks, real market data functions wired correctly.

**Frontend**: 9/11 checks pass. API layer and scan workflow are clean. Two UI pages lack empty states. One store seeds hardcoded symbols.

**PRD Compliance**: Core workflow (FR-06 through FR-12) is implemented. CSV upload missing. Some table fields incomplete.

---

## Backend Audit Results

| File | Status | Notes |
|------|--------|-------|
| `backend/app/main.py` | **PASS** | Title: "Trading Assistant API" (L25). All 13 routers registered (L39-52). |
| `backend/app/routers/watchlist.py` | **PASS** | Returns `[]` (L9). No mock data. |
| `backend/app/routers/portfolio.py` | **PASS** | Returns `[]` (L9). No mock data. |
| `backend/app/routers/tradecards.py` | **PASS** | Returns `[]` (L9). No mock data. |
| `backend/app/routers/alerts.py` | **PASS** | Returns `[]` (L9). No mock data. |
| `backend/app/routers/events.py` | **PASS** | Returns `[]` (L9). No mock data. |
| `backend/app/routers/candles.py` | **PASS** | Calls `fetch_candles()` (L10). No mock fallback. |
| `backend/app/routers/contracts.py` | **PASS** | Calls `fetch_option_chain()` (L10). No mock fallback. |
| `backend/app/routers/regime.py` | **PASS** | Uses live VIX via `fetch_price('VIX')` (L19). Falls back to CAUTION, not mock data. |
| `backend/app/routers/sectors.py` | **PASS** | Uses live ETF quotes via `fetch_quotes()` (L34). Returns `[]` if unavailable. |
| `backend/app/routers/scan.py` | **PASS** | Calls real market data: `fetch_candles`, `fetch_price`, `fetch_option_chain`, `fetch_earnings_date`, `fetch_dividend_date` (L62-80). Scores stocks and validates contracts with real logic. |
| `backend/app/fixtures/` | **PASS** | Files exist but only imported by test files (`tests/test_candles.py:3`) and other fixtures — never by production routers. |
| `backend/requirements.txt` | **PASS** | Clean: fastapi, uvicorn, pydantic, pydantic-settings, scipy, pytest, httpx, pyyaml. No asyncpg or sqlalchemy. |

---

## Frontend Audit Results

| File | Status | Notes |
|------|--------|-------|
| `frontend/lib/scanStore.ts` | **PASS** | Initial state: `scanState: 'IDLE'` (L32), `scanAt: null` (L33), `context: null` (L34). No seeded mock state. |
| `frontend/lib/api.ts` | **PASS** | All functions call real backend endpoints via `fetch` (L5-39). No mock fallbacks. |
| `frontend/components/organisms/RunScanButton/index.tsx` | **PASS** | Calls `api.postScan()` (L58). No setTimeout or mock path. |
| `frontend/app/(frame)/screener/step-3-regime/page.tsx` | **PASS** | Candle fetches use `SPY` (L53) and `QQQ` (L54). `RunScanButton` imported (L20) and rendered (L180). |
| `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | **PASS** | Reads from `scanStore.scanResult?.candidates` (L134). No `api.getWatchlist()` usage. |
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | **PASS** | Reads from `scanStore.scanResult?.candidates` (L49). |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | **PASS** | Fetches real option chain via `api.getContracts(selectedSymbol)` (L44). |
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | **PASS** | Reads `scanResult` from store (L80) and uses `candidates` (L84-91). No mock fallback. |
| `frontend/app/(frame)/dashboard/page.tsx` | **PASS** | Shows "No scan yet" when `scanAt` is null (L29-33). Handles offline state. |
| `frontend/app/(frame)/watchlist/page.tsx` | **FAIL** | Stocks tab lacks empty state. When `watchlist` is empty, renders table headers with no rows but no "No items" message (L139-198). |
| `frontend/app/(frame)/portfolio/page.tsx` | **FAIL** | No empty state. When `positions` is empty, renders table headers + footer with zeros but no "No positions" message (L75-133). |

---

## PRD Feature Compliance

| Requirement | Status | Notes |
|-------------|--------|-------|
| **FR-06** 7-step workflow | **PASS** | All 7 steps present and navigable (step-1 through step-7). |
| **FR-07** Universe creation | **PARTIAL** | Presets (SP500, NDX100, etc.) and manual custom entry implemented. **CSV upload missing.** |
| **FR-08** Direction modes | **PASS** | Bullish/Bearish toggle in step-2-direction (L96-108). |
| **FR-09** Analysis horizon | **PASS** | Intraday/Swing/Position/Custom horizon selection in step-2 (L113-153). |
| **FR-10** Market regime | **PASS** | PASS/CAUTION/REJECT banner with live VIX data in step-3 (L78-83). |
| **FR-11** Stock ranking table | **PASS** | Sortable table with score, rank delta, status, breakdown in step-4. |
| **FR-12** Ranked table fields | **PARTIAL** | Has: symbol, direction, score, rank change, score change, status. **Missing:** analysis horizon column, stock confidence index, rule-status changes, reject reasons. |

---

## Prioritized Punch List

### 1. Blockers (app cannot be used without fixing these)

**None.** The backend returns real data from live market data functions. The frontend scan workflow is fully wired. No blockers.

---

### 2. PRD Gaps (features specified but missing or incomplete)

| Priority | Issue | Location | Details |
|----------|-------|----------|---------|
| **High** | CSV upload missing | `frontend/app/(frame)/screener/step-1-universe/page.tsx` | FR-07 requires CSV upload for universe creation. Only presets and manual paste are implemented. No file input or CSV parser. |
| **High** | Missing table fields | `frontend/app/(frame)/screener/step-4-ranking/page.tsx` | FR-12 requires: analysis horizon column, stock confidence index, rule-status changes vs previous run, reject/caution reasons. Current table only shows symbol, rank delta, score delta, score, next event. |
| **Medium** | Settings Save button dead | `frontend/app/(frame)/settings/page.tsx:66` | Save button has no `onClick` handler. Weights and broker settings are not persisted. |
| **Medium** | Settings not persisted | `frontend/lib/settingsStore.ts` | Custom weights and parameters exist in store but Save button doesn't trigger persistence to backend/localStorage. |
| **Low** | Contract type hardcoded to CALL | `backend/app/routers/scan.py:71`, `backend/app/routers/contracts.py:10` | MVP scoped to long-calls-only per PRD, so this is acceptable for now. Bearish path documented as post-MVP. |

---

### 3. Mock Data Remnants (hardcoded data in live code paths)

| Priority | Issue | Location | Details |
|----------|-------|----------|---------|
| **Medium** | Watchlist seeded with hardcoded symbols | `frontend/lib/watchlistStore.ts:14-27` | `SEED_SYMBOLS = ['AAPL', 'NVDA', 'MSFT', ...]` (10 symbols) pre-populates every new user's watchlist. Per PRD: "Portfolio and watchlist are empty until user adds real data." |
| **Low** | Portfolio store comment references mock | `frontend/lib/portfolioStore.ts:4-5` | Comment says "Seeded from MOCK_PORTFOLIO" but code actually initializes `positions: []` — the comment is stale, not the code. |
| **Low** | Watched contracts comment references mock | `frontend/lib/watchedContractsStore.ts:6-7` | Comment references "MOCK_CONTRACT_INDEX" but store initializes `ids: []` — comment only. |

---

### 4. Dead UI (buttons/links not wired to real logic)

| Priority | Issue | Location | Details |
|----------|-------|----------|---------|
| **Medium** | Watchlist stocks tab empty state | `frontend/app/(frame)/watchlist/page.tsx:139-198` | When `watchlist.length === 0`, renders table headers with zero rows but no "No candidates" message. Contracts tab has empty state (L222-230) — stocks tab needs equivalent. |
| **Medium** | Portfolio empty state | `frontend/app/(frame)/portfolio/page.tsx:75-133` | When `positions.length === 0`, renders table headers + sticky footer with `$0` values but no "No open positions" message. |
| **Medium** | Settings Save button | `frontend/app/(frame)/settings/page.tsx:66` | `<button>Save changes</button>` has no `onClick` handler. Clicking it does nothing. |
| **Low** | Broker form not persisted | `frontend/app/(frame)/settings/page.tsx:110-142` | Broker, account, API token, paper toggle are local `useState` only — not connected to any store or API. |

---

## Summary

The app is **functionally sound** for production use with the scan workflow as the primary path. The backend is clean — all routers return empty arrays until real data flows through the scan endpoint, which correctly calls live market data functions. The frontend scan store starts from a clean IDLE state and all screener steps read from scan results.

**Three fixes recommended before calling it production-ready:**

1. **Remove hardcoded watchlist seeds** (`frontend/lib/watchlistStore.ts:14`) — change `SEED_SYMBOLS` to `[]` or remove the seed entirely.
2. **Add empty states** to Watchlist stocks tab and Portfolio page.
3. **Wire the Settings Save button** to persist weights and broker config (even if just to localStorage for now).
