# Code Review Findings — Bamendjou

Audit date: 2026-08-13. Scope: `frontend/`, `backend/`, root docs, and cross-checks against
`CLAUDE.md`. Findings are grouped by severity. File:line references are accurate as of this
commit; re-verify before fixing if the branch has moved on.

---

## Critical — financial correctness / risk control

### 1. "Max single position %" setting is never enforced
`backend/app/routers/risk_settings.py:118,142` persists the frontend's `maxSinglePositionPct`
into `risk_rules.yaml`'s `portfolio.max_single_position_pct` key. But the actual sizing gate used
by `auto_trader.py` — `check_position_risk()` in `backend/app/services/portfolio_risk.py:88` —
reads a **different** key, `max_single_trade_exposure_pct`, which has no settings-page UI at all
and is hardcoded at `0.05` in `risk_rules.yaml:4`. A user tightening or loosening the setting in
Settings has zero effect on real trade sizing/exposure enforcement. This is a silent risk-control
failure, not a display bug.

### 2. Closing a stock position shows realized P&L ~100x too large
`frontend/components/organisms/ClosePositionDrawer/index.tsx:34` computes
`realizedDollar = (exitPrice - entryPrice) * 100 * qty` unconditionally, assuming a 100-share
option contract. Every other P&L/exposure calculation in the app branches on
`position.contract.endsWith('|STOCK') ? 1 : 100` (`frontend/app/(frame)/portfolio/page.tsx:119,501`,
`frontend/app/(frame)/@contextRail/portfolio/page.tsx:15`, `frontend/lib/riskStore.ts:67`,
`frontend/lib/risk.ts:30-31`). Since `ClosePositionDrawer` is used for stock positions too
(`contract` = `"SYM|STOCK"`), the confirm dialog shows a wildly wrong number before the user
confirms the close.

### 3. Shorted stock positions are recorded as "Bullish" in the local portfolio
`frontend/lib/paperTrade.ts:29` — `buildPaperStockPosition()` hardcodes `direction: 'Bullish'`
regardless of the actual trade direction, even though the broker order sent from the same call
sites correctly does `action: c.direction === 'Bullish' ? 'BUY' : 'SELL'`
(`frontend/components/organisms/StockSendDialog/index.tsx:101`,
`frontend/components/organisms/StockPositionCard/index.tsx:189`). The mislabeled direction then
feeds `alertEngine.scanPortfolio()`'s direction-aware stop/target comparisons
(`frontend/lib/alertEngine.ts:49-90`) backwards for every short position.

---

## High

