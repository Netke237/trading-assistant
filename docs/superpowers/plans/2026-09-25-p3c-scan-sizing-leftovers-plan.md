# P3c — Scan & sizing leftovers — plan

Package: P3c in `docs/superpowers/plans/2026-09-25-work-packages.md` (decision P3C-PACKAGE-CREATED-2026-09-25).
Branch `claude/confident-volta-mja4lz`, off main 2f67e6f. Claim `P3C-SCAN-SIZING-LEFTOVERS`.

Every backlog entry was re-checked against 2f67e6f before this plan. The seven items and their state:

| # | Item | State on 2f67e6f | This plan |
|---|---|---|---|
| 1 | Options scan keeps an Intraday name whose 15-min regime fetch failed | open | code (scan.py) |
| 2 | Options direction gate judges an unmeasured trend placeholder | open | code (scan.py), **no schema field** (see Q1) |
| 3 | A 0% scan schedule silently runs at the 1% default | open | UI warning (settings page + resolver helper) |
| 4 | conviction_sizing messages (3)(4)(5) + (10) | (10) FIXED by P3b (ERROR once per process, `_ZERO_FULL_LOGGED`, conviction_sizing.py:158-229); (3)(4)(5) open | code (conviction_sizing.py) |
| 5 | Negative bearish backtest price — split hypothesis | open, data-side | read-only check script; fix follows evidence |
| 6 | Options regime series length depends on the data source | open | read-only check script + one conditional fix |
| 7 | POST /auto-trade/fire blocks the event loop | open | code (auto_trade.py, /fire only) |

## Files touched

Owned by P3c: `backend/app/routers/scan.py`, `backend/app/scoring/conviction_sizing.py`,
`backend/app/routers/auto_trade.py` (`fire_now` only), `frontend/lib/scanScheduleResolve.ts`,
`frontend/app/(frame)/settings/page.tsx` (`ScheduleEntryRow` only, for the 0% warning), their tests.
New: `backend/scripts/p3c_data_checks.py` (read-only), `backend/tests/test_p3c_*.py`.

NOT touched: `stock_scan.py` / `stock_scorer.py` (P3a — `_regime_data_drop` and `RuleResult.measured` are
CALLED/READ, not edited), `auto_trader.py` (P3b), `schemas/__init__.py` (see Q1),
`historical_store.py` (see item 5 — not owned by any package), `ScanFunnel`, `types/stockDomain.ts`,
`ArmRequest` (P6).

## 1. Options scan drops an Intraday name with no 15-min regime bars

Decision P3A-INTRADAY-REFUSAL-MATCHES-FIRE-2026-09-25 applies to the options scan (package text).

Today (`scan.py:567-623`): for timeframe `15min` a failed fetch logs a warning and sets `_regime_bars = []`;
the regime is then simply unmeasured and the name continues to pre-screen with `regime_signal=None`. The
auto-trader's fire on the same name raises `RegimeDataUnavailableError` (auto_trader.py ~:960-993) whenever
it measures — YAML `regime_gate.enabled` or regime sizing on.

Change, in `_process_symbol`:

- Initialise `_regime_bars: list[dict] = []`, `_regime_fetch_exc: Exception | None = None` and
  `_rcfg: dict | None = None` BEFORE the `try` at :569, so all three exist even when the config read raises.
- In the `except Exception as exc` of the intraday fetch (:588), also set `_regime_fetch_exc = exc`.
- Right after `_regime_gate = _resolve_regime_gate(...)` (:634-638), before the pre-screen:

  ```python
  if _rcfg is not None and (_drop := _regime_data_drop(
          symbol, _NO_REGIME_FILTER, _load_scoring_cfg(), _regime_gate, _rcfg,
          _regime_bars, _regime_fetch_exc)):
      log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": _drop["reason"]})
      return RejectedCandidate(symbol=symbol, reason=_drop["reason"])
  ```

  `_regime_data_drop` is imported from `app.routers.stock_scan` (no import cycle: stock_scan imports only
  the `regime` and `contracts` routers, neither imports `scan`). `_NO_REGIME_FILTER =
  SimpleNamespace(regime_filter=False)` is a module constant: the options request has no `regime_filter`
  field, so the helper's condition reduces to exactly the fire's (gate enabled OR sizing on). The helper
  already returns None for a daily timeframe and for a non-empty series (a short series still abstains,
  as on the fire).
