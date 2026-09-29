# COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD — plan (r5, plan stage CLOSED by Kenneth; build unit A next)

- **Phase:** `COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD` (PROJECT_STATE.json), decision `P4B-FOLLOWUPS-2026-09-26`, item 1.
- **Scope source:** `docs/superpowers/plans/2026-09-25-work-packages.md` → "P4b follow-ups" → "COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD (item 1)".
- **Branch:** `claude/composite-momentum-confirmations` (off `origin/main` at `adb597c`).
- **Status:** section 2 ANSWERED 2026-09-29 — Kenneth: **yes to all recommendations** (decision
  `COMPOSITE-MOMENTUM-ANSWERS-2026-09-29`): Q0 (a), Q4 single `rows[-2]` bar, Q12 (a), all others as recommended.
  The design in section 3 is therefore unchanged. Plan stage is past its 3-round cap; Kenneth allowed ONE gated
  round 5 over the round-4 fixes and the answers (`COMPOSITE-MOMENTUM-PLAN-CAP-2026-09-29`), and split the build:
  **unit A** = backend (3.1-3.4, save validation, tests 1-14 and 16-18), **unit B** = dialog (3.5, test 15).
  Continued on branch `ccr-2fe3aef8-jpt3lz`.
- **Plan stage CLOSED 2026-09-29** (decision `COMPOSITE-MOMENTUM-PLAN-CLOSED-2026-09-29`): round 5 found one
  gate-level defect (Q11 4h session filter); Kenneth chose to apply the fix (Q11 span-overlap rule, test 17 4h
  cases) WITHOUT a further plan round and go straight to building **unit A**. The code stage starts at code
  round 1 of 3 (continuous numbering: round 6 = code round 1).

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
- **Intraday (incl. 4h):** mean volume of the **same slot over the previous 10 sessions** (at least 5, else
  not matched + one WARNING). Slot = the bar's **Eastern wall-clock time of day** (so the 09:30 open bar is always
  compared with previous 09:30 bars across DST, and a Tradier pre-market bar only with pre-market bars). 4h
  buckets are UTC-anchored (`resample(origin="epoch")`, `market.py:279-282`; IBKR the same) and start at
  08:00/12:00 ET in EDT but 07:00/11:00/15:00 ET in EST, so the Eastern slot key already never mixes DST regimes;
  for ~5 sessions after a switch there are too few matches → not matched (stated). The code has no early-close calendar
  (`market_session` has none; P4b item 6 was closed as accepted), so half days are not excluded — see Q12. Comparing to the previous 20 bars (r0) flags every
  open (U-shaped intraday volume).
- **1min:** yfinance gives 7 days (~5 sessions, `market.py:232-233`), so without a Tradier token the slot
  baseline is usually short and `volume_spike` does not match on 1min. Stated in the dialog tooltip; ask:
  acceptable?
- Baseline <= 0 or judged-bar volume missing/non-finite/<= 0 → **not matched (definite)**, never "no reading"
  (an index with no volume would otherwise freeze an armed watch).

**Q4 — Which bar is judged, and how often it can fire.**
- **Rule:** the closed candle only. The scheduler judges each closed candle once (`_claim_candles_to_evaluate`;
  catch-up at most 3, only the newest after a restart — stated residual). The chart WebSocket path
  (`chart.py:100-121`, intraday only, fetched without `refresh_on_close`) also calls
  `evaluate_and_notify_for_symbol` with its `candles[-2]`, without the claim, so a closed candle can be judged
  more than once. A composite rule with a momentum confirmation therefore stores `{"interval": iv, "time": t}` of
  the newest candle it fired on (`condition_state["composite_fired_candle"]`) and does not fire for a closed
  candle of the **same interval** with `time <= t` (type-guarded; non-int or other interval → no suppression;
  `replace_rule` keeps `condition_state` across an interval edit, `chart_alerts.py:662,685-686`). Residual, stated: the WS path and the scheduler
  run in separate DB sessions, so two truly concurrent evaluations can both fire (same race the cooldown comment
  documents, `chart_alerts.py:1099-1113`).
