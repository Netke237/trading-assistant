# Adversarial Audit Round 3 Report — Plan Stage: `APP-AUDIT-BROKER-PORTFOLIO`

**Target Diff:** `git -C .worktrees/app-audit-broker-portfolio-c4b17ff3 diff 30e88233..ed5c1529`  
**Plan Document:** `.worktrees/app-audit-broker-portfolio-c4b17ff3/docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md`  
**Reviewer:** Independent Adversarial Reviewer (Round 3)  
**Methodology:** `.claude/skills/bmad-review-adversarial-general/SKILL.md` evaluated against the numeric and persistence gate defined in `docs/superpowers/PROJECT_STATE.json` (`audit_rule`).

---

## 1. Scope & Objective

Round 3 reviews the exact diff of fixes applied in commit `ed5c1529` to resolve the 5 Round 2 findings, as well as their interactions with existing plan assertions and real codebase mechanisms across:
- `backend/app/routers/broker.py`
- `backend/app/data/ibkr_paper.py`
- `frontend/lib/directOrder.ts`
- `frontend/lib/stockDirectSend.ts`
- `backend/app/models/portfolio.py`

---

## 2. Verification of Round 2 Fixes Against the Codebase

### Item 1: State Matrix Failed/Cancelled Row & Save-First Pattern
- **Round 2 Defect:** The state matrix asserted "no position created" on 500 errors, contradicting the save-first pattern where 500/unknown retains the pre-saved position with an `ORDER-UNKNOWN` note (`verdict='keep'`) while 422 deletes it (`verdict='delete'`).
- **Diff Resolution (`lines 41-42, 168`):**
  - Section 2 (Surface Inventory Table): Explicitly states that `StockSendDialog` saves position first via `stockDirectSend.ts`, and `Trade Card Direct Order` saves position first via `directOrder.ts`.
  - Section 4 (State Matrix `Failed / Cancelled` row): Clarified for both dialogs that Broker 422 pre-flight error banners delete the pre-saved row via `classifyDirectFailure(verdict='delete')`, while Broker 500 / network failures retain the pre-saved position with an `ORDER-UNKNOWN` note (`verdict='keep'`).
- **Codebase Verification:**
  - `frontend/lib/directOrder.ts:90-112`: `classifyDirectFailure` classifies status 422 as `preSubmit` returning `{ verdict: 'delete', why }`, while unhandled 5xx / connection drops return `{ verdict: 'keep', why, orderId: null }`.
  - `frontend/lib/stockDirectSend.ts:163-250`: Confirmed position is persisted before order dispatch; `outcome.verdict === 'delete'` deletes the tracked row via `removeTrackedRow(recId, true)`, while `outcome.verdict === 'keep'` executes `keepRow()` adding an `order-unknown` note and retaining the row.
  - `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:1215-1315`: Mirror save-first execution path for single-contract option direct sends.
- **Verdict:** Fully resolved. Accurately describes the persistence and deletion lifecycle.

### Item 2: IBKR Order Ticket Payload Keys
- **Round 2 Defect:** The plan asserted incorrect payload keys (`"conid"`, `"ticker"`), which do not exist in IBKR Client Portal API order submission.
- **Diff Resolution (`line 70`):**
  - Section 3, Task 1: Updated payload specification to verify `_build_payload` transmits:
    `{"orders": [{"orderType": order.order_type, "side": order.action, "quantity": order.quantity, "tif": order.tif, ("price": order.limit_price), ("conidex": str(order.conid), "secType": f"{order.conid}:{order.sec_type}") | ("symbol": order.symbol, "secType": order.sec_type)}]}`
- **Codebase Verification:**
  - `backend/app/data/ibkr_paper.py:117-134`:
    ```python
    o: dict = {
        "orderType": order.order_type,
        "side": order.action,
        "quantity": order.quantity,
        "tif": order.tif,
    }
    if order.order_type == "LMT" and order.limit_price is not None:
        o["price"] = order.limit_price
    if order.conid:
        o["conidex"] = str(order.conid)
        o["secType"] = f"{order.conid}:{order.sec_type}"
    else:
        o["symbol"] = order.symbol
        o["secType"] = order.sec_type
    return {"orders": [o]}
    ```
- **Verdict:** Fully resolved. The assertion matches the exact dictionary structure constructed by `ibkr_paper.py`.

