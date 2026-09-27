# W2-STRUCT — OrderBlock / FVG / Divergence rules can fire — plan

Phase: W2-STRUCT. Package: `2026-09-25-work-packages.md` §W2-STRUCT.
Decisions: Q16 (do NOT hide these kinds; fix with a per-kind "confirmed at" time). Q16b answered 2026-09-27: **no "not firing yet" note** — the fix ships in this package, so AlertRuleBuilder is not edited.
Prerequisite: P4a merged (met). Branch `claude/clever-planck-rpz8yh`, from main `480c322`.

Two build parts, one layer each (audit_rule: batch size): A backend, B frontend (browser stops judging structure). Both small (< 250 lines incl. tests).

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

## Part B — frontend: the browser stops judging structure conditions (R1-1)

`ChartWorkspace` evaluates the same rules in the browser on candle close (`index.tsx:399-440`) against `structureSignals`
from the chart WebSocket. That list is ALWAYS computed on a bar that was still forming:
- the first "closed" candle after load is `candles[prevCount-1]`, the last bar of the `history` message, which was the forming bar when `chart.py:49-55` computed the structure it sent;
- after that, `chart.py` sends the `tick` BEFORE it recomputes and re-sends `structure`, so the browser judges the closed bar against the list computed while that bar was forming.
So a browser-side structure match reads partial-bar data (a gap or break that may undo before the close; FVG confidence from an ATR that includes the partial bar). The fire is not display-only: `addHistory` posts it to the server history and `stampRuleTriggered(..., {persist: true})` PATCHes `last_triggered_at`, which starts the SERVER's cooldown (`alert_evaluator.is_cooldown_passed`) and can suppress the correct backend fire. Today this already happens for BOS/CHoCH; `confirmed_at` alone would widen it to three more kinds.

On INTRADAY charts the backend already evaluates every server-stored rule causally (A4e) and pushes the result to the open chart as `alert_triggered` (`chart.py:100-105` → `ChartWorkspace/index.tsx:375`); the WS evaluates under the chart's interval spelling, which is the stored one (`chart_interval`, `chart_alerts.py:597`). **Not on 1D/1W (R2-2):** the chart WS connects as `'daily'`/`'weekly'` (`ChartWorkspace/index.tsx:226-229`) while rules are stored `'1D'`/`'1W'`, so the WS evaluation never matches a daily/weekly rule; only `chart_alert_scheduler` evaluates them (email/Telegram, server history, no chart push).

**B1. `frontend/lib/chartAlertEngine.ts` `evaluateRules` — rule level, intraday only (R2-1, R2-2):** skip (`continue`, before any condition is evaluated, no history, no stamp, no `condition_state` change) every rule whose `interval` is NOT `'1D'`/`'1W'` and whose `group.conditions` contains any `kind === 'structure'` condition. A condition-level "not met" is NOT used: for an OR / N_OF_M rule it would still fire the browser on the other conditions with a false ✗ on the structure line in the persisted checklist/notification, and its `stampRuleTriggered(..., {persist:true})` PATCH would start the server cooldown and block the backend's correct fire for the same bar. With the rule skipped, the backend owns the whole rule on intraday — decision, checklist, history, cooldown stamp, push.
- 1D/1W: browser evaluation is UNCHANGED from today (Part B does not touch it). The browser never reads `confirmed_at` (no type change), so it keeps today's `time ?? time_start >= candleTime` rule: FVG/OrderBlock/Divergence still never fire browser-side there, BOS/CHoCH behave as today. The new kinds fire on 1D/1W from the scheduler only.
- Price / indicator / regime-only rules: unchanged everywhere. `conditionLabel` unchanged.
**B2. Tests (`frontend/lib/__tests__/chartAlertEngine.test.ts`):** on an intraday interval, a rule with a structure condition (alone, AND, OR with a met price condition, N_OF_M) produces no history and does not change `condition_state`, per kind; a price-only rule still fires; on `'1D'` a BOS rule behaves exactly as today (existing tests `:129`, `:143` kept on `'1D'` or moved there; any rewrite reported in the round log).

## What changes for Kenneth

OrderBlock, FVG and Divergence alert rules start firing from the backend — once, on the bar that completes the pattern (FVG: the third bar of the gap; OrderBlock: the breakout bar; Divergence: 5 bars after the second swing, the first bar the swing is certain). On intraday charts the fire also appears on the open chart (pushed by the backend); on 1D/1W it arrives by email/Telegram only (pre-existing gap, logged). On intraday charts, any rule containing a structure condition is now decided by the backend only, so it no longer fires early on a bar that has not closed. The rule builder is unchanged. The "test rule" dry-run now shows a match only on the bar a live rule would fire.

