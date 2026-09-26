# P3c — Scan & sizing leftovers — plan

Package: P3c in `docs/superpowers/plans/2026-09-25-work-packages.md` (decision P3C-PACKAGE-CREATED-2026-09-25).
Branch `claude/confident-volta-mja4lz` (r1-r4), continued on `claude/clever-planck-rpz8yh` from r5 (claim expired
and re-taken 2026-09-26, no new commits on the old branch), off main 2f67e6f. Claim `P3C-SCAN-SIZING-LEFTOVERS`.

Round history: r1 → 15 findings (2 HIGH, 7 MED, 6 LOW), addressed in r2. r2 → 13 findings (3 HIGH, 4 MED, 6 LOW),
addressed in r3. r3 → 7 findings (0 HIGH, 3 MED, 4 LOW), addressed in r4. r4 → 6 findings (0 HIGH, 1 MED, 5 LOW),
addressed in r5. r5 → round 5 limited to §7: 5 findings (0 HIGH, 3 MED, 2 LOW), addressed in r6. r6 → round 6 (§7): 4 LOW, addressed in r7. r7 → round 7 (§7): 2 LOW, addressed in r8. r8 → round 8 (§7): 3 LOW,
addressed in r9. r9 → round 9 (§7): 1 LOW, addressed in
r10. r10 → round 10 (§7): 3 findings (1 MED, 2 LOW), addressed in r11. r11 → round 11 (§7): 1 LOW, addressed in r12.
r12 → round 12 (the unaudited r5 edits to §2-§5 + §7's r12 fix): 6 findings (1 MED, 5 LOW), addressed in r13.
r13 → round 13 (the r13 fixes): 4 LOW, addressed in r14. r14 → round 14: 4 LOW, all the same class (the hand-copied
setup rules drift from the code), addressed in r15 by calling the real signal instead. r15 → round 15 (§5): 7 findings (1 MED,
6 LOW), addressed in r16. r16 → round 16 (§5): 3 LOW, addressed in r17. r17 → round 17: 2 LOW, addressed in r18. r18 → round 18: 3 LOW, addressed in r19. r19 → round 19 (FULL plan vs merged main): 8 LOW, addressed in r20. r20 → round 20: 4 LOW, addressed in r21. r21 → round 21: 4 findings (1 HIGH, 1 MED, 2 LOW), addressed in r22.
Logs at the end.

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
| 4 | conviction_sizing messages (3)(4)(5) + (10) | (10) FIXED by P3b (ERROR once per process, `_ZERO_FULL_LOGGED`, conviction_sizing.py:160-166 flag, :226-239 ERROR-then-DEBUG); (3)(4)(5) open | code (conviction_sizing.py) |
| 5 | Negative bearish backtest price — split hypothesis | open, data-side | read-only check script; fix follows evidence |
| 6 | Options regime series length depends on the data source | open | read-only check script + one conditional fix |
| 7 | POST /auto-trade/fire blocks the event loop | open | code (auto_trade.py, /fire only) |

## Files touched

Owned by P3c: `backend/app/routers/scan.py`, `backend/app/scoring/conviction_sizing.py`,
`backend/app/routers/auto_trade.py` (`fire_now` only), `frontend/lib/scanScheduleResolve.ts`,
`frontend/app/(frame)/settings/page.tsx` (`ScheduleEntryRow` only, for the 0% warning), their tests —
including the `_FakeDb` classes in `backend/tests/test_auto_trader.py` (:3491), `test_autotrade_a6_a7.py` (:194)
and `test_autotrade_a9.py` (:139), which gain `async def rollback(self): pass` for §7 (r5-M1).
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
passes `benchmark_candles=_bench` (`_bench = _aligned_benchmark(rs_benchmark, candles)`, computed once; helper
imported from stock_scan) to BOTH `score_stock` calls. The stock scan hands `bars[-120:]`; the options scan scores on its full `candles` — the
alignment is by last date, so the slice does not matter to `_aligned_benchmark`.
This is a behaviour change for relative_strength users of the options scan: the trend becomes a real reading
instead of a flat CAUTION 50. That is the options scan catching up with the stock scan, not a new rule.
A benchmark that is still missing (no ETF proxy, fetch failed, last dates differ) leaves the trend unmeasured,
and the name is removed as "no data", as in the stock scan. **Residual, stated (r2-M6):** unlike the stock scan,
an options name that missed the DB is scored on `fetch_candles_async` bars (Tradier/yfinance) while the benchmark
comes from the DB store; if their last dates differ `_aligned_benchmark` returns None and the name is removed as
unmeasured. The scan logs one INFO line per scan with the count of names whose benchmark failed to align
(`SCAN %s rs_benchmark: misaligned=%d of %d`), so a systematic loss is visible; logged as an open question.
**How the count gets back (r3-M2):** the reject reason cannot carry it (every unmeasured drop gets the same
`_direction_conviction_drop` text, and `_process_symbol` returns only `TradeCardData | RejectedCandidate`), and
`_execute_scan_core` has no candles for DB-miss names to recompute it. So `_execute_scan_core` creates
`_rs_misaligned: list[str] = []` before the fan-out and passes it as `_process_symbol(..., rs_misaligned=...)`
(default None); `_process_symbol` computes `_bench = _aligned_benchmark(rs_benchmark, candles)` once, and when
`rs_benchmark is not None and _bench is None` appends `symbol`. All `_process_symbol` calls run as coroutines on
the one event loop (`gather`), so the append needs no lock. After `gather` the line logs `len(_rs_misaligned)`
of `len(symbols)`, only when `_rs_bench is not None`.
Test: a DB-miss name whose fetched last date ≠ the benchmark's → removed unmeasured, and the INFO line reads
`misaligned=1 of 1` (caplog).

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
  _is_direction(r))`. (r4-L3) The `direction_filtered_count` counter (scan.py:1640, :1657) is DELETED: both its
  readers — the banner at :1673 and `failed_direction=` at :1732 — read `_dir_removed = sum(1 for r in rejected if
  _is_direction(r))` instead, so an all-unmeasured scan shows the banner. Placement (r12-F3 — `_is_direction` is
  today a nested def at :1721, inside the funnel block, AFTER the banner at :1673; reading it at the banner would
  raise UnboundLocalError): `_is_direction` (both prefixes) and `_dir_removed` are defined ONCE, right after the
  post-gather gate and before the banner; the funnel block drops its own `_is_direction` def, keeps the name in
  `_buckets`, and passes `failed_direction=_dir_removed`. The residual does not
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
- Intraday (floor None) with an unmeasured trend → not rejected. The 15-min fetch is stubbed (r19-L5): on shipped
  config (gate + sizing on) a failed or empty `fetch_intraday_candles` hits §1's drop first, and unpatched it is a
  live call — patch `app.routers.scan.fetch_intraday_candles` to return completed bars (`test_a4_intraday_regime_bars.INTRADAY`).
- relative_strength: `_execute_scan_core` with `overrides={"trend_method": "relative_strength"}` and
  `app.routers.scan._rs_benchmark_candles` patched with an `AsyncMock` (r19-L6: scan.py imports it by name, so
  patching `stock_scan._rs_benchmark_candles` has no effect, and the real helper calls the unstubbed
  `stock_scan.get_historical_bars`) returning aligned bars → `score_stock` received non-None `benchmark_candles` in both calls;
  with the benchmark fetch returning None → the name is removed unmeasured.
- Funnel: one unmeasured + one measured-below-floor + one kept → `failed_direction == 2`, `other_rejected == 0`,
  no banner; both removed and nothing kept → banner equals the stock form ("removed 2 of 2"), and contains no
  "market structure". (r3-L5: no existing backend test asserts the old text — test_scan_direction_funnel.py:150,
  :162 only check truthiness, so none change. The only copy of the old text is a frontend fixture,
  `step-4-ranking/__tests__/emptyStateBanner.test.tsx:21-22`, outside P3c's files; it still passes but is now
  misleading — logged as an open question for its owner.)
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
only") and :297-298 ("The options gate ... cannot see this") become false. stock_scan.py is not P3c's — logged
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
a render test of `SettingsPage` (r3-L6: `ScheduleEntryRow` is private, page.tsx:742, and a Next 15 `page.tsx`
may not add named exports), navigated to the Scan section — the pattern `__tests__/RiskForm.hydration.test.tsx`
already uses — shows the text for a stocks entry with `risk_pct: 0` and not for `0.02`. The `@/lib/api` mock
(r4-L2 — the RiskForm mock holds only `postCredentials`, and no existing test renders the Scan section) returns a
resolved value for EVERY `api.*` call made while that section mounts, not only the two under test: the Scan
section mounts `OperatorTimezoneSection` (`getSchedulingTimezone`, page.tsx:497), `ScheduledScanRetentionSection`
(`getScheduledScanRunRetention`, :550) and `ScheduledScansSection` (`getScanSchedule`, `getScanScheduleEntryRuns`,
:623/:627), page.tsx:483-485. The implementer lists every call reached from the section's mount (grep of
`api\.` and of any store `fetch*` in the components it renders) in the test's header comment, and each is mocked;
a missing one throws `undefined is not a function` in an effect and fails the render.

## 4. conviction_sizing refusal messages

(10) is closed by P3b — recorded in the state entry, no code.

- (3) `min_mult` outside (0, 1]: the message is built per case instead of one sentence that names both
  "above 1" and "0":
  - `> 1`: "... is a FRACTION of full size, so a floor above 1 is not a floor at all" (+ hint, below).
  - `== 0` (r3-M3 — the existing zero sentence is FALSE since P3a removed `or 0.01`: a 0 multiplier no longer
    falls through to 1%): "... a floor of 0 does not remove the position: at or beyond -full_conviction_pct, and
    whenever the regime is unmeasured (the floor itself is used), the multiplier is 0 and the order is still the
    MINIMUM — 1 share on the stock card (`max(1, …)`, stock_scan.py:1016) and 1 contract on the fire path
    (`_sized_quantity`'s `max(1, …)`, auto_trader.py:1392) — never zero." (r4-L5: on the two-sided ramp `lo=0`
    gives `mult = frac`, which is 0 only at conviction ≤ -full; a milder headwind sizes a nonzero fraction, so "in
    every headwind" was wrong. r12-F4: an unmeasured regime also uses the floor — stock_scan.py:1264-1271
    `mult = _sizing[0]` / `floor:unmeasured`, auto_trader.py:1476-1488 `_sized_quantity(strategy.quantity,
    min_mult)` — e.g. an Intraday name whose 15-min fetch failed.) + the existing "To stop trading in a headwind"
    advice.
  - Stale text corrected in the same commit (r3-M3 + r4-L5), every place that restates the fall-through to 1% or
    the doubling (line refs re-checked in r12-F6): conviction_sizing.py:285-308 (the "ZERO IS REFUSED TOO" block —
    the `stock_scan.py:685` / FALSY / "doubled" sentences); test_conviction_sizing.py:387-394 (the "CORRECTED
    2026-09-17" comment), :438-463 (the zero test — renamed
    `test_a_zero_min_mult_is_refused_because_it_still_sizes_the_minimum`, docstring and asserts rewritten), and
    :466-470 (docstring of `test_the_multiplier_can_no_longer_reach_a_falsy_zero`; the test's own assert is
    unchanged). NOT everything there is stale (r12-F5): P3a removed only `risk_pct or 0.01`; `risk_fixed if
    risk_fixed` is still at stock_scan.py:1015 and `risk_fixed_usd` has no `gt=0` (schemas/stock_scan.py:52), so a
    fixed $0 still falls through to pct sizing. Both the :304-308 "THE FALSY READ ... IS STILL THERE" sentence and
    the :466-470 docstring are therefore reworded, not deleted, to: "`risk_pct or 0.01` was removed by P3a;
    `risk_fixed if risk_fixed` (stock_scan.py:1015) remains, and is harmless here because the pct branch is
    multiplied by the same `mult`". The history ("admitted until 2026-09-17") stays.
  - `< 0`: "... is negative — a multiplier floor cannot be below 0; write a fraction in (0, 1], e.g. 0.3".
  All three keep the prefix `scoring_rules.yaml: regime_sizing.min_mult is {min_mult}, outside (0, 1]`.
- (4) the `/100` hint is offered only when the value reads as a whole percent: `float(min_mult).is_integer()`
  and `2 <= min_mult <= 100` (so YAML `30.0` still gets the hint). `1.01` → no hint. `30` → "Did you mean 0.3?". `100` → "Did you mean 1?".
- (5) the `* 100` hint on `full_conviction_pct` is offered only when `full * 100` is itself accepted,
  i.e. `MIN_FULL_CONVICTION_PCT < full * 100 <= MAX_FULL_CONVICTION_PCT`. `0.004` → no hint; `0.4` → "40".
  The "sizes every order at FULL" sentence is unchanged.

Tests (extend `tests/test_conviction_sizing.py`): message for -0.1 contains "negative" and does NOT
contain "above 1" or "FALSY"; 1.01 has no "Did you mean"; 30 → "0.3"; 0 → contains "1 share" and "do not set
the floor to zero" and NOT "1%" / "FALSY" — the existing zero test (test_conviction_sizing.py:438-463, asserts
`"1%" in msg`) and its docstring are rewritten to the current behaviour in the same commit (r3-M3), and also
asserts the message names the unmeasured case ("unmeasured", r12-F4);
full 0.004 no "Did you mean"; full 0.4 → "40". All still raise `SizingConfigError`.

## 5. Negative bearish backtest price — measure, then fix

**Lead found while planning (not yet measured):** `historical_store._read_bars` (historical_store.py:133-165)
returns `close = raw_close × adj_factor` (fully adjusted) but `open`, `high`, `low` RAW. Across a split
inside the window, every pre-split bar's high/low sits at the pre-split price while its close is adjusted
down — e.g. WMT 3:1: high ≈ 3 × close on every pre-split bar. ATR (`high - low`, `|high - prev_close|`) is
then hugely inflated, and a bearish target `current - risk × mult` goes negative. This fits all four named
symbols and would ALSO inflate bullish ATR, stops and targets silently — for every consumer of `get_bars`,
both scans included.

`backend/scripts/p3c_data_checks.py`, read-only. URL resolution comes FIRST, before any other `app.*` import
(r21-1, HIGH: `app/database.py:8` calls `create_async_engine(settings.DATABASE_URL)` at import, and
`app.routers.stock_scan` imports it at :25, so a `postgres://` / `postgresql://` / `mysql://` URL crashed the
script at import, before its own routing ran). The script, run from `backend/` like the app, reads the URL with
`app.config.Settings().DATABASE_URL` — `app.config` imports only pydantic_settings and builds no engine; a fresh
`Settings()`, not the `@lru_cache`d `get_settings`, so it sees `DATABASE_URL` from the environment AND
`backend/.env`, as the app does (reading `os.environ` alone would miss a `.env` URL and silently open `dev.db`).
It validates and, for postgres, rewrites that URL (rules below), exits non-zero naming the scheme for any other,
then sets `os.environ["DATABASE_URL"]` to the rewritten URL (env beats `.env` in pydantic-settings) and only then
imports `app.routers.stock_scan` (for `_merge_strategy_params`, `_SIGNAL_KWARGS`, `_HISTORY_YEARS`) and
`app.services.strategy_engine`, lazily inside `main()`. Routing (r19-L8: a sqlite `DATABASE_URL` or none → stdlib
sqlite3 with a `mode=ro` URI, like `iv_basis_analysis.py`; a `postgresql+asyncpg://`, `postgresql://` or `postgres://` URL →
the last two rewritten to `postgresql+asyncpg://` first (r20-L2: only the asyncpg form builds an engine here —
psycopg2 is not installed; the app's own URL is already that form, app/database.py:8), then
`create_async_engine(url)` (asyncpg, in requirements.txt; imported at the script's module level — r20-L4), all reads
on one connection in ONE transaction whose first statement is `SET TRANSACTION READ ONLY`, never committed
(r21-3: the SET covers one transaction only, so a commit would let later reads run read-write; verified on
Postgres 16 + asyncpg — under autobegin the SET is inside the transaction and `SHOW transaction_read_only` is on); any other scheme → exit non-zero naming it. Not
`iv_basis_analysis.py`'s approach (r20-L1): for non-sqlite it falls back to the HTTP API (:251-254), and no API
serves raw `ohlcv_daily` rows (`adj_factor`, raw OHLC), so that fallback is useless here).
Everywhere in this script a NULL `adj_factor` is read as 1.0, as `_read_bars` does (historical_store.py:154-155 —
r19-L7, r20-L3: every product with `adj_factor` below, not only the first). It never calls `get_bars`
(which writes on a stale DB). Window (r2-H2): `[today - 5×365d, today]` — `_HISTORY_YEARS = 5` (stock_scan.py:450), the span `get_bars` serves the
backtest where the negative price happens. The splits (WMT 3:1 Feb 2024, TSCO 5:1 Dec 2024, CPRT and SRE 2023) are
outside the 441-day regime window, so that window cannot see them.
For each symbol (default WMT CPRT TSCO SRE LYB, overridable):

- rows in `ohlcv_daily` over the scan window: count, date span, `source` mix, `adj_factor` / `split_factor` changes;
- max of `high / (raw_close × adj_factor)` and the largest one-day `|Δclose|` %, with dates;
- ATR(14) at the last bar computed three ways: as `_read_bars` returns it (mixed), fully raw, fully adjusted
  (OHLC all × adj_factor);
- the bearish pullback_ema target on the two series named below (r15-6: the `_read_bars` MIXED series and the
  SPLIT-REBUILT series; the "fully adjusted" series of the ATR bullet above is for ATR only).

Split detection does NOT rely on `split_factor` (round-1 M5: the Alpaca normaliser, the primary provider,
hard-codes `split_factor: 1.0`, alpaca.py:117). A split is detected from consecutive rows: a one-day
`raw_close` ratio within 3% of a common split ratio (2, 3, 4, 5, 10, 20, 1/2, 1/3 …), reported with its date.
`get_bars` only appends `last+1 → end` and never rewrites old rows (historical_store.py:230-233), so rows
stored before a split may keep a stale `adj_factor`. Per symbol the script prints ONE of:

- `STALE ADJ_FACTOR` — the adjusted close (`raw_close × adj_factor`, what `_read_bars` returns) itself jumps
  by a split ratio at a detected split date (adjustment never applied to old rows);
- `MIXED ADJUSTMENT` — adjusted close is continuous across the split but `high / adjusted_close` on the
  pre-split rows is ≈ the split ratio (raw high/low next to adjusted close);
- `NO SPLIT IN WINDOW` / `CLEAN`;
- `NO ROWS` (r21-2) — zero `ohlcv_daily` rows for the symbol in the window: printed as
  `NO ROWS in ohlcv_daily for {sym} over {start}..{end}` INSTEAD of the per-symbol stats, ATR and target blocks
  below (which are undefined on no bars), and the script moves to the next symbol. A fifth verdict.

plus, over EVERY bar of the window (r2-H2 — the last bar is post-split and clean, so it cannot show this):
the maximum ratio of ATR(14) as `_read_bars` returns the series to ATR(14) on a series rebuilt from raw OHLC with
the detected split ratios applied backwards (independent of stored `adj_factor`), and the bearish pullback_ema
target figures below on each of exactly two series — (a) the series as `_read_bars` returns it and (b) that
split-rebuilt series — with dates (r15-6); and the same values on the 5 bars either side of each detected split.
**Target measurement — the REAL signal, not a copy (r15; replaces the hand reimplementation of r4-r14, whose
setup rules drifted from the code in every round: the `trend_ema + 10` and empty-MA guards (r13-1), the volume gate
with a zero 20-bar average (r14-1), 2dp rounding of the primary (r14-2)).** The script calls
`strategy_engine.pullback_ema_signal` itself, so the setup bars and the stop are the code's by construction.
The one thing the real signal hides is the case being measured — P3a's `_build_target_ladder` drops non-positive
rungs, and with every rung dropped the signal returns None (strategy_engine.py:502-503), so a negative target
never shows. When the ladder is empty (r15-1, verified against :295-351): the primary (the 20-bar `_swing_low`,
today included) was dropped — in MIXED data typically because raw pre-split lows sit ABOVE the adjusted entry, not
because it is non-positive — AND the fallback `entry - risk × max(fallback_mult, _LADDER_MIN_FALLBACK_R)` rounded
to ≤ 0. The degenerate guard (:292-295, `entry <= 0` / non-finite risk) cannot be reached from the DB (`high`/`low`
NOT NULL, models/ohlcv_daily.py:29-30; a close ≤ 0 fails the setup earlier), so there is no second cause to label. The script therefore wraps the ladder helper for the duration of its own calls
(`unittest.mock.patch.object(strategy_engine, "_build_target_ladder", wrapper)` — `pullback_ema_signal` looks the
name up in module globals at call time, :493; the script is single-threaded and nothing else runs in its
process). The wrapper calls the ORIGINAL helper with the same arguments, records the arguments (`entry`, `stop`,
`primary`, `extensions`, `fallback_mult`) and the real result, and returns the real result unchanged — unless it is EMPTY, in which
case it returns a placeholder one-rung ladder `[round(entry * 0.5, 2)]` (bearish; strictly below entry and
positive) so the signal completes and the bar is still recorded as a setup bar. The placeholder is never
reported. Per setup bar (signal not None under the patch) the script records: `stop_price`; the raw rungs
(`primary`, ext1, ext2 exactly as passed); the real `targets[0]`, or, when the real ladder is empty (r15-1, r15-3):
`NONE — no valid rung: primary {p} {non-positive | not below entry | missing}, fallback {f} <= 0. Before P3a the
signal emitted {f} as target_price; ` + one of two endings (r17-1 — the helper empties the ladder on
`rounded <= 0`, :346, so `{f}` can be exactly 0.00): `{f} < 0` → `had this bar's order FILLED, backtesting.py would
have raised (0 < price assertion) and failed the symbol's whole backtest.`; `{f} == 0.00` → `had it filled, the
short would have opened with NO take-profit, no raise.` (backtesting.py `_open_trade` sets tp only `if tp:`,
:1105-1106.) The split is NUMERIC on the float (r18-2), and `{f}` is normalised before formatting (`f = 0.0 if f ==
0 else f`) so a rounded `-0.0` prints `0.00`, not `-0.00`. (r16-1: the assertion runs in `Trade.tp`'s setter, i.e. on fill
— backtesting.py `__set_contingent` — not when the order is placed; the signal is not called while in a trade, and
an unfilled limit is cancelled by the next order under `exclusive_orders=True`, strategy_backtest.py:136.) — `{f}` computed from the recorded args with the module's own `_LADDER_MIN_FALLBACK_R`, the
primary's status from the same 2dp comparison `_valid` makes. (P3a's docstring, strategy_engine.py:283-288, and
`git show a2365a3` confirm the old path: the fallback was emitted, not traded; strategy_backtest.py:138-140 turns
the raise into `_empty_result`.) Summary per series: signal-fire count — an UPPER BOUND on what the backtest
evaluates (r15-5: the backtest calls the signal only while flat, strategy_backtest.py:125; the script calls it on
every bar) — how many had a non-positive raw rung, how many had an empty real ladder, the minimum raw rung and the
minimum fallback, with dates, and the FIRST empty-ladder bar with `{f} < 0` — the EARLIEST bar at which the pre-P3a backtest could have
raised, not necessarily the one that did (r16-1, r17-1) — plus the count of `{f} == 0.00` bars.
Nothing is reimplemented except that one-line empty-ladder fallback, so there is no ordering or rounding rule to
drift.

Params (r12-F1 — `active.bearish` alone is NOT what the stock-scan backtest ran): the script builds the same merged
set the backtest uses, `_merge_strategy_params` (stock_scan.py:198-212, precedence exit < active < request) —
`get_exit("pullback_ema")`, then `get_active("pullback_ema", "Bearish")`, then `_SIGNAL_KWARGS["pullback_ema"](req)`
(stock_scan.py:181) where `req` is a `StockScanRequest` built with dummy `universe=[]`, `direction="Bearish"`,
`horizon="Swing"`, `strategy="pullback_ema"` and its defaults (schemas/stock_scan.py:16-20), which are always
non-None and so always win. Shipped result: `ema_period 50` (active's 35 is overridden), `trend_ema 100`,
`tolerance 0.08`, `ma_type EMA`, `require_reversal False`, `atr_stop_mult 1.5`, `rr_target_mult 2.0`,
`exit_swing_lookback 20`. The script prints the merged set and which layer set each key. `--params-json` (r13-3,
r14-3, r15-4) accepts ONLY the five request fields `_SIGNAL_KWARGS["pullback_ema"]` reads (stock_scan.py:181):
`pullback_tolerance_pct`, `pullback_ema_period`, `pullback_trend_ema`, `pullback_ma_type`,
`pullback_require_reversal`, passed as extra kwargs when building `req` — overlaid on the defaults, so a partial
JSON cannot let active's `ema_period 35` back in. Any other key (the signal's own `ema_period`; `atr_stop_mult`;
another strategy's `rsi_period`; the dummy `direction`, which would raise a raw TypeError) is REFUSED by name,
listing the five; a pydantic `ValidationError` (e.g. `pullback_ema_period: 0`) exits non-zero with its message.

Bar windowing (r12-F2): like the backtest (strategy_backtest.py:113-127), bar `i` is evaluated on the trailing slice
`bars[max(0, i+1-350) : i+1]` and skipped when it has fewer than 60 bars; the signal is called as the backtest calls
it (`fn(slice_bars, direction="Bearish", **params)`, no `current_price`).

Pin (`tests/test_p3c_data_checks.py`): on a split-free fixture LONGER than 350 bars where every rung is positive,
the patched run's setup-bar set equals the set where the UNPATCHED `pullback_ema_signal` (same slices, same params)
is not None, and on every such bar its recorded `targets[0]` and `stop_price` equal the unpatched signal's
`target_price` and `stop_price`; the test asserts at least one such bar has index ≥ 350 (r13-2). A second fixture
(r15-2 — negative extensions alone do not empty the ladder while the swing low is valid): MIXED-shaped rows
(pre-split high/low ≈ 3× the adjusted close) so the swing low sits above entry, with an ATR large enough that the
fallback is ≤ 0. The unpatched signal returns None on those bars; the patched run records them with `NONE — no
valid rung`, asserts the recorded primary is `not below entry` and the fallback < 0 — the case the script exists
to show.
LYB had no split: for it the script prints `NO SPLIT IN WINDOW` and the line "the split hypothesis does not
explain LYB's negative target" with its minimum raw ext1, so the evidence is not over-read.

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
  (market.py:121, reached at :1302) patched to return `[]`, so the answer is Tradier's alone.
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

`fire_now` (auto_trade.py:199-275) calls `auto_trader.fire(...)` synchronously. `fire()` has blocking network
I/O (market-open check ~3s, regime fetch ≤ 25s deadline since P3b — auto_trader.py:582-587, broker order).

Change: `fire()` runs on a DEDICATED single-worker executor, `_FIRE_EXECUTOR =
ThreadPoolExecutor(max_workers=1, thread_name_prefix="auto-trade-fire")` in auto_trade.py, via
`cf = _FIRE_EXECUTOR.submit(...)` + `await asyncio.wrap_future(cf)` (r2-L13; r3-M1 — the handler keeps the
`concurrent.futures.Future` itself, see Cancellation): the default executor is shared with a running scan's `to_thread` calls (intraday
fetch, HMM, confidence, quotes), so a manual fire during a large scan could queue before its market-open check
even starts. One worker also SERIALISES two concurrent `/fire` calls: the second enters `fire()` only after the
first has disarmed, and gets `ArmPreservedError` → 400.
Precedent that `fire()` is safe off the loop: `run_scan` already runs `maybe_fire_on_scan` → `fire()` in a worker
thread (scan.py:1832); `fire()` guards its state with a `threading.Lock`. The DB read stays on the loop before the
call; `book_fired_order(fired, db)` stays on the loop after it (the session never enters the thread).
**DB connection (r3-L7):** after the snapshot read and before the await, the handler calls `await db.rollback()`
(the read opened a transaction and holds a pool connection; nothing is written), so a `/fire` queued behind the
single worker — up to ~3s market check + 25s regime deadline + broker call — does not pin a connection;
`book_fired_order`'s first statement checks one out again. Test: after the await begins, the session reports no
active transaction (`db.in_transaction()` is False) — this one test uses a REAL `AsyncSession` from an in-memory
aiosqlite engine built by a fixture defined in `test_p3c_fire_off_loop.py` itself (tests/conftest.py has no
DB-session fixture; `engine_and_session` is local to test_o4_step4_booking.py). The fixture creates the tables
(`async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)`, as
test_o4_step4_booking.py:103-111 does — r6-L2; without it the snapshot `select` raises "no such table"). The test
arms `auto_trader` (disarm in `finally`), patches `fire` with the held stub below and `auto_trade.book_fired_order`
with an `AsyncMock` (no real booking write), waits for `started`, asserts `db.in_transaction() is False`, then
releases. Existing callers of `fire_now`
with a `_FakeDb` that has only `execute()` (test_auto_trader.py:3491, test_autotrade_a6_a7.py:194,
test_autotrade_a9.py:139) would now raise AttributeError on `rollback`, so each `_FakeDb` gains
`async def rollback(self): pass` (r5-M1). Exceptions
propagate from the executor with their type, so the handlers are unchanged. The executor's worker is a normal
non-daemon thread, joined at interpreter exit like the default executor's.

The comment block at :224-233 ("NOT REACHABLE OVER HTTP TODAY ... It stops holding the moment `fire()` moves
behind `asyncio.to_thread`") is rewritten: `fire()` now runs off the loop, the single-worker executor serialises
`/fire` calls, and `expect=` stays the guard against a re-arm by any other producer during the window.

**Cancellation (r1-M9, corrected by r2-M4).** Main.py installs only CORSMiddleware, so a client disconnect does not
cancel the handler; a forced/timed-out shutdown does, and then `asyncio.run`'s teardown cancels every task —
an asyncio-side done-callback would see only "cancelled" and lose the result. So the logging is on the THREAD
side of the `concurrent.futures.Future` (r3-M1 replaces r2's Event + double check, which had a race — worker
checks the unset Event, handler sets it, handler sees `.done()` False, worker returns: nothing logged — and could
not be built on `run_in_executor`, whose asyncio future is cancelled with the task, so no result is readable). The
handler captures `armed_symbol = _armed_state.strategy.symbol` before the call, submits `cf =
_FIRE_EXECUTOR.submit(auto_trader.fire, ...)` and awaits `asyncio.wrap_future(cf)`. On `CancelledError` it calls
`cf.add_done_callback(functools.partial(_log_unbooked, armed_symbol))` and re-raises. `add_done_callback` runs the
callback at once if `cf` is already done, otherwise in the worker thread when `fire()` finishes; the Future's
internal lock makes that hand-off atomic, so exactly one of the two happens and there is no window. (The
`wrap_future` cancel propagates `cf.cancel()`, which is a no-op on a running future and, on a still-QUEUED one,
cancels it — `fire()` never ran, nothing to book; `_log_unbooked` then logs "cancelled before fire() ran" at
WARNING.) `_log_unbooked(symbol, cf)` (r4-M1 — it must never raise: `add_done_callback` swallows an exception
from the callback and logs only "exception calling callback for <Future>" on the `concurrent.futures` logger,
so the designed line would be lost; `cf.result()` re-raises `fire()`'s exception and raises
`concurrent.futures.CancelledError` on a cancelled future) reads the future in this order:
`if cf.cancelled():` WARNING `"POST /auto-trade/fire for {symbol} was cancelled before fire() ran; nothing was
sent"`, return; `exc = cf.exception()`; `outcome = exc if exc is not None else cf.result()`; ERROR `"POST
/auto-trade/fire for {symbol} was cancelled while fire() ran; this outcome was NOT booked: {outcome!r}"`.
The executor's thread is joined at shutdown, so a thread-side callback is written. Booking is not attempted after
a cancel (the request's session is gone).
Handler shape (r4-L1): the snapshot read, `armed_symbol` capture and `await db.rollback()` run BEFORE the `try`;
`cf = _FIRE_EXECUTOR.submit(...)` is assigned before it; the `try: ... except asyncio.CancelledError:` encloses
ONLY `await asyncio.wrap_future(cf)`, so a cancel during the read or the rollback propagates normally with no
`cf` to reference and nothing submitted.
The same gap on `run_scan`'s `maybe_fire_on_scan` call is logged as an open question.

Stale docstrings outside P3c (round-1 L11): auto_trader.py:1548-1550 ("reachable from the event-loop thread,
via the /fire endpoint, where asyncio.run raises") and :2280-2283 ("a manual POST /auto-trade/fire on the event
loop") become false. auto_trader.py is P3b's — logged as an open_questions entry with the replacement text.

Tests (`tests/test_p3c_fire_off_loop.py`):

- `fire` monkeypatched to `time.sleep(0.5)` then return a FiredOrder; while the request is in flight, a second
  request (`GET /auto-trade/status`) completes first — the loop is free. Transport (r8-L3): NOT a sync
  `TestClient` (Starlette's portal gives each threaded request its own loop, so GET would finish first even on
  today's blocking code, and conftest's `client` app has no auto_trade router). A local FastAPI app containing only
  `auto_trade.router`, driven by `httpx.AsyncClient(transport=ASGITransport(app))` on the test's loop with
  `asyncio.gather(post, get)`; `get_db` overridden with a `_FakeDb` (`execute` + `rollback`);
  `auto_trade.book_fired_order` patched with `AsyncMock(return_value=BookingOutcome(booked=True, rec_id="r1",
  error=None, over_exposure=False))` (r9-L1, reason corrected by r10-L3 — a bare `AsyncMock` does NOT crash: `fire_now` returns a plain
  `dict` with no response model, so the MagicMock fields serialise as junk such as `[]` and POST still returns 200;
  a real `BookingOutcome` is needed so the body is meaningful; `BookingOutcome` is at
  app/services/auto_trade_booking.py:99-105 after the main merge; its new `wrong_side_stop` field defaults to False, so the four-field constructor above is still valid); completion order recorded, asserting GET finished while POST was
  still pending, the POST returned 200, and its body has `rec_id == "r1"`. Armed/disarmed per the Arming rule below.
- `fire` runs on a thread named `auto-trade-fire*`, not the loop's thread.
- SizingConfigError → 500 and RuntimeError → 400 still mapped (existing tests re-run after their `_FakeDb` gains
  `rollback` — r5-M1 — plus one each here). Both new tests are ARMED (r8-L2 — unarmed, the endpoint's own
  "AutoTrader not armed" 400 at auto_trade.py:205-206 would pass the RuntimeError test without reaching the
  executor) and disarm in `finally`; each asserts the raising stub was called exactly once, and the detail:
  `str(raised_exc)` for the 400, the `SIZING_CONFIG_REFUSED_PREFIX` detail for the 500.
- Two concurrent `/fire` on one armed strategy (r2-H3 — the two 400 texts are identical, so the test does not
  compare detail text; r10-F1 — the old "either two calls or one" allowance let a multi-worker pool pass ~98% of
  runs, since in the one-call branch there is nothing to overlap). `auto_trade.auto_trader.fire` (instance-level
  patch) is replaced by a wrapper that records `enter` and then, on the FIRST call only, waits on a test-created
  `hold = threading.Event()` (`hold.wait(timeout=5)`, raising on timeout) BEFORE calling the real `fire`, then
  records (exit, raised-type). The `submit` wrapper (as in the Cancellation tests) records each submission of the
  patched `fire`. The two POSTs are started with `asyncio.gather` on an `httpx.AsyncClient(ASGITransport)` over the
  loop-free test's local app; the test waits, TIME-bounded (`await asyncio.sleep(0.01)` up to 5s, then `assert` — the
  requests cross the whole ASGI stack, so the 100-yield bound below does not apply), until the `submit` wrapper has recorded
  TWO submissions — both requests passed the endpoint's armed check, because the first is held inside `fire()`
  before it disarms. Then (r11-F1 — setting `hold` at once let a multi-worker pool pass ~0.2% of runs idle and
  ~20% under CPU load, because the second pool thread had not yet entered the wrapper) it waits, time-bounded
  (`await asyncio.sleep(0.01)` up to 0.5s), until `len(calls) >= 2 or subs[1].running()`, and asserts
  `len(calls) == 1 and not subs[1].running()` — the second call is still QUEUED while the first is held (`subs`
  = the `submit` wrapper's recorded futures; `calls` = the fire wrapper's `enter` records). Only then does it set
  `hold`. `hold.set()` is also in the `finally`. (Simulated by the round-11 auditor: one worker 300/300 pass; a
  4-worker pool under load 500/500 fail, all on this assertion; ~0.5s per run.) Assert: the wrapper
  recorded exactly two calls; exactly one raised `ArmPreservedError` from inside `fire()`; the calls did not
  overlap (the second's enter ≥ the first's exit — serialisation after release; the queued-while-held assertion
  above is what makes a multi-worker pool fail); `execute_option_order` called exactly once;
  one 200 and one 400. Isolation (r10-F2 — this test runs the REAL `fire()`, which appends a "filled" row to the
  process-wide `_state.history` and counts toward `_check_daily_loss` in later fires): before arming,
  `monkeypatch.setattr(auto_trade.auto_trader._state, "history", [])`, the precedent at
  test_o4_step4_booking.py:142. `_market_is_open`, `_apply_vol_sizing` and `execute_option_order` are patched;
  `book_fired_order` as in the loop-free test.
- Cancellation (r3-M1, r4-M1/L1, r5-M2..L5, r6-L1..L4): the TEST BODY creates `started` and `ev`, both new
  `threading.Event()` objects per test (r6-L3 — never module-level, or Case C would start with `started` already
  set from Case A); the patched `fire` calls `started.set()` and then `ev.wait(timeout=5)` (raising on timeout). The handler is driven as a
  task on the test's loop (`fire_now(db=...)` called directly, not through the HTTP client, so the test can cancel
  it) with a `_FakeDb` that has `execute` and `rollback`. `auto_trade.book_fired_order` is patched with an
  `AsyncMock`. The test gets `cf` by monkeypatching `auto_trade._FIRE_EXECUTOR.submit` with a wrapper that calls
  the real `submit` and records the returned future ONLY when the submitted `fn` is the patched `fire` (r6-L1), so
  a helper submitted in the same test cannot be mistaken for the handler's `cf`. Every held test releases in `try/finally: ev.set()`, so a
  failed assertion can never leave the one worker blocked. An AUTOUSE, FUNCTION-scoped fixture (default scope —
  r5-L5; not module scope, whose teardown runs once per module) asserts in its teardown that the worker is idle:
  `_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)`.
  Arming (r7-L2, r8-L2): every test that patches `fire` (Cases A–D, the thread-name, loop-free and both mapping
  tests, and the `in_transaction()` test) arms
  `auto_trader` with `_make_armed(...)` before creating the task and calls `auto_trader.disarm()` in the same
  `try/finally` that sets `ev` — the stub never runs the real disarm, and `auto_trader` is a process-wide singleton.
  Patch target (r7-L1): `fire` is patched ON THE INSTANCE, `mocker.patch.object(auto_trade.auto_trader, "fire",
  stub)` (as test_auto_trader.py:3497 does), so the handler's `submit(auto_trader.fire, ...)` receives exactly
  `stub` and the wrapper's `fn is stub` filter matches (a class-level patch yields a fresh bound method per lookup
  and never matches). Every "wait until the wrapper has recorded `cf`" is BOUNDED:
  `for _ in range(100): if recorded or task.done(): break; await asyncio.sleep(0)`, then `assert recorded`
  (surfacing `task.exception()` if the task ended first) — there is no pytest-timeout, so an unbounded wait would
  hang the suite instead of failing it. The 100-yield bound is for `_FakeDb` tests ONLY (r8-L1): with the real
  aiosqlite session each call resolves from aiosqlite's own thread (measured 58 / 680 / 2895 yields min / median /
  max), so the `in_transaction()` test waits with `assert await asyncio.to_thread(started.wait, 5)` and never uses
  the yield loop; any `cf` wait on a real session is bounded by time (`await asyncio.sleep(0.01)` up to 5s).
  Callback barrier (r5-L4): `Future.set_result`/`set_exception` notify waiters BEFORE `_invoke_callbacks`, so
  `cf.result()` can return while `_log_unbooked` has not yet run. Before any caplog assertion in Cases A and C,
  the test waits `_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)` — the single worker finishes the previous
  work item, callbacks included, before it takes the next one.
  Case A — the test waits `await asyncio.to_thread(started.wait, 5)` and asserts `cf.running()` BEFORE
  `task.cancel()` (r5-M2: without it the cancel lands while `cf` is still QUEUED in ~all runs and the case
  silently becomes Case D); awaits the task (CancelledError); releases the Event; callback barrier → the ERROR
  line (written from the worker thread) names the symbol and the FiredOrder repr. Case B, the race — after `create_task` the test yields
  (`await asyncio.sleep(0)` until the wrapper has recorded the fire `cf`; with the `_FakeDb` one yield suffices, as
  `execute`/`rollback` never suspend — r6-L4), then the Event is
  released and the test waits `cf.result(timeout=5)` BEFORE calling `task.cancel()`, with no yield between the wait
  and the cancel, so `cf` is done when the handler's `add_done_callback` runs → the line is logged once, at once,
  on the loop thread (no barrier needed). Case C — as Case A (`started` waited, `cf.running()` asserted), but
  `fire` raises `ValueError("boom")` after the release → callback barrier → the ERROR line contains `boom`.
  Case D (r5-M3) — the one worker is occupied DIRECTLY by `held_blocker` submitted through the ORIGINAL
  `submit` (captured before the monkeypatch — r6-L1; the wrapper filters it out in any case) (a plain function
  that waits on the same Event; not a first `fire_now` task, which would itself book or log); the test starts the
  `fire_now` task, waits until the `submit` wrapper has recorded its `cf` (so the cancel does not land during
  `db.execute`/`rollback`, where nothing is submitted and nothing is logged), asserts `not cf.running()`, then
  `task.cancel()` → `cf.cancel()` succeeds on the queued future and `_log_unbooked` runs on the loop thread → the
  WARNING "cancelled before fire() ran"; the Event is released; the patched `fire` was never called.
  Every case: exactly one line from `_log_unbooked`, NO record containing "exception calling callback" on the
  `concurrent.futures` logger (caplog at DEBUG on that logger), the `book_fired_order` mock not awaited.

