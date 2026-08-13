# Implementation Plan — Explicit Open/Close Order Semantics (Stock + Options)

Status: IMPLEMENTED, including a post-implementation adversarial audit and its one real finding.
Backend and frontend changes complete; full backend suite (1408 passed), frontend typecheck, and
full frontend suite (519 passed) all green. One additional correctness issue was caught during
implementation itself (not by any of the 3 pre-implementation review rounds) and fixed on the
spot — see the note inline in §2.3: the P&L sign-flip must only apply to short *stock* positions,
not to bearish *options* (a bought put is still long the contract, not short — this app never
writes/sells options). CODE_REVIEW_FINDINGS.md findings #2, #3, and #15 are marked fixed.

**Post-implementation audit (separate from the 3 plan-review rounds — this one reviewed the actual
diff, not the plan):** found no live bugs in the shipped code. It did find and prove, via mutation
testing, that this plan's own §3 requirement for router-level SELL/CLOSE regression tests
(`test_broker_router.py`) had not actually been implemented — the schema-validation tests only
checked for a *missing* `effect` field, not that a *present* value was correctly propagated from
the HTTP request into `BrokerOrder`. The auditor mutated `broker.py` to silently hardcode
`effect="OPEN"` and the full 1408-test backend suite still passed. Fixed: added
`test_stock_order_propagates_close_effect_to_broker_order`,
`test_stock_order_propagates_open_effect_to_broker_order`,
`test_option_order_propagates_close_effect_to_broker_order` (mock-adapter tests through the real
FastAPI route), plus the plan's other previously-unmet §3 item —
`test_ibkr_payload_unaffected_by_effect`/`test_alpaca_payload_unaffected_by_effect`. Independently
re-verified the exact same mutation is now caught (test fails as expected), then confirmed the
file was restored and the full suite is green.

