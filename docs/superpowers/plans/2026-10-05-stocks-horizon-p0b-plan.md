# Stocks horizon P0B: bearish block + earnings veto over the hold — Implementation Plan (`STOCKS-HORIZON-P0B`)

> **For agentic workers:** built through `k-ticket-coordinator`. One ticket per task, one fresh implementer per
> ticket, test-first. The coordinator owns `PROJECT_STATE.json`, the tracking issue and the audits. Implementers never
> edit audit fields and never put `round N` in a commit subject.

**Origin.** Decision `STOCKS-PARAMS-PER-HORIZON-2026-10-05` (ADR `docs/adr/0001-stocks-parameters-per-horizon.md`) and
decision `STOCKS-HORIZON-P0-SCOPE-2026-10-05` (Kenneth, 2026-10-05, in chat):

- **Bearish is Unvalidated now, on stocks AND options.** A bearish card cannot reach PASS, cannot be auto-armed or
  auto-fired, and a manual broker send that **opens** a bearish position is refused. Closing orders are never blocked.
  Bearish stays visible for research. Evidence: every bearish cell lost money before costs (Phase C
  `score_calibration.md`, `strategy_matrix.md`).
- **Earnings veto window = max(reject_days, hold_max)** on the existing options vetoes (scan card, Step 7, auto-fire;
  the arm carries `hold_max`), **and a new stocks veto**: no PASS and no send when earnings fall inside the hold.

P0A (exclusion list, confidence) is a separate target. This plan does not touch confidence or universes.

**Live behaviour that changes, on purpose.**

- Every Bearish options card and stock card is capped at CAUTION and says why. The stocks "After scan" auto-fire
  (PASS only) therefore never fires a bearish card.
- `/auto-trade/arm` refuses `direction: "Bearish"`; a fire of an arm with that direction is refused and recorded.
- `/broker/stock-order` refuses `SELL` + `OPEN`; `/broker/option-order` refuses `OPEN` of a bearish option (BUY a put,
  or SELL a call). Step 7 and the three stocks send UIs refuse before saving a Portfolio row.
- A Quarterly options scan (hold 45–60d, scoring horizon Position, `reject_days` 30) now vetoes earnings 30–59 days
  out; Semi-annual and Annual likewise up to 104 / 199 days. Swing (reject 21 ≥ hold 15) and Position (reject 30 <
  hold 45 → 45) as computed.
- Stocks scans gain an earnings veto: a stock card with a known earnings date inside `max(reject_days, hold_max)` is
  capped at CAUTION, flagged, and cannot be sent.

## Global constraints

- **Runtime.** Backend Python **3.11** (Windows `.\.venv\Scripts\python.exe -m pytest`). Frontend
  `cd frontend && npm run typecheck && npm run test`.
- **TDD.** Write the failing test first, run it, see it fail for the predicted reason, then write the code.
- **No YAML value changes.** `reject_days` / `caution_days` stay as configured.
- **Numeric golden pins.** Pins on Bearish card statuses and on long-hold options vetoes move on purpose; the
  implementer lists every moved pin with the reason. Any other moved pin is a defect: stop and report it.
- **Frontend and backend deploy together** (`ArmRequest` forbids unknown keys and gains a required field; the stock
  scan request gains an optional field).
- **Commit trailer:** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Shared definitions (used by several tickets)

- **Bearish-opening order.** `effect == "OPEN"` and either `sec_type == "STK"` and `action == "SELL"`, or
  `sec_type == "OPT"` and ((`action == "BUY"` and right `P`) or (`action == "SELL"` and right `C`)). Never a `CLOSE`.
  The option right comes from a new helper `app/data/option_symbol.py::option_right(option_symbol) -> Literal["C",
  "P"]`, accepting OCC (`AAPL250516P00185000`) and pipe (`AAPL|185|2025-05-16|P`) forms and raising `ValueError`
  otherwise. An unparsable option symbol on an OPEN is refused (422) — fail closed.
- **Unvalidated-bearish message** (one constant, backend `app/services/unvalidated.py::BEARISH_UNVALIDATED_MESSAGE`,
  frontend `lib/unvalidated.ts::BEARISH_UNVALIDATED_MESSAGE`, same text): `"Bearish setups are Unvalidated: no
  bearish strategy has passed validation yet (decision STOCKS-PARAMS-PER-HORIZON-2026-10-05). Visible for research;
  no PASS, no auto-trade, no opening order."`
