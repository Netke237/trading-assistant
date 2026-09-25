# A4e — chart-rule structure signals on the closed candle

Branch `claude/wizardly-ritchie-ndb5sg`, restarted off main `16310e0` (Q3B merged).
Backend only. Item (2) of decision A4C-FOLLOWUPS-LOCKED-2026-09-24:

> chart-rule indicator values (compute_indicators_for_conditions(all_candles)) and structure
> signals (compute_structure(candles)) are computed on the list INCLUDING the forming candle
> while the price condition reads candles[-2]; align them to the closed candle. Plan must first
> verify how indicator conditions index their values. The composite mean_reversion_vwap
> confirmation stays on the forming bar.

## 1. Verification the decision asked for (done before planning)

**Indicator conditions index by the closed candle's own timestamp, not by position.**
`alert_evaluator._evaluate_condition` (kind `indicator`) looks up
`idx = first i with series[i]['time'] == candle_time`, where `candle_time` is
`closed_candle['time']`, then reads `series[idx]` (and `series[idx-1]` for `crosses_*`).
Every indicator in `indicator_compute.py` is causal: the point at index i is a function of
bars 0..i only. EMA/SMA/RSI/MACD/ATR/BB are forward recursions or trailing windows, VWAP is
session-anchored cumulative, and `volume`/`close` are the raw bar. The one length-dependent
branch is EMA's `len(values) < period → []`. With the forming bar the series exists but the
closed index is `< period` and holds `None`; without it the series is empty. Both are
"not met", with no trigger value.

Empirical check: 400 random series (40–200 five-minute bars) × 12 indicators × 3 operators.
The full list and the closed prefix return identical `(met, trigger_values)` in every case.

**Conclusion: the indicator half needs no code change.** The forming candle cannot move an
indicator reading or outcome at the closed candle. It is pinned by a test (§3, T1) so that a
future non-causal indicator is caught. The composite path receives the same `indicators`
dict and is equally unaffected.

**Structure signals DO read the forming candle, and change outcomes.** A standard `structure`
condition is met by any matching signal whose `time`/`time_start` is `>= closed_candle.time`.
The composite path (`_matched_confirmations`) is met by ANY matching signal in the list, with
no time filter. `compute_structure` runs on the full list, forming candle included, so the
decision can differ in two ways:
- a BOS/CHoCH/FVG/divergence detected ON the forming bar (time > closed time) satisfies the
  closed candle's rule. The rule fires on a break that has not closed.
- `find_swings` confirms a pivot with right-side bars. The forming bar can confirm a swing
  that makes the closed candle a BOS (look-ahead), or change `trend`, turning BOS into CHoCH.

Empirical check: same 400 series × 5 kinds × 2 directions. 35 outcome flips between the
full list and the closed prefix. A fired alert on a structure break that has not closed
is a wrong alert in front of the user, so this is gate-level.

Filtering the full-list signals by time cannot fix the look-ahead (the swing itself was
confirmed by the forming bar), so the signals must be RECOMPUTED on the closed prefix.

**Out of scope, verified not to change a decision:** `_mtf_align(ht_candles)` (the 1h rule's
daily candles, forming daily bar included) runs after confidence and confluence are set. It
only sets the `mtf_aligned`/`multi_tf` flags, and no alert condition or composite
confirmation reads either. The display `structure` messages the chart WS sends to the
browser stay on the full list: that is the live chart overlay, not an alert decision. The
dry-run `POST /rules/{id}/test` takes client-supplied signals and is unchanged.
`evaluate_scheduled` and `describe_match` compute structure on `bars_daily` from the
historical store. Whether that contains a forming bar is A4g's question, not this one.

## 2. The change

**New helper**, `app/routers/chart_alerts.py`, next to `evaluate_and_notify_for_symbol`:

```python
def closed_candle_structure(candles, closed_candle, interval, symbol, ht_candles=None) -> list[dict]:
    """A4e: structure signals for ALERT evaluation, computed on `candles` up to and
    including `closed_candle` (matched by time, searched from the end) -- never on bars
    after it. ... If closed_candle is not in candles, returns []: fail closed (no
    structure condition can be met) rather than fall back to the forming bar."""
```

