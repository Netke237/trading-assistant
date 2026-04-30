# Bamendjou — Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Bamendjou options screener from its current fixture-data state to a fully working scan engine — real market data, real scoring, real pricing, real trade cards — by dispatching parallel LLM workstreams in four waves.

**Architecture:** Each wave is a set of workstreams with zero shared file ownership that can run simultaneously in separate git worktrees. A context doc per workstream tells the assigned LLM exactly what to create and what to leave alone. Quality is protected by owned-files isolation, inline type contracts, and `npm run typecheck` on every frontend commit.

**Tech Stack:** Next.js 15 / TypeScript 5.7 / CSS Modules / Zustand v5 / FastAPI 0.104 / Pydantic v2 / Python 3.11 / yfinance / scipy

---

## Current state (2026-04-30)

| Layer | Status |
|---|---|
| Frontend UI — all 7 screener steps, dashboard, watchlist, portfolio, calendar, settings | **Done** |
| FastAPI skeleton — 9 fixture endpoints, CORS, health | **Done** |
| api.ts client — all pages wired to `fetch()` calls | **Done** |
| Step 1 state lifted to Zustand (WS-11) | **Context doc written, not yet implemented** |
| Step 2 state lifted to scanStore (WS-12) | **Context doc written, not yet implemented** |
| Market data, scoring, pricing, contract validation | **Not started** |

Context docs that already exist:

| # | File | Workstream |
|---|---|---|
| 01 | `llm-contexts/01-backend-fastapi.md` | Fixture backend (historical — done) |
| 02–10 | `llm-contexts/02-…-10-…` | Frontend scaffold (historical — done) |
| 11 | `llm-contexts/11-step1-universe-wiring.md` | **WS-11** — ready to dispatch |
| 12 | `llm-contexts/12-step2-direction-wiring.md` | **WS-12** — ready to dispatch |

---

## Workstream registry

| WS | Name | Wave | Conflict class | Key owned files | Depends on |
|---|---|---|---|---|---|
| WS-11 | Step 1 universe store | 1 | Zero | `frontend/lib/universeStore.ts`, `step-1-universe/page.tsx` | — |
| WS-12 | Step 2 direction wiring | 1 | Zero | `step-2-direction/page.tsx` | — |
| WS-13 | Market data client | 1 | Zero | `backend/app/data/market.py` | — |
| WS-14 | Black-Scholes module | 1 | Zero | `backend/app/models/black_scholes.py` | — |
| WS-15 | Excel export | 1 | Zero | `frontend/lib/export.ts`, step-4 page | — |
| WS-16 | Responsive audit | 1 | Zero | CSS modules only (no shared files) | — |
| WS-17 | Alerts WebSocket skeleton | 1 | Zero | `backend/app/routers/ws_alerts.py`, `alert_service.py` | — |
| WS-18 | Audit trail + rec IDs | 1 | Zero | `backend/app/services/audit.py` | — |
| WS-19 | Test infrastructure | 1 | Zero | `backend/tests/`, `frontend/jest.config.ts` | — |
| WS-20 | Stock scoring engine | 2 | Zero | `backend/app/scoring/stock_scorer.py` | WS-13 + **SCORING_RULES.md** |
| WS-21 | Heston pricing model | 2 | Zero | `backend/app/models/heston.py` | WS-14 |
| WS-22 | Contract validation engine | 2 | Zero | `backend/app/scoring/contract_validator.py` | WS-13 |
| WS-23 | Portfolio risk controls | 2 | Zero | `backend/app/services/portfolio_risk.py` | WS-13 |
| WS-24 | Entry quality + reward-risk | 3 | Zero | `backend/app/scoring/entry_quality.py`, `reward_risk.py` | WS-21 + WS-22 |
| WS-25 | Full /api/scan endpoint | 3 | Zero | `backend/app/routers/scan.py` | WS-20 + WS-22 + WS-24 |
| WS-26 | Trade card completeness | 3 | Zero | `frontend/app/(frame)/screener/step-7-trade-card/` | WS-24 shapes |
| WS-27 | RunScanButton → real scan | 4 | Zero | `frontend/lib/scanStore.ts`, RunScanButton | WS-25 |
| WS-28 | Alert triggers post-scan | 4 | Zero | `backend/app/services/alert_triggers.py` | WS-25 + WS-17 |
| WS-29 | Integration test suite | 4 | Zero | `backend/tests/integration/` | WS-25 |

