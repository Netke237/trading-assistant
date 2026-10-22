# APP-AUDIT-BROKER-PORTFOLIO reconciliation report

**Programme:** APP-AUDIT (#348)  
**Phase ID:** `APP-AUDIT-BROKER-PORTFOLIO` (#354)  
**Worktree:** `.worktrees/app-audit-broker-portfolio-c4b17ff3`  
**Branch:** `board/app-audit-broker-portfolio-c4b17ff3`  
**Target Surfaces:** Broker routing (`/broker/*`), Broker Attempts (`BrokerAttemptService`), Paper adapters (`Tradier`, `IBKR`, `Tastytrade`, `Alpaca`), Risk & Exposure engines (`portfolio_risk.py`, `portfolio_exposure.py`), Portfolio storage (`PortfolioPositionModel`, `PositionWriter`), Dialogs & Screens (`SendToBrokerDialog`, `StockSendDialog`, `step-7-trade-card`, `portfolio/page.tsx`, `EditDrawer.tsx`, `CloseModal.tsx`).  
**Baseline Commit:** Frozen at `origin/main` (`3cd38f00`)  
**Status:** Audit Complete — Zero Gate Findings on verified code and formulas; 3 Operational / Informational findings cataloged.

---

## 1. Executive Summary

This reconciliation report delivers the comprehensive Lane F audit of broker order routing, pre-flight risk checks, durable order attempt lifecycles, and portfolio reconciliation across Bamendjou:
1. **Broker Adapters & Order Payloads:** Verified canonical order normalization (`_canonical_order`), payload builders, order types, limit price serialization, and rate-limiting governors across Tradier, IBKR, Tastytrade, and Alpaca paper adapters.
2. **Pre-Flight Risk & Capital Gates:** Verified `check_position_risk` rules, capital caps, long-option loss basis (`premium_cap_basis`), concurrent position limits, exposure hold reservations (`lock_exposure`, `load_holds`), and the rejection zero-state invariant (zero transmissions, zero database writes).
3. **Durable Attempt State Machine & Deduplication:** Verified `BrokerAttemptService` forward state transitions (`preparing` $\to$ `dispatching` $\to$ terminal states), idempotent double-click claim resolution (`leader=False`), idless option order matching (`_prepare_idless` to `PortfolioPositionModel.prepared_order`), and strict zero automated redispatch of uncertain outcomes (`outcome-unknown` $\to$ HTTP 502).
4. **Portfolio Reconciliation & Math:** Verified database schema mapping (`qty = Column(Integer)`), internal composite contract keys, dynamic cost basis and market valuation, weighted average entry price arithmetic on added fills, rung share rescaling preserving runner legs (`_rescale_rung_shares`), realized P&L formulas, and documented the unrouted broker exit stub (`_maybe_send_close_to_broker`).
5. **Frontend Direct Order Lifecycles:** Verified save-first persistence in `directOrder.ts` and `stockDirectSend.ts`, ensuring pre-flight refusals delete pre-saved rows (`verdict: 'delete'`) while ambiguous server errors retain tracked rows with `ORDER-UNKNOWN` notes (`verdict: 'keep'`).

All calculations, schemas, and state transitions strictly satisfy the project's numerical and persistence gate: no formula puts a wrong number in front of the user, no live broker order is miscalculated or misrouted, and all persisted data structures adhere to exact storage conventions.

---

## 2. Surface Inventory & Architecture Matrix

| Component / Layer | Source Location | Underlying Store / Table | External API / Route | Disposition |
|---|---|---|---|---|
| Stock Order API | `backend/app/routers/broker.py` | `BrokerAttempt` | `POST /broker/stock-order` | Verified |
| Option Order API | `backend/app/routers/broker.py` | `BrokerAttempt` | `POST /broker/option-order` | Verified |
| Attempt Service | `backend/app/services/broker_attempts.py` | `broker_attempts` table | N/A (Internal Service) | Verified |
| Broker Router | `backend/app/services/broker_router.py` | N/A | Adapter dispatch | Verified |
| Tradier Paper | `backend/app/data/tradier_paper.py` | N/A | Sandbox API (`POST .../orders`) | Verified |
| IBKR Paper | `backend/app/data/ibkr_paper.py` | N/A | Client Portal API (`:7499/v1/api`) | Verified |
| Tastytrade Paper | `backend/app/data/tastytrade_paper.py` | N/A | tastytrade SDK session | Verified |
| Alpaca Paper | `backend/app/data/alpaca_paper_execution.py` | N/A | Alpaca Paper API (`:443/v2/orders`) | Verified |
| Portfolio Risk | `backend/app/services/portfolio_risk.py` | `risk_rules.yaml` | `check_position_risk` | Verified |
| Portfolio Exposure | `backend/app/services/portfolio_exposure.py` | `exposure_guard` | `lock_exposure` | Verified |
| Position Writer | `backend/app/services/position_writer.py` | `portfolio_positions` | `create_position` | Verified |
| Portfolio Models | `backend/app/models/portfolio.py` | `portfolio_positions`, `closed_positions` | `GET/POST /api/portfolio` | Verified |
| SendToBrokerDialog | `frontend/components/organisms/SendToBrokerDialog/` | `portfolioStore` | Local offline tracker | Verified (DEFECT-BROKER-2) |
| StockSendDialog | `frontend/components/organisms/StockSendDialog/` | `portfolioStore` | `POST /broker/stock-order` | Verified |
| Trade Card Direct Send | `frontend/app/(frame)/screener/step-7-trade-card/` | `portfolioStore` | `POST /broker/option-order` | Verified |
| Portfolio Page & Drawers | `frontend/app/(frame)/portfolio/` | `portfolioStore` | `POST /api/portfolio/{id}/close` | Verified (DEFECT-BROKER-1) |

---

## 3. Data & Arithmetic Parity Audit (The Gate)

### 3.1 Broker Adapters & Order Payloads (Task 1)

#### Canonical Order Normalization
- `_canonical_order` in `backend/app/routers/broker.py:414-438` normalizes payloads into deterministic, canonical forms:
  - **Instrument Formatting:** Stock orders map strictly to `{symbol}|STOCK` (e.g. `AAPL|STOCK`). Option orders map to 21-character canonical OCC representation (e.g. `AAPL250516C00185000`).
  - **Limit Price Normalization:** `Decimal(str(req.limit_price)).normalize()` eliminates floating-point representation artifacts (e.g. `185.500000000001` $\to$ `"185.5"`).
  - **Quantity Invariant:** Enforces strict integer `ge=1` validation on both stock and option order schemas.

#### Adapter Payload Specifications
- **Tradier Paper (`tradier_paper.py`):**
  - Targets `POST https://sandbox.tradier.com/v1/accounts/{account_id}/orders`.
  - Maps 4-way side semantics:
    - Equity (`_EQUITY_SIDE`): `(BUY, OPEN) -> buy`, `(SELL, OPEN) -> sell_short`, `(SELL, CLOSE) -> sell`, `(BUY, CLOSE) -> buy_to_cover`.
    - Option (`_OPTION_SIDE`): `(BUY, OPEN) -> buy_to_open`, `(SELL, OPEN) -> sell_to_open`, `(SELL, CLOSE) -> sell_to_close`, `(BUY, CLOSE) -> buy_to_close`.
  - Governor pacing: Integrates with `get_governor().admit_sync("tradier_paper")` to ensure 0.5s inter-call pacing.
- **IBKR Paper (`ibkr_paper.py`):**
  - Requires pre-resolved `conid` on option orders; no conid discovery is executed inside the adapter.
  - Payload ticket construction (`_build_payload`):
    - Transmits `{"orders": [{"orderType": ..., "side": ..., "quantity": ..., "tif": ..., "conidex": str(conid), "secType": f"{conid}:{sec_type}"}]}` when conid is present (omitting `"symbol"`).
    - Multiplier: Explicit 100 multiplier for option contracts.
  - Confirmation question handling: When `result.awaiting_confirmation is True`, `_raise_if_awaiting_confirmation` logs `broker_order_failed` and raises `HTTPException(status_code=502)` (not `OrderAdmissionRefusedError`), recording the attempt as `proven-not-submitted`.
- **Tastytrade Paper (`tastytrade_paper.py`):**
  - Hard-rejects market orders (`order.order_type != "LMT"`) via `OrderPreflightRefusedError`.
  - Price sign convention:
    $$\text{price} = \begin{cases} -\text{abs}(\text{limit}) & \text{if BUY (debit)} \\ +\text{abs}(\text{limit}) & \text{if SELL (credit)} \end{cases}$$
  - Direct execution: executes directly with `dry_run=False`.
- **Alpaca Paper (`alpaca_paper_execution.py`):**
  - Serializes stock orders to `POST https://paper-api.alpaca.markets/v2/orders` with `symbol`, `qty`, `side`, `type`, `time_in_force`, and `limit_price`.
  - Option order refusal: Immediately raises `OrderPreflightRefusedError("AlpacaPaperAdapter only supports stock (STK) orders")` when `sec_type != "STK"`.

---

### 3.2 Pre-Flight Risk & Capital Gates (Task 2)

#### Capital & Loss Cap Enforcement
- `check_position_risk` (`backend/app/services/portfolio_risk.py`):
  - `min_portfolio_value`: Refuses orders when account capital is below threshold ($1,000 default), returning `portfolio_too_small`.
  - `max_contracts_per_trade`: Hard refusal when proposed contracts exceed sizing cap (10 contracts default), returning `exceeds_max_contracts_per_trade`.
  - `max_single_position_pct`: Compares `capital_at_risk / portfolio_value` against single position limit (5% default). If reduced size $\ge 1$, returns soft `size_reduced_to_fit_exposure_limit`; if even 1 contract exceeds cap, returns hard refusal `single_trade_exposure_too_high`.
  - `max_total_exposure_pct`: Asserts combined existing exposure plus new trade does not exceed total portfolio exposure limit (20% default), returning `total_exposure_limit_reached`.

#### Long Option Premium Risk Basis (`premium_cap_basis`)
- Entry-price risk bounds (`portfolio_risk.py:51-86`):
  $$\text{premium\_cap\_basis} = \begin{cases} \max(\text{mid}, \text{limit\_price}) & \text{for LMT orders} \\ \text{ask} \quad (\text{or } \text{mid} + \frac{\text{spread}}{2}) & \text{for MKT orders} \\ \text{mid} & \text{for unplaced/basket rows} \end{cases}$$
- Protects against limit price slippage and worst-case fills on long option orders.

#### Rejection Zero-State Invariant
- Validated via `TestTask2RiskGates::test_rejection_zero_state_invariant`:
  - When an order is refused at preflight or risk check:
    1. Zero network transmissions are made to any external broker adapter.
    2. Zero rows are inserted into `portfolio_positions` or `closed_positions`.
    3. Exposure holds in `exposure_guard` are released immediately.

---

### 3.3 Broker Attempts Lifecycle & Concurrency (Task 3)

#### State Transition Finite State Machine
- Lowercase states strictly governed by `_FORWARD` table in `backend/app/services/broker_attempts.py`:
  - `preparing` $\to$ `outcome-unknown` (crash/timeout before dispatch)
  - `dispatching` $\to$ `submitted` $\lor$ `filled` $\lor$ `outcome-unknown` $\lor$ `proven-not-submitted`
  - Terminal states (`submitted`, `filled`, `outcome-unknown`, `proven-not-submitted`) have no forward transitions.

#### Deduplication & Concurrency
- **Double-Click Deduplication:** First call acquires `claim` as leader (`leader=True, authorized=True, state="dispatching"`). Rapid second call with identical attempt ID and payload returns cached claim with `leader=False, authorized=False`.
- **In-Flight Waiters:** Callers awaiting resolution wait on `_attempt_waiters[attempt_id]`, preventing concurrent duplicate submissions.
- **Idless Option Order Deduplication:** Direct option orders submitted from `step-7-trade-card` submit with `attempt_id: null`. `_prepare_idless` queries `PortfolioPositionModel` where `prepared_order.is_not(None)`, verifies matching order attributes via `_prepared_matches`, assigns a durable UUID attempt ID, and updates `PortfolioPositionModel.order_attempt_id`.

#### Unknown Submission Outcomes (Decision #165 / BROKER-PATH-RESIDUALS)
- On network timeout or dropped HTTP connection after transmission:
  - Attempt transitions to durable state `outcome-unknown`.
  - Endpoint returns HTTP 502 with `{"detail": "submission outcome unknown"}`.
  - **Zero automated redispatch:** Any subsequent claim attempt with the same payload fingerprint raises `BrokerAttemptConflict` (HTTP 409). Automated background re-transmissions are strictly forbidden.

---

### 3.4 Portfolio Position Reconciliation & Arithmetic (Task 4)

#### Database Schema Integrity
- `PortfolioPositionModel` (`backend/app/models/portfolio.py`):
  - Quantity persists strictly to `qty = Column(Integer, nullable=False, default=1)`. No `quantity` column exists.
  - Contract identifier stores internal composite key `{symbol}|{strike}|{expiry}|{right}` (for options) or `{symbol}|STOCK` (for equities) in `contract = Column(String, unique=True)`.
  - Dynamic derivation: `cost_basis` and current valuation are dynamically derived as $\text{entry\_price} \times \text{qty} \times \text{multiplier}$ ($1$ for stocks, $100$ for options). No fictitious cost basis columns exist.

#### Added Fills Weighted Average Entry Price
- When a position receives additional shares/contracts via `confirmAddedFill` (`EditDrawer.tsx` -> `portfolioStore.ts:sendAddedFill` -> `routers/portfolio.py:update_position` -> `portfolio_exposure.py:weighted_entry`):
  $$\text{New Average Entry Price} = \frac{(\text{Old Qty} \times \text{Old Entry}) + (\text{Added Qty} \times \text{Added Price})}{\text{Old Qty} + \text{Added Qty}}$$
- Validated via `TestTask4PortfolioReconciliation::test_weighted_average_price_arithmetic`: 10 shares @ $150 + 5 shares @ $165 $\to$ 15 shares @ $155.00 exact.

#### Target Rung Rescaling & Runner Preservation
- `_rescale_rung_shares` in `position_writer.py:209-232`:
  - When stored quantity $\ge$ asked quantity: returns target rungs untouched.
  - When partial fill occurs (stored $<$ asked): scales target rungs down proportionally:
    $$\text{target\_sum} = \min\left(\text{stored}, \frac{\text{total} \times \text{stored}}{\text{asked}}\right)$$
  - Preserves runner legs and active rungs without truncating target price definitions. Tested with 100 asked, 50 stored, 60 rung shares (40 runner shares) $\to$ exact 30 rescaled rungs (15 each) and 20 runner shares preserved (40%).

#### Realized P&L Calculation
- `ClosedPositionModel` (`backend/app/models/closed_position.py`) stores `qty_closed = Column(Integer, nullable=False)`, `realized_pnl_dollar`, and `realized_pnl_pct`.
- Math is computed in `portfolio_performance.py:realized_pnl` and signed via `is_short_stock_position` in `routers/portfolio.py:close_position`:
  - Stocks Long: $(\text{exit\_price} - \text{entry\_price}) \times \text{qty\_closed} \times 1$
  - Stocks Short: $(\text{entry\_price} - \text{exit\_price}) \times \text{qty\_closed} \times 1$ (sign-inverted via `is_short_stock_position("AAPL|STOCK", "Bearish")`)
  - Options: $(\text{exit\_price} - \text{entry\_price}) \times \text{qty\_closed} \times 100$ (via `_contract_multiplier`)

#### Operational Boundary: Unrouted Broker Exit Stub (DEFECT-BROKER-1)
- Verified `_maybe_send_close_to_broker` in `backend/app/routers/portfolio.py:73-81`:
  - Closing a position from `CloseModal.tsx` calls `POST /api/portfolio/{id}/close`.
  - If `sendToBroker=True`, the router invokes `_maybe_send_close_to_broker`, which logs a warning (`"sendToBroker=True for %s but broker close-routing is not yet implemented — order NOT sent"`) and returns without placing any order at any broker adapter.
  - Position is archived locally in `closed_positions`, but live broker exit routing remains unrouted.

---

## 4. State Space Verification Matrix

| State | SendToBrokerDialog (Basket) | StockSendDialog | Trade Card Direct Order | Portfolio Table & Drawers | Broker Router & Attempts |
|---|---|---|---|---|---|
| **Normal** | Adds position to `portfolioStore` with `source: 'manual'`; no broker order. | Persists pre-saved position, transmits `POST /broker/stock-order`, transitions to `placed`. | Persists pre-saved position, transmits `POST /broker/option-order`, matches `prepared_order`, transitions to `placed`. | Renders active positions, P&L, DTE, target rungs, and stop status. | Resolves adapter, validates pre-flight, transitions attempt `preparing` $\to$ `dispatching` $\to$ `submitted`/`filled`. |
| **Expanded / Nested** | Edit drawer / target rungs inspection. | Preview card showing order details and limit price. | CandidateNav alternative contracts view. | `EditDrawer` exposes added fills, ladder rungs, and trailing stop rules. | Full payload details inspected with exact OCC and pricing keys. |
| **Empty** | "Add to Portfolio" disabled when inputs invalid. | Quantity input clamped $\ge 1$; empty inputs disabled. | Direct order buttons disabled when trade card has no valid option selection. | Empty state banner: "No open positions. Run a scan to discover setups." | Empty orders rejected with Pydantic 422. |
| **Loading** | Immediate synchronous store mutation. | Spinner on Submit button; inputs disabled during transmission. | "Sending..." state on Place Limit / Right Now buttons; card navigation locked. | Skeleton rows during initial `/api/portfolio` fetch. | `_attempt_waiters[attempt_id]` holds concurrent callers during dispatch. |
| **Failed / Cancelled** | Invalid input displays validation error; no mutation. | Broker 422 deletes row via `classifyDirectFailure(verdict='delete')`; Broker 500 / network drop retains row with `ORDER-UNKNOWN` note (`verdict='keep'`). | Broker 422 deletes row (`verdict='delete'`); Broker 500 / network drop retains row with `ORDER-UNKNOWN` note (`verdict='keep'`). | API failure displays error toast; optimistic update rolled back. | Attempt marked `outcome-unknown` on dropped connection; HTTP 502 returned; zero automated redispatch. |
| **Legacy / Unsupported** | N/A | Market orders on illiquid names warn of slippage. | Tastytrade paper rejects market orders via `directOrderBlock`. | Migrates legacy storage keys and unfloored stops (`floorStop`). | Alpaca paper rejects option orders with `OrderPreflightRefusedError`. |
| **Zero / False / Null / Absent** | Zero quantity rejected; null limit defaulted. | Quantity 0 rejected (`ge=1`); null limit rejected for LMT. | `attempt_id: null` triggers backend `_prepare_idless` resolution. | `quoteUnavailable: true` renders "?" price and leaves row out of totals. | Missing broker credentials return HTTP 503 (`OrderBeforeSubmissionError`). |
| **Stale Async Response** | N/A | Cached response returned on duplicate submit (`deduped=True`). | Out-of-order response matches exact `contractLabelFor`. | Synchronous `syncFromBackend` serializes updates, avoiding last-write-wins races. | Stale verification version rejected on `record_outcome` with HTTP 409. |
| **Post-Reload / Restart** | State restored from persisted `portfolioStore`. | Pending notes restored from `directSendNotesStore`. | Pending notes restored from `directSendNotesStore`. | Portfolio rehydrated from local storage, then synchronized with `/api/portfolio`. | Durable attempts preserved in SQLite/PostgreSQL `broker_attempts` table. |

---

## 5. Findings & Discrepancies Catalog

### Operational Boundary DEFECT-BROKER-1: Unrouted Broker Exit Stub
- **Location:** `backend/app/routers/portfolio.py:73-81` (`_maybe_send_close_to_broker`)
- **Severity:** Low (Operational Boundary)
- **Gate Blocking:** False
- **Observed Behavior:** When a position is closed via `CloseModal.tsx` with `sendToBroker=True`, the request records the closure in `closed_positions` and deletes the active row, but logs a warning without transmitting any order to Tradier, IBKR, Alpaca, or Tastytrade.
- **Remediation:** Documented as an intended operational boundary. Live exit order placement will be routed in a dedicated exit execution phase.

### Usability Observation DEFECT-BROKER-2: SendToBrokerDialog Copy Discrepancy
- **Location:** `frontend/components/organisms/SendToBrokerDialog/index.tsx`
- **Severity:** Informational
- **Gate Blocking:** False
- **Observed Behavior:** The dialog title and submit button ("Send to Broker") imply live broker transmission, but the implementation is strictly an offline basket row tracker adding positions to `usePortfolioStore` with `source='manual'`.
- **Remediation:** Clarify dialog header to indicate "Add to Portfolio Basket (Manual Track)" to avoid user confusion.

### Operational Environment DEFECT-BROKER-3: Live Broker Gateway Local Prerequisites
- **Location:** `backend/app/data/ibkr_paper.py`, `tradier_paper.py`, `tastytrade_paper.py`
- **Severity:** Informational
- **Gate Blocking:** False
- **Observed Behavior:** End-to-end execution against live sandbox endpoints requires active daemons (IBKR Client Portal gateway on port 7499) and decrypted local credentials (`local_credentials.yaml`) available on Kenneth's workstation.
- **Remediation:** Verified deterministically via mock harnesses; live sandbox sanity runs to be performed during authorized interactive sessions.

---

## 6. Verification Evidence

### 6.1 Backend Test Execution (Python 3.11)
```
backend/.venv/Scripts/python.exe -m pytest tests/test_audit_broker_portfolio_lane_f.py -v
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.1.1, pluggy-1.6.0
collected 21 items

tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_canonical_order_normalization_stock PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_canonical_order_normalization_option PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_tradier_endpoint_and_side_mapping PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_ibkr_paper_payload_keys_and_conid_contract PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_ibkr_confirmation_question_http_502 PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_tastytrade_paper_order_type_and_price_sign PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_tastytrade_paper_option_leg_resolution PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask1BrokerAdapters::test_alpaca_paper_option_rejection PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask2RiskGates::test_premium_cap_basis_lmt_and_mkt PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask2RiskGates::test_capital_cap_rejection PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask2RiskGates::test_loss_cap_rejection PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask2RiskGates::test_rejection_zero_state_invariant PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask3AttemptsLifecycle::test_state_machine_forward_lifecycle PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask3AttemptsLifecycle::test_deduplication_double_click PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask3AttemptsLifecycle::test_idless_option_order_matching PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask3AttemptsLifecycle::test_outcome_unknown_no_auto_redispatch PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask4PortfolioReconciliation::test_schema_mapping_and_contract_string PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask4PortfolioReconciliation::test_weighted_average_price_arithmetic PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask4PortfolioReconciliation::test_rung_share_rescaling_runner_preservation PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask4PortfolioReconciliation::test_realized_pnl_calculation PASSED
tests/test_audit_broker_portfolio_lane_f.py::TestTask4PortfolioReconciliation::test_unrouted_broker_exit_stub PASSED

============================= 21 passed in 7.75s ==============================
```

### 6.2 Frontend Test Execution (Jest)
```
npm test -- auditBrokerPortfolioLaneF
PASS lib/__tests__/auditBrokerPortfolioLaneF.test.ts
  Lane F Frontend Audit: Direct Order Classification & Portfolio Reconciliation
    Task 1 & Task 3: classifyDirectFailure lifecycle and preflight boundaries
      √ classifies 422 pre-flight refusal as safe to delete pre-saved row (6 ms)
      √ classifies unauthenticated broker credentials (503) as safe to delete (1 ms)
      √ classifies IBKR confirmation question refusal (502) as safe to delete (1 ms)
      √ retains pre-saved position (verdict: keep) on 500 internal server error (2 ms)
      √ retains pre-saved position (verdict: keep) on network drop / gateway timeout (504) (5 ms)
      √ retains pre-saved position (verdict: keep) when broker reply lacks usable order ID (2 ms)
      √ classifies successful submission with usable order ID as placed (2 ms)
      √ enforces Tastytrade paper market order preflight refusal (2 ms)
      √ formats broker labels truthfully across all supported paper adapters (2 ms)
      √ distinguishes accepted/pending states from executed fills (2 ms)
    Task 4: Portfolio Store duplicate contract merging & domain keys
      √ creates canonical contract composite key and display label (2 ms)
      √ merges duplicate contract positions in portfolioStore and sums contracts (96 ms)

Test Suites: 1 passed, 1 total
Tests:       12 passed, 12 total
Snapshots:   0 total
Time:        12.701 s
```

### 6.3 Frontend Typecheck
```
npm run typecheck
> bamendjou-frontend@0.1.0 typecheck
> tsc --noEmit
(Clean — 0 type errors)
```

### 6.4 State Verification
```
python scripts/state.py
Bamendjou — stop-model state (source: docs/superpowers/PROJECT_STATE.json, updated 2026-10-21)
No drift: every declared status matches the code.
```
