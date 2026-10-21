# Round 2 Adversarial Review: Implementation Plan for APP-AUDIT-BROKER-PORTFOLIO

**Target Diff:** `git -C .worktrees/app-audit-broker-portfolio-c4b17ff3 diff d632995f..30e88233`  
**Plan File:** `.worktrees/app-audit-broker-portfolio-c4b17ff3/docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md`  
**Review Standard:** `.claude/skills/bmad-review-adversarial-general/SKILL.md` (Strict Numeric & Persistence Gates)

---

### Status of Round 1 Findings Resolution

| # | Round 1 Finding | Status in Diff `d632995f..30e88233` | Verification vs Codebase |
|---|---|---|---|
| 1 | Hallucinated batch endpoint | **Mostly Resolved** | `POST /broker/batch-option-order` removed; `SendToBrokerDialog` documented as offline basket tracker. *Residual batch reference discovered in State Matrix.* |
| 2 | Inverted Tastytrade price sign | **Resolved** | Plan line 77 reflects `price = -abs(limit)` for BUY/debit and `price = abs(limit)` for SELL/credit (`tastytrade_paper.py:128-132`). |
| 3 | Tradier endpoint & side mappings | **Resolved** | Target endpoint `POST .../accounts/{account_id}/orders`, 4-way `_EQUITY_SIDE`/`_OPTION_SIDE`, and rate-limit governor admit check verified against `tradier_paper.py:32, 60, 98-105`. |
| 4 | IBKR conid & payload contract | **Partially Resolved** | Pre-resolved conid contract verified. However, payload dictionary keys (`conidex`/`secType` vs `conid`/`ticker`) and confirmation question exception handling (`OrderAdmissionRefusedError` vs `HTTPException(502)`) remain inaccurate. |
| 5 | `premium_cap_basis` mechanics | **Resolved** | Verified against `portfolio_risk.py:51-86`: `max(mid, limit_price)` for LMT and `ask` / `mid + spread/2` for MKT. |
| 6 | Exposure holds vs sector caps | **Resolved** | Hallucinated sector caps removed; replaced with `lock_exposure`, `load_holds`, `capacity_positions`, `_uncovered_notional`, and `_release_open_risk` (`portfolio_exposure.py`). |
| 7 | Attempt states preparing/dispatching | **Resolved** | Verified lowercase states `preparing` $\to$ `dispatching` $\to$ `submitted` $\lor$ `filled` $\lor$ `outcome-unknown` $\lor$ `proven-not-submitted` adhering to `_FORWARD` (`broker_attempts.py:32-35`). |
| 8 | Idless option orders | **Resolved** | Trade card direct execution with `attempt_id: null` documented with `_prepare_idless` (`broker_attempts.py:672`), matching against `prepared_order` stamped by `position_writer.py:795`. |
| 9 | Portfolio model schema qty/contract | **Resolved** | `qty = Column(Integer)` and dynamic derivation of `cost_basis` verified against `models/portfolio.py:18`. Symbology format clarified. |
| 10 | Target rung rescaling runner preservation | **Resolved** | Formula `target_sum = min(stored, (total * stored) // asked)` with runner preservation and no-op for `stored >= asked` verified against `position_writer.py:209-229`. |
| 11 | CloseModal closing vs EditDrawer & exit stub | **Resolved** | Closing UI correctly mapped to `CloseModal` in `portfolio/page.tsx`; `_maybe_send_close_to_broker` in `routers/portfolio.py:73-81` documented as an unrouted no-op stub. |
| 12 | 9-state space matrix | **Partially Resolved** | 9-state space matrix added in Section 4. However, persistence handling on 500 errors contradicts the core save-first pattern. |

---

### Adversarial Findings in Round 2 Fixes and Interactions

- **location**: `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md:168` (Section 4 — State Space Verification Matrix, row "Failed / Cancelled", columns "StockSendDialog" and "Trade Card Direct Order")
- **trigger_condition**: Broker returns an HTTP 500 error, network timeout, or connection drop during direct order execution. The matrix claims: *"Broker 422/500 error banner, no position created"*.
- **guard_snippet**:
  ```markdown
  | **Failed / Cancelled** | Broker 422 pre-flight error banner (no position created / saved row deleted via `classifyDirectFailure(verdict='delete')`); Broker 500 / network failure retains saved position with `ORDER-UNKNOWN` note (`verdict='keep'`). | Broker 422 pre-flight error banner (saved row deleted via `classifyDirectFailure(verdict='delete')`); Broker 500 / network failure retains saved position with `ORDER-UNKNOWN` note (`verdict='keep'`). | ...
  ```