---

## WS-20 proposition — the critical decision

**WS-20 is the dependency bottleneck for all of Waves 2, 3, and 4.** It cannot be written as a context doc until the financial rules are specified in concrete numeric terms.

The PRD (FR-11, FR-29) names the rule families — trend rule, pullback rule, reversal trigger, event context, volatility context — but does not define their thresholds. An LLM implementing WS-20 without those numbers will invent them, and you will have a scorer that does not match your trading logic.

### Proposed resolution: one rules definition session

Before launching Wave 2, run a single focused session (~45 minutes) with this goal:

> "Produce `SCORING_RULES.md` — a concrete spec of every numeric threshold, weight, and decision boundary the stock scorer needs."

**Questions that session must answer:**

| Rule | Question |
|---|---|
| Trend | Which MA defines the trend? (e.g., 200 EMA?) What counts as "above"? Is slope required? |
| Pullback | How deep is a valid pullback — % from swing high? ATR multiples? |
| Reversal trigger | Candle pattern (e.g., hammer, engulfing)? Momentum crossover? Volume confirmation? |
| Event context | How many days before earnings triggers CAUTION? REJECT? |
| Volatility context | What IV rank range is acceptable for long-call buying? |
| Weights | What % does each component contribute to the stock score (0–100)? |
| Thresholds | PASS = score ≥ X? CAUTION = score ≥ Y? REJECT = score < Y? |

**Output:** `SCORING_RULES.md` at project root — a table-driven spec of every boundary value.

**Then:** The WS-20 context doc can be written in ~15 minutes referencing `SCORING_RULES.md`, and WS-20 can be dispatched like any other workstream.

**Alternative if you want to unblock Wave 2 immediately:** Write WS-20 with placeholder thresholds externalised to `backend/config/scoring_rules.yaml`. The scorer logic is correct; the numbers are tunable via config without touching code. This lets Wave 2 run now, but you must tune the YAML before the scan produces meaningful results. I do not recommend this path — fixing wrong thresholds after the fact is harder than agreeing on them first.

**Recommendation: do the rules session first.** It takes less time than debugging bad output later.

---

## Worktree playbook

Every workstream runs in an isolated git worktree. No two workstreams touch the same file. This means all Wave 1 workstreams can run simultaneously without merge conflicts.

### One-time setup

```bash
# 1. Verify .worktrees is gitignored (run from project root)
git check-ignore -q .worktrees && echo "already ignored" || (echo ".worktrees/" >> .gitignore && git add .gitignore && git commit -m "chore: ignore worktrees directory")

# 2. Confirm baseline typecheck is clean
cd frontend && npm run typecheck && cd ..
```

### Launch a workstream (template)

```bash
# Replace XX and short-name with the workstream number and slug
git worktree add .worktrees/ws-XX -b feature/ws-XX-short-name

# If frontend work:
cd .worktrees/ws-XX/frontend && npm install && cd ../../..

# Dispatch to LLM:
# "Read llm-contexts/XX-workstream-name.md fully before writing any code.
#  That file is your single source of truth.
#  After every file change, run npm run typecheck (frontend) or python -c 'from app.main import app' (backend).
#  Commit only owned files when done."
```

### Merge a completed workstream

```bash
# After workstream passes typecheck and acceptance criteria:
git -C .worktrees/ws-XX add <owned-files>
git -C .worktrees/ws-XX commit -m "feat(ws-XX): short description"

# Create PR targeting feature/1-api-integration, or merge directly:
git merge feature/ws-XX-short-name --no-ff -m "merge: ws-XX short-name"
git worktree remove .worktrees/ws-XX
git branch -d feature/ws-XX-short-name
```

