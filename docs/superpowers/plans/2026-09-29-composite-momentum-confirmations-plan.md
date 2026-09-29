# COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD — plan (r2, after adversarial rounds 1-2; decisions pending)

- **Phase:** `COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD` (PROJECT_STATE.json), decision `P4B-FOLLOWUPS-2026-09-26`, item 1.
- **Scope source:** `docs/superpowers/plans/2026-09-25-work-packages.md` → "P4b follow-ups" → "COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD (item 1)".
- **Branch:** `claude/composite-momentum-confirmations` (off `origin/main` at `adb597c`).
- **Status:** plan written; **no code until Kenneth answers section 2** (the phase note makes this the first step).

## 1. What is true on main today (verified at adb597c)

1. **The schema accepts three momentum kinds; nothing ever produces them.**
   `ConfirmationSignalDef.type == "momentum"` with `signal_kind` in `volume_spike` / `rsi_cross` / `macd_cross`
   (`app/schemas/composite_trigger.py:18-23`, a comment only — `signal_kind` is a free `str`).
   The matcher (`composite_trigger_evaluator._matched_confirmations`, momentum branch) matches when
   `indicator_values[signal_kind]` is a finite real number `>= min_confidence`. It **ignores `direction`**.
2. **Rule path never supplies a value.** `chart_alerts.evaluate_and_notify_for_symbol` passes
   `indicator_values_at(indicators, closed_candle["time"])`, where `indicators =
   compute_indicators_for_conditions(all_candles, <standard-rule conditions only>)`. No standard condition is named
   `rsi_cross` etc., and `indicator_compute` has no such series, so the key is always absent → never matches.
   (A standard rule whose indicator happened to be *named* `rsi_cross` would leak its raw series value in — the
   existing T6 test even builds that case. That leak is removed by this plan.)
3. **Watch path passes `{}`.** `evaluate_scheduled` calls `_count_confirmations(td, structure_signals, {})`
   (the phase's defect marker). `describe_match` on the watch path gets `indicator_values=None`.
4. **The UI does NOT offer momentum confirmations.** `CompositeAlertDialog` `CONFIRMATION_OPTIONS` lists six
   *structure* kinds only (BOS, CHoCH, FVG, OrderBlock, RSIDivergence, MACDDivergence); no frontend file contains
   `volume_spike`, `rsi_cross` or `macd_cross` (grep, `frontend/` excl. node_modules). Momentum confirmations are
   reachable **only through the API** (`POST <alerts prefix>/rules` `composite_def` (chart_alerts router, `prefix="/alerts"`), `POST
   /api/composite-watches/` `trigger_def`) or a hand-edited `strategy_watches.yaml`. No shipped YAML uses one.
   The work-package line "the dialog offers confirmations that can never fire" is therefore inaccurate: the
   *API/schema* offers them. This changes what "done" means — see Q0.
5. **Bars each path reads today.**
   - Rule: fires per closed candle of the rule's interval. the closed candle is `candles[-2]` of the scheduler's refreshed chart-cache fetch (`chart_alert_scheduler.py:139-160`, each candle claimed once, catch-up included); `_regime_candles` = those candles
     (`get_intraday_with_fetched_at`), completed at the fetch time `as_of` (`completed_bars_for_interval` +
     `completed_session_bars`), capped at `MAX_LIVE_MODEL_CANDLES = 1500`.
   - Watch: runs on the watch scheduler (EOD, or every N hours in market hours — not per candle). Reads completed
     `get_bars` daily rows always; fetches `fetch_intraday_candles(interval, days=intraday_history_days)` only
     for `HMM_intraday` or intraday VWAP. It **never reads 1W bars** — no weekly series exists on that path.
6. **Structure confirmations already differ by path** (rule: closed-candle structure on the rule's interval;
   watch: `compute_structure(bars_daily, "1D")`). Out of scope here (not a momentum path); noted so the parity
   test is scoped to momentum only.

7. **Existing MACD helper is lagged (round 1 finding 1, reproduced).** `indicator_compute._ema_values` stores
   `result[i]` *before* folding in `values[i]` (`_ema_values([1]*30+[100], 3)[-1] == 1.0`) and zero-pads the warm-up,
   so `_calc_macd`'s line equals the price for bars 12-25 and its signal line is polluted for dozens of bars. It
   serves standard rules today and stays untouched here (standard-rule behaviour unchanged is in scope); momentum
   gets its own correct EMA. Logged as a separate defect for Kenneth (Q9).
8. **Cadences.** Rule: every closed candle, once (catch-up included). Watch: `poll_hours` (default 4) during market
   hours, or once at EOD (`strategy_watch_scheduler.py:57-80`). Rule cooldown default 60 min (`chart_alerts.py:122`).

## 2. Questions for Kenneth (answer before any code)

Each has a recommendation; "yes to all recommendations" is a complete answer.

**Q0 — Reach.** Momentum confirmations are API-only today.
- (a) **Recommended:** make them match on both paths **and** add them to `CompositeAlertDialog` (W2-INTERVAL's
  file; this is the ask), labelled by direction (Bullish "RSI crosses up through 60", Bearish "RSI crosses down
  through 40", any: "RSI crosses up through 60 or down through 40"; volume "any candle colour" when direction is
  any), plus a line under the N-of-M control: "N of the selected confirmations (structure and momentum
  together)". Selecting a momentum row disables the sustain input with a note (Q7).