## State updates (PROJECT_STATE.json)

On merge, entries named by their opening text (round-1 L15 — indices shift under parallel sessions):
"LOGGED BY P3a (2026-09-25), NOT FIXED, outside P3a's files", "LOGGED BY P3a (2026-09-25), NOT FIXED: the options
direction", "LOGGED BY P3a (2026-09-25), NOTE: frontend", "LOGGED BY P3c SETUP" closed with the commit;
"P3a (2026-09-25) FIXED the stock_scan.py items" gets (3)(4)(5) fixed, (10) closed by P3b; "P3a (2026-09-25)
FIXED (a) _build_target_ladder" and "P3a (2026-09-25) FIXED the comment (441" updated with "check script
shipped, awaiting Kenneth's run" (not closed). New entries: the stale stock_scan.py and auto_trader.py
comments (L11, L12), the scan-vs-fire END difference (item 6), `run_scan`'s cancellation gap (item 7),
the relative_strength DB-miss misalignment residual (r2-M6), P3a's `_valid` keeping a positive rung below 0.005
that rounds to 0.0 (strategy_engine.py:300-311 — the `value <= 0` test runs before rounding; practically
unreachable, P3a's code; round-16 observation; BEARISH only — a bullish 0.0 fails the entry-side test at :310 —
and the effect, when the 0.0 rung is `targets[0]` (`target_price`), is a short opened with NO take-profit, since
backtesting.py skips a falsy tp (:1105-1106), not the raise P3a guarded against; when a valid primary or nearer
extension leads (rungs sort nearest-first, :318-321, so a bearish 0.0 is always last), it is only a 0.00 rung in
`targets` (the UI ladder) — r17-2, r18-3), the ScanFunnel unmeasured stage (r2-M7), the
stale "market structure does not support" text in the frontend fixture `step-4-ranking/__tests__/emptyStateBanner.test.tsx:21-22` (r3-L5).
The two Kenneth decisions above go to the front of `decisions`. One new decision
per Q below once answered. Phase probe: a regex for `_NO_REGIME_FILTER` and `direction_conviction_unmeasured` in scan.py.

## Verification

`cd backend && pytest` (all), `cd frontend && npm run typecheck && npm run test`, `python3 scripts/state.py`.
The script: `python3 backend/scripts/p3c_data_checks.py --help`; sections chosen by `--sections db,sources`
(default both; `sources` is the only one that touches the network — r2-L10). `tests/test_p3c_data_checks.py` runs
`--sections db` only, against a fixture sqlite `ohlcv_daily` with three symbols — Alpaca-shaped 3:1 split
(`split_factor` 1.0, correct `adj_factor`, raw OHLC) → `MIXED ADJUSTMENT`; stale pre-split `adj_factor` 1.0 (one of its rows NULL, r19-L7) →
`STALE ADJ_FACTOR`; no split → `NO SPLIT IN WINDOW` — and asserts the DB file's bytes and mtime are unchanged
after the run, and that no socket was opened (socket.socket patched to raise). Verdict strings are exactly the
five in §5: `STALE ADJ_FACTOR`, `MIXED ADJUSTMENT`, `NO SPLIT IN WINDOW`, `CLEAN`, `NO ROWS` (r2-L9, r21-2). The same module holds
§5's two target pins (r14-4): the >350-bar all-positive fixture (patched = unpatched on setup bars, stop and
target; a setup bar at index ≥ 350 asserted to exist) and the MIXED-shaped empty-ladder fixture (unpatched None,
patched `NONE — no valid rung`, primary `not below entry`, fallback < 0); `--params-json` with a key outside the five (e.g. `ema_period`, `direction`) exits non-zero naming it. DB-URL routing (r19-L8, r21-1): each URL case runs the script in a SUBPROCESS (`sys.executable scripts/p3c_data_checks.py --sections db`, cwd `backend/`, `DATABASE_URL` set in its env) — an in-process importlib load imports `app.database` once under the test's sqlite URL and so can never see the import-time crash r21-1 found. `mysql://u@h/db` → exit non-zero, stderr names the scheme, no `Traceback`. For `postgresql+asyncpg://`, `postgresql://` and `postgres://` (host `127.0.0.1`, an unused port): the script gets PAST import and fails only at connect — exit non-zero with a connection error naming the rewritten `postgresql+asyncpg://` URL (password masked), no `ModuleNotFoundError` / `NoSuchModuleError` — which proves the rewrite ran before `app.database` built its engine. The read-only contract is pinned in-process: the importlib-loaded module (like tests/test_iv_basis_analysis.py) with its module-level `create_async_engine` patched ON THE LOADED MODULE to a recording fake whose queries return no rows; assert `SET TRANSACTION READ ONLY` is the first statement of the one transaction, no `commit()` was called, no write statement ran, and each symbol printed `NO ROWS in ohlcv_daily for …`.

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