- **The hold.** Every frontend place that sends or uses `hold_max_days` takes it from the hold that produced the
  scan, never from the preset table: `ScanContext.holdMax` (`frontend/lib/scanStore.ts`) passed through
  `sanitizeHoldDays` (`lib/horizonPresets.ts`), exactly as `resolveOptionsScanRequest.ts` already does for the options
  scan; a schedule profile uses `profile.holdMax` (`lib/scanScheduleResolve.ts`). `presetByKey(...).holdMax` is wrong
  for Custom (its row is a fixed 15 while the user's range can be 60-185). Plan round 1, P0B-P1-F2.
- **Veto window.** `veto_days = max(reject_days, hold_max_days)`. `hold_max_days` comes from the request. When a
  request has none (an older client, or a scheduled scan saved before this change), the backend uses the scoring
  horizon's own preset hold: `DEFAULT_HOLD_MAX = {"Intraday": 2, "Swing": 15, "Position": 45}` in
  `app/scoring/stock_scorer.py`, beside `effective_event_window`, with a comment naming
  `frontend/lib/horizonPresets.ts` as the source it mirrors. New function
  `effective_veto_days(horizon, overrides, hold_max_days) -> int` returns
  `max(effective_event_window(horizon, overrides)[0], hold_max_days if not None else DEFAULT_HOLD_MAX[horizon])`.

**Plan round 1 (2026-10-05):** P0B-P1-F1 (B6 read an earnings date the batch quote never carries), P0B-P1-F2
(the hold came from the preset table, wrong for Custom) and P0B-P1-F3 (Step 4 / Watchlist read `status`, which B2 left
uncapped) fixed in this text.

## Ticket graph

```
B1 (option_right + bearish-opening guard at the broker endpoints)
B2 (bearish cap on options + stocks cards)          ── B4 (frontend bearish refusals)
B3 (arm/fire refuse bearish; arm carries hold_max)  ──┘
B5 (veto window on the options scan + auto-fire)    ── B7 (frontend veto window: Step 7 + stocks send)
B6 (stocks earnings veto in the stock scan)         ──┘
```

Sequential build: B1, B2, B3, B4, B5, B6, B7. B3 and B5 both edit `services/auto_trader.py`; B2, B5 and B6 edit the
scan routers; serial order avoids conflicts.

---

## B1 — The broker endpoints refuse bearish-opening orders

**Mechanism today.** `routers/broker.py` has `/stock-order` and `/option-order`. Both build a `BrokerOrder` and call a
shared helper (near lines 30–58) that, for `effect == "OPEN"`, checks account value and the daily risk budget and
already refuses `OPT` opens whose action is not `BUY` ("Daily risk budget refuses naked short option opens"). Nothing
checks direction.

**Semantics.**

- Add `option_right` to `app/data/option_symbol.py` (shared definitions).
- In the shared helper, for `effect == "OPEN"` **before** the daily-risk reservation: if the order is
  bearish-opening, raise `HTTPException(422, detail=BEARISH_UNVALIDATED_MESSAGE)`. (Because the existing naked-short
  check already refuses `OPT SELL OPEN`, the reachable new case for options is `BUY` a put.)
- Log `broker_order_failed` with `http_status: 422` and `error: "bearish unvalidated"` the same way the endpoint logs
  its other refusals, so the audit log records it. Confirm the idempotency claim is released on this path (it raises
  inside the `try` whose `finally` releases it; add a test).
- `CLOSE` orders (either direction) pass unchanged.

**Test first.** `backend/tests/test_broker_bearish_block.py` (patch the broker router so no adapter is reached):

1. `/broker/stock-order` `SELL OPEN` → 422 with the message; adapter never called. `SELL CLOSE` and `BUY OPEN` reach
   the adapter.
2. `/broker/option-order` `BUY OPEN` on `AAPL250516P00185000` and on `AAPL|185|2025-05-16|P` → 422; `BUY OPEN` on a
   call reaches the adapter; `SELL CLOSE` on a put reaches it; an unparsable option symbol on `OPEN` → 422.
3. `option_right` unit tests for both formats and a bad input.
4. A refused order does not leave the idempotency key claimed (a second identical request is processed, not
   deduped).

**Commit:** `feat(broker): refuse bearish-opening orders while bearish is Unvalidated (STOCKS-HORIZON-P0B)`

---

## B2 — Bearish cards are capped at CAUTION on both paths

**Mechanism today.** Options: `routers/scan.py` builds `finalStatus=_final_status(card.status, contract_card.status,
entry.quality_status, <earnings veto>, <unknown-earnings cap>)` (near line 1284). Stocks: the `/stock-scan`
per-symbol function and `_analyze_core` in `routers/stock_scan.py` set `stock_status` from the scorer card and the
confidence/regime gates.

**Semantics.**

- Options: cap **both** verdicts a card carries. `finalStatus`: add `"CAUTION" if direction == "Bearish" else
  "PASS"` to the `_final_status(...)` arguments. `status` (the stock-only verdict, `status=card.status` near line
  1219): capped at CAUTION for Bearish, never lowering a REJECT -- Step 4 ranking (`step-4-ranking/cardToRow.ts`, row
  tint, SymbolHeader, total-score badge) and `/api/watchlist` (`routers/watchlist.py`) read `status`, not
  `finalStatus` (plan round 1, P0B-P1-F3). Also add a field
  `unvalidatedReason: Optional[str]` on `TradeCardData` (default `None`) set to `BEARISH_UNVALIDATED_MESSAGE` for
  bearish cards. Shortlist ranking already sorts CAUTION after PASS.
- Stocks: in both functions, after the existing caps, a Bearish request caps `stock_status` at CAUTION (never lowers
  a REJECT) and appends `{"gate": "unvalidated", "status": "CAUTION", "detail": BEARISH_UNVALIDATED_MESSAGE}` to the
  card's gate flags. `_analyze_core` already builds `gate_flags`; `_process_stock` does not yet carry them, so
  add `PositionCardOut.gate_flags: list[GateFlag] = Field(default_factory=list)` (reuse the existing `GateFlag`
  type) and the matching optional `PositionCardData.gate_flags` frontend wire field. Initialize the scan card
  list empty and append the required Unvalidated flag for Bearish. Default-empty/optional makes older saved
  cards readable; this is the carrier for the flag already required by B2, not a new gate or score change.
- No candidate is dropped by this cap; funnel counts are unchanged.
- Pre-breakout and fib scans emit setups, not statuses; untouched.

**Test first.** Options scan with a fixture that PASSes Bullish: run it Bearish (patch the scorer to PASS) → card
`finalStatus == "CAUTION"` **and** `status == "CAUTION"`, `unvalidatedReason` set; Bullish unchanged. `/api/watchlist`
over a stored Bearish card returns CAUTION. Jest: `cardToRow` on a Bearish card (status CAUTION) renders CAUTION. Stocks `/stock-scan` Bearish → candidate
present at CAUTION with the `unvalidated` flag; `/analyze-stock` Bearish shows the flag.

**Commit:** `feat(scan): cap bearish cards at CAUTION as Unvalidated, options and stocks (STOCKS-HORIZON-P0B)`

---

## B3 — Auto-trade refuses bearish; the arm carries `hold_max_days`

**Mechanism today.** `routers/auto_trade.py::ArmRequest` (options only; `extra="forbid"`) carries `direction` and a
required `horizon`. Arms live in memory (`AutoTradeState`; not persisted). `services/auto_trader.py` fires through
`fire()`, which records refusals with `_record_refusal(attempt_id, strategy, <status>, reason)` and raises (the
earnings veto uses `_STATUS_EVENT_VETO_BLOCKED`).

**Semantics.**

- `ArmRequest.direction == "Bearish"` → `/auto-trade/arm` returns 422 with `BEARISH_UNVALIDATED_MESSAGE`; nothing is
  armed. Implement as a check in the arm handler (not a schema `Literal` change), so the 422 detail is the message.
- In `fire()`, before any broker call and before the sizing/regime check, an armed strategy with
  `direction == "Bearish"` is disarmed and refused: new status constant `_STATUS_UNVALIDATED_BLOCKED =
  "unvalidated_blocked"`, `_record_refusal(...)`, then raise a `RuntimeError` subclass `UnvalidatedDirectionError`
  that `/auto-trade/fire` maps to 400 like `EventVetoError`. Follow how `EventVetoError` is declared, recorded and
  mapped; mirror it, including any alert the event veto raises. (Defensive: B3's arm check means production cannot
  hold a bearish arm after deploy, but an arm created before a restart-less deploy could.)
- `ArmRequest` gains `hold_max_days: int = Field(..., ge=0, le=3650)` (**required**, the loud failure `horizon`
  already uses). `ArmedStrategy` gains `hold_max_days: Optional[int] = None` (direct constructors / tests). B5 reads
  it.
- Frontend `components/organisms/AutoTradeArm/index.tsx` sends `hold_max_days` = the scan's hold (shared
  definitions: `sanitizeHoldDays` over `useScanStore.getState().context`'s hold, where it already reads `horizon`). `lib/api.ts` `armAutoTrade`
  request type gains the field.

**Test first.** Backend: arm Bearish → 422, state unarmed; arm Bullish without `hold_max_days` → 422; with it → armed
and `ArmedStrategy.hold_max_days` set; fire of a directly constructed Bearish `ArmedStrategy` → refused, status
`unvalidated_blocked` recorded, adapter never called. Frontend: the arm request body includes `hold_max_days` equal
to the scan context's hold, including a **Custom 60-185** context (→ 185, not 15).

**Commit:** `feat(autotrade): refuse bearish arms and fires; arm carries hold_max_days (STOCKS-HORIZON-P0B)`

---

## B4 — The UIs refuse bearish opens before saving anything

**Mechanism today.** Options manual sends go through Step 7 (`app/(frame)/screener/step-7-trade-card/page.tsx`, the
send handler near line 1116 that already returns early on an earnings veto, and `api.postOptionOrder` near line 1215);
the arm is `components/organisms/AutoTradeArm`. Stock sends all go through `lib/stockDirectSend.ts::sendStockSaveFirst`
(save the Portfolio row first, then `api.postStockOrder` with `effect: 'OPEN'`), called from `StockPositionCard`,
`StockSendDialog` and the Step-7 position-card page. After audited STOCKS-STEP-MERGE-S2
landed on main, the stock Step-7 page delegates its sends to these shared components; put the guard in those
authoritative components and test the page through them, without recreating a separate submit path. Preserve the
existing unavailable-C4-validation refusal and in-flight ownership/recovery gates. This changes wiring only, not B4 semantics.

**Semantics.**

- New `frontend/lib/unvalidated.ts`: `BEARISH_UNVALIDATED_MESSAGE` (same text as the backend) and
  `isBearishUnvalidated(direction: string | null | undefined): boolean` (`direction === 'Bearish'`).
- Step 7 (options): when the active card's direction is Bearish, the send handler returns before any save or order
  (beside the earnings-veto early return), the send and arm buttons are disabled with the message as their reason,
  and the card shows the message (reuse the component Step 7 already uses to show the earnings-veto reason). The
  `@contextRail` pre-trade checklist adds a REJECT row "Direction" with the message (find how it adds the earnings
  row).
- `AutoTradeArm`: refuses to arm a Bearish card (button disabled + reason), mirroring its `armBlockedReason` handling.
- `sendStockSaveFirst`: when `action === 'SELL'` (it only sends `effect: 'OPEN'`), return `{ kind: 'not-placed',
  message: BEARISH_UNVALIDATED_MESSAGE }` **before** the save. The three stock UIs show a not-placed outcome as they
  already do; additionally disable their send buttons for Bearish cards with the message (find each component's
  existing disabled-reason pattern).
- Displays only: Step 4 ranking, the Watchlist and the stocks Steps 4/6 tables show the CAUTION status the backend
  now returns (B2 caps both `status` and `finalStatus`); no extra column.

**Test first.** Jest: `sendStockSaveFirst` with `action: 'SELL'` returns not-placed and calls neither the save nor
`postStockOrder`; Step 7 send handler with a Bearish card calls neither `postOptionOrder` nor the portfolio save;
AutoTradeArm with a Bearish card cannot call `armAutoTrade`; each stocks send button is disabled for a Bearish card.

**Commit:** `feat(ui): refuse bearish opens and arms before saving, with the Unvalidated reason (STOCKS-HORIZON-P0B)`

---

## B5 — Options: the earnings veto covers the hold

**Mechanism today.** `routers/scan.py::_earnings_veto(card)` vetoes when the event rule's `earnings_days <
reject_days` (the scan's effective reject window, `effective_event_window`). The scan echoes `event_window =
EventWindow(reject_days, caution_days)` (near line 1823), which Step 7 and its rail pass to
`frontend/lib/earningsGate.ts::earningsGateFor` as `rejectDays`. `auto_trader._apply_event_veto` uses
`effective_event_window(strategy.horizon, None)[0]` (YAML window, no override), or the widest window over all horizons
when the arm has no horizon. `ScanRequest` already carries `hold_min_days` / `hold_max_days` (used for the DTE window).

**Semantics.**

- `effective_veto_days` (shared definitions) in `stock_scorer.py`.
- Options scan: compute `veto_days = effective_veto_days(req.horizon, req.overrides, req.hold_max_days)` once beside
  `_event_win`, never failing the scan (same try/except as `_event_win`; on failure fall back to the event window's
  `reject_days`, and if that is unavailable too, to the widest `effective_veto_days` over all horizons with no
  overrides — fail toward vetoing). Pass it into `_earnings_veto(card, veto_days)`: veto when `0 <= earnings_days <
  veto_days`. Both call sites (the `finalStatus` argument and `earningsVeto=`) use the same value.
- `EventWindow` schema gains `veto_days: Optional[int] = None`, set on the result. Frontend `scanStore` type gains it.
- `_apply_event_veto(strategy)`: the window becomes `max(effective_event_window(strategy.horizon, None)[0],
  strategy.hold_max_days if not None else DEFAULT_HOLD_MAX[strategy.horizon])`; with no horizon, the widest over all
  horizons of that same expression. The message names the window (`"inside the hold window (<{veto}d: max(reject
  {r}d, hold {h}d))"`).