- **Watch — Kenneth decides (Q4 is a question, not a settled design): recommended the same single bar as the rule** (`rows[-2]` of the same chart-cache fetch, Q5). Exact
  rule/watch parity, no new watch state, and the existing once-per-entry `armed` phase does the rest (a 1D watch
  polled every 4h sees the same cross bar all day → one alert; the next day no cross → re-arms). **Cost:** a watch
  only sees the bar that closed last before each run, so an intraday momentum watch misses crosses between runs
  (a 15min watch polled every 4h sees 1 bar in 16). Recommendation: use **rules** for intraday momentum; watches
  suit 1D/1W. The dialog tooltip says so.
- Alternative (r1/r2): the watch judges every bar since its last run. Rejected on complexity after round 3: it
  needs stored `momentum_through` state, a time bound so a re-enabled or long-down watch does not alert on weeks-old
  crosses, per-bar evaluation so two momentum confirmations cannot match on different bars, and new re-arm rules
  so consecutive-window crosses are not swallowed. Available as a follow-up if Kenneth wants intraday watches.

**Q5 — Which bars.** The alert's own chart candles on both paths (a 1W alert = weekly RSI), not the `get_bars`
daily rows.
- Rule: the caller's candle list cut at the closed candle (`candles[: idx+1]`, idx found by time from the end).
  The closed candle is closed by construction.
- Watch: the same cache key (`get_intraday_with_fetched_at(symbol, interval)`, default `days`),
  `refresh_on_close=True`, `max_age` = one bar span on intraday and `None` on 1D/1W (the scheduler's values,
  `chart_alert_scheduler.py:38-60`); judged bar = `rows[-2]` (the newest row treated as forming, as the rule). The alert
  text names the judged bar's time and close, since the watch event's price is the daily close.
- **1D/1W one-day lag, both paths:** after the close the newest daily row D is complete but both paths judge
  momentum on D-1 until D+1's row exists (same pick as the rule scheduler). The regime on the watch reads
  completed `get_bars` rows through D, so an EOD watch judges regime on D and momentum on D-1 (the rule has the
  same mix: `_regime_candles` keeps D, closed candle D-1). The same one-bar lag applies to an EOD watch on an
  intraday interval (with Q11, a run at 16:15 ET judges the last regular-session bar only once a newer regular bar
  exists, i.e. the next session). Recommended: accept, documented. Alternative: on
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

**Q8 — Watch re-arm.** With Q4's single judged bar, the trigger goes false on the first run whose judged bar has
no cross, and the watch re-arms; the next cross in the same regime sends a new alert. Recommended: accept, stated
in the tooltip. Alternative: re-arm only when the regime goes false.

