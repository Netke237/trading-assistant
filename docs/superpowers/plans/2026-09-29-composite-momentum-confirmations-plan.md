# COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD — plan (r1, after adversarial round 1; decisions pending)

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
  through 40"; direction "any" = either way / any candle colour, stated next to the checkbox), plus a line under the
  N-of-M control: "N of the selected confirmations (structure and momentum together)".
- (b) Backend only (API/YAML users only).
- (c) Remove them instead: the schema refuses `type: "momentum"` on create; stored ones never match, logged. None
  exist in shipped config. Cheapest; no new trading signal.

**Q1 — `rsi_cross`.** Recommended: RSI(14) **crosses a level on the judged bar**. Bullish `prev <= L < cur`,
`L = min_confidence` (60 → "into 60+"); Bearish `prev >= 100-L > cur` (60 → "into 40-"); direction null = either.
Same edges as the standard `crosses_above/below` (`alert_evaluator.py:239-254`). `min_confidence` outside
1..99, non-int, or bool → not matched (debug log). Rejected: "RSI >= 60" (a level; fires every bar of a trend).

**Q2 — `macd_cross`.** Recommended: MACD(12,26,9) line crosses its signal line on the judged bar (Bullish up,
Bearish down, null either), from a **correct** EMA (SMA-seeded, current bar included). `min_confidence` unused.
Alternative: also require the line on the matching side of zero.

**Q3 — `volume_spike`.** Recommended: judged bar's volume >= **2.0×** a baseline, and its candle agrees with
the direction (Bullish close > open, Bearish close < open, null any). `min_confidence` unused. Baseline:
- **1D/1W:** mean volume of the 20 bars before it.
- **Intraday (incl. 4h):** mean volume of the **same time-of-day bar over the previous 10 sessions** (at least 5
  found, else not matched). Comparing to the previous 20 bars flags every open (U-shaped intraday volume) and the
  larger morning 4h bucket; a slot baseline removes both.
- Baseline <= 0, or the judged bar's volume missing/non-finite/<= 0 → **not matched (definite)**, never "no
  reading" — a symbol with no volume (e.g. an index) would otherwise freeze an armed watch forever.

**Q4 — Which bars are judged, and how often it can fire.** Recommended:
- **Rule:** the closed candle only (lookback 1). The scheduler already judges every closed candle once, so a
  cross can fire the rule once — no triple fire on 1h/1D where the 60-min cooldown is shorter than a bar.
- **Watch:** every completed bar **since the watch's last judged bar** (stored as `last_state.momentum_through`,
  capped at 100 bars; first run or missing value = the last bar only). A 15min watch polled every 4h then sees
  all 16 bars, not 1. The regime primary is still judged only at run time (a cross that happened while the regime
  was not yet in state counts once the regime is in state, if it lies within the bars since the last run — stated
  difference from the rule, which needs both on the same candle).
- Rejected: a fixed 3-bar lookback (r0) — at the default 4h poll a 15min watch saw 3 of 16 bars and a 1D rule
  re-fired on 3 consecutive closes.

**Q5 — Which bars, per interval.** Recommended: **the rule's own chart candles** on both paths, not the
`get_bars` daily rows (momentum means "the chart you set the alert on"; a 1W alert = weekly RSI).
- Rule: the scheduler's candle list cut at the closed candle (`view[: idx+1]`). That candle is closed by
  construction, so there is no completeness filter to fail (r0 used `_regime_candles`, which routinely lacks the
  closed candle on 4h and sandbox-lagged intraday — round 1 finding 2).
- Watch: the **same cache key** (`get_intraday_with_fetched_at(symbol, interval)`, default `days`) with the
  scheduler's freshness (`refresh_on_close=True`, `max_age` = one bar span), and the scheduler's pick: the judged
  bar is `rows[-2]` (the newest row is treated as forming, exactly as the rule does). So on 1D after the close
  both paths judge D-1 until D+1's row exists — the same structural lag Kenneth accepted in WATCH-RULE-BAR-PARITY
  Q-E, but here identical on both paths.
- Independent of WATCH-RULE-BAR-PARITY's model series (it reads neither `_regime_candles` nor their cut series).

**Q6 — Too few bars.** RSI and MACD read a fixed trailing window of **200 bars** ending at the judged bar (so the
answer does not depend on how much history a fetch returned; the smallest default chart window, 1W ≈ 260 bars,
covers it). Fewer than 200 bars → **no reading**: watch → `None` (state unchanged), rule → not matched. Volume: Q3.

**Q7 — Sustain (missing in r0).** A momentum cross is an event; `sustain_minutes` requires the whole trigger to
stay true for N minutes, which a single-bar cross never does (rule), and a watch needs two runs. Recommended:
**momentum confirmations are latched while a sustain is pending** — the rule/watch stores the matched momentum
kinds in its sustain state (`condition_state["composite_momentum"]` / `last_state.pending_momentum`) when the
pending clock starts, and they count until the clock completes or the rest of the trigger goes false.
Alternative: refuse sustain > 0 together with momentum on save (touches the create endpoints — outside ownership).