---

## Phase 0 — Baseline

- [ ] **Step 1: Commit existing context docs**

  ```bash
  git add llm-contexts/11-step1-universe-wiring.md llm-contexts/12-step2-direction-wiring.md
  git commit -m "docs: add WS-11 and WS-12 context docs"
  ```

- [ ] **Step 2: Add .worktrees to .gitignore and commit**

  ```bash
  git check-ignore -q .worktrees || echo ".worktrees/" >> .gitignore
  git add .gitignore && git commit -m "chore: ignore .worktrees directory"
  ```

- [ ] **Step 3: Verify clean baseline**

  ```bash
  cd frontend && npm run typecheck
  # Expected: 0 errors
  cd ../backend && python -c "from app.main import app; print('OK')"
  # Expected: OK
  ```

---

## Phase 1 — Write missing Wave 1 context docs

Seven context docs need writing before Wave 1 can launch in full. WS-11 and WS-12 are ready. These seven follow the same format as `llm-contexts/11-step1-universe-wiring.md`.

- [ ] **Step 4: Write `llm-contexts/13-market-data-client.md`**

  **Scope:** Create `backend/app/data/market.py` with three functions:
  - `fetch_candles(symbol: str, bars: int = 120) -> list[dict]` — calls `yfinance.Ticker(symbol).history(period="6mo")`, returns dicts matching the `Candle` schema
  - `fetch_price(symbol: str) -> float` — current close price
  - `fetch_option_chain(symbol: str, expiry: str | None = None) -> list[dict]` — returns call chain as list of dicts matching `OptionContract` schema fields
  
  Add `yfinance` to `backend/requirements.txt`.
  Does not touch `frontend/`.

- [ ] **Step 5: Write `llm-contexts/14-black-scholes.md`**

  **Scope:** Create `backend/app/models/black_scholes.py` with pure-math functions:
  - `bs_price(S, K, T, r, sigma, is_call) -> float` (standard BS formula)
  - `bs_delta(S, K, T, r, sigma, is_call) -> float`
  - `bs_theta(S, K, T, r, sigma, is_call) -> float` (per calendar day)
  - `bs_iv(price, S, K, T, r, is_call, tol=1e-6) -> float | None` (Newton-Raphson; return None if non-convergent)
  
  Uses `scipy.stats.norm`. Add `scipy` to `backend/requirements.txt`.
  No data access. No frontend changes.

- [ ] **Step 6: Write `llm-contexts/15-excel-export.md`**

  **Scope:** Add Excel download to Step 4 ranking table.
  - Create `frontend/lib/export.ts` — `exportToXlsx(rows: WatchlistRow[], filename: string): void`
  - Uses `xlsx` npm package (`npm install xlsx`)
  - Columns: Rank, Symbol, Company, Direction, Score, Score Δ, Rank Δ, Status, Trend, Pullback, Trigger, Event, Vol, Next Event
  - Add an "Export .xlsx" button to `step-4-ranking/page.tsx` that calls `exportToXlsx`
  
  No backend changes.

- [ ] **Step 7: Write `llm-contexts/16-responsive-audit.md`**

  **Scope:** CSS-only fixes across all pages. Audit at 1200px, 1440px, 1920px.
  Known issues to check: TopBar overflow at narrow widths, step body horizontal scroll, ContextRail clipping, table column wrapping in Step 6.
  No new components. No store changes. No backend changes.

- [ ] **Step 8: Write `llm-contexts/17-alerts-websocket.md`**

  **Scope:** Create WebSocket endpoint for live alerts.
  - Create `backend/app/routers/ws_alerts.py` — `WebSocket /ws/alerts`
  - On connect: immediately broadcasts all 5 `MOCK_ALERTS` from the fixture as a JSON array
  - Create `backend/app/services/alert_service.py` — holds connected clients set, `broadcast(alert)` method
  - Wire into `main.py`
  - No frontend changes yet (alerts hook-up is WS-28)
  
  Uses FastAPI's native WebSocket support (already in fastapi 0.104).

