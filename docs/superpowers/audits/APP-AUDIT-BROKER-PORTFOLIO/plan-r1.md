# Adversarial Implementation Plan Audit: Lane F (APP-AUDIT-BROKER-PORTFOLIO) — Round 1

**Reviewed Document:** `.worktrees/app-audit-broker-portfolio-c4b17ff3/docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md`  
**Diff on Branch:** `git -C .worktrees/app-audit-broker-portfolio-c4b17ff3 diff 3cd38f00..HEAD`  
**Tracking Issues:** Issue #354 (Lane F), Programme #348  
**Reviewer:** Independent Adversarial Subagent `d00d3aea-493c-4f1f-8815-65d0ed8a769c`  
**Standard Enforced:** Numerical & Persistence Gate, Broker Order Routing Integrity, Issue #354 Audit Rigor

---

### Audit Findings

1. **Hallucinated `POST /broker/batch-option-order` and Misattribution of Option Order Execution to `SendToBrokerDialog`**
   - Location: Section 2 (`Surface Inventory & Architecture Matrix`, line 40) & Section 1 (line 14)
   - Trigger condition: The plan asserts that `SendToBrokerDialog` submits orders via `POST /broker/option-order` and `POST /broker/batch-option-order`. In reality, `POST /broker/batch-option-order` does not exist anywhere in the codebase, and `SendToBrokerDialog` explicitly places no broker orders—it only saves basket rows as `source='manual'`. Real option orders are placed strictly as individual orders from `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` via `api.postOptionOrder`.
   - Guard snippet: Update Section 2 and Section 3 Task 1: (1) Remove `POST /broker/batch-option-order`; (2) Explicitly inventory `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` as the primary UI surface calling `POST /broker/option-order`; (3) Clarify that `SendToBrokerDialog` is an offline/manual basket tracker.
   - Potential consequence: Breaches Live Broker Order Gate.

2. **Inverted Sign and Missing Order-Type Validation in Tastytrade Paper Adapter Audit**
   - Location: Section 3 (`Task 1 — Broker Adapters & Payload Contract Audit`, lines 70-72)
   - Trigger condition: The plan asserts that Tastytrade Paper adapter performs dry-run balance checks, but omits the adapter's strict price sign convention (`LimitOrder` price must be negative for BUY/debit and positive for SELL/credit: `tastytrade_paper.py:128-132`) and fails to audit the fact that `tastytrade_paper.py:116` hard-rejects market orders (`order_type != "LMT"`).
   - Guard snippet: Update Task 1 for Tastytrade: (1) market orders (`MKT`) refused with `OrderPreflightRefusedError`, (2) limit prices for BUY serialize as negative Decimal debit values (`price = -abs(limit)`), (3) limit prices for SELL serialize as positive Decimal credit values (`price = abs(limit)`).
   - Potential consequence: Breaches Numerical and Live Broker Order Gate.

3. **Tradier Paper Endpoint URL and Equity/Option Side Mapping Discrepancy**
   - Location: Section 3 (`Task 1 — Broker Adapters & Payload Contract Audit`, lines 60-63)
   - Trigger condition: The plan claims Tradier paper orders use `POST /v1/markets/orders` with `side=buy|sell`. In reality, `tradier_paper.py:98` posts to `POST https://sandbox.tradier.com/v1/accounts/{account_id}/orders`, and requires explicit 4-way side mappings (`_EQUITY_SIDE` and `_OPTION_SIDE`).
   - Guard snippet: Correct endpoint to `POST /v1/accounts/{account_id}/orders` and specify payload assertions for all 4 side combinations. Also verify rate-limit governor check (`get_governor().admit_sync("tradier_paper")`).
   - Potential consequence: Breaches Live Broker Order Routing Gate.

4. **Fictitious Conid Resolution and Order Multiplier in IBKR Paper Adapter**
   - Location: Section 3 (`Task 1 — Broker Adapters & Payload Contract Audit`, lines 63-66)
   - Trigger condition: The plan asserts that `ibkr_paper.py` performs conid resolution and includes contract multiplier in the order payload. In reality, `ibkr_paper.py` requires pre-resolved `order.conid`, and `_build_payload` never transmits a contract multiplier field.
   - Guard snippet: Remove claims of internal conid resolution from `ibkr_paper.py`; audit the contract for caller-supplied `conid`. Remove multiplier field assertion from IBKR order payload.
   - Potential consequence: Breaches Live Order Gate.

5. **Complete Misstatement of `premium_cap_basis` Mechanics**
   - Location: Section 3 (`Task 2 — Risk Gates, Capital Limits & Rejection Boundary Verification`, line 84)
   - Trigger condition: The plan defines `premium_cap_basis` as "maximum risk of long option = 100% of premium paid". In reality, `premium_cap_basis` (`portfolio_risk.py:51-86`) evaluates at `max(mid, limit_price)` for LMT orders, and `ask` / `mid + spread/2` for MKT orders.
   - Guard snippet: Rewrite Task 2's description of `premium_cap_basis` to verify entry-price risk is bounded against slippage.
   - Potential consequence: Breaches Numerical Formula Gate.

