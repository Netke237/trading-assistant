# Strategy-Aware Stock Exit Targets & Stops — Implementation Plan

> **For agentic workers:** implement this plan task-by-task, in order. Steps use checkbox (`- [ ]`) syntax for tracking. Every task ends with a test run and a commit.

**Goal:** Make stock-mode exit levels (a) survive the portfolio boundary instead of being discarded, (b) actually reflect each strategy's own exit thesis instead of one generic R/ATR multiple shared by six of seven strategies, and (c) carry the same probability / expected-days / structural-stop veneer the Options Trade Card already shows. Concretely: `TP_HIT` / `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` — three fully-built, stock-native, already-notified alert types — become able to fire for stock positions for the first time; the Step-4 strategy picker's exit prose ("measured move", "return to mid-band", "prior high") stops being an unimplemented spec; and T2/T3 stop being a client-side 2R/3R invention invisible to the backtester.

**Architecture:** Three layers, shipped in dependency order.

- **A — plumbing (Tasks 1–2).** `frontend/lib/paperTrade.ts`'s `buildPaperStockPosition()` gains an optional `levels` argument and a sanitizer (`stockPositionLevels()`) that turns an entry / stop / target-ladder triple into a `{ stop: number | null; targets: TargetLevel[] }` pair, dropping anything non-positive or on the wrong side of entry and sorting targets nearest-first. All four call sites pass real levels. No backend change, no domain-type change.
- **D — declarative per-strategy exit policies (Tasks 3–12).** One new shared helper in `backend/app/services/strategy_engine.py`, `_build_target_ladder()`, plus one new `exit:` block per strategy in `backend/config/strategy_params.yaml` read through a new `strategy_param_store.get_exit()`. Each signal function derives its ladder from inputs it *already computes* and currently throws away, passing its thesis level as the helper's **`primary`** and its outward continuations as **`extensions`**, sets `target_price = ladder[0]`, and carries the full ladder on a new `StrategySignal.targets` field. `mean_reversion_multi`'s "inherits `fired[0]`" resolution is replaced by an order-independent `resolve_multi_signal()`.
- **B — probability veneer (Tasks 13–15).** `estimate_stock_first_passage()` alongside `estimate_first_passage()` in `backend/app/scoring/first_passage.py`, keeping the ATR→σ, trend-score→drift and GBM+barrier machinery and dropping the three option-pricing stages. One new endpoint. `StockPositionCard` gains an "Estimate" affordance and a "Check structure" affordance (the latter reusing the *existing* `/api/contracts/structural-stop`, which is already instrument-agnostic).

**Tech Stack:** FastAPI + Pydantic v2, PyYAML config, NumPy/SciPy (already a dependency of `first_passage.py`), pytest; Next.js 15 / React client components, TypeScript strict, Zustand, Jest + Testing Library.

---

## Background (read this before touching code)

### Scope: what this plan builds, and what it deliberately does not

This plan implements **Approach A**, **Approach D**, and **Approach B** from
`docs/superpowers/plans/2026-08-21-stock-exit-targets-ideas.md` §Part 3, in the layering Part 4
recommends and Kenneth agreed to. Three things from that brainstorm are **explicitly out of scope**
and must not be mistaken for oversights:

- **Approach C (empirical MFE/MAE percentile calibration) — not built here.** `signal_confidence.py`'s
  `_measure_excursion()` really does compute and discard per-fire favourable/adverse excursion
  distributions, and those distributions are the right way to *choose* D's multiples. But C belongs
  offline, feeding the existing WFO tuner as a calibration input, not as a per-candidate runtime
  dependency (`min_samples` is 20 and `compute_confidence` already returns `None` often enough that
  the UI has a dedicated "not enough history" string). D's config-driven multiples are exactly the
  surface C would later tune, so D is a prerequisite for C, not a competitor.
- **Approach E (trailing stops via the strategy-watch state machine) — deferred.** Four strategies'
  UI copy promises a trailing stop and nothing in the backend implements one; a trailing stop needs
  per-bar state that the current stateless `signal_fn(bars) → levels` shape does not have. Task 3
  deliberately puts the ladder logic in a *shared module-level function* (`_build_target_ladder`) and
  Task 9 puts the multi-signal resolution in a shared `resolve_multi_signal`, precisely so that when
  E is built the watch evaluator, the backtester, the position card and the portfolio all read one
  definition of "where is my stop" instead of forking it. Task 5 emits `ma_crossover`'s cross-back
  level as a *detail field* for display only, for the same reason.
- **Pre-Breakout mode — out of scope entirely.** `breakout_setup_signal` returns `SetupSignal`
  (`strategy_engine.py:231-237`), which has `strategy`/`direction`/`symbol`/`confidence`/`metrics`
  and **no** entry, stop or target. Nothing in this plan reaches it, and no `SetupSignal` field is
  added.

Persisting a first-passage estimate across navigation is also out of scope: that is the parallel
`2026-08-21-trade-card-profit-target-cache.md` work on the Options path, in
`components/organisms/TradeCard/` and `step-7-trade-card/`. **Do not touch those two directories.**

### Kenneth's two "decide early" questions, resolved

**1. Which stop is *the* stop?** After this plan a stock position can name three levels: the
strategy stop, a structural (order-block/swing) stop, and an implied risk-sizing stop.

> **Decision: `PortfolioPosition.stop` is the strategy stop (as edited by the user). It is the risk
> basis and the invalidation of record. `PortfolioPosition.structuralStop` is an optional
> chart-level *reference*, set only when the user explicitly ran "Check structure".**

Justification: this is the convention the options path already uses and the one the alert engine
already encodes. `alert_generator.py:126-157` fires `STOP_REACHED` against `pos.stop` and
`alert_generator.py:159-193` fires `STRUCTURAL_STOP_BREACHED` against `pos.structural_stop` — two
distinct alert types with distinct severities, both already stock-native (both compare the live
*stock* price). Mapping the strategy stop onto `stop` and the structural level onto `structuralStop`
therefore needs **zero** new domain fields, zero new alert types, and zero change to
`frontend/types/domain.ts`. There is no third "risk-sizing stop" to store: `_position_size()`
(`stock_scan.py:851-854`) derives share count *from* `signal.entry_price`/`signal.stop_price` — it
consumes the strategy stop, it does not produce a competing one.

**2. Pristine or edited?** Persist which — the strategy's computed levels or the user's overlay?

> **Decision: persist the user's edited overlay into the live fields (`stop`, `targets[]`), and the
> pristine strategy signal into `tradeCardSnapshot`. Both are stored; they have different jobs.**

Justification: the live fields are what the alert engine fires on, and what the user intends to
trade is their overlay — firing `STOP_REACHED` at a level the user deliberately moved off would be
wrong. The pristine signal is the analytics/audit copy, and it is **already** being stored:
`stockCardSnapshotOf()` (`paperTrade.ts:6-17`) puts `c.strategy` — the untouched `StrategySignalData`
— into `tradeCardSnapshot`, which the backend permanently attaches via `log_approval`. Storing both
is therefore genuinely almost free; Task 2 adds the one missing half (an `edited` block recording
what the user actually chose, so the audit record is a *diff*, not just a baseline). Task 2 also
applies this consistently at **every** site that mints a stock `PortfolioPosition`, not just the
one the brainstorm found — see the call-site table below.

### The facts this plan rests on, verified against the live code

The brainstorm's line numbers were a lead, not ground truth. Every claim below was re-derived from
the working tree; **corrections to the brainstorm are called out in bold.**

| Claim | Verified location | Status |
|---|---|---|
| `buildPaperStockPosition` hardcodes `stop: 0, targets: []` | `frontend/lib/paperTrade.ts:35-36` | ✅ exactly as stated |
| `floorStop()` treats non-positive as unset | `frontend/lib/portfolioStore.ts:136-138` | ✅ — and it is applied at **eight** documented sites (`portfolioStore.ts:115-135`), including `addPosition`'s optimistic `set()`, so a `stop: 0` is silently converted to `null` at every entry point |
| `TP_HIT` / `STOP_REACHED` / `STRUCTURAL_STOP_BREACHED` compare the live *stock* price | `alert_generator.py:90-193` | ✅ all three; only `PREMIUM_STOP` (line 195+) is options-only |
| `TP_HIT` fires against `targets[0]` only | `alert_generator.py:93-97` (`first_target = targets[0]`, reads `stock_price` *or* `stockPrice`) | ✅ — **this makes target ordering load-bearing**: a ladder that is not nearest-first would alert on the wrong rung |
| `StrategySignal` carries entry/stop/target for every strategy | `strategy_engine.py:208-228` | ✅ |
| Stops are already strategy-specific | `strategy_engine.py:300, 317` (MA∓ATR), `381, 390` (base∓ATR), `439, 446` (slow-MA∓ATR), `500, 509` (swing∓ATR), `575, 589` (band∓ATR), `649, 661` / `714, 726` (entry∓ATR) | ✅ — **keep all of these unchanged** |
| Six of seven targets are a generic multiple | `strategy_engine.py:304, 321, 385, 394, 443, 449, 504, 513, 579, 593, 653, 665, 718, 728` | ✅ |
| Step-4 picker already promises strategy-specific exits | `frontend/app/(frame)/screener/step-4-stocks/page.tsx:40-58` | ✅ — **the brainstorm said lines 41-57; the two `const` arrays span 40-58** |
| `breakout_base` already computes the base height | `strategy_engine.py:363-364` (`base_high`, `base_low`) | ✅ exactly as stated |
| `mean_reversion_bb` already computes mid and both bands | `strategy_engine.py:553` (`upper, mid, lower = _bollinger(...)`) | ✅ exactly as stated |
| `mean_reversion_vwap` already computes VWAP | `strategy_engine.py:635` (`vwap = _vwap(bars)`); daily variant at `699` | ✅ |
| `first_passage.py`'s invalidation branch is a pure stock-price barrier test | `first_passage.py:241` (`stock_paths <= invalidation_price if is_call else stock_paths >= …`) | ✅ exactly as stated, exactly at line 241 |
| `structural_stop.py` is instrument-agnostic | `find_structural_stop(candles, direction, reference_price)` — `structural_stop.py:27-31`; no strike/premium/DTE anywhere in the file | ✅ — the *endpoint* is namespaced `/api/contracts/…`, the function is not |
| `scoring_rules.yaml` has `confidence_backtest.<horizon>.n_days` | `backend/config/scoring_rules.yaml:20-40`; read by `signal_confidence.load_backtest_cfg()` (`signal_confidence.py:29-30`) | ✅ — keys are **lowercase** (`swing`/`position`/`intraday`), values 10 / 40 / 5 |
| `PortfolioPosition.structuralStop` already has a working alert | `frontend/types/domain.ts:206-210` + `alert_generator.py:159-193` + `portfolio.py:403-404` (PATCH) | ✅ |
| `mean_reversion_multi` "inherits `fired[0]`" | `backend/app/routers/stock_scan.py:765-769` | ⚠️ **the bug is real but the brainstorm's wording is wrong.** It is not *non-deterministic*: `fired` is built by iterating `req.mean_reversion_variants` (line 747), so the same request always yields the same answer. It is **order-dependent and arbitrary** — the levels come from whichever variant the caller happened to list first, and reordering the checkbox list in the UI silently changes every stop and target. `detail["fired"]` (line 768) inherits the same request-order dependence. Still worth fixing; fixed in Task 9 for the right reason. |
| `StockScanRequest`'s backtest gate defaults | `backend/app/schemas/stock_scan.py:37-38` (`bt_min_trades: int = 5`, `bt_min_win_rate: float = 0.45`) | ✅ — note `strategy_backtest._MIN_TRADES` is **10**, but the live scan always passes the request value (5), so 5 is the number that actually gates candidates |
| `adopt()` replaces the whole `active[direction]` dict | `strategy_param_store.py:118-120` (`active[direction.lower()] = copy.deepcopy(params)`) | ⚠️ **a key this plan relies on.** A parameter removed from `search:` is therefore **deleted from `active:`** by the next tuner adopt (the winning combo contains only grid keys), silently reverting to the Python default. This is why every rung-2/3 parameter also goes into the `exit:` block — see Task 12. |
| `adopt()` rewrites the YAML via `yaml.safe_dump` | `strategy_param_store.py:121-123` | ⚠️ **all comments in `strategy_params.yaml` are destroyed on the first adopt.** Data (including `exit:` blocks) survives; prose does not. Task 12 Step 2's re-tune note is therefore best-effort documentation, not a durable record — the durable copies are this plan and `get_exit()`'s docstring. |
| `rr_target_mult` is in the WFO `search:` grid | `strategy_params.yaml:50` (pullback_ema), `:69` (breakout_base), `:124` (mean_reversion_bb) | ⚠️ **three strategies, not four.** The brainstorm said "four" while citing three line numbers. `ma_crossover` and `mean_reversion_rsi` have no `rr_target_mult` at all (they use hardcoded `atr × 3.0` / `atr × 2.5`); `mean_reversion_vwap` has an `rr_target_mult` in `active:` but **no `search:` block at all** (`strategy_params.yaml:140`, excluded from WFO as intraday-only). |
| `StockPositionCard` invents T2/T3 client-side | `frontend/components/organisms/StockPositionCard/index.tsx:43-56` (`defaultOverlay`) | ✅ — `t1 = card.strategy.target_price`, then `t2 = entry + sign·2·risk`, `t3 = entry + sign·3·risk`, where `risk = |entry − stop|`. Not persisted, not backtested, not backend-derived. |
| The backtest already consumes `target_price` | `strategy_backtest.py:113-121` (`self.buy(limit=…, sl=…, tp=…)`) | ✅ — so **any change to `target_price` immediately changes every historical win rate**; see the coupling section below |

Three further facts the brainstorm did not surface, all of which materially shape this plan:

- **`_entry_side()` is a hard gate on target validity.** `strategy_backtest.py:15-22` returns `None`
  unless `sl < entry < tp` (bullish) or `tp < entry < sl` (bearish) — a target that lands *at* or on
  the wrong side of entry does not produce a worse trade, it produces **no trade at all**, silently
  zeroing that strategy's backtest. Every thesis formula below can, on some real bar sequence, land
  on the wrong side of entry (a gapping breakout can open above `base_high + H`; a Bollinger squeeze
  can put `mid` within pennies of entry). This is why Task 3's `_build_target_ladder()` exists and
  why it *drops* bad rungs rather than clamping them into place.
- **Sorting a mixed thesis list nearest-first would silently demote the thesis rung.** This is the single
  most important design constraint in Approach D, and the reason `_build_target_ladder()` takes a
  `primary` separately from `extensions` rather than one flat `thesis` list. If every candidate rung
  were pooled and sorted by distance from entry, the generic R/ATR extension would become `ladder[0]`
  — and therefore `target_price`, and therefore the only thing the backtest measures — whenever it
  happens to be nearer than the strategy's own objective. That is not hypothetical: for
  `mean_reversion_vwap` the entry gate requires price to be at least `vwap_dev_pct` (1.5%) away from
  VWAP while `risk = stop_atr_mult × atr` (0.5 ATR on 15-minute bars), so `entry + 2R = entry + 1 ATR`
  is almost always nearer than VWAP. The same inversion is reachable for `pullback_ema` (2R vs the
  prior swing high), `mean_reversion_bb` (2R vs the mid-band), `mean_reversion_rsi` (2.5 ATR vs the
  20-SMA) and `mean_reversion_vwap_daily` (2R vs the mirror deviation). **The primary, when it is
  valid, is always rung 1; extensions are kept only if they are strictly beyond the rung before them.**
- **An R-relative "minimum distance" floor must not be applied to a strategy's own primary rung.**
  `ma_crossover`'s stop is anchored at the slow MA, which right after a fast cross can sit far below
  price — a 0.5R floor there is 47 points while its 3-ATR objective is 24, so a floor applied to the
  primary would drop the one rung this plan promises is numerically unchanged and promote a 6-ATR
  extension in its place. The only thing `_entry_side` and `TP_HIT` actually require is that a rung is
  finite, positive and *strictly* beyond entry after rounding. A poor R:R on a strategy's declared
  objective is real information, and it is already surfaced honestly by `rr_ratio` and by the
  backtest; the ladder builder is not the place to second-guess it. The optional `min_rung_r` floor
  therefore defaults to **0** and is used by exactly one caller — `resolve_multi_signal()`, where a
  rung genuinely *is* being re-used against a stop no variant derived it with.
- **WFO calls the signal function with the grid combo only.** `walk_forward.train_fold()` (line 212)
  calls `run_strategy_backtest(train_bars, strategy=…, direction=…, params=combo)`, where `combo`
  contains **only** the `search:` keys — not `active:`. `run_strategy_backtest` then does
  `fn(slice_bars, direction=direction, **(params or {}))` (`strategy_backtest.py:114`). So any exit
  parameter that is not in the grid falls back to the *Python function default* during tuning, while
  the live scan uses the `active:` value via `_merge_strategy_params` (`stock_scan.py:151-155`). If
  the exit policy lived only in `active:`, the tuner would be optimising a strategy whose exits
  differ from the live one. **This is why Task 2 merges the `exit:` block inside
  `run_strategy_backtest` itself**, so tuning, scanning, watching and composite-triggering all see
  one exit policy.
- **A signal function raises `TypeError` on an unknown kwarg.** `active:` values are splatted
  straight into the signal function. Deleting a parameter from a function signature while leaving it
  in `active:` (or in `search:`) is an immediate hard failure, not a silent no-op. **No exit
  parameter is ever removed from a function signature in this plan** — `rr_target_mult` stays
  accepted everywhere it is accepted today.

### The WFO / backtest coupling, and what happens to `rr_target_mult`

`strategy_backtest` issues `tp=sig.target_price`. Because Task 3 makes `target_price = ladder[0]`
(the *nearest*, thesis-first rung), **every historical win rate, expectancy and Sharpe for every
stock strategy will move when this ships, and the direction is predictable: win rate up, average win
down.** That is honest — the old targets were an arbitrary 2R — but it is not a quiet change, and it
has two concrete consequences that must be handled rather than discovered later:

1. **The `step-6-backtest` confidence gate will pass and fail different candidates.** Expected. The
   gate thresholds (`bt_min_win_rate` 0.45, `bt_min_trades` 5) are unchanged; the numbers they judge
   are now measured against the strategy's real target. Task 16 checks a before/after on one symbol.
2. **Every tuned `active:` value in `strategy_params.yaml` was selected under the old target
   formula, so a re-run of the WFO tuner is an expected, *intended* side effect of this plan — not
   an accident.** Task 12 records this in the config file itself so the next person to read
   `active:` knows those numbers predate the exit rework.

The specific question — *what happens to the `search:` grid entry for a strategy whose target no
longer uses `rr_target_mult`* — resolves from the coupling above. The optimizer can only observe
`target_price` (= `ladder[0]`). A parameter that influences only rungs 2 and 3 is therefore
**invisible to the tuner**: the grid search would spend 3–4× the compute distinguishing combos with
identical backtests and then let `consensus()` write a median of pure noise into `active:`. That is
strictly worse than not tuning it. The rule this plan adopts, and applies uniformly:

> **`search:` may contain only parameters that influence `ladder[0]` or `stop_price`. Parameters
> that only scale rungs 2–3 leave the grid, and are written into BOTH `active:` and the new `exit:`
> block.**

The "and `exit:`" half is not belt-and-braces — it is load-bearing. `adopt()` replaces
`active[direction]` wholesale with the winning grid combo, so a parameter that is no longer in
`search:` is *deleted from `active:`* the first time the tuner adopts a proposal, and silently
reverts to the signal function's Python default. `exit:` is never touched by `adopt()`, and the
merge order is `exit < active < request`, so putting the value there gives it a durable configured
baseline that an adopt cannot erase and an explicit override can still beat.

Applied per strategy:

| Strategy | `rr_target_mult` today | After this plan | Grid change |
|---|---|---|---|
| `pullback_ema` | in `search:` (line 50), sets the only target | stays in `active:` **and moves into `exit:`** (2.0), scaling rungs 2–3; **removed from `search:`**. Replaced in the grid by `exit_swing_lookback: [10, 20, 30]`, which sets rung 1 (the prior swing high) | 432 → 324 combos |
| `breakout_base` | in `search:` (line 69), sets the only target | stays in `active:` **and `exit:`** (2.0) as the degenerate-case fallback only; **removed from `search:`**. Replaced by `measured_move_mult: [0.75, 1.0, 1.25, 1.5]`, which sets rung 1 | 144 → 144 combos |
| `mean_reversion_bb` | in `search:` (line 124), sets the only target | stays in `active:` **and `exit:`** (2.0) scaling rung 3; **removed from `search:`**, with **no replacement** — rung 1 is the mid-band, already fully determined by `bb_period`/`bb_std`, which are already in the grid and now genuinely drive the exit | 162 → 54 combos |
| `ma_crossover` | absent (hardcoded `atr × 3.0`) | the hardcoded 3.0 becomes `atr_target_mult`, **added** to `active:`, `exit:` (3.0) and `search:` `[2.0, 3.0, 4.0]` — it sets rung 1 | 8 → 24 combos |
| `mean_reversion_rsi` | absent (hardcoded `atr × 2.5`) | the hardcoded 2.5 becomes `atr_target_mult` in `active:` **and `exit:`** (2.5, **not** in `search:` — it scales rung 2 now); `exit_sma_period: [10, 20]` **added** to `search:`, it sets rung 1 | 12 → 24 combos |
| `mean_reversion_vwap` | in `active:` only, no `search:` block | unchanged — still no `search:` block (intraday-only, excluded from WFO); `rr_target_mult` (also mirrored into `exit:`) now scales rung 3 | n/a |
| `mean_reversion_vwap_daily` | has **no entry in `strategy_params.yaml` at all** | gains an `exit:`-only entry; still no `active:`/`search:` | n/a |
| `mean_reversion_multi` | not a key in `strategy_params.yaml` (assembled in `stock_scan.py` from variants) | unchanged — it inherits each variant's own policy, then resolves | n/a |