- [ ] **Step 9: Write `llm-contexts/18-audit-trail.md`**

  **Scope:** Create structured audit logging for recommendations.
  - Create `backend/app/services/audit.py`
  - `new_rec_id() -> str` — returns `f"REC-{datetime.utcnow().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"`
  - `log_event(event_type: str, rec_id: str, payload: dict) -> None` — appends JSON line to `backend/audit.log`
  - Event types: `scan_started`, `candidate_accepted`, `candidate_rejected`, `trade_card_created`, `approval`
  - No frontend changes. No route changes yet.

- [ ] **Step 10: Write `llm-contexts/19-test-infrastructure.md`**

  **Scope:** Set up baseline test suites for backend and frontend.
  
  Backend (`pytest`):
  - `backend/tests/__init__.py` (empty)
  - `backend/tests/conftest.py` — FastAPI `TestClient` fixture
  - `backend/tests/test_routes.py` — one test per route: GET 200, correct first-item shape, correct array length
  - `backend/tests/test_candles.py` — verify Mulberry32 RNG is deterministic: same seed produces same first bar twice
  
  Frontend (`jest`):
  - If `jest` not configured: add `jest.config.ts`, `@testing-library/react`
  - `frontend/__tests__/status.test.ts` — `statusForScore` returns PASS for score ≥ 75, CAUTION for 50–74, REJECT for < 50
  - `frontend/__tests__/export.test.ts` — `exportToXlsx` called with 10 rows does not throw (mock DOM)

---

## Phase 2 — Launch Wave 1 (all 9 in parallel)

After Phase 1 is complete, all 9 Wave 1 workstreams can run simultaneously.

- [ ] **Step 11: Launch WS-11** (Step 1 universe store)

  ```bash
  git worktree add .worktrees/ws-11 -b feature/ws-11-universe-store
  # Dispatch: "Read llm-contexts/11-step1-universe-wiring.md fully before writing any code."
  ```

- [ ] **Step 12: Launch WS-12** (Step 2 direction wiring)

  ```bash
  git worktree add .worktrees/ws-12 -b feature/ws-12-direction-wiring
  # Dispatch: "Read llm-contexts/12-step2-direction-wiring.md fully before writing any code."
  ```

- [ ] **Step 13: Launch WS-13** (market data client)

  ```bash
  git worktree add .worktrees/ws-13 -b feature/ws-13-market-data
  # Dispatch: "Read llm-contexts/13-market-data-client.md fully before writing any code."
  ```

- [ ] **Step 14: Launch WS-14** (Black-Scholes)

  ```bash
  git worktree add .worktrees/ws-14 -b feature/ws-14-black-scholes
  # Dispatch: "Read llm-contexts/14-black-scholes.md fully before writing any code."
  ```

- [ ] **Step 15: Launch WS-15** (Excel export)

  ```bash
  git worktree add .worktrees/ws-15 -b feature/ws-15-excel-export
  # Dispatch: "Read llm-contexts/15-excel-export.md fully before writing any code."
  ```

- [ ] **Step 16: Launch WS-16** (responsive audit)

  ```bash
  git worktree add .worktrees/ws-16 -b feature/ws-16-responsive-audit
  # Dispatch: "Read llm-contexts/16-responsive-audit.md fully before writing any code."
  ```

- [ ] **Step 17: Launch WS-17** (alerts WebSocket)

  ```bash
  git worktree add .worktrees/ws-17 -b feature/ws-17-alerts-ws
  # Dispatch: "Read llm-contexts/17-alerts-websocket.md fully before writing any code."
  ```

- [ ] **Step 18: Launch WS-18** (audit trail)

  ```bash
  git worktree add .worktrees/ws-18 -b feature/ws-18-audit-trail
  # Dispatch: "Read llm-contexts/18-audit-trail.md fully before writing any code."
  ```

- [ ] **Step 19: Launch WS-19** (test infrastructure)

  ```bash
  git worktree add .worktrees/ws-19 -b feature/ws-19-test-infra
  # Dispatch: "Read llm-contexts/19-test-infrastructure.md fully before writing any code."
  ```