## Round-3 log (7 findings)

All 13 round-2 resolutions verified present in the body and correct against the code.

| # | Sev | Finding | Resolution (r4) |
|---|---|---|---|
| M1 | MEDIUM | §7 Event + double check races (nothing logged) and can't be built on `run_in_executor` | `submit` + `wrap_future`; on cancel `cf.add_done_callback(_log_unbooked)` — atomic under the Future's lock; four tests incl. the race |
| M2 | MEDIUM | §2 misaligned-benchmark count had no path back to the scan | per-scan `_rs_misaligned` list passed into `_process_symbol`; caplog test |
| M3 | MEDIUM | §4 kept the zero-floor "falls through to 1%" sentence, false since P3a | zero case rewritten (min 1 share / 1 contract); existing test + docstring + module comment updated |
| L4 | LOW | §5 minimum-target formula didn't match the backtest | exact reimplementation, both rungs + prior_extreme, setup-bars vs all-bars, pinned to `stop_price` |
| L5 | LOW | §2 said banner tests assert old text; none do | sentence dropped; stale frontend fixture logged as open question |
| L6 | LOW | §3 `ScheduleEntryRow` is private and page.tsx can't export it | render `SettingsPage` with mocks (RiskForm.hydration pattern) |
| L7 | LOW | §7 queued `/fire` calls each pin a DB connection | `await db.rollback()` before the await; test |

