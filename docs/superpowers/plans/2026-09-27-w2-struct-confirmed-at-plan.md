# W2-STRUCT — OrderBlock / FVG / Divergence rules can fire — plan

Phase: W2-STRUCT. Package: `2026-09-25-work-packages.md` §W2-STRUCT.
Decisions: Q16 (do NOT hide these kinds; fix with a per-kind "confirmed at" time). Q16b answered 2026-09-27: **no "not firing yet" note** — the fix ships in this package, so AlertRuleBuilder is not edited.
Prerequisite: P4a merged (met). Branch `claude/clever-planck-rpz8yh`, from main `480c322`.

Two build parts, one layer each (audit_rule: batch size): A backend, B frontend mirror. Both small (< 250 lines incl. tests).

## 0. Today (main `480c322`)

A structure condition is met when some signal of the right kind/direction/confidence has
`signal_time >= candle_time`, where `signal_time = s.time or s.time_start`
(`backend/app/services/alert_evaluator.py:266-270`; browser mirror `frontend/lib/chartAlertEngine.ts:161-172`).

The live backend path (`chart.py` → `closed_candle_structure`, `chart_alerts.py:858-878`) recomputes structure on the
candles UP TO the closed candle (A4e), so every signal it sees was produced from bars `<= closed`. A signal therefore
fires only if its time field IS the closed bar. That holds for BOS/CHoCH (`time` = the breaking bar) and for no other kind:

| Kind | Time field the evaluator reads | Bar that actually confirms it | Lag |
|---|---|---|---|
| BOS / CHoCH | `time` = breaking bar `i` | `i` | 0 |
| FVG | `time_start` = c0 (`candles[i-2]`) | c2 = `candles[i]` (the gap needs all three bars) | 2 |
| OrderBlock | `time_start` = the candle before the BOS | the BOS bar (`bs["time"]`) | 1 |
| Divergence | `time_start` = first swing `ph0` | `ph1.index + 5` — `find_swings(lookback=5)` needs 5 bars right of the second swing | 5 after `time_end` |

Measured (scratch probe, bar-by-bar recompute over the four `tests/fixtures/*_candles.json`, 251 bars each): the lags
above hold for EVERY first appearance (FVG 313/313 at +2, OrderBlock 19/19 at +1, Divergence 60/60 at +5 after
`time_end`, BOS/CHoCH 65/65 at 0), and the AAPL replay fires BOS 10×, CHoCH 7×, FVG/OrderBlock/Divergence **0×**.
So standard rules on those three kinds can never fire today.

## Part A — backend: signals carry `confirmed_at`; the evaluator reads it

**A1. `backend/app/services/market_structure.py` — add `confirmed_at: str` (a candle `time`) to every signal of the five kinds.** Additive only: no existing field changes, so chart drawing (`time_start`/`time_end`), confluence, MTF alignment, structural stops and composite confirmations are untouched.
- `detect_fvg`: `confirmed_at = candles[i]["time"]` (c2), both directions.
- `detect_bos_choch`: `confirmed_at = c["time"]` (equal to `time`; set so every kind has the field).
- `detect_order_blocks`: `confirmed_at = bs["time"]` (the BOS bar that makes the prior candle an order block).
- `_detect_divergence`: `confirmed_at = candles[ph1["index"] + lookback]["time"]` (resp. `pl1`), with `lookback` the same value passed to `find_swings` (today the literal 5 — hoist it to one local so the two cannot drift). `ph1.index + lookback <= len(candles) - 1` always holds because `find_swings` only emits `i <= len - 1 - lookback`; assert-free, pinned by test A3(c).
- Not changed: mitigation flags, confidence, `compute_confluence`, `_mtf_align`, Fibonacci/Confluence signals (not offered as rule kinds).

**A2. `alert_evaluator._evaluate_condition` structure branch.**
```python
signal_time = s.get('confirmed_at') or s.get('time') or s.get('time_start', '')
if signal_time == candle_time:
```
- `confirmed_at` first; the old fallback stays for a signal list without the field (a stale client posting `/rules/{id}/test`), where it behaves exactly as today for BOS/CHoCH.
- `>=` becomes `==`. On the live path the two are identical (every recomputed signal is `<= closed`). On the dry-run endpoint `POST /alerts/rules/{id}/test` (`chart_alerts.py:~826`), which replays `body.signals` — ONE list computed on the full history — `>=` matches, at candle k, every signal confirmed LATER than k: the dry-run shows a match on nearly every bar before a signal. `==` makes it match only on the confirmation bar, i.e. the bar the live path would fire on. This is the same line, not a widening; it also corrects BOS/CHoCH in the dry-run.
- `_compare`-free string equality: both sides are the same backend candle `time` value (`chart_alerts.closed_candle_structure` takes `closed_candle` from the same `candles`), so no format conversion.

