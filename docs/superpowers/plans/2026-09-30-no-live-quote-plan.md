# NO-LIVE-QUOTE — plan (PARKED draft; NOT audited; nothing built)

- **Phase:** `NO-LIVE-QUOTE` (PROJECT_STATE.json). Status `not_started`.
- **Origin:** split out of `CONTRACT-LIQUIDITY-DTE` on 2026-09-30, Kenneth's call (decision
  `CONTRACT-LIQUIDITY-DTE-SPLIT-2026-09-30`). This was fix 3 of that plan. Across two adversarial plan
  rounds it produced every high finding (3 in round 1, 6 in round 2), and its input has never been observed.
  Fixes 1 and 2 ship without it and don't make the off-hours case any worse than today.
- **Kenneth's decision that still stands** (`CONTRACT-LIQUIDITY-DTE-ANSWERS-2026-09-30`, Q3):
  - a chain row with no live bid/ask is hard-rejected in the scan and in auto-trade;
  - Step 6 and the Watchlist only label it.
- **Step 0, before any design work: measure.** The design below rests on a code comment ("Outside market
  hours Tradier returns bid=0, ask=0", `market.py:808`/`:1489`) that nobody has observed.
  - Call Tradier `/v1/markets/options/chains` **directly**, not `/api/contracts`. The chain builder folds
    bid/ask into `price`/`spread` and drops rows where both `ask` and `last` are 0, so the app's output
    cannot show the case.
  - Record raw `bid`, `ask`, `last`, `volume`, `open_interest`, `bid_date`, `ask_date` and `trade_date` for
    every row, including the dropped both-zero rows.
  - Take the sample pre-market, in session, after the close and at a weekend, on the production (not
    sandbox) base. The sandbox is 15 minutes delayed (`_is_sandbox_base`, `market.py:58`), so any
    quote-age rule must account for it.
  - Only then rewrite 3a/3g against what was seen.

## What is true on main (from the parent plan, §1 item 4)

The off-hours spread is fabricated, not measured.
- `market.py:808-813` (and the async twin ~:1489-1496): when `ask == 0`, `price` falls back to `last` and
  `spread = 0.0`.
- `augment.py:94-95` then builds `bid = ask = last`, so `spread_pct` is 0 and passes both the hard spread
  cap and the soft preference.
- PRD FR-24 lists "missing bid or ask" and "spread cannot be calculated" as hard rejects.

## Draft design as of CONTRACT-LIQUIDITY-DTE plan r2 (carried over verbatim; superseded wherever the findings below say so)

**Fix 3 — a contract with no live two-sided quote is never graded or traded as a 0% spread (FR-24; Q3 (a)
plus a label).** The reason key is `no_live_quote`; it replaces r1's `quote_stale`. It also covers FR-24's
"missing bid", so the name had to be broader.

*3a. Data.*
- `fetch_option_chain_async` (`market.py` ~:1489-1496, the live one) and its dead sync twin (`:808-814`,
  changed identically) set `"quote_live": bid > 0 and ask > 0` on every row.
- When `quote_live` is False, the row's `spread` is `None` instead of `0.0`. `price` still falls back to
  `last`, for display only.
- `fetch_contract_quote_async` returns the chain row, so the quote endpoint and every quote consumer see the
  same two fields.
- `_augment` (`augment.py:94-95`) passes `quote_live` through. When it is False, `_augment` sets
  `bid = ask = None` in place of `mid ± spread/2`.

*3b. Grading.* `validate_contract(..., stale_quote: Literal["reject", "label"] = "reject")`.
- The rule fires only when `contract.get("quote_live") is False`. A missing key counts as live, so fixtures
  and hand-built dicts keep working. A test pins that both chain builders always set the key.
- In both modes:
  - the spread hard and soft rules are skipped for that row, so the one cause is not also reported as
    `spread_too_wide`;
  - `detail["spread"]["spread_pct"]` is `None`, never the 1.0 that `_score_spread` computes from a zero
    mid;
  - the new `ContractScoreCard.no_live_quote` is True.
- `"reject"` (the default, so any new caller is safe): hard reject reason `no_live_quote`.
- `"label"`: the row is graded on the other axes, with a spread score of 0 (unknown counts as worst).
  - Its status is capped at CAUTION, so a row without a live quote can never read PASS.
  - This is a deliberate, recorded deviation from FR-24's "blocks recommendation" for the display path
    only. It is logged as a decision when the plan is clean, and §3 Docs no longer claims FR-24 is
    satisfied everywhere.

*3c. Callers and wire.*
- `routers/scan.py:852` keeps `"reject"`.
- `routers/contracts.py:244` (Step 6 and the Watchlist refresh) passes `"label"`.
- `OptionContract` (schemas `:224`) gains `noLiveQuote: bool = False`. `OptionContract.spread`,
  `ContractQuoteResponse.spread` and `SpreadDetail.spread_pct` become `Optional[float]`.
- `scan.py:1015-1016` reads `float(contract.get("bid", 0))`. Under `"reject"` it can't be reached with
  `bid = None`, since picks come only from non-REJECT cards. It is still hardened to treat None as missing,
  so the default-flip mutation fails on an assertion and not on a TypeError.

*3d. Auto-trade fire gate (round 1 H2).*
- New `_option_quote_is_live(option_symbol)` in `auto_trader.py`, next to `_market_is_open`, with the same
  pattern: worker thread, 3 s deadline, never under the lock. It fetches the contract's chain row.
  - It returns True only for a row with `quote_live is True`.
  - Exception, timeout, a missing row or False all refuse.
- `fire()` calls it right after `_market_is_open` for an option strategy (a 4-part `option_symbol`),
  *before* any broker call, and refuses with a named history reason: "no live option quote for
  <contract>".
- Stock strategies are untouched.

*3e. Frontend.*
- Step 6 (`step-6-contracts/page.tsx`) and the Watchlist Contracts tab (`watchlist/page.tsx`):
  - a "no live quote" tag on rows with `noLiveQuote`;
  - the SPREAD column renders "—" for `spread == null` and sorts it last;
  - such rows are never chosen as the "A — Recommended" row (`page.tsx:239`).
- `applyPickedContract` (`lib/tradeCardOverride.ts:26`) carries `noLiveQuote` onto `TradeCardData`, and a
  scan card defaults it to false.
- Step 7 (`TradeCard`) and `SendToBrokerDialog` show a "no live quote — entry price is the last trade"
  warning. It does **not** block: a manual limit order after hours is the user's call (Q3 said label
  outside the scan).