**Q8 — Watch re-arm (missing in r0).** An armed watch re-arms when the trigger goes false. A momentum-gated
trigger goes false on the next run with no new cross, so each new cross in the same regime sends a new alert.
Recommended: **accept** (each new cross is a new confirmation; this is the point of a momentum confirmation) and
say so in the dialog tooltip. Alternative: re-arm only when the primary regime goes false (changes the "once per
entry" rule, decision of 2026-09-25).

**Q9 — The lagged standard-rule MACD (1.7).** Recommended: log as a new backlog defect (standard `macd` /
`macd_signal` alerts judge the previous bar and are wrong for ~40 bars of warm-up); not fixed here.

## 3. Design (assuming the recommendations; adjusted to the answers before building)

### 3.1 Pure functions — `indicator_compute.py` (additions only)
```python
MOMENTUM_WINDOW = 200
def momentum_match(bars, judged: list[int], kind, direction, min_confidence) -> bool | None
```
- `bars`: chart candles oldest→newest ending at the newest judged bar; `judged`: indexes of the bars to test
  (rule: `[len-1]`; watch: the bars since `momentum_through`). True if any judged bar matches; None if some
  judged bar lacked warm-up and none matched; False otherwise.
- RSI/MACD for judged bar `j` are computed on `bars[j-199 : j+1]` (+1 previous bar for the cross) with a private
  correct EMA (`_ema_seeded`) and Wilder RSI; `_calc_rsi`/`_calc_macd`/`compute_indicators_for_conditions` untouched.
- Direction normalised case-insensitively (`"bullish"` ok); any other string → not matched. Non-finite/missing
  close → None for RSI/MACD. Unknown `kind` → not matched (definite).
- Volume per Q3: intraday slot = the Eastern time-of-day of an int `time`; slot bars from the previous sessions
  within `bars`.

### 3.2 Evaluator — `composite_trigger_evaluator.py`
- `_matched_confirmations(td, structure_signals, indicator_values, momentum=None)`; `momentum` is a
  `MomentumInput(bars, judged)` or None (→ momentum not matched). `indicator_values` is no longer read for momentum
  (removes the name-collision leak, 1.2). `indicator_values_at` deleted with its call (only use), T6 tests rewritten.
- One count for the three-valued gate (round 1 finding 9): `unread = (#structure confirmations if structure_unread
  else 0) + #momentum confirmations returning None`; `count + unread < min` → definite False; else short → no
  reading; else True.
- Threaded through `evaluate_from_context`, `evaluate_from_context_detailed`, `evaluate_scheduled`,
  `describe_match` as a keyword `momentum=None`.
- `describe_match` gains `momentum_matched` (and `structure_matched` stays structure-only);
  `format_composite_reason` adds "N/M momentum confirmations (…)". Rule-path wording
  `_composite_need_suffix` "structure signals" → "confirmation signals" (composite-only helper).

### 3.3 Rule path — `chart_alerts.py` composite block (+ its composite-only helpers)
- Only if some composite rule has a momentum confirmation: `_momentum = MomentumInput(cut, [len(cut)-1])` with
  `cut = all_candles` up to and including the candle whose `time == closed_candle["time"]` (searched from the end,
  as `closed_candle_structure`); not found → `None` (unreachable: both callers take the closed candle from that
  list).
- Sustain latch (Q7): when the rule's pending clock starts, store `describe_match`'s `momentum_matched` in
  `condition_state["composite_momentum"]`; while pending, those kinds count as matched; cleared with the clock.
- `_composite_checklist`: momentum rows labelled from a `_MOMENTUM_LABELS` map, `met` from `momentum_matched`.

### 3.4 Watch path — `strategy_watch_evaluator._eval_composite_watch`
- Only if the trigger has a momentum confirmation: fetch as Q5, `rows[:-1]` (need ≥ 2 rows), judged = indexes with
  `time > last_state.momentum_through` (cap 100; none stored → last index). Fetch failure → momentum `None`-reading
  (→ `None`, state unchanged).
- After any run that returned a reading, persist `momentum_through = rows[-2].time` together with the state write
  that run makes (every branch of the function that writes, and a write on the no-transition path). If the run
  returns a transition, it is carried in the transition's `new_state` so it commits with delivery. Coordination:
  WATCH-UNDELIVERED-EVENT-RESEND also edits `last_state` shape — additive key, no overlap in lines expected.
- Sustain latch (Q7): `last_state.pending_momentum` alongside `pending_entry_since`.

### 3.5 Dialog (only if Q0 = a) — as Q0(a). Jest test; `npm run typecheck`.

## 4. Tests, each with the mutation it must kill

1. `momentum_match` per kind × {Bullish, Bearish, None}: cross on the judged bar → True; **opposite-direction
   cross with direction Bullish/Bearish → False** (each kind; volume with the wrong candle colour); no cross;
   `prev == L` edges; Bearish uses `100-L`. Mutations: `<=`→`<`; drop `100-L`; ignore direction.
2. MACD correctness: a spike on the last bar that makes the line cross → True on that bar (not the next);
   flat series → no cross after warm-up. Mutation: reuse `_ema_values`.
3. Window: same last 200 bars with 250 vs 1500 bars of history → same answer where full-history RSI differs;
   1W-sized list (260 bars) works. 199 bars → None. Mutations: drop the slice; return False on warm-up.
4. Volume: slot baseline (a normal open bar ≥ 2× the prior 20 bars but not ≥ 2× its slot → False); zero-volume
   symbol → False (not None); missing volume on the judged bar → False; < 5 slot sessions → False. Mutations:
   previous-20 baseline intraday; `None` for zero volume; drop `baseline > 0`.
5. Input normalisation: `"bullish"` matches; `min_confidence` `"60"`, `True`, `0`, `100` → not matched, no raise.
6. Standard rules unchanged: golden output of `compute_indicators_for_conditions` for every name in its table.
7. Name-collision leak gone: a standard indicator series named `rsi_cross` no longer satisfies a composite.
8. Rule integration (`_fire` harness): cross completed by the closed candle → fires; cross only on the forming
   candle → not; catch-up candle (older `idx`) judged on its own prefix; 4h with sandbox lag (closed candle absent
   from `_regime_candles`) still judged. Mutations: use `_regime_candles`; use `all_candles` uncut.
9. Rule fires once per cross: the next closed candle (no new cross) → not fired. Mutation: lookback 3.
10. Watch: patched cache → fires; spy asserts `evaluate_scheduled` received a non-None `momentum` (kills a
    probe-clearing half fix); fetch raises → None and `last_state` untouched; `momentum_through` persisted; next run
    judges only newer bars; 16 bars since last run with the cross on the 3rd → fires. Mutations: pass None; judge
    last bar only; don't persist `momentum_through`.
11. **Parity:** one candle list; the rule path on closed candle X and the watch whose `momentum_through` is X-1
    and whose fetch returns the list up to X+1 (forming) → same momentum answer, for 1h, 4h, 1D, 1W × both
    directions × each kind; plus an after-close 1D case (last row complete) asserting both judge D-1. Mutation:
    the watch judges `rows[-1]`.
12. Three-valued gate: momentum-only trigger + `compute_structure` raising + momentum False → **False** (not
    None); one unread momentum and count+unread ≥ min → None; < min → False. Mutation: OR instead of the count.
13. Sustain latch (rule and watch): cross at clock start, clock completes with no cross → fires; regime breaks →
    clock and latch cleared. Mutation: don't read the latch.
14. (Q0 = a) Jest: the three rows render with direction labels and save `type: 'momentum'`.

Runs: backend full suite (`backend/.venv/bin/python -m pytest`), `python3 scripts/state.py` exit 0 with the phase
`verify` switched to a presence probe on `momentum_match` (test 10's spy is what proves the watch supplies it),
frontend typecheck + jest if the dialog is touched.

## 5. Ownership and coordination

- **Owned:** `composite_trigger_evaluator.py` (momentum paths), `strategy_watch_evaluator.py`
  (`_eval_composite_watch`), `chart_alerts.py` composite block + composite-only helpers (`_composite_checklist`,
  `_composite_need_suffix`), `indicator_compute.py` (additions only), their tests. Dialog only on Q0 = a.
- **WATCH-RULE-BAR-PARITY** (r6, its §2.9): both own the composite block. This plan reads only `all_candles` (cut
  at the closed candle) and adds a `momentum=` argument; it does not read `_regime_candles` or their model
  series, so no bar-series merge is needed. Per their §2.9: whoever merges second merges main in and resolves;
  no rebase of the other's branch.
- **WATCH-UNDELIVERED-EVENT-RESEND:** additive `last_state` keys only.
- **Do not touch:** rest of `chart_alerts.py`, `dispatch.py`, chart display windows, `_calc_macd` (Q9).

## 6. Round 1 disposition (17 findings, none rejected)
1 → 1.7, Q2, Q9, 3.1, test 2. 2 → Q5 rule cut at the closed candle, test 8. 3 → Q5 watch judges `rows[-2]`,
test 11 after-close case. 4 → Q4 watch judges bars since last run, test 10. 5 → Q3 definite False, test 4.
6 → Q3 slot baseline, test 4. 7 → Q4 rule lookback 1, test 9. 8 → Q7, test 13. 9 → 3.2 single count, test 12.
10 → Q5/§5 (no `_regime_candles`). 11 → Q6 window 200, test 3. 12 → Q5 same cache key + freshness.
13 → Q1/3.1 normalisation, test 5. 14 → 3.2 wording + `momentum_matched`, Q0(a) text. 15 → Q0(a) labels.
16 → test 1 opposite-direction cases. 17 → test 10 spy. Missing re-arm question → Q8.

## 7. Loop
Plan → adversarial rounds until clean → Kenneth's answers → plan revised to the answers (re-audited if the design
changed) → build with the mutation checks above → code rounds until clean → state record → merge only with
Kenneth's approval.