## Round-4 log (6 findings)

All 7 round-3 resolutions verified present in the body and correct against the code; the §7 hand-off
(`add_done_callback` under the Future's lock, `wrap_future` cancelling a queued `cf`) confirmed empirically.

| # | Sev | Finding | Resolution (r5) |
|---|---|---|---|
| M1 | MEDIUM | §7 `_log_unbooked`'s `cf.result() or cf.exception()` raises inside the callback on a failed or cancelled future; the line is swallowed | read order stated: `cancelled()` → WARNING; `exception()` before `result()`; tests assert no "exception calling callback" record |
| L1 | LOW | §7 tests A–D unwritable as stated (no handle on `cf`; a failed assert hangs the one worker) | `submit` wrapper records `cf`; `try/finally ev.set()`, `ev.wait(timeout)`, idle-worker fixture; `try` encloses only the executor await |
| L2 | LOW | §3 render test mocks too few `api.*` calls; the Scan section's other effects throw | every call reached from the section's mount is mocked and listed; the four known named with lines |
| L3 | LOW | §2 contradicts itself on which count drives the banner | `direction_filtered_count` deleted; banner and `failed_direction` read `_dir_removed` |
| L4 | LOW | §5 reported the minimum rung, not the backtest's `targets[0]`; setup filter missed the volume gate; only stop pinned; params ambiguous | reports `targets[0]` (primary if profitable-side else ext1), min rung secondary; volume gate added; target and setup-bar set pinned; bearish active block named, tuned params stated |
| L5 | LOW | §4 left stale fall-through text (test name, comments, docstrings, conviction_sizing.py:286-307); "every headwind" is wrong | all listed and corrected, test renamed; message says "at or beyond -full_conviction_pct" |

## Round-5 log (5 findings; scope §7 only)

Verified: the M1 read order cannot raise in a done-callback; the `add_done_callback` hand-off is atomic; the
`wrap_future` cancel propagation; `asyncio_mode = auto`; `FiredOrder` is a frozen dataclass (safe repr); the
existing `except` clauses on a `try` holding only the await are correct (`CancelledError` is a BaseException).

| # | Sev | Finding | Resolution (r6) |
|---|---|---|---|
| M1 | MEDIUM | §7 `await db.rollback()` breaks three existing tests whose `_FakeDb` has only `execute`; the "DB-session fixture" does not exist | the three `_FakeDb` classes gain `rollback` (files listed); the `in_transaction()` test builds its own aiosqlite `AsyncSession` fixture in the new module |
| M2 | MEDIUM | §7 Cases A/C: the cancel lands while `cf` is still queued (498/500 trials), turning them into Case D | patched `fire` sets a `started` Event first; A/C wait on it and assert `cf.running()` before cancelling |
| M3 | MEDIUM | §7 Case D's held first `/fire` books (or logs) too, contradicting "exactly one line / book not called" | the worker is occupied directly by `_FIRE_EXECUTOR.submit(held_blocker)`; test waits for the second `cf` to be recorded before cancelling |
| L4 | LOW | §7 A/C caplog assertions race the worker-thread callback (`set_result` notifies before callbacks run) | barrier `_FIRE_EXECUTOR.submit(lambda: None).result(timeout=5)` before any caplog assertion |
| L5 | LOW | §7 idle-worker check called a "module fixture", whose teardown runs once per module | autouse function-scoped fixture |

## Round-6 log (4 findings; scope §7 only)

All five round-5 fixes verified present and correct; Cases A–D simulated 300× each with the plan's exact handler
shape, no failure, no "exception calling callback" record.

| # | Sev | Finding | Resolution (r7) |
|---|---|---|---|
| L1 | LOW | §7 Case D: `held_blocker` routed through the `submit` wrapper is recorded as `cf`, so the test cancels too early | blocker submitted via the original `submit`; the wrapper records only submissions of the patched `fire` |
| L2 | LOW | §7 `in_transaction()` fixture has no tables; `fire`/`book_fired_order` unspecified for that test | fixture runs `Base.metadata.create_all`; test patches `fire` (held stub) and `book_fired_order` (`AsyncMock`), asserts after `started` |
| L3 | LOW | §7 `started` Event could be read as created inside `fire` or module-level | test body creates `started` and `ev` per test; `fire` sets / waits on them |
| L4 | LOW | §7 Case B has no handle on `cf` before releasing | yield until the wrapper has recorded the fire `cf` |

## Round-7 log (2 findings; scope §7 only)

All four round-6 fixes verified present and correct; the wrapper identity filter confirmed for an instance-level
patch (plain function and MagicMock); the rollback cannot expire the snapshot (`orm_positions_to_risk` copies rows
into dataclasses before it).

| # | Sev | Finding | Resolution (r8) |
|---|---|---|---|
| L1 | LOW | §7 the wrapper filter matches only an instance-level patch, and the wait for `cf` is unbounded — a miss hangs the suite | patch target stated (`auto_trade.auto_trader` instance); bounded 100-yield wait, then `assert recorded` |
| L2 | LOW | §7 Cases A–D never arm/disarm `auto_trader`; the stub never disarms, leaving the singleton armed | every `fire`-patching test arms first and disarms in the same `try/finally` as `ev.set()` |

## Round-8 log (3 findings; scope §7 only)

Both round-7 fixes verified; `_make_armed` importable from tests.test_auto_trader (precedent
test_autotrade_ibkr_confirm_not_submitted.py:30); arming needs no setup; fixture teardown order puts the idle check
after the `fire` patch is undone; no HIGH/MED in §7's design.

| # | Sev | Finding | Resolution (r9) |
|---|---|---|---|
| L1 | LOW | §7 the 100-yield `cf` wait fails ~90% with the real aiosqlite session | yield bound limited to `_FakeDb` tests; `in_transaction()` test waits on `started` via `to_thread`; real-session waits time-bounded |
| L2 | LOW | §7 RuntimeError → 400 test passes vacuously unarmed; armed, it leaks the singleton | both mapping tests armed + disarm in `finally`; stub called once; detail asserted |
| L3 | LOW | §7 loop-free test's client unspecified; a sync `TestClient` passes on today's blocking code | local app with `auto_trade.router`, `httpx.AsyncClient(ASGITransport)` + `gather`, `get_db` override, `book_fired_order` mocked, completion order asserted |

## Round-9 log (1 finding; scope §7 only)

All three round-8 fixes verified. The loop-free test discriminates: on today's blocking code POST completes before
GET 300/300; with the planned handler GET completes first. The local-app wiring (router prefix, no auth,
`app.database.get_db` override key) and the mapping-test details confirmed.

| # | Sev | Finding | Resolution (r10) |
|---|---|---|---|
| L1 | LOW | §7 loop-free test: a bare `AsyncMock` booking returns a MagicMock that crashes response serialisation | `AsyncMock(return_value=BookingOutcome(...))`; POST 200 asserted |

## Round-10 log (3 findings; scope §7 only)

The round-9 fix verified in the body (the line ref corrected 73-79 → 74-79). Verified by simulation on a scratch
copy of the planned handler: the loop-free test discriminates; on the planned code two concurrent `/fire` always
give one 200 / one 400 / one order; the three `_FakeDb` callers are the only direct callers of `fire_now`; Case D
is safe in either callback order.

| # | Sev | Finding | Resolution (r11) |
|---|---|---|---|
| F1 | MEDIUM | §7 two-concurrent test does not pin serialisation: a 4-worker pool passed 98/100 runs (the one-call branch has nothing to overlap) | the first call is held inside the wrapper until both submissions are recorded; exactly two calls, one `ArmPreservedError`, no overlap — the "either" branch dropped |
| F2 | LOW | §7 the concurrent test's real `fire()` leaks "filled" rows into the singleton's history → later daily-loss refusals | `_state.history` monkeypatched to `[]` before arming (test_o4_step4_booking.py:142 precedent) |
| F3 | LOW | §7 r9's stated reason (MagicMock crashes serialisation) is false — `fire_now` returns a plain dict, POST is 200 | reason corrected; `rec_id == "r1"` asserted |

## Round-11 log (1 finding; scope §7 only)

All three round-10 fixes verified; the rewritten test cannot deadlock (the second request reaches `submit` while
the first is held) and passes on one worker under CPU load; exception-handler order unchanged. No HIGH/MED in §7.

| # | Sev | Finding | Resolution (r12) |
|---|---|---|---|
| F1 | LOW | §7 two-concurrent test: a multi-worker pool still passed ~0.2% idle / ~20% loaded (second thread not yet in the wrapper when `hold` is set) | before `hold.set()`, a 0.5s time-bounded wait then `assert len(calls) == 1 and not subs[1].running()` |

## Round-12 log (6 findings; scope: the r5 edits to §2-§5, unaudited since, + §7's r12 fix)

§7's r12 fix verified (re-simulated: one worker 30/30 pass, 4 workers 30/30 fail on the queued-while-held
assertion). §3's mock list verified complete (nothing else fetches on mount; default section is Brokers). §2's
counter has no other reader. §4's stock/fire minimum-size claims and §5's formula, volume gate and `targets[0]`
equivalence to the pre-P3a target verified.