- (b) Backend only (API/YAML users only).
- (c) Remove them instead: the schema refuses `type: "momentum"` on create; stored ones never match, logged. None
  exist in shipped config. Cheapest; no new trading signal.

**Q1 — `rsi_cross`.** RSI(14) crosses a level on the judged bar. Bullish `prev <= L < cur`, `L = min_confidence`
(60 → "into 60+"); Bearish `prev >= 100-L > cur` (60 → "into 40-"); direction null = **the Bullish test OR the
Bearish test** (up through L, or down through 100-L). Same edges as `crosses_above/below`
(`alert_evaluator.py:239-254`). `min_confidence` not an int in 1..99 (incl. bool, str, 0, 100) → not matched,
one WARNING per rule/watch id per process. Rejected: "RSI >= 60" (a level; fires every bar of a trend).

**Q2 — `macd_cross`.** MACD(12,26,9) line crosses its signal line on the judged bar (Bullish up, Bearish down, null
either), from a **correct** EMA (SMA-seeded, current bar included). `min_confidence` unused.
Alternative: also require the line on the matching side of zero.

**Q3 — `volume_spike`.** Judged bar's volume >= **2.0×** a baseline, and its candle agrees with the direction
(Bullish close > open, Bearish close < open, null any). `min_confidence` unused.
- **1D/1W:** mean volume of the 20 bars before it; fewer than 20 → not matched.
- **Intraday (incl. 4h):** mean volume of the **same slot over the previous 10 full sessions** (at least 5, else
  not matched + one WARNING). Slot = the bar's UTC time-of-day (its bucket start), so 4h's `origin="epoch"` UTC
  buckets (`market.py:280-282`) compare like with like across DST (for ~5 sessions after a DST switch the new
  grid has too few matches → not matched; stated). The code has no early-close calendar (`market_session`
  has none; P4b item 6 "early-close sessions" was closed as accepted), so half days are not excluded: a half day's
  closing auction bar can read as a spike against its normal slot, and its missing afternoon slots simply do not
  count toward those slots' 10 sessions. Stated, not fixed. Comparing to the previous 20 bars (r0)
  flags every open (U-shaped intraday volume).
- **1min:** yfinance gives 7 days (~5 sessions, `market.py:232-233`), so without a Tradier token the slot
  baseline is usually short and `volume_spike` does not match on 1min. Stated in the dialog tooltip; ask:
  acceptable?
- Baseline <= 0 or judged-bar volume missing/non-finite/<= 0 → **not matched (definite)**, never "no reading"
  (an index with no volume would otherwise freeze an armed watch).