## Out of scope (logged, not fixed)

- A BOS (and its OrderBlock) can vanish from a later recompute (seen: AAPL 1+1, NVDA 2+2 over 211 bars) because `_is_duplicate_bos` and the trend state depend on history. Pre-existing; affects composite confirmations and drawing, not whether a standard rule fired.
- A mitigated zone still fires on its confirmation bar only if mitigation happened on that same bar (FVG: impossible, mitigation scan starts after c2; OrderBlock: the BOS bar itself closing through the block — unchanged semantics).

- (R2-2) The chart WS evaluates 1D/1W rules under `'daily'`/`'weekly'`, never matching the stored `'1D'`/`'1W'`, so no daily/weekly fire is pushed to the chart, and the frontend never loads server alert history (`api.getAlertHistory` has no caller). Mapping the interval in `chart.py` is NOT a drop-in fix: the daily WS path re-evaluates on every intraday tick timestamp and duplicates the scheduler. Needs its own package.
- 1D/1W browser evaluation keeps today's forming-bar exposure for BOS/CHoCH (pre-existing, unchanged by this package).

## Owned files

`backend/app/services/market_structure.py`, `backend/app/services/alert_evaluator.py`, `backend/tests/test_w2_struct_confirmed_at.py`; `frontend/lib/chartAlertEngine.ts`, its test. AlertRuleBuilder: not edited (Q16b).

## Verification

Backend `pytest -q` (baseline 3671 passed, 1 skipped); frontend `npx tsc --noEmit` clean + `npx jest --silent` (baseline 3903); `python3 scripts/state.py` exit 0.

## Bookkeeping (state file only, same branch)

Retire `AUTOTRADE-DIRECTION-SIZING` in PROJECT_STATE.json as superseded by sub-phases 1, 2A, 2C, 3, 4 (decision AUTOTRADE-SIZING-SPLIT-THREE-WAYS-2026-09-19). No code.

## Round log

- **Plan round 1 (2026-09-27): 1 gate-level finding, fixed.** R1-1: Part B's browser `===` still judged the closed bar against a structure list computed while that bar was forming (first tick after `history`; `tick` sent before the `structure` recompute), and a browser fire persists history and the server cooldown stamp. Fix: Part B rewritten — the browser treats structure conditions as not met; the backend (causal, A4e) owns them and already pushes `alert_triggered`. Part A confirmed correct and causal by the reviewer on all four fixtures; `==` confirmed equivalent to `>=` on both live backend paths (chart WS and scheduler/catch-up via `closed_candle_structure`).
- **Plan round 2 (2026-09-27): 2 gate-level findings, fixed.** R2-1: a condition-level browser "not met" still let OR/N_OF_M rules fire browser-side with a false ✗ checklist line, and the persisted cooldown stamp blocked the backend's correct fire. Fix: rule-level skip. R2-2: the chart WS never evaluates 1D/1W rules (`'daily'` vs stored `'1D'`), so the claimed push does not exist there. Fix: Part B limited to intraday; 1D/1W browser unchanged; gap logged (a `chart.py` mapping was rejected — re-evaluates on every tick and duplicates the scheduler). Reviewer confirmed: no other caller of the browser engine; offline-created rules are re-synced; interval spellings match on intraday.
- **Plan round 3 (2026-09-27): ZERO gate-level findings — plan stage CLEAN.** Reviewed the r2 diff only. Confirmed: `evaluateRules` receives the UI `Interval` ('1D'/'1W' exact), rules use the same type; `evaluateRules` is pure (history write and stamp are in the caller, only for returned entries), so the skip leaves no state wrong; the WS loop evaluates every intraday interval the chart offers on the same trigger the browser used, so no intraday structure rule loses coverage.
- **Round 4 = code round 1, Part A (3c24913): ZERO gate-level findings — CLEAN.** All 10 emission sites set `confirmed_at`; the Divergence index cannot overflow (`find_swings` emits `i <= len-1-lookback` on the same list); `==` equals `>=` on both live paths; no consumer validates or dedups signal dicts.
- **Round 5 = code round 1, Part B (c98258d): ZERO gate-level findings — CLEAN.** Skip is rule level, after the existing guards and before any condition; `evaluateRules` is pure so a skipped rule writes/stamps nothing; a null condition entry threw in the old `.map` too (no new crash path); every intraday interval has WS evaluation.