Below is the plan as executed, retained for reference. Status: REVISED after 3 rounds of
adversarial review. Round 1: 13 issues (3 at severity 5). Round
2: verified round 1's fixes against real code, found 3 more (1 at severity 4 — the Tradier-stock
"no change" claim was factually wrong per Tradier's own API docs). Round 3: verified round 2's
fixes, found 3 more mechanical implementation-blocking gaps (max severity 3, all "fails loudly at
implementation time" rather than "ships a silent bug" per round 3's own assessment) — a
dataclass field-ordering hazard, a missing propagation step in `broker.py`'s handlers, and a
non-exported helper the plan told the implementer to reuse. All 19 total findings across 3 rounds
are addressed below; see §6 for the full log. Ready for implementation.

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
- **Tradier stock — REVISED after round 2 review, this is NOT "no change."** The original draft
  claimed Tradier's equity API auto-infers short-vs-cover from plain `buy`/`sell`. Round 2 review
  checked this against Tradier's actual API documentation and found it false: Tradier's equity
  `side` parameter has **four** explicit values — `buy`, `sell`, `sell_short`, `buy_to_cover` —
  paralleling the options vocabulary exactly, with no auto-inference. This codebase's adapter
  currently sends plain `order.action.lower()` for stock (`tradier_paper.py:70`), so a bearish
  stock entry today sends `"sell"` — which per Tradier's real API is the *close-a-long* side, not
  *open-a-short*. This is live and reachable (`'tradier_paper'` is a selectable broker for stock
  orders in `StockSendDialog`/`StockPositionCard`), so leaving it as "no change" would ship this
  plan without actually fixing Tradier for stock — directly against the plan's own stated goal.
  Fix: give Tradier stock the same 4-way treatment as its options side:
  ```python
  _EQUITY_SIDE = {
      ("BUY",  "OPEN"):  "buy",
      ("SELL", "OPEN"):  "sell_short",
      ("SELL", "CLOSE"): "sell",
      ("BUY",  "CLOSE"): "buy_to_cover",
  }
  ```
  **Behavior change, not just a field addition:** this changes the wire value for a bearish stock
  entry from `"sell"` to `"sell_short"` — that's the actual bug fix, not incidental. The existing
  test `test_adapter_builds_equity_params` (`test_tradier_paper.py:11-23`) only covers BUY and is
  unaffected; there is currently no existing test asserting stock SELL's wire value, so nothing
  existing needs its assertion changed — but new tests must cover all 4 stock combinations,
  including confirming `sell_short` (not `sell`) for the opening-short case, since that's precisely
  the behavior this plan is here to correct. **Residual caveat (round 3):** `sell_short` generally
  requires a margin-enabled brokerage account and Tradier may reject it for a cash account or a
  hard-to-borrow symbol — this plan does not add any pre-flight check for that (mirrors how the
  plan already accepts, rather than pre-validates, other broker-side rejections per §2.4's
  "acceptable for now, nothing in live UI can trigger it yet" reasoning — except this one *is*
  live-reachable, so a Tradier-side rejection here should surface as a clear error message to the
  user, not the generic truncated-fault-text 502 described in §2.4; worth a follow-up, not a
  blocker for this plan).
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
  Keyed on `(order.action, order.effect, order.sec_type)`. **Note:** `(SELL, OPEN, OPT)` —
  writing/shorting an option — is added to the map for completeness but stays unreachable dead
  code after this plan ships (see §2.4); do not read its presence as "selling to open an option is
  now supported."
- **Consuming lookup lines must change shape too (round 2 review flagged this as missing from the
  original snippets-only draft):** it's not enough to redefine the maps — the code that *reads*
  them must be updated to match, or every order (open and close alike) breaks, not just close
  orders:
  - `tradier_paper.py:70` — currently `side = order.action.lower()` for equities; becomes
    `side = _EQUITY_SIDE[(order.action, order.effect)]`.
  - `tradier_paper.py`'s option-side lookup — currently `_OPTION_SIDE[order.action]` (single-key);
    becomes `_OPTION_SIDE[(order.action, order.effect)]` (tuple-keyed).
  - `tastytrade_paper.py:57` — currently `_ACTION_MAP.get((order.action, order.sec_type))`
    (2-tuple); becomes `_ACTION_MAP.get((order.action, order.effect, order.sec_type))` (3-tuple).
  These three line changes are as load-bearing as the map redefinitions themselves and must ship
  in the same commit as each map change — the existing test suite will catch a mismatch
  immediately (every BUY/OPEN case would fail, not just SELL/CLOSE), so this is self-correcting
  during implementation, but it's called out explicitly so it isn't discovered by trial and error.
- **IBKR** (`ibkr_paper.py`) and **Alpaca** (`alpaca_paper_execution.py`) — no change. Both send
  plain `side: BUY/SELL` and the broker's own engine infers open-vs-close from current account
  position (standard behavior for both platforms' retail APIs). `effect` is accepted on
  `BrokerOrder` for interface consistency but intentionally unused by these two adapters — add a
  one-line comment at each `_build_payload`/`_build_params` saying so explicitly, so a future
  reader doesn't assume it's an oversight. **Residual risk, not newly introduced by this plan:**
  this "auto-infers short vs. cover" assumption is not verified against live Tradier/IBKR sandbox
  behavior anywhere in this codebase or this review — it's inherited from the adapters' existing
  comments, not confirmed against broker docs. Both are paper-trading endpoints only (virtual
  money), so the blast radius of the assumption being wrong is a confusing paper-order rejection,
  not real financial loss. Flagged for manual verification against Tradier/IBKR API docs before
  this fix is trusted with real money; not blocking for this pass.

### 2.2 API surface changes

**Round 1 review found the "shared dataclass" premise was false — `tradier_paper.py` defines its
own independent `BrokerOrder`, not the one in `ibkr_paper.py`. Every runtime caller happens to
duck-type through `ibkr_paper.BrokerOrder`, but `backend/tests/test_tradier_paper.py` imports and
constructs `tradier_paper.BrokerOrder` directly in 7 places. Both classes must change together.**

- `backend/app/data/ibkr_paper.py` — `BrokerOrder` dataclass gains `effect: Effect` (the one every
  production caller — `broker_router.py`, `routers/broker.py`, `auto_trader.py`,
  `alpaca_paper_execution.py`, `tastytrade_paper.py` — imports and constructs).
- `backend/app/data/tradier_paper.py` — its **separate** `BrokerOrder` dataclass (lines 26-36)
  also gains `effect: Effect`. Keep the two dataclasses' field shape identical (same field names,
  same order) even though they're not literally the same class — anything else is a footgun for
  the next person who assumes they're interchangeable, which is exactly the bug in this repo today.
- `backend/app/routers/broker.py` — `StockOrderRequest` / `OptionOrderRequest` gain
  `effect: Literal["OPEN", "CLOSE"]` (required field, no default). **Round 3 review caught that
  this alone is incomplete:** both route handlers construct `BrokerOrder(...)` directly
  (`place_stock_order` at lines 55-63, `place_option_order` at lines 103-113) and must also gain
  `effect=req.effect` in that construction — the schema change alone doesn't propagate the value,
  it just makes it possible to receive. Omitting this crashes every order with a missing-kwarg
  `TypeError` (loud and immediate, not a silent bug, but a real omission from this checklist).
- **Round 3 review found a dataclass field-ordering hazard, reproduced directly:** both
  `ibkr_paper.BrokerOrder` and `tradier_paper.BrokerOrder` have several trailing fields with
  defaults (`tif: TIF = "DAY"`, `option_symbol: Optional[str] = None`, etc.). Appending
  `effect: Effect` at the end — the natural-looking place to add a new field — raises
  `TypeError: non-default argument 'effect' follows default argument` at import time, since
  `effect` has no default. Fix: insert `effect: Effect` among the existing *non-defaulted* fields,
  immediately after `action` (both dataclasses currently order those as `symbol, action, quantity,
  order_type, limit_price` before the first defaulted field `tif`) — i.e. `symbol, action, effect,
  quantity, order_type, limit_price, tif="DAY", ...`, unchanged after that point.
- `backend/app/routers/auto_trade.py` / `backend/app/services/auto_trader.py` — **no new field.**
  Round 1 review confirmed `AutoTradeService.fire()`/`arm()` have no existing-position lookup
  anywhere and are structurally entry-only (`ArmRequest` requires `option_symbol`, and
  `AutoTradeArm/index.tsx:39` hardcodes `action: 'BUY'` with the comment "long single-leg option
  ... is always buy-to-open"). Resolving the plan's own open question from round 1 in favor of the
  safer option: **hardcode `effect="OPEN"` as a literal inside `execute_option_order()`** when it
  constructs `BrokerOrder` (`auto_trader.py:118-127`), rather than adding a caller-supplied field
  to `ArmRequest`/`ArmedStrategy`. This is deliberately the smaller, safer change — it removes the
  single biggest crash risk round 1 found (a required field on `ArmRequest` with no corresponding
  field on `ArmedStrategy` would 500 every `/auto-trade/arm` call via `ArmedStrategy(**req.model_dump())`
  unpacking an unexpected kwarg) and it means there is no way to call this structurally-entry-only
  endpoint with the wrong effect, because the caller never gets to set it.
- `frontend/lib/api.ts` — `postStockOrder`/`postOptionOrder` request types gain
  `effect: 'OPEN' | 'CLOSE'`. Auto-trade arm's request type is **unchanged** (per above).

### 2.3 Frontend call-site changes

**Entry flows (effect: 'OPEN'):**
- `frontend/components/organisms/StockPositionCard/index.tsx:189`
- `frontend/components/organisms/StockSendDialog/index.tsx:101`
- `frontend/app/(frame)/screener/step-7-position-card/page.tsx:92`
- `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:491,524`

All of the above already compute the correct `action` (BUY for bullish/long entries, SELL for
bearish/short stock entries) — they just need `effect: 'OPEN'` added alongside.

**Correction from round 1 review:** the original draft named `StockAutoTradeArm/index.tsx` as an
auto-trade-arm call site needing `effect`. Verified wrong — that component only calls
`api.addStrategyWatch(...)`, an unrelated strategy-watch feature; it never calls `armAutoTrade`.
The real call site is `frontend/components/organisms/AutoTradeArm/index.tsx:35-44`
(`api.armAutoTrade({..., action: 'BUY', ...})`). Per §2.2's resolution, `effect` is no longer part
of the arm request shape at all, so **this component needs no change** — noting it here only so
the corrected understanding is on record, not as an action item.

**ChartWorkspace's chart-click "buy" popover — the 4th `buildPaperStockPosition` call site the
original draft missed having a real answer for:**
`frontend/components/organisms/ChartWorkspace/index.tsx:848` calls `buildPaperStockPosition(symbol,
price, qty)` from inside a click-to-buy popover. Verified: `clickPopover.kind` is typed as
`'alert' | 'buy'` only (`ChartWorkspace/index.tsx:169`) — there is no "sell"/"short" popover kind
anywhere in this component, so this call site is unconditionally a long entry. Fix: pass
`direction: 'Bullish'` as a literal at this call site (not threaded from anywhere — there's
nothing to thread; a manual chart-click buy is definitionally long). This avoids the new-UI scope
creep round 1 flagged as a risk of making `direction` a naively-required parameter.

**Close flow — data model fix now, broker wiring stays deferred:**
`ClosePositionDrawer` is explicitly out of live broker execution ("coming soon"), and this plan
does not turn that on — that's a separate feature decision. But its *local* P&L math has two bugs
this plan should fix at the same time, because both are part of the same "we don't correctly
model short vs. long" gap, and leaving them for a follow-up risks the same landmine recurring:

1. **Round-1 finding (already filed as #2 in CODE_REVIEW_FINDINGS.md):** hardcodes `* 100`
   unconditionally — wrong for stock positions (`contract` ending `|STOCK'`). Fix: use the same
   `contract.endsWith('|STOCK') ? 1 : 100` multiplier every other P&L calc in the app already
   uses (`frontend/lib/risk.ts:31` is the canonical helper — reuse it instead of re-deriving).
   **Round 3 review caught that this helper, `_multiplier`, is not currently exported** (leading
   underscore, module-private, only used internally by `risk.ts`'s own `totalNotional`/
   `computePortfolioRiskMetrics`) — `ClosePositionDrawer` cannot import it as-is. This plan's fix
   includes adding `export` to that function (and dropping the underscore prefix, or renaming to
   something like `positionMultiplier` for an exported name — implementer's call, either is fine)
   as part of the same change, not a separate follow-up.
2. **New, found while scoping this plan:** both `realizedDollar` AND `realizedPct`
   (`ClosePositionDrawer/index.tsx:34-37`) assume a long position (profit when price rises). For a
   *short stock* position, P&L is inverted — profit when price *falls*. **Round 1 review caught
   that the original draft only patched `realizedDollar`, leaving `realizedPct` unfixed — the
   result would have been an internally contradictory display like "+$500 (-3.2%)" for a
   profitable short close.** Fix: compute a single signed `priceDelta` once, then derive both
   `realizedDollar = priceDelta * mult * qty` and `realizedPct = (priceDelta / entryPrice) * 100`
   from that same `priceDelta` — not two independently-written branches that can drift apart again.
   **Caught during implementation (round 4, self-caught, not by rounds 1-3):** the sign flip must
   NOT apply to `direction === 'Bearish'` unconditionally — it only applies to a short *stock*
   position. A `'Bearish'` **option** position is a bought put (this app never writes/sells
   options to open, per §1's confirmed-latent finding), which is still long the contract and
   profits when its premium rises, exactly like a bought call. Flipping the sign for a bearish
   option would have silently inverted P&L for every put position in the portfolio. Correct
   formula: `isShortStock = position.direction === 'Bearish' && position.contract.endsWith('|STOCK')`,
   then `priceDelta = isShortStock ? (entryPrice - exitPrice) : (exitPrice - entryPrice)`.

This requires `PortfolioPosition.direction` to be trustworthy, which is round-1 finding #3
(`buildPaperStockPosition` hardcodes `'Bullish'`) — fixed as part of this same plan since it's a
direct dependency:

- `frontend/lib/paperTrade.ts:19-29` — `buildPaperStockPosition()` gains a required `direction:
  Direction` parameter, sets `direction: direction` instead of the hardcoded literal.
- 3 of its 4 call sites (`step-4-stocks/page.tsx:167`, `StockSendDialog/index.tsx:91,113`,
  `StockPositionCard/index.tsx:209`) pass the real direction they already have in scope
  (`c.direction` / `card.direction`) — no new data needed, just stop dropping the field they
  already have. The 4th call site, `ChartWorkspace/index.tsx:848`, has no direction in scope by
  design (see §2.3) and passes the literal `'Bullish'` instead.
- **Also confirm and fix:** `frontend/lib/paperTrade.test.ts:5` calls
  `buildPaperStockPosition('AAPL', 150, 10)` with no direction — this existing test breaks once
  `direction` becomes a required parameter and must be updated in the same change (round 1 flagged
  this as missing from the original draft).
- **Residual gap, found in round 2 review, not fixed by this plan:** `direction` is only
  *statically* trustworthy after the fix above — not at runtime end-to-end. Backend
  `PortfolioPositionCreate.direction` / `PortfolioPositionSchema.direction`
  (`backend/app/schemas/__init__.py:592,627`) are plain unconstrained `str`, not
  `Literal["Bullish","Bearish"]`, and `frontend/lib/portfolioStore.ts:43` does an unchecked
  `p.direction as Direction` cast when hydrating from the backend. So the new
  `direction === 'Bearish'` ternary in `ClosePositionDrawer` will silently take the *long* branch
  for any value that isn't the exact string `'Bearish'` — not just a mislabeled-but-valid value
  (§2.4's existing note) but also `undefined`, `''`, or a typo, with no validation catching it.
  Blast radius today is display-only (broker-send stays disabled), so not blocking, but tightening
  the backend schemas to `Literal["Bullish","Bearish"]` would be a natural, small follow-up — not
  included in this plan's scope since it's a pre-existing gap this plan doesn't worsen, only fails
  to close.

### 2.4 Known out-of-scope items (flagging, not fixing here)

- Multi-leg spread execution (`OptionLeg.action` in `scan.py`/`TradeCard.legs`) is display-only
  today — `SendToBrokerDialog` renders spread legs for information but never submits a multi-leg
  order; the actual submit path (`placeLimitPaper` et al.) is always single-leg. Confirmed by
  round 1 review (independently re-checked, no `postOptionOrder`/`BrokerOrder` call found in
  `SendToBrokerDialog`). Not touched by this plan.
- Turning on `ClosePositionDrawer`'s "send to broker" checkbox is a separate feature; this plan
  only makes sure the data model (`effect`, direction-aware P&L) will be correct the day someone
  does turn it on. **Because that checkbox stays disabled, `(SELL, CLOSE)` and `(BUY, CLOSE)` are
  not reachable from any live UI after this plan ships either** — only reachable via a direct API
  call or the new tests in §3. Round 1 review asked what happens when a broker rejects a
  sell_to_close/buy_to_close because no matching position exists: today that flows through the
  adapter's generic `RuntimeError` → router's flat 502 with the broker's raw truncated response
  text (`tradier_paper.py:106-109`, `broker.py:72-77,122-127`) — acceptable for now precisely
  because nothing in the live UI can trigger it yet, but **must be revisited with real
  error-message handling when the exit-to-broker feature is actually built**, not assumed solved
  by this plan.
- `(SELL, OPEN, OPT)` in the new Tastytrade mapping (writing/shorting an option) is added for
  mapping completeness but stays unreachable dead code — every current options entry path
  hardcodes `action: 'BUY'` (`step-7-trade-card/page.tsx:491,524`, `AutoTradeArm/index.tsx:39`).
  If it ever becomes reachable, note that nothing in `auto_trader.py`/`portfolio_risk.py` models
  margin/buying-power requirements for a naked short option — only premium-at-risk sizing exists
  today. Not this plan's problem to solve, but the next person wiring up an actual "sell to open"
  UI path needs to know that gap exists before doing so.
- Existing already-open positions in a user's local DB that are short stock but persisted with
  `direction: 'Bullish'` (a real possibility if this bug has been live) are **not** retroactively
  corrected by this plan — there's no reliable signal in `PortfolioPositionModel` to distinguish
  "actually bullish" from "mislabeled short" after the fact. Flagged as a manual data-reconciliation
  note for the user, not an automated migration.

## 3. Test plan

**Correction from round 1 review:** the original draft claimed `test_broker_router.py` had
"existing SELL-against-`ibkr_paper` cases" to extend. Independently re-verified: false — there are
zero `"SELL"` occurrences anywhere in `test_broker_router.py` or `test_ibkr_paper.py`; every
existing `BrokerOrder(...)` there uses `action="BUY"`. All SELL/OPEN/CLOSE coverage below is
**new**, not an extension of something that already exists.

**Step 0 — migration of existing tests (must happen before any new test can pass). Round 2 review
found the round-1 count was internally self-contradictory (undercounted `test_alpaca_paper_execution.py`
after saying two sentences later that it needs updating; wrongly included `test_auto_trade.py`,
which posts to the unchanged `ArmRequest`). Corrected count, verified against actual file
contents:**

| File | Sites needing `effect` added | Why |
|---|---|---|
| `test_broker_router.py` | 5 `BrokerOrder(...)` + 1 raw JSON POST body | Constructs `ibkr_paper.BrokerOrder`; posts to `StockOrderRequest`/`OptionOrderRequest` |
| `test_ibkr_paper.py` | 4 | Same dataclass |
| `test_tastytrade_paper.py` | 1 | Same dataclass |
| `test_tradier_paper.py` | 7 | `tradier_paper.py`'s own separate `BrokerOrder` (§2.2) |
| `test_alpaca_paper_execution.py` | 4 | Imports and constructs `ibkr_paper.BrokerOrder` too — **round 1 wrongly exempted this file; it does need updating** |
| `test_auto_trader.py` | 0 | `ArmedStrategy` is unchanged (§2.2's resolution removed the field from this path entirely) |
| `test_auto_trade.py` | 0 | Posts to `ArmRequest`, which is unchanged — **round 1 wrongly included this file** |

**Net: 22 sites** need `effect="OPEN"` added, as a first, purely mechanical commit with no other
behavior change, before writing any new SELL/CLOSE-specific test. Separately (not part of this
mechanical pass, since it's a real behavior change): `test_tradier_paper.py`'s
`test_option_sell_uses_sell_to_open` (line 40-48) currently asserts that a bare `action="SELL"`
maps to `sell_to_open` — under the new model this test's premise changes (that mapping is now
conditional on `effect="OPEN"`), so it must be rewritten to pass `effect="OPEN"` explicitly and
keep asserting `sell_to_open`, alongside new sibling tests for `effect="CLOSE"` → `sell_to_close`.

- **Backend, per adapter** (`backend/tests/test_broker_router.py` or a new
  `test_broker_adapters.py`): for `tradier_paper` and `tastytrade_paper`, assert all 4
  `(action, effect)` combinations produce the correct wire-level side/action string, for both
  `STK` and `OPT` where applicable — for Tradier stock specifically, explicitly assert
  `(SELL, OPEN)` → `"sell_short"` and `(BUY, CLOSE)` → `"buy_to_cover"`, not just `"sell"`/`"buy"`,
  since that value change *is* the fix (§2.1). For `ibkr_paper` and `alpaca_paper`, assert `effect`
  is accepted but doesn't change the payload (documents the "auto-inferred" behavior as
  intentional, not untested).
- **Backend, schema validation**: `StockOrderRequest`/`OptionOrderRequest` reject a request
  missing `effect` (no default → 422). (`ArmRequest` is unchanged, no test needed there.)
- **Backend, routing** (genuinely new, not an extension of anything): add SELL+OPEN and SELL+CLOSE
  cases routed through `broker_router.py` to `tradier_paper` and `tastytrade_paper` specifically —
  this exact combination is the gap that let the original bug ship untested.
- **Frontend, `paperTrade.test.ts`**: update the existing no-direction call
  (`paperTrade.test.ts:5`) to pass `'Bullish'`, and add a new case asserting
  `buildPaperStockPosition('AAPL', 150, 10, 'Bearish', ...)` produces `direction: 'Bearish'`.
- **Frontend, new `ClosePositionDrawer.test.tsx`**: four cases — long stock, short stock, long
  option (existing behavior, unchanged), short option — asserting **both** `realizedDollar` and
  `realizedPct` (not just dollar, per the §2.3 fix) against a hand-computed expected P&L for each.
- **Frontend, call-site smoke check**: for each of the 4 entry call sites, confirm the outgoing
  request body includes `effect: 'OPEN'` (can be a light assertion in existing tests for those
  components rather than new test files, where such tests already exist).

## 4. Sequencing

0. Mechanical pass: add `effect="OPEN"` (or the frontend equivalent) to every existing test call
   site enumerated in §3's Step 0, with **no other behavior change**, so the suite still passes
   before any real logic changes. This isolates "did I break something old" from "is the new logic
   right" in separate commits/diffs.
1. Backend: add `Effect` type; add `effect` to **both** `BrokerOrder` dataclasses
   (`ibkr_paper.py` and `tradier_paper.py`); update all 4 adapters' mapping logic; update
   `broker.py`'s two request schemas; hardcode `effect="OPEN"` inside
   `auto_trader.py:execute_option_order()` (no schema change there). Backend tests green.
2. Frontend: `api.ts` type changes for `postStockOrder`/`postOptionOrder` only; wire
   `effect: 'OPEN'` through the 4 entry call sites; fix `buildPaperStockPosition`'s direction
   param + its 4 call sites (3 threaded, 1 literal per §2.3) + its existing test; fix
   `ClosePositionDrawer`'s multiplier + single shared signed-delta calc for both dollar and pct.
   Frontend tests green.
3. `npm run typecheck` clean, full `pytest` + `npm run test` green.
4. Update `CODE_REVIEW_FINDINGS.md` to mark findings #2, #3, and #15 as fixed (do not delete —
   keep as a record).

**Rollout-window note (round 1):** step 1 ships before step 2, so between those two commits any
in-flight request to `/broker/stock-order` or `/broker/option-order` without `effect` would 422.
Given this is a locally-run single-developer tool (`npm run dev` + local FastAPI, per CLAUDE.md —
not a deployed multi-user service), that window is sub-second in practice and not worth
engineering around with a transitional default; noting it so it isn't a silent gap in the plan.

## 5. Resolved design questions (were open in round 1, resolved during revision)

- **`effect` vs `intent`/`position_effect` as the field name:** kept `effect` — matches the
  "position effect" terminology brokers themselves use (Tradier/Tastytrade docs both call this an
  order's "effect"), no strong reason to deviate.
- **Should `ArmRequest.effect` be caller-supplied or hardcoded server-side:** resolved to
  hardcoded (§2.2) — removes a required-field-with-no-matching-dataclass-field crash risk entirely
  rather than trading it for a "caller must always pass OPEN" convention that has no enforcement
  behind it.

## 6. Adversarial review log (3 rounds)

### Round 1

| # | Finding | Severity | Resolved in |
|---|---|---|---|
| 1 | `tradier_paper.py` has its own separate `BrokerOrder`, not shared with `ibkr_paper.py` | 5 | §2.2 — verified correct by round 2 |
| 2 | `ArmedStrategy`/`execute_option_order()` unaddressed → guaranteed 500 on `/auto-trade/arm` | 5 | §2.2 (removed the field instead) — verified correct by round 2, full-file read |
| 3 | Wrong frontend component named for auto-trade arm call site | 4 | §2.3 (corrected, now moot per #2's resolution) — verified correct by round 2 |
| 4 | `ChartWorkspace` buy-popover call site has no direction in scope | 4 | §2.3 (hardcode `'Bullish'`) — verified correct by round 2, incl. no downstream code assumes chart-click positions could be short |
| 5 | `realizedPct` sign left unfixed alongside `realizedDollar` | 3 | §2.3 — formula verified correct by round 2 with worked long/short examples |
| 6 | False claim of "existing SELL-against-ibkr_paper" tests to extend | 3 | §3 (corrected) — verified correct by round 2 |
| 7 | Test-migration blast radius unquantified | 3 | §3 Step 0 — round 1's own fix was itself wrong (see round 2 #2 below); corrected again |
| 8 | No handling proposed for broker-side rejection of a close with no matching position | 3 | §2.4 (explicitly deferred, not silently ignored) — confirmed not contradicted elsewhere by round 2 |
| 9 | `(SELL, OPEN, OPT)` unreachable dead code, no margin modeling if ever wired up | 2 | §2.4 — verified correct by round 2 |
| 10 | Plan internally inconsistent about the `ArmRequest.effect` open question | 2 | §2.2 / §5 (resolved) — verified correct by round 2 |
| 11 | `paperTrade.test.ts`'s existing 3-arg call breaks silently | 1 | §2.3, §3 — verified accurate by round 2 |
| 12 | Rollout ordering / transient-breakage window not addressed | 1 | §4 |
| 13 | Tradier/IBKR auto-infer assumption still unverified against live sandbox | 3 | Only half-resolved by round 1 (IBKR/Alpaca hedge was fine; Tradier's was replaced with a false-confidence claim) — see round 2 #1 |

### Round 2 (verified round 1's fixes against real code; found these additional issues)

| # | Finding | Severity | Resolved in |
|---|---|---|---|
| 1 | Tradier-stock "no change" claim is factually wrong — Tradier's equity API has explicit `sell_short`/`buy_to_cover` sides, not auto-inference (verified against Tradier's own API docs) | 4 | §2.1, rewritten with a 4-way `_EQUITY_SIDE` map — this was the most significant finding of either round, since it left the plan's own stated goal ("sell is sell to close... for both stock and options, everywhere") unmet for a live, reachable broker+asset-class combination |
| 2 | §3's Step 0 test-count table was self-contradictory (said `test_alpaca_paper_execution.py` needs no updates, then said it does two sentences later) and wrong (missed Alpaca's 4 sites, wrongly included `test_auto_trade.py`'s 2 sites which post to the unchanged `ArmRequest`) | 3 | §3, corrected table: 22 sites, not ~41 |
| 3 | Map redefinitions (`_OPTION_SIDE`, `_ACTION_MAP`) never said the *consuming lookup lines* (`tradier_paper.py:70` and the option-side lookup, `tastytrade_paper.py:57`) must change key shape too — if missed, every order breaks, not just close orders | 3 | §2.1, new explicit subsection listing all 3 lookup-line changes |
| — | (Confirmed correct, no action needed): §2.3 P&L formula math, `auto_trader.py` full-file read, ChartWorkspace kind-typing, §2.4/§3 "unreachable from UI" vs. new tests not actually contradictory, dict tuple-key hashing mechanics | — | — |
| — | (New residual gap noted, not blocking): `direction` isn't runtime-enforced end-to-end (backend schemas are plain `str`) — added as an explicit caveat, not a required fix | 2 | §2.3 |

Round 2's own verdict: "not clean" pending the 3 findings above. All 3 are addressed in the round-2
revision.

### Round 3 (verified round 2's `_EQUITY_SIDE` fix, test-count table, and lookup-line note against
real code; independently re-fetched Tradier's API docs rather than trusting round 2's citation)

| # | Finding | Severity | Resolved in |
|---|---|---|---|
| 1 | `_EQUITY_SIDE` map itself confirmed correct against Tradier's docs (independently re-fetched) — no action needed | — | — |
| 2 | `broker.py`'s two route handlers construct `BrokerOrder(...)` directly and were never told to add `effect=req.effect` — schema-only change is incomplete | 2 | §2.2, new explicit note |
| 3 | Appending `effect` (no default) after already-defaulted fields on both `BrokerOrder` dataclasses raises `TypeError` at import time — reproduced directly by the reviewer | 3 | §2.2, explicit field-placement instruction (insert after `action`, before `tif`) |
| 4 | Test-count table (22 sites) re-verified correct, independently recounted — no action needed | — | — |
| 5 | `ClosePositionDrawer`'s instructed reuse of `risk.ts`'s `_multiplier` is impossible as written — the helper is module-private, not exported | 2 | §2.3, explicit export instruction added |
| 6 | Tradier `sell_short` has no margin-account caveat, unlike the equivalent IBKR/Alpaca hedge | 2 | §2.1, caveat added |
| 7 | Minor line-citation slips (`auto_trader.py:118-124` should be `118-127`; the plan's two "consuming lookup line" bullets for Tradier are actually one physical line) | 1 | §2.1/§2.2 citation fixed; the one-line-two-halves nuance is described accurately enough in context, not further split |

Round 3's own verdict: no severity-4/5 findings; all issues are described by the reviewer itself
as "self-correcting... fail loudly and immediately (import-time TypeError, missing-kwarg TypeError,
or a `tsc` compile error) rather than shipping a silent bug." All are fixed in this revision.
Diminishing-returns judgment call: stopping the adversarial-review loop here rather than running a
round 4 — three consecutive rounds have moved from severity-5 structural errors, to one
severity-4 factual error, to purely mechanical severity-≤3 gaps that a normal implementation pass
(guided by this now much more precise plan) and the existing test suite would catch immediately
even if this document missed something else at this point.
