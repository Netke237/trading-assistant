# COMPOSITE-MOMENTUM-CONFIRMATIONS-BUILD — plan (r0, decisions pending)

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
   - Rule: fires per closed candle of the rule's interval. `_regime_candles` = the chart-cache candles
     (`get_intraday_with_fetched_at`), completed at the fetch time `as_of` (`completed_bars_for_interval` +
     `completed_session_bars`), capped at `MAX_LIVE_MODEL_CANDLES = 1500`.
   - Watch: runs on the watch scheduler (EOD, or every N hours in market hours — not per candle). Reads completed
     `get_bars` daily rows always; fetches `fetch_intraday_candles(interval, days=intraday_history_days)` only
     for `HMM_intraday` or intraday VWAP. It **never reads 1W bars** — no weekly series exists on that path.
6. **Structure confirmations already differ by path** (rule: closed-candle structure on the rule's interval;
   watch: `compute_structure(bars_daily, "1D")`). Out of scope here (not a momentum path); noted so the parity
   test is scoped to momentum only.

## 2. Questions for Kenneth (answer before any code)

Each has a recommendation; "yes to all recommendations" is a complete answer.

**Q0 — Reach.** Momentum confirmations are API-only today.
- (a) **Recommended:** make them match on both paths (this plan) **and** add three checkboxes to
  `CompositeAlertDialog` (Volume spike / RSI cross / MACD cross, `type: 'momentum'`). The dialog is W2-INTERVAL's
  file; the work package says "ask" — this is the ask. Without it the feature stays invisible to you.
- (b) Backend only (API/YAML users only).
- (c) Remove them instead: the schema rejects `type: "momentum"` on create, and existing stored ones are refused
  at evaluation with a log line (none exist in shipped config). Cheapest, honest, no new trading signal.

**Q1 — `rsi_cross`.** Recommended: **RSI(14) crossed a level on the evaluated bar**, level from `min_confidence`:
- Bullish: `prev <= L < cur` with `L = min_confidence` (default 60 → "RSI crossed up into 60+").
- Bearish: `prev >= L' > cur` with `L' = 100 - min_confidence` (60 → "RSI crossed down into 40-"), so one number
  means the same momentum strength both ways.
- `direction: null`: either of the two.
Same strict/non-strict edges as the standard rule's `crosses_above`/`crosses_below` (`alert_evaluator.py:239-254`).
Rejected alternatives: "RSI value >= 60" (a level, not a cross — fires every bar in a trend); a fixed 50 centre
line (ignores the stored field).

**Q2 — `macd_cross`.** Recommended: **MACD(12,26,9) line crossed its signal line on the evaluated bar** — Bullish
up (`prev_macd <= prev_sig and macd > sig`), Bearish down (mirror), `null` either. `min_confidence` is **not
used** for this kind (documented in the schema comment and the alert text). Alternative: also require the MACD line
on the matching side of zero.

**Q3 — `volume_spike`.** Recommended: **evaluated bar's volume >= 2.0 × the mean volume of the 20 completed bars
before it**, and the bar's body agrees with `direction` (Bullish `close > open`, Bearish `close < open`, `null`
any). `min_confidence` not used; the 2.0× / 20-bar constants are module constants, not config. Alternative: ratio
from `min_confidence` (e.g. `min_confidence / 30` → 60 = 2.0×) — rejected as unreadable.

**Q4 — Which bar is "the evaluated bar".** Recommended: **the cross/spike must occur within the last 3 completed
bars** (`_MR_STRATEGY_LOOKBACK = 3`, the strategy-confirmation convention), on both paths. Reason: the watch runs
EOD or every N hours, so on an intraday watch "the last completed bar only" would miss almost every cross (a 15min
watch checked hourly sees 1 of 4 bars). Cost: a rule can re-fire on the next 2 closes — handled by the rule's
existing `cooldown_minutes` / sustain and the watch's once-per-entry `armed` phase. Alternative: last closed bar
only (exactly the standard-rule semantics; the watch then rarely matches intraday).