6. **Hallucinated Sector Exposure Caps (`max_sector_pct`)**
   - Location: Section 3 (`Task 2 — Risk Gates, Capital Limits & Rejection Boundary Verification`, line 88)
   - Trigger condition: The plan claims `portfolio_exposure.py` enforces sector exposure caps. In reality, no sector cap exists; it implements transactional capacity serialization (`ExposureGuard`) and durable hold tracking (`ExposureHold`).
   - Guard snippet: Replace sector caps with actual exposure mechanisms: `lock_exposure`, `load_holds`, `capacity_positions`, `_uncovered_notional`, and hold lifecycle transitions.
   - Potential consequence: Breaches Persistence and Risk Gate.

7. **Inaccurate State Machine States in `BrokerAttemptService`**
   - Location: Section 3 (`Task 3 — Broker Attempts Lifecycle, Idempotency & Concurrency Audit`, line 101)
   - Trigger condition: The plan asserts attempt states `PENDING` -> `SUBMITTED` -> `FILLED` -> `OUTCOME-UNKNOWN`. In reality, states are lowercase: `preparing` -> `dispatching` -> `submitted` | `filled` | `outcome-unknown` | `proven-not-submitted`.
   - Guard snippet: Update Task 3 with exact lowercase states adhering to `_FORWARD`.
   - Potential consequence: Breaches Persistence and State Machine Gate.

8. **Omission of Idless Option Submissions and `prepared_order` Linkage**
   - Location: Section 3 (`Task 3 — Broker Attempts Lifecycle, Idempotency & Concurrency Audit`, lines 100-112)
   - Trigger condition: The plan assumes all submissions supply `attempt_id`. In reality, `step-7-trade-card` submits with `attempt_id: null`, activating `_prepare_idless` to link `prepared_order` stamped on `PortfolioPositionModel`.
   - Guard snippet: Add explicit sub-task auditing `_prepare_idless` and `prepared_order` reconciliation.
   - Potential consequence: Breaches Persistence and Idempotency Gate.

9. **Erroneous Schema Assertions for `PortfolioPositionModel`**
   - Location: Section 3 (`Task 4 — Portfolio Position Reconciliation, Added Fills & Exits Audit`, lines 114-117)
   - Trigger condition: The plan claims `PortfolioPositionModel` persists `quantity`, `shares`, `contracts`, `cost_basis`. In reality, columns are `qty = Column(Integer)` and `contract = Column(String)`; cost basis is derived.
   - Guard snippet: Update Task 4 schema assertions to match SQLAlchemy models.
   - Potential consequence: Breaches Persistence Gate.

10. **False Assertion on Target Rung Rescaling for Partial Ladders**
    - Location: Section 3 (`Task 4 — Portfolio Position Reconciliation, Added Fills & Exits Audit`, lines 121-122)
    - Trigger condition: The plan asserts `_rescale_rung_shares` rescales rungs to sum exactly to total quantity. In reality, it only scales down on reductions and intentionally preserves partial ladders and runners.
    - Guard snippet: Correct Task 4 assertion to verify proportional reduction with runner preservation.
    - Potential consequence: Breaches Numerical Formula Gate.

11. **Misattribution of Manual Position Closing to `EditDrawer.tsx` and Unaudited No-Op `sendToBroker` Stub**
    - Location: Section 2 (line 44) & Section 3 (`Task 4 — Exits, Closures & Stop Parity`, lines 123-124)
    - Trigger condition: The plan assigns manual closing to `EditDrawer.tsx`. In reality, closing is in `portfolio/page.tsx` (`CloseModal`), and `_maybe_send_close_to_broker` in `routers/portfolio.py:73-81` is an unrouted no-op stub.
    - Guard snippet: Move closing to `CloseModal` in `portfolio/page.tsx` and document the unrouted broker exit stub as an operational boundary.
    - Potential consequence: Breaches Live Order Gate.

12. **Missing State-Space Matrix and Audit Artefact Requirements from Issue #354**
    - Location: Section 1 (lines 27-33) & Section 5 (lines 160-178)
    - Trigger condition: Plan omitted the 9-state application matrix required by Issue #354 and Python 3.11 pinning.
    - Guard snippet: Add Section 4 State Space Verification Matrix across the 9 canonical states and pin Python 3.11.
    - Potential consequence: Breaches Audit Completeness and Rigor.

---

### Conclusion & Verdict

- **Total gate findings:** 12
- **Plan stage verdict:** NOT CLEAN
