# APP-AUDIT-BROKER-PORTFOLIO — Lane F Execution Plan

**Tracking:** Issue [#354](https://github.com/Netke237/trading-assistant/issues/354), Programme [#348](https://github.com/Netke237/trading-assistant/issues/348)  
**Phase ID:** `APP-AUDIT-BROKER-PORTFOLIO`  
**Branch:** `board/app-audit-broker-portfolio-c4b17ff3`  
**Source Baseline:** Frozen at `origin/main` commit `3cd38f00b5489930eb12c12107c6a5521ca05c2a`  
**Report Destination:** `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/report.md`  

---

## 1. Goal and Deliverables

Verify broker payloads, risk gates, order attempts lifecycle, and Portfolio position reconciliation across both frontend and backend surfaces of Bamendjou:
1. **Send Dialogs & Baskets** (`SendToBrokerDialog`, `StockSendDialog`, `DirectSendNotesPanel`)
2. **Broker Adapters & Routing** (`tradier_paper`, `ibkr_paper`, `alpaca_paper_execution`, `tastytrade_paper`, `broker_router.py`)
3. **Risk Gates & Capital Validation** (`risk.ts`, `riskStore.ts`, `portfolio_risk.py`, `portfolio_exposure.py`, `position_writer.py`)
4. **Order Attempts & Idempotency** (`broker_attempts.py`, `routers/broker.py`)
5. **Portfolio Reconciliation & Exits** (`portfolioStore.ts`, `routers/portfolio.py`, `EditDrawer.tsx`, `position_writer.py`)

The audit establishes exact end-to-end parity: comparing final UI confirmation → API request → exact adapter payload → broker response → persisted position. It verifies that capital, share, contract multiplier (100x), limit price, and exposure units are mathematically sound, ensures no unauthorized order transmission occurs on rejection paths, proves idempotency and deduplication across process restarts, and verifies that portfolio positions and stops match alert monitor levels.

**Audit Boundaries:**
- **Audit and report scope only:** No application code, trading policies, risk thresholds, or database schemas are modified during this audit phase.
- **Zero live broker orders:** All checks are executed against deterministic stubs, paper adapters, and isolated test databases. Real paper broker tests requiring live credentials or market connectivity remain explicitly documented as operational requirements rather than mock passes.
- **Discovered defects** are cataloged into structured findings; each actionable defect becomes a separate board remediation ticket.

**Deliverable Artifacts** (under `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/`):
1. `provenance.json`: Frozen environment, Node, Python 3.11, Chromium, commit SHAs, config hashes, and fixture provenance.
2. `reconciliation.json`: Explicit mapping between Lane A inventoried surfaces/states and Lane F audit touchpoints.
3. `defects.json`: Separated numbers/persistence and presentation/usability defect ledger with full reproduction steps.
4. `README.md` & `report.md`: Complete audit findings, verified assertions, reproduction evidence, and open residuals.
5. Automated evidence harnesses and tests: deterministic scripts verifying payloads, risk limits, attempts lifecycle, added fills, and exits.

---

## 2. Surface Inventory & Architecture Matrix

| Surface / Component | Source Path | Stores / Services Attached | Backend Endpoints | Key Responsibilities |
|---|---|---|---|---|
| **Option Send Dialog** | `frontend/components/organisms/SendToBrokerDialog/` | `useSettingsStore`<br>`useRiskStore`<br>`usePortfolioStore` | `POST /broker/option-order`<br>`POST /broker/batch-option-order` | Strike/expiry display, contract count, limit price, premium calculation, account balance check, exposure check. |
| **Stock Send Dialog** | `frontend/components/organisms/StockSendDialog/` | `useSettingsStore`<br>`useRiskStore`<br>`usePortfolioStore` | `POST /broker/stock-order` | Share quantity, order type (MKT/LMT), limit price, total capital, stop/target prices, risk/reward preview. |
| **Direct Send Notes** | `frontend/components/organisms/DirectSendNotesPanel/` | `useDirectSendNotesStore` | `POST /journal/entries` (optional link) | Execution operator notes attached to submitted orders. |
| **Portfolio Page** | `frontend/app/(frame)/portfolio/page.tsx` | `usePortfolioStore`<br>`useRiskStore`<br>`useSettingsStore` | `GET /api/portfolio`<br>`GET /api/quotes` | Stocks and Options positions table, summary metrics (`openTotals`), P&L calculations, delta/theta sums. |
| **Portfolio EditDrawer** | `frontend/app/(frame)/portfolio/EditDrawer.tsx` | `usePortfolioStore`<br>`useAlertStore` | `PATCH /api/portfolio/{id}`<br>`POST /api/portfolio/{id}/close` | Position editing, adding fills (weighted average price), adjusting stop/target levels, manual closing. |
| **Broker Router** | `backend/app/services/broker_router.py` | `CredentialStore` | Internal router resolution | Resolves broker adapter by name (`tradier`, `ibkr`, `alpaca`, `tastytrade`), routing paper vs live credentials. |
| **Broker Attempts** | `backend/app/services/broker_attempts.py` | `BrokerAttemptService`<br>DB attempts table | `GET /broker/attempts/{id}`<br>`POST /broker/attempts/verify` | Durable order attempt state machine, idempotency keys, duplicate suppression, unknown outcome resolution. |
| **Position Writer** | `backend/app/services/position_writer.py` | `AsyncSession`<br>Portfolio SQLite/PostgreSQL | `POST /api/portfolio`<br>`PATCH /api/portfolio/{id}` | Atomic position creation, capital/exposure gates, rung share rescaling, added fills, stop level floor. |
| **Paper Adapters** | `backend/app/data/{tradier_paper,ibkr_paper,alpaca_paper_execution,tastytrade_paper}.py` | Broker client SDKs / HTTP sessions | Broker paper API endpoints | Converts canonical `BrokerOrder` into broker-specific JSON/form payloads and parses fills/order IDs. |

---

## 3. Detailed Audit Scope & Verification Tasks

### Task 1 — Broker Adapters & Payload Contract Audit
- **Canonical Order Normalization (`_canonical_order` in `backend/app/routers/broker.py:414-438`):**
  - Verify instrument string formatting: `{symbol}|STOCK` for equities; exact OCC symbol `{symbol}{YYMMDD}{C/P}{strike_padded}` for options.
  - Verify limit price serialization: formatted via `Decimal(str(req.limit_price)).normalize()` to avoid floating point representations like `182.500000000001`.
  - Verify quantity constraints: strict integer `ge=1` on both `StockOrderRequest` and `OptionOrderRequest`.
- **Adapter Payloads across Supported Brokers:**
  - **Tradier Paper (`tradier_paper.py`):**
    - Stock: `POST /v1/markets/orders` with `class=equity`, `symbol`, `side=buy|sell`, `quantity`, `type=market|limit`, `price`, `duration=day|gtc`.
    - Option: `class=option`, `option_symbol`, `side=buy_to_open|sell_to_close`.
  - **IBKR Paper (`ibkr_paper.py`):**
    - Conid resolution via `secdef/search` or `trsrv/secdef`.
    - Order ticket payload with contract multiplier (100 for equity options).
    - Handling confirmation hooks and order questions (`_confirmation_question`).
  - **Alpaca Paper (`alpaca_paper_execution.py`):**
    - Stock order payload formatting (`symbol`, `qty`, `side`, `type`, `time_in_force`, `limit_price`).
    - Rejection of options trading on Alpaca (unsupported broker instrument check).
  - **Tastytrade Paper (`tastytrade_paper.py`):**
    - Async loop bridge integration (`tastytrade_bridge.py`).
    - Account number resolution, leg formatting, dry-run balance checks.
- **Fractional Strikes & Precision:**
  - Verify decimal strike serialization (e.g. `182.5`) across all 4 adapters.
  - Link and cross-reference issue [#162](https://github.com/Netke237/trading-assistant/issues/162) (`EXACT-STRIKE`).
- **Multiplier & Premium Accounting:**
  - Verify option premium multiplier: total cash required = $\text{limit\_price} \times 100 \times \text{contracts}$.
  - Ensure UI display and backend payload never confuse per-share premium with total contract cost.

### Task 2 — Risk Gates, Capital Limits & Rejection Boundary Verification
- **Capital & Loss Gates (`backend/app/services/portfolio_risk.py` & `position_writer.py`):**
  - `max_capital_per_trade`: order value $\le \text{cap}$.
  - `max_loss_per_trade_pct`: projected loss at stop $\le \text{portfolio\_value} \times \text{max\_loss\_pct}$.
  - Long option loss cap basis (`premium_cap_basis`): maximum risk of long option = $100\% \text{ of premium paid}$.
  - Audit of client `portfolioValue` multiplier: verify behavior when user modifies portfolio value in `riskStore` vs server default ($100,000$ in YAML, $50,000$ in schemas; reference item R3 in `TRADING_REVIEW.md`).
- **Exposure Limits (`backend/app/services/portfolio_exposure.py`):**
  - Verify reservation hooks (`daily_risk_hooks`, `portfolio_exposure_hooks`).
  - Sector exposure caps: total active capital in single sector $\le \text{max\_sector\_pct}$.
  - Hold release on failure: verify `_release_open_risk` releases exposure holds when order submission fails before broker transmission.
- **Direction & Regime Gates:**
  - Verify bearish scan execution block (`BEARISH_UNVALIDATED_MESSAGE` in `routers/broker.py:26`, link to [#87](https://github.com/Netke237/trading-assistant/issues/87) / [#107](https://github.com/Netke237/trading-assistant/issues/107)).
  - Verify market regime REJECT gate: UI confirmation / refusal of execution when market regime is REJECT.
- **Rejection Zero-State Invariant:**
  - Prove that any rejected order (failing risk gate, unvalidated regime, invalid limit, or missing credentials) produces:
    1. Zero broker network transmissions.
    2. Zero created rows in `portfolio_positions` database.
    3. Proper release of temporary exposure reservations.

### Task 3 — Broker Attempts Lifecycle, Idempotency & Concurrency Audit
- **Attempt State Machine (`backend/app/services/broker_attempts.py`):**
  - States: `PENDING` $\to$ `SUBMITTED` $\to$ `FILLED` $\lor$ `OUTCOME-UNKNOWN` $\lor$ `PROVEN-NOT-SUBMITTED`.
  - Idempotency key tracking: verification of `attempt_id` consistency, format, and collision rejection (`BrokerAttemptConflict`).
- **Deduplication & Concurrency:**
  - Rapid double-click on Send button: first request acquires claim; second request receives cached response with `"deduped": true`.
  - In-flight concurrency: second request awaiting resolution waits on `_attempt_waiters[attempt_id]` without re-submitting to broker.
- **Unknown Submission Outcomes:**
  - Network timeout or connection drop after payload transmission: state transition to `outcome-unknown`.
  - HTTP 502 with `{"detail": "submission outcome unknown"}` returned to client.
  - Enforce decision [#165](https://github.com/Netke237/trading-assistant/issues/165) / `BROKER-PATH-RESIDUALS`: strictly **no automated redispatch** of unknown outcomes.
- **Crash Recovery & Restart:**
  - Server restart with unconfirmed attempt: attempt remains recorded as durable attempt in DB; verify restart behavior does not duplicate order.

### Task 4 — Portfolio Position Reconciliation, Added Fills & Exits Audit
- **Position Creation & Accounting (`backend/app/services/position_writer.py`):**
  - Stock position: `quantity = shares`, `entry_price = fill_price`, `cost_basis = shares * fill_price`.
  - Option position: `contracts = quantity`, `entry_price = fill_price`, `cost_basis = contracts * fill_price * 100`.
  - Strike formatting: numeric float / integer strike preserved accurately in position model.
- **Added Fills Arithmetic (`frontend/app/(frame)/portfolio/EditDrawer.tsx` & `backend/app/services/position_writer.py`):**
  - Weighted average price formula:
    $$\text{New Average Price} = \frac{(\text{Old Qty} \times \text{Old Entry}) + (\text{Added Qty} \times \text{Added Price})}{\text{Old Qty} + \text{Added Qty}}$$
  - Rung share rescaling: verify `_rescale_rung_shares` rescales exit target shares proportionally to sum exactly new total quantity.
- **Exits, Closures & Stop Parity:**
  - Manual position closing: `POST /api/portfolio/{id}/close` creating record in `closed_positions` and removing/archiving active position.
  - Realized P&L calculation:
    - Stocks: $(\text{exit\_price} - \text{entry\_price}) \times \text{quantity}$ (long) or $(\text{entry\_price} - \text{exit\_price}) \times \text{quantity}$ (short).
    - Options: $(\text{exit\_price} - \text{entry\_price}) \times \text{contracts} \times 100$.
  - Stop loss parity: verify stop price in Portfolio position matches active alert rule level (`STOP-ALERT-DRAWER-PARITY`, issue [#334](https://github.com/Netke237/trading-assistant/issues/334)).
- **Store Reconciliation & Offline Behavior (`frontend/lib/portfolioStore.ts`):**
  - Duplicate contract merging in `addPosition`: merging positions with identical `contractId(symbol, strike, expiry, right)`.
  - Optimistic updates and rollback on API error.
  - Offline mode: rendering cached portfolio when backend is unreachable, displaying clear offline status without zeroing deployed capital.

### Task 5 — Reconcile Evidence, Catalog Findings, and Publish Lane F Report
- Reconcile Lane A surface inventory rows (all broker, send, and portfolio elements) against Lane F evidence.
- Build comprehensive artifacts:
  - `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/provenance.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/reconciliation.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/defects.json`
  - `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/report.md`
- Classify findings into:
  - Numerical / Persistence Gate findings (blocking).
  - Usability / Presentation observations (non-blocking).
  - Operational live-environment checks (explicitly logged as requiring Kenneth's authorized session on the mini PC).
- Run full typecheck and relevant backend/frontend test suites.

---

## 4. Historical Context & Related Tickets

| Ticket / Decision | Title | Relationship to Lane F Audit |
|---|---|---|
| [#162](https://github.com/Netke237/trading-assistant/issues/162) | **EXACT-STRIKE** | Fractional-strike broker serialization across option orders and broker adapters. |
| [#165](https://github.com/Netke237/trading-assistant/issues/165) | **BROKER-PATH-RESIDUALS** | Durable broker attempts, no automated redispatch of unknown outcomes, exposure holds. |
| [#334](https://github.com/Netke237/trading-assistant/issues/334) | **STOP-ALERT-DRAWER-PARITY** | Parity between Portfolio stop loss levels and background alert monitor rules. |
| [#171](https://github.com/Netke237/trading-assistant/issues/171) | **Direct Send Notes** | Operator notes persistence during direct order transmission. |
| [#107](https://github.com/Netke237/trading-assistant/issues/107) | **P0B Market-Hours UI Check** | Verification of bearish scan order blocking during market hours (Kenneth mini-PC task). |

---

## 5. Verification Strategy & Test Harnesses

To gather deterministic, reproducible evidence without mutating production databases or placing live broker orders:
1. **Isolated Backend Database Fixtures:**
   - Run tests using in-memory or temporary SQLite test databases (`tmp_path`).
   - Mock broker network responses (`httpx` / SDK clients) with representative success, rejection, timeout, and partial fill fixtures.
2. **Deterministic Adapter Payload Assertions:**
   - Inspect raw HTTP requests and parameters generated by `tradier_paper`, `ibkr_paper`, `alpaca_paper_execution`, and `tastytrade_paper`.
   - Assert exact string and numeric equality for strikes, multipliers, order types, and sides.
3. **Frontend Dialog & Store Simulation:**
   - Execute Jest tests for `SendToBrokerDialog`, `StockSendDialog`, `portfolioStore`, and `EditDrawer`.
   - Verify calculation of total debit/credit, added fills weighted price, and duplicate merge.
4. **Automated Evidence Scripts:**
   - Write standalone audit scripts under `docs/superpowers/audits/app-audit/APP-AUDIT-BROKER-PORTFOLIO/` verifying:
     - `verify_broker_payloads.py`: Validates adapter payload structures and decimal strike normalization.
     - `verify_risk_gates.py`: Validates capital, exposure, and directional rejection paths.
     - `verify_attempts_lifecycle.py`: Validates deduplication, idempotency, and unknown outcome handling.
     - `verify_portfolio_reconciliation.py`: Validates position booking, 100x multiplier, added fills, and exit P&L.

---

## 6. Independent Adversarial Review Workflow

In accordance with `AGENTS.md` and `.claude/skills/K-adversarial-audit-loop/SKILL.md`:
1. **Plan Stage:**
   - Submit this plan to a fresh independent subagent using `bmad-review-adversarial-general`.
   - Review against numeric and persistence gates: verify that all formulas, schemas, endpoints, and error paths are completely covered.
   - Address all findings iteratively until a clean verdict (`audit_clean: true`) is obtained (max 3 rounds per stage).
2. **Decomposition:**
   - Create build/audit sub-tickets under tracking issue [#354](https://github.com/Netke237/trading-assistant/issues/354) with native GitHub dependency links.
3. **Execution & Evidence:**
   - Execute the verification tasks, run test suites, and write the report and defect ledgers.
4. **Code & Evidence Stage:**
   - Merge `origin/main` into the branch.
   - Submit the complete diff `origin/main..HEAD` to a fresh independent adversarial reviewer.
   - Address any findings until clean (max 3 rounds).
5. **Self-Merge:**
   - Once plan and code audits are clean and CI is green, execute self-merge per `board.md` step 7.