`backend/tests/test_strategy_params_config_sanity.py` asserts every `active.<direction>.<key>` that
*also appears in* `search` is one of the searched values. Keys present in `active:` but absent from
`search:` are explicitly skipped (that file's own comment, lines 52-56), so leaving `rr_target_mult`
in `active:` without a grid entry is legal and already precedented (`require_choppy_regime`,
`interval`). The new `exit:` block sits as a **sibling of** `active:`/`search:`, so that test does
not walk it at all.

### Why `target_price = ladder[0]` rather than "keep the 2R target and add rungs around it"

Two rejected alternatives, recorded so they are not re-litigated:

- *Keep `target_price` as the 2R multiple and add T1/T3 alongside.* Rejected: the backtest and the
  strategy-watch evaluator both read `target_price` and nothing else, so the strategy-aware rung
  would remain invisible to exactly the two systems that could validate it — which is the whole
  point of doing this backend-side rather than in `defaultOverlay()`.
- *Make `target_price` the furthest rung.* Rejected: it would make win rates worse than today across
  the board for no thesis reason, and `TP_HIT`'s `targets[0]` convention (verified above) already
  establishes nearest-first as this codebase's ordering.
- *Pool every candidate rung into one list and sort nearest-first.* Rejected — see the third
  "further fact" above. It reads as the simplest implementation and is the one bug that would make
  the whole approach a no-op for the strategies most in need of it, because a generic 2R extension is
  frequently nearer than the strategy's own objective. Hence `primary` + `extensions`.

`ma_crossover` is the one strategy whose primary rung is deliberately left numerically unchanged
(`atr × 3.0` by default): a moving-average cross has no natural price objective — its thesis exit is
"cross back", which is a *condition*, not a level — so inventing a nearer price target for it would
be a formula in search of a thesis. Its ladder extends outward (3 / 4.5 / 6 ATR) and the cross-back
level is emitted for display.

### The seven exit theses, and the input each one uses

Every input below is already computed inside its signal function today and discarded (verified
per-function; the two claims the brainstorm made about specific lines both check out). `sign` is
`+1` for Bullish and `−1` for Bearish throughout; `risk = |entry − stop|`, which every function
already guarantees is `> 0` before it constructs a signal.

Rung 1 is the helper's `primary`; rungs 2 and 3 are its `extensions`, and an extension that is not
strictly beyond the rung before it is dropped rather than reordered ahead of the thesis.

| Strategy | Rung 1 = `primary` (`target_price`) | Extension A | Extension B | Already-computed input |
|---|---|---|---|---|
| `pullback_ema` | prior swing extreme: `_swing_high(bars, exit_swing_lookback)` / `_swing_low(…)` | `entry + sign·risk·rr_target_mult` | `entry + sign·risk·rr_target_mult·1.5` | `bars`, `risk`; `_swing_high`/`_swing_low` are existing module helpers (lines 53-60) |
| `breakout_base` | measured move off the breakout level: `base_high + H·measured_move_mult` / `base_low − …`, `H = base_high − base_low` | `base_high + H·(measured_move_mult + 0.5)` | `base_high + H·(measured_move_mult + 1.0)` | `base_high`/`base_low` at lines 363-364 |
| `ma_crossover` | `entry + sign·atr·atr_target_mult` (3.0 — unchanged) | `entry + sign·atr·atr_target_mult·1.5` | `entry + sign·atr·atr_target_mult·2.0` | `atr` (line 437); plus `slow_ma[-1]` emitted as `detail["cross_back_level"]` |
| `mean_reversion_rsi` | return to the short-term mean: `_sma(closes, exit_sma_period)[-1]` | `entry + sign·atr·atr_target_mult` (2.5 — today's target) | `entry + sign·atr·atr_target_mult·1.5` | `closes` (line 482), `atr` (line 495); `_sma` is an existing helper (line 18) |
| `mean_reversion_bb` | mid-band `mid[-1]` | opposite band (`upper[-1]` bullish / `lower[-1]` bearish) | `entry + sign·risk·rr_target_mult` | all three at line 553 |
| `mean_reversion_vwap` | VWAP itself | `vwap + sign·atr·vwap_extension_atr` | `entry + sign·risk·rr_target_mult` | `vwap` (line 635), `atr` (638) |
| `mean_reversion_vwap_daily` | symmetric overshoot: `vwap·(1 + sign·dev_pct)` | `entry + sign·risk·rr_target_mult` | `entry + sign·risk·rr_target_mult·1.5` | `vwap` (699), `prev` (704) → `dev_pct` (730 — a *fraction*, despite the name; `detail` stores it ×100) |
| `mean_reversion_multi` | no `primary` — every fired variant's rungs are pooled as `extensions` and re-sanitized against the resolved entry/stop, so the tightest surviving rung leads | " | " | resolved in `resolve_multi_signal()` |

Two of these need their reasoning spelled out, because the obvious formula is wrong:

- **`mean_reversion_rsi` must NOT target the trend SMA.** The brainstorm suggested "RSI returns to
  mid (50) / the trend SMA". But the Bullish gate is `closes[-1] > trend[-1]` (line 497) — oversold
  *within* an uptrend — so the 200-SMA sits **below** entry. Targeting it would be targeting a loss.
  The mean this signal actually reverts to is a *short-term* one: RSI is low precisely because price
  is below its short mean, so `_sma(closes, 20)` is above entry for a Bullish fire and below it for a
  Bearish one. That is the price proxy for "RSI returns to mid", and it is the one used here.
- **`mean_reversion_vwap_daily` must NOT target VWAP.** Its Bullish gate is `current > vwap` (line
  712) — the bar has *already reclaimed* the rolling VWAP; VWAP is below entry and the "return to
  VWAP" target is already achieved at entry. Its thesis is a reclaim-and-overshoot, so rung 1 is the
  mirror of the deviation that triggered it: price deviated `dev_pct` below VWAP (a fraction,
  despite the name), so it targets `dev_pct` above VWAP. Its intraday sibling (`mean_reversion_vwap`) has the opposite gate — price
  is still *below* VWAP when it fires (line 644) — so for that one, VWAP itself is correct.

### Edge cases every formula must survive

`_build_target_ladder()` (Task 3) is the single place these are handled, so no individual formula
has to:

| Hazard | Where it comes from | Handling |
|---|---|---|
| `atr == 0` | `_atr()` returns `0.0` on a single-bar list (line 48-49); a genuinely flat series also gives 0 | ATR-derived rungs collapse onto `entry`, fail the strict "beyond entry after rounding" test, and are dropped |
| `atr < 0` | not reachable (`_atr` sums non-negative true ranges) but guarded anyway | `sign·atr·k` lands on the wrong side of entry → dropped |
| base height `H <= 0` | a perfectly flat base (`base_high == base_low`) | `H_eff = H if H > 0 else atr`; if that is also `<= 0`, all measured-move rungs land on the breakout level, are dropped, and the fallback rung applies |
| `mid`/band within pennies of entry | Bollinger squeeze | kept, if it is still strictly above `entry` at 2dp — it is the strategy's own declared objective, the backtest measures it honestly, and `rr_ratio` shows the resulting poor reward:risk. Only `resolve_multi_signal` applies an R-relative floor, and only because it re-uses rungs against a stop no variant derived them with |
| `vwap` unavailable | `_vwap()` returns `0.0` when total volume is 0 (line 79); both VWAP functions already `return None` on `vwap <= 0` (lines 636-637, 700-701) | unreachable — the signal never gets built |
| `_sma(closes, exit_sma_period)` returns `[]` | fewer bars than the period | the call site passes `None` as `primary`; the helper ignores `None`, and the first surviving extension leads |
| a rung lands exactly on `entry` after rounding | rounding to 2dp | dropped (not nudged) — `_entry_side` needs a strict inequality, and a one-cent target would be worse than no rung. The fallback guarantees the ladder is still non-empty |
| every rung is dropped | any combination of the above | ladder falls back to `[entry + sign·risk·max(fallback_mult, 0.5)]`; if even that rounds onto entry (sub-cent risk) it is nudged one cent. Always valid, because `risk > 0` is a precondition every caller already enforces |
| duplicate rungs | mid-band ≈ measured move ≈ 2R on some bar | extensions within 0.1% of the previous kept rung are dropped |
| an extension nearer than the primary | 2R inside the prior swing high; 1 ATR inside VWAP | dropped, **never** reordered ahead of the primary — this is the whole reason `primary` is a separate argument |
| `NaN` / `inf` | not currently reachable but cheap to guard | `math.isfinite` filter |

### The four sites that mint a stock `PortfolioPosition`

The pristine-vs-edited decision has to be applied at all of them, not just the one the brainstorm
found. Verified by grep for `buildPaperStockPosition`:

| Site | Has an edited overlay? | Levels to send |
|---|---|---|
| `StockPositionCard/index.tsx:212` ("Add to Portfolio") | **yes** — `overlay.{entry,stop,t1,t2,t3,sharesT1..3}` | the **edited** overlay; pristine signal already rides along in `stockCardSnapshotOf(card)` |
| `StockSendDialog/index.tsx:106` and `:129` (manual row, and the recommendation-mode fallback) | no — only `c.strategy` | the **pristine** signal ladder |
| `step-4-stocks/page.tsx:184` (after-scan auto-execute) | no — fires without a human in the loop | the **pristine** signal ladder |
| `ChartWorkspace/index.tsx:851` (manual buy from the chart) | no strategy at all | **no levels** — `stop` must stay `null`, never `0` |

`ChartWorkspace` is why the default changes from `stop: 0` to `stop: null` rather than being made a
required argument: a chart buy genuinely has no stop, and `null` is the value `floorStop()`,
`toBackendPayload()` and the backend's own `_floor_stop` all already mean by "unset".

### Deliberately NOT re-anchoring stock levels to the fill price

`POST /api/portfolio` re-anchors `stop`/`structuralStop`/`targets` by
`delta = live_price − scanStockPrice` whenever `scanStockPrice` is set and positive
(`backend/app/routers/portfolio.py:173, 197-227`). `buildPaperStockPosition` does not set
`scanStockPrice` today, so that path is dormant for stocks, and **this plan deliberately keeps it
dormant.**

Justification: the re-anchor adds a flat dollar delta to every level. That is right for an
option position whose stop is a premium-derived offset from the underlying at scan time. It is
*wrong* for these levels, which are absolute chart structure — a mid-Bollinger-band target shifted
by +$2 is no longer the mid-band, and a base-low stop shifted up is no longer below the base. Setting
`scanStockPrice` for stocks would silently corrupt exactly the strategy-awareness this plan is
building. Recorded here so a future reader does not "fix" the missing field.

Note that `add_position` *does* still overwrite `entry_price` with the live quote
(`portfolio.py:230-234`) regardless of `scanStockPrice`. That is fine and unchanged: the levels this
plan sends are absolute, not entry-relative, so a moved fill price changes the position's R:R
honestly rather than invalidating the levels.

### Why the structural stop reuses the existing endpoint

`find_structural_stop(candles, direction, reference_price)` (`structural_stop.py:27-31`) takes no
strike, no premium, no DTE. `POST /api/contracts/structural-stop` (`contracts.py:288-310`) passes it
`symbol` / `direction` / `stock_price` and nothing else. The `/contracts/` prefix is a legacy
namespace artefact, not a contract dependency. Task 15 therefore calls the **existing**
`api.getStructuralStop` from the stock card rather than adding an alias route: an alias would
duplicate the request/response models and the candle fetch for zero behavioural gain, and would then
have to be kept in sync. A one-line comment is added to the endpoint docstring naming its second
consumer. Stock first-passage *does* get a new endpoint — its request and response shapes share
nothing with the option version (no strike, no premium, no `optionPrice`, a target *ladder* instead
of three percentages).

### The GBM caveat for `mean_reversion_*`, and how it is handled

A constant drift derived from a trend score is the wrong generative model for a strategy whose entire
thesis is that the recent drift is transient and price snaps back. The estimate would look
authoritative and be systematically wrong for `mean_reversion_rsi` / `_bb` / `_vwap` / `_vwap_daily`
/ `_multi`.

> **Decision: label, do not suppress.** The backend returns a `modelCaveat: string | null` alongside
> the estimate, non-null for any strategy whose key starts with `mean_reversion`, and the card
> renders it inline under the Estimate block. Suppression is rejected for two reasons: the
> *stop-out* probability remains genuinely informative for a mean-reversion trade (its stop is an
> ordinary price barrier and GBM's variance estimate is not the part that is wrong), and suppressing
> only these five while showing an equally drift-assumption-dependent number for `breakout_base`
> would be an inconsistency the user cannot see the reasoning for. Putting the rule in the backend,
> next to the model, keeps it from being duplicated or drifting out of sync in the UI.

---

## File Structure

**New files:**
- `backend/tests/test_strategy_exit_policies.py` — ladder helper + per-strategy thesis tests.
- `backend/tests/test_stock_first_passage.py` — stock first-passage estimator tests.
- `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.exits.test.tsx` — overlay-from-backend-ladder and level-plumbing tests.

**Modified — backend:**
- `backend/app/services/strategy_engine.py` — `_build_target_ladder()`, `resolve_multi_signal()`, `StrategySignal.targets`, and the seven per-strategy exit policies.
- `backend/config/strategy_params.yaml` — one `exit:` block per strategy; `search:` realignment.
- `backend/app/services/strategy_param_store.py` — `get_exit()`.
- `backend/app/services/strategy_backtest.py` — merge the exit policy into `params` before calling the signal function.
- `backend/app/services/strategy_watch_evaluator.py` — same merge, so all three param-resolving consumers agree. (`composite_trigger_evaluator.py` is **not** modified — see Task 4 Step 3(c).)
- `backend/app/routers/stock_scan.py` — `_merge_strategy_params` picks up `exit:`; `mean_reversion_multi` uses `resolve_multi_signal`; `targets` surfaced on `StrategySignalOut`; new `POST /api/stocks/first-passage`.
- `backend/app/schemas/stock_scan.py` — `StrategySignalOut.targets`.
- `backend/app/scoring/first_passage.py` — `estimate_stock_first_passage()` and its result dataclasses.
- `backend/app/routers/contracts.py` — docstring only (names the stock consumer of `/contracts/structural-stop`).
- `backend/tests/test_strategy_engine.py` — one assertion updated (`test_pullback_ema_rr_ratio_is_two_to_one`).

**Modified — frontend:**
- `frontend/lib/paperTrade.ts` — `stockPositionLevels()` sanitizer; `buildPaperStockPosition()` gains `levels`; `stockCardSnapshotOf()` gains the `edited` block.
- `frontend/lib/paperTrade.test.ts` — extended.
- `frontend/components/organisms/StockPositionCard/index.tsx` — overlay seeded from the backend ladder; edited levels passed on add; Estimate + Check-structure sections.
- `frontend/components/organisms/StockSendDialog/index.tsx`, `frontend/app/(frame)/screener/step-4-stocks/page.tsx` — pristine levels passed on add; Step-4 exit copy corrected.
- `frontend/components/organisms/ChartWorkspace/index.tsx` — no change needed (verify only: it passes no levels, so `stop` defaults to `null`).
- `frontend/types/stockDomain.ts` — `StrategySignalData.targets?: number[]`; stock first-passage response types.
- `frontend/lib/api.ts` — `getStockFirstPassage()`.

**Explicitly NOT modified:** `frontend/types/domain.ts` (`PortfolioPosition.stop` / `.targets` /
`.structuralStop` and `TargetLevel` already carry everything needed — see Task 1 Step 1),
`frontend/components/organisms/TradeCard/**`, `frontend/app/(frame)/screener/step-7-trade-card/**`.

---

# Approach A — stop dropping the levels at the portfolio boundary

### Task 1: Add the level sanitizer to `paperTrade.ts`

**Files:**
- Modify: `frontend/lib/paperTrade.ts`
- Modify: `frontend/lib/paperTrade.test.ts`

- [ ] **Step 1: Confirm no `types/domain.ts` change is needed**

Read `frontend/types/domain.ts:171-183` (`TargetLevel`) and `:186-226` (`PortfolioPosition`). Confirm:
`TargetLevel.stockPrice` is a required `number`, `targetPrice`/`contractsToSell`/`status` are optional;
`PortfolioPosition.stop` is `number | null`, `structuralStop` is `number | null | undefined`, `targets`
is `TargetLevel[]`. All four fields this plan writes already exist with the right types.

**Do not edit `types/domain.ts`.** A sibling agent is working in `TradeCard`/`step-7-trade-card`,
which imports from this file; leaving it untouched keeps the two workstreams disjoint. If a later
task appears to need a change here, stop and re-derive — it almost certainly does not.

- [ ] **Step 2: Add `stockPositionLevels()` and widen `buildPaperStockPosition()`**

Find (`frontend/lib/paperTrade.ts:1-2`):

```typescript
import type { Direction, PortfolioPosition } from '@/types/domain';
import type { PositionCardData } from '@/types/stockDomain';
```

Replace with:

```typescript
import type { Direction, PortfolioPosition, TargetLevel } from '@/types/domain';
import type { PositionCardData } from '@/types/stockDomain';

/** One rung of a stock exit ladder, before sanitizing. */
export interface StockTargetInput {
  price:  number;
  shares?: number;
}

export interface StockLevels {
  stop:    number | null;
  targets: TargetLevel[];
}

/**
 * Turn a raw (entry, stop, ladder) triple into the exact `{ stop, targets }` pair
 * `PortfolioPosition` wants, dropping anything that would be meaningless or actively
 * dangerous downstream.
 *
 * Why each rule exists:
 *  - `portfolioStore.floorStop()` maps any non-positive stop to `null` ("unset") at all
 *    eight of its documented entry points, so sending `0` LOOKS like it worked and
 *    silently no-ops. This returns `null` explicitly instead, never `0`.
 *  - A stop on the wrong side of entry (bullish stop above entry) is a data error, and
 *    `alert_generator.py`'s STOP_REACHED comparison would treat it as breached on the
 *    very first tick — a real notification for a position that is fine. Dropped.
 *  - `alert_generator.py:93` fires TP_HIT against `targets[0]` and nothing else, so the
 *    ladder MUST be nearest-first; a user is free to type T1 > T2 in the card, so the
 *    ordering is enforced here rather than trusted. Share allocations travel with their
 *    price through the sort.
 *  - Both `stockPrice` and `targetPrice` are written. Only `stockPrice` is read today
 *    (by TP_HIT and the portfolio drawer), but `POST /api/portfolio`'s re-anchor branch
 *    does `(t.get("targetPrice") or 0) + delta`, which would turn a missing field into a
 *    bogus small number if that branch is ever enabled for stocks.
 */
export function stockPositionLevels(
  entry: number,
  direction: Direction,
  stop: number | null | undefined,
  targets: ReadonlyArray<StockTargetInput> = [],
): StockLevels {
  const sign = direction === 'Bullish' ? 1 : -1;
  const entryOk = Number.isFinite(entry) && entry > 0;

  const safeStop =
    entryOk && stop != null && Number.isFinite(stop) && stop > 0 && sign * (entry - stop) > 0
      ? Math.round(stop * 100) / 100
      : null;

  const rungs = entryOk
    ? targets
        .filter((t) => Number.isFinite(t.price) && t.price > 0 && sign * (t.price - entry) > 0)
        .map((t) => ({
          price: Math.round(t.price * 100) / 100,
          shares: t.shares != null && Number.isFinite(t.shares) && t.shares > 0
            ? Math.round(t.shares)
            : undefined,
        }))
        .sort((a, b) => sign * (a.price - b.price))
    : [];

  return {
    stop: safeStop,
    targets: rungs.map((r, i) => ({
      id: `T${i + 1}`,
      stockPrice: r.price,
      targetPrice: r.price,
      ...(r.shares != null ? { contractsToSell: r.shares } : {}),
      status: 'PENDING',
    })),
  };
}
```

- [ ] **Step 3: Wire `levels` through `buildPaperStockPosition()`**

Find (`frontend/lib/paperTrade.ts:19-47`):

```typescript
export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
  direction: Direction,
  snapshot?: Record<string, unknown>,
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction,
    entryPrice:   price,
    contracts:    shares,
    entryDate:    today,
    expiry:       '',
    stop:         0,
    targets:      [],
```

Replace with:

```typescript
export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
  direction: Direction,
  snapshot?: Record<string, unknown>,
  levels?: {
    stop?: number | null;
    targets?: ReadonlyArray<StockTargetInput>;
    /** Optional chart-structure level; only set when the user ran "Check structure". */
    structuralStop?: number | null;
  },
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  // Levels are OPTIONAL by design: ChartWorkspace's manual buy has no strategy and
  // therefore genuinely has no stop. `null` (not 0) is what every layer already means
  // by "unset" — floorStop(), toBackendPayload(), and the backend's own _floor_stop.
  const { stop, targets } = stockPositionLevels(price, direction, levels?.stop, levels?.targets ?? []);
  const structuralStop =
    levels?.structuralStop != null && Number.isFinite(levels.structuralStop) && levels.structuralStop > 0
      ? Math.round(levels.structuralStop * 100) / 100
      : null;
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction,
    entryPrice:   price,
    contracts:    shares,
    entryDate:    today,
    expiry:       '',
    stop,
    structuralStop,
    targets,
```

The remainder of the object literal (`dteTotal` through `tradeCardSnapshot`) is unchanged.

- [ ] **Step 4: Extend the unit tests**

Find (`frontend/lib/paperTrade.test.ts:1-3`):

```typescript
import { buildPaperStockPosition } from './paperTrade';
```

Replace with:

```typescript
import { buildPaperStockPosition, stockPositionLevels } from './paperTrade';
```

The two existing tests assert only `symbol` / `contract` / `entryPrice` / `contracts` / `direction`
— **neither touches `stop` or `targets`, so neither needs changing.** (An earlier draft of this plan
claimed they assert `stop === 0`; re-read the file, they do not.) Append:

```typescript
describe('stockPositionLevels', () => {
  it('never emits a 0 stop — floorStop would silently treat it as unset', () => {
    expect(stockPositionLevels(100, 'Bullish', 0, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bullish', -5, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bullish', null, []).stop).toBeNull();
  });

  it('drops a stop on the wrong side of entry', () => {
    expect(stockPositionLevels(100, 'Bullish', 105, []).stop).toBeNull();
    expect(stockPositionLevels(100, 'Bearish', 95, []).stop).toBeNull();
  });

  it('keeps a genuine stop on the correct side', () => {
    expect(stockPositionLevels(100, 'Bullish', 95, []).stop).toBe(95);
    expect(stockPositionLevels(100, 'Bearish', 105, []).stop).toBe(105);
  });

  it('sorts targets nearest-first because TP_HIT only reads targets[0]', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [
      { price: 120, shares: 3 }, { price: 105, shares: 5 }, { price: 110, shares: 2 },
    ]);
    expect(targets.map((t) => t.stockPrice)).toEqual([105, 110, 120]);
    expect(targets.map((t) => t.contractsToSell)).toEqual([5, 2, 3]);
  });

  it('sorts bearish targets nearest-first (descending price)', () => {
    const { targets } = stockPositionLevels(100, 'Bearish', 105, [
      { price: 80 }, { price: 95 }, { price: 90 },
    ]);
    expect(targets.map((t) => t.stockPrice)).toEqual([95, 90, 80]);
  });

  it('drops targets on the wrong side of entry', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [{ price: 99 }, { price: 110 }]);
    expect(targets.map((t) => t.stockPrice)).toEqual([110]);
  });

  it('writes both stockPrice and targetPrice on every rung', () => {
    const { targets } = stockPositionLevels(100, 'Bullish', 95, [{ price: 110 }]);
    expect(targets[0]).toMatchObject({ stockPrice: 110, targetPrice: 110, status: 'PENDING' });
  });

  it('returns no levels at all when entry is unusable', () => {
    expect(stockPositionLevels(0, 'Bullish', 95, [{ price: 110 }])).toEqual({ stop: null, targets: [] });
  });
});

describe('buildPaperStockPosition levels', () => {
  it('carries a real stop and ladder', () => {
    const p = buildPaperStockPosition('AAPL', 100, 10, 'Bullish', undefined, {
      stop: 95, targets: [{ price: 110, shares: 4 }, { price: 120, shares: 6 }],
    });
    expect(p.stop).toBe(95);
    expect(p.targets).toHaveLength(2);
    expect(p.targets[0].stockPrice).toBe(110);
  });

  it('leaves stop null when no levels are supplied (ChartWorkspace manual buy)', () => {
    expect(buildPaperStockPosition('AAPL', 100, 10, 'Bullish').stop).toBeNull();
  });
});
```

- [ ] **Step 5: Run**

```bash
cd frontend && npm run typecheck && npm run test -- --testPathPattern=paperTrade
```
Expected: clean typecheck, all `paperTrade` tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/paperTrade.ts frontend/lib/paperTrade.test.ts
git commit -m "feat(stocks): add level sanitizer to buildPaperStockPosition, stop hardcoding stop:0"
```

---

### Task 2: Pass real levels at all four stock-position sites

**Files:**
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx`
- Modify: `frontend/components/organisms/StockSendDialog/index.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- Modify: `frontend/lib/paperTrade.ts` (the `edited` half of the snapshot)
- Verify only: `frontend/components/organisms/ChartWorkspace/index.tsx`

- [ ] **Step 1: Record the edited overlay in the audit snapshot**

Find (`frontend/lib/paperTrade.ts:4-17`):

```typescript
// The "why was this bought" snapshot for the stocks path — attached once at
// buy time so it survives independent of later scans overwriting scanStore.
export function stockCardSnapshotOf(c: PositionCardData): Record<string, unknown> {
  return {
    stock_score: c.stock_score,
```

Replace with:

```typescript
// The "why was this bought" snapshot for the stocks path — attached once at
// buy time so it survives independent of later scans overwriting scanStore.
//
// This carries the PRISTINE strategy signal (`strategy`), which is the analytics /
// audit copy of the levels. The user's EDITED levels go into the live
// `PortfolioPosition.stop` / `.targets` fields, which are what the alert engine
// actually fires on. Passing `edited` here records the diff between the two, so the
// audit answer to "why was this bought, and at what levels" is complete rather than
// just a baseline. See the plan's "Pristine or edited?" decision.
export function stockCardSnapshotOf(
  c: PositionCardData,
  edited?: { entry: number; stop: number; targets: number[]; shares: number },
): Record<string, unknown> {
  return {
    ...(edited ? { edited } : {}),
    stock_score: c.stock_score,
```

The rest of the returned object is unchanged.

- [ ] **Step 2: `StockPositionCard` — send the edited overlay**

Find (`frontend/components/organisms/StockPositionCard/index.tsx:210-213`):

```typescript
    try {
      const res = await addPosition(
        buildPaperStockPosition(card.symbol, overlay.entry, overlay.shares, card.direction as Direction, stockCardSnapshotOf(card)),
      );
```

Replace with:

```typescript
    try {
      // The user's EDITED overlay is what gets persisted as the live stop/targets —
      // it is what they intend to trade, and it is what TP_HIT / STOP_REACHED will
      // fire on. The pristine signal rides along inside the snapshot for the audit
      // trail. stockPositionLevels() drops anything non-positive or on the wrong
      // side of entry, so a half-edited overlay can never send a 0 stop.
      const res = await addPosition(
        buildPaperStockPosition(
          card.symbol, overlay.entry, overlay.shares, card.direction as Direction,
          stockCardSnapshotOf(card, {
            entry: overlay.entry,
            stop: overlay.stop,
            targets: [overlay.t1, overlay.t2, overlay.t3],
            shares: overlay.shares,
          }),
          {
            stop: overlay.stop,
            targets: [
              { price: overlay.t1, shares: overlay.sharesT1 },
              { price: overlay.t2, shares: overlay.sharesT2 },
              { price: overlay.t3, shares: overlay.sharesT3 },
            ],
          },
        ),
      );
```

- [ ] **Step 3: `StockSendDialog` — send the pristine ladder at both sites**

This file calls `buildPaperStockPosition` twice, at lines 105-107 (the "manual" row) and 128-130
(the auto-send-with-broker-`recommendation` fallback). They are byte-identical today; make them
byte-identical after the change too. First add a helper just above `async function submit()`
(line 80):

```typescript
  // Both add-to-portfolio paths below send the PRISTINE strategy levels: this dialog
  // has no per-row level editor, so there is no overlay to prefer. `strategy.targets`
  // is the backend ladder (Task 11); the `?? [target_price]` fallback covers a scan
  // result restored from localStorage that predates that field.
  const pristineLevels = (c: PositionCardData) => ({
    stop: c.strategy.stop_price,
    // `?.length ? … : …`, NOT `?? …`: nullish coalescing does not catch an EMPTY
    // array, and an older backend (or a scan result rehydrated from
    // localStorage) can send `targets: []`, which would silently persist a
    // position with no take-profit at all.
    targets: (c.strategy.targets?.length ? c.strategy.targets : [c.strategy.target_price])
      .map((price) => ({ price })),
  });
```

Then at **both** call sites replace:

```typescript
        const res = await addPosition(
          buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction, stockCardSnapshotOf(c)),
        );
```

with:

```typescript
        const res = await addPosition(
          buildPaperStockPosition(
            c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction,
            stockCardSnapshotOf(c), pristineLevels(c),
          ),
        );
```

- [ ] **Step 4: `step-4-stocks` after-scan auto-execute — send the pristine ladder**

Find (`frontend/app/(frame)/screener/step-4-stocks/page.tsx:184`):

```typescript
        const addRes = await addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction));
```

Replace with:

```typescript
        // Auto-execute fires with no human in the loop, so there is no overlay to
        // prefer — send the pristine strategy levels. Note this path also did not
        // attach a snapshot before; it still does not, deliberately (the scan result
        // it came from is already persisted in scanStore).
        const addRes = await addPosition(buildPaperStockPosition(
          c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction, undefined,
          {
            stop: c.strategy.stop_price,
            // `?.length ?` not `??` — an empty array must fall back too.
            targets: (c.strategy.targets?.length ? c.strategy.targets : [c.strategy.target_price])
              .map((price) => ({ price })),
          },
        ));
```

- [ ] **Step 5: Verify `ChartWorkspace` needs no change**

Read `frontend/components/organisms/ChartWorkspace/index.tsx:851`. Confirm it calls
`buildPaperStockPosition(symbol, price, qty, 'Bullish')` with four arguments and no strategy context.
With Task 1 in place this now yields `stop: null` (previously `stop: 0`) — the intended behaviour for
a manual chart buy. **Make no edit here.** Note the improvement in the commit message.

- [ ] **Step 6: Run**

```bash
cd frontend && npm run typecheck && npm run test -- --testPathPattern="paperTrade|StockSendDialog|portfolioStore"
```
Expected: clean. `portfolioStore.test.ts:97` has a round-6 audit comment referencing
`buildPaperStockPosition` sending `stop: 0` — read that test. If it asserts the *store* floors a 0 it
still passes unchanged (the store's floor is untouched and still correct as defence-in-depth); if it
asserts `buildPaperStockPosition` *produces* a 0, update the comment and the expectation to `null`
and note it in the commit.

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/paperTrade.ts frontend/components/organisms/StockPositionCard/index.tsx \
        frontend/components/organisms/StockSendDialog/index.tsx \
        "frontend/app/(frame)/screener/step-4-stocks/page.tsx" frontend/lib/paperTrade.test.ts
git commit -m "feat(stocks): carry strategy/edited exit levels into PortfolioPosition at all four sites"
```

---

# Approach D — declarative per-strategy exit policies

### Task 3: `_build_target_ladder()` and `StrategySignal.targets`

**Files:**
- Modify: `backend/app/services/strategy_engine.py`
- Create: `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Add the ladder builder above the `StrategySignal` dataclass**

Insert immediately before the `# ── Signal dataclass ──` banner (`strategy_engine.py:206`):

```python
# ── Exit-target ladder ────────────────────────────────────────────────────────

_LADDER_MAX_RUNGS = 3


_LADDER_MIN_FALLBACK_R = 0.5


def _build_target_ladder(
    *,
    entry: float,
    stop: float,
    direction: str,
    primary: float | None,
    extensions: list[float | None],
    fallback_mult: float,
    min_rung_r: float = 0.0,
) -> list[float]:
    """Turn a strategy's exit thesis into a validated, nearest-first ladder.

    Single place where every degenerate case is handled, so no individual signal
    function has to. Callers pass their own objective as ``primary`` and their
    outward continuations as ``extensions`` — including ``None`` and values that
    may land on the wrong side of entry — and get back a ladder that is
    guaranteed non-empty, strictly on the profitable side of entry, strictly
    monotonic, and ordered nearest-first.

    WHY ``primary`` IS A SEPARATE ARGUMENT — the one thing not to "simplify".
    Pooling every candidate into one list and sorting by distance would let a
    generic R/ATR extension become ``ladder[0]`` whenever it happens to be
    nearer than the strategy's own objective, which is exactly the thing this
    rework exists to stop: ``ladder[0]`` is ``target_price``, and
    ``target_price`` is the only exit ``strategy_backtest`` can observe (it
    issues ``tp=sig.target_price``). It is not hypothetical — for
    ``mean_reversion_vwap`` the entry gate puts VWAP >= 1.5% away while
    ``risk = 0.5 ATR``, so ``entry + 2R`` is almost always nearer than VWAP.
    The primary leads whenever it is valid; an extension that is not strictly
    beyond the rung before it is DROPPED, never reordered ahead of it.

    Nearest-first is load-bearing, not cosmetic: ``alert_generator.py`` fires
    ``TP_HIT`` against ``targets[0]`` and nothing else.

    Rungs are DROPPED, never clamped, when they fail a test. Clamping a
    wrong-side value into place would manufacture a target the strategy never
    claimed; dropping it lets the next rung — or the fallback — take over
    honestly.

    WHY THERE IS NO R-RELATIVE FLOOR BY DEFAULT. The only thing ``_entry_side``
    and ``TP_HIT`` require is that a rung is finite, positive and *strictly*
    beyond entry after rounding. An R-relative "must be at least 0.5R away"
    floor sounds prudent and is actively harmful applied to a primary:
    ``ma_crossover``'s stop sits at the slow MA, which right after a fast cross
    can be far below price, so 0.5R there can exceed its 3-ATR objective — the
    floor would silently drop the one rung this plan promises is numerically
    unchanged and promote a 6-ATR extension instead. A poor reward:risk on a
    strategy's declared objective is real information; ``rr_ratio`` and the
    backtest are where it belongs. ``min_rung_r`` therefore defaults to 0 and
    has exactly one caller: ``resolve_multi_signal``, where a rung genuinely IS
    being re-used against a stop no variant derived it with.

    Args:
        entry:  signal entry price (> 0, caller-guaranteed).
        stop:   signal stop price. ``risk = abs(entry - stop)`` must be > 0;
                every caller already returns None before reaching here otherwise.
        direction: "Bullish" or "Bearish".
        primary: the strategy's own exit objective, or ``None`` when it is
                unavailable on this bar (e.g. too few bars for the short SMA).
        extensions: outward continuations, in the caller's own order; they are
                sorted nearest-first among themselves. ``None`` entries are
                ignored so a caller can pass an optional level unconditionally.
        fallback_mult: R multiple used for the guaranteed rung when every
                supplied rung is dropped. Floored at 0.5R.
        min_rung_r: optional minimum distance from entry, in R, applied to every
                supplied rung (primary included). Defaults to 0 — see above.

    Returns:
        1..3 prices, rounded to 2dp, strictly ordered away from entry. Empty
        only when the inputs are degenerate (``risk <= 0`` or ``entry <= 0``).
    """
    sign = 1.0 if direction == "Bullish" else -1.0
    risk = abs(entry - stop)
    if risk <= 0 or not math.isfinite(risk) or entry <= 0 or not math.isfinite(entry):
        # Unreachable via the signal functions (each returns None on risk <= 0),
        # but this helper is public enough to be called from a future consumer.
        return []

    entry_r = round(entry, 2)
    floor = entry + sign * min_rung_r * risk

    def _valid(value: float | None) -> float | None:
        """Round to 2dp and keep only if strictly beyond entry (and the floor)."""
        if value is None or not math.isfinite(value) or value <= 0:
            return None
        if min_rung_r > 0 and sign * (value - floor) < 0:
            return None
        rounded = round(value, 2)
        # A rung that rounds onto (or behind) entry is dropped rather than
        # nudged: _entry_side needs a strict inequality, and a one-cent target
        # would be worse than letting the next rung or the fallback take over.
        if sign * (rounded - entry_r) <= 0:
            return None
        return rounded

    ladder: list[float] = []

    head = _valid(primary)
    if head is not None:
        ladder.append(head)

    ext = sorted(
        (v for v in (_valid(e) for e in extensions) if v is not None),
        key=lambda v: sign * (v - entry),
    )
    for value in ext:
        if len(ladder) >= _LADDER_MAX_RUNGS:
            break
        if ladder:
            prev = ladder[-1]
            # Strictly beyond the previous rung — an extension that is nearer
            # than the primary is dropped, never reordered ahead of it.
            if sign * (value - prev) <= 0:
                continue
            # Dedupe within 0.1% of the previous rung: a squeezed mid-band and a
            # 2R extension really can coincide on some bars, and two
            # indistinguishable rungs in the UI is noise.
            if prev > 0 and abs(value - prev) / prev < 0.001:
                continue
        ladder.append(value)

    if not ladder:
        fallback = entry + sign * risk * max(fallback_mult, _LADDER_MIN_FALLBACK_R)
        rounded = round(fallback, 2)
        if sign * (rounded - entry_r) <= 0:
            # Sub-cent risk. One tick is the smallest thing _entry_side accepts.
            rounded = round(entry_r + sign * 0.01, 2)
        ladder.append(rounded)

    return ladder
```

Add `import math` to the module's imports (`strategy_engine.py:1-4`):

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal
```

- [ ] **Step 2: Add `targets` to `StrategySignal`**

Find (`strategy_engine.py:208-216`):

```python
@dataclass
class StrategySignal:
    strategy:    str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float
    stop_price:  float
    target_price: float
    atr:         float
    detail:      dict = field(default_factory=dict)
```

Replace with:

```python
@dataclass
class StrategySignal:
    strategy:    str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float
    stop_price:  float
    target_price: float
    atr:         float
    detail:      dict = field(default_factory=dict)
    #: Full nearest-first exit ladder. ``target_price`` is always ``targets[0]``
    #: — every existing consumer (strategy_backtest's ``tp=``, the strategy-watch
    #: evaluator, the composite trigger evaluator) reads ``target_price`` and is
    #: unaffected; ``targets`` is additive. Defaults to ``[]`` so a directly
    #: constructed signal (several tests do this) stays valid.
    targets:     list[float] = field(default_factory=list)
```

- [ ] **Step 3: Test the helper**

Create `backend/tests/test_strategy_exit_policies.py`:

```python
"""Exit-ladder helper and per-strategy exit-thesis tests."""
from __future__ import annotations

import math

import pytest

from app.services.strategy_engine import _build_target_ladder


def test_ladder_puts_the_primary_first_and_sorts_extensions_bullish():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=105, extensions=[120, 110], fallback_mult=2.0)
    assert out == [105.0, 110.0, 120.0]


def test_ladder_puts_the_primary_first_and_sorts_extensions_bearish():
    out = _build_target_ladder(entry=100, stop=105, direction="Bearish",
                               primary=95, extensions=[80, 90], fallback_mult=2.0)
    assert out == [95.0, 90.0, 80.0]


def test_ladder_never_reorders_a_nearer_extension_ahead_of_the_primary():
    """THE regression this design exists for: a generic 2R extension nearer than
    the strategy's own objective must be dropped, not promoted to target_price."""
    out = _build_target_ladder(entry=100, stop=99, direction="Bullish",
                               primary=110, extensions=[102, 115], fallback_mult=2.0)
    assert out[0] == 110.0
    assert 102.0 not in out
    assert out == [110.0, 115.0]


def test_ladder_never_reorders_a_nearer_extension_ahead_of_the_primary_bearish():
    out = _build_target_ladder(entry=100, stop=101, direction="Bearish",
                               primary=90, extensions=[98, 85], fallback_mult=2.0)
    assert out == [90.0, 85.0]


def test_ladder_drops_wrong_side_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=99, extensions=[110], fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_keeps_a_primary_inside_half_an_r_by_default():
    """No R-relative floor by default — a squeezed mid-band a few cents above
    entry is the strategy's own objective and is measured honestly."""
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=100.4, extensions=[112], fallback_mult=2.0)
    assert out == [100.4, 112.0]


def test_ladder_min_rung_r_drops_rungs_inside_the_floor_when_asked():
    # risk = 5, min_rung_r 0.5 -> floor at 102.5; 101 is inside it.
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=101, extensions=[112], fallback_mult=2.0,
                               min_rung_r=0.5)
    assert out == [112.0]


def test_ladder_falls_back_when_every_rung_is_dropped():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=None, extensions=[90, float("nan"), 0],
                               fallback_mult=2.0)
    assert out == [110.0]     # entry + 2R


def test_ladder_fallback_respects_the_minimum_fallback_floor():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=None, extensions=[], fallback_mult=0.0)
    assert out == [102.5]     # max(fallback_mult, 0.5R)


def test_ladder_handles_zero_atr_derived_rungs():
    # atr == 0 collapses every ATR rung onto entry; all are dropped.
    entry, atr = 100.0, 0.0
    out = _build_target_ladder(entry=entry, stop=95, direction="Bullish",
                               primary=entry + atr * 3.0,
                               extensions=[entry + atr * 4.5, entry + atr * 6.0],
                               fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_dedupes_near_identical_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=110.0, extensions=[110.05, 120.0],
                               fallback_mult=2.0)
    assert out == [110.0, 120.0]


def test_ladder_caps_at_three_rungs():
    out = _build_target_ladder(entry=100, stop=95, direction="Bullish",
                               primary=105, extensions=[110, 115, 120, 125],
                               fallback_mult=2.0)
    assert len(out) == 3


def test_ladder_first_rung_always_satisfies_entry_side_gate():
    from app.services.strategy_backtest import _entry_side
    for direction, stop in (("Bullish", 95.0), ("Bearish", 105.0)):
        out = _build_target_ladder(entry=100.0, stop=stop, direction=direction,
                                   primary=None, extensions=[], fallback_mult=2.0)
        assert _entry_side(direction, entry=100.0, sl=stop, tp=out[0]) is not None


def test_ladder_drops_a_rung_that_rounds_onto_entry():
    out = _build_target_ladder(entry=100.0, stop=95.0, direction="Bullish",
                               primary=100.001, extensions=[], fallback_mult=2.0)
    assert out == [110.0]


def test_ladder_returns_empty_on_zero_risk():
    assert _build_target_ladder(entry=100, stop=100, direction="Bullish",
                                primary=110, extensions=[], fallback_mult=2.0) == []
```

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_strategy_engine.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(strategy-engine): add validated exit-target ladder builder and StrategySignal.targets"
```

---

### Task 4: `exit:` config block and a single resolution path

**Files:**
- Modify: `backend/config/strategy_params.yaml`
- Modify: `backend/app/services/strategy_param_store.py`
- Modify: `backend/app/services/strategy_backtest.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `backend/app/services/strategy_watch_evaluator.py`
- Verify only (no edit): `backend/app/services/composite_trigger_evaluator.py`

- [ ] **Step 1: Add `get_exit()` to the param store**

Find (`backend/app/services/strategy_param_store.py`, after `get_search_space`):

```python
def get_search_space(strategy: str) -> dict:
    """Get search space (hyperparameter grid) for a strategy.

    Returns a copy of the search params dict, or empty dict if strategy not found.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("search", {}))
```

Add immediately after:

```python
def get_exit(strategy: str) -> dict:
    """Exit-policy params for a strategy — the ``exit:`` block, a sibling of
    ``active:``/``search:``.

    Deliberately NOT direction-keyed. Every exit thesis in ``strategy_engine`` is
    a mirror pair (measured move up / measured move down, mid-band from below /
    from above) implemented by the function's own ``if direction ==`` branch, so
    the tunables — how far to project, which lookback, which extension multiple —
    are direction-symmetric. Keeping them flat avoids a second place for the two
    directions to silently drift apart.

    Merged UNDER request/grid params at every call site, so an explicit override
    always wins. Returns {} for a strategy with no ``exit:`` block, in which case
    the signal function's own Python defaults apply.

    DURABILITY, which is half the reason this block exists: ``adopt()`` replaces
    ``active[direction]`` wholesale with the WFO tuner's winning grid combo, so a
    parameter that is not in ``search:`` is DELETED from ``active:`` the first
    time a proposal is adopted. ``exit:`` is never touched by ``adopt()``, so a
    rung-2/3 parameter written here keeps its configured value across every
    re-tune instead of silently reverting to the Python default.

    Note also that ``adopt()`` rewrites the whole YAML with ``yaml.safe_dump``,
    which destroys every comment in the file. Configuration prose in
    strategy_params.yaml is therefore best-effort; the durable record of why
    these values exist is this docstring and
    docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("exit", {}))