- The event **rule**'s own REJECT/CAUTION grading (`_rule_event`, `reject_days`/`caution_days`) is unchanged: the
  veto is the gate, the rule is the score.

**Test first.** `_earnings_veto` with earnings 40d, reject 30, veto 60 → True; with veto 30 → False. Options scan with
`hold_max_days=60`, Position, earnings 40d → card REJECT and `earningsVeto`; `event_window.veto_days == 60`. Without
`hold_max_days` → `veto_days == 45`. `_apply_event_veto` on an arm with `hold_max_days=105`, earnings 90d → refused;
`hold_max_days=None`, Position, earnings 40d → refused (45).

**Commit:** `fix(earnings): options veto window = max(reject_days, hold_max) (STOCKS-HORIZON-P0B)`

---

## B6 — Stocks: a new earnings veto over the hold

**Mechanism today.** The stocks path never vetoes on earnings and **has no earnings date at all**: the batch quote
(`data/market.py::fetch_quotes`, used at `stock_scan.py` ~1627 for `_process_stock` and ~727 for `_analyze_core`)
returns only `last` / `prevclose`, so the `quote.get("earnings_date")` reads that build `next_event_days` (~919,
~1416) always see None -- that display is dead today -- and `score_stock` on the stocks path gets no `earnings_date`.
The options scan gets dates from Tradier `fundamentals/calendars` (`market._extract_earnings_date`) with the yfinance
fallback (`fetch_calendar_dates_async`) (`scan.py` ~641-649); the auto-trade fire path has the same chain as a sync
call with per-source deadlines and failure backoff, `auto_trader._fetch_earnings_date` → `_lookup_earnings_date`
(returns the date or None, raises on a failed lookup). `StockScanRequest` (`app/schemas/stock_scan.py`) has no hold
days. (Plan round 1, P0B-P1-F1.)