**Q8b — Rule cooldown.** The default 60-minute rule cooldown (`chart_alerts.py:122`) also suppresses a second
distinct cross within the hour on 1min/5min rules. Recommended: keep (it is the rule's own setting and visible);
stated in the tooltip.

**Q9 — Lagged standard-rule MACD (1.7).** Recommended: log as a new backlog defect; not fixed here.

**Q10 — Ownership (round 2 finding 9).** The work package grants the chart_alerts composite block and
`_eval_composite_watch` *inputs*. This plan also needs (a) `_composite_checklist` and `_composite_need_suffix`
(composite-only helpers just above the block: labels, "structure" → "confirmation" wording) and (b)
the sustain skip in `_eval_composite_watch`, and (c) **validation on save**: `create_rule`/`replace_rule`
(`chart_alerts.py:605,668`) store `composite_def` raw and `CompositeWatchCreate.trigger_def` is a plain dict,
so nothing enforces the schema (files: `chart_alerts.py` create/replace handlers, `routers/composite_watch.py`); add a 422 for a momentum confirmation whose kind is not one of the three,
direction not Bullish/Bearish/null (case-insensitive), or `rsi_cross` `min_confidence` not an int in 1..99 —
otherwise a bad value is stored and silently never fires, the very defect this package fixes. On PUT the 422 applies only when the momentum confirmations differ
from the stored `composite_def` (the frontend toggles `enabled` by re-sending the full rule, `chart_alerts.py:679-684`;
same exemption as A4f, `:649-659`). The watch check is an `HTTPException(422)` in `routers/composite_watch.py`
(its `ValueError` → 400 mapping is left alone). The runtime guard stays for already-stored rows. Recommended: extend ownership
to these. Also (d) WATCH-RULE-BAR-PARITY r6 §2.5 left passing the watch's `direction` into `evaluate_scheduled`
to "the momentum task": recommended **not** taken here (a separate follow-up), recorded in both plans.

**Q11 — Extended hours (round 4).** With a Tradier token, intraday series include pre-/post-market bars
(`session_filter: "all"`, `market.py:407`); yfinance does not. Recommended: **momentum on intraday reads
regular-session bars only** — RSI/MACD/volume inputs are filtered to 09:30-16:00 ET, and a judged bar outside
regular hours is not matched. **(r5 fix) A bar is regular when its SPAN `[t, t + interval)` OVERLAPS
09:30-16:00 ET on its Eastern date — never by its start time alone:** 4h bars are UTC-epoch buckets
(`market.py:271-282`, IBKR `ibkr.py:174,250-251` the same) stamped 08:00 ET (EDT) / 07:00 ET (EST) while holding
the 09:30-11:59 1h bars, so a start-time test would drop the morning 4h bar from every input and never judge it.
A Tradier 09:25 5min bar (span ends 09:30) and a 16:00 post-market bar (span starts at 16:00) stay excluded;
1D/1W are not filtered. So a rule gives the same signal with or without a token, and thin pre-market bars
never cross RSI/MACD. (The watch's `rows[-2]` is taken after the filter.)

**Q12 — Half-day sessions (a design call r2 made alone; now put to Kenneth).** The code has no early-close
calendar, so the intraday volume baseline cannot recognise a half day: its 12:45/13:00 ET closing-auction bar can
read as a `volume_spike` against normal 12:45 bars, and RSI/MACD treat the short session as normal bars.
- (a) Recommended: **accept and document** (about 3 half days a year; affects intraday `volume_spike` only).
- (b) Add a small hard-coded NYSE early-close date list (maintained yearly) and leave those sessions out of the
  baseline and the judged set (new file, outside ownership — needs your OK).

**Residual (round 4 finding 7), stated:** the watch has no marker of bars it judged, so if the daily chart row
for today does not exist yet while the `get_bars` regime already moved forward, the watch can pair a cross on an
older bar with today's regime (the rule, judging each candle once with that candle's regime, would not). Rare
(early-session window on 1D) and documented; a fix needs a freshness rule on the judged bar — follow-up if
Kenneth wants it.

## 3. Design (assuming the recommendations)

### 3.1 Pure function — `indicator_compute.py` (additions only)
```python
MOMENTUM_RSI_MACD_HISTORY = 200
def momentum_match(bars, interval, kind, direction, min_confidence, log_key) -> bool
```
Judges the last bar of `bars`. `interval` picks the Q3 baseline and slot keys; `log_key` (rule/watch id) dedupes
the one-per-id WARNINGs (module-level set). RSI/MACD for the last bar and the one before it, computed on the last 201 bars with a private correct
EMA (`_ema_seeded`) and Wilder RSI (copied, not shared, so `_calc_rsi`/`_calc_macd` and
`compute_indicators_for_conditions` are byte-for-byte unchanged). Direction normalised case-insensitively; other
strings → False. Non-finite/missing OHLCV on a bar a kind reads → False for that bar. Unknown kind → False. Never
raises (a guard returns False and logs).

### 3.2 Evaluator — `composite_trigger_evaluator.py`
- `MomentumInput(bars, interval, log_key)` dataclass. `_matched_confirmations(td, structure_signals, indicator_values,
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
- `has_momentum(td) -> bool` = at least one momentum confirmation **and** `min_confirmations > 0` (with 0 the
  confirmations are never evaluated, `composite_trigger_evaluator.py:417-421,558-570`, so sustain must still
  apply) — helper used by both paths for the sustain skip and the fetch decision.

### 3.3 Rule path — `chart_alerts.py` composite block (+ Q10 helpers)
- If any composite rule `has_momentum`: `cut` = `all_candles` up to and including the candle whose time equals
  `closed_candle["time"]` (from the end); `MomentumInput(cut, interval, rule id)`.
- For a `has_momentum` rule: sustain skipped (Q7); fire suppressed per Q4
  (`composite_fired_candle`, same interval, `time <=`), set when it fires.
- `_composite_checklist` uses `matched_indexes` and `_MOMENTUM_LABELS`, reading `detail.get("matched_indexes")` with a by-kind fallback for older detail dicts (the same-kind caveat, `chart_alerts.py:341-350,372-373`, is deleted — per-index matching makes it wrong); `_composite_need_suffix` says
  "confirmation signals".

### 3.4 Watch path — `_eval_composite_watch`
- If `has_momentum`: fetch per Q5; fetch failure or < 2 rows → `momentum=None` (unread; §3.2's count decides None
  vs False vs True). Otherwise `MomentumInput(rows[:-1], fetch_iv, watch id)`. No new watch state.
- Sustain skipped for `has_momentum` triggers (Q7). State writes unchanged (all existing paths already use
  `_write_effective`).
- The event reason includes the judged bar's time and close.

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
   judged volume → False; 4 slot sessions → False; 1D with 19 prior → False; 5min open bar after the November DST switch compared with
   09:30 ET bars, not 10:30; a Tradier pre-market bar never in the open's baseline; 4h baseline across DST excludes
   the other DST regime (by the slot key alone). Mutations: prior-20 intraday; drop `baseline > 0`; UTC
   time-of-day slot.
5. Normalisation: `"bullish"` ok; `min_confidence` `"60"`/`True`/`0`/`100` → False, no raise.
6. Standard rules unchanged: golden `compute_indicators_for_conditions` for every name in its table.
7. Leak gone: a standard series named `rsi_cross` no longer satisfies a composite.
8. Rule (via `_fire`): cross completed by the closed candle → fires; only on the forming candle → not. Via
   `evaluate_closed_candles` with a primed last-seen candle: a catch-up candle is judged on its own prefix; with
   an explicit `as_of` and sandbox-lagged 4h (closed candle absent from `_regime_candles`) still judged.
   Mutations: use `_regime_candles`; use `all_candles` uncut.
9. Once per cross (`cooldown_minutes=0`): same closed candle evaluated twice → one fire; an older candle after a
   newer fired one → no fire; next candle without a cross → no fire. Variant: 4h, 60-min cooldown, second
   evaluation 90 min later → still one fire. Mutations: drop `composite_fired_candle`; `==` instead of `<=`. Plus: 1h→1D interval edit, first daily
   candle with a cross fires. Mutation: ignore the interval key.
10. Watch: spy asserts `evaluate_scheduled` got a non-None `momentum` whose bars end at `rows[-2]`; fetch raises +
    no other confirmation → None and state untouched; fetch raises + structure already meets min → True; 1D watch
    run twice on the same cross bar → one alert (armed), next run with no cross → re-armed. Mutations: pass None;
    judge `rows[-1]`.
11. **Parity:** one candle list; rule on closed candle X vs watch whose fetch returns rows up to X+1 → same answer
    for 1h, 4h, 1D, 1W × directions × kinds, including a trigger with two momentum confirmations; after-close 1D
    case: both judge D-1. Mutation: watch judges `rows[-1]`. Stated limit: it cannot see a real fetch difference.
12. Three-valued gate: momentum-only + structure raising + momentum False → False; momentum unread + count+unread ≥
    min → None; < min → False. Mutation: OR instead of the count.
13. Sustain skip: momentum trigger with sustain 30 fires on the cross bar (rule and watch), WARNING once; a
    non-momentum trigger's sustain unchanged; `min_confirmations` 0 + a momentum confirmation + sustain 30 still
    honours the sustain. Mutations: skip sustain for every trigger; `has_momentum` ignoring the minimum.
14. Checklist: rsi_cross 60 and 70, only 60 matched → only its row met. Mutation: match by kind.
15. (Q0 = a) Jest: rows, labels per direction, sustain disabled, save `type: 'momentum'`.
16. Save validation (Q10c): rule create/PUT and watch create with `rsi_cross` `min_confidence` 0 or `"60"`, an
    unknown momentum kind, or direction `"up"` → 422; valid ones stored; PUT with an unchanged invalid
    `composite_def` and `enabled: false` → 200. Mutations: drop the check; drop the PUT exemption.
17. Extended hours (Q11): token-style series with pre/post bars — RSI inputs exclude them (a pre-market-only
    cross → False); a judged post-market bar → False; a 09:25 5min bar and a 16:00 5min bar excluded; the watch
    at 16:15 ET judges a regular bar. **4h (r5):** an EDT series (morning bar stamped 08:00 ET) and an EST series
    (07:00 ET) where the morning 4h bar holds the cross → matched, and the morning bars are in the RSI inputs
    (reading equals the unfiltered 4h RSI on a regular-only 1h source). Mutations: no session filter; classify by
    start time; overlap test with `<=` at the 09:30/16:00 edges.
18. Existing tests updated, not deleted: `test_chart_alerts_notification_text.py:387,402` ("confirmation signals"),
    `test_composite_sustain.py:48,147` and `test_p4b_watch_isolation_and_delivery.py:93` (detail dicts without
    `matched_indexes` still work via the fallback), `test_p4b_momentum_confirmations.py` (rewritten off
    `indicator_values_at`).

Runs: backend full suite (`backend/.venv/bin/python -m pytest`), `python3 scripts/state.py` exit 0 with the phase
`verify` switched to a presence probe on `momentum_match` (test 10's spy proves the watch supplies it), frontend
typecheck + jest if the dialog is touched.

## 5. Ownership and coordination
- **Owned:** per the work package + Q10. **Do not touch:** rest of `chart_alerts.py`, `dispatch.py`, chart
  display windows, `_calc_macd`/`_ema_values` (Q9), chart_alert_scheduler, chart.py.
- **WATCH-RULE-BAR-PARITY** (§2.9): both own the composite block; this plan reads only the caller's candle list
  and adds `momentum=`; no shared bar series. Whoever merges second merges main in and resolves. The `direction=`
  pass-through (their §2.5) stays their follow-up (Q10d).
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
16 → Q10d.
**Round 3 (9, none rejected):** 1 → Q3 ET wall-clock slot + 4h same-UTC-offset filter, test 4. 2, 3, 4, 9a-c →
Q4 watch judges the single `rows[-2]` bar (multi-bar window dropped; stated cost, follow-up option), Q8 reworded,
tests 10-11. 5 → 3.1 signature `interval`, `log_key`. 6 → Q10c save validation, test 16. 7 → test 9
`cooldown_minutes=0` + 4h variant. 8 → Q4 `<=` + concurrency residual. 9d → Q5 intraday EOD lag. 9e → Q5/3.4 alert
names the judged bar. 9f → 3.3 caveat deleted. 9g → Q8b. (r3 superseded the round-2 dispositions that mention
`momentum_through`, the 500 cap and the multi-bar window.)
**Round 5 (gated, shrinking target: r3->r4 diff + Kenneth's answers) — NOT CLEAN, 1 gate-level finding, verified
against the code:** Q11's regular-session filter keys on a bar's START time, but 4h bars are UTC-epoch buckets of
1h regular bars (`market.py:271-282`, IBKR the same), stamped 08:00 ET (EDT) / 07:00 ET (EST) while holding the
09:30-11:59 bars. The filter would drop the morning 4h bar from RSI/MACD/volume inputs (every 4h reading wrong) and
never judge it (a real morning cross never fires), with or without a token, on both paths. Per decision
`COMPOSITE-MOMENTUM-PLAN-CAP-2026-09-29` the plan stage stopped and went to Kenneth, who chose (b): fix applied
in r5 without a further round (`COMPOSITE-MOMENTUM-PLAN-CLOSED-2026-09-29`). Fix (APPLIED, Q11 + test 17): classify a bar as regular when its SPAN `[t, t+interval)` overlaps 09:30-16:00 ET (source-agnostic;
a Tradier 09:25 5min bar still excluded), test 17 gains EDT and EST 4h cases where the morning bar holds the
cross (mutation: classify by start time). Alternative: apply the filter only to `1min/5min/15min`.
**Round 4 (9, none HIGH, none rejected):** 1 → 3.1/3.3 stale r2 text fixed. 2 → Q3 4h filter dropped (the Eastern
slot key already separates DST), test 4. 3 → Q10c PUT exemption, test 16. 4 → Q11 regular session only, Q5
corrected, test 17. 5 → `has_momentum` needs `min_confirmations > 0`, test 13. 6 → `composite_fired_candle` keyed
by interval, test 9. 7 → stated residual after Q11. 8 → Q10c files + router 422. 9 → test 18, `.get` fallback.

## 7. Loop
Plan → adversarial rounds until clean → Kenneth's answers → plan revised to the answers (re-audited if the design
changed) → build with the mutation checks above → code rounds until clean → state record → merge only with
Kenneth's approval.

## 8. Unit A build record (2026-09-29, branch `ccr-2fe3aef8-jpt3lz`)
- **Built:** 3.1 (`indicator_compute.momentum_match`, `momentum_session_bars`, `_ema_seeded`, Wilder RSI copy),
  3.2 (`MomentumInput`, `_matched_indexes`, `has_momentum`, `momentum_sustain_ignored`, `momentum=` through
  `evaluate_from_context[_detailed]` / `evaluate_scheduled` / `describe_match`, `format_composite_reason`
  momentum part; `indicator_values_at` deleted), 3.3 (cut at the closed candle, Q7 sustain skip, Q4
  `composite_fired_candle`, per-index checklist, `_MOMENTUM` labels, "confirmation signals"), 3.4
  (`_composite_watch_momentum`: chart-cache fetch, session filter, `rows[-2]`; sustain skip; judged bar named in
  the reason), Q10c (`momentum_confirmation_error`, 422 on rule create/PUT with the unchanged-momentum
  exemption, and on watch create).
- **Tests:** `tests/test_composite_momentum_match.py` (1-7, 12, 14, 17 unit), `tests/test_composite_momentum_paths.py`
  (8-11, 13, 16, 17 watch), `tests/test_p4b_momentum_confirmations.py` rewritten (18), notification-text test
  wording (18). **Mutations: 30/30 killed** (every mutation named in section 4, plus sustain-kept-for-momentum on
  each path).
- **Deviations for the code round to judge:**
  1. `evaluate_scheduled` applies the single structure+momentum count only when the trigger HAS a momentum
     confirmation; a momentum-free trigger keeps its old rule (a shortfall with structure unread is no reading),
     because `tests/test_composite_watch_keyerror.py` pins it and it is outside this package's scope.
  2. `_composite_checklist` drops the same-kind caveat when `matched_indexes` is present (3.3) but KEEPS it on the
     by-kind fallback for a detail dict without `matched_indexes`, where it is still true.
  3. `indicator_values` stays as an ignored parameter of `evaluate_from_context[_detailed]` / `describe_match`
     (about 45 test call sites pass it positionally); the rule path passes `{}`.
  4. A flat RSI window (both Wilder averages 0) reads 50, not `_calc_rsi`'s 100, so a flat series never "crosses".
- Q9 logged in `PROJECT_STATE.json` open_questions as a backlog defect.