### Item 3: IBKR Confirmation Questions Exception & Attempt Recording
- **Round 2 Defect:** Asserted that `_confirmation_question` raises `OrderAdmissionRefusedError`, whereas the real mechanism in `routers/broker.py` raises `HTTPException(status_code=502)`.
- **Diff Resolution (`line 71`):**
  - Section 3, Task 1: Updated to state that `_confirmation_question` (`routers/broker.py:299`) extracts the question text from `result.message` when `result.awaiting_confirmation is True`, and `_raise_if_awaiting_confirmation` (`routers/broker.py:315`) raises `HTTPException(status_code=502)` (not `OrderAdmissionRefusedError`), recording the attempt as `proven-not-submitted`.
- **Codebase Verification:**
  - `backend/app/routers/broker.py:299-332`: `_confirmation_question` extracts question text when `getattr(result, "awaiting_confirmation", False) is True`. `_raise_if_awaiting_confirmation` logs `broker_order_failed` and raises `HTTPException(status_code=502, detail="IBKR did not place the order: it asked for a confirmation this app does not send. IBKR said: ...")`.
  - `backend/app/routers/broker.py:650-668`: `except HTTPException as exc:` catches this 502, calls `await _record_attempt(service, claim, "proven-not-submitted", holder["status"], holder["body"])`.
  - `frontend/lib/directOrder.ts:98`: `status === 502 && d.startsWith('IBKR did not place the order:')` is caught by `preSubmit`, returning `{ verdict: 'delete', why }` so the pre-saved row is cleanly removed.
- **Verdict:** Fully resolved. Both the raised exception and the resulting attempt state machine transition are verified against backend and frontend handlers.

### Item 4: Removal of Residual Batch Order Mention
- **Round 2 Defect:** State matrix contained a residual mention of unpacking batch payload details (`"Batch payload details unpacked"`), implying batch broker orders.
- **Diff Resolution (`line 165`):**
  - Section 4 (State Matrix `Expanded / Nested` row, `Broker Attempts Service` column): Updated from `"Batch payload details unpacked"` to `"In-flight attempt payload canonical inspection (single-order payload only; no batch orders)"`.
- **Codebase Verification:**
  - `backend/app/routers/broker.py:613-640` and `backend/app/services/broker_attempts.py`: Every attempt is claimed and tracked individually for a single `BrokerOrder`. No batch order submission endpoints or attempt records exist.
- **Verdict:** Fully resolved. Residual eliminated and single-order contract explicitly affirmed.

### Item 5: Internal Composite Key vs 21-Character OCC Option Symbol
- **Round 2 Defect:** Contract string was referred to as "canonical OCC representation", which was inaccurate since OCC option symbols are 21-character strings without delimiters (e.g. `AAPL250516C00185000`), whereas `portfolio_positions.contract` stores pipe-delimited composite keys.
- **Diff Resolution (`line 124`):**
  - Section 3, Task 4: Clarified to: `internal composite key {symbol}|{strike}|{expiry}|{right} (for options) or {symbol}|STOCK (for equities) stored in contract = Column(String), distinct from the 21-character OCC option symbol (option_symbol in broker payloads)`.
- **Codebase Verification:**
  - `backend/app/models/portfolio.py:15`: `contract = Column(String, nullable=False, unique=True, index=True)`.
  - `backend/app/services/position_writer.py:235, 341, 815`: Validates and checks uniqueness on `body.contract` formatted as `{symbol}|STOCK` or `{symbol}|{strike}|{expiry}|{right}`.
  - `backend/app/routers/broker.py:414-438`: `_canonical_order` sets `instrument = req.option_symbol` (21-char OCC symbol) for options and `{symbol}|STOCK` for equities.
- **Verdict:** Fully resolved. The distinction between the internal composite key in `portfolio_positions` and the 21-character OCC string in broker orders is rigorously established.

---

## 3. Interaction and Regression Analysis

A re-check of the complete diff and surrounding context in `docs/superpowers/plans/2026-10-21-app-audit-broker-portfolio-plan.md` shows:
1. No contradictions were introduced between Section 2 (Surface Inventory), Section 3 (Audit Scope), and Section 4 (State Matrix).
2. The numeric and persistence gate standards are preserved:
   - Derivation of `cost_basis` and current position valuation ($\text{entry\_price} \times \text{qty} \times \text{multiplier}$) remains intact.
   - Weighted average price and ladder rescaling formulas in Task 4 remain mathematically sound.
   - Idempotency, zero-redispatch invariants, and deduplication behavior in Task 3 remain intact.
3. No new gate-level defects or mechanism misstatements were introduced.

---

## 4. Audit Findings

Zero gate-level findings in the reviewed diff and its interactions.

---

## 5. Conclusion

- **Total gate findings in Round 3 fixes/interactions:** 0
- **Plan stage verdict:** clean