```

- [ ] **Step 2: ~~Add the `exit:` blocks to `strategy_params.yaml`~~ — MOVED TO TASK 12**

> **Implementation-order correction (found while implementing).** Writing the `exit:` blocks here,
> before Tasks 5–10 add the matching keyword parameters, breaks the tree: `active:`/`exit:` values are
> splatted straight into the signal function, so `atr_target_mult: 3.0` reaching an
> `ma_crossover_signal` that does not yet accept it is an immediate `TypeError`, and
> `run_strategy_backtest` swallows it into a zero-trade `_empty_result`. Verified empirically — five
> `test_strategy_backtest.py` tests fail at this point with
> `"ma_crossover_signal() got an unexpected keyword argument 'atr_target_mult'"`.
>
> The plumbing below (Step 1's `get_exit`, Step 3's three merge sites) is safe on its own:
> `get_exit()` returns `{}` for every strategy until the blocks exist. **So Task 4 ships the plumbing
> only, and the entire YAML edit — `exit:` blocks and `search:` realignment together — happens in
> Task 12, after every signature exists.** They were always one coherent edit to one file; splitting
> them across two tasks was the mistake.
>
> The full `exit:` block content is specified in Task 12 Step 1. It is reproduced here for reference
> only — do not write it yet:

Insert an `exit:` block into each strategy, between its `active:` and `search:` blocks. Full values
are given per-strategy in Tasks 5–10; add them all now so the merge points can be wired in one pass:

Every rung-2/3 parameter appears here **as well as** in `active:` — `exit:` is the copy that
survives a tuner `adopt()`.

```yaml
strategies:
  pullback_ema:
    active:
      # ... unchanged ...
    # Exit policy — see docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md.
    # Direction-symmetric by design; the Bullish/Bearish mirror lives in the signal
    # function, not here. Merged UNDER active:/request params, so an override wins.
    # adopt() never rewrites this block, so it is the durable home for any exit
    # parameter that is not in search: (adopt replaces active: wholesale).
    exit:
      exit_swing_lookback: 20      # rung 1: prior swing high/low over this many bars
      rr_target_mult: 2.0          # rungs 2-3: R extensions past the swing extreme
    search:
      # ... see Task 12 for the realignment ...

  breakout_base:
    exit:
      measured_move_mult: 1.0      # rung 1: base height projected off the breakout level
      rr_target_mult: 2.0          # degenerate-case fallback only (flat base AND zero ATR)

  ma_crossover:
    exit:
      atr_target_mult: 3.0         # rung 1: ATR extension (was hardcoded 3.0)

  mean_reversion_rsi:
    exit:
      exit_sma_period: 20          # rung 1: return to the SHORT-term mean (not the 200 trend SMA)
      atr_target_mult: 2.5         # rung 2: ATR extension (was hardcoded 2.5)

  mean_reversion_bb:
    exit:
      # rung 1 = mid-band, rung 2 = opposite band: neither has a tunable of its
      # own (both follow bb_period/bb_std, already in active:/search:).
      rr_target_mult: 2.0          # rung 3 only

  mean_reversion_vwap:
    exit:
      vwap_extension_atr: 0.5      # rung 2: ATR extension past VWAP
      rr_target_mult: 2.0          # rung 3 only

  mean_reversion_vwap_daily:
    exit:
      # rung 1 = symmetric overshoot of the entry deviation; no tunable of its own.
      rr_target_mult: 2.0          # rungs 2-3 only

  breakout_setup:
    # no exit: block — SetupSignal has no levels (see the plan's scope section)
