# Exit points for stocks — targets & stops, strategy-aware

> **This is a brainstorm, not a plan.** Nothing here is decided, there are no tasks,
> no checkboxes, and no implementation code. It is a survey of what already exists in
> the repo, an honest assessment of what is genuinely missing, and 5 architectural
> options with tradeoffs, for Kenneth to pick from (or reject, or mix). Several of
> the options compose; one of them is nearly free and probably worth doing regardless
> of which of the others gets chosen.
>
> Companion reading: `docs/superpowers/plans/2026-08-20-tradecard-rr-and-profit-targets-redesign.md`
> documents the Options-mode Profit Targets UX this is trying to mirror.

---

## The ask

> "How can we extend the profit-target / exit-point concept to the Stocks scan path
> and the portfolio — determining exit points (profit targets **and** stops) for stock
> positions the way we do for option contracts — and strategy should be factored in."

Two halves worth separating up front, because they have different answers:

1. **"like options"** — the options Trade Card shows, per target: a price, an estimated
   value at that price, a *probability of getting there before expiry*, an *expected
   number of days*, and an R:R measured against a real structural stop. That's a
   probability layer over a level ladder.
2. **"strategy-aware"** — the *levels themselves* should come from the strategy's own
   logic, not from a uniform percentage ladder. A Bollinger mean-reversion trade and a
   base breakout do not have the same natural target.