**Semantics.**

- `StockScanRequest.hold_max_days: Optional[int] = Field(None, ge=0, le=3650)`. Frontend: `ResolvedStockScanContext`
  (`lib/resolveStockScanRequest.ts`) gains a **required** hold field and `buildStockScanRequestBody` sends it; all
  three callers pass the scan's hold (shared definitions): `lib/stockScan.ts` (~346, `context.holdMax`),
  `lib/scanScheduleResolve.ts` (~119, `profile.holdMax`), `lib/analysisStore.ts` (~47, `ctx.holdMax`).
- **Earnings lookup.** In `_process_stock`, only for a symbol that has passed every drop gate (just before the
  `PositionCardOut` is built, so dropped symbols cost nothing), and in `_analyze_core`, look up the next earnings
  date with `await asyncio.to_thread(auto_trader._fetch_earnings_date, symbol)` -- the same Tradier-then-yfinance
  chain, deadlines and backoff the fire path uses. A raised lookup or `None` = unknown. `earnings_days = (date -
  today).days` when `>= 0`, else unknown. The quote's dead `earnings_date` read is left alone (not this ticket).
- Compute `veto_days = effective_veto_days(req.horizon,
  req.overrides, req.hold_max_days)` once per scan (the per-symbol function receives it; same fail-toward-vetoing
  fallback as B5). When `earnings_days is not None and earnings_days < veto_days`: cap `stock_status` at CAUTION
  (never lowers a REJECT), add gate flag `{"gate": "earnings", "status": "CAUTION", "detail": "earnings in {n}d is
  inside the hold window (<{veto}d)"}`, set `earnings_veto=True`.