- Recompute-plan for such a pick sends `spread: null`.
  - `contracts.py`'s request model makes `spread` Optional; when it is None, `entry_bid = entry_ask = None`.
  - `assess_entry` (`entry_quality.py:51`) accepts None bid/ask and returns CAUTION with the reason
    "no live quote", with no spread reasons.
- The `OptionContract` and `TradeCardData` TS types gain the optional field, and the Jest mocks in
  `frontend/__mocks__/` are updated.
- `ScanLog`'s `REASON_CATEGORY` (`ScanLog/index.tsx:27`) gains `no_live_quote: 'DATA'`.

*3f. Consequences, stated honestly.*
- An off-hours options scan returns few or no candidates. Each affected name's rejection reason string
  reads `contracts rejected: no_live_quote(N)`, and the funnel counts it under the existing
  `failed_contracts` bucket. The funnel does **not** get its own `no_live_quote` row (§4).
- Scheduled options scans (`scan_schedule_scheduler.py:56-64,129-145`): a run with zero candidates and at
  least one `no_live_quote` rejection skips its rank diff and change notification. It sends one notice
  instead: "options scan at <time> ran without live option quotes". The previous row stays the diff base.
- Such a run can still trigger `maybe_fire_on_scan`, which 3d then refuses for an option strategy.

*3g. Verification gate: before any of fix 3 is built.*
- The off-hours shape is read from code comments, never observed. Rerun
  `backend/scripts/contract_liquidity_sample.py` pre-market, after the close and at a weekend. For every row,
  record `bid`, `ask`, `last`, `volume`, `bid_date`, `ask_date` and `trade_date`.
- Pass condition: off-hours rows show `bid == 0 or ask == 0`, and in-session rows are two-sided with
  current `bid_date`/`ask_date`.
- If off-hours rows carry non-zero *closing* quotes instead, `bid > 0 and ask > 0` cannot tell stale from
  live. The pre-decided fallback is then a quote age: stale when `max(bid_date, ask_date)` is older than 15
  minutes. That changes 3a, so fix 3 goes back for its own plan round.
- Fix 1's sentence "off-hours rows never reach the volume rule in the scan" holds only if this gate passes.


## Open findings against the draft (round 2 of the parent plan, 2026-09-30, not yet fixed)

These are the starting list for this plan's first round. Round 1's findings are already folded into the draft
above.

0. **The after-close residual CONTRACT-LIQUIDITY-DTE accepted (its round 3, finding 4).**
   - Once `min_volume` defaults to 0, after-close rows with volume 1–49 and a fabricated 0% spread
     (`ask == 0`) pass the scan's hard gates. Main used to reject them as `volume_too_low`.
   - This plan's hard reject in the scan closes that window. Kenneth may order this phase to land first.
   - **Decided 2026-09-30 (`CONTRACT-LIQUIDITY-DTE-MERGE-HOLD-2026-09-30`):** CONTRACT-LIQUIDITY-DTE is
     built but its merge is held until this phase lands, because the window reaches broker orders (scan
     PASS trigger → armed Step 7 card → price-only `_market_is_open`, and Step 7 direct send). This phase's
     hard reject must therefore cover the auto-trade fire and Step 7 send paths, not only the scan.

