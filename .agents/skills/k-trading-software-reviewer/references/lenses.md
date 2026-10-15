# The panel's lenses

Each lens is a list of questions, not a checklist of verdicts. Answer the ones that apply,
with `file:line` evidence. A lens question that doesn't apply needs no answer — this is about questions, not files; every file still gets its coverage status (SKILL.md rule 8).

## The Trader

**Edge and entries**
- Does the scoring stack (trend + pullback + trigger + event + vol, or whatever it is now)
  express the stated edge, or can the weights let a weak setup through? Work one borderline
  example through the weights to show it.
- Are horizon weights (intraday / swing / position) genuinely different, or copy-pasted?
- Bearish side: its own entry, exit and invalidation, or a mirror with sign bugs? Mirror code
  breaks in retracement direction, candle detection and target/stop placement — check each.
- Does the regime engine actually gate entries (trace it into the scan and the auto-trader),
  or is it only displayed?

**Options and contract selection**
- For long premium: DTE vs intended holding time (theta), delta band, IV ceiling vs where IV
  typically sits for the names traded, earnings inside the holding window (IV crush).
- For spreads: which structures, how width and strikes are chosen, max loss vs max profit,
  short-leg assignment risk (ex-dividend for short calls), pin risk at expiry, whether the
  spread's R/R is computed on the net debit/credit and a real fill price.
- Liquidity: can the hard-reject floors (volume, OI, spread %) actually be exited at size, at
  the price the model assumes (mid? natural?).
- R/R honesty: is the risk basis (premium stop %, structural stop, ATR stop) consistent with
  the target basis? Does the stop on the option correspond to the stop on the underlying the
  trader sees? If there are several stop definitions, which one wins, and does the trade card
  show that one?

**Reference points** (prompts, not gates): 30–90 DTE for long premium, delta with real
directional exposure (~0.30–0.70), buy premium when IV isn't already rich, spread small vs
premium, OI deep enough to exit, chart R/R around 2:1 or better, volume surge ~1.5x on
triggers.

## The Quant

**Evidence quality**
- Sample size: for every win rate / hit rate the system displays or gates on, how many trades
  back it? Show the 95% interval: `p ± 1.96·√(p(1−p)/n)`. At n = 20 and p = 0.5 that is ±22
  points — say plainly when a gate is deciding on noise.
- Multiple testing: how many parameter combinations does the optimizer search
  (`param_combos` × strategies × symbols)? The best of many backtests is biased upward; is
  there a penalty (complexity penalty, deflated Sharpe, out-of-sample minimums) and is it
  applied before or after selection?
- Walk-forward integrity: do `build_folds` windows overlap? Is out-of-sample data ever used to
  choose parameters? Are `degradation_pct` / `consistency` used to *reject* params, or only
  reported?
- Lookahead and leakage: does every signal, regime label, confidence replay and indicator only
  see bars up to the decision bar? Check the tests exist *and* that they test the live code
  path, not a copy.
- Costs: do backtest costs (fees, slippage) match what the live instrument costs? Options
  crossing a wide spread cost far more than a stock trade.
- Backtest-engine honesty: read the engine's warnings. Trades still open at the end left out
  of the stats, or a stop/target and its entry in the same bar executed on the next bar,
  both bias results. Say which way.
- Independent samples: does a replay or backtest count every consecutive day of the same setup
  as a new sample? Overlapping samples inflate n; count distinct setups before computing an
  interval.
- Planned vs realised R/R: a high win rate with negative expectancy usually means targets sit
  closer than stops. Check the planned R/R of the actual trades, not the configured multiples.
- Data sufficiency: does the history available cover the warm-up periods and walk-forward
  windows the config asks for? One year of data is one regime.
- Universe: is the symbol list today's constituents applied to the past (survivorship bias)?

**Models**
- "Confidence" scores: derived from an actual historical replay or a static weight? Is it
  calibrated — do signals shown at 70 hit about 70% of the time? If nobody measured that, say
  "uncalibrated".