- [ ] **Step 20: Merge all Wave 1 workstreams into `feature/1-api-integration`**

  For each completed workstream: verify typecheck (frontend) or import-OK (backend), then merge.
  ```bash
  # Example for WS-11:
  cd frontend && npm run typecheck  # must be clean
  git merge feature/ws-11-universe-store --no-ff -m "merge: ws-11 universe store"
  git worktree remove .worktrees/ws-11
  ```

---

## Phase 3 — WS-20 rules definition session

**Do this while Wave 1 is running or immediately after Wave 1 merges.**

- [ ] **Step 21: Run rules definition session — produce `SCORING_RULES.md`**

  Open a fresh conversation with this prompt:

  > "I need to define the concrete numeric rules for a stock scoring engine (Python) that powers an options screener. It needs values for: trend rule (which MA, what slope threshold, PASS/CAUTION/REJECT boundaries), pullback rule (depth as % or ATR, time window), reversal trigger rule (candle pattern or momentum signal, confirmation criteria), event context rule (days before earnings → CAUTION vs REJECT), volatility context rule (IV rank range for long-call buying), score component weights (trend/pullback/trigger/event/vol must sum to 100), and score-to-status thresholds. Ask me one question at a time. Output: SCORING_RULES.md with a table per rule family."

  Save the output as `SCORING_RULES.md` at the project root.

- [ ] **Step 22: Write `llm-contexts/20-stock-scoring-engine.md`**

  After `SCORING_RULES.md` exists:
  
  **Scope:** Create `backend/app/scoring/stock_scorer.py`.
  - `score_stock(symbol: str, direction: str, horizon: str, market_data: MarketData) -> StockScoreCard`
  - Implements trend rule, pullback rule, reversal trigger, event context, volatility context from `SCORING_RULES.md`
  - Returns a `StockScoreCard` with `score: int`, `status: Status`, `breakdown: ScoreBreakdown`, `rules: list[RuleResult]`
  - All thresholds loaded from `backend/config/scoring_rules.yaml` (not hardcoded) — values seeded from `SCORING_RULES.md`
  - Depends on WS-13 market data functions (`from app.data.market import fetch_candles, fetch_price`)

---

## Phase 4 — Write Wave 2 context docs and launch

All four Wave 2 workstreams can run in parallel once their prerequisites are met.

- [ ] **Step 23: Write `llm-contexts/21-heston-model.md`**

  **Scope:** Create `backend/app/models/heston.py`.
  - `heston_price(S, K, T, r, v0, kappa, theta, sigma_v, rho, is_call) -> float` — full Heston closed-form solution
  - `heston_iv(market_price, S, K, T, r, v0, kappa, theta, sigma_v, rho, is_call) -> float | None`
  - `calibrate_heston(option_chain: list[dict], S: float, r: float) -> HestonParams` — simple grid calibration over `(v0, kappa, theta, sigma_v, rho)`
  - Depends on WS-14's Black-Scholes functions for fallback and IV seed.
  - Uses `scipy.integrate.quad` for Heston integration if closed-form becomes numerically unstable.

- [ ] **Step 24: Write `llm-contexts/22-contract-validation.md`**

  **Scope:** Create `backend/app/scoring/contract_validator.py`.
  - `validate_contract(contract: OptionContract, stock_score: int, config: ContractConfig) -> ContractScoreCard`
  - Implements all hard-reject rules (FR-24) and soft-rank rules (FR-25) from the PRD
  - Returns `ContractScoreCard` with `score: int`, `status: Status`, `breakdown: ContractScoreBreakdown`, `rejectReasons: list[str]`
  - All thresholds configurable from `backend/config/contract_rules.yaml`
  - Depends on WS-13 option chain data.