- `PositionCardOut` and `StockAnalysisOut` gain `earnings_days: Optional[int] = None`, `earnings_veto: bool = False`.
  `StockScanResult` gains `veto_days: Optional[int] = None`.
- Unknown earnings (none in the quote) is **not** a veto on the stocks path (decision D4's unknown-date rule is an
  options auto-fire policy; extending it to stocks was not decided). State this in the code comment.
- No candidate is dropped; funnel counts unchanged.

**Test first.** Patch `auto_trader._fetch_earnings_date` (the module-level seam the suite already replaces in
`tests/conftest.py`), **not** the quote: `/stock-scan` with a PASS fixture, `hold_max_days=60`, Position, earnings 40d
→ CAUTION, `earnings_veto`, flag; 70d → unchanged; lookup returns None or raises → no veto, no crash; a symbol dropped
by an earlier gate never triggers the lookup; no `hold_max_days` → window 45. `/analyze-stock` same. One test drives
the real `_lookup_earnings_date` underneath with its HTTP layer stubbed (follow `tests/test_earnings_lookup_fire.py`).
Frontend: the stock scan request body includes `hold_max_days` from each of the three callers, including a Custom
60-185 context (→ 185).

**Commit:** `feat(earnings): stocks veto earnings inside the hold window (STOCKS-HORIZON-P0B)`