| # | Sev | Finding | Resolution (r13) |
|---|---|---|---|
| F1 | MEDIUM | §5 script params were `active.bearish` (ema 35, tol 0.04); the backtest runs the merged set, where the request's always-non-None fields win (ema 50, tol 0.08) | script calls `_merge_strategy_params` with `StockScanRequest` defaults; prints the merged set and each key's layer; `--params-json` is the request layer |
| F2 | LOW | §5 backtest evaluates a trailing 350-bar slice, n ≥ 60; the reimplementation used the full prefix | same slicing; pin fixture > 350 bars, signal called on the same slice |
| F3 | LOW | §2 `_is_direction` is defined after the banner (scan.py:1721 vs :1673) | `_is_direction` + `_dir_removed` defined once before the banner; funnel reuses them |
| F4 | LOW | §4 zero-floor wording missed the unmeasured-regime case (floor used on both paths) | message names it; test asserts it |
| F5 | LOW | §4 planned rewrites would say the falsy read is gone; `risk_fixed if risk_fixed` remains | both texts reworded, not deleted |
| F6 | LOW | §4 line refs off | corrected (stock_scan.py:1016; conviction_sizing.py:285-307; tests :387-394, :438-463, :466-470) |

## Round-13 log (4 findings; scope: the round-12 resolutions)