- [ ] **Step 25: Write `llm-contexts/23-portfolio-risk.md`**

  **Scope:** Create `backend/app/services/portfolio_risk.py`.
  - `check_position_risk(symbol: str, contract: str, portfolio: list[PortfolioPosition], config: RiskConfig) -> RiskCheckResult`
  - Enforces: max exposure per trade (% of portfolio), max total exposure, max concurrent positions, max daily recommendations
  - Checks correlation: rejects if two positions in the same symbol are already open
  - Returns `RiskCheckResult` with `approved: bool`, `reasons: list[str]`, `adjusted_size: int | None`
  - All limits from `backend/config/risk_rules.yaml`
  - Depends on WS-13 for current prices (for position sizing calculations).

- [ ] **Step 26: Launch WS-20, WS-21, WS-22, WS-23 in parallel**

  ```bash
  git worktree add .worktrees/ws-20 -b feature/ws-20-stock-scorer
  git worktree add .worktrees/ws-21 -b feature/ws-21-heston
  git worktree add .worktrees/ws-22 -b feature/ws-22-contract-validator
  git worktree add .worktrees/ws-23 -b feature/ws-23-portfolio-risk
  ```

- [ ] **Step 27: Merge all Wave 2 workstreams**

  For each: verify `python -m pytest backend/tests/ -q` passes, then merge.

---

## Phase 5 — Wave 3

- [ ] **Step 28: Write `llm-contexts/24-entry-quality.md`**

  **Scope:** Create `backend/app/scoring/entry_quality.py` and `backend/app/scoring/reward_risk.py`.
  
  `entry_quality.py`:
  - `assess_entry(contract: OptionContract, config: EntryConfig) -> EntryAssessment`
  - Returns `limit_price: float`, `max_fill: float`, `order_type: OrderType`, `quality_status: Status`, `quality_reasons: list[str]`
  - Default fill: mid-price. Max fill: mid + configured spread tolerance.
  
  `reward_risk.py`:
  - `estimate_rr(stock_price, target_price, invalidation_price, contract: OptionContract, heston_params: HestonParams | None, dte_at_target: int) -> RrResult`
  - Returns `rr_ratio: float`, `model_used: RrModel`, `estimated_exit_premium: float`
  - Falls back to delta approximation if Heston params are None; labels result accordingly.
  
  Depends on WS-21 (Heston) and WS-22 (ContractScoreCard shapes).

- [ ] **Step 29: Write `llm-contexts/25-scan-endpoint.md`**

  **Scope:** Create `backend/app/routers/scan.py` — `POST /api/scan`.
  
  Request body:
  ```json
  {
    "universe": ["AAPL", "NVDA", "MSFT"],
    "direction": "Bullish",
    "horizon": "Swing",
    "overrides": {}
  }
  ```
  
  Response: `ScanResult` with `candidates: list[TradeCardData]`, `rejected: list[RejectedCandidate]`, `scan_id: str`, `timestamp: str`
  
  Pipeline: fetch prices → score stocks → rank → filter → validate contracts → assess entry quality → compute reward-risk → generate trade cards → log to audit trail
  
  Depends on WS-20, WS-22, WS-24.

- [ ] **Step 30: Write `llm-contexts/26-trade-card-completeness.md`**

  **Scope:** Frontend only — extend Step 7 trade card to display all fields from the real `TradeCardData` shape.
  - Add invalidation level, premium stop, time stop to the exit plan section
  - Add reward-risk ratio with model label (Heston repriced / Delta approximation)
  - Add entry: limit, max fill, order type
  - Show confidence label as colored badge
  - No new components beyond Text/Data/StatusBadge (already exist)
  
  Depends on WS-24 finalising the TradeCardData shape (check `backend/app/schemas/__init__.py` after WS-24 merges).

- [ ] **Step 31: Launch WS-24, WS-25, WS-26 in parallel**

  ```bash
  git worktree add .worktrees/ws-24 -b feature/ws-24-entry-quality
  git worktree add .worktrees/ws-25 -b feature/ws-25-scan-endpoint
  git worktree add .worktrees/ws-26 -b feature/ws-26-trade-card
  ```

  Note: WS-26 can start as soon as WS-24 schemas are finalised and the context doc is updated. It does not need WS-25 to be running.