---

## B7 — Frontend: Step 7 and the stocks sends use the veto window

**Mechanism today.** `earningsGateFor(card, scanTimestamp, rejectDays)` ages the scan's `earningsDays` by the scan's
age and vetoes when `daysNow < rejectDays` or `card.earningsVeto`. Step 7 and its rail pass
`scanResult.event_window.reject_days`. The stocks send UIs have no earnings gate.

**Semantics.**

- Step 7 and its rail pass `event_window.veto_days ?? max(event_window.reject_days, holdMaxOfScan)`, where
  `holdMaxOfScan` is the scan's hold (shared definitions -- `ScanContext.holdMax` through `sanitizeHoldDays`, never
  the preset table; a persisted pre-deploy result has no `veto_days`, and `setContext` clears results when the
  horizon changes, so the context matches the result shown). If neither is available, keep today's `reject_days`.
  Test a Custom 60-185 context (→ 185).
- Stocks: a small adapter `stockEarningsGate(card, scanTimestamp, vetoDays)` reusing `earningsGateFor`'s ageing (map
  `earnings_days`/`earnings_veto` onto its input; unknown is never a block on stocks, so pass `earningsUnknown:
  false` and `isEtf: true`-equivalent semantics, or factor the ageing out — implementer's choice, tested). The three
  stocks send UIs (`StockPositionCard`, `StockSendDialog`, Step-7 position card) disable send with the veto message
  when it vetoes, and `sendStockSaveFirst` gains an `earningsVeto` guard input so the ORDER is refused even if a
  button is bypassed (mirrors Step 7's belt-and-braces early return).

**Test first.** Jest: `earningsGateFor` with `veto_days` 60 and aged distance 40 → veto; Step 7 passes `veto_days`
when present and the fallback when absent; each stocks send button disabled on an `earnings_veto` card;
`sendStockSaveFirst` with the veto refuses before saving.

**Commit:** `feat(ui): earnings veto over the hold on Step 7 and the stocks sends (STOCKS-HORIZON-P0B)`

---

## Verification (coordinator, after B7)

- Backend full suite on Python 3.11; frontend typecheck + Jest.
- On Kenneth's machine: a Bearish options scan and stock scan show CAUTION with the Unvalidated reason; Step 7 and the
  stock card refuse a bearish send without creating a Portfolio row; `/auto-trade/arm` with Bearish returns 422. A
  Quarterly options scan shows `veto_days 60` in the result.

## Out of scope (logged, not built)

- Server-side earnings re-check on manual sends (`/broker/option-order`, `/broker/stock-order`): the request carries
  no hold window. Existing open item Phase-B A1-F4b covers options; stocks join it.
- Unknown earnings on the stocks path (not a veto; D4 is options policy).
- Strategy watches: they alert, never trade; bearish watch alerts continue.
- Re-enabling bearish per cell: STOCKS-HORIZON-T2, from tuned verdicts.