- **potential_consequence**: In both `frontend/lib/directOrder.ts:8-12, 85-100` and `frontend/lib/stockDirectSend.ts:6-18, 38-46`, Bamendjou implements the strict save-first persistence invariant: a position is saved to the portfolio *before* order dispatch. Pre-flight refusals (422, unauthenticated credentials) provably never reached the broker and delete the row (`verdict: 'delete'`). However, on 500 errors or unknown failures, the position is intentionally **retained** with an `ORDER-UNKNOWN` note (`verdict: 'keep'`) to prevent untracked live broker positions. Asserting "no position created" on 500 errors directly violates this persistence invariant and causes the test harness to enforce unsafe state rollbacks.

- **location**: `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md:70` (Section 3 — Task 1: IBKR Paper Order Ticket Payload)
- **trigger_condition**: Test harness verifies the payload dictionary built by `backend/app/data/ibkr_paper.py:_build_payload`. The plan specifies: `{"orders": [{"conid": ..., "orderType": ..., "price": ..., "side": ..., "ticker": ..., "tif": ..., "quantity": ...}]}`.
- **guard_snippet**:
  ```markdown
  - Order ticket payload: verify `_build_payload` transmits `{"orders": [{"orderType": ..., "side": ..., "quantity": ..., "tif": ..., ("price": ...), ("conidex": str(conid), "secType": f"{conid}:{sec_type}") | ("symbol": symbol, "secType": sec_type)}]}` matching IBKR Client Portal API specifications.
  ```
- **potential_consequence**: `ibkr_paper.py:120-134` constructs order tickets where pre-resolved conids are passed via `"conidex": str(order.conid)` and `"secType": f"{order.conid}:{order.sec_type}"`, omitting `"symbol"` and never using keys named `"conid"` or `"ticker"`. If `verify_broker_payloads.py` asserts against `"conid"` or `"ticker"`, it will fail against the actual adapter.

- **location**: `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md:71` (Section 3 — Task 1: IBKR Confirmation Questions)
- **trigger_condition**: IBKR answers an order submission with an order-reply confirmation question (`awaiting_confirmation=True`). The plan states: *"verify `_confirmation_question` intercepts IBKR price/size questions and raises `OrderAdmissionRefusedError`"*.
- **guard_snippet**:
  ```markdown
  - Order confirmation questions: verify `_confirmation_question` (`routers/broker.py:299`) extracts the question text from `result.message` when `result.awaiting_confirmation is True`, and `_raise_if_awaiting_confirmation` (`routers/broker.py:315`) raises `HTTPException(status_code=502)` (not `OrderAdmissionRefusedError`), recording the attempt as `proven-not-submitted`.
  ```
- **potential_consequence**: `_confirmation_question` is a pure helper returning `str | None`. The exception raised by `_raise_if_awaiting_confirmation` is an `HTTPException(status_code=502, detail="IBKR did not place the order: ...")`. `OrderAdmissionRefusedError` is an adapter-level pre-transmission error (e.g., Tradier rate governor) and is never raised on this path. Verification scripts expecting `OrderAdmissionRefusedError` will fail.

- **location**: `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md:165` (Section 4 — State Space Verification Matrix, row "Expanded / Nested", column "Broker Attempts Service")
- **trigger_condition**: Verification of `BrokerAttemptService` under "Expanded / Nested" state. The matrix specifies: *"Batch payload details unpacked"*.
- **guard_snippet**:
  ```markdown
  | **Expanded / Nested** | ... | ... | Multiple basket items expanded | In-flight attempt payload canonical inspection (single-order payload only; no batch orders) | ... |
  ```
- **potential_consequence**: `BrokerAttemptService` in `backend/app/services/broker_attempts.py` persists single canonical payloads (`payload_canonical`) exclusively. It contains no batch processing or batch payload unpacking logic. This is an unremoved residual from Round 1's hallucinated batch endpoint.

- **location**: `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md:127` (Section 3 — Task 4: Position Creation & Schema Integrity)
- **trigger_condition**: Verification of contract identifier format stored in `PortfolioPositionModel.contract`. The plan specifies: *"canonical OCC representation `{symbol}|{strike}|{expiry}|{right}` stored in `contract = Column(String)`"*.
- **guard_snippet**:
  ```markdown
  - Contract string: internal composite key `{symbol}|{strike}|{expiry}|{right}` (for options) or `{symbol}|STOCK` (for equities) stored in `contract = Column(String)`, distinct from the 21-character OCC option symbol (`option_symbol` in broker payloads).
  ```
- **potential_consequence**: `{symbol}|{strike}|{expiry}|{right}` is the application's internal pipe-delimited composite key generated by `contractId(...)`, whereas canonical OCC symbology is `{symbol}{YYMMDD}{C/P}{strike_padded}` (used in `req.option_symbol`). Calling the pipe string "canonical OCC representation" conflates the internal database identifier with the broker-facing OCC format.

---

### Audit Gate Conclusion

- **Total gate findings in Round 2 fixes/interactions:** 5 (3 persistence & state invariant defects, 2 contract & schema key defects)
- **Plan stage verdict:** **not clean**