**Q5 — Which bars, per interval.** Recommended: **the rule's/watch's own interval, from the chart cache, on both
paths** — the watch calls the same `chart_cache.get_intraday_with_fetched_at(symbol, interval)` the rule's
scheduler reads and applies the same completeness trim at the returned fetch time. So an RSI cross on a 1W
composite means weekly RSI, as on the chart. This is deliberately **not** the `get_bars` daily rows used for
rsi/bb/HMM_daily (those are "daily" by definition; momentum is "the chart you set the alert on").
Alternative: 1D/1W read completed `get_bars` rows (1W resampled to weeks) as D7 did for VWAP — more code, and
~104 weekly bars from 730 days.

**Q6 — Too few bars.** Recommended: fewer than the kind's warm-up (RSI 15 closes + lookback, MACD 35 + lookback,
volume 21 + lookback) = **no reading**: the watch returns `None` (state unchanged, as a failed feed) under
`unknown_as_none`, the rule treats the confirmation as not matched (fail closed). Same split as today's
`structure_unread`.

## 3. Design (assuming the recommendations; adjusted to the answers before building)

### 3.1 One pure function, both paths — `indicator_compute.py`
```python
MOMENTUM_WINDOW = 300      # bars fed to RSI/MACD; fixed so the answer does not depend on fetch length
MOMENTUM_LOOKBACK = 3
def momentum_match(bars: list[dict], kind: str, direction: str | None, min_confidence: int) -> bool | None
```
- `bars`: completed bars of the interval, oldest→newest, the last one being the evaluated bar. Only the last
  `MOMENTUM_WINDOW` are used (RSI's Wilder smoothing and the EMAs depend on the start point; a fixed trailing window
  makes the rule's 1500-candle list and the watch's list give the same value when their last 300 bars agree —
  the parity property). Returns True/False, or None if too few bars (Q6) or an unknown `kind`.
- Reuses the existing private `_calc_rsi` and `_calc_macd`; adds nothing to `compute_indicators_for_conditions`
  (standard-rule behaviour byte-for-byte unchanged — pinned by the existing indicator tests).
- Non-finite / missing OHLCV on a bar the kind reads → None (never an exception).

### 3.2 Evaluator — `composite_trigger_evaluator.py`
- `_matched_confirmations(td, structure_signals, indicator_values, momentum_bars=None)`: the momentum branch calls
  `momentum_match(momentum_bars, kind, direction, min_conf)`; `indicator_values` is **no longer read for
  momentum** (removes the name-collision leak in 1.2). `momentum_bars is None` → not matched.
- New `_momentum_unread(td, momentum_bars) -> bool`: some momentum confirmation returned None.
- `evaluate_from_context(..., momentum_bars=None)` and `evaluate_from_context_detailed(...)`,
  `evaluate_scheduled(..., momentum_bars=None)`, `describe_match(..., momentum_bars=None)` thread it through.
- `evaluate_scheduled`: the confirmation shortfall is "no reading" when `structure_unread` **or** the shortfall
  could be covered by unread momentum confirmations (same counting rule as the strategy `starved` count:
  `count + unread_momentum < min` → definitely False).
- `indicator_values_at` stays (used by nothing else after this change → deleted if grep confirms; the T6 tests that
  pin it are rewritten to pin the new source instead).
- `format_composite_reason`: "structures matched" → "confirmations matched" (the list now mixes kinds).

### 3.3 Rule path — `chart_alerts.py` composite block only
- `_momentum_bars = [c for c in _regime_candles if <time> <= closed_candle time]` — the completed candles up to and
  including the closed candle (A4e). If the closed candle is not in `_regime_candles` → `None` (fail closed).
  Computed only when some composite rule has a momentum confirmation.
- Passed as `momentum_bars=` to `evaluate_from_context_detailed`. `_composite_indicators` argument kept (structure
  signature) but no longer consulted for momentum.
- `_composite_checklist` already labels rows by `signal_kind`; add readable labels for the three kinds.