The options path solves (1) and has no need for (2) — every option contract shares the
same generative model (the underlying's price process) so a fixed %-of-premium ladder is
defensible. The stock path is the reverse: (2) is where the real value is, and (1) is a
veneer that can be bolted on afterwards.

---

## Part 1 — What already exists

### 1.1 The options reference implementation

| Piece | Path | Instrument-specific? |
|---|---|---|
| Monte Carlo first-passage | `backend/app/scoring/first_passage.py` | **Mostly not** — see §1.4 |
| Structural stop finder | `backend/app/scoring/structural_stop.py` | **Not at all** — pure candles + direction + reference price |
| `/contracts/structural-stop`, `/contracts/first-passage` | `backend/app/routers/contracts.py` | Endpoints are namespaced under contracts, the *logic* isn't |
| R:R + target ladder | `backend/app/scoring/reward_risk.py` | **Yes** — Heston/BS repricing, premium stop basis. Not reusable for stocks |
| Entry quality | `backend/app/scoring/entry_quality.py` | **Yes** — bid/ask spread, min premium. Options only; stocks never call it |
| Rendering | `frontend/components/organisms/TradeCard/index.tsx` | — |
| Tunables | `backend/config/risk_rules.yaml` → `reward_risk:`, `first_passage:` | Mixed |

### 1.2 Stocks: strategy signals already carry entry / stop / target

`StrategySignal` (`backend/app/services/strategy_engine.py:208-228`) has carried
`entry_price`, `stop_price`, `target_price`, `atr`, and derived `risk` / `reward` /
`rr_ratio` properties since day one. Every signal function populates all of them. They
flow through `PositionCardData.strategy` (`frontend/types/stockDomain.ts:4-7`) to the UI.

**So "stock positions have no exit levels" is false — they have had them all along.**
The interesting question is *what those levels actually are*, and here's the table:

| Strategy | Stop formula | Target formula | Target strategy-aware? |
|---|---|---|---|
| `pullback_ema` | `fast MA ∓ ATR × atr_stop_mult` (1.5) | `entry ± risk × rr_target_mult` (2.0) | ✗ generic R-multiple |
| `breakout_base` | `base low/high ∓ ATR × 0.2` | `entry ± risk × rr_target_mult` (2.0) | ✗ generic R-multiple (**not** the base height) |
| `ma_crossover` | `slow MA ∓ ATR × 0.5` | `entry ± ATR × 3.0` | ✗ generic ATR multiple |
| `mean_reversion_rsi` | `swing low/high ∓ ATR × 0.2` | `entry ± ATR × 2.5` | ✗ generic ATR multiple (**not** the mean) |
| `mean_reversion_bb` | `lower/upper band ∓ ATR × stop_atr_mult` (0.5) | `entry ± risk × rr_target_mult` (2.0) | ✗ generic R-multiple (**not** mid-band) |
| `mean_reversion_vwap` | `entry ∓ ATR × 0.5` | `entry ± risk × 2.0` | ✗ generic (**not** VWAP) |
| `mean_reversion_vwap_daily` | `entry ∓ ATR × 0.5` | `entry ± risk × 2.0` | ✗ generic |
| `mean_reversion_multi` | inherits `fired[0]`'s levels | inherits `fired[0]`'s levels | ✗ and *non-deterministic* — whichever variant fired first sets the exits |
| `breakout_setup` (pre-breakout) | — | — | Emits `SetupSignal`, which has **no levels at all** |

**The finding that matters:** *stops are already genuinely strategy-specific* (MA-anchored,
base-anchored, swing-anchored, band-anchored, ATR-anchored — each one reflects that
strategy's actual invalidation thesis). *Targets are not.* Six of the seven pickable
strategies use the same "2× the risk" or "2.5–3× ATR" formula, differing only in which
`rr_target_mult` sits in `strategy_params.yaml`. The three mean-reversion strategies do
not target the mean they are reverting to.

That is unmistakably visible in the UI already. `frontend/app/(frame)/screener/step-4-stocks/page.tsx:41-57`
describes each strategy's exit to the user in prose:

- `breakout_base` → *"Measured move / trailing stop"*
- `mean_reversion_bb` → *"Return to mid-band / upper band"*
- `pullback_ema` → *"Prior high / trailing stop under higher lows"*
- `ma_crossover` → *"Cross back down"*

**None of those four exits exist in the code.** There is no measured move, no mid-band
target, no prior-high target, no cross-back exit, and no trailing stop anywhere in the
backend (verified: zero hits for trail/chandelier/breakeven outside options spread
breakevens). The screener's own copy is effectively an unimplemented spec for
strategy-aware targets, written by us, shown to the user today.

### 1.3 Stocks: the frontend already renders a ladder

`StockPositionCard` (`frontend/components/organisms/StockPositionCard/index.tsx`) already
has, and lets you edit: entry, stop, T1/T2/T3, per-target R:R, per-target % return, and a
per-target share allocation ("Sell-to-Close Plan"). Structurally it is already the stock
twin of the options Trade Card.

Two caveats:
- `defaultOverlay()` (`index.tsx:43-56`) invents T2 and T3 client-side as `entry ± 2R`
  and `entry ± 3R`. They are not strategy-derived, not backend-derived, not validated by
  any backtest, and not persisted.
- Missing versus the options card: probability, expected days, structural stop, and any
  R:R-vs-structural-stop column.

### 1.4 `first_passage.py` is *already* mostly a stock engine

This is the single most reusable asset. Decomposing `estimate_first_passage()`:

| Stage | Option-specific? |
|---|---|
| ATR → annualized `sigma_stock`, floored/ceilinged | **No** — pure stock |
| `trend_score` (0–100) → drift `mu` | **No** — and the input is literally a *stock* score |
| GBM path simulation `(n_paths × n_days)` | **No** — pure stock |
| Invalidation barrier test (`stock_paths <= invalidation_price`), probability + median days | **No** — a pure stock-price barrier test, already in the file, with zero option involvement |
| `sigma_iv` back-out from premium (`_derive_fallback_sigma`) | Yes |
| Stage-1 bisection: "what stock price yields premium × (1+pct)?" | Yes |
| Per-day Black-Scholes repricing loop, hit test on option value | Yes |

A stock profit target is *the invalidation branch with the comparison flipped* —
`stock_paths >= target_price` instead of `<=`. Line 241 already does exactly this shape.
Dropping the three option-specific stages makes the function **shorter and materially
faster** (the per-day BS reprice over 2000 paths is the expensive part), not harder.

Two inputs need substitutes for stocks:
- **`dte`** — stocks have no expiry, so the simulation needs an explicit holding horizon.
  A ready-made candidate already exists in config: `scoring_rules.yaml`'s
  `confidence_backtest.<horizon>.n_days` (intraday 5, swing 10, position 40), which is
  exactly "how long we expect a signal in this horizon to resolve". Reusing it keeps the
  Monte Carlo window consistent with the empirical confidence window.
- **`trend_score`** — `StockScoreCard.score` or its `trend` rule component is a natural
  drop-in; options already feed it `data.stockBreakdown.trend`.

Estimate: a `estimate_stock_first_passage()` sibling in the same module is on the order of
40–60 lines, sharing `_atr` and the sigma derivation, plus one endpoint. It needs no
changes to the existing options function.

### 1.5 The backtest already simulates strategy-specific exits

`run_strategy_backtest()` (`backend/app/services/strategy_backtest.py:113-121`) issues
`self.buy(limit=entry, sl=stop_price, tp=target_price)` on every fire. **The stop/target
exit engine already exists, per strategy, and is already what `step-6-backtest`'s win
rate and expectancy are computed from.** Any change to how targets are derived is
automatically validated by the existing backtest and by the WFO tuner
(`walk_forward.py` → `strategy_param_optimizer.py`), because `rr_target_mult` is already
in the `search:` grid for four of the strategies (`strategy_params.yaml:50, 69, 124`).

Note also what is computed and discarded: `stats["_trades"]` carries per-trade duration,
and only `ReturnPct` is read (`strategy_backtest.py:155`). "Expected days to target,"
per strategy, per symbol, is sitting unused in that dataframe.

### 1.6 An empirical first-passage estimator already exists

`backend/app/scoring/signal_confidence.py` is not usually described this way, but that is
what it is:

- `evaluate_fire()` (line 37) replays each historical signal fire and asks "did the
  favorable `atr_mult_target × ATR` barrier get hit before the adverse
  `atr_mult_stop × ATR` barrier, within `n_days`?" — a **target-before-stop first-passage
  test on real historical price paths**, no distributional assumption at all.
- `_measure_excursion()` (line 92) records, per fire, the realized **maximum favorable and
  maximum adverse excursion in ATR units** — textbook MFE/MAE analysis, the standard
  empirical method for placing profit targets and stops.

Today both excursion arrays are collapsed into a single `payoff_ratio` scalar in
`aggregate()` (line 150-153) and then thrown away. The *distribution* — which is what
would tell you "70% of past fires reached 1.5 ATR, 35% reached 3 ATR, median 6 days" — is
computed and discarded on every scan.

Caveat: `compute_confidence` replays `score_stock(...).status == "PASS"` (the scorer), not
the strategy signal function, so as written it is *scorer*-aware, not *strategy*-aware.
The strategy-aware equivalent is the `strategy_backtest` replay in §1.5.

### 1.7 The strategy-watch state machine already tracks armed exits

`strategy_watch_evaluator.py` holds, per watch, `{phase: armed, entry_price, stop_price,
target_price, direction}` and emits `exit_stop` / `exit_target` / `reversal` transitions
with full level detail (lines 153-231). It is already a live per-symbol exit-level tracker.

Limits: it only wires 5 of the 7 pickable strategies (`_SIGNAL_FNS`, line 35 — both VWAP
variants and multi are absent); its output goes to Gmail/Telegram notifications only,
never to a UI level display; and it is a *watch* concept (pre-entry monitoring), not the
position of record.

### 1.8 The portfolio already has stop / structural stop / targets — and never receives them

The portfolio side is, surprisingly, the most complete part of the stack:

- `PortfolioPosition` (`frontend/types/domain.ts:186-226`) has `stop`, `structuralStop`,
  and `targets: TargetLevel[]`. The backend model (`backend/app/models/portfolio.py`) and
  schemas mirror them. None of these fields are options-specific.
- The portfolio edit drawer (`frontend/app/(frame)/portfolio/page.tsx:489-534`) lets you
  edit stop, structural stop, and the full target list — **on stock rows too**; the
  editors are generic and the only stock/option branch in the page is a `× 1` vs `× 100`
  multiplier.
- `alert_generator.py` fires `TP_HIT` (against `targets[0].stockPrice`), `STOP_REACHED`
  (against `pos.stop`), and `STRUCTURAL_STOP_BREACHED` (against `pos.structural_stop`) —
  and **all three compare the live *stock* price**, not the option premium. They are
  already stock-native. Only `PREMIUM_STOP` is options-only.

And then:

```
// frontend/lib/paperTrade.ts:35-36  — buildPaperStockPosition()
stop:         0,
targets:      [],
```

**Every stock position added to the portfolio discards its stop and its entire target
ladder at the boundary.** The strategy computed them, the position card displayed them,
the user possibly edited them — and then `stop: 0`, `targets: []`. Which means TP_HIT,
STOP_REACHED and STRUCTURAL_STOP_BREACHED can never fire for a stock position, despite
being fully implemented, stock-native, and wired to notifications.

(`stockCardSnapshotOf()` does stash `c.strategy` in `tradeCardSnapshot`, but as an opaque
display blob — nothing reads it for alerting — and it snapshots the *pristine* signal, not
the user's edited overlay.)

---

## Part 2 — What is genuinely new work

Stripping out everything that already exists, the actual gaps are:

1. **The portfolio hand-off drops levels** (`paperTrade.ts:35-36`). Pure plumbing.
2. **Targets are not strategy-aware** — one generic R/ATR multiple across six strategies,
   contradicting the exit prose the UI already shows the user (§1.2).
3. **T2/T3 are fabricated client-side** at 2R/3R, invisible to the backtest and to WFO.
4. **No probability / expected-days** for stock targets.
5. **No structural stop on the stock path** — the finder is instrument-agnostic and unused
   there; only the endpoint's URL namespace ties it to contracts.
6. **No holding-horizon concept for stocks** — options have DTE, stocks have nothing.
   Must be chosen before any probabilistic estimate is meaningful.
7. **No trailing / adaptive stop** anywhere in the codebase, despite four strategies'
   UI copy promising one.
8. **Pre-Breakout mode has no exit levels at all** — `SetupSignal` carries none.

---

## Part 3 — Five approaches

### Approach A — Plumb the levels that already exist ("stop dropping the data")

Carry the strategy's `stop_price` / `target_price`, plus the user's edited overlay
(entry / stop / T1-T3 / share allocation), into `PortfolioPosition.stop` and
`.targets[]` instead of `stop: 0, targets: []`. Optionally do the same on the broker-send
path in `StockSendDialog`.

No new math, no new engine, no new endpoint, no new UI.

**Tradeoffs**
- ✅ Cheapest possible change; unlocks TP_HIT / STOP_REACHED / STRUCTURAL_STOP_BREACHED for
  stock positions — three fully-built, already-notified alert types that currently cannot
  fire for stocks at all.
- ✅ Strategy-aware "for free": the stop it carries is already the strategy's own
  (MA/base/band/swing-anchored, per §1.2).
- ✅ Makes the portfolio edit drawer meaningful for stock rows for the first time.
- ⚠️ Needs a decision on the pristine-vs-edited question: persist the signal's levels, or
  the user's overlay? (The overlay is what they actually intend to trade.)
- ⚠️ Watch out for `floorStop()` in `portfolioStore.ts` — it treats a non-positive stop as
  "unset", so this must send a real positive number, not 0.
- ❌ Delivers none of the options-parity features (no probability, no expected days).
- ❌ T2/T3 remain the arbitrary 2R/3R ladder — it just persists an arbitrary ladder instead
  of discarding it.

*Standalone verdict: not the answer to the question, but arguably a bug fix that should
happen regardless of which of B–E is chosen, since every other approach ultimately needs
levels to survive the portfolio boundary.*

---

### Approach B — Reuse `first_passage.py` for stocks (shared probabilistic engine)

Add an `estimate_stock_first_passage()` sibling that keeps the GBM + barrier machinery and
drops the three option stages (§1.4). New endpoint (either `/stocks/first-passage` or a
generalization of the existing one). Frontend: an "Estimate" button on `StockPositionCard`,
rendering probability + expected days per target, plus probability of hitting the stop
first — visually the same card as the options Profit Targets section.

Strategy enters only through the *inputs*: entry, stop, targets, and the drift score.
The math is shared and strategy-agnostic.

**Tradeoffs**
- ✅ Maximum consistency with the options UX — same numbers, same labels, same mental
  model, one engine to reason about and maintain.
- ✅ The reuse is real, not aspirational: the invalidation branch is already a pure stock
  barrier test; the stock version is a strict subset and runs *faster* than the options one.
- ✅ Config already exists (`risk_rules.yaml → first_passage:`) and can be shared.
- ✅ Pairs naturally with lifting `structural_stop.py` onto the stock path (gap 5), giving
  stocks the same "R:R vs. a real chart level" column.
- ⚠️ Requires deciding the holding horizon (gap 6). `confidence_backtest.n_days` is a
  defensible default but it *is* a decision, and the probability number is highly sensitive
  to it — "72% chance of +6%" is meaningless without "…within 10 days".
- ❌ **GBM is a poor generative model for three of the seven strategies.** A mean-reversion
  trade's entire thesis is that drift is transient and price snaps back; simulating it with
  a constant drift derived from a trend score gets the dynamics backwards. The number would
  look authoritative and be systematically wrong for `mean_reversion_*`.
- ❌ Doesn't answer the "strategy-aware" half at all — it decorates whatever levels it is
  handed.

---

### Approach C — Empirical MFE/MAE calibration from the existing replay machinery

Stop discarding the excursion distributions (§1.6). Keep `favorable_atrs` / `adverse_atrs`
(and/or extend `strategy_backtest` to emit per-trade MFE/MAE and duration from
`stats["_trades"]`), then derive:

- **T1/T2/T3** = percentiles of the realized favorable-excursion distribution for this
  symbol × strategy × direction (e.g. 70th / 45th / 20th percentile of MFE).
- **Stop** = a percentile of the adverse-excursion distribution — a stop that historically
  survived N% of winning trades.
- **Probability of reaching Tn** = the empirical fraction of past fires that reached it.
- **Expected days** = the empirical median duration to that excursion.

**Tradeoffs**
- ✅ **Strategy-aware by construction**, not by formula — it replays that strategy's own
  signal function on that symbol's own history. No one has to hand-write seven target
  formulas and argue about them.
- ✅ Zero distributional assumption; handles mean-reversion correctly and automatically
  (it will simply *show* that mean-rev MFE tops out near the band/mean, which is the
  correct answer).
- ✅ The probability and expected-days numbers are empirical, arguably more trustworthy
  than B's simulated ones, and satisfy the options-parity ask without GBM.
- ✅ Reuses `signal_confidence` / `strategy_backtest` / WFO infrastructure that is already
  cached, thread-pooled, and battle-tested.
- ❌ **Sample-size fragile.** `min_samples` is 20 and `compute_confidence` already returns
  `None` confidence often enough that the UI has a dedicated "not enough history" string.
  Many symbol × strategy pairs will produce no ladder at all, needing a fallback.
- ❌ Backward-looking and slow — these replays are cached and off-thread *because* they are
  expensive; per-scan-candidate percentile computation adds real latency.
- ❌ Per-trade MFE/MAE is not something `backtesting.py` exposes as standard columns, so the
  strategy-aware variant needs new tracking (the `signal_confidence` path already has it,
  but is scorer-driven rather than strategy-driven — see §1.6's caveat).
- ⚠️ Risk of overfitting to one symbol's history; the WFO framework exists partly to guard
  against exactly this and should probably be in the loop.

---

### Approach D — Declarative per-strategy exit policies

Add an explicit `exit:` block per strategy in `strategy_params.yaml`, sitting alongside the
existing `active:` / `search:` entry params, describing that strategy's *actual* exit
thesis — and have `strategy_engine.py` build the target ladder (and any trail rule) from it
instead of a uniform `rr_target_mult`. Roughly, the policies the UI copy already promises:

| Strategy | Natural target thesis | Natural stop thesis |
|---|---|---|
| `pullback_ema` | prior swing high/low, then R-multiple extensions | current: MA ∓ ATR (keep); trail under higher lows after T1 |
| `breakout_base` | **measured move** — project base height (`base_high − base_low`, already computed at line 363-364) 1×/1.5×/2× off the breakout | back inside the base |
| `ma_crossover` | ATR extension ladder, exit on cross-back | slow MA ∓ ATR (keep) |
| `mean_reversion_rsi` | RSI returns to mid (50) / the trend SMA | swing ∓ ATR (keep) |
| `mean_reversion_bb` | **mid-band, then opposite band** (both already computed, line 553) | band ∓ ATR (keep) |
| `mean_reversion_vwap(_daily)` | **VWAP itself**, then an extension past it (already computed) | entry ∓ ATR (keep) |
| `mean_reversion_multi` | the *tightest* of its fired variants' targets (deterministic) | the widest of their stops |

Nearly every input is already computed inside the respective signal function and thrown
away in `detail{}`.

**Tradeoffs**
- ✅ This *is* the "strategy-aware" ask, directly. It closes the gap between what the Step 4
  picker tells the user the exit is and what the code does.
- ✅ Makes T2/T3 meaningful rather than a client-side 2R/3R invention, and moves them
  backend-side where the backtest and the WFO tuner can see them.
- ✅ Config-driven, so it lands in the existing tunable surface (`strategy_params.yaml`, the
  Step 3 Execution Parameters panel) rather than being hard-coded.
- ✅ Automatically validated: `strategy_backtest` already feeds `target_price` into `tp=`,
  so a policy change immediately shows up in `step-6-backtest` win rate / expectancy.
- ⚠️ That same coupling is a hazard: changing targets changes every historical backtest and
  every tuned parameter set. Win rates will move. Existing WFO proposals may need re-running.
  This is honest (the old targets were arbitrary) but it is not a quiet change.
- ❌ Seven formulas to write, defend, and test — more code and more judgment calls than any
  other option here, and each one is a place to be wrong.
- ❌ On its own it delivers no probability / expected-days, so it doesn't look like the
  options card.
- ⚠️ Trailing stops (four strategies' copy promises one) are a notably bigger lift than
  static targets: they need per-bar state, which the current stateless `signal_fn(bars) →
  levels` shape doesn't have. Could be scoped out, or pushed into Approach E where the
  state machine already exists.

---

### Approach E — Extend the strategy-watch state machine to own live exit levels

Treat `strategy_watch_evaluator.py` as the home for live exit tracking: it already holds
armed `{entry, stop, target}` per symbol and already detects `exit_stop` / `exit_target`.
Surface that state to the frontend (the `/strategy-watch` page and/or the portfolio row),
and let it maintain *evolving* levels — trail the stop after T1, move to breakeven, re-arm
on reversal.

**Tradeoffs**
- ✅ The state machine, dedup logic, and transition events already exist and are tested; a
  trailing stop is natural here and unnatural anywhere else in the current architecture.
- ✅ It is the only component in the stack that could implement the "trailing stop under
  higher lows" the UI already promises.
- ❌ **Wrong system of record.** A watch is a pre-entry subscription; a portfolio position is
  a thing you own. Exit levels for an owned position belong with the position
  (`PortfolioPosition.stop` / `.targets`, which already exist and already drive alerts) — not
  in a parallel watch store that may not even have a subscription for that symbol.
- ❌ Covers only 5 of 7 strategies today (`_SIGNAL_FNS`, line 35), and its output path is
  Gmail/Telegram, not the UI — so "display exit levels" means new plumbing anyway.
- ❌ Would create a second, competing source of truth for "where is my stop", which the
  portfolio alert path would not see. Divergence between the watch's stop and the
  position's stop is a real correctness hazard for an app that can auto-trade.
- ✅ …**as a consumer** rather than an owner, though, it is excellent: if D's exit policy is
  a shared function, the watch evaluator, the backtester, the position card, and the
  portfolio all read the *same* levels, and the state machine becomes the place trailing
  logic lives without owning the definition.

---

## Part 4 — Recommendation

**Not one approach — a layering, in this order.** The ask has two halves (§"The ask") and
no single approach covers both honestly.

**A first, unconditionally.** `stop: 0, targets: []` is a data-loss bug, not a design
choice. It costs almost nothing to fix and it is a prerequisite for every other approach:
whatever levels B/C/D produce still have to survive the portfolio boundary to be alerted
on. Fixing it alone lights up three already-built, already-notified alert types for stock
positions.

**Then D — this is the actual answer to "strategy-aware".** The stops are already
strategy-specific and good; the targets are the half that isn't, and the Step 4 picker is
already telling the user what they should be. Measured moves for breakouts, mid-band and
opposite band for Bollinger reversion, VWAP for VWAP reversion — the inputs are all already
computed inside the signal functions. Doing this makes T2/T3 real, moves them backend-side
where `strategy_backtest` and WFO can validate them, and closes a copy-vs-code gap that is
visible to the user today. Scope trailing stops *out* of the first pass; static
strategy-aware ladders are most of the value at a fraction of the risk.

**Then B as the probability veneer.** Once the ladder is meaningful, wrap it in the shared
first-passage engine so the stock card gains "probability of reaching T2 / expected days /
probability of stopping out first" and looks like its options twin. Lift `structural_stop.py`
onto the stock path at the same time — it is instrument-agnostic and gives stocks the same
"R:R vs. a real chart level" column, plus it populates `PortfolioPosition.structuralStop`,
which already has a working alert.
Two honest conditions on B: pick and *display* the holding horizon
(`confidence_backtest.n_days` is the natural default), and consider labelling or suppressing
the probability for the `mean_reversion_*` strategies, where a constant-drift GBM
misrepresents the dynamics.

**Use C offline, not at scan time.** MFE/MAE percentile analysis is the right way to *choose
D's multiples and percentiles* — feed it through the existing WFO tuner as a calibration
input rather than as a per-candidate runtime dependency. That sidesteps its two real
weaknesses (sample-size gaps and latency) while keeping its main strength: the defaults
stop being arbitrary and start being measured. If the empirical distributions turn out to be
rich and stable per symbol, promoting C to a runtime display later is easy.

**Treat E as a consumer, not an owner.** If D's exit policy is a shared function rather than
inline code in each signal, then the watch evaluator, backtester, position card, and
portfolio all read the same levels — and E becomes the natural (later) home for trailing
logic without forking the definition of "where is my stop".

### Three things worth deciding early

1. **Which stop is *the* stop?** After this, a stock position could have three: the strategy
   stop, the structural stop, and a risk-sizing stop. The options card already has this
   ambiguity and resolves it by convention (premium stop is the risk basis; structural stop
   is the R:R reference). Stocks need the same explicit convention, and the UI should show
   when they disagree.
2. **Pristine or edited?** Persist the strategy's computed levels, or the user's overlay?
   Different answers for the alert path (the user's) and the analytics path (the strategy's).
   Storing both is cheap and probably right.
3. **Pre-Breakout mode.** `SetupSignal` has no levels at all, so nothing here reaches it.
   Either it stays a pure discovery surface, or it needs a way to project levels from the
   swing/Fibonacci structure it already computes.