*High*
1. **The verification gate cannot run through `/api/contracts`.** See Step 0 above.
2. **Step 7 still sends a 0% spread.** The recompute takes `spread: q?.spread ?? 0` from Step 7's live quote
   (`step-7-trade-card/page.tsx:887`). `get_option_quote` does `float(quote["spread"])` (`contracts.py:324`),
   so a None spread gives a 500, then `q = null`, then spread 0 again, and entry quality reads PASS. Fix the
   call site, harden `:324`, add `quoteLive` to `ContractQuoteResponse`, and add a test plus a mutation that
   restores `?? 0`.
3. **3d contradicts itself: armed-and-silent, or consumed with a history row?** The probe sits in the
   pre-disarm region, where the only refusal is `ArmPreservedError` ("nothing consumed, nothing recorded",
   `auto_trader.py:38-53`). Only the pre-disarm reading is consistent with `_market_is_open`; the draft
   must state it.
4. **A 3 s probe over the full chain fetch will time out during market hours.** Each chain fetch enriches
   from IBKR (with a 1.5 s warm-up), then tastytrade, then yfinance (`market.py:1540-1582`), and `fire()` is
   sync. Use a quote-only fetch instead (Tradier `/markets/quotes` via `to_occ`, or the chain without
   enrichment), and name the function and its timeout budget.
5. **The probe can match another expiry.** `fetch_contract_quote_async` falls back to the first expiry at
   least 21 days out (`market.py:1438-1452`) and matches the row by strike only. Require
   `row["expiry"] == expiry` and the same right, as `contracts.py:319` already does.
6. **The scheduled-scan rule (3f) is wrong on four points:**
   - the scheduler never touches auto-trade (`scan_schedule_scheduler.py:125-129`);
   - there is no rank diff or change notification in the scheduler, only a count notice (`:173-177`), and
     deltas live in `_execute_scan_core` (`scan.py:1974`);
   - "keep the previous row as the diff base" needs a new run status (`scan_schedule_store.py:112`,
     `models/scheduled_scan_run.py:24`);
   - the trigger fires in session too, because `bid == 0, ask > 0` rows are common.

   Base it on a structured signal counted in `_execute_scan_core` ("no chain had a live two-sided row").

*Medium*
7. **Casting None to float crashes.** Affected: `augment.py:49` `float(c.get("spread", 0))`,
   `contracts.py:266`, `:324` and `:396`. List every site.
8. **Frontend readers turn a null spread into 0.** `lib/scoreDetailText.ts:109` renders a null as
   "Spread 0.0%" and reaches the Step 7 card through `applyPickedContract`. `lib/statusTooltips.ts:322`
   computes `c.spread / c.price`. Make the TS types nullable.
9. **The Step 7 warning comes from a Step 6 snapshot.** Base it on the live quote (`quoteLive` on
   `ContractQuoteResponse`) and fall back to the pick's flag.
10. **The "4-part `option_symbol`" test fails open for OCC-armed strategies.** `ArmRequest.option_symbol`
    is an unvalidated str (`routers/auto_trade.py:79`), and `execute_option_order` hardcodes
    `sec_type="OPT"` (`auto_trader.py:2177`), so "stock strategies" do not exist. Refuse symbols that
    neither parse as pipe form nor convert with `to_occ`. Drop the stock-strategy claim.
11. **About 15 fire test files patch `_market_is_open`.** They need the new probe patched too, or a shared
    fixture: `test_auto_trader.py`, `test_autotrade_a6_a7.py`, `test_autotrade_a9.py`,
    `test_docc1_money_blocks.py`, `test_o4_step4_booking.py`, `test_p3c_fire_off_loop.py`, `test_a4_*`, …
12. **`price` for a `bid == 0, ask > 0` row is unspecified.** Today it is `ask/2`. It is shown in Step 6 and
    becomes Step 7's entry premium.

*Low*
13. **The Watchlist contracts table has no SPREAD column** (`watchlist/page.tsx:480-489`).
14. **`frontend/__mocks__/` holds no API mocks.** It has only `lightweight-charts.js` and `styleMock.js`.
15. **ScanLog category mutation.** `REASON_CATEGORY` is not exported, and the parser's `[reason×N]` format is
    never produced. Export the map and test it directly.
17. **Name one test file each.** The candidates are `test_scan_schedule.py` vs `test_scan_schedule_entry.py`,
    `test_auto_trader.py`, and `test_entry_quality.py` for `assess_entry`.
18. **Mutation 7 needs a validator test.** Some test must call `validate_contract` relying on the
    `stale_quote` default.
19. **A 15-minute quote-age fallback marks every quote stale on the sandbox.**
20. **Hard-reject reasons accumulate.** An off-hours row with a volume floor reports both `no_live_quote` and
    `volume_too_low`. Either short-circuit, or reword.

(Finding 16 concerned the parent plan's preset test and stayed there.)

**Carried from the parent plan.** CONTRACT-LIQUIDITY-DTE keeps the zero-volume exemption for an *explicit*
`min_volume` floor above 0, because without a live-quote signal off-hours volume 0 cannot be told apart
from no trades. Once this plan has a trustworthy `quote_live`, revisit it: the exemption can become "only
when the quote is not live".