### 3.4 Watch path — `strategy_watch_evaluator._eval_composite_watch`
- When the trigger has a momentum confirmation: `rows, fetched_at = await chart_cache.get_intraday_with_fetched_at(
  symbol, fetch_iv)`, trimmed with the same two calls the rule uses (`completed_bars_for_interval(rows, iv,
  now=fetched_at)` then `completed_session_bars(..., now=datetime.fromtimestamp(fetched_at, MARKET_TZ))`). A shared
  helper `completed_chart_bars(rows, interval, fetched_at)` goes in `composite_trigger_evaluator.py` and the watch
  uses it; the rule block keeps its existing `_regime_candles` expression (outside this package's ownership) and a
  test pins that both produce the same list for the same input.
- Fetch failure → `momentum_bars=None` → no reading → watch state unchanged.
- Passed to `evaluate_scheduled(..., momentum_bars=...)` and `describe_match(..., momentum_bars=...)`.

### 3.5 Dialog (only if Q0 = a)
Three rows appended to `CONFIRMATION_OPTIONS` with `type: 'momentum'`; the save body already sends `type`,
`direction`, `min_confidence: 60`. Labels: "Volume spike (2× avg)", "RSI cross (60 / 40)", "MACD signal cross".
Jest test: the three appear and save with `type: 'momentum'`. `npm run typecheck` clean.

## 4. Tests (backend unless noted), each with the mutation it must kill

1. `momentum_match` truth tables per kind × direction {Bullish, Bearish, None}: cross on bar −1, −3 (matches),
   −4 (does not); no cross; exact-level edges (`prev == L`). Mutations: flip `<=`/`<`; drop the Bearish
   `100 - L`; lookback 3 → 4; ignore direction.
2. Warm-up: one bar short → None; enough → bool. Mutation: return False instead of None.
3. Window independence: same last 300 bars with 400 vs 1500 bars of prior history → same answer on a
   constructed case where the full-history RSI would differ. Mutation: drop the window slice.
4. Standard rules unchanged: `compute_indicators_for_conditions` output identical before/after for every name in
   its table (golden fixture). Mutation: route `rsi` through the new code.
5. Name-collision leak gone: a standard rule's indicator named `rsi_cross` no longer satisfies a composite.
   (Replaces the T6 test that built that case.)
6. Rule path, integration (the existing `_fire` harness): a closed candle that completes an RSI cross → fires;
   the cross only on the forming candle → does not. Mutation: use `all_candles` instead of the completed prefix.
7. Watch path: `_eval_composite_watch` with a patched chart cache → fires; fetch raises → returns None and
   `last_state` untouched; too few bars → None. Mutation: pass `{}`/None again (defect marker back).
8. **Parity:** the same candle list fed to the rule path and to the watch path (both through their real trimming
   code) gives the same fired/not-fired for each kind, for 1h, 1D and 1W, both directions. Mutation: have the
   watch skip the completeness trim.
9. Three-valued watch gate: min_confirmations 2, one structure match + one unread momentum → None; one unread and
   count+unread < min → False. Mutation: treat unread as False.
10. (Q0 = a) Jest: dialog renders and saves the momentum rows.

Runs: `backend/.venv/bin/python -m pytest` full suite; `python3 scripts/state.py` exit 0 (the defect-marker probe
must now be absent, and the phase's `verify` block is updated to a presence probe on `momentum_match`);
frontend `npm run typecheck` + jest if the dialog is touched.

## 5. Ownership and coordination

- **Owned (work package):** `composite_trigger_evaluator.py` (momentum paths), `strategy_watch_evaluator.py`
  (`_eval_composite_watch` inputs), `chart_alerts.py` composite block only, `indicator_compute.py` (add only), their
  tests. `CompositeAlertDialog` only on Q0 = a (this plan is the ask).
- **Overlap risk:** `WATCH-RULE-BAR-PARITY` (claimed, `claude/blissful-maxwell-c8g4nk`) edits the same
  chart_alerts composite block, `composite_trigger_evaluator.py` and the watch fetches. No shared lines by design
  (it changes HMM windows, `get_bars` trimming time, 1W daily reads; this adds a new `momentum_bars` input). Whoever
  merges second merges main in and re-runs the parity tests; this branch will not edit their lines.
- **Do not touch:** the rest of `chart_alerts.py`, `dispatch.py`, chart display windows.

## 6. Loop
Plan → adversarial round (fresh subagent, bmad-review-adversarial-general) until clean → Kenneth's answers →
plan revised to the answers (re-audited if the design changed) → build with the mutation checks above → code
adversarial round until clean → state record → merge only with Kenneth's approval.
