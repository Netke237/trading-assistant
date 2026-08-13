# Implementation Plan — Explicit Open/Close Order Semantics (Stock + Options)

Status: DRAFT — pending adversarial review before implementation.

## 1. Problem

`BrokerOrder.action` is `'BUY' | 'SELL'` with no separate signal for whether the order is meant
to **open** a new position or **close** an existing one. Two adapters currently guess, and they
guess differently for the same input:

- `backend/app/data/tradier_paper.py:23` — for options, `SELL` always means `sell_to_open`
  (comment: "the screener always opens a new position").
- `backend/app/data/tastytrade_paper.py:44-49` — for **both** stock and options, `SELL` always
  means `SELL_TO_CLOSE`.

Confirmed live (not just latent) impact: bearish stock entries send `action: 'SELL'` to *open* a
short (`StockPositionCard/index.tsx:189`, `StockSendDialog/index.tsx:101`,
`step-7-position-card/page.tsx:92`, all `direction === 'Bullish' ? 'BUY' : 'SELL'`). Tastytrade is
a selectable broker for these (`'tastytrade_paper'` in both dialogs' broker lists). Routing a
bearish stock trade through Tastytrade today either errors (no existing long to close) or, worse,
closes an unrelated real long position in that symbol if the user happens to hold one.

Confirmed latent (currently unreachable but a landmine): the options entry flow
(`step-7-trade-card/page.tsx:491,524`) hardcodes `action: 'BUY'` always — this app never sells an
option to open (no covered calls / cash-secured puts / credit-spread execution exists;
`trade_plan.py:53` confirms bullish↔call, bearish↔put, always bought). `ClosePositionDrawer`'s
"send to broker" checkbox is explicitly disabled ("coming soon"), so no live path sends `SELL`
for an option today. But the two adapters disagree on what that `SELL` *would* mean the moment
that checkbox is turned on, and nothing today would catch the mismatch.

**Decision (from user):** `SELL` means **close**, for both stock and options, everywhere.
Opening a short is a distinct intent from closing a long and must be represented as such — not
inferred from `action` alone.

## 2. Design

Add an explicit second field alongside `action`, matching the vocabulary the two most particular
brokers (Tradier options, Tastytrade both) already use natively:

```python
Effect = Literal["OPEN", "CLOSE"]
```

New `BrokerOrder.effect: Effect` (required, no default — every call site must state its intent
explicitly; a silent default is exactly the bug we're removing).

Combinations and what they mean:

| action | effect | Real-world meaning | Existing call sites (today) |
|---|---|---|---|
| BUY | OPEN | Buy to open (long entry) | Bullish stock entry, all options entries (calls + puts) |
| SELL | OPEN | Sell to open (short entry) | Bearish stock entry |
| SELL | CLOSE | Sell to close (exit a long) | Closing a long stock or long option (not yet wired to broker) |
| BUY | CLOSE | Buy to close (cover a short) | Closing a short stock position (not yet wired to broker) |

### 2.1 Per-adapter mapping

- **Tradier options** (`tradier_paper.py`) — already has open/close vocabulary, just needs the
  close half turned on and keyed by `effect` instead of assumed:
  ```python
  _OPTION_SIDE = {
      ("BUY",  "OPEN"):  "buy_to_open",
      ("SELL", "OPEN"):  "sell_to_open",
      ("SELL", "CLOSE"): "sell_to_close",
      ("BUY",  "CLOSE"): "buy_to_close",
  }
  ```
- **Tradier stock** — no change. Tradier's equity API takes plain `buy`/`sell` with no
  open/close qualifier; it infers short-vs-cover from account state itself. Confirmed still
  correct under the new model: `side = order.action.lower()` regardless of `effect`.
- **Tastytrade stock + options** (`tastytrade_paper.py`) — replace the 2-entry map with the full
  4-way one already described in the file's own comment as "known, accepted limitation — not
  fixed in this task" (this task fixes it):
  ```python
  _ACTION_MAP = {
      ("BUY",  "OPEN",  "STK"): OrderAction.BUY_TO_OPEN,
      ("SELL", "OPEN",  "STK"): OrderAction.SELL_TO_OPEN,
      ("SELL", "CLOSE", "STK"): OrderAction.SELL_TO_CLOSE,
      ("BUY",  "CLOSE", "STK"): OrderAction.BUY_TO_CLOSE,
      ("BUY",  "OPEN",  "OPT"): OrderAction.BUY_TO_OPEN,
      ("SELL", "OPEN",  "OPT"): OrderAction.SELL_TO_OPEN,
      ("SELL", "CLOSE", "OPT"): OrderAction.SELL_TO_CLOSE,
      ("BUY",  "CLOSE", "OPT"): OrderAction.BUY_TO_CLOSE,
  }
  ```
  Keyed on `(order.action, order.effect, order.sec_type)`.
- **IBKR** (`ibkr_paper.py`) and **Alpaca** (`alpaca_paper_execution.py`) — no change. Both send
  plain `side: BUY/SELL` and the broker's own engine infers open-vs-close from current account
  position (standard behavior for both platforms' retail APIs). `effect` is accepted on
  `BrokerOrder` for interface consistency but intentionally unused by these two adapters — add a
  one-line comment at each `_build_payload`/`_build_params` saying so explicitly, so a future
  reader doesn't assume it's an oversight.

### 2.2 API surface changes

- `backend/app/data/ibkr_paper.py` — `BrokerOrder` dataclass gains `effect: Effect` (shared
  dataclass reused by every adapter's type import).
- `backend/app/routers/broker.py` — `StockOrderRequest` / `OptionOrderRequest` gain
  `effect: Literal["OPEN", "CLOSE"]` (required field, no default).
- `backend/app/routers/auto_trade.py` — `ArmRequest` gains `effect: Literal["OPEN", "CLOSE"]`.
  In practice auto-trade is entry-only today (`option_symbol` required, no existing-position
  lookup anywhere in `auto_trader.py`), so every caller sets `"OPEN"` — but the field is still
  required rather than defaulted, consistent with the rest of the design, and it documents the
  current entry-only constraint explicitly instead of leaving it implicit.
- `frontend/lib/api.ts` — `postStockOrder`/`postOptionOrder`/auto-trade arm request types gain
  `effect: 'OPEN' | 'CLOSE'`.

### 2.3 Frontend call-site changes

**Entry flows (effect: 'OPEN'):**
- `frontend/components/organisms/StockPositionCard/index.tsx:189`
- `frontend/components/organisms/StockSendDialog/index.tsx:101`
- `frontend/app/(frame)/screener/step-7-position-card/page.tsx:92`
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:491,524`
- `frontend/components/organisms/StockAutoTradeArm/index.tsx` (wherever it calls the arm
  endpoint) — always `effect: 'OPEN'`, `action: 'BUY'` (auto-trade only ever buys options today).

All of the above already compute the correct `action` (BUY for bullish/long entries, SELL for
bearish/short stock entries) — they just need `effect: 'OPEN'` added alongside.

**Close flow — data model fix now, broker wiring stays deferred:**
`ClosePositionDrawer` is explicitly out of live broker execution ("coming soon"), and this plan
does not turn that on — that's a separate feature decision. But its *local* P&L math has two bugs
this plan should fix at the same time, because both are part of the same "we don't correctly
model short vs. long" gap, and leaving them for a follow-up risks the same landmine recurring:

1. **Round-1 finding (already filed as #2 in CODE_REVIEW_FINDINGS.md):** hardcodes `* 100`
   unconditionally — wrong for stock positions (`contract` ending `|STOCK'`). Fix: use the same
   `contract.endsWith('|STOCK') ? 1 : 100` multiplier every other P&L calc in the app already
   uses (`frontend/lib/risk.ts:31` is the canonical helper — reuse it instead of re-deriving).
2. **New, found while scoping this plan:** `realizedDollar = (exitPrice - entryPrice) * mult * qty`
   assumes a long position (profit when price rises). For a short position, P&L is inverted —
   profit when price *falls*: `(entryPrice - exitPrice) * mult * qty`. `ClosePositionDrawer`
   currently has no access to `position.direction` in its P&L formula at all. Fix: branch on
   `position.direction === 'Bearish' ? (entryPrice - exitPrice) : (exitPrice - entryPrice)`.

This requires `PortfolioPosition.direction` to be trustworthy, which is round-1 finding #3
(`buildPaperStockPosition` hardcodes `'Bullish'`) — fixed as part of this same plan since it's a
direct dependency:

- `frontend/lib/paperTrade.ts:19-29` — `buildPaperStockPosition()` gains a required `direction:
  Direction` parameter, sets `direction: direction` instead of the hardcoded literal.
- All 4 call sites (`step-4-stocks/page.tsx:167`, `ChartWorkspace/index.tsx:848`,
  `StockSendDialog/index.tsx:91,113`, `StockPositionCard/index.tsx:209`) pass the real direction
  they already have in scope (`c.direction` / `card.direction`) — none of them need new data,
  just to stop dropping the field they already have.

### 2.4 Known out-of-scope items (flagging, not fixing here)

- Multi-leg spread execution (`OptionLeg.action` in `scan.py`/`TradeCard.legs`) is display-only
  today — `SendToBrokerDialog` renders spread legs for information but never submits a multi-leg
  order; the actual submit path (`placeLimitPaper` et al.) is always single-leg. Not touched by
  this plan; noting it so the adversarial reviewer doesn't flag it as a missed call site.
- Turning on `ClosePositionDrawer`'s "send to broker" checkbox is a separate feature; this plan
  only makes sure the data model (`effect`, direction-aware P&L) will be correct the day someone
  does turn it on.
- Existing already-open positions in a user's local DB that are short stock but persisted with
  `direction: 'Bullish'` (a real possibility if this bug has been live) are **not** retroactively
  corrected by this plan — there's no reliable signal in `PortfolioPositionModel` to distinguish
  "actually bullish" from "mislabeled short" after the fact. Flagged as a manual data-reconciliation
  note for the user, not an automated migration.

## 3. Test plan

- **Backend, per adapter** (`backend/tests/test_broker_router.py` or a new
  `test_broker_adapters.py`): for `tradier_paper` and `tastytrade_paper`, assert all 4
  `(action, effect)` combinations produce the correct wire-level side/action string, for both
  `STK` and `OPT` where applicable. For `ibkr_paper` and `alpaca_paper`, assert `effect` is
  accepted but doesn't change the payload (documents the "auto-inferred" behavior as intentional,
  not untested).
- **Backend, schema validation**: `StockOrderRequest`/`OptionOrderRequest`/`ArmRequest` reject a
  request missing `effect` (no default → 422).
- **Backend, routing**: extend `test_broker_router.py`'s existing SELL-against-`ibkr_paper` cases
  to also cover SELL+OPEN and SELL+CLOSE against `tradier_paper` and `tastytrade_paper`
  specifically, since that's the exact gap that let this bug ship untested.
- **Frontend, `paperTrade.test.ts`**: `buildPaperStockPosition('AAPL', 150, 10, 'Bearish', ...)`
  produces `direction: 'Bearish'`.
- **Frontend, new `ClosePositionDrawer.test.tsx`**: four cases — long stock, short stock, long
  option (existing behavior, unchanged), and confirm the multiplier/sign combination for each
  against a hand-computed expected P&L.
- **Frontend, call-site smoke check**: for each of the 4 entry call sites, confirm the outgoing
  request body includes `effect: 'OPEN'` (can be a light assertion in existing tests for those
  components rather than new test files, where such tests already exist).

## 4. Sequencing

1. Backend: add `Effect` type + `BrokerOrder.effect` field, update all 4 adapters, update
   `broker.py`/`auto_trade.py` schemas. Backend tests green.
2. Frontend: `api.ts` type changes, wire `effect: 'OPEN'` through the 5 entry call sites, fix
   `buildPaperStockPosition` direction param + its 4 call sites, fix `ClosePositionDrawer`'s
   multiplier + direction-aware sign. Frontend tests green.
3. `npm run typecheck` clean, full `pytest` + `npm run test` green.
4. Update `CODE_REVIEW_FINDINGS.md` to mark findings #2, #3, and #15 as fixed (do not delete —
   keep as a record).

## 5. Open questions for review

- Is `effect` the right field name, or would `intent`/`position_effect` read clearer against the
  rest of this codebase's naming? (Non-blocking, easy to rename.)
- Should `ArmRequest.effect` really be a free field the caller sets, given auto-trade is
  structurally entry-only today — or should the router just hardcode `effect="OPEN"` server-side
  and drop it from the request body entirely, so there's no way to call the endpoint wrong?
- Confirm assumption: Tradier and IBKR equity APIs really do support opening a short via plain
  `sell` with no existing position (not verified against live sandbox behavior in this pass —
  based on adapter comments and standard retail-brokerage conventions, not an actual sandbox call).