- Monte Carlo first-passage: GBM assumes no fat tails and no volatility clustering; how is
  drift derived (from a score → an assumed drift is a modelling choice, not data)? Are sigma
  floors/ceilings masking bad inputs?
- Option repricing (Heston / Black-Scholes): where do the parameters come from, and how wrong
  can the repriced value at the target be?
- Regime models (HMM etc.): number of states, retraining cadence, and whether labels are
  computed with future data (smoothed vs filtered probabilities).

## The Risk Manager

**Missing data**
- For every gate, what happens when its input is missing (no earnings date, no IV rank, no
  quote, no regime)? Fail-open (full points / pass) on missing data is a finding.

**Sizing and limits**
- Survive a losing streak: at the maximum allowed loss per trade, how many consecutive losers
  until the portfolio is down 10%, 20%? Show the arithmetic.
- Concentration: per-position caps, per-symbol caps, per-sector, total exposure — per
  instrument type. Are stocks and options capped on the same basis? Correlated positions
  (same sector, all long beta) count as one bet.
- Is sizing volatility-aware or conviction-only? Does a higher-vol name get the same dollars?

**Execution safety** (be hardest here)
- Pre-trade: what gates run before an order (exposure, liquidity, events, regime, daily loss)?
  Which are hard blocks and which are warnings?
- Order path: live vs paper enforcement, fail-closed behaviour, double-fire races, stale
  prices, partial fills, broker/API errors, restart mid-order.
- Post-entry: is there a protective order at the broker, or only an alert? What happens on an
  overnight gap through the stop, a halt, a regime flip while positions are open?

## Cross-parameter pass (mandatory in modes A and B)

Build a small table of related limits and check each pair for contradictions. Categories to
cover — find the actual keys, don't assume these names:

| Check | Question |
|---|---|
| Per-trade loss vs daily loss | Can one trade at the maximum allowed loss exceed the daily loss limit? Is the per-trade limit a hard block or only a warning? |
| Per-trade loss vs sizing caps | Do contract/share caps and position-% caps actually keep a stopped-out trade inside the per-trade loss limit? |
| Stock vs option caps | Are the two instrument types capped consistently, and is the total (stocks + options) bounded? |
| Backtest costs vs allowed liquidity | Is the modelled slippage consistent with the widest bid-ask spread the contract filter still accepts? |
| Walk-forward windows vs data | Do train + test windows and indicator warm-ups fit in the history actually available? |
| Minimum-trade gates | Do the backtest, optimizer and confidence gates use consistent minimum sample sizes, and are they statistically meaningful? |
| Stop definitions | Premium stop %, structural stop, ATR stop, auto-trader stop — which one each path uses, and do they agree? |
| DTE vs holding horizon | Does the DTE rule leave time value at the planned exit for every horizon preset? |
| Walk-forward windows vs code minimums | Does each train and test window contain at least the minimum bars the optimizer and backtest engine require (plus indicator warm-up)? A test window below the minimum silently produces zero-trade folds. |
| Config vocabulary vs code | Do enum-like config values (direction, strategy names, horizon keys) match exactly what the code compares against, including case? A mismatch runs the wrong branch silently. |
| Account value basis | Is the portfolio value every % cap multiplies live from the broker or typed by hand? Do fallbacks in code use the same number as the YAML? |
| Thresholds vs their mirrors | Do YAML thresholds match the frontend mirrors and `SCORING_RULES.md`? |
| Dead or unmeasured config | Keys no code reads, and values marked UNMEASURED that sit in a live gate. |

A contradiction is a finding even if each value alone is reasonable. Before flagging, check
the comments: two similar-looking numbers that measure different things (and say so) are not
a contradiction.

## Stress test

For each scenario, trace what the code does; where it's unhandled, say "not handled — here's
the exposure":
clean uptrend · downtrend · volatility spike (VIX 20 → 40) · earnings inside the holding
window · overnight gap through the stop · trading halt · regime flip with positions open ·
broker API down at the moment of an order.