```

`mean_reversion_vwap_daily` has no top-level key in `strategy_params.yaml` today (verified), so this
adds one with only an `exit:` child.

> **Implementation note:** verified — `test_strategy_params.py`, `test_strategy_param_store.py` and
> `test_strategy_param_store_direction.py` contain no assertion over the exact set of strategy keys,
> so adding a `mean_reversion_vwap_daily` key is safe. `test_strategy_params_config_sanity.py` walks
> only `active`/`search`, so it never sees `exit:` at all.

- [ ] **Step 3: Merge the exit policy at the three consumer sites that resolve params**

**(a) The live scan** — find (`backend/app/routers/stock_scan.py:151-155`):

```python
def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
    """Adopted defaults for this direction, overridden by per-request kwargs."""
    merged = get_active(strategy, direction)
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged
```

Replace with:

```python
def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
    """Exit policy, then adopted defaults for this direction, then per-request kwargs.

    Precedence is deliberately exit < active < request: the exit block is a
    baseline the tuner may later override into `active:` (WFO's adopt() writes
    there), and an explicit per-scan override always wins over both.
    """
    merged = get_exit(strategy)
    merged.update(get_active(strategy, direction))
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged
```

and extend the import at the top of the file (`stock_scan.py:47` already imports `get_active` and
`get_costs` from `app.services.strategy_param_store`) to include `get_exit`.

Note this changes `_backtest_key`'s inputs: `_bt_params` is part of the backtest cache key, so
every cached `BacktestResult` is invalidated on deploy. That is correct — the exits genuinely
changed — but it means the first scan after this ships re-runs every backtest.

**(b) The backtester — this is the one that makes the tuner honest.** Find
(`backend/app/services/strategy_backtest.py:112-114`):

```python
            if not self.position:
                sig = fn(slice_bars, direction=direction, **(params or {}))
```

Replace with, and add the resolution just above the `class _Strategy` definition
(`strategy_backtest.py:94`):

```python
    # WFO's train_fold (walk_forward.py:212) passes ONLY the search-grid combo as
    # `params` — never the `active:` block — so any exit parameter absent from the
    # grid would fall back to the Python default during tuning while the live scan
    # used the configured value. Merging the exit policy HERE (under `params`, so a
    # grid value still wins) is what keeps the tuner, the scan and the watch
    # evaluator all measuring the same exits.
    effective_params = {**get_exit(strategy), **(params or {})}

    class _Strategy(BtStrategy):
        def init(self):
            pass

        def next(self):
            # ... unchanged through `start = max(0, n - 350)` and slice_bars ...
            if not self.position:
                sig = fn(slice_bars, direction=direction, **effective_params)
```

Put `get_exit` in the existing deferred-import block at the top of the function
(`strategy_backtest.py:69-74`), alongside `from app.services.strategy_engine import (…)`, so the
module still has no import-time dependency on the param store. `run_strategy_backtest` also runs
inside `stock_scan.py`'s `_BACKTEST_POOL` (a **process** pool), so each worker process reads the
YAML once and then serves it from `strategy_param_store`'s own 60-second cache — no change needed
for that, just do not be surprised by the per-process read.

**(c) The strategy-watch evaluator** — it calls `get_active(key, …)` in two places: the primary
signal at `strategy_watch_evaluator.py:114` and the opposite-direction reversal check at `:211`.
Wrap both:

```python
                    opp_params = {**get_exit(key), **get_active(key, opposite_dir)}
                    opp_params.update(params_override)
```

```python
            adopted = {**get_exit(key), **get_active(key, wdir)}
            params_override = w.get("params_override") or {}
            adopted.update(params_override)  # params_override wins
```

Add `get_exit` to the existing `from app.services.strategy_param_store import get_active` line
(`:29`).

**(d) The composite trigger evaluator — DO NOT MODIFY IT.** An earlier draft of this plan called for
the same wrapping here, on the belief that it resolved per-strategy params "around the
`_SIGNAL_FNS`-style dispatch at lines 116-124". **It does not.** `_matched_strategy_signals`
(`composite_trigger_evaluator.py:108-145`) calls `fn(slice_bars, direction=direction)` with the
signal functions' pure Python defaults — no `get_active`, no params dict at all; lines 116-124 are a
local `_FNS` lookup table, not a param resolution. Merging `get_exit` there without `get_active`
would be incoherent, and adding `get_active` is an out-of-scope behaviour change to an evaluator
that has always deliberately used defaults.

It is also unnecessary. This evaluator asks one boolean question — "did this strategy fire in the
last few bars?" — and no exit parameter can change that answer: `_build_target_ladder` always
returns at least the fallback rung when `risk > 0`, which every signal function has already
guaranteed by the time it calls the helper, so the new `if not targets: return None` guard is
unreachable in practice. Leave the file alone and record this reasoning in the commit message.

- [ ] **Step 4: Run and commit** (plumbing only — no YAML in this commit)

```bash
cd backend && pytest tests/test_strategy_param_store.py tests/test_strategy_params.py \
  tests/test_strategy_params_config_sanity.py tests/test_strategy_backtest.py \
  tests/test_strategy_backtest_bearish.py tests/test_strategy_watch_evaluator.py \
  tests/test_strategy_param_optimizer.py -q
git add backend/app/services/strategy_param_store.py \
        backend/app/services/strategy_backtest.py backend/app/routers/stock_scan.py \
        backend/app/services/strategy_watch_evaluator.py
git commit -m "feat(config): add get_exit() and resolve the exit policy at all three consumers"
```

---

### Task 5: `pullback_ema` — prior swing extreme, then R extensions

**Files:** `backend/app/services/strategy_engine.py`, `backend/config/strategy_params.yaml`,
`backend/tests/test_strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Accept the new parameter**

Find (`strategy_engine.py:242-254`) and add one keyword to the signature, immediately after
`rr_target_mult`:

```python
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    exit_swing_lookback: int = 20,
    tolerance: float = 0.04,
```

- [ ] **Step 2: Replace both target computations with the ladder**

Find (`strategy_engine.py:288-321`), the two `target = …` lines inside the direction branches, and
**delete only those two lines** (`target = current + risk * rr_target_mult` at line 304 and
`target = current - risk * rr_target_mult` at line 321), leaving every stop/risk guard exactly as
it is. Then, immediately before the `ma_label = ma_type.upper()` line (322), insert:

```python
    # Exit thesis: "prior high / trailing stop under higher lows" — the exit the
    # Step-4 picker has always shown the user. Rung 1 is the prior swing extreme
    # the pullback interrupted; rungs 2 and 3 are R extensions past it, which is
    # where rr_target_mult now lives (it no longer sets the only target, so it is
    # no longer in the WFO grid — see the plan's coupling section).
    #
    # _swing_high/_swing_low look at bars[-lookback:], which includes today. In a
    # valid pullback today's high is at or below the prior high by construction,
    # so including it is harmless; in the edge case where the swing extreme
    # equals the entry close (or a live current_price has already exceeded it)
    # the rung rounds onto/behind entry, is dropped, and the R extensions carry
    # the ladder.
    prior_extreme = (_swing_high(bars, lookback=exit_swing_lookback) if direction == "Bullish"
                     else _swing_low(bars, lookback=exit_swing_lookback))
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=prior_extreme,
        extensions=[
            current + _sign * risk * rr_target_mult,
            current + _sign * risk * rr_target_mult * 1.5,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
```

- [ ] **Step 3: Emit the ladder on the signal**

Find (`strategy_engine.py:324-335`) and add `targets=targets,` plus a detail entry:

```python
    ma_label = ma_type.upper()
    return StrategySignal(
        strategy="pullback_ema",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        targets=targets,
        detail={
            f"{ma_label.lower()}_{ema_period}": round(fast_val, 2),
            f"{ma_label.lower()}_{trend_ema}":  round(slow_val, 2),
            "prior_swing_extreme": round(prior_extreme, 2),
        },
    )
```

- [ ] **Step 4: Fix the test that pins the old formula**

`backend/tests/test_strategy_engine.py:319-332` (`test_pullback_ema_rr_ratio_is_two_to_one`)
asserts `reward / risk ≈ 2.0`, which was true only because the target *was* `2 × risk`. It is now
the prior swing high. Replace that test with:

```python
def test_pullback_ema_targets_the_prior_swing_high():
    """Rung 1 is the prior swing extreme (the exit the Step-4 picker promises),
    not a fixed R multiple. The R extensions live on rungs 2 and 3."""
    bars = _uptrend_pullback_bars()
    signal = pullback_ema_signal(bars, tolerance=0.04)
    if signal is None:
        pytest.skip("setup did not fire on synthetic data")

    risk = signal.entry_price - signal.stop_price
    assert risk > 0, "risk must be positive (stop below entry)"
    assert signal.target_price == signal.targets[0]
    assert signal.target_price > signal.entry_price
    # Either the prior swing extreme carried rung 1, or it rounded onto entry
    # and was dropped so the 2R extension took over. Both are correct.
    prior = signal.detail["prior_swing_extreme"]
    assert signal.target_price in (
        round(prior, 2),
        round(signal.entry_price + risk * 2.0, 2),
    )
    # The full ladder is strictly increasing and nearest-first.
    assert signal.targets == sorted(signal.targets)
    assert len(set(signal.targets)) == len(signal.targets)
```

- [ ] **Step 5: Add a thesis test**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def test_pullback_ema_ladder_is_monotonic_and_starts_at_target_price():
    from tests.test_strategy_engine import _uptrend_pullback_bars
    from app.services.strategy_engine import pullback_ema_signal

    sig = pullback_ema_signal(_uptrend_pullback_bars(), tolerance=0.04)
    if sig is None:
        pytest.skip("setup did not fire on synthetic data")
    assert sig.targets and sig.targets[0] == sig.target_price
    assert all(b > a for a, b in zip(sig.targets, sig.targets[1:]))
    assert all(t > sig.entry_price for t in sig.targets)
```

- [ ] **Step 6: Run and commit**

```bash
cd backend && pytest tests/test_strategy_engine.py tests/test_strategy_engine_bearish.py \
  tests/test_strategy_exit_policies.py -q
git add backend/app/services/strategy_engine.py backend/tests/
git commit -m "feat(pullback-ema): target the prior swing extreme, with R extensions on rungs 2-3"
```

---

### Task 6: `breakout_base` — measured move off the breakout level

**Files:** `backend/app/services/strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Accept the new parameter**

Find (`strategy_engine.py:340-349`) and add after `rr_target_mult`:

```python
    volume_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    measured_move_mult: float = 1.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
```

- [ ] **Step 2: Replace both target computations**

Find (`strategy_engine.py:378-395`). Delete the two `target = …` lines (385 and 394) and leave the
stop/risk/detail assignments untouched. Then insert immediately before the `return StrategySignal(`
at line 396:

```python
    # Exit thesis: the MEASURED MOVE the Step-4 picker has always promised —
    # project the base height off the breakout LEVEL (base_high for a breakout,
    # base_low for a breakdown), not off entry. Projecting off entry would let a
    # gapping open inflate the target by the size of the gap, which is the
    # opposite of what a measured move means.
    #
    # base_high/base_low are already computed above (lines 363-364) and were
    # previously used only for the stop and the detail blob.
    base_height = base_high - base_low
    # A perfectly flat base gives height 0; one ATR is the natural stand-in for
    # "how far this thing travels". A gapping open can also put `current` above
    # anchor + height, in which case that rung is behind entry and is dropped.
    # If ATR is also 0 (degenerate data) every measured-move rung collapses onto
    # the breakout level and is dropped, leaving the rr_target_mult fallback.
    height = base_height if base_height > 0 else atr
    _sign = 1 if direction == "Bullish" else -1
    anchor = base_high if direction == "Bullish" else base_low
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=anchor + _sign * height * measured_move_mult,
        extensions=[
            anchor + _sign * height * (measured_move_mult + 0.5),
            anchor + _sign * height * (measured_move_mult + 1.0),
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
    detail["base_height"] = round(base_height, 2)
    detail["measured_move_anchor"] = round(anchor, 2)
```

- [ ] **Step 3: Emit the ladder**

In the `return StrategySignal(` block (`strategy_engine.py:396-404`) add `targets=targets,` after
`atr=round(atr, 2),`.

- [ ] **Step 4: Add thesis tests**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def _flat_base_then_breakout(base_high: float = 100.0, base_low: float = 96.0) -> list[dict]:
    """25 bars of a tight base, then a high-volume close above it."""
    bars = []
    for i in range(25):
        mid = (base_high + base_low) / 2
        bars.append({"open": mid, "high": base_high, "low": base_low,
                     "close": mid, "volume": 1_000_000})
    bars.append({"open": base_high, "high": base_high + 2, "low": base_high - 0.5,
                 "close": base_high + 1, "volume": 5_000_000})
    return bars


def test_breakout_base_rung_one_is_the_measured_move_off_the_base_high():
    from app.services.strategy_engine import breakout_base_signal

    bars = _flat_base_then_breakout()
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    height = sig.detail["base_height"]
    anchor = sig.detail["measured_move_anchor"]
    assert height == pytest.approx(4.0, abs=0.01)
    assert sig.target_price == pytest.approx(round(anchor + height, 2), abs=0.01)
    assert sig.targets[0] == sig.target_price
    # The two outward extensions survive: anchor + 1.5H and anchor + 2H.
    assert sig.targets == [round(anchor + height, 2),
                           round(anchor + height * 1.5, 2),
                           round(anchor + height * 2.0, 2)]


def test_breakout_base_survives_a_zero_height_base():
    """A perfectly flat base (base_high == base_low) must not produce a target
    at the breakout level itself — _entry_side would reject it and the strategy
    would silently stop trading."""
    from app.services.strategy_engine import breakout_base_signal
    from app.services.strategy_backtest import _entry_side

    bars = _flat_base_then_breakout(base_high=100.0, base_low=100.0)
    sig = breakout_base_signal(bars, base_lookback=20, atr_tight_max=99.0, volume_mult=1.5)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    assert sig.detail["base_height"] == 0.0
    assert _entry_side("Bullish", entry=sig.entry_price,
                       sl=sig.stop_price, tp=sig.target_price) == "buy"
```

- [ ] **Step 5: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_strategy_engine.py \
  tests/test_strategy_engine_bearish.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(breakout-base): target the measured move projected off the breakout level"
```

---

### Task 7: `ma_crossover` — ATR extension ladder plus a cross-back level

**Files:** `backend/app/services/strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Accept the new parameter**

Find (`strategy_engine.py:409-417`) and add after `lookback`:

```python
    lookback: int = 10,
    atr_target_mult: float = 3.0,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