- [ ] **Step 32: Merge all Wave 3 workstreams**

---

## Phase 6 — Wave 4 (final wiring)

- [ ] **Step 33: Write `llm-contexts/27-run-scan-button.md`**

  **Scope:** Wire the RunScanButton in the frontend to call `POST /api/scan`.
  - Modify `frontend/lib/scanStore.ts`: add `scanState: ScanState`, `setScanState()`, `scanResult: ScanResult | null`, `setScanResult()`
  - Modify the RunScanButton organism to call `api.scan({ universe, direction, horizon })` and update the store
  - Show scan state in TopBar: Idle → Scanning → Completed / Failed
  - On completion, redirect to Step 4 with results loaded
  
  Depends on WS-25.

- [ ] **Step 34: Write `llm-contexts/28-alert-triggers.md`**

  **Scope:** Create `backend/app/services/alert_triggers.py`.
  - `evaluate_scan_alerts(scan_result: ScanResult, portfolio: list[PortfolioPosition]) -> list[AlertItem]`
  - Generates alerts: `new_candidate_ready`, `contract_reject_reason`, `trade_card_ready`, `invalidation_approaching`, `event_risk_warning`
  - Calls `alert_service.broadcast(alert)` for each generated alert (WS-17)
  - Deduplication: suppress if same symbol + same alert kind appeared within configured window
  - Invoked from the scan endpoint after pipeline completes (modify WS-25's router)
  
  Depends on WS-25 + WS-17.

- [ ] **Step 35: Write `llm-contexts/29-integration-tests.md`**

  **Scope:** End-to-end tests for the full scan pipeline.
  - `backend/tests/integration/test_scan_pipeline.py`
  - Test 1: `POST /api/scan` with `["AAPL", "NVDA", "MSFT"]`, direction=Bullish, horizon=Swing → HTTP 200, at least 1 candidate
  - Test 2: Same input twice → identical candidate list (reproducibility)
  - Test 3: `POST /api/scan` with empty universe → HTTP 200, `candidates: []`, no error
  - Test 4: Portfolio risk check — adding a position that exceeds `max_exposure_pct` returns `approved: false`
  - Uses `pytest-asyncio` for async route testing
  
  Depends on WS-25.

- [ ] **Step 36: Launch WS-27, WS-28, WS-29 in parallel**

  ```bash
  git worktree add .worktrees/ws-27 -b feature/ws-27-run-scan-button
  git worktree add .worktrees/ws-28 -b feature/ws-28-alert-triggers
  git worktree add .worktrees/ws-29 -b feature/ws-29-integration-tests
  ```

- [ ] **Step 37: Merge all Wave 4 workstreams**

---

## Phase 7 — Final integration

- [ ] **Step 38: Full typecheck + test run**

  ```bash
  cd frontend && npm run typecheck
  # Expected: 0 errors

  cd ../backend && python -m pytest tests/ -q
  # Expected: all tests pass
  ```

- [ ] **Step 39: Smoke test the full scan flow**

  ```bash
  # Start both servers
  cd backend && uvicorn app.main:app --reload --port 8000 &
  cd frontend && npm run dev &

  # Run a scan via curl
  curl -X POST http://localhost:8000/api/scan \
    -H "Content-Type: application/json" \
    -d '{"universe":["AAPL","NVDA","MSFT"],"direction":"Bullish","horizon":"Swing","overrides":{}}'
  # Expected: {"scan_id": "REC-...", "candidates": [...], "rejected": [...]}
  ```

- [ ] **Step 40: Open PR from `feature/1-api-integration` → `main`**

---

## How to launch the next workstream from this plan

1. Open this file, find the next unchecked step.
2. If it says "Write context doc": run that as a task in this session. The scope description above is the brief.
3. If it says "Launch WS-XX": follow the worktree template, then dispatch to a fresh Claude session with the single line: `"Read llm-contexts/XX-name.md fully before writing any code."`
4. When the workstream is done and merged: check the step, save this file.

---

*Last updated: 2026-04-30. Base branch: `feature/1-api-integration`.*