**Q4 — Which bars are judged, and how often it can fire.**
- **Rule:** the closed candle only. The scheduler judges each closed candle once (`_claim_candles_to_evaluate`;
  catch-up at most 3, only the newest after a restart — stated residual). The **chart WebSocket path**
  (`chart.py:100-121`, intraday only) also calls `evaluate_and_notify_for_symbol` with `candles[-2]` on each
  tick that reaches it, without the claim, so the same closed candle can be judged more than once. To make "one
  cross = one alert" hold on both callers, a composite rule with a momentum confirmation stores the closed
  candle time it last fired on (`condition_state["composite_fired_candle"]`) and does not fire again for the
  same candle. (Scoped to momentum rules so no other rule's behaviour changes.)
- **Watch:** every completed bar **since the watch's last judged bar** (`last_state.momentum_through`), capped at
  **500** bars (covers 1min over an EOD day with extended hours); older bars skipped with a WARNING naming the
  count. First run / no stored value = the judged bar only. The regime primary is judged only at run time, so a
  watch can pair a cross from earlier in the window with the regime now (stated difference from the rule).

**Q5 — Which bars.** The alert's own chart candles on both paths (a 1W alert = weekly RSI), not the `get_bars`
daily rows.
- Rule: the caller's candle list cut at the closed candle (`candles[: idx+1]`, idx found by time from the end).
  The closed candle is closed by construction.
- Watch: the same cache key (`get_intraday_with_fetched_at(symbol, interval)`, default `days`),
  `refresh_on_close=True`, `max_age` = one bar span on intraday and `None` on 1D/1W (the scheduler's values,
  `chart_alert_scheduler.py:38-60`); judged bar = `rows[-2]` (the newest row treated as forming, as the rule).
- **1D/1W one-day lag, both paths:** after the close the newest daily row D is complete but both paths judge
  momentum on D-1 until D+1's row exists (same pick as the rule scheduler). The regime on the watch reads
  completed `get_bars` rows through D, so an EOD watch judges regime on D and momentum on D-1 (the rule has the
  same mix: `_regime_candles` keeps D, closed candle D-1). Recommended: accept, documented. Alternative: on
  1D/1W judge the newest *completed* row (breaks the rule/watch pick parity after the close unless the rule
  scheduler changes too — out of scope).

**Q6 — History.** RSI and MACD read a fixed trailing window: the judged bar and the **200 bars before it** (201
total; the extra one gives the previous value for the cross). Fewer → **not matched (definite)** + one WARNING,
not "no reading": a short history is a property of the symbol/fetch window (e.g. a 1W symbol listed < ~4 years,
the 1W fetch being ~260 bars), not a blip, and "no reading" would freeze an armed watch forever. The only
"no reading" is a failed watch fetch (3.4).

**Q7 — Sustain.** A momentum cross is a one-bar event; `sustain_minutes` needs the whole trigger true for N
minutes, which a cross never is on the next candle. Recommended: **a trigger with any momentum confirmation
ignores `sustain_minutes`** (fires on the bar that meets it; one WARNING per rule/watch id when a non-zero
sustain is ignored), and the dialog disables sustain when a momentum row is selected. A latch (r1) was dropped:
it needed a new evaluator input, and the rule's clock is never cleared on a fire (`chart_alerts.py:1082-1093`),
so a latch would re-fire every candle.

**Q8 — Watch re-arm.** Each new cross in the same regime re-arms (trigger false on the next run) and sends a new
alert. Recommended: accept, stated in the tooltip. Alternative: re-arm only when the regime goes false.

**Q9 — Lagged standard-rule MACD (1.7).** Recommended: log as a new backlog defect; not fixed here.

**Q10 — Ownership (round 2 finding 9).** The work package grants the chart_alerts composite block and
`_eval_composite_watch` *inputs*. This plan also needs (a) `_composite_checklist` and `_composite_need_suffix`
(composite-only helpers just above the block: labels, "structure" → "confirmation" wording) and (b)
`_eval_composite_watch`'s state writes (`momentum_through`) and the sustain skip. Recommended: extend ownership
to these. Also (c) WATCH-RULE-BAR-PARITY r6 §2.5 left passing the watch's `direction` into `evaluate_scheduled`
to "the momentum task": recommended **not** taken here (a separate follow-up), recorded in both plans.

## 3. Design (assuming the recommendations)

### 3.1 Pure function — `indicator_compute.py` (additions only)
```python
MOMENTUM_RSI_MACD_HISTORY = 200
def momentum_match(bars, judged: list[int], kind, direction, min_confidence) -> bool
```
True if any judged index matches. RSI/MACD for index `j` computed on `bars[j-200 : j+1]` with a private correct
EMA (`_ema_seeded`) and Wilder RSI (copied, not shared, so `_calc_rsi`/`_calc_macd` and
`compute_indicators_for_conditions` are byte-for-byte unchanged). Direction normalised case-insensitively; other
strings → False. Non-finite/missing OHLCV on a bar a kind reads → False for that bar. Unknown kind → False. Never
raises (a guard returns False and logs).

### 3.2 Evaluator — `composite_trigger_evaluator.py`
- `MomentumInput(bars, judged)` dataclass. `_matched_confirmations(td, structure_signals, indicator_values,
  momentum=None)` returns **confirmation indexes** (internally); momentum `None` = unread. `indicator_values` no
  longer read for momentum (leak 1.2 gone); `indicator_values_at` and its one call deleted; T6 tests rewritten.
- Three-valued gate, one count: `unread = (#structure confs if structure_unread else 0) + (#momentum confs if
  momentum is None else 0)`; `count + unread < min` → False; short → no reading; else True.
- `momentum=` keyword threaded through `evaluate_from_context`, `evaluate_from_context_detailed`,
  `evaluate_scheduled`, `describe_match`. On the rule path `momentum=None` for a rule with momentum confirmations
  cannot happen (the cut always exists); if it did, those confirmations are not matched (fail closed).
- `describe_match`: `structure_matched`/`structure_total` count structure confirmations only; new
  `momentum_matched`/`momentum_total`; plus `matched_indexes` so the checklist marks the right row when two
  confirmations share a kind (e.g. rsi_cross 60 and 70). `format_composite_reason` adds "N/M momentum
  confirmations (…)".
- `has_momentum(td) -> bool` helper used by both paths for the sustain skip and the fetch decision.

### 3.3 Rule path — `chart_alerts.py` composite block (+ Q10 helpers)
- If any composite rule `has_momentum`: `cut` = `all_candles` up to and including the candle whose time equals
  `closed_candle["time"]` (from the end); `MomentumInput(cut, [len(cut)-1])`.
- For a `has_momentum` rule: sustain skipped (Q7); fire suppressed when
  `condition_state["composite_fired_candle"] == closed_candle["time"]`, set when it fires (Q4).
- `_composite_checklist` uses `matched_indexes` and `_MOMENTUM_LABELS`; `_composite_need_suffix` says
  "confirmation signals".

### 3.4 Watch path — `_eval_composite_watch`
- If `has_momentum`: fetch per Q5; fetch failure or < 2 rows → `momentum=None` (unread; the §3.2 count decides
  None vs False vs True) and `momentum_through` **unchanged**. Otherwise judged = indexes of `rows[:-1]` with
  `time > momentum_through` (cap 500, WARNING on skip), or `[len-2]` when none stored; a stored value not
  comparable to row times (type change) → `[len-2]`.
- `momentum_through` = `rows[-2].time` is written **through `_write_effective`** (WATCH-UNDELIVERED-EVENT-RESEND is
  shipped; a plain `_write` would drop `pending_events`) on **every path that got a reading**: armed+fired (today
  no write — one is added), armed→idle, sustain paths (not reached for momentum triggers, Q7), not-fired, and in
  the transition's `new_state` for an entry (commits with delivery).
- Sustain skipped for `has_momentum` triggers (Q7).

### 3.5 Dialog (Q0 = a) — rows, labels, sustain disable as Q0. Jest; `npm run typecheck`.

## 4. Tests, each with the mutation it must kill

1. `momentum_match` per kind × {Bullish, Bearish, None}: cross on the judged bar → True; opposite-direction
   cross with Bullish/Bearish → False (each kind; volume with the wrong candle colour); null matches up-through-L
   and down-through-100-L but not down-through-L; `prev == L` edges. Mutations: `<=`→`<`; drop `100-L`; ignore
   direction; null = "through L either way".
2. MACD: a last-bar spike that makes the line cross → True on that bar. Mutation: reuse `_ema_values`.
3. History: 201 bars → judged; 200 → False (+ WARNING once); same last 201 bars with 300 vs 1500 bars of prior
   history → same answer where full-history RSI differs. Mutations: drop the slice; min 200.
4. Volume: open-slot bar ≥ 2× prior 20 bars but < 2× its slot → False; zero-volume symbol → False; missing
   judged volume → False; 4 slot sessions → False; 1D with 19 prior → False; 4h slots across a DST switch keyed
   by UTC bucket. Mutations: prior-20 intraday; drop `baseline > 0`; Eastern
   time slot.
5. Normalisation: `"bullish"` ok; `min_confidence` `"60"`/`True`/`0`/`100` → False, no raise.
6. Standard rules unchanged: golden `compute_indicators_for_conditions` for every name in its table.
7. Leak gone: a standard series named `rsi_cross` no longer satisfies a composite.
8. Rule (via `_fire`): cross completed by the closed candle → fires; only on the forming candle → not. Via
   `evaluate_closed_candles` with a primed last-seen candle: a catch-up candle is judged on its own prefix; with
   an explicit `as_of` and sandbox-lagged 4h (closed candle absent from `_regime_candles`) still judged.
   Mutations: use `_regime_candles`; use `all_candles` uncut.
9. Once per cross: same closed candle evaluated twice (WS path simulation) → one fire; next candle without a
   cross → no fire. Mutations: drop `composite_fired_candle`; lookback 3.
10. Watch: spy asserts `evaluate_scheduled` got a non-None `momentum`; fetch raises + no other confirmation → None,
    state untouched, `momentum_through` unchanged; fetch raises + structure already meets min → True and
    `momentum_through` unchanged; 16 bars since last run with the cross on the 3rd → fires; armed + fired →
    `momentum_through` advanced; a watch with `pending_events` keeps its queue. Mutations: pass None; judge last
    bar only; `_write` instead of `_write_effective`; no write on armed+fired.
11. **Parity:** one candle list; rule on closed candle X vs watch with `momentum_through = X-1` and fetch rows up
    to X+1 → same answer for 1h, 4h, 1D, 1W × directions × kinds; after-close 1D case: both judge D-1. Mutation:
    watch judges `rows[-1]`. Stated limit: it cannot see a real fetch difference between the paths.
12. Three-valued gate: momentum-only + structure raising + momentum False → False; momentum unread + count+unread ≥
    min → None; < min → False. Mutation: OR instead of the count.
13. Sustain skip: momentum trigger with sustain 30 fires on the cross bar (rule and watch), WARNING once; a
    non-momentum trigger's sustain unchanged. Mutation: skip sustain for every trigger.
14. Checklist: rsi_cross 60 and 70, only 60 matched → only its row met. Mutation: match by kind.
15. (Q0 = a) Jest: rows, labels per direction, sustain disabled, save `type: 'momentum'`.

Runs: backend full suite (`backend/.venv/bin/python -m pytest`), `python3 scripts/state.py` exit 0 with the phase
`verify` switched to a presence probe on `momentum_match` (test 10's spy proves the watch supplies it), frontend
typecheck + jest if the dialog is touched.

## 5. Ownership and coordination
- **Owned:** per the work package + Q10. **Do not touch:** rest of `chart_alerts.py`, `dispatch.py`, chart
  display windows, `_calc_macd`/`_ema_values` (Q9), chart_alert_scheduler, chart.py.
- **WATCH-RULE-BAR-PARITY** (§2.9): both own the composite block; this plan reads only the caller's candle list
  and adds `momentum=`; no shared bar series. Whoever merges second merges main in and resolves. The `direction=`
  pass-through (their §2.5) stays their follow-up (Q10c).
- **WATCH-UNDELIVERED-EVENT-RESEND** is shipped: all watch writes go through `_write_effective`.

## 6. Round dispositions
**Round 1 (17, none rejected):** 1 → 1.7, Q2, Q9, test 2. 2 → Q5 cut at the closed candle, test 8. 3 → Q5
`rows[-2]`, test 11. 4 → Q4 bars since last run. 5 → Q3 definite False. 6 → Q3 slot baseline. 7 → Q4. 8 → Q7.
9 → 3.2 single count. 10 → Q5/§5. 11 → Q6. 12 → Q5 freshness. 13 → Q1 normalisation. 14 → 3.2 wording. 15 →
Q0 labels. 16 → test 1. 17 → test 10 spy. Missing re-arm → Q8.
**Round 2 (16, none rejected):** 1, 2 → latch dropped; Q7 = sustain ignored for momentum triggers, test 13.
3 → Q3 UTC-bucket slot, half days, 1min stated/asked, test 4. 4 → 3.4 `_write_effective` on every reading
path, test 10. 5 → 3.4 fetch-failure outcome by the count, `momentum_through` unchanged, test 10. 6 → Q4
`composite_fired_candle`, test 9. 7 → Q5 1D/1W lag stated and asked. 8 → Q6 definite False, 201 pinned, test
3. 9 → Q10. 10 → 3.2 per-index + totals, test 14. 11 → cap 500 + WARNING. 12 → Q4/Q5 residuals, `max_age`
None on 1D/1W. 13 → Q1 WARNING + null formula. 14 → Q3 1D/1W < 20. 15 → test 8 via `evaluate_closed_candles`.
16 → Q10c.

## 7. Loop
Plan → adversarial rounds until clean → Kenneth's answers → plan revised to the answers (re-audited if the design
changed) → build with the mutation checks above → code rounds until clean → state record → merge only with
Kenneth's approval.