### 4. Blocking sync calls inside `async def` route handlers stall the event loop
- `backend/app/routers/contracts.py:80,83` — `get_contracts` (backs Step 6's contracts table)
  calls sync `fetch_option_chain(...)` / `fetch_price(...)` directly, even though the same file
  already imports and uses the async-safe `fetch_price_async`/`fetch_candles_async` elsewhere
  (lines 165, 295, 368). `fetch_option_chain` can invoke `fetch_iv_metrics_ibkr`
  (`backend/app/data/ibkr.py:262-303`), which does a hard blocking `time.sleep(1.5)` —
  explicitly documented at `ibkr.py:301-303` as needing a worker thread, not an async route.
- `backend/app/routers/watchlist.py:62-63` — `get_watchlist` calls sync `fetch_price`/
  `fetch_company_name` in a per-symbol loop.
- `backend/app/routers/regime.py:103,126` — same sync `fetch_price('VIX')` pattern.

Each of these stalls the single uvicorn event loop for the whole process — all concurrent scans,
websockets, and other requests — for up to several seconds per call. This is exactly the failure
mode `tastytrade_bridge.py` was built to avoid elsewhere; these three call sites just don't use
the async-safe path that already exists in `market.py`.

### 5. StepNavBar's REJECT gate reads a different field than CLAUDE.md documents
CLAUDE.md says: "`scanStore.regime` is set by Step 1 on mount and read by StepNavBar for the
REJECT gate." Actual code (`frontend/components/organisms/StepNavBar/index.tsx:25,43`) reads
`scanStore.combinedRegime`, a genuinely different value —  `regime` is the raw market-overall
status, `combinedRegime` is `alignmentVerdict(direction, descriptor)`
(`frontend/app/(frame)/screener/step-1-regime/page.tsx:85,89`). A developer trusting the doc
would edit the wrong field and silently break the REJECT confirmation overlay.

---

## Medium

### 6. Live strategy param falls outside its own WFO search grid
`backend/config/strategy_params.yaml:36` sets `pullback_ema.active.bearish.ema_period: 35`, but
line 42's `search.ema_period: [20, 50]` never includes 35. `walk_forward.py`'s
`_complexity_penalty` does `values.index(combo[key])` — so the walk-forward optimizer that's
supposed to keep this parameter honest can never reproduce or validate the value actually running
in production.

### 7. CLAUDE.md's Settings page section describes a UI that doesn't exist
CLAUDE.md (lines ~238-247) says the sub-nav is "Broker · Appearance · Score weights & parameters
· Alerts" with a 4-tab horizon strip storing `customW`/`customParams`. The actual sub-nav
(`frontend/app/(frame)/settings/page.tsx:28-37`) has nine sections (Appearance, Scan, Strategy
scan, Brokers, Risk, Regime, Notifications, Data, Strategy Tuning) — no "Score weights &
parameters" tab, no "Alerts" tab, and `customW`/`customParams` appear nowhere in `frontend/`.
Reads as a removed or never-shipped feature that was never pulled from the doc.

### 8. Strategy count undercounted in CLAUDE.md
CLAUDE.md says the Strategy picker offers 4 strategies and that `strategy_engine.py` has "Four
named signal functions." The actual picker
(`frontend/app/(frame)/screener/step-5-strategy/page.tsx:17-57`) lists six, and
`backend/app/services/strategy_engine.py` defines nine signal functions total, all wired into
`backend/app/routers/stock_scan.py:42-45,125-127`.

### 9. Zustand persisted storage key prefix is inconsistent
CLAUDE.md claims a single `'bamendjou:'` prefix. About half the stores use a colon
(`bamendjou:theme`, `bamendjou:alerts`, `bamendjou:scan-params`, …) and the other half use a
hyphen (`bamendjou-watchlist-v1`, `bamendjou-settings`, `bamendjou-portfolio-v1`,
`bamendjou-risk-v1`, `bamendjou-auto-trade`, `bamendjou-scan-store`, `bamendjou-alerts-v2`,
`bamendjou-audit-log`). No single convention actually holds today.

### 10. Primitive prop API in CLAUDE.md doesn't match the components
CLAUDE.md documents `Text size={11|12|13|14}`, `Data weight={400|500|600}`, and
`Title as="h1|h2|h3" size={18|20|24}`. Actual types
(`frontend/components/primitives/Text.tsx:13-14`, `Data.tsx:13-14`, `Title.tsx:10-11`) allow
`TextSize = 10|11|12|13|14|16`, `DataWeight = 400|500` only, and
`TitleSize = 20|24|32` with `as: 'h1'|'h2'|'span'|'div'`. `size={16}` is used extensively in real
code, so the doc's scale is stale.

---

## Low / cleanup

### 11. Stale `settingsStore.ts` header comment
`frontend/lib/settingsStore.ts:4` still says the store "Persists broker config,
alertDeduplicationHours, and IV thresholds," but IV thresholds were removed in the v18 migration
(`settingsStore.ts:336-339`) and now live in `ivThresholdsStore.ts`.

### 12. Hardcoded `#fff` bypasses the CSS-token-only rule
Five files hardcode `color: #fff` instead of a token: `NavItems.module.css:60`,
`StepNavBar.module.css:98`, `RunScanButton/index.module.css:128`,
`ConfirmDialog.module.css:56`, `AlertBadge.module.css:12`. Low functional impact but a direct,
repeated rule violation of the CLAUDE.md styling convention.

### 13. Redundant double-POST on options paper-order placement
`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:498,507` POSTs the new position via
`persistPosition(pos)`, then on success also calls `addPosition(pos)`, which independently POSTs
the same position again (`frontend/lib/portfolioStore.ts:311`). The second POST is swallowed as a
harmless 409 today, but it's a wasted request and a maintenance trap if duplicate-handling ever
changes.

### 14. Bare `except Exception: pass` worth a spot-check
Several sites (`backend/app/data/market.py:40-41,156-157,426-427,1054-1055,1113-1114`,
`backend/app/main.py:180-236`) swallow `Exception` broadly — mostly documented as deliberate
non-fatal fallbacks, but broad enough to also hide genuine programming errors (`AttributeError`,
`KeyError`) rather than just the intended I/O failures.

---

## Documentation staleness (root-level docs, not CLAUDE.md)

- **`LLM_CONTEXT.md`** — presents itself as current ("read this file fully before touching any
  code") but claims "There is no backend yet. Everything runs on deterministic mocks" and "the
  project root only contains this file and CLAUDE.md," both long false. Also documents the
  opposite step order (`step-1-universe/step-2-direction/step-3-regime`) from CLAUDE.md's current
  `step-1-regime/step-2-universe/step-3-direction`, and references a `mocks/` folder and
  `frontend/styles/tokens.ts` that no longer exist. Unlike `PRODUCTION_READINESS_AUDIT.md`, which
  self-flags as historical, this one doesn't — an agent could read it instead of CLAUDE.md and be
  actively misled.
- **`docs/design/nextjs-implementation-plan.md`** and **`docs/design/bamendjou-design-spec.md`**
  — same stale step ordering and `/mocks` folder reference, no historical disclaimer.
- **`README.md`** — describes a root `config/` directory and a populated `tests/` scaffold that
  don't match the repo; calls the repo "the initial workspace."
- **`IMPLEMENTATION_PLAN.md`** — "Current state" table claims scoring/pricing/contract
  validation are "Not started," directly contradicted by CLAUDE.md's own pipeline description.

---

## Verified as correct (no action needed)

- All ~20 Zustand stores listed in CLAUDE.md exist with matching fields (`screenerMode`,
  `confidenceGate`, `premiumStopPct`, etc.)
- All screener step folders `step-1-regime` through `step-7-trade-card`/`step-7-position-card`
  exist and match their described contents; `step-4-prebreakout` genuinely has no steps 5-7.
- `tastytrade_bridge.py`'s single-persistent-event-loop design is correct and consistent with
  `governor.py`'s process-wide lock.
- `scoring_rules.yaml` horizon weights all sum to 1.00; event-proximity windows match CLAUDE.md
  exactly (Swing reject <21d / caution <45d); `contract_rules.yaml` weights sum to 1.00;
  `fundamentals_gate` threshold directionality is correct for both bullish and bearish.
- All scheduled-job wiring in `main.py` matches the CLAUDE.md scheduler table.
- `reward_risk.py`, `entry_quality.py`, `walk_forward.py`, `signal_confidence.py`,
  `contract_validator.py` — no defects found.

---

## Suggested next step

Fix items 1-3 first (they affect real money/risk decisions), then 4-5 (correctness/perf), then
sweep the doc staleness in one pass. Happy to implement any subset on request.
