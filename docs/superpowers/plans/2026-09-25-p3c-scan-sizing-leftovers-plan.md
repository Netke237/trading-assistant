# P3c — Scan & sizing leftovers — plan

Package: P3c in `docs/superpowers/plans/2026-09-25-work-packages.md` (decision P3C-PACKAGE-CREATED-2026-09-25).
Branch `claude/confident-volta-mja4lz`, off main 2f67e6f. Claim `P3C-SCAN-SIZING-LEFTOVERS`.

Round history: r1 → 15 findings (2 HIGH, 7 MED, 6 LOW), addressed in r2. r2 → 13 findings (3 HIGH, 4 MED, 6 LOW),
addressed in r3. Logs at the end.

**Kenneth's decisions (2026-09-25, plan round 1):**
- P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25: item 2 is done inside the options scan's `_process_symbol` with
  no schema field; unmeasured drops count under the existing "Direction conviction" funnel stage.
- P3C-OWNS-READ-BARS-FIX-IF-CONFIRMED-2026-09-25: if the item-5 script confirms mixed/stale adjustment, P3c
  takes the `historical_store._read_bars` fix (scope widened to that file only, claimed before it is touched).

Every backlog entry was re-checked against 2f67e6f before this plan. The seven items and their state:

| # | Item | State on 2f67e6f | This plan |
|---|---|---|---|
| 1 | Options scan keeps an Intraday name whose 15-min regime fetch failed | open | code (scan.py) |
| 2 | Options direction gate judges an unmeasured trend placeholder | open | code (scan.py), **no schema field** (decision P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25) |
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
CALLED/READ, not edited), `auto_trader.py` (P3b), `schemas/__init__.py` (decision P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25),
`historical_store.py` (until item 5's evidence is in — see P3C-OWNS-READ-BARS-FIX-IF-CONFIRMED), `ScanFunnel`, `types/stockDomain.ts`,
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
- Classification guard (r2-L8): `test_every_options_reason_producer_is_classified`
  (test_scan_direction_funnel.py ~:240) only finds `reason="..."` literals, and this producer's literal lives in
  stock_scan.py. Add `("regime data unavailable: no completed 15-min bars for X", "failed_data")` to `_REAL_REASONS`.

**Existing tests this changes (round-1 H2).** The shipped config has `regime_gate.enabled: true` and
`regime_sizing.enabled: true`, so on shipped config an empty/failed Intraday fetch now returns BEFORE
`score_stock`:
- `tests/test_a4_intraday_regime_bars.py::test_options_scan_leaves_intraday_unmeasured_rather_than_falling_back_to_daily`
  is parametrized `[RuntimeError, [], INTRADAY[:10]]` and asserts `score.call_args.kwargs["regime_signal"] is None`.
  The `RuntimeError` and `[]` cases are split out: (a) on shipped config they assert the `RejectedCandidate`
  and `score.assert_not_called()` (the new behaviour); (b) with `_load_scoring_cfg` patched to a copy whose
  `regime_gate.enabled` and `regime_sizing.enabled` are both false, they keep the old assertion
  (unmeasured, no daily fallback) so that behaviour stays pinned. `INTRADAY[:10]` (short series) is unchanged.
- `tests/test_a4b_completed_intraday_bars.py` (:175 calls `_process_symbol` Intraday): re-checked during
  implementation; if its fixture yields zero completed bars it gets the same split. Every other `_process_symbol`
  test (test_scan_core, test_scan_db_first, test_scan_endpoint, test_scan_router_spreads, test_alternatives, …)
  is run; any Intraday case with an empty/failed intraday fetch is changed the same way and listed in the commit.

## 2. Options direction gate removes an UNMEASURED trend

Decision P3C-UNMEASURED-TREND-NO-SCHEMA-FIELD-2026-09-25.

Today (`scan.py:1639-1668`): the gate runs after `gather`, on `TradeCardData`, and reads
`stockBreakdown.trend` — an int. `_rule_score` returns 50 when the card has no trend rule, and an
unmeasured rule carries a 0/50 placeholder, so the gate judges a placeholder.
The stock gate removes both cases as `direction_conviction_unmeasured: ...` (stock_scan.py:277-306,
decision P3A-UNMEASURED-TREND-REMOVE-2026-09-25).

**Prerequisite — the options scan must be ABLE to measure relative strength (round-1 H1).** The options scan
never passes `benchmark_candles` to `score_stock`, so with `trend_method=relative_strength` (a Step-3 option
that `resolveOptionsScanRequest.ts:115-117` forwards in `overrides`) every card's trend is the
`measured=False` CAUTION 50 placeholder (stock_scorer.py:362-370). Today that placeholder passes the floor;
with the unmeasured check it would remove EVERY Swing/Position name. So, in `_execute_scan_core`, once before
the fan-out:

```python
_rs_bench = await _rs_benchmark_candles(SimpleNamespace(horizon=req.horizon, overrides=req.overrides or {}))
```

(`_rs_benchmark_candles` imported from `app.routers.stock_scan`, called not copied; it reads only
`req.horizon` / `req.overrides` via `resolve_rs_benchmark` and returns None when the method is not
relative_strength — the shipped `additive` method — so no existing scan fetches anything new.) The call is wrapped
in `try/except Exception` → `_rs_bench = None` + WARNING (r2-L11): `resolve_rs_benchmark` sits OUTSIDE the helper's
own try (stock_scan.py:336) and a malformed `trend` block raises KeyError, which must not 500 every options scan;
a None benchmark leaves the trend unmeasured, the fail-closed outcome. **Cost, stated (r2-L11):** when
relative_strength is on, this is one `get_bars` for the ETF proxy (SPY/QQQ) per scan — on a stale store that is a
5-year provider fetch AND a DB write (`get_bars` stores what it fetched), on the options path for the first time.
It is the same call the stock scan already makes per scan. `_process_symbol` gains `rs_benchmark: list[dict] | None = None` and
passes `benchmark_candles=_aligned_benchmark(rs_benchmark, candles)` (also imported from stock_scan) to BOTH
`score_stock` calls. The stock scan hands `bars[-120:]`; the options scan scores on its full `candles` — the
alignment is by last date, so the slice does not matter to `_aligned_benchmark`.
This is a behaviour change for relative_strength users of the options scan: the trend becomes a real reading
instead of a flat CAUTION 50. That is the options scan catching up with the stock scan, not a new rule.
A benchmark that is still missing (no ETF proxy, fetch failed, last dates differ) leaves the trend unmeasured,
and the name is removed as "no data", as in the stock scan. **Residual, stated (r2-M6):** unlike the stock scan,
an options name that missed the DB is scored on `fetch_candles_async` bars (Tradier/yfinance) while the benchmark
comes from the DB store; if their last dates differ `_aligned_benchmark` returns None and the name is removed as
unmeasured. The scan logs one INFO line per scan with the count of names whose benchmark failed to align
(`SCAN %s rs_benchmark: misaligned=%d of %d`), so a systematic loss is visible; logged as an open question.
Test: a DB-miss name whose fetched last date ≠ the benchmark's → removed unmeasured, counted in that line.

Change — **inside `_process_symbol`, on the PRE-SCREEN card, calling the stock helper**:

- `_process_symbol` gains `direction_min_trend: float | None = None`; `_execute_scan_core` passes
  `_direction_min_trend` (already resolved before the fan-out at :1489-1493).
- Directly after the pre-screen `if card_pre.status == "REJECT": ...` (~:657) and BEFORE the chain fetch
  (round-1 M3 — the trend rule does not read `iv_rank`, so `card_pre`'s trend is the final card's trend, and a
  dropped name costs no chain fetch):

  ```python
  _dc = _direction_conviction_drop(symbol, card_pre, direction_min_trend, direction, horizon)
  if _dc and _dc["reason"].startswith("direction_conviction_unmeasured:"):
      log_event("candidate_rejected", scan_id, {"symbol": symbol, "reason": _dc["reason"]})
      return RejectedCandidate(symbol=symbol, reason=_dc["reason"])
  ```

  `_direction_conviction_drop` is imported from stock_scan (round-1 M4 — called, not copied). Only its
  UNMEASURED verdict is acted on here; a measured-below-floor verdict is left to the existing post-gather
  gate, so this item does not move WHERE the measured floor runs. The helper's `min_trend is None` exemption
  is how Intraday is excused.
- The post-gather floor at :1641 is unchanged. Its comment block (:1650-1654, "An int: this gate cannot
  tell...") is rewritten: unmeasured trends never reach it, they are removed in `_process_symbol`.
- Funnel: `_is_direction` matches both prefixes (`direction_conviction:` and
  `direction_conviction_unmeasured:`), and the pipeline's `failed_direction = sum(1 for r in rejected if
  _is_direction(r))` (the `direction_filtered_count` counter stays for the banner). The residual does not
  absorb the new reason, and `scanned == candidates + buckets` still holds. The ScanFunnel subtracts stages in
  sequence, so the "Direction conviction" stage carries the extra count with no frontend change.
- Banner (r1-L13, corrected by r2-M5): the options banner is replaced by the STOCK banner's P3a-(c) form,
  word for word (stock_scan.py:1536-1551): `_dir_removed` counts both prefixes; when `not candidates and
  _dir_removed > 0` → `"No {direction} candidates survived. The direction-conviction gate removed {_dir_removed}
  of {len(symbols)}{ (trend below X) if floor }{; the rest were removed by other gates — see the pipeline}."`.
  The "market structure does not support …" text is deleted — it states a cause the scan did not measure,
  the defect P3a removed on the stock side. The CAUTION-grade branch is unchanged.
- Funnel presentation, stated (r2-M7): by decision the unmeasured drops count under the "Direction conviction"
  stage; the ScanFunnel subtracts stages in order (data → pre-screen → chain → score+contracts → direction), so
  it will show those names as having passed chain and contracts, under the label "no conviction". ScanFunnel is
  not P3c's; an open question is logged for its owner: a separate `failed_direction_unmeasured` stage after
  pre-screen, as the stock funnel has (ScanFunnel :110-116).

Tests (`tests/test_p3c_options_direction_unmeasured.py`):

- Swing Bullish, `score_stock` patched so `card_pre` has `trend` `measured=False` score 50 → rejected
  `direction_conviction_unmeasured:`, `fetch_option_chain_async` NOT awaited.
- Same with `measured=True` score 50, floor 40 → not rejected by this check (chain fetch reached).
- `card_pre` with no trend rule → rejected unmeasured.
- Intraday (floor None) with an unmeasured trend → not rejected.
- relative_strength: `_execute_scan_core` with `overrides={"trend_method": "relative_strength"}` and a patched
  benchmark fetch returning aligned bars → `score_stock` received non-None `benchmark_candles` in both calls;
  with the benchmark fetch returning None → the name is removed unmeasured.
- Funnel: one unmeasured + one measured-below-floor + one kept → `failed_direction == 2`, `other_rejected == 0`,
  no banner; both removed and nothing kept → banner equals the stock form ("removed 2 of 2"), and contains no
  "market structure"; the existing banner tests in test_scan_direction_funnel.py that assert the old text are
  updated to the new text (listed in the commit).
- Classification guard (r2-L8): add `("direction_conviction_unmeasured: no trend measurement for Bullish Swing",
  "failed_direction")` to `_REAL_REASONS`.

**Existing tests this changes (r2-H1).** `tests/test_scan_endpoint.py::_force_passing_stock_score` (:185-196)
returns a `StockScoreCard` with no rules; through `POST /api/scan` (Swing/Bullish) `direction_min_trend` is now
set, and "no trend rule" is unmeasured, so all 8 users lose their only candidate. The fixture is changed to carry
`rules=[RuleResult("trend", "PASS", 80, {})]` (measured by default). Every other fixture that patches `score_stock`
with a rule-less card and runs through `_execute_scan_core` gets the same change; the full suite is run and each
changed file is listed in the commit.
- Anti-drift: `scan._direction_conviction_drop is stock_scan._direction_conviction_drop`, same for
  `_rs_benchmark_candles` and `_aligned_benchmark`.

Stale comments outside P3c (round-1 L12): stock_scan.py :285-287 ("The unmeasured check below is stock-scan
only") and :300-301 ("The options gate ... cannot see this") become false. stock_scan.py is not P3c's — logged
as an open_questions entry for its next owner, text included.

## 3. A 0% scan schedule warns that the 0% is ignored

Decision P3C-SCHEDULE-ZERO-RISK-WARNS-2026-09-25: behaviour unchanged (the backend's
`_stored_zero_is_unset` maps `risk_pct: 0` to the 1% default); the UI says so.

- `scanScheduleResolve.ts` exports `scheduleRiskIgnored(entry: { mode: string; resolved_request: unknown }): boolean`
  — true when `mode === 'stocks'`, `resolved_request` is a non-null object, `'risk_pct' in resolved_request`,
  and `resolved_request.risk_pct === 0`. The resolver itself keeps sending
  `maxLossPerTradePct` as-is (sending 0 is what the backend maps; changing the wire value would hide the
  0 from this check). Its header comment gains one line naming the decision.
- `ScheduleEntryRow` (settings/page.tsx) renders, under the mode tag, when `scheduleRiskIgnored(entry)`:
  `<Text size={11} tone="caution">Saved with 0% max loss per trade — ignored; this schedule runs at the 1% default (conviction-adjusted). Set it in Settings → Risk, then re-save the profile.</Text>`
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
- (4) the `/100` hint is offered only when the value reads as a whole percent: `float(min_mult).is_integer()`
  and `2 <= min_mult <= 100` (so YAML `30.0` still gets the hint). `1.01` → no hint. `30` → "Did you mean 0.3?". `100` → "Did you mean 1?".
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
(which writes on a stale DB). Window (r2-H2): `[today - 5×365d, today]` — `_HISTORY_YEARS = 5` (stock_scan.py:450), the span `get_bars` serves the
backtest where the negative price happens. The splits (WMT 3:1 Feb 2024, TSCO 5:1 Dec 2024, CPRT and SRE 2023) are
outside the 441-day regime window, so that window cannot see them.
For each symbol (default WMT CPRT TSCO SRE LYB, overridable):

- rows in `ohlcv_daily` over the scan window: count, date span, `source` mix, `adj_factor` / `split_factor` changes;
- max of `high / (raw_close × adj_factor)` and the largest one-day `|Δclose|` %, with dates;
- ATR(14) at the last bar computed three ways: as `_read_bars` returns it (mixed), fully raw, fully adjusted
  (OHLC all × adj_factor);
- the bearish pullback_ema target the mixed series would produce (strategy_engine's formula, called as a
  pure function on the rows) vs the fully-adjusted one.

Split detection does NOT rely on `split_factor` (round-1 M5: the Alpaca normaliser, the primary provider,
hard-codes `split_factor: 1.0`, alpaca.py:117). A split is detected from consecutive rows: a one-day
`raw_close` ratio within 3% of a common split ratio (2, 3, 4, 5, 10, 20, 1/2, 1/3 …), reported with its date.
`get_bars` only appends `last+1 → end` and never rewrites old rows (historical_store.py:230-233), so rows
stored before a split may keep a stale `adj_factor`. Per symbol the script prints ONE of:

- `STALE ADJ_FACTOR` — the adjusted close (`raw_close × adj_factor`, what `_read_bars` returns) itself jumps
  by a split ratio at a detected split date (adjustment never applied to old rows);
- `MIXED ADJUSTMENT` — adjusted close is continuous across the split but `high / adjusted_close` on the
  pre-split rows is ≈ the split ratio (raw high/low next to adjusted close);
- `NO SPLIT IN WINDOW` / `CLEAN`.

plus, over EVERY bar of the window (r2-H2 — the last bar is post-split and clean, so it cannot show this):
the maximum ratio of ATR(14) as `_read_bars` returns the series to ATR(14) on a series rebuilt from raw OHLC with
the detected split ratios applied backwards (independent of stored `adj_factor`), and the MINIMUM bearish
pullback_ema target (`current - risk × rr_target_mult`, strategy_engine's formula as a pure function) on each
series, with dates; and the same values on the 5 bars either side of each detected split.
LYB had no split: for it the script prints `NO SPLIT IN WINDOW` and the line "the split hypothesis does not
explain LYB's negative target" with its minimum target, so the evidence is not over-read.

**Fix, only after Kenneth's run (P3C-OWNS-READ-BARS-FIX-IF-CONFIRMED-2026-09-25).** P3c claims
`historical_store.py` first (`claim.py take P3C-READ-BARS-ADJUSTMENT`) and plans the fix as its own audited round:
`MIXED ADJUSTMENT` → scale open/high/low by the same `adj_factor` in `_read_bars`; `STALE ADJ_FACTOR` → a
re-adjustment of stored rows is a data migration, planned separately. No code in this round.

Fixture test builds BOTH row shapes: Alpaca-shaped (`split_factor` 1.0, correct `adj_factor`, raw OHLC) →
`MIXED ADJUSTMENT`; stale (pre-split `adj_factor` 1.0) → `STALE ADJ_FACTOR`; no split → `NO SPLIT IN WINDOW`.

## 6. Options regime series length by source — measure, then fix

Today: the options regime measures `compute_omm` on `candles`, which is the DB window (~306 bars) or, on a
DB miss, `fetch_candles_async` (Tradier: 252; yfinance fallback: returned whole, ~1250).

Same script, second section, per symbol — the three series the options scan can measure on:

- **DB**: `ohlcv_daily` rows over `[today-441d, today]`, read-only, converted exactly as `_read_bars` does.
- **Tradier path**: `await market.fetch_candles_async(client, symbol)` (default `bars=252`) with
  `market._candles_cache.pop(symbol, None)` first, and the yfinance fallback `market._fetch_daily_yf`
  (market.py:121, reached at :1301) patched to return `[]`, so the answer is Tradier's alone.
- **yfinance path**: the same call with a client built on `httpx.MockTransport` that raises on every request
  (so the Tradier try fails at market.py ~:1272 and falls through to `_fetch_daily_yf`), cache popped again.
The script is its own process, so popping the in-memory cache touches no server. GETs only; no DB writes.
For each: length, first/last date, and `compute_omm` state/conviction with the horizon's `regime` block —
so Kenneth sees whether the length difference flips a verdict on real data.

Conditional fix, applied only if the run shows a flip: in `_process_symbol`'s daily branch,
`_regime_bars = [b for b in candles if str(b["time"])[:10] >= _bar_start_iso]` — trim by DATE (compared on
`str(time)[:10]`, as the fire path does) to the scan's own window start, passed in from `_execute_scan_core`.
Residuals, stated: a 252-bar Tradier series stays short (cannot be lengthened); the END is not changed —
the fire path drops today's unclosed bar (auto_trader.py ~:737-800, Option A) and the scan's DB window ends
`today`; that end difference is a separate scan-vs-fire question, logged, not in item 6. Scoring `candles` are
not trimmed (only the regime input).

## 7. POST /auto-trade/fire off the event loop

`fire_now` (auto_trade.py:199-262) calls `auto_trader.fire(...)` synchronously. `fire()` has blocking network
I/O (market-open check ~3s, regime fetch ≤ 25s deadline since P3b — auto_trader.py:582-587, broker order).

Change: `fire()` runs on a DEDICATED single-worker executor, `_FIRE_EXECUTOR =
ThreadPoolExecutor(max_workers=1, thread_name_prefix="auto-trade-fire")` in auto_trade.py, via
`loop.run_in_executor` (r2-L13): the default executor is shared with a running scan's `to_thread` calls (intraday
fetch, HMM, confidence, quotes), so a manual fire during a large scan could queue before its market-open check
even starts. One worker also SERIALISES two concurrent `/fire` calls: the second enters `fire()` only after the
first has disarmed, and gets `ArmPreservedError` → 400.
Precedent that `fire()` is safe off the loop: `run_scan` already runs `maybe_fire_on_scan` → `fire()` in a worker
thread (scan.py:1832); `fire()` guards its state with a `threading.Lock`. The DB read stays on the loop before the
call; `book_fired_order(fired, db)` stays on the loop after it (the session never enters the thread). Exceptions
propagate from the executor with their type, so the handlers are unchanged. The executor's worker is a normal
non-daemon thread, joined at interpreter exit like the default executor's.

The comment block at :224-233 ("NOT REACHABLE OVER HTTP TODAY ... It stops holding the moment `fire()` moves
behind `asyncio.to_thread`") is rewritten: `fire()` now runs off the loop, the single-worker executor serialises
`/fire` calls, and `expect=` stays the guard against a re-arm by any other producer during the window.

**Cancellation (r1-M9, corrected by r2-M4).** Main.py installs only CORSMiddleware, so a client disconnect does not
cancel the handler; a forced/timed-out shutdown does, and then `asyncio.run`'s teardown cancels every task —
an asyncio-side done-callback would see only "cancelled" and lose the result. So the logging is on the THREAD
side: the handler captures `armed_symbol = _armed_state.strategy.symbol` before the call and submits
`_fire_and_report(cancelled: threading.Event, armed_symbol, **kwargs)`, which calls `auto_trader.fire(...)` and,
when it returns or raises, checks `cancelled.is_set()`; if set it logs at ERROR
`"POST /auto-trade/fire for {symbol} was cancelled while fire() ran; this outcome was NOT booked: {FiredOrder or
exception}"` — then returns/re-raises as before. The handler, on `CancelledError` at the await, sets `cancelled`,
and — if the executor future is already done and not cancelled (the thread finished just before the cancel) —
logs the same line itself from the future's result, then re-raises. The executor's thread is joined at shutdown,
so the thread-side line is written. Booking is not attempted after a cancel (the request's session is gone).
The same gap on `run_scan`'s `maybe_fire_on_scan` call is logged as an open question.

Stale docstrings outside P3c (round-1 L11): auto_trader.py:1548-1550 ("reachable from the event-loop thread,
via the /fire endpoint, where asyncio.run raises") and :2280-2283 ("a manual POST /auto-trade/fire on the event
loop") become false. auto_trader.py is P3b's — logged as an open_questions entry with the replacement text.

Tests (`tests/test_p3c_fire_off_loop.py`):

- `fire` monkeypatched to `time.sleep(0.5)` then return a FiredOrder; while the request is in flight, a second
  request (`GET /auto-trade/status`) completes first — the loop is free.
- `fire` runs on a thread named `auto-trade-fire*`, not the loop's thread.
- SizingConfigError → 500 and RuntimeError → 400 still mapped (existing tests re-run, plus one each here).
- Two concurrent `/fire` on one armed strategy (r2-H3 — the two 400 texts are identical, so the test does not
  compare detail text): a wrapper around the real `fire` records (enter, exit, raised-type) per call. Assert:
  `execute_option_order` called exactly once; one 200 and one 400; the recorded calls did not overlap (the
  second's enter ≥ the first's exit — serialisation); and EITHER the wrapper recorded two calls with exactly one
  `ArmPreservedError` raised from inside `fire()`, OR it recorded one call (the loser stopped at the endpoint's
  own armed check) — both are correct refusals, and the test says which it saw.
- Cancellation: `fire` held on a `threading.Event`; the handler task is cancelled; the Event is released; assert
  the ERROR line names the symbol and the FiredOrder, and `book_fired_order` was not called. Second case: the
  future completes, then the cancel lands before the await resumes → the handler-side line is logged.

## State updates (PROJECT_STATE.json)

On merge, entries named by their opening text (round-1 L15 — indices shift under parallel sessions):
"LOGGED BY P3a (2026-09-25), NOT FIXED, outside P3a's files", "LOGGED BY P3a (2026-09-25), NOT FIXED: the options
direction", "LOGGED BY P3a (2026-09-25), NOTE: frontend", "LOGGED BY P3c SETUP" closed with the commit;
"P3a (2026-09-25) FIXED the stock_scan.py items" gets (3)(4)(5) fixed, (10) closed by P3b; "P3a (2026-09-25)
FIXED (a) _build_target_ladder" and "P3a (2026-09-25) FIXED the comment (441" updated with "check script
shipped, awaiting Kenneth's run" (not closed). New entries: the stale stock_scan.py and auto_trader.py
comments (L11, L12), the scan-vs-fire END difference (item 6), `run_scan`'s cancellation gap (item 7),
the relative_strength DB-miss misalignment residual (r2-M6), the ScanFunnel unmeasured stage (r2-M7).
The two Kenneth decisions above go to the front of `decisions`. One new decision
per Q below once answered. Phase probe: a regex for `_NO_REGIME_FILTER` and `direction_conviction_unmeasured` in scan.py.

## Verification

`cd backend && pytest` (all), `cd frontend && npm run typecheck && npm run test`, `python3 scripts/state.py`.
The script: `python3 backend/scripts/p3c_data_checks.py --help`; sections chosen by `--sections db,sources`
(default both; `sources` is the only one that touches the network — r2-L10). `tests/test_p3c_data_checks.py` runs
`--sections db` only, against a fixture sqlite `ohlcv_daily` with three symbols — Alpaca-shaped 3:1 split
(`split_factor` 1.0, correct `adj_factor`, raw OHLC) → `MIXED ADJUSTMENT`; stale pre-split `adj_factor` 1.0 →
`STALE ADJ_FACTOR`; no split → `NO SPLIT IN WINDOW` — and asserts the DB file's bytes and mtime are unchanged
after the run, and that no socket was opened (socket.socket patched to raise). Verdict strings are exactly the
four in §5: `STALE ADJ_FACTOR`, `MIXED ADJUSTMENT`, `NO SPLIT IN WINDOW`, `CLEAN` (r2-L9).

## Open questions for Kenneth

None open. Q1 and Q2 of r1 were answered (decisions at the top).

## Round-1 log (15 findings)

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | relative_strength is always unmeasured in options → item 2 would drop every name | fixed: options scan fetches + aligns the benchmark via stock_scan's helpers |
| 2 | HIGH | test_a4 Intraday-unmeasured test breaks on shipped config | fixed: named, split into drop-on-shipped + unmeasured-with-gate/sizing-off |
| 3 | MED | unmeasured check after chain fetch; test unprovable | fixed: runs on `card_pre`, before the chain fetch |
| 4 | MED | copied the helper's logic | fixed: calls `_direction_conviction_drop`, anti-drift `is` test |
| 5 | MED | script verdict misses Alpaca rows / stale adj_factor | fixed: split detection from raw ratios, two verdicts, both fixture shapes |
| 6 | MED | item-6 fix trims one end only | fixed: date compare on `[:10]`, end difference stated as residual + logged |
| 7 | MED | "cache bypassed / each source" named nothing real | fixed: exact calls, cache pop in a separate process, provider isolation by patching |
| 8 | MED | concurrency test passes on the wrong 400 | fixed: Event-held first fire, asserts ArmPreservedError detail + one order |
| 9 | MED | cancelled /fire leaves an unbooked order | fixed: shield + ERROR log callback; run_scan gap logged |
| 10 | LOW | deadline is 25s, not 8s | fixed |
| 11 | LOW | stale auto_trader docstrings | logged for P3b's owner (not P3c's file) |
| 12 | LOW | stale stock_scan comments | logged for its owner (not P3c's file) |
| 13 | LOW | all-unmeasured empty result unexplained | fixed: new "could not be measured" banner branch |
| 14 | LOW | warning text / type guard | fixed |
| 15 | LOW | is_integer; state entries by index | fixed |

## Round-2 log (13 findings)

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | HIGH | 8 test_scan_endpoint tests use rule-less cards → dropped as unmeasured | fixed: fixture carries a measured trend rule; other such fixtures listed |
| 2 | HIGH | script window (441d) and last-bar ATR cannot see 2023-24 splits | fixed: 5-year window, max/min over every bar + around splits, LYB stated |
| 3 | HIGH | concurrency test cannot tell the two identical 400 texts apart | fixed: wrapper records calls; one order, no overlap, either refusal path named |
| 4 | MED | cancellation callback loses the result on shutdown | fixed: thread-side logging on a threading.Event + handler-side for the done case |
| 5 | MED | new banner branch diverges from P3a's stock banner | fixed: options banner = stock banner word for word; "market structure" text deleted |
| 6 | MED | DB-miss names vs DB benchmark misalign under relative_strength | stated as residual, per-scan count logged, test, open question |
| 7 | MED | funnel shows unmeasured drops after chain/contracts, labelled "no conviction" | stated; open question for ScanFunnel's owner |
| 8 | LOW | classification guard misses the two new reasons | fixed: both added to `_REAL_REASONS` |
| 9 | LOW | verdict strings inconsistent | fixed: one set of four |
| 10 | LOW | script test would hit the network | fixed: `--sections`, test runs `db` only, socket patched to raise |
| 11 | LOW | benchmark call can raise; writes to DB | fixed: wrapped → None; cost and write stated |
| 12 | LOW | dangling "see Q1" | fixed: points to the decision |
| 13 | LOW | manual fire can queue behind a scan on the default executor | fixed: dedicated single-worker executor |