**A3. Tests (`backend/tests/test_w2_struct_confirmed_at.py`, new).**
(a) Per kind, synthetic candles: FVG `confirmed_at` = c2 time; OrderBlock = the BOS bar time; Divergence = time of `ph1.index + 5`; BOS/CHoCH = `time`.
(b) Causality property, on each of the four fixtures: for every FVG/OrderBlock/Divergence/BOS/CHoCH signal in `compute_structure(bars[:j+1])` for j over the replay, the signal with the same identity key first appears at the `j` whose `bars[j].time == confirmed_at`. (Identity key: kind, direction, `time`/`time_start`, and for Divergence `indicator` + `time_end`.)
(c) Divergence `confirmed_at` is always a real candle time in the list (no IndexError at the right edge; last-bar-confirmed case included).
(d) End to end through `closed_candle_structure` + `evaluate_rules`: a standard rule with one structure condition per kind, replayed bar by bar over a fixture, fires on exactly the bars where a matching signal's `confirmed_at` equals the closed candle, and at least once for each of FVG, OrderBlock, Divergence (today: 0).
(e) Direction and `min_confidence` filters still exclude as before; a signal without `confirmed_at` falls back to `time`.
(f) Dry-run endpoint: with a full-history `signals` list, a BOS rule matches only on the BOS bar, not on earlier bars.
Existing `tests/test_a4e_closed_candle_alignment.py` and alert-evaluator tests must pass unchanged; any that asserted `>=`-only behaviour is reported, not silently edited.

## Part B — frontend mirror (browser-side evaluation on the chart)

`ChartWorkspace` evaluates the same rules in the browser on candle close (`index.tsx:~401-420`) against `structureSignals`
from the chart WebSocket — the FULL list (`chart.py:55/81`), which includes signals confirmed by the forming bar.

**B1. `frontend/types/structure.ts`:** `confirmed_at?: string` on `ZoneSignal`, `LineSignal`, `DivergenceSignal` (optional: a cached list from before the deploy lacks it).
**B2. `frontend/lib/chartAlertEngine.ts` structure branch:** same rule as A2 —
`signalTime = s.confirmed_at ?? ('time' in s ? s.time : 'time_start' in s ? s.time_start : '')`, met iff `String(signalTime) === String(candleTime)`.
With the full list, `>=` would fire the closed candle's rule on a signal the forming bar confirmed (the A4e defect, browser side); `===` fires only on a signal confirmed by the closed bar itself.
**B3. Tests (`frontend/lib/__tests__/chartAlertEngine.test.ts`):** per kind, a signal with `confirmed_at` equal to the closed candle fires; one bar later (forming-bar-confirmed) does not; one bar earlier does not; missing `confirmed_at` falls back to `time`. Existing BOS tests updated only if they relied on `>` (reported in the round log).

## What changes for Kenneth

OrderBlock, FVG and Divergence alert rules start firing — once, on the bar that completes the pattern (FVG: the third bar of the gap; OrderBlock: the breakout bar; Divergence: 5 bars after the second swing, the first bar the swing is certain). The rule builder is unchanged. The "test rule" dry-run now shows a match only on the bar a live rule would fire.

## Out of scope (logged, not fixed)

- A BOS (and its OrderBlock) can vanish from a later recompute (seen: AAPL 1+1, NVDA 2+2 over 211 bars) because `_is_duplicate_bos` and the trend state depend on history. Pre-existing; affects composite confirmations and drawing, not whether a standard rule fired.
- The browser path can evaluate before the new `structure` message arrives (stale list → a miss). Best-effort display path; the backend path is the one that notifies.
- A mitigated zone still fires on its confirmation bar only if mitigation happened on that same bar (FVG: impossible, mitigation scan starts after c2; OrderBlock: the BOS bar itself closing through the block — unchanged semantics).

## Owned files

`backend/app/services/market_structure.py`, `backend/app/services/alert_evaluator.py`, `backend/tests/test_w2_struct_confirmed_at.py`; `frontend/types/structure.ts`, `frontend/lib/chartAlertEngine.ts`, its test. AlertRuleBuilder: not edited (Q16b).

## Verification

Backend `pytest -q` (baseline 3671 passed, 1 skipped); frontend `npx tsc --noEmit` clean + `npx jest --silent` (baseline 3903); `python3 scripts/state.py` exit 0.

## Bookkeeping (state file only, same branch)

Retire `AUTOTRADE-DIRECTION-SIZING` in PROJECT_STATE.json as superseded by sub-phases 1, 2A, 2C, 3, 4 (decision AUTOTRADE-SIZING-SPLIT-THREE-WAYS-2026-09-19). No code.

## Round log

(empty)