All six round-12 resolutions verified, several by execution: the merged param set printed exactly as stated;
importing `app.routers.stock_scan` from a script starts no scheduler/thread, writes no file and opens no DB
connection (the only socket is urllib3's import-time `::1` bind probe, inside its own `try/except`, so the
test's raising socket patch is swallowed there); a >350-bar fixture with bearish fires past index 350 and all
rungs positive is buildable; nothing appends to `rejected` between the gate and the banner.

| # | Sev | Finding | Resolution (r14) |
|---|---|---|---|
| 1 | LOW | §5 setup-bar rule missed the signal's `len < trend_ema + 10` and empty-MA guards (flagged bars 106-108; signal first fires at 109) | both guards added to the setup definition |
| 2 | LOW | §5 pin could be satisfied on a bar < 350, where slice = prefix | pin requires a firing bar at index ≥ 350 and asserts one exists |
| 3 | LOW | §5 `--params-json` replace-vs-overlay unstated; replace lets `ema_period 35` back in | overlaid on `StockScanRequest` defaults, then used as the request layer |
| 4 | LOW | line refs one short (conviction_sizing.py :308; strategy_engine.py :504) | corrected |

## Round-14 log (4 findings; scope: the round-13 resolutions)

The round-13 line refs, early-return analysis of `pullback_ema_signal`, merged params and the r13-2 pin logic
verified. With the r13 guards the hand-copied setup rule matched the signal on a normal fixture — but not on the
edge cases below, the fourth round running in which the copy had drifted.

| # | Sev | Finding | Resolution (r15) |
|---|---|---|---|
| 1 | LOW | §5 volume gate stricter than the code when the 20-bar average is 0 (zero volume is stored by three adapters) | class removed: setup bars come from the real `pullback_ema_signal` |
| 2 | LOW | §5 primary compared unrounded; `_valid` rounds to 2dp → wrong `targets[0]` | class removed: `targets[0]` is the real helper's output, recorded by a pass-through wrapper |
| 3 | LOW | §5 `--params-json` key names unstated; unknown keys dropped silently by `StockScanRequest` | keys are `StockScanRequest` field names; unknown keys refused |
| 4 | LOW | Verification omitted the §5 pin test | both pins (all-positive >350-bar; non-positive-rung) and the unknown-key refusal listed |

## Round-15 log (7 findings; scope §5 as redesigned in r15)

The redesign verified by execution: `patch.object` intercepts the call at :493 (module-global lookup); the
placeholder passes through `StrategySignal` unvalidated; pin 1 (420 bars, 94 setup bars, identical stop/target,
bars ≥ 350) and a MIXED-shaped pin 2 (unpatched 0 / patched 94) are constructible; merged params as stated.

| # | Sev | Finding | Resolution (r16) |
|---|---|---|---|
| 1 | MEDIUM | §5 label "no positive rung" false: in MIXED data the primary is dropped for being ABOVE entry, and the ladder empties only when the fallback is ≤ 0 | label names the primary's actual status and the fallback; the only reachable cause stated |
| 2 | LOW | §5 pin 2 fixture ("rungs go non-positive") does not empty the ladder while the swing low is valid | fixture is MIXED-shaped with fallback ≤ 0; primary status and fallback asserted |
| 3 | LOW | §5 "before P3a the backtest traded ext1" wrong: the fallback was emitted and backtesting.py raised, failing the whole backtest | label corrected, with the P3a docstring / a2365a3 / strategy_backtest.py:138-140 evidence |
| 4 | LOW | §5 `--params-json` let through keys that do nothing or crash | whitelist of the five `_SIGNAL_KWARGS` fields; ValidationError exits non-zero |
| 5 | LOW | §5 the backtest evaluates only while flat; the script's count overstates | count labelled an upper bound; first empty-ladder bar reported |
| 6 | LOW | §5 which series the signal runs on was inconsistent | exactly two: `_read_bars` mixed and split-rebuilt |
| 7 | LOW | line ref :501-502 | :502-503 |

## Round-16 log (3 findings; scope: the round-15 resolutions)

All seven round-15 resolutions verified, by execution where possible: the three primary statuses are exhaustive
(`min_rung_r` is never passed, so the floor branch never applies; "missing" is unreachable but harmless); the
fallback equals ext1 at `rr_target_mult` 2.0; the pre-P3a raise reproduced ("Make sure 0 < price < inf! price:
-426.65"); pin 2 built (unpatched 0 / patched 133, all primaries not below entry, fallbacks < 0); whitelist and
ValidationError handling; the two series consistent everywhere.

| # | Sev | Finding | Resolution (r17) |
|---|---|---|---|
| 1 | LOW | §5 label/summary said the first empty-ladder bar failed the pre-P3a backtest; the assertion runs on FILL, and that bar may be in a trade or unfilled | reworded: "had this bar's order filled"; summary says "earliest bar at which it could have raised" |
| 2 | LOW | degenerate-guard ref :295-298 | :292-295 |
| 3 | LOW | `low` NOT NULL ref :29 | :29-30 |

Observation (out of scope, P3a's code): `_valid` can keep a sub-0.005 positive rung that rounds to 0.0 — logged in
State updates.

## Round-17 log (2 findings; scope: the r17 diff)

The r16 reasoning verified against backtesting 0.6.6 (`__set_contingent` on the `tp` setter, on fill; `new_order`
does not assert; `exclusive_orders` cancels pending orders); refs :292-295 and ohlcv_daily.py:29-30 correct.

| # | Sev | Finding | Resolution (r18) |
|---|---|---|---|
| 1 | LOW | §5 label's "would have raised" is false when `{f}` is exactly 0.00: backtesting.py skips a falsy tp, so the short opens with no TP | label split on `{f} < 0` vs `== 0.00`; summary's first bar is the first with `{f} < 0`, plus a count of 0.00 bars |
| 2 | LOW | State-updates `_valid` entry omitted bearish-only and the no-TP (not raise) effect | added |

## Round-18 log (3 findings; scope: the r18 diff)

The r18 claims verified against the code and backtesting 0.6.6 (`new_order` passes tp=0 and negative; `_open_trade`
skips a falsy tp; a negative tp asserts only on fill); "bearish only" holds.

| # | Sev | Finding | Resolution (r19) |
|---|---|---|---|
| 1 | LOW | §5 the 0.00 ending's citation sat inside the printed span (nested backticks) | citation moved outside the span; ref :345 → :346 |
| 2 | LOW | §5 a rounded `-0.0` would print `-0.00` beside "no raise" | split stated as numeric; `{f}` normalised before formatting |
| 3 | LOW | State-updates `_valid` entry: no-TP effect only when the 0.0 rung is `targets[0]` | reworded: otherwise only a 0.00 rung in `targets` |

## Round-19 log (8 findings, all LOW; scope: the WHOLE plan against HEAD 9cbdce9, after the origin/main merge)

Verified by running: §1+§2 applied to a scratch copy breaks exactly the named tests (8 `test_scan_endpoint.py`
via `_force_passing_stock_score`, two `test_a4` fetch cases; the rest 3392 passed); no import cycle; §5 merged
params as stated; each new §4 test fails today; `resolved_request` is a raw dict; §3 mount-call list complete
after the merge; `scan.py`/`stock_scan.py`/`conviction_sizing.py`/`auto_trade.py` unchanged since 2f67e6f; all
seven State-update openings present once in PROJECT_STATE.json.

| # | Sev | Finding | Resolution (r20) |
|---|---|---|---|
| 1 | LOW | §2 stale-comment ref stock_scan.py :300-301 | :297-298 |
| 2 | LOW | §7 refs: `fire_now` :199-262, not-armed 400 :203-205, `BookingOutcome` :98-104 | :199-275, :205-206, :98-105 |
| 3 | LOW | table row 4 ref conviction_sizing.py:158-229 | :160-166 flag, :226-239 ERROR-then-DEBUG |
| 4 | LOW | §6 `_fetch_daily_yf` reached at market.py:1301 | :1302 |
| 5 | LOW | §2 Intraday test doesn't stub the 15-min fetch (§1's drop fires first; live call) | patch `app.routers.scan.fetch_intraday_candles` with `INTRADAY` |
| 6 | LOW | §2 relative_strength test names no patch target | `app.routers.scan._rs_benchmark_candles` AsyncMock, with why |
| 7 | LOW | §5 formulas silent on NULL `adj_factor` | NULL read as 1.0 like `_read_bars`; a NULL row in the STALE fixture |
| 8 | LOW | §5 Postgres read-only path names no driver | sqlite → sqlite3 `mode=ro`; postgresql → `create_async_engine` + `SET TRANSACTION READ ONLY`; other → exit non-zero |

## Round-20 log (4 findings, all LOW; scope: the r20 diff)

Verified: every r20 line ref; the §2 Intraday stub reaches the direction check (`scan.py:585-587` calls the
module-global name via `asyncio.to_thread`; all 400 `INTRADAY` bars are completed; §1 drops only on empty);
`_rs_benchmark_candles` is `async def (req)`, so an AsyncMock fits; NULL-as-1.0 matches `_read_bars`.
Nit: the auditor put `BookingOutcome`'s `@dataclass` at :99. Rejected in r21, wrongly (:97-98 are blank); r21-4 corrected the ref to :99-105.

| # | Sev | Finding | Resolution (r21) |
|---|---|---|---|
| 1 | LOW | §5 said `iv_basis_analysis.py:251-252` refuses non-sqlite; it falls back to the HTTP API (:251-254) | reworded, with why that fallback can't serve raw rows |
| 2 | LOW | §5 plain `postgresql://` / `postgres://` fail in `create_async_engine` (no psycopg2) | rewritten to `postgresql+asyncpg://` first; routing test covers all three |
| 3 | LOW | §5 NULL-as-1.0 stated only for the first `adj_factor` product; the fully-adjusted ATR and STALE verdict would hit None × float | stated once for the whole script |
| 4 | LOW | Verification: no patch target for `create_async_engine` | module-level import; patched on the importlib-loaded script module; fake returns no rows |

## Round-21 log (4 findings: 1 HIGH, 1 MED, 2 LOW; scope: the r21 diff)

Checked by running (backend venv; a throwaway Postgres 16): `create_async_engine` accepts `postgresql+asyncpg://`
with or without a query string; `?sslmode=` fails in asyncpg but equally in `app/database.py`, so a working app
URL never carries it; a module-level import on the importlib-loaded module is patchable; NULL-as-1.0 is consistent
with every §5 `adj_factor` product.

| # | Sev | Finding | Resolution (r22) |
|---|---|---|---|
| 1 | HIGH | §5 the postgres rewrite never runs: importing `stock_scan` builds `app.database`'s engine from the raw URL and crashes (`psycopg2` / `NoSuchModuleError`); the in-process test can't see it | URL resolved via a fresh `app.config.Settings()` (env + `.env`, not `os.environ` alone) and rewritten before any other `app.*` import, written back to the env, `app.*` imported lazily; URL cases run in a subprocess |
| 2 | MED | Verification asserted a "no-rows line" §5 never defined; zero rows made §5's stats undefined | `NO ROWS …` defined as a fifth verdict that skips the stats; "four" → "five" |
| 3 | LOW | `SET TRANSACTION READ ONLY` is per transaction, not per connection | one never-committed transaction; test asserts no `commit()` |
| 4 | LOW | round-20 nit wrongly rejected: `BookingOutcome` is :99-105 | ref corrected; log sentence corrected |