- `_rcfg` is None only when `_scfg["regime"][horizon]` raised; today that name continues unmeasured and it
  still does (not this item's defect; the fire has its own `_load_regime_cfg` refusal path).

Funnel: add `_data_kw` entry — `_is_data` also matches `r.reason.startswith("regime data unavailable:")`.
Counting it under `failed_data` mirrors the stock scan, which counts the same reason under
`failed_history` ("no 15-min regime bars is a data drop, like no price" — stock_scan.py:479).
The Options funnel label "Data / Filters (data/price/cap)" is not changed (ScanFunnel is not P3c's).

Tests (`tests/test_p3c_options_regime_data.py`), driving `_process_symbol` with the fetch monkeypatched:

- Intraday, gate enabled, fetch raises → `RejectedCandidate`, reason starts `regime data unavailable:`
  and contains `fetch failed`; the chain fetch is NEVER called (assert the monkeypatched chain fetch was not awaited).
- Intraday, gate enabled, fetch returns `[]` → dropped, no `fetch failed` suffix.
- Intraday, gate disabled AND sizing disabled → not dropped (continues; the chain fetch is reached).
- Intraday, gate disabled, sizing block malformed → dropped (the helper fails closed).
- Intraday, fetch returns 5 bars (< min_obs) → not dropped by this rule.
- Swing with the same failing intraday fetch patched → not dropped (daily timeframe).
- Funnel: a scan whose only rejection is this reason reports `failed_data == 1`, `other_rejected == 0`.
- Anti-drift: `scan._regime_data_drop is stock_scan._regime_data_drop`.

## 2. Options direction gate removes an UNMEASURED trend

Today (`scan.py:1639-1668`): the gate runs after `gather`, on `TradeCardData`, and reads
`stockBreakdown.trend` — an int. `_rule_score` returns 50 when the card has no trend rule, and an
unmeasured rule carries a 0/50 placeholder, so the gate judges a placeholder.
The stock gate removes both cases as `direction_conviction_unmeasured: ...` (stock_scan.py:280-306,
decision P3A-UNMEASURED-TREND-REMOVE-2026-09-25).

Change — **inside `_process_symbol`, where the `StockScoreCard` is still in hand; no schema field**:

- `_process_symbol` gains a keyword `direction_min_trend: float | None = None`; `_execute_scan_core`
  passes `_direction_min_trend` (already resolved before the fan-out at :1489-1493).
- Directly after the final score gate (`if card.status == "REJECT": ...`, ~:747), before contract work:

  ```python
  if direction_min_trend is not None:
      _trend = next((r for r in card.rules if r.name == "trend"), None)
      if _trend is None or not getattr(_trend, "measured", True):
          _reason = f"direction_conviction_unmeasured: no trend measurement for {direction} {horizon}"
          log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": _reason})
          return RejectedCandidate(symbol=symbol, reason=_reason)
  ```

  Same exemption as the stock gate (`min_trend is None` → no check, which is how Intraday is excused),
  same reason text, same "no trend rule at all = unmeasured" rule.
- The post-gather floor at :1641 is unchanged (a measured trend below the floor is still `direction_conviction:`).
  Its comment block (:1650-1654, "An int: this gate cannot tell...") is rewritten to say the unmeasured case
  is removed earlier, in `_process_symbol`.
- Funnel: `_is_direction` matches both prefixes (`direction_conviction:` and `direction_conviction_unmeasured:`),
  and `failed_direction = sum(1 for r in rejected if _is_direction(r))` replaces the `direction_filtered_count`
  counter for the pipeline (the counter stays for the banner). So the residual does not absorb the new
  reason and `scanned == candidates + buckets` still holds.
- Banner: `not candidates and direction_filtered_count > 0` is unchanged — an unmeasured trend is "no data",
  not "market structure does not support", so it must NOT trigger the structure banner.

Why no schema field: the package allowed ONE `ScoreBreakdown` field shared with P6. Doing the check where
the card exists needs none, touches no shared file, and removes the P6 coordination. The cost: the options
funnel counts unmeasured drops under `failed_direction` (label "no conviction") instead of a separate
bucket as in the stock funnel — a separate bucket would need an `OptionsPipeline` field plus a ScanFunnel
change, neither P3c's. See Q1.

Tests (`tests/test_p3c_options_direction_unmeasured.py`):

- Swing Bullish, card with `trend` rule `measured=False` score 50 → rejected `direction_conviction_unmeasured:`,
  chain/contract work not reached.
- Same with `measured=True` score 50 and floor 40 → kept by this check.
- Card with no trend rule → rejected unmeasured.
- Intraday (floor None) with an unmeasured trend → kept.
- `_execute_scan_core` funnel: one unmeasured + one measured-below-floor → `failed_direction == 2`,
  `other_rejected == 0`, `direction_banner` None when a third candidate survives; and when BOTH are
  unmeasured and nothing survives, the structure banner is NOT shown.
- Reason text is byte-identical to `stock_scan._direction_conviction_drop`'s for the same inputs.

## 3. A 0% scan schedule warns that the 0% is ignored

Decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25: behaviour unchanged (the backend's
`_stored_zero_is_unset` maps `risk_pct: 0` to the 1% default); the UI says so.

- `scanScheduleResolve.ts` exports `scheduleRiskIgnored(entry: { mode: string; resolved_request: unknown }): boolean`
  — true when `mode === 'stocks'` and `resolved_request.risk_pct === 0`. The resolver itself keeps sending
  `maxLossPerTradePct` as-is (sending 0 is what the backend maps; changing the wire value would hide the
  0 from this check). Its header comment gains one line naming the decision.
- `ScheduleEntryRow` (settings/page.tsx) renders, under the mode tag, when `scheduleRiskIgnored(entry)`:
  `<Text size={11} tone="caution">Saved with 0% max loss per trade — ignored; this schedule runs at the 1% default. Set it in Settings → Risk, then re-save the profile.</Text>`
  Same placement and style as the existing `stale` caution line.
- Options entries are never flagged: the options request carries no `risk_pct`.

Tests (jest): `scheduleRiskIgnored` true for stocks/0, false for stocks/0.02, stocks/undefined, options;
a render test of `ScheduleEntryRow` (or the section with a mocked `api.getScanSchedule`) shows the text for a
stocks entry with `risk_pct: 0` and not for `0.02`.

## 4. conviction_sizing refusal messages

(10) is closed by P3b — recorded in the state entry, no code.

- (3) `min_mult` outside (0, 1]: the message is built per case instead of one sentence that names both
  "above 1" and "0":
  - `> 1`: "... is a FRACTION of full size, so a floor above 1 is not a floor at all" (+ hint, below).
  - `== 0`: the existing zero sentence + the existing "To stop trading in a headwind" advice.
  - `< 0`: "... is negative — a multiplier floor cannot be below 0; write a fraction in (0, 1], e.g. 0.3".
  All three keep the prefix `scoring_rules.yaml: regime_sizing.min_mult is {min_mult}, outside (0, 1]`.
- (4) the `/100` hint is offered only when the value reads as a whole percent: `min_mult` is an integer
  value in [2, 100]. `1.01` → no hint. `30` → "Did you mean 0.3?". `100` → "Did you mean 1?".
- (5) the `* 100` hint on `full_conviction_pct` is offered only when `full * 100` is itself accepted,
  i.e. `MIN_FULL_CONVICTION_PCT < full * 100 <= MAX_FULL_CONVICTION_PCT`. `0.004` → no hint; `0.4` → "40".
  The "sizes every order at FULL" sentence is unchanged.

Tests (extend `tests/test_conviction_sizing.py`): message for -0.1 contains "negative" and does NOT
contain "above 1" or "FALSY"; 1.01 has no "Did you mean"; 30 → "0.3"; 0 unchanged (existing test);
full 0.004 no "Did you mean"; full 0.4 → "40". All still raise `SizingConfigError`.

## 5. Negative bearish backtest price — measure, then fix

**Lead found while planning (not yet measured):** `historical_store._read_bars` (historical_store.py:133-165)
returns `close = raw_close × adj_factor` (fully adjusted) but `open`, `high`, `low` RAW. Across a split
inside the window, every pre-split bar's high/low sits at the pre-split price while its close is adjusted
down — e.g. WMT 3:1: high ≈ 3 × close on every pre-split bar. ATR (`high - low`, `|high - prev_close|`) is
then hugely inflated, and a bearish target `current - risk × mult` goes negative. This fits all four named
symbols and would ALSO inflate bullish ATR, stops and targets silently — for every consumer of `get_bars`,
both scans included.

`backend/scripts/p3c_data_checks.py`, read-only (sqlite `mode=ro` like `iv_basis_analysis.py`;
for a Postgres `DATABASE_URL` a read-only transaction `SET TRANSACTION READ ONLY`). It never calls `get_bars`
(which writes on a stale DB). For each symbol (default WMT CPRT TSCO SRE LYB, overridable):

- rows in `ohlcv_daily` over the scan window: count, date span, `source` mix, `adj_factor` / `split_factor` changes;
- max of `high / (raw_close × adj_factor)` and the largest one-day `|Δclose|` %, with dates;
- ATR(14) at the last bar computed three ways: as `_read_bars` returns it (mixed), fully raw, fully adjusted
  (OHLC all × adj_factor);
- the bearish pullback_ema target the mixed series would produce (strategy_engine's formula, called as a
  pure function on the rows) vs the fully-adjusted one.

Prints a table and a one-line verdict per symbol: `MIXED-ADJUSTMENT CONFIRMED` when the mixed ATR exceeds the
fully-adjusted ATR by > 2× and a split row exists, else `NOT REPRODUCED`.

**The fix is not in P3c's files.** If Kenneth's run confirms it, the fix (adjust open/high/low by the same
`adj_factor` in `_read_bars`) is logged as a new decision for Kenneth to assign: `historical_store.py`
is owned by no package and it changes every scan's numbers. P3c does not change it.

## 6. Options regime series length by source — measure, then fix

Today: the options regime measures `compute_omm` on `candles`, which is the DB window (~306 bars) or, on a
DB miss, `fetch_candles_async` (Tradier: 252; yfinance fallback: returned whole, ~1250).

Same script, second section: for each symbol, the series length from each source (DB rows over the
`[today-441d, today]` window read-only; `fetch_candles` from Tradier and yfinance with the cache bypassed —
GET-only provider reads, no DB writes), and `compute_omm` conviction/state on each, so Kenneth sees whether
the length difference flips a verdict on real data.

Conditional fix, applied only if the run shows a flip: in `_process_symbol`'s daily branch,
`_regime_bars = [b for b in candles if _bar_start_iso <= b["time"]]` — trim the fallback series by DATE to the
scan's own window start (passed in from `_execute_scan_core`), which is what the fire path's
`_fetch_scan_window_bars` does. A 252-bar Tradier series stays short (can't be lengthened) — stated as the
residual. Scoring `candles` are not trimmed (only the regime input).

## 7. POST /auto-trade/fire off the event loop

`fire_now` (auto_trade.py:199-262) calls `auto_trader.fire(...)` synchronously. `fire()` has blocking network
I/O (market-open check ~3s, regime fetch ≤ 8s deadline, broker order).

Change: `fired = await asyncio.to_thread(auto_trader.fire, portfolio_snapshot=..., portfolio_value=None, expect=_armed_state.strategy)`.
Precedent: `run_scan` already runs `maybe_fire_on_scan` → `fire()` in a worker thread (scan.py:1832), so
`fire()` is already exercised off-loop; it guards its state with a `threading.Lock`.
The DB read stays on the loop before the call; `book_fired_order(fired, db)` stays on the loop after it
(the session never enters the thread — the scan path's rule). The exception handlers are unchanged: exceptions
propagate out of `to_thread` with their type.

The comment block at :224-233 ("NOT REACHABLE OVER HTTP TODAY ... It stops holding the moment `fire()` moves
behind `asyncio.to_thread`") becomes true now: it is rewritten to say the `expect=` identity check is now the
live guard against a re-arm during the window, and the second concurrent `/fire` gets `ArmPreservedError` → 400.

Tests (`tests/test_p3c_fire_off_loop.py`):

- `fire` monkeypatched to `time.sleep(0.5)` then return a FiredOrder; while the request is in flight, a second
  cheap request (`GET /auto-trade/status`) completes before it — proving the loop is free.
- `fire` called on a thread other than the loop's (record `threading.get_ident()`).
- SizingConfigError → 500 and RuntimeError → 400 still mapped (existing tests re-run; one new assert each via to_thread).
- Two concurrent `/fire` calls on one armed strategy: exactly one order; the other 400.

## State updates (PROJECT_STATE.json)

On merge: open_questions [66], [67], [68], [69] closed with the commit; [15] items (3)(4)(5) fixed, (10) closed by
P3b; [42] and [43] updated with "check script shipped, awaiting Kenneth's run" (not closed). One new decision
per Q below once answered. Phase probe: a regex for `_NO_REGIME_FILTER` and `direction_conviction_unmeasured` in scan.py.

## Verification

`cd backend && pytest` (all), `cd frontend && npm run typecheck && npm run test`, `python3 scripts/state.py`.
The script: `python3 backend/scripts/p3c_data_checks.py --help` and a run against a fixture sqlite DB in a test
(`tests/test_p3c_data_checks.py`: builds a tiny `ohlcv_daily` with a 3:1 split, asserts the verdict is
`MIXED-ADJUSTMENT CONFIRMED`, asserts the file's mtime/contents are unchanged after the run).

## Open questions for Kenneth

- **Q1 (item 2):** do the unmeasured check inside `_process_symbol` with no schema field, counting it under the
  options funnel's "Direction conviction / no conviction" stage (recommended), or add the `ScoreBreakdown`
  field + a separate funnel bucket (needs `OptionsPipeline` + ScanFunnel, outside P3c)?
- **Q2 (item 5):** if the script confirms mixed adjustment, who fixes `historical_store._read_bars`? It is
  owned by no package and changes every scan's ATR, stops and targets.