`compute_structure` itself is unchanged, and so are its other callers (the display message,
the composite scheduler's daily path, `describe_match`).

**Caller 1: `app/services/chart_alert_scheduler._tick`.** Its `signals` feed only the
evaluation, so the one line
`signals = await asyncio.to_thread(compute_structure, candles, interval, symbol, ht_candles)`
becomes
`signals = await asyncio.to_thread(closed_candle_structure, candles, closed, interval, symbol, ht_candles)`.

**Caller 2: `app/routers/chart.py` WS candle-close branch.** The display `signals`, computed on
the full list and sent as the `structure` message, stay as they are. The call to
`evaluate_and_notify_for_symbol` gets
`alert_signals = await asyncio.to_thread(closed_candle_structure, candles, closed, interval, symbol, ht_candles)`
in place of `signals`. Cost: one extra `compute_structure` per candle close per open chart
(a few hundred bars, off the event loop). The recompute sits inside the existing `try`, so a
failure is logged and skips evaluation, as today.

`evaluate_and_notify_for_symbol`'s signature is unchanged. Its docstring line "Indicators,
structure signals, the closed candle and the VWAP confirmation keep `all_candles`" is
corrected. Structure signals are now the callers' closed-prefix signals. Indicators still
read `all_candles`, and it states why that is equivalent (causal, indexed by time). The
VWAP confirmation keeps the forming bar by decision.

## 3. Tests — `backend/tests/test_a4e_closed_candle_alignment.py`

- **T1 indicator pin.** For every indicator name `compute_indicators_for_conditions`
  supports, on seeded random series: `_evaluate_condition` returns the same `(met,
  trigger_values)` with the full list and with the closed prefix, for `>`, `<`,
  `crosses_above`, `crosses_below`.
- **T2 helper, forming-bar break.** A fixture where the forming bar's close breaks the last
  swing high and the closed bar does not. `compute_structure(full)` has a bullish BOS at
  the forming time; `closed_candle_structure(...)` has none at or after the closed time.
- **T3 helper, look-ahead.** A fixture where the forming bar is the 5th right-side bar
  confirming a swing. The prefix result matches `compute_structure(candles[:k+1])`
  exactly (equality with direct truncation, whatever the fixture).
- **T4 helper edges.** `closed_candle` not in the list → `[]`; a closed candle that is the
  last element → identical to `compute_structure(candles)`; `ht_candles` is passed through.
- **T5 scheduler end to end.** A real `evaluate_and_notify_for_symbol` over an in-memory DB
  (the pattern of `test_chart_alert_scheduler`), with a standard rule
  `structure BOS bullish` and the T2 fixture. `_tick` stores NO history row. With a
  fixture where the closed bar itself breaks, it stores one. The scheduler test's
  `compute_structure` monkeypatch target moves with the call.
- **T6 composite end to end (scheduler).** A composite rule with `model: any`,
  `min_confirmations: 1`, confirmation `BOS bullish`, on the T2 fixture: no fire.
  Closed-bar break: fires.
- **T7 chart WS.** Drive the WS through `TestClient.websocket_connect` (the harness of
  `test_chart_router`), with a stream-client queue that yields one tick with a new
  timestamp. Assert the `structure` message carries the full-list signals and
  `evaluate_and_notify_for_symbol` receives the closed-prefix signals. If the loop can't
  be driven deterministically, fall back to a source pin of the call, as A4c did for the
  fetch time.

Mutations to kill: scheduler reverted to `compute_structure(candles, ...)`; WS passes
`signals` to the evaluator; helper slices `[:i]` (drops the closed bar); helper slices
`[:i+2]`; helper returns full `candles` when the closed candle is missing.

## 4. Process

Plan round 1 (this document), briefed on the gate. Then the build, tests and mutations, the
full backend suite, and a code round on the build diff only. Merge when a round returns zero
gate-level findings. Hard cap 3. Only gate-level findings are fixed in-branch; everything
else is logged against main.