```

- [ ] **Step 2: Replace both target computations**

Find (`strategy_engine.py:436-458`). Delete the two `target = current ± atr * 3.0` lines (443, 449)
and insert, immediately before the `return StrategySignal(` at line 450:

```python
            # A moving-average cross has no natural PRICE objective — its thesis
            # exit is a condition ("cross back"), not a level. So rung 1 keeps
            # the multiple this strategy has always used (3.0 ATR, now tunable as
            # atr_target_mult) and the ladder extends outward from there, rather
            # than inventing a nearer price target with no thesis behind it.
            # This is the one strategy whose primary target is numerically
            # unchanged by this rework — which is only true because
            # _build_target_ladder applies no R-relative floor by default. This
            # strategy's stop sits at the slow MA, so right after a fast cross
            # `risk` can be several times ATR and a 0.5R floor would exceed the
            # 3-ATR objective, dropping it and promoting the 6-ATR extension.
            _sign = 1 if direction == "Bullish" else -1
            targets = _build_target_ladder(
                entry=current, stop=stop, direction=direction,
                primary=current + _sign * atr * atr_target_mult,
                extensions=[
                    current + _sign * atr * atr_target_mult * 1.5,
                    current + _sign * atr * atr_target_mult * 2.0,
                ],
                # atr == 0 drops every rung; fall back to the R multiple the
                # other strategies use so a degenerate series still trades.
                fallback_mult=2.0,
            )
            if not targets:
                return None
            target = targets[0]
```

- [ ] **Step 3: Emit the ladder and the cross-back level**

Find (`strategy_engine.py:450-458`) and replace the `return StrategySignal(` block with:

```python
            return StrategySignal(
                strategy="ma_crossover",
                direction=direction,
                entry_price=round(current, 2),
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr=round(atr, 2),
                targets=targets,
                detail={
                    f"sma_{fast}": round(fast_ma[-1], 2),
                    f"sma_{slow}": round(slow_ma[-1], 2),
                    # The "cross back down" exit the Step-4 picker promises is a
                    # CONDITION, not a price, and evaluating it needs per-bar
                    # state this stateless signal_fn(bars) -> levels shape does
                    # not have. The level is emitted for display so the card can
                    # show it; acting on it is Approach E's job (the strategy-
                    # watch state machine), explicitly deferred by this plan.
                    "cross_back_level": round(slow_ma[-1], 2),
                    "exit_rule": "cross_back",
                },
            )
```

- [ ] **Step 4: Test**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def test_ma_crossover_primary_target_is_unchanged_at_three_atr():
    """Regression guard: this is the ONE strategy whose rung 1 must not move,
    because it has no thesis price target to move to."""
    from app.services.strategy_engine import ma_crossover_signal, _atr

    # A monotonically rising series never crosses — the fast MA is above the slow
    # MA from the first comparable bar, so ma_crossover_signal returns None and a
    # `pytest.skip` test would pass while proving nothing. Use the flat-then-step
    # shape that tests/test_strategy_params.py::_crossover_bars already relies on:
    # the cross happens on the first stepped bar, 5 bars from the end.
    bars = [{"open": 99.9, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1_000}
            for _ in range(100)]
    bars += [{"open": 199.9, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 1_000}
             for _ in range(5)]
    sig = ma_crossover_signal(bars, fast=20, slow=50, lookback=10)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    atr = _atr(bars)
    expected = round(sig.entry_price + atr * 3.0, 2)
    assert sig.target_price == pytest.approx(expected, abs=0.02)
    assert sig.detail["exit_rule"] == "cross_back"
    assert sig.detail["cross_back_level"] > 0
    # 3 / 4.5 / 6 ATR all survive: this stop sits at the slow MA, so `risk` here
    # is ~11x ATR — precisely the case an R-relative floor would have broken.
    assert len(sig.targets) == 3
    assert sig.targets[1] == pytest.approx(round(sig.entry_price + atr * 4.5, 2), abs=0.02)
    assert sig.targets[2] == pytest.approx(round(sig.entry_price + atr * 6.0, 2), abs=0.02)
```

- [ ] **Step 5: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_strategy_engine.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(ma-crossover): tunable ATR ladder plus an advisory cross-back level"
```

---

### Task 8: `mean_reversion_rsi` — return to the short-term mean

**Files:** `backend/app/services/strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Accept the new parameters**

Find (`strategy_engine.py:464-474`) and add after `trend_sma`:

```python
    trend_sma: int = 200,
    exit_sma_period: int = 20,
    atr_target_mult: float = 2.5,
    require_choppy_regime: bool = False,
```

- [ ] **Step 2: Replace both target computations**

Find (`strategy_engine.py:496-513`). Delete the two `target = current ± atr * 2.5` lines (504, 513)
and insert immediately before the `return StrategySignal(` at line 514:

```python
    # Exit thesis: "RSI returns to mid". The price proxy for that is the SHORT-term
    # mean, NOT the trend SMA. The Bullish gate above requires close > trend[-1]
    # (oversold WITHIN an uptrend), so the 200-SMA sits BELOW entry — targeting it
    # would be targeting a loss. RSI is low precisely because price is stretched
    # below its short mean, so that mean is the level the snap-back reaches for.
    short_mean_series = _sma(closes, exit_sma_period)
    short_mean = short_mean_series[-1] if short_mean_series else None
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        # None when there are fewer bars than exit_sma_period — the helper
        # ignores it and the ATR extensions carry the ladder.
        primary=short_mean,
        extensions=[
            current + _sign * atr * atr_target_mult,
            current + _sign * atr * atr_target_mult * 1.5,
        ],
        fallback_mult=2.0,
    )
    if not targets:
        return None
    target = targets[0]
```

- [ ] **Step 3: Emit the ladder and the mean**

Find (`strategy_engine.py:514-522`) and add `targets=targets,` after `atr=round(atr, 2),`, plus a
detail entry:

```python
        detail={
            "rsi": round(rsi[-1], 1),
            f"sma_{trend_sma}": round(trend[-1], 2),
            **({f"sma_{exit_sma_period}": round(short_mean, 2)} if short_mean is not None else {}),
        },
```

- [ ] **Step 4: Test**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def test_mean_reversion_rsi_never_targets_the_trend_sma():
    """The 200-SMA is BELOW entry on a bullish fire (oversold in an uptrend);
    targeting it would be targeting a loss. Rung 1 must be above entry."""
    from app.services.strategy_engine import mean_reversion_rsi_signal

    # A STEEP long uptrend, then a short sharp dip that drives RSI under 30 while
    # price stays comfortably above the 200-SMA, with the final bar ticking back
    # up so the "RSI recovering" gate passes.
    #
    # The slope and the dip depth are both load-bearing: with a shallow ramp
    # (0.12/bar) and an 8-bar dip the close lands BELOW the 200-SMA, the uptrend
    # gate rejects, and the signal never fires — an earlier draft of this test
    # used exactly those numbers and silently skipped every run. If this ever
    # starts skipping again, fix the fixture, do not relax the test.
    closes = [50 + i * 0.45 for i in range(260)]
    closes += [closes[-1] - 2.5 * (i + 1) for i in range(4)]
    closes += [closes[-1] + 0.5]
    bars = [{"open": c, "high": c + 0.4, "low": c - 0.4, "close": c, "volume": 1_000_000}
            for c in closes]
    sig = mean_reversion_rsi_signal(bars, rsi_period=14, rsi_oversold=30, trend_sma=200)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    trend_sma_val = sig.detail["sma_200"]
    assert sig.entry_price > trend_sma_val, "bullish gate: entry is above the trend SMA"
    assert sig.target_price > sig.entry_price
    assert sig.target_price > trend_sma_val
    assert sig.targets[0] == sig.target_price
    # Rung 1 is the SHORT-term mean, and the detail dict reports it.
    assert sig.target_price == pytest.approx(sig.detail["sma_20"], abs=0.02)
```

- [ ] **Step 5: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_strategy_engine.py \
  tests/test_strategy_engine_bearish.py tests/test_mean_reversion_multi.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(mr-rsi): target the short-term mean, never the trend SMA"
```

---

### Task 9: `mean_reversion_bb` — mid-band, then the opposite band

**Files:** `backend/app/services/strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: Replace both target computations**

The signature needs no new parameter — the levels are fully determined by `bb_period`/`bb_std`,
which are already in `active:` **and** `search:`. Find (`strategy_engine.py:566-593`), delete the two
`target = current ± risk * rr_target_mult` lines (579, 593), and insert immediately before the
`return StrategySignal(` at line 595:

```python
    # Exit thesis: "return to mid-band / opposite band" — literally what the
    # Step-4 picker tells the user, and both levels are already computed above at
    # line 553 (`upper, mid, lower = _bollinger(closes, bb_period, bb_std)`).
    #
    # The entry gates guarantee the mid-band is on the profitable side: Bullish
    # requires lower[-1] < current < mid[-1] (lines 571-574), Bearish requires
    # mid[-1] < current < upper[-1] (lines 585-588). So the primary is always
    # valid unless a squeeze puts the mid within half a cent of entry, in which
    # case it rounds onto entry, is dropped, and the opposite band leads.
    #
    # Note the 2R extension is deliberately an EXTENSION, not a co-equal rung:
    # with stop_atr_mult 0.5 the risk here is small, so entry + 2R is routinely
    # NEARER than the mid-band. Pooling and sorting would make an arbitrary R
    # multiple the target again, which is exactly what this rework removes.
    _sign = 1 if direction == "Bullish" else -1
    opposite_band = upper[-1] if direction == "Bullish" else lower[-1]
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=mid[-1],
        extensions=[
            opposite_band,
            current + _sign * risk * rr_target_mult,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
```

- [ ] **Step 2: Emit the ladder**

Add `targets=targets,` after `atr=round(atr, 2),` in the `return StrategySignal(` block
(`strategy_engine.py:595-608`). The `detail` dict already carries `bb_upper`, `bb_mid` and
`bb_lower`; leave it unchanged.

- [ ] **Step 3: Test**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def test_mean_reversion_bb_targets_the_real_mid_band_then_the_opposite_band():
    """Rung 1 must equal the mid-band the signal itself reports in detail, and
    rung 2 the opposite band — not an R multiple that happens to be nearby."""
    from app.services.strategy_engine import mean_reversion_bb_signal

    # Deterministic (no `random`): a steady uptrend well above its 200-SMA, then
    # a two-bar dip whose FIRST bar's low tags the lower band and whose second
    # bar closes back inside the band but still under the midline — the exact
    # three gates at strategy_engine.py:569-574. Tune the two dip magnitudes
    # until the signal fires; do not settle for a skip.
    closes = [80 + i * 0.09 for i in range(240)]
    closes += [closes[-1] - 3.2, closes[-1] - 3.2 + 1.8]
    bars = [{"open": c, "high": c + 0.5, "low": c - 1.2, "close": c, "volume": 1_000_000}
            for c in closes]
    sig = mean_reversion_bb_signal(bars, bb_period=20, bb_std=2.0, trend_sma=200)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"

    mid = sig.detail["bb_mid"]
    upper = sig.detail["bb_upper"]
    # Rung 1 IS the mid-band the signal itself reports — not an R multiple that
    # happens to be nearby, and not the opposite band.
    assert sig.target_price == pytest.approx(mid, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert sig.targets[1] == pytest.approx(upper, abs=0.02)
    assert all(t > sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets)
```

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_strategy_engine.py \
  tests/test_strategy_engine_bearish.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(mr-bb): target the mid-band then the opposite band, both already computed"
```

---

### Task 10: The two VWAP variants — VWAP itself, and the symmetric overshoot

**Files:** `backend/app/services/strategy_engine.py`, `backend/tests/test_strategy_exit_policies.py`

- [ ] **Step 1: `mean_reversion_vwap` (intraday) — VWAP, then an ATR extension past it**

Add `vwap_extension_atr: float = 0.5,` to the signature after `rr_target_mult`
(`strategy_engine.py:619`). Then find (`strategy_engine.py:642-665`), delete the two
`target = current ± risk * rr_target_mult` lines (653, 665), and insert before the
`return StrategySignal(` at line 667:

```python
    # Exit thesis: VWAP itself, then an extension past it. Valid here — and ONLY
    # here — because this variant's entry gate requires price to still be
    # DEVIATED from VWAP by vwap_dev_pct (lines 643-645 / 655-657), so VWAP sits
    # on the profitable side of entry. Its daily sibling has the opposite gate;
    # see below.
    #
    # This is THE strategy that proves why `primary` must be a separate argument:
    # the gate puts VWAP at least vwap_dev_pct (1.5%) away, while
    # risk = stop_atr_mult * atr (0.5 ATR on 15-minute bars). `entry + 2R` is
    # therefore almost always NEARER than VWAP, and a pooled nearest-first sort
    # would silently make an arbitrary 1-ATR multiple the target again — leaving
    # this strategy's exits exactly as they were before the rework.
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=vwap,
        extensions=[
            vwap + _sign * atr * vwap_extension_atr,
            current + _sign * risk * rr_target_mult,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
```

Add `targets=targets,` to that function's `return StrategySignal(` block.

- [ ] **Step 2: `mean_reversion_vwap_daily` — the symmetric overshoot**

Find (`strategy_engine.py:709-730`), delete the two `target = current ± risk * rr_target_mult`
lines (718, 728), and insert immediately after the existing `dev_pct = abs(vwap - prev) / vwap` line
(730):

```python
    dev_pct = abs(vwap - prev) / vwap
    # Exit thesis: a RECLAIM-and-overshoot, NOT "return to VWAP".
    #
    # This variant's Bullish gate is `current > vwap` (line 712) — the bar has
    # already closed back ABOVE the rolling VWAP, so VWAP is BELOW entry and the
    # "return to VWAP" target is achieved at entry. What the thesis actually says
    # is that a deviation of dev_pct below VWAP should mean-revert to a mirror
    # deviation above it. That mirror level is rung 1; R extensions follow.
    _sign = 1 if direction == "Bullish" else -1
    targets = _build_target_ladder(
        entry=current, stop=stop, direction=direction,
        primary=vwap * (1 + _sign * dev_pct),
        extensions=[
            current + _sign * risk * rr_target_mult,
            current + _sign * risk * rr_target_mult * 1.5,
        ],
        fallback_mult=rr_target_mult,
    )
    if not targets:
        return None
    target = targets[0]
```

Add `targets=targets,` to that function's `return StrategySignal(` block.

- [ ] **Step 3: Test both**

Append to `backend/tests/test_strategy_exit_policies.py`:

```python
def test_mean_reversion_vwap_intraday_rung_one_is_vwap_itself():
    from app.services.strategy_engine import mean_reversion_vwap_signal

    # 40 flat bars establishing VWAP near 100, then a drop to ~97 with the final
    # bar ticking back up toward it.
    bars = [{"open": 100, "high": 100.3, "low": 99.7, "close": 100, "volume": 10_000}
            for _ in range(40)]
    bars.append({"open": 97.5, "high": 97.6, "low": 96.9, "close": 97.0, "volume": 10_000})
    bars.append({"open": 97.0, "high": 97.9, "low": 97.0, "close": 97.8, "volume": 10_000})
    sig = mean_reversion_vwap_signal(bars, vwap_dev_pct=1.5, reversal_pct=0.3, interval="15m")
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    vwap = sig.detail["vwap"]
    # Rung 1 IS VWAP. This assertion is the regression guard for the pooled-sort
    # bug: here `entry + 2R` (~1 ATR) is nearer than VWAP (>=1.5% away), so a
    # nearest-first pool would put the R multiple first and this would fail.
    assert sig.target_price == pytest.approx(vwap, abs=0.02)
    assert sig.targets[0] == sig.target_price
    assert all(t > sig.entry_price for t in sig.targets)
    assert sig.targets == sorted(sig.targets)


def test_mean_reversion_vwap_daily_never_targets_vwap_itself():
    """Its gate is `close > vwap`, so VWAP is BEHIND entry — a VWAP target would
    be a target already achieved (and would be rejected by _entry_side)."""
    from app.services.strategy_engine import mean_reversion_vwap_daily_signal
    from app.services.strategy_backtest import _entry_side

    bars = [{"open": 100, "high": 101, "low": 99, "close": 100, "volume": 10_000}
            for _ in range(22)]
    bars.append({"open": 98, "high": 98.5, "low": 97, "close": 97.5, "volume": 10_000})
    bars.append({"open": 97.5, "high": 101.5, "low": 97.5, "close": 101.0, "volume": 10_000})
    sig = mean_reversion_vwap_daily_signal(bars, vwap_lookback=20, vwap_deviation_pct=0.02)
    assert sig is not None, "fixture must fire — a skipping thesis test proves nothing"
    vwap = sig.detail["rolling_vwap"]
    assert sig.target_price > sig.entry_price > vwap
    # Rung 1 is the MIRROR of the entry deviation, not VWAP itself.
    dev_frac = sig.detail["deviation_pct"] / 100.0
    assert sig.target_price == pytest.approx(round(vwap * (1 + dev_frac), 2), abs=0.02)
    assert _entry_side("Bullish", entry=sig.entry_price,
                       sl=sig.stop_price, tp=sig.target_price) == "buy"
```

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_strategy_exit_policies.py tests/test_mean_reversion_multi.py -q
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_exit_policies.py
git commit -m "feat(mr-vwap): VWAP target intraday, symmetric-overshoot target on the daily variant"
```

---

### Task 11: `mean_reversion_multi` — deterministic, order-independent resolution

**Files:** `backend/app/services/strategy_engine.py`, `backend/app/routers/stock_scan.py`,
`backend/tests/test_mean_reversion_multi.py`

- [ ] **Step 1: Add `resolve_multi_signal()` to the strategy engine**

Append to `backend/app/services/strategy_engine.py`, after the `mean_reversion_vwap_daily_signal`
function and before the `# ── Strategy 7: Pre-breakout` banner:

```python
# ── Multi-signal resolution ──────────────────────────────────────────────────

def resolve_multi_signal(
    fired: list[StrategySignal],
    *,
    strategy: str = "mean_reversion_multi",
    fallback_mult: float = 2.0,
) -> StrategySignal | None:
    """Combine several confirming variant signals into one, deterministically.

    Replaces ``dataclasses.replace(fired[0], ...)``, which took its entry, stop
    and target from whichever variant the CALLER happened to list first. That is
    not non-deterministic — the same request always produced the same answer —
    but it is arbitrary: reordering the variant checkboxes in the UI silently
    moved every stop and every target. This function's answer depends only on the
    SET of fired variants, never on their order.

    Resolution rule (the conservative pairing):
      * stop   = the WIDEST of the variants' stops (furthest from entry). If any
                 one variant's invalidation has not been hit, the thesis is
                 intact, so the position should not already be stopped out.
      * ladder = every variant's rungs pooled as ``extensions`` (there is no
                 ``primary`` here — no single variant's objective outranks
                 another's) and re-sanitized against the resolved entry/stop,
                 which yields the TIGHTEST surviving rung first. Taking the
                 tightest target with the widest stop is deliberately the low-R:R
                 pairing: for a multi-confirmation entry the edge is the
                 confirmation count, not the R:R, and the alternative (tight stop
                 + far target) would flatter the numbers by pairing two levels no
                 single variant ever claimed together.
      * entry  = the anchor variant's. All variants that can appear here read the
                 same last close, so entries agree; the anchor is chosen by
                 alphabetical strategy name purely so the tie-break is stable.

    This is the ONE caller that passes a non-zero ``min_rung_r``. Everywhere else
    a rung is the strategy's own objective measured against its own stop, and the
    ladder builder deliberately does not second-guess it. Here a rung derived
    against one variant's tight stop is being re-used against a stop that may be
    many times wider, so a 0.6R target can become a 0.06R target that no variant
    ever proposed. Half an R is the floor for a rung to survive that transplant.

    KNOWN LIMITATION, recorded rather than hidden: nothing backtests this
    resolution. ``stock_scan.py`` deliberately uses ``mean_reversion_rsi`` as the
    canonical backtest proxy for ``mean_reversion_multi`` (so the gate is
    order-independent), which means the RSI variant's own ladder is what the
    Step-6 win rate measures, not the resolved one. That predates this plan and
    is unchanged by it; it is why the resolution rule is chosen to be
    conservative rather than optimised.

    Returns None when ``fired`` is empty or the resolved risk is non-positive.
    """
    if not fired:
        return None

    ordered = sorted(fired, key=lambda s: s.strategy)
    anchor = ordered[0]
    direction = anchor.direction
    entry = anchor.entry_price

    if direction == "Bullish":
        stop = min(s.stop_price for s in ordered)
    else:
        stop = max(s.stop_price for s in ordered)

    if abs(entry - stop) <= 0:
        return None

    pooled: list[float] = []
    for s in ordered:
        pooled.extend(s.targets or [s.target_price])

    targets = _build_target_ladder(
        entry=entry, stop=stop, direction=direction,
        primary=None, extensions=pooled,
        fallback_mult=fallback_mult, min_rung_r=0.5,
    )
    if not targets:
        return None

    detail = {
        **anchor.detail,
        "confirmations": len(ordered),
        # Sorted, so this field is order-independent too — it was previously the
        # caller's request order.
        "fired": [s.strategy for s in ordered],
        "resolution": "widest_stop_tightest_target",
    }

    return StrategySignal(
        strategy=strategy,
        direction=direction,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        target_price=targets[0],
        atr=anchor.atr,
        targets=targets,
        detail=detail,
    )
```

- [ ] **Step 2: Use it in the scan router**

Find (`backend/app/routers/stock_scan.py:763-769`):

```python
                if len(fired) < req.mean_reversion_min_confirmations:
                    return {"symbol": symbol, "reason": f"no mean_reversion_multi: {len(fired)}/{len(valid_variants)} signals fired"}
                signal = dataclasses.replace(
                    fired[0],
                    strategy="mean_reversion_multi",
                    detail={**fired[0].detail, "confirmations": len(fired), "fired": [s.strategy for s in fired]},
                )
```

Replace with:

```python
                if len(fired) < req.mean_reversion_min_confirmations:
                    return {"symbol": symbol, "reason": f"no mean_reversion_multi: {len(fired)}/{len(valid_variants)} signals fired"}
                # Order-independent resolution: widest stop, tightest target,
                # pooled ladder. Previously this took fired[0]'s levels verbatim,
                # so reordering the variant checkboxes changed every level.
                signal = resolve_multi_signal(fired, strategy="mean_reversion_multi")
                if signal is None:
                    return {"symbol": symbol, "reason": "mean_reversion_multi: variants produced no valid combined levels"}
```

Add `resolve_multi_signal` to the `from app.services.strategy_engine import (…)` block at
`stock_scan.py:38-45`. `dataclasses` stays imported — `dataclasses.replace(card, status="CAUTION")`
at line 845 still uses it (verified).

Leave the `_bt_strategy = "mean_reversion_rsi"` proxy and its comment exactly as they are: the
backtest gate for multi is deliberately measured against the RSI variant so that it, too, is
order-independent. Note in the commit message that this means the resolved multi ladder is not
itself backtested — see `resolve_multi_signal`'s KNOWN LIMITATION note.

- [ ] **Step 3: Test order-independence**

Append to `backend/tests/test_mean_reversion_multi.py`:

```python
def test_resolve_multi_signal_is_order_independent():
    """The bug this replaces: fired[0] made the answer depend on the order the
    caller listed the variants in."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=96.0, target_price=108.0,
                       atr=2.0, targets=[108.0, 114.0])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bullish",
                       entry_price=100.0, stop_price=94.0, target_price=105.0,
                       atr=2.0, targets=[105.0, 111.0])

    first = resolve_multi_signal([a, b])
    second = resolve_multi_signal([b, a])
    assert first == second
    # Widest stop wins (94, not 96).
    assert first.stop_price == 94.0
    # Tightest surviving rung leads. risk = 6, floor = entry + 0.5R = 103.
    assert first.target_price == 105.0
    assert first.targets[0] == first.target_price
    assert first.detail["fired"] == ["mean_reversion_bb", "mean_reversion_rsi"]


def test_resolve_multi_signal_bearish_widest_stop_is_the_highest():
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bearish",
                       entry_price=100.0, stop_price=104.0, target_price=92.0,
                       atr=2.0, targets=[92.0])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bearish",
                       entry_price=100.0, stop_price=106.0, target_price=95.0,
                       atr=2.0, targets=[95.0])
    out = resolve_multi_signal([a, b])
    assert out.stop_price == 106.0
    assert out.target_price == 95.0     # tightest, and outside the 0.5R floor (97)
    assert all(t < out.entry_price for t in out.targets)


def test_resolve_multi_signal_drops_rungs_inside_the_widened_floor():
    """Widening the stop widens the 0.5R floor this caller passes, which can
    invalidate a rung that was fine against a variant's own tighter stop. That
    must not produce a target at or behind entry, and must not let a rung no
    variant ever proposed against THIS stop become the target."""
    from app.services.strategy_engine import StrategySignal, resolve_multi_signal
    from app.services.strategy_backtest import _entry_side

    a = StrategySignal(strategy="mean_reversion_bb", direction="Bullish",
                       entry_price=100.0, stop_price=99.0, target_price=100.6,
                       atr=1.0, targets=[100.6])
    b = StrategySignal(strategy="mean_reversion_rsi", direction="Bullish",
                       entry_price=100.0, stop_price=90.0, target_price=112.0,
                       atr=1.0, targets=[112.0])
    out = resolve_multi_signal([a, b])
    assert out.stop_price == 90.0
    assert out.target_price == 112.0    # 100.6 is inside the 5.0 floor, dropped
    assert _entry_side("Bullish", entry=out.entry_price,
                       sl=out.stop_price, tp=out.target_price) == "buy"


def test_resolve_multi_signal_returns_none_on_empty():
    from app.services.strategy_engine import resolve_multi_signal
    assert resolve_multi_signal([]) is None
```

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_mean_reversion_multi.py tests/test_strategy_exit_policies.py -q
git add backend/app/services/strategy_engine.py backend/app/routers/stock_scan.py \
        backend/tests/test_mean_reversion_multi.py
git commit -m "fix(mr-multi): replace order-dependent fired[0] levels with deterministic resolution"
```

---

### Task 12: Realign the WFO `search:` grids and record the re-tune expectation

**Files:** `backend/config/strategy_params.yaml`, `backend/tests/test_strategy_params_config_sanity.py`

- [ ] **Step 1: Apply the grid changes**

Edit `backend/config/strategy_params.yaml` exactly as the coupling table in the Background section
specifies. Concretely:

```yaml
  pullback_ema:
    active:
      bullish:
        ema_period: 50
        trend_ema: 100
        atr_stop_mult: 1.5
        rr_target_mult: 2.0          # rungs 2-3 only; also in exit: so adopt() can't drop it
        tolerance: 0.04
        exit_swing_lookback: 20
      bearish:
        ema_period: 35
        trend_ema: 100
        atr_stop_mult: 1.5
        rr_target_mult: 2.0
        tolerance: 0.04
        exit_swing_lookback: 20
    exit:
      exit_swing_lookback: 20
      rr_target_mult: 2.0
    search:
      ema_period: [20, 35, 50]
      trend_ema: [100, 150, 200]
      atr_stop_mult: [1.0, 1.5, 2.0]
      # rr_target_mult REMOVED from the grid: it no longer influences
      # target_price (= ladder[0], now the prior swing extreme), and
      # strategy_backtest can only observe ladder[0]. Tuning it here would let
      # consensus() write a median of pure noise into active:.
      exit_swing_lookback: [10, 20, 30]
      tolerance: [0.02, 0.04, 0.06, 0.08]

  breakout_base:
    active:
      bullish:
        base_lookback: 20
        atr_tight_max: 4.0
        volume_mult: 1.5
        rr_target_mult: 2.0          # degenerate-case fallback only
        measured_move_mult: 1.0
      bearish:
        base_lookback: 20
        atr_tight_max: 4.0
        volume_mult: 1.5
        rr_target_mult: 2.0
        measured_move_mult: 1.0
    exit:
      measured_move_mult: 1.0
      rr_target_mult: 2.0
    search:
      base_lookback: [15, 20, 30]
      atr_tight_max: [3.0, 3.5, 4.0, 4.5]
      volume_mult: [1.1, 1.3, 1.5]
      # rr_target_mult REMOVED (see pullback_ema); replaced by the parameter
      # that actually sets rung 1. Same combo count as before.
      measured_move_mult: [0.75, 1.0, 1.25, 1.5]

  ma_crossover:
    active:
      bullish:
        fast: 20
        slow: 50
        lookback: 10
        atr_target_mult: 3.0
      bearish:
        fast: 20
        slow: 50
        lookback: 10
        atr_target_mult: 3.0
    exit:
      atr_target_mult: 3.0
    search:
      fast: [10, 20]
      slow: [50, 100]
      lookback: [5, 10]
      # Newly tunable: this multiple was hardcoded at 3.0 in the signal function
      # and does set rung 1, so the tuner can now see it.
      atr_target_mult: [2.0, 3.0, 4.0]

  mean_reversion_rsi:
    active:
      bullish:
        rsi_period: 14
        rsi_oversold: 30
        trend_sma: 200
        require_choppy_regime: false
        exit_sma_period: 20
        atr_target_mult: 2.5         # scales rung 2 only — not in the grid
      bearish:
        rsi_period: 14
        rsi_oversold: 30
        trend_sma: 200
        require_choppy_regime: false
        exit_sma_period: 20
        atr_target_mult: 2.5
    exit:
      exit_sma_period: 20
      atr_target_mult: 2.5
    search:
      rsi_period: [7, 14]
      rsi_oversold: [25, 30, 35]
      trend_sma: [100, 200]
      exit_sma_period: [10, 20]      # sets rung 1

  mean_reversion_bb:
    # active: unchanged (rr_target_mult: 2.0 stays, now scaling rung 3)
    exit:
      rr_target_mult: 2.0
    search:
      bb_period: [15, 20, 25]
      bb_std: [1.5, 2.0, 2.5]
      trend_sma: [100, 200]
      stop_atr_mult: [0.2, 0.5, 1.0]
      # rr_target_mult REMOVED with NO replacement: rung 1 is the mid-band,
      # already fully determined by bb_period/bb_std, which are in the grid
      # above and now genuinely drive the exit as well as the entry.

  mean_reversion_vwap:
    active:
      bullish:
        vwap_dev_pct: 1.5
        reversal_pct: 0.3
        stop_atr_mult: 0.5
        rr_target_mult: 2.0
        interval: '15m'
        vwap_extension_atr: 0.5
      bearish:
        vwap_dev_pct: 1.5
        reversal_pct: 0.3
        stop_atr_mult: 0.5
        rr_target_mult: 2.0
        interval: '15m'
        vwap_extension_atr: 0.5
    exit:
      vwap_extension_atr: 0.5
      rr_target_mult: 2.0
    # still no search block — intraday-only; excluded from WFO

  mean_reversion_vwap_daily:
    # No active:/search: — this variant is only reachable through
    # mean_reversion_multi, which supplies vwap_lookback/vwap_deviation_pct from
    # the request. It gets an exit: block so its ladder is configurable.
    exit:
      rr_target_mult: 2.0
```

`ma_crossover` and `mean_reversion_rsi` are written with block mappings rather than the flow-style
`{ … }` the plan draft used, so the file stays consistent with the rest of `strategies:` — and
because `adopt()` will rewrite them as block mappings anyway.

> **Critical:** `test_strategy_params_config_sanity.py` asserts every `active.<direction>.<key>` that
> also appears in `search` is one of the searched values. So every value added to `active:` above
> **must** appear in its own grid when a grid entry exists — `exit_swing_lookback: 20` ∈ `[10,20,30]`
> ✓, `measured_move_mult: 1.0` ∈ `[0.75,1.0,1.25,1.5]` ✓, `atr_target_mult: 3.0` ∈ `[2.0,3.0,4.0]` ✓,
> `exit_sma_period: 20` ∈ `[10,20]` ✓. Run that test as the first check of Step 3.

- [ ] **Step 2: Record the re-tune expectation in the config itself**

Add at the top of `backend/config/strategy_params.yaml`, above `windows:`. **Caveat, stated so it is
not mistaken for a durable record:** `strategy_param_store.adopt()` rewrites this file with
`yaml.safe_dump`, which destroys every comment in it — so this note survives only until the first
tuner adopt. It is still worth writing (it will be read by whoever looks at the file before the next
adopt), but the durable copies are this plan and `get_exit()`'s docstring.

```yaml
# NOTE (2026-08-22, stock exit-targets rework): every `active:` value below was
# selected by the WFO tuner under the PREVIOUS exit formula, where target_price
# was a uniform `entry +/- risk * rr_target_mult` (or a fixed ATR multiple) for
# six of seven strategies. Targets are now strategy-specific (measured move,
# mid-band, prior swing extreme, VWAP, short-term mean), so `strategy_backtest`
# measures a different `tp=` and these values are no longer the tuner's answer to
# the current question. RE-RUNNING THE TUNER (Settings -> Strategy Tuning) IS AN
# EXPECTED, INTENDED CONSEQUENCE of that rework, not a symptom of a problem.
# Historical win rates and expectancies shown in step-6-backtest will also move
# (win rate up, average win down) for the same reason.
```

- [ ] **Step 3: Add a grid-hygiene test**

Append to `backend/tests/test_strategy_params_config_sanity.py`:

```python
# Parameters that, by design, influence only ladder rungs 2-3 and therefore
# CANNOT be observed by strategy_backtest (which only sees target_price =
# ladder[0]). Keeping one in a search grid makes the WFO tuner spend compute
# distinguishing identical backtests and then write a median of noise into
# active: — see docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md.
_RUNG_2_3_ONLY = {
    "pullback_ema":       {"rr_target_mult"},
    "breakout_base":      {"rr_target_mult"},
    "mean_reversion_bb":  {"rr_target_mult"},
    "mean_reversion_rsi": {"atr_target_mult"},
    "mean_reversion_vwap": {"rr_target_mult", "vwap_extension_atr"},
}


def test_no_backtest_invisible_param_is_in_a_search_grid():
    strategies = _load_strategies()
    violations = []
    for strat_name, keys in _RUNG_2_3_ONLY.items():
        search = strategies.get(strat_name, {}).get("search") or {}
        for key in keys & set(search):
            violations.append(f"{strat_name}.search.{key}")
    assert not violations, (
        "These params only affect exit-ladder rungs 2-3, which the backtest "
        "cannot observe, so tuning them produces noise:\n" + "\n".join(violations)
    )


def test_rung_2_3_params_survive_a_tuner_adopt():
    """adopt() replaces active[direction] wholesale with the winning grid combo,
    so a param that is not in search: is DELETED from active: on the first adopt
    and silently reverts to the signal function's Python default. exit: is never
    rewritten by adopt(), so every such param must be mirrored there."""
    strategies = _load_strategies()
    missing = []
    for strat_name, keys in _RUNG_2_3_ONLY.items():
        exit_block = strategies.get(strat_name, {}).get("exit") or {}
        for key in sorted(keys - set(exit_block)):
            missing.append(f"{strat_name}.exit.{key}")
    assert not missing, (
        "Rung-2/3 params absent from their exit: block — a tuner adopt would "
        "erase them from active: with no durable fallback:\n" + "\n".join(missing)
    )


def test_every_exit_block_key_is_accepted_by_its_signal_function():
    """An `exit:` key the signal function does not accept becomes a TypeError on
    the first scan, because active:/exit: values are splatted straight in."""
    import inspect
    from app.services import strategy_engine

    fn_for = {
        "pullback_ema":              strategy_engine.pullback_ema_signal,
        "breakout_base":             strategy_engine.breakout_base_signal,
        "ma_crossover":              strategy_engine.ma_crossover_signal,
        "mean_reversion_rsi":        strategy_engine.mean_reversion_rsi_signal,
        "mean_reversion_bb":         strategy_engine.mean_reversion_bb_signal,
        "mean_reversion_vwap":       strategy_engine.mean_reversion_vwap_signal,
        "mean_reversion_vwap_daily": strategy_engine.mean_reversion_vwap_daily_signal,
    }
    violations = []
    for strat_name, strat_cfg in _load_strategies().items():
        fn = fn_for.get(strat_name)
        if fn is None:
            continue
        accepted = set(inspect.signature(fn).parameters)
        for block in ("exit", "active"):
            cfg = strat_cfg.get(block) or {}
            entries = cfg.values() if block == "active" and any(
                k in cfg for k in ("bullish", "bearish")) else [cfg]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                for key in entry:
                    if key not in accepted:
                        violations.append(f"{strat_name}.{block}.{key}")
    assert not violations, (
        "Config keys not accepted by their signal function (TypeError on the "
        "next scan):\n" + "\n".join(sorted(set(violations)))
    )
```

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_strategy_params_config_sanity.py tests/test_strategy_params.py \
  tests/test_strategy_param_optimizer.py tests/test_strategy_basket.py -q
git add backend/config/strategy_params.yaml backend/tests/test_strategy_params_config_sanity.py
git commit -m "chore(wfo): realign search grids to params the backtest can actually observe"
```

---

### Task 13: Surface the ladder to the frontend and retire the client-side 2R/3R

**Files:** `backend/app/schemas/stock_scan.py`, `backend/app/routers/stock_scan.py`,
`frontend/types/stockDomain.ts`, `frontend/components/organisms/StockPositionCard/index.tsx`,
`frontend/app/(frame)/screener/step-4-stocks/page.tsx`

- [ ] **Step 1: Add `targets` to the API schema**

Find (`backend/app/schemas/stock_scan.py:83-91`):

```python
class StrategySignalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy:     str
    entry_price:  float
    stop_price:   float
    target_price: float
    rr_ratio:     float
    atr:          float
    detail:       dict
```

Replace with:

```python
class StrategySignalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    strategy:     str
    entry_price:  float
    stop_price:   float
    target_price: float
    #: Full nearest-first exit ladder; targets[0] == target_price. Defaults to []
    #: so a scan result deserialized from an older persisted session still
    #: validates.
    targets:      list[float] = Field(default_factory=list)
    rr_ratio:     float
    atr:          float
    detail:       dict
```

- [ ] **Step 2: Populate it at both construction sites**

`stock_scan.py` builds `StrategySignalOut` in `_process_stock` (line 883-887) and again in the
analysis path (`_analyze_core`, grep for the second `StrategySignalOut(`). Add `targets=signal.targets,`
after `target_price=signal.target_price,` at **both**.

- [ ] **Step 3: Add the optional field to the frontend type**

Find (`frontend/types/stockDomain.ts:4-7`):

```typescript
export interface StrategySignalData {
  strategy: string; entry_price: number; stop_price: number;
  target_price: number; rr_ratio: number; atr: number; detail: Record<string, unknown>;
}
```

Replace with:

```typescript
export interface StrategySignalData {
  strategy: string; entry_price: number; stop_price: number;
  target_price: number; rr_ratio: number; atr: number; detail: Record<string, unknown>;
  /** Backend-computed nearest-first exit ladder; `targets[0] === target_price`.
   *  OPTIONAL, and it must stay optional: `scanStore` persists `stockScanResult`
   *  to localStorage (`bamendjou-scan-store`, version 12), so a result saved
   *  before this field existed rehydrates without it. Every read site falls back
   *  to `[target_price]`, which is why no store version bump / migration is
   *  needed here. */
  targets?: number[];
}
```

- [ ] **Step 4: Seed the overlay from the backend ladder**

Find (`frontend/components/organisms/StockPositionCard/index.tsx:43-56`):

```typescript
function defaultOverlay(card: PositionCardData): StockEditOverlay {
  const entry = card.strategy.entry_price;
  const stop  = card.strategy.stop_price;
  const risk  = Math.abs(entry - stop);
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  const t1    = card.strategy.target_price;
  const t2    = Math.round((entry + sign * 2 * risk) * 100) / 100;
  const t3    = Math.round((entry + sign * 3 * risk) * 100) / 100;
  const s     = card.shares;
  const s1    = Math.floor(s / 3);
  const s2    = Math.floor(s / 3);
  return { entry, stop, shares: s, t1, t2, t3, sharesT1: s1, sharesT2: s2, sharesT3: s - s1 - s2 };
}
```

Replace with:

```typescript
function defaultOverlay(card: PositionCardData): StockEditOverlay {
  const entry = card.strategy.entry_price;
  const stop  = card.strategy.stop_price;
  const risk  = Math.abs(entry - stop);
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  // T2/T3 used to be invented here as a flat 2R/3R — not strategy-derived, not
  // validated by any backtest, and invisible to the WFO tuner. They now come
  // from the backend ladder, which is built from each strategy's own exit
  // thesis. The R-step fill survives only as the fallback for a scan result
  // rehydrated from localStorage before `targets` existed (`?.length`, not
  // `??`: an empty array must fall back too).
  const round2 = (v: number) => Math.round(v * 100) / 100;
  const ladder = card.strategy.targets?.length
    ? card.strategy.targets
    : [card.strategy.target_price];
  // Missing rungs are filled by stepping ONE MORE R past the previous rung, not
  // by measuring 2R/3R from entry. Measuring from entry can place T2 nearer than
  // a strategy-derived T1 (a prior swing high 4R away leaves T2 = 2R behind it),
  // and stockPositionLevels() sorts the ladder nearest-first on the way into the
  // portfolio — so the persisted targets[0], which is the ONLY rung TP_HIT
  // fires on, would not be the rung the card showed as T1.
  const t1 = round2(ladder[0] ?? card.strategy.target_price);
  const t2 = round2(ladder[1] ?? t1 + sign * risk);
  const t3 = round2(ladder[2] ?? t2 + sign * risk);
  const s     = card.shares;
  const s1    = Math.floor(s / 3);
  const s2    = Math.floor(s / 3);
  return { entry, stop, shares: s, t1, t2, t3, sharesT1: s1, sharesT2: s2, sharesT3: s - s1 - s2 };
}
```

- [ ] **Step 5: Correct the Step-4 exit copy so it matches the code**

Find `frontend/app/(frame)/screener/step-4-stocks/page.tsx:40-58` and update only the `exit:` strings
so the picker describes what the code now actually does. The two `stop:` strings for `pullback_ema`
are also wrong today ("Below recent swing low" — the stop is `fast MA − ATR × atr_stop_mult`); fix
those in the same pass.

`STRATEGIES_BULLISH`:

| key | new `stop:` | new `exit:` |
|---|---|---|
| `pullback_ema` | `Below the pullback MA by 1.5 ATR` | `Prior swing high, then 2R / 3R extensions` |
| `breakout_base` | `Below the base low` | `Measured move — base height projected off the breakout` |
| `ma_crossover` | `Below 50-SMA` | `3 / 4.5 / 6 ATR ladder (cross-back level shown)` |
| `mean_reversion_rsi` | `Below recent swing low` | `Return to the 20-SMA, then 2.5 / 3.75 ATR` |
| `mean_reversion_bb` | `Below lower band` | `Mid-band, then upper band` |
| `mean_reversion_vwap` | `0.5 ATR below entry` | `VWAP, then 0.5 ATR past it` |
| `mean_reversion_multi` | `Widest of the fired variants' stops` | `Tightest of the fired variants' targets` |

`STRATEGIES_BEARISH` mirrors each (above/below, high/low, upper/lower band swapped).

- [ ] **Step 6: Add the card test**

Create `frontend/components/organisms/StockPositionCard/__tests__/StockPositionCard.exits.test.tsx`
covering `defaultOverlay`'s two paths. Since `defaultOverlay` is module-private, exercise it through
the rendered card: mount with a fixture whose `strategy.targets` is `[105, 112, 120]` and assert the
T1/T2/T3 rows read those values; mount a second fixture with `targets` omitted and assert the 2R/3R
fallback still renders (`entry + 2·risk`, `entry + 3·risk`). Mock `@/lib/api`'s `getBrokerStatus`
(the card calls it on mount) following the pattern in
`frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx`.

- [ ] **Step 7: Run and commit**

```bash
cd backend && pytest tests/test_stock_scan_backtest_commission.py -q
cd ../frontend && npm run typecheck && npm run test -- --testPathPattern="StockPositionCard|StockSendDialog|paperTrade"
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py \
        frontend/types/stockDomain.ts frontend/components/organisms/StockPositionCard/ \
        "frontend/app/(frame)/screener/step-4-stocks/page.tsx"
git commit -m "feat(stocks): surface the backend exit ladder to the position card, retire client 2R/3R"
```

---

# Approach B — the probability veneer

### Task 14: `estimate_stock_first_passage()`

**Files:** `backend/app/scoring/first_passage.py`, `backend/tests/test_stock_first_passage.py`

- [ ] **Step 1: Add the stock estimator**

Append to `backend/app/scoring/first_passage.py`, after `estimate_first_passage()`:

```python
@dataclass
class StockTargetEstimate:
    price: float
    probability: float
    expected_days: Optional[float]   # None if probability == 0


@dataclass
class StockFirstPassageResult:
    targets: list[StockTargetEstimate]
    invalidation: InvalidationEstimate
    sigma_stock: float
    mu: float
    horizon_days: int


def estimate_stock_first_passage(
    *,
    stock_price: float,
    direction: str,
    trend_score: float,
    stop_price: float,
    targets: list[float],
    candles: list[dict],
    horizon_days: int,
    max_drift_pct: float = 0.40,
    n_paths: int = 2000,
    sigma_floor: float = 0.10,
    sigma_ceiling: float = 1.50,
    seed: int = 0,
) -> StockFirstPassageResult:
    """Monte Carlo first-passage estimate for a STOCK position's exit ladder.

    Strict subset of estimate_first_passage(): it keeps the three
    instrument-agnostic stages — ATR -> annualized sigma, trend score -> drift,
    GBM path simulation — and the barrier test, and drops the three
    option-specific ones (sigma_iv back-out from premium, the Stage-1 bisection
    for "what stock price yields premium x (1+pct)", and the per-day
    Black-Scholes repricing loop). Dropping the repricing loop is why this is
    materially FASTER than its option sibling, not merely smaller: that loop is
    the expensive part.

    A stock profit target is the invalidation branch with the comparison flipped
    (`stock_paths >= target` instead of `<=`), which is exactly the shape already
    at line 241 of the option version.

    horizon_days replaces `dte`: stocks have no expiry, so the simulation needs an
    explicit holding window. Callers pass scoring_rules.yaml's
    `confidence_backtest.<horizon>.n_days` (Intraday 5 / Swing 10 / Position 40),
    which is this app's existing definition of "how long a signal in this horizon
    takes to resolve" — reusing it keeps the Monte Carlo window consistent with
    the empirical confidence window rather than inventing a second answer.

    UNITS — the one place this deliberately differs from its option sibling.
    ``n_days`` counts TRADING days (signal_confidence walks forward N bars), and
    ``sigma_stock`` is annualized from a daily ATR with ``sqrt(252)``, so the
    time step here is ``1/252``. The option version steps at ``1/365`` because
    its window is ``dte``, which is CALENDAR days to expiry. Both are internally
    consistent — annualized vol times the right year fraction — and copying
    ``1/365`` here would have understated the simulated variance over the window
    by 252/365 (about 20% in vol terms). ``expected_days`` is therefore also in
    trading days; the endpoint and the card say so.

    NOTE ON MODEL VALIDITY: a constant drift derived from a trend score is a poor
    generative model for the mean_reversion_* strategies, whose whole thesis is
    that the recent drift is transient. That caveat is surfaced to the user by the
    caller (see the endpoint's `model_caveat`), not silently absorbed here.
    """
    is_bullish = direction == "Bullish"
    sign = 1.0 if is_bullish else -1.0

    atr = _atr(candles, 14) if candles else 0.0
    sigma_stock = sigma_floor
    if stock_price > 0:
        sigma_stock = max(sigma_floor, min(sigma_ceiling, (atr / stock_price) * math.sqrt(252)))

    # trend_score is DIRECTION-ALIGNED by the time it reaches here: the stock
    # scorer scores in the requested direction, so 80 means "strongly favours
    # this trade" for a Bearish scan just as much as for a Bullish one. Hence
    # sign * (score - 50): a favourable score drifts WITH the trade, an
    # unfavourable one drifts against it. Same construction as the option
    # sibling's `direction_sign * (trend_score - 50)`.
    mu = sign * (trend_score - 50) / 50 * max_drift_pct

    clean_targets = [float(t) for t in targets if t is not None and math.isfinite(t) and t > 0]

    # Degenerate inputs: a non-positive price or an empty window can't be
    # simulated. Return zero-probability rather than crashing on median() of an
    # empty array — the same guard the option version applies at dte < 1.
    if stock_price <= 0 or horizon_days < 1:
        return StockFirstPassageResult(
            targets=[StockTargetEstimate(price=t, probability=0.0, expected_days=None)
                     for t in clean_targets],
            invalidation=InvalidationEstimate(probability=0.0, expected_days=None),
            sigma_stock=sigma_stock, mu=mu, horizon_days=max(horizon_days, 0),
        )

    rng = np.random.default_rng(seed)
    dt = 1 / 252   # horizon_days is a TRADING-day count — see the docstring
    z = rng.standard_normal((n_paths, horizon_days))
    log_returns = (mu - 0.5 * sigma_stock ** 2) * dt + sigma_stock * math.sqrt(dt) * z
    stock_paths = stock_price * np.exp(np.cumsum(log_returns, axis=1))

    def _barrier(mask: np.ndarray) -> tuple[float, Optional[float]]:
        ever = mask.any(axis=1)
        probability = float(ever.mean())
        if not ever.any():
            return probability, None
        first = np.argmax(mask, axis=1)
        return probability, float(np.median(first[ever]) + 1)   # +1: column 0 == day 1

    target_estimates: list[StockTargetEstimate] = []
    for t in clean_targets:
        prob, days = _barrier(stock_paths >= t if is_bullish else stock_paths <= t)
        target_estimates.append(StockTargetEstimate(price=t, probability=prob, expected_days=days))

    if math.isfinite(stop_price) and stop_price > 0:
        stop_prob, stop_days = _barrier(
            stock_paths <= stop_price if is_bullish else stock_paths >= stop_price
        )
    else:
        stop_prob, stop_days = 0.0, None

    return StockFirstPassageResult(
        targets=target_estimates,
        invalidation=InvalidationEstimate(probability=stop_prob, expected_days=stop_days),
        sigma_stock=sigma_stock, mu=mu, horizon_days=horizon_days,
    )
```

- [ ] **Step 2: Test**

Create `backend/tests/test_stock_first_passage.py`:

```python
"""Stock first-passage estimator — the option-free sibling of estimate_first_passage."""
from __future__ import annotations

import pytest

from app.scoring.first_passage import estimate_stock_first_passage


def _candles(price: float = 100.0, n: int = 60, atr_pct: float = 0.02) -> list[dict]:
    band = price * atr_pct
    return [{"open": price, "high": price + band, "low": price - band,
             "close": price, "volume": 1_000_000} for _ in range(n)]


def test_nearer_targets_are_more_likely_than_farther_ones():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[102.0, 110.0, 125.0], candles=_candles(), horizon_days=10, seed=1,
    )
    probs = [t.probability for t in res.targets]
    assert probs == sorted(probs, reverse=True)
    assert 0.0 <= probs[-1] <= probs[0] <= 1.0


def test_bearish_targets_are_below_and_the_comparison_flips():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bearish", trend_score=80.0, stop_price=105.0,
        targets=[98.0, 90.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.targets[0].probability >= res.targets[1].probability
    # trend_score is direction-ALIGNED: 80 on a Bearish scan means "strongly
    # bearish", so the drift must point down. (An earlier draft asserted this
    # with trend_score=20, which yields mu = -1 * -0.6 * 0.4 = +0.24 — an UPWARD
    # drift, and the assertion would have failed.)
    assert res.mu < 0


def test_an_unfavourable_trend_score_drifts_against_the_trade():
    """The mirror of the above, pinned so the sign convention can't silently flip."""
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bearish", trend_score=20.0, stop_price=105.0,
        targets=[90.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.mu > 0


def test_is_deterministic_for_a_given_seed():
    kwargs = dict(stock_price=100.0, direction="Bullish", trend_score=55.0,
                  stop_price=96.0, targets=[105.0], candles=_candles(), horizon_days=10)
    a = estimate_stock_first_passage(**kwargs, seed=42)
    b = estimate_stock_first_passage(**kwargs, seed=42)
    assert a.targets[0].probability == b.targets[0].probability
    assert a.targets[0].expected_days == b.targets[0].expected_days


def test_zero_horizon_returns_zero_probability_without_crashing():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[110.0], candles=_candles(), horizon_days=0, seed=1,
    )
    assert res.targets[0].probability == 0.0
    assert res.targets[0].expected_days is None
    assert res.invalidation.probability == 0.0


def test_non_positive_price_returns_zero_probability():
    res = estimate_stock_first_passage(
        stock_price=0.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[110.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.targets[0].probability == 0.0


def test_empty_candles_still_produce_a_floored_sigma():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=50.0, stop_price=95.0,
        targets=[110.0], candles=[], horizon_days=10, sigma_floor=0.10, seed=1,
    )
    assert res.sigma_stock == pytest.approx(0.10)


def test_bad_target_values_are_filtered_out():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=95.0,
        targets=[0.0, -5.0, float("nan"), 110.0], candles=_candles(),
        horizon_days=10, seed=1,
    )
    assert [t.price for t in res.targets] == [110.0]


def test_a_non_positive_stop_yields_no_invalidation_probability():
    res = estimate_stock_first_passage(
        stock_price=100.0, direction="Bullish", trend_score=60.0, stop_price=0.0,
        targets=[110.0], candles=_candles(), horizon_days=10, seed=1,
    )
    assert res.invalidation.probability == 0.0
    assert res.invalidation.expected_days is None
```

- [ ] **Step 3: Run and commit**

```bash
cd backend && pytest tests/test_stock_first_passage.py tests/test_first_passage.py \
  tests/test_first_passage_alert_compatibility.py -q
git add backend/app/scoring/first_passage.py backend/tests/test_stock_first_passage.py
git commit -m "feat(first-passage): add option-free stock first-passage estimator"
```

---

### Task 15: The `/api/stocks/first-passage` endpoint

**Files:** `backend/app/routers/stock_scan.py`, `backend/app/routers/contracts.py` (docstring only)

- [ ] **Step 1: Add the request/response models and the route**

Append to `backend/app/routers/stock_scan.py`:

```python
class StockFirstPassageRequest(BaseModel):
    symbol:       str
    direction:    Literal["Bullish", "Bearish"]
    horizon:      Literal["Intraday", "Swing", "Position"]
    strategy:     str
    stock_price:  float = Field(..., gt=0)
    stop_price:   float = Field(..., gt=0)
    targets:      list[float] = Field(..., min_length=1, max_length=5)
    trend_score:  float = Field(..., ge=0, le=100)


class StockFirstPassageTargetOut(BaseModel):
    price:        float
    probability:  float
    expectedDays: Optional[float] = None


class StockFirstPassageResponse(BaseModel):
    targets:      list[StockFirstPassageTargetOut]
    invalidation: FirstPassageInvalidationOut
    horizonDays:  int
    #: Non-null when the GBM model is a poor fit for this strategy; the card
    #: renders it verbatim. See the plan's "GBM caveat" decision — labelled, not
    #: suppressed, and decided HERE (next to the model) rather than in the UI so
    #: the rule lives in exactly one place.
    modelCaveat:  Optional[str] = None


@router.post('/stocks/first-passage', response_model=StockFirstPassageResponse)
async def stock_first_passage(req: StockFirstPassageRequest) -> StockFirstPassageResponse:
    """On-demand Monte Carlo first-passage estimate for a stock position's exit
    ladder: probability and expected days to reach each target, and to hit the
    stop, within this horizon's holding window.

    Fired only by the stock position card's "Estimate" button — never by the scan
    — for the same latency reasons as the options `/contracts/first-passage`.
    The holding window comes from scoring_rules.yaml's
    `confidence_backtest.<horizon>.n_days`, this app's existing definition of how
    long a signal in that horizon takes to resolve.
    """
    fp_cfg = _fp_cfg()
    try:
        horizon_days = int(load_backtest_cfg(req.horizon)["n_days"])
    except (KeyError, TypeError, ValueError):
        horizon_days = 10   # Swing default; never fail the request over config shape

    async with httpx.AsyncClient(timeout=10) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # Deterministic per-request seed, same construction and same reasoning as
    # contracts.py's: identical inputs return an identical answer instead of
    # visible Monte Carlo noise on repeated presses, while genuinely different
    # inputs still draw independently. sha256, not hash() — the latter is salted
    # per process (PYTHONHASHSEED) and so is not stable across restarts/workers.
    seed_key = (f"{req.symbol.upper()}|{req.direction}|{req.horizon}|"
                f"{round(req.stock_price, 2)}|{round(req.stop_price, 2)}|"
                f"{','.join(f'{t:.2f}' for t in req.targets)}")
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    result = await asyncio.to_thread(
        functools.partial(
            estimate_stock_first_passage,
            stock_price=req.stock_price,
            direction=req.direction,
            trend_score=req.trend_score,
            stop_price=req.stop_price,
            targets=req.targets,
            candles=candles,
            horizon_days=horizon_days,
            max_drift_pct=fp_cfg["max_drift_pct"],
            n_paths=fp_cfg["n_paths"],
            sigma_floor=fp_cfg["sigma_floor"],
            sigma_ceiling=fp_cfg["sigma_ceiling"],
            seed=seed,
        )
    )

    caveat = None
    if req.strategy.startswith("mean_reversion"):
        caveat = (
            "Approximate for mean-reversion strategies: this model assumes a constant "
            "drift from the trend score, while a mean-reversion trade's thesis is that "
            "the recent drift is transient. Treat the target probabilities as a rough "
            "upper bound; the stop probability is less affected."
        )

    return StockFirstPassageResponse(
        targets=[
            StockFirstPassageTargetOut(
                price=round(t.price, 2),
                probability=round(t.probability, 4),
                expectedDays=t.expected_days,
            )
            for t in result.targets
        ],
        invalidation=FirstPassageInvalidationOut(
            probability=round(result.invalidation.probability, 4),
            expectedDays=result.invalidation.expected_days,
        ),
        horizonDays=result.horizon_days,
        modelCaveat=caveat,
    )
```

Add the imports this needs at the top of `stock_scan.py`: `hashlib`, `Optional`/`Literal` from
`typing` (check what is already imported), `Field` from `pydantic`,
`from app.scoring.first_passage import estimate_stock_first_passage`,
`from app.scoring.signal_confidence import load_backtest_cfg`,
`from app.services.config_loader import load_first_passage_cfg as _fp_cfg`, and
`fetch_candles_async` from wherever `contracts.py` imports it. Reuse `FirstPassageInvalidationOut`
by importing it from `app.routers.contracts` — it is an exact shape match and duplicating it would
create two models to keep in sync.

> The estimator is CPU-bound NumPy over 2000 paths. `asyncio.to_thread` keeps it off the event loop,
> matching how `stock_scan.py` already offloads `compute_confidence` (line 822) and
> `fetch_intraday_candles` (line 624). Do not use the module's `_BACKTEST_POOL` — that is a
> *process* pool sized for the backtester and this work is far too small to justify pickling.

- [ ] **Step 2: Name the second consumer of the structural-stop endpoint**

In `backend/app/routers/contracts.py:289-296`, extend the `structural_stop` docstring:

```python
    """On-demand structural (order block / swing) invalidation lookup for one symbol.

    Deliberately its own endpoint, not folded into recompute-plan: this is fired
    only by an explicit user action ("Check structure") on the trade card, never
    on every contract swap, so it never adds latency to the scan or to Step 6
    contract overrides.

    NOT options-specific despite the /contracts/ prefix (a legacy namespace
    artefact): find_structural_stop() takes only candles, direction and a
    reference price. The stocks-mode StockPositionCard calls this same endpoint
    for its own "Check structure" affordance — do not fork an alias route.
    """
```

- [ ] **Step 3: Smoke-test the route**

Append a route test to `backend/tests/test_stock_first_passage.py` following the FastAPI
`TestClient` pattern already used elsewhere in `backend/tests/` (grep for `TestClient(app)`), asserting:
a 200 with three targets in, three out and probabilities in `[0, 1]`; `horizonDays == 10` for
`horizon="Swing"`; `modelCaveat` non-null for `strategy="mean_reversion_bb"` and null for
`strategy="breakout_base"`; a 422 for `stop_price=0` and for `targets=[]`.

- [ ] **Step 4: Run and commit**

```bash
cd backend && pytest tests/test_stock_first_passage.py -q
git add backend/app/routers/stock_scan.py backend/app/routers/contracts.py backend/tests/
git commit -m "feat(api): add POST /api/stocks/first-passage with an explicit mean-reversion caveat"
```

---

### Task 16: The Estimate and Check-structure affordances on `StockPositionCard`

**Files:** `frontend/lib/api.ts`, `frontend/types/stockDomain.ts`,
`frontend/components/organisms/StockPositionCard/index.tsx` + its `.module.css`

- [ ] **Step 1: Add the response types**

Append to `frontend/types/stockDomain.ts`:

```typescript
export interface StockFirstPassageTarget {
  price:        number;
  probability:  number;         // 0-1
  expectedDays: number | null;  // median days to hit; null if probability is 0
}

export interface StockFirstPassageEstimate {
  targets:      StockFirstPassageTarget[];
  invalidation: { probability: number; expectedDays: number | null };
  horizonDays:  number;
  /** Non-null when the model is a poor fit for this strategy (mean_reversion_*).
   *  Rendered verbatim; the decision of WHEN to set it lives in the backend. */
  modelCaveat:  string | null;
}
```

- [ ] **Step 2: Add the API client method**

In `frontend/lib/api.ts`, immediately after `getFirstPassageEstimate` (line 361-380), add:

```typescript
  /** On-demand Monte Carlo first-passage estimate for a STOCK position's exit
   *  ladder — fired only by the stock position card's "Estimate" button. */
  getStockFirstPassage: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    horizon: 'Intraday' | 'Swing' | 'Position';
    strategy: string;
    stock_price: number;
    stop_price: number;
    targets: number[];
    trend_score: number;
  }, signal?: AbortSignal) =>
    post<StockFirstPassageEstimate>('/api/stocks/first-passage', req, signal),
```

with the matching type import.

- [ ] **Step 3: Add both affordances to the card**

Insert a new section into `StockPositionCard` between the Sell-to-Close plan (which ends at
`index.tsx:336`) and `<MarketSentiment …>`. It mirrors the options Trade Card's Profit Targets
section (`TradeCard/index.tsx:711-790`) — **read that for the visual pattern only; do not modify
it.** The section needs:

- Two buttons, `Estimate` and `Check structure`, each with a `…ing` disabled state, matching the
  existing `styles.actionBtn` / `styles.actionRow` markup already in this file.
- `useState` for `estimate: StockFirstPassageEstimate | null`, `structural: { price, source,
  confidence, distancePct } | null`, two loading flags and two error flags.
- Two `useRef<AbortController | null>` request refs, aborted in the existing
  `useEffect([card.symbol])` reset block (`index.tsx:131-139`) and in an unmount cleanup effect —
  the same discipline `TradeCard` documents at its lines 228-256. Add `setEstimate(null)`,
  `setStructural(null)` and both error resets to that existing effect.
- `Estimate` calls `api.getStockFirstPassage` with the **current overlay** values
  (`overlay.stop`, `[overlay.t1, overlay.t2, overlay.t3]`, `overlay.entry` as `stock_price`) —
  the overlay is what the user intends to trade, matching this plan's pristine-vs-edited decision —
  plus `strategy: card.strategy.strategy`, `direction`, `horizon` from
  `useScanStore(s => s.context?.horizon) ?? 'Swing'`, and `trend_score: card.stock_score`.
  Be honest about that last one in the code comment: `stock_score` is the 5-rule composite
  (trend / pullback / trigger / event / vol), not a pure trend score. It is the only 0–100 conviction
  number the stock card actually has, and the estimator only uses it as a drift scale
  (`mu = sign · (score − 50) / 50 · max_drift_pct`), so a composite conviction is a defensible proxy
  — but it is a proxy, and the parameter name should not be allowed to imply otherwise.
- Rows rendering, per target: price, `probability` as a percentage, `expectedDays` as `~Nd` or
  `unlikely`, using `<Data>` / `<Text>` primitives at the sizes the rest of this file uses.
- A stop-out row: "Probability of stopping out first" + expected days.
- The horizon window rendered inline — *"within {horizonDays} trading days"*. A probability without
  its window is meaningless, so it is not optional chrome; and the unit is trading days, not
  calendar days, because `confidence_backtest.n_days` counts bars (see
  `estimate_stock_first_passage`'s UNITS note). `expectedDays` is in the same unit.
- `estimate.modelCaveat` rendered verbatim as `<Text size={11} tone="caution">` when non-null.
- `Check structure` calls the existing `api.getStructuralStop({ symbol, direction, stock_price:
  overlay.entry })`, renders the level, its source and `R:R vs structural = |t1 − entry| / |entry −
  structuralPrice|`. **This task then amends the `buildPaperStockPosition(…)` call Task 2 Step 2
  wrote**, adding `structuralStop: structural?.price ?? null` to its `levels` argument — that is what
  lets `STRUCTURAL_STOP_BREACHED` fire for a stock position. Guard the R:R division against
  `|entry − structuralPrice| === 0`.

CSS: reuse the existing classes in `StockPositionCard.module.css` wherever possible; any new class
must use `border: 1px solid var(--border-subtle)` (no card shadows) and tokens from
`app/globals.css` — never a hardcoded colour.

- [ ] **Step 4: Extend the card test**

Add to `StockPositionCard.exits.test.tsx`: mock `api.getStockFirstPassage` and
`api.getStructuralStop`; assert clicking Estimate renders one row per target with the mocked
probabilities and the `within N days` window; assert `modelCaveat` renders when the mock returns one
and is absent when it returns `null`; assert that after a successful `Check structure`, clicking
"Add to Portfolio" calls `addPosition` with a position whose `structuralStop` equals the mocked
price.

- [ ] **Step 5: Run and commit**

```bash
cd frontend && npm run typecheck && npm run test -- --testPathPattern=StockPositionCard
git add frontend/lib/api.ts frontend/types/stockDomain.ts frontend/components/organisms/StockPositionCard/
git commit -m "feat(stocks): add first-passage Estimate and structural-stop check to the position card"
```

---

### Task 17: Typecheck, full suites, and manual verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

```bash
cd backend && pytest
```
Expected: clean. Any failure must be triaged, not accepted: re-run the same test on the branch point
(`git stash` / `git worktree` a clean checkout) to establish whether it is pre-existing. Record every
pre-existing failure by name in the final report; fix every new one.

Pay particular attention to `test_strategy_engine.py`, `test_strategy_engine_bearish.py`,
`test_mean_reversion_multi.py`, `test_strategy_backtest*.py`, `test_strategy_watch_evaluator.py`,
`test_strategy_param_optimizer.py` and `test_strategy_params_config_sanity.py` — these are the
suites the exit rework can legitimately move. A test that asserts a specific `target_price` derived
from the old formula is a **real** signal that a call site was missed, not a test to relax.

- [ ] **Step 2: Frontend typecheck and full suite**

```bash
cd frontend && npm run typecheck && npm run test
```
Expected: clean. Watch `portfolioStore`, `alertEngine` and `stockScan` suites in particular — they
exercise `PortfolioPosition.stop`/`.targets`, which now arrive populated for stock rows for the first
time.

- [ ] **Step 3: Manual verification**

Start the backend and `cd frontend && npm run dev` (port 3001), then:

1. **Approach A, the headline fix.** Run a Stocks scan, open a candidate, note its T1/T2/T3, click
   "Add to Portfolio". Open `/portfolio`, open that row's edit drawer: the Stop field shows a real
   positive number (not blank) and the target list has three rungs at the card's values. Before this
   plan the drawer showed no stop and no targets.
2. **Nearest-first ordering.** On the card, deliberately type T1 = 130, T2 = 110, T3 = 120 (bullish).
   Add to portfolio. The drawer's first target must be **110**, not 130 — `TP_HIT` reads `targets[0]`
   and the ladder is re-sorted on the way in.
3. **The zero-stop hazard.** Clear the STOP field on the card (leave it mid-edit at 0 if the input
   allows it) and add. The portfolio row's stop is **blank/unset**, never `0`, and no
   `STOP_REACHED` alert appears. Check the browser console and the backend log for a fired alert —
   there must be none.
4. **Approach D per strategy.** Run one scan per strategy and check the position card's T1 against
   the strategy's thesis: `breakout_base` T1 ≈ base high + base height (compare with the chart);
   `mean_reversion_bb` T1 = the mid-band value shown in the score-card detail; `pullback_ema` T1 =
   a visible prior swing high on the chart; `ma_crossover` T1 ≈ entry + 3 ATR (unchanged); the
   Step-4 picker's exit prose now matches what the card shows.
5. **`mean_reversion_multi` order-independence.** Select variants in the order RSI, BB, VWAP-daily
   and run; note entry/stop/T1 for one symbol. Re-select them as VWAP-daily, BB, RSI and re-run: the
   three numbers must be **identical**. Before this plan they changed.
6. **Approach B.** On a `breakout_base` candidate click "Estimate": three rows appear with
   probabilities in descending order, expected days, a stop-out probability, and a visible
   "within 10 days" (Swing). No caveat text. Repeat on a `mean_reversion_bb` candidate: the caveat
   paragraph is present.
7. **Structural stop end-to-end.** Click "Check structure", then "Add to Portfolio". The portfolio
   drawer's Structural Stop field is populated. Before this plan it was only ever populated from the
   options path.
8. **Backtest movement is visible and sane.** Note one symbol's Step-6 win rate before and after
   (use `git stash` to compare if needed). It should move — and move up — for every strategy except
   `ma_crossover`, whose primary target is deliberately unchanged.
9. **Nothing regressed on the options path.** Run an Options scan through to Step 7, click
   "Estimate" and "Check structure" on the Trade Card, and send a contract to a paper broker.
   Everything behaves exactly as before — this plan touched neither `TradeCard` nor
   `step-7-trade-card`.

- [ ] **Step 4: Re-run the tuner (optional, and expected)**

Settings → Strategy Tuning. Confirm the job runs to completion against the new grids and that the
proposals it produces reference the new parameters (`measured_move_mult`, `exit_swing_lookback`,
`atr_target_mult`, `exit_sma_period`) and no longer reference `rr_target_mult` for the three
strategies it was removed from. Adopting the proposals is Kenneth's call, not this plan's.

- [ ] **Step 5: Final commit (only if Steps 1-4 found something to fix)**

```bash
git add -A
git commit -m "fix(stocks): address issues found in exit-targets verification"
```

---

## Adversarial-audit corrections (round 1)

The following were found by a hostile re-read of this plan against the working tree, after the
Self-Review Notes below were written. They are recorded separately because several of them
*contradict* those notes, and a reader should see the contradiction rather than a quietly patched
document.

1. **[critical] Sorting one flat `thesis` list nearest-first demotes the thesis rung.** The original
   `_build_target_ladder(thesis=[...])` pooled the strategy's objective with its generic R/ATR
   extensions and sorted them all by distance from entry. For `mean_reversion_vwap` that is not a
   corner case — the entry gate puts VWAP ≥ 1.5% away while `risk = 0.5 ATR`, so `entry + 2R` is
   almost always nearer and would have become `target_price`, leaving that strategy's exits
   unchanged while the Step-4 copy claimed otherwise. Reachable for `pullback_ema`,
   `mean_reversion_bb`, `mean_reversion_rsi` and `mean_reversion_vwap_daily` too. **Fixed:** the
   helper now takes `primary` and `extensions` separately; the primary always leads when valid and
   an extension nearer than the rung before it is dropped, never reordered ahead.
2. **[high] A 0.5R floor on the primary silently changes `ma_crossover`.** Its stop sits at the slow
   MA, so right after a fast cross `risk` can be ~11× ATR and 0.5R exceeds the 3-ATR objective — the
   floor would drop the one rung this plan promises is numerically unchanged and promote the 6-ATR
   extension. **Fixed:** `min_rung_r` now defaults to 0; the only validity test applied to a
   strategy's own objective is "finite, positive, strictly beyond entry at 2dp". `resolve_multi_signal`
   is the single caller that passes `min_rung_r=0.5`, and only because it re-uses rungs against a
   stop no variant derived them with.
3. **[high] `composite_trigger_evaluator.py` does not resolve per-strategy params at all.** Task 4
   Step 3(d) claimed it did, "around the `_SIGNAL_FNS`-style dispatch at lines 116-124"; those lines
   are a local `_FNS` lookup table and `_matched_strategy_signals` calls
   `fn(slice_bars, direction=direction)` with pure Python defaults. **Fixed:** the file is no longer
   modified; the reasoning (exit params cannot change whether a signal fires) is recorded in place.
   "All four consumers" is now three.
4. **[high] Removing a param from `search:` deletes it from `active:` on the next tuner adopt.**
   `adopt()` sets `active[direction] = params` — a whole-dict replace with the winning grid combo —
   so `rr_target_mult` and `atr_target_mult` would vanish and revert to Python defaults, contradicting
   the plan's "stays in `active:`". **Fixed:** every rung-2/3 param is mirrored into `exit:` (which
   `adopt()` never touches), and `test_rung_2_3_params_survive_a_tuner_adopt` enforces it.
5. **[medium] `adopt()` destroys every comment in `strategy_params.yaml`** (`yaml.safe_dump`). The
   Task 12 Step 2 re-tune note is therefore best-effort, not durable. **Fixed:** caveat stated; the
   durable copy lives in `get_exit()`'s docstring and this plan.
6. **[medium] The claim that `paperTrade.test.ts` asserts `stop === 0` is false.** Its two tests
   touch only `symbol`/`contract`/`entryPrice`/`contracts`/`direction`. **Fixed.**
7. **[high] Two thesis-test fixtures could never fire, so those tests would always `pytest.skip`.**
   `ma_crossover`'s used a monotonically rising series, which never crosses (the fast MA is above the
   slow MA at every comparable bar); `mean_reversion_rsi`'s 0.12/bar ramp with an 8-bar dip lands the
   close *below* the 200-SMA and fails the uptrend gate. Both would have passed green while proving
   nothing — exactly the soft spot the Self-Review Notes flagged, realised twice. **Fixed:** both
   fixtures replaced, and every new thesis test now asserts `sig is not None` instead of skipping.
8. **[medium] `mean_reversion_multi`'s resolution is not backtested.** `stock_scan.py` uses
   `mean_reversion_rsi` as the canonical backtest proxy, so the Step-6 win rate measures the RSI
   variant's ladder, not the resolved one. Pre-existing and unchanged, but the plan never said so.
   **Fixed:** recorded as a KNOWN LIMITATION in `resolve_multi_signal`'s docstring.
9. **[low] Line-number and naming nits.** `TargetLevel` is `domain.ts:170-183` (not 171-183);
   `PortfolioPosition` starts at 185 and runs past 226; `mean_reversion_bb`'s bearish gates are at
   585/587 (not 586-588); the analysis-path `StrategySignalOut` is at `stock_scan.py:555`; the
   variable at `strategy_engine.py:730` is `dev_pct` (a fraction) not `dev_frac`. **Fixed.**
10. **[low] `trend_score: card.stock_score` is a proxy, not a trend score.** `stock_score` is the
   5-rule composite. Defensible as a drift scale, but the plan now says so out loud rather than
   letting the parameter name imply otherwise. **Fixed.**
11. **[low, retracted]** The Background's "`bt_min_win_rate` 0.45, `bt_min_trades` 5" looked wrong
   against `strategy_backtest._MIN_TRADES = 10`, but `StockScanRequest` defaults to 5 and the live
   scan always passes it. The plan was right; a clarifying row was added to the facts table.

## Adversarial-audit corrections (round 2)

A second hostile pass, run against the round-1 revision:

12. **[high] The `mu` sign test asserted the wrong direction.**
   `test_bearish_targets_are_below_and_the_comparison_flips` used `trend_score=20` and asserted
   `mu < 0`, but `trend_score` is direction-*aligned* (the stock scorer scores in the requested
   direction), so 20 on a Bearish scan means the trend *opposes* the trade and
   `mu = −1 · (20−50)/50 · 0.40 = +0.24`. **Fixed:** the test now uses 80, and a mirror test pins the
   unfavourable case at `mu > 0` so the convention cannot silently flip.
13. **[high] `dt = 1/365` is wrong for a trading-day horizon.** `horizon_days` comes from
   `confidence_backtest.<horizon>.n_days`, which counts bars, and `sigma_stock` is annualized with
   `sqrt(252)` — so stepping at 1/365 understates the simulated variance over the window by 252/365
   (≈20% in vol terms). The option sibling's 1/365 is correct *there* because `dte` is calendar days.
   **Fixed:** `dt = 1/252`, documented, and both the endpoint and the card now say "trading days".
14. **[medium] `?? [c.strategy.target_price]` does not catch an empty array.** `StockSendDialog` and
   the Step-4 auto-execute both used `??`, which only fires on `null`/`undefined` — a backend or
   rehydrated scan result carrying `targets: []` would have persisted a position with no take-profit
   at all. **Fixed:** `?.length ? … : …` at all three sites (including `defaultOverlay`).
15. **[medium] `defaultOverlay`'s 2R/3R fill can put T2 nearer than a strategy-derived T1.** A prior
   swing high 4R away leaves the old `entry + 2R` fill *behind* T1, and `stockPositionLevels()` sorts
   nearest-first on the way into the portfolio — so the persisted `targets[0]`, the only rung
   `TP_HIT` fires on, would not be the rung the card labelled T1. **Fixed:** missing rungs step one
   more R past the *previous rung*, not from entry. (This also fixes the pre-existing legacy case,
   where `t1 = target_price = entry + 2R` duplicated `t2`.)
16. **[low] Task 16 amends a call site Task 2 already wrote.** Made explicit, plus a divide-by-zero
   guard on the structural R:R.

## Adversarial-audit corrections (round 3)

A third pass found no new defects. What it checked, so the clean result is auditable rather than
asserted, plus two residual risks now recorded rather than left implicit:

- **Grid-size changes break nothing.** `test_walk_forward.py::test_param_combos_cartesian` uses a
  synthetic 2×2 space, not the shipped grids; no test asserts a combo count for a real strategy.
- **A strategy with no `search:` block is skipped cleanly** by `strategy_param_optimizer.run_optimization`
  (`strategy_param_optimizer.py:241-247` — `if not search_space: … continue`), and
  `strategy_tuning.py:64` enumerates `cfg["strategies"].keys()` without assuming any sub-block, so
  adding a `mean_reversion_vwap_daily` key that has only `exit:` is safe.
- **`test_strategy_params_config_sanity.py`'s existing assertion still passes** for every value this
  plan adds to `active:`: `exit_swing_lookback` 20 ∈ [10,20,30]; `measured_move_mult` 1.0 ∈
  [0.75,1.0,1.25,1.5]; `atr_target_mult` 3.0 ∈ [2.0,3.0,4.0]; `exit_sma_period` 20 ∈ [10,20];
  `rr_target_mult`/`atr_target_mult` where no grid entry exists are skipped by that test's own rule.
- **`stock_scan.py` has no `/stocks/…` route today** and `test_routes.py` asserts no route inventory,
  so `POST /api/stocks/first-passage` collides with nothing.
- **No import cycle** from `stock_scan.py` importing `FirstPassageInvalidationOut` out of
  `contracts.py`: `contracts.py` imports nothing from `stock_scan.py` (verified by grep), and
  `main.py` registers `contracts_router` before `stock_scan_router`.

**Residual risk 1 — a moved fill price can put a validated stop on the wrong side of the real entry.**
`add_position` overwrites `entry_price` with the live quote (`portfolio.py:230-234`), while
`stockPositionLevels()` validated the stop against the card's entry. If the live quote has already
crossed the stop, `STOP_REACHED` fires immediately. That is **correct** — the position genuinely is
beyond its invalidation the moment it opens — and it is not the failure mode the sanitizer exists to
prevent (a stop stored on the wrong side of a *stationary* entry). Recorded so a future reader does
not mistake one for the other. It is equally true of the options path today and is not changed here.

**Residual risk 2 — the new exit parameters are not exposed in the Step-3 Execution Parameters panel.**
`exit_swing_lookback`, `measured_move_mult`, `atr_target_mult`, `exit_sma_period` and
`vwap_extension_atr` are configurable via `strategy_params.yaml` and tunable (where they set rung 1)
via WFO, but there is no per-scan UI override for them. Deliberate: the panel already carries 62
definitions and adding five more is a separate design question, not part of making exits
strategy-aware. `_merge_strategy_params`'s `request_kwargs` layer already accepts them, so wiring the
UI later needs no backend change.

## Self-Review Notes (completed by the plan author, not a task for the implementer)

- **Every brainstorm claim was re-derived from the working tree, and three were wrong.** (1)
  `rr_target_mult` is in the `search:` grid for **three** strategies, not four — the brainstorm said
  "four" while citing three line numbers (50, 69, 124), and `mean_reversion_vwap` has no `search:`
  block at all. (2) `mean_reversion_multi`'s `fired[0]` resolution is **order-dependent and
  arbitrary**, not "non-deterministic" — `fired` is built by iterating `req.mean_reversion_variants`,
  so the same request is reproducible; the real bug is that reordering the UI checkboxes silently
  changes every level, which is a better reason to fix it. (3) The Step-4 exit prose spans lines
  **40-58**, not 41-57. Everything else checked out exactly, including `paperTrade.ts:35-36`,
  `strategy_engine.py:363-364` (base height), `:553` (Bollinger triple), and `first_passage.py:241`
  (the barrier test, at that precise line).
- **Three facts the brainstorm missed shape the plan more than anything it found.** `_entry_side`
  turns a bad target into *zero trades*, not worse trades (hence a ladder builder that drops rather
  than clamps); WFO passes only the grid combo to the signal function, so an exit policy living only
  in `active:` would make the tuner optimise a different strategy than the one that ships (hence the
  merge inside `run_strategy_backtest`); and `active:` values are splatted as kwargs, so removing a
  parameter from a signature while leaving it in config is an immediate `TypeError` (hence no
  parameter is ever removed from a signature, and hence the new
  `test_every_exit_block_key_is_accepted_by_its_signal_function`).
- **The `floorStop()` hazard is answered by never producing a number that needs flooring.**
  `stockPositionLevels()` returns `null`, not `0`, and additionally drops a stop on the wrong side of
  entry — which the store's floor does *not* catch and which would fire a real `STOP_REACHED`
  notification on the first tick for a healthy position. The store's eight floor sites stay as
  defence in depth; Task 1 Step 4 pins the "never 0" behaviour with three explicit assertions.
- **The pristine-vs-edited decision is applied at all four mint sites, not one.** Verified by grep
  for `buildPaperStockPosition`: the card (edited overlay), both `StockSendDialog` sites (pristine —
  and they are byte-identical today, so the plan keeps them byte-identical), the Step-4 after-scan
  auto-execute (pristine, no human in the loop), and `ChartWorkspace` (no levels at all, which is why
  `levels` is optional rather than required). The audit copy is genuinely "both": the pristine signal
  was *already* in `tradeCardSnapshot` via `stockCardSnapshotOf`, and Task 2 Step 1 adds the missing
  `edited` half so the record is a diff.
- **The WFO coupling is answered with a rule, not a case-by-case judgement.** "`search:` may contain
  only parameters that influence `ladder[0]` or `stop_price`" follows directly from
  `strategy_backtest` issuing `tp=target_price` and nothing else. Applied uniformly it removes
  `rr_target_mult` from three grids, adds a rung-1 parameter to four, and leaves
  `mean_reversion_bb` with no replacement because `bb_period`/`bb_std` genuinely already drive its
  mid-band target. `test_no_backtest_invisible_param_is_in_a_search_grid` makes the rule enforceable
  rather than a comment. The re-tune expectation is written into the config file itself, where the
  next reader of `active:` will actually see it.
- **Two "obvious" formulas were rejected on the strategy's own gate conditions, not on taste.**
  `mean_reversion_rsi` cannot target the trend SMA: its bullish gate is `close > trend[-1]`, so the
  200-SMA is *below* entry and targeting it targets a loss. `mean_reversion_vwap_daily` cannot target
  VWAP: its bullish gate is `close > vwap`, so VWAP is already behind entry and `_entry_side` would
  reject the signal entirely. Both are stated in the plan with their line numbers so a reviewer can
  check the gate rather than take the formula on faith. The intraday VWAP variant has the *opposite*
  gate, so VWAP is correct there — the two variants deliberately get different theses.
- **`ma_crossover`'s target is deliberately unchanged, and that is the honest answer.** A moving-
  average cross has no price objective; its thesis exit is a *condition*. Inventing a nearer price
  target to make it "strategy-aware" would be a formula in search of a thesis. It gets a ladder, a
  newly-tunable multiple, and the cross-back level emitted for display — with an explicit note that
  acting on that level needs per-bar state and is Approach E's job.
- **Edge cases are handled in one place and tested there.** Zero/negative ATR, a zero or negative
  base height, an unavailable short SMA, a squeezed mid-band, `NaN`/`inf`, duplicate rungs,
  out-of-order rungs, and a rung that rounds onto entry all resolve inside `_build_target_ladder`,
  with a named test each. The guarantee it provides — non-empty, strictly past entry, nearest-first —
  is exactly what `_entry_side` and `TP_HIT`'s `targets[0]` require, and
  `test_ladder_first_rung_always_satisfies_entry_side_gate` asserts the connection directly rather
  than by inspection.
- **`mean_reversion_multi`'s resolution is order-independent by construction, and the contradictory
  pairing is chosen deliberately.** Sorting by strategy name before resolving removes the request-
  order dependence; widest-stop-with-tightest-target is the conservative pairing and is defended in
  the docstring (the edge is the confirmation count, not the R:R; the alternative would pair two
  levels no single variant ever claimed together). The widened stop widens the minimum-R floor, which
  can drop a rung that was valid against a variant's own tighter stop —
  `test_resolve_multi_signal_drops_rungs_inside_the_widened_floor` covers exactly that and asserts
  the result still passes `_entry_side`.
- **Shared-file risk is zero by construction.** `frontend/types/domain.ts` is *not* modified:
  `PortfolioPosition.stop`, `.structuralStop`, `.targets` and `TargetLevel`'s
  `stockPrice`/`targetPrice`/`contractsToSell`/`status` already carry everything this plan writes.
  `TradeCard/` and `step-7-trade-card/` are untouched. The only file this plan and the sibling
  profit-target-cache work could both want is `frontend/lib/api.ts`, where this plan appends one
  method after an existing one — a trivial merge.
- **CLAUDE.md conventions checked:** new component test lives in the component's own
  `__tests__/` folder; primitives (`Text`/`Data`) are used at the sizes already present in the file;
  no card shadows and no hardcoded colours in new CSS; no new Zustand store and no new persistence
  key (the estimate is deliberately not persisted — that is the sibling's concern on the options
  side, and noted as a non-goal here); `StrategySignalData.targets` is optional specifically so no
  `scanStore` version bump or `migrate()` branch is needed for the persisted `stockScanResult`.
- **The GBM caveat is decided in the backend, not the UI.** `modelCaveat` is computed next to the
  model in the endpoint and rendered verbatim, so the rule cannot drift or be duplicated. Label
  rather than suppress is justified on two grounds stated in the plan: the stop-out probability
  stays informative for a mean-reversion trade, and suppressing five strategies while showing an
  equally drift-dependent number for `breakout_base` would be an inconsistency with no visible
  reasoning.
- **Deliberate non-goals, so they are not read as gaps:** trailing stops (Approach E — the ladder
  builder and `resolve_multi_signal` are shared functions specifically so E can consume them later);
  MFE/MAE percentile calibration (Approach C — the `exit:` block is precisely the surface it would
  tune); Pre-Breakout levels (`SetupSignal` has none); persisting a stock first-passage estimate
  across navigation; re-anchoring stock levels to the fill price (rejected with reasoning — a flat
  dollar delta would corrupt absolute chart levels, which is the opposite of what this plan builds);
  and a `/api/stocks/structural-stop` alias route (rejected — `find_structural_stop` is already
  instrument-agnostic and the existing endpoint takes exactly the inputs a stock has).
- **Known soft spot, recorded rather than hidden.** Tasks 5-11's synthetic-bar tests each begin with
  `if sig is None: pytest.skip(...)`, following the existing convention in
  `test_strategy_engine.py:310-312`. That means a formula bug *could* hide behind a signal that
  stops firing on the fixture. Mitigations: the ladder builder itself is tested directly with no
  skips at all; `test_every_exit_block_key_is_accepted_by_its_signal_function` catches the most
  likely cause of a signal silently disappearing (a config/signature mismatch); and Task 17 Step 3's
  manual pass exercises all seven strategies against real data. If a skip fires during
  implementation, treat it as a fixture to fix, not a test to accept.

## Post-implementation independent audit (round 1)

A fresh, independent subagent reviewed the implemented diff (not this plan) after Tasks 1-17
shipped. Findings, all fixed:

- **CRITICAL — `breakout_base_signal`'s stop was anchored on the far side of the base
  (`base_low` for a Bullish breakout), not the breakout level.** Once the target became the
  measured move instead of `entry + risk*rr_mult`, this made R:R < 1 for *every* possible input:
  risk = (base_high-base_low) + overshoot + buffer, reward = (base_high-base_low) - overshoot, so
  risk > reward for any overshoot > 0 — and the entry gate (`current > base_high`) guarantees a
  positive overshoot. Fixed by anchoring the stop at `base_high`/`base_low` (the breakout/breakdown
  level itself) instead — "back inside the level that was just broken," the classic
  breakout-invalidation pairing. Verified against the repo's own `_flat_base_then_breakout`
  fixture: R:R went from 0.52 to 1.67.
- **HIGH — no side validation on `/api/stocks/first-passage`.** A target or stop on the wrong side
  of entry isn't a valid exit ladder — it's already "hit" — which silently produced a bogus ~100%
  probability instead of a real error. Fixed with an explicit check in the endpoint (422, plain-
  string `detail` matching this file's existing validation convention).
- **HIGH — `StockPositionCard`'s overlay edits didn't invalidate a stale displayed
  Estimate/Check-structure result.** Editing the stop after running Estimate kept showing the OLD
  probability/expected-days next to the NEW stop, implying they were computed together. Fixed in
  `patch()`: whichever result depends on what just changed (and its in-flight request, if any) is
  cleared.
- **MEDIUM — `mean_reversion_vwap`'s GBM caveat didn't mention the intraday/daily timeframe
  mismatch.** Its signal and backtest run on 15m bars, but the first-passage estimator always
  simulates daily closes — a bigger mismatch than the general mean-reversion caveat already covers.
  Fixed with a distinct, longer caveat for this one strategy (`mean_reversion_vwap_daily` runs on
  daily bars like the estimator, so it keeps the generic caveat).
- **MEDIUM — two `pullback_ema` tests used `pytest.skip` on a non-fire, on a deterministic
  (non-random) fixture, so a real regression could hide as a silent skip.** Tightened to a hard
  assertion. All seven strategies' exit-thesis tests were also Bullish-only; Bearish-mirror coverage
  was added for all seven — the exact kind of untested branch the breakout_base bug above lived in.
- **MEDIUM — `resolve_multi_signal`'s `min_rung_r=0.5` floor, called with exactly ONE fired
  variant, could discard that variant's own valid target.** `mean_reversion_min_confirmations` is
  user-configurable down to 1, so this is reachable in production, not a theoretical edge case.
  Entry/stop with a single variant are exactly that variant's own — nothing is being merged — so
  the floor (there to stop a rung surviving a transplant onto another variant's wider stop) has no
  transplant to guard against and was discarding a rung the variant would have shown standalone.
  Fixed by passing a single variant's own ladder through unchanged.
- **LOW — `sharesT1+sharesT2+sharesT3` had no check against total `shares`.** Each rung's share
  count is editable independently, so nothing stopped the sum from exceeding the position's total
  shares — an oversell instruction. Fixed with a clamp in `patch()`: the rung just edited is capped
  to what's left after the others; if total `shares` itself shrinks below the existing allocation,
  every rung scales down proportionally.
- **LOW — `structural.distancePct` was captured but never rendered.** Added next to the
  structural-stop price, matching the options TradeCard's existing `"($price ($pct% away))"`
  format. `structural.confidence` stays unrendered — verified the options TradeCard never renders
  it either, so this is pre-existing parity, not a gap this feature introduced.
- **Investigated, not changed:** `pullback_ema_signal`'s R:R varies widely (0.19 to 2.31 across
  fixtures). Confirmed this is honest variation reflecting real setup quality, not a formula
  defect — there is no downstream R:R gate in the stock pipeline, matching the ladder builder's own
  "no R-relative floor by default" design.

Backend: 1621 passed, 1 skipped (up from 1607 baseline). Frontend: typecheck clean, 682 passed
(up from 672 baseline).

## Post-implementation independent audit (round 2)

A second, independently spawned subagent re-verified every round-1 fix against the actual code
(not the commit message) and re-ran the diff hunt, this time explicitly computing concrete numbers
rather than checking formula shape — the mistake that let the CRITICAL bug above through an earlier
personal (non-subagent) read. All eight round-1 fixes were confirmed genuinely fixed. Three new
findings, all fixed:

- **HIGH — the base_high anchor fix (round 1) doesn't hold when the breakout bar ITSELF has a
  wide range or wick relative to the tight base.** `atr = _atr(bars)` included today's bar, so one
  huge-range candle can dominate a 14-period average — reproduced at R:R = 0.19x with a 24-bar
  flat base (range 0.10) followed by a bar with a 30-point high-low range that still closed only
  $0.06 above the base. `base_high`/`base_low` already excluded today's bar
  (`base_bars = bars[-(lookback+1):-1]`); ATR was the one inconsistent scale. Fixed by computing
  `atr = _atr(bars[:-1])`, pre-breakout, everywhere in this function (the tight-base gate, the stop
  buffer, and the flat-base height fallback). A distinct "gap-and-crap" scenario the same finding
  raised (a large gap-up moving entry far from a base_high-anchored stop) was investigated and left
  as-is: the risk genuinely is entry-back-to-the-breakout-level, and a big gap has already spent
  part of the measured move before the signal fires — real information, not a bug, by the same
  no-R-floor philosophy already documented for `ma_crossover`.
- **HIGH — a card left open across a same-symbol re-scan kept showing (and could submit) the
  PREVIOUS scan's overlay.** `step-4-stocks/page.tsx`'s `openSymbol` isn't reset by `onRun()`, and
  `StockPositionCard`'s own overlay-reset effect only fires on a `card.symbol` change — so a
  same-symbol Run Scan with the card still open never re-derived the overlay from the fresh signal.
  Fixed by keying `StockPositionCard` on the signal itself (`stockPositionCardKey()` in
  `lib/stockScan.ts`: symbol + entry + stop + target), forcing a remount exactly when the
  underlying signal changes, never on an unrelated re-render.
- **MEDIUM — a target dropped for sitting on the wrong side of entry gave no user-facing
  warning.** `stockPositionLevels()` silently filters such a rung (and its allocated shares) out of
  the sell-to-close plan; `EditableField.save()` has no side check, so a fat-fingered T1/T2/T3 sent
  a partial ladder to the portfolio with no indication anything was dropped. Fixed by
  `invalidTargetRungs()` (`paperTrade.ts`, sharing `stockPositionLevels`'s own sign check) gating
  `onAddToPortfolio()`: it now blocks and names the bad target(s) instead of silently truncating.

Also fixed in passing while in this area: `step-4-stocks/page.tsx` and `step-5-strategy/page.tsx`
both still described `breakout_base`'s stop as "below the base low" / "above the base high" — the
pre-round-1 (buggy) anchor — even though round 1 had already moved the actual stop to the breakout
level. `step-5-strategy/page.tsx`'s whole `STRATEGIES` list had drifted from the reworked exit
theses in several other places too (`pullback_ema`, `ma_crossover`, `mean_reversion_rsi`,
`mean_reversion_vwap`, `mean_reversion_multi`); brought in line with the accurate, already-correct
text in `step-4-stocks/page.tsx`.

Backend: 1624 passed, 1 skipped (up from round 2 audit's 1623). Frontend: typecheck clean,
695 passed (up from 682).

## Post-implementation independent audit (round 3)

A third, independently spawned subagent re-verified all three round-2 fixes and hunted specifically
in areas the first two rounds under-scrutinized (strategy_watch_evaluator parity, the WFO/backtest
coupling, `targets` `?.length` vs `??` usage at every read site, the mean_reversion_multi variant
loop). Two of the three round-2 fixes were CONFIRMED FIXED outright (the pre-breakout ATR fix's
underflow/crash safety, and `invalidTargetRungs`'s boundary behavior); the other two were found to
be real but incomplete — genuinely closing the reported scenario while leaving a related one open.
All three new/incomplete findings, fixed:

- **HIGH — `breakout_base_signal`'s round-2 ATR fix left a worse failure mode: a large gap doesn't
  just produce a poor R:R (the accepted "honest information" case), it can outrun the FARTHEST
  measured-move extension entirely and fall through to `_build_target_ladder`'s generic
  degenerate-input fallback, fabricating a plausible-looking, exactly-2.0x R:R target with zero
  connection to the strategy's own thesis.** Reproduced: entry gapping to $115 against a $100.30
  base (height $0.60) produced a **$144.64 target at a clean 2.0× R:R** — the real measured-move
  objective was $100.90, 24x closer, already far behind entry. breakout_base is the only one of the
  seven strategies whose entire ladder (primary + both extensions) is anchored to a fixed price
  level rather than to entry, so it is uniquely exposed: every other strategy's ATR/R extensions are
  entry-relative and can never be "lapped" this way. Fixed by checking whether the farthest
  extension is still strictly beyond entry before calling `_build_target_ladder` at all; if not
  (and there's a genuine non-zero measured-move `height` to outrun — gated so the pre-existing
  zero-height-base fallback in `test_breakout_base_survives_a_zero_height_base` still fires), the
  signal now returns `None` instead of inventing a target. The moderate-gap "honest low R:R" case
  from round 2 (a gap that outruns only the primary rung, not the farthest extension) still fires
  unchanged, pinned by a new test alongside the fabrication-repro test.
- **MEDIUM — `stockPositionCardKey` (round 2) hashed only `target_price` (== `targets[0]`), not the
  full ladder, so `resolve_multi_signal` could return byte-identical entry/stop/target[0] across two
  scans while `targets[1]`/`[2]` differed** (e.g. a re-scan that adds a third confirming
  mean-reversion variant whose own rung is farther than the already-tightest one). The card would
  not remount, and `StockPositionCard`'s client-fabricated T2/T3 fallback (`t1+risk`, `t1+2*risk`)
  could reach Add to Portfolio instead of the fresh backend ladder — the exact class of staleness
  this key was built to eliminate, just not fully closed. Fixed by hashing the full `targets` array
  (falling back to `[target_price]` when absent/empty, matching `defaultOverlay()`'s own
  `?.length`-not-`??` convention).
- **MEDIUM — `mean_reversion_multi`'s per-variant loop always evaluates DAILY bars, with no
  special-casing for `_INTRADAY_STRATEGIES`, unlike the single-strategy path.** Including
  `"mean_reversion_vwap"` (the intraday variant — not `"_daily"`) in `mean_reversion_variants` would
  silently run its VWAP/ATR/entry-gate math on daily candles mislabeled as 15-minute bars: no
  error, just quietly wrong numbers with a plausible shape. Confirmed not reachable through the
  shipped UI today (`MeanReversionConfirmPanel` only offers rsi/bb/vwap_daily) — a live API footgun
  rather than an active bug. Fixed by rejecting the combination outright at the `/api/stock-scan`
  endpoint (422) rather than either silently mis-computing it or investing in full intraday-bar
  plumbing for a variant nothing calls yet.

No issues found in: `resolve_multi_signal`'s behavior at exactly 2 fired variants (uniform code path
for any count ≥ 2); the `stockPositionCardKey`/`invalidTargetRungs` sign-check boundary at
target == entry; `strategy_watch_evaluator.py`'s exit/param precedence (confirmed matching the
scan/backtest path); the WFO/backtest `exit:`+`params` coupling from Task 12; every `targets`
read site's `?.length`-not-`??` convention (`StockPositionCard`, `StockSendDialog`,
`step-4-stocks/page.tsx` all correct); the options TradeCard's `structuralStop.confidence`
non-rendering parity claim from round 2.

Fixing round 3's findings also surfaced a regression: `test_strategy_engine_bearish.py`'s
pre-existing `test_breakout_base_bearish_breakdown` fixture used a breakdown large enough to also
exhaust the farthest extension (the same fabricated-fallback case the HIGH finding above fixes) —
it only asserted price ordering, not target realism, so it had silently been exercising the
fallback path all along. Adjusted the fixture to a breakdown that stays within the ladder's reach,
preserving its actual intent (verify Bearish direction support).

Backend: 1627 passed, 1 skipped (up from round 3 audit's 1624). Frontend: typecheck clean,
697 passed (up from 695).
