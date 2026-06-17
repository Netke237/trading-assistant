# Bearish Trading Support — Design

**Date:** 2026-06-14
**Status:** Approved, pending implementation plan
**Author:** Kenneth + Claude

---

## Goal

Make Bamendjou usable for making money in a bearish market, across **both**
workflows: the **options screener** (7-step) and the **stock scanner**
(`step-4-stocks`, strategy-based). Today the scoring engine understands bearish
signals, but the surrounding plumbing is bullish-only or — worse — silently
broken for bearish.

---

## Background: what already works vs. what's broken

The backend **scoring engine** (`backend/app/scoring/stock_scorer.py`) is already
fully direction-aware: trend crossover, additive trend, relative strength,
pullback (Fibonacci bounce from swing low), and candle triggers (shooting star,
bearish engulfing, evening star) all invert correctly when `direction ==
"Bearish"`. `type Direction = 'Bullish' | 'Bearish'` is live, the Step 2 picker
offers both, `risk_rules.yaml` has separate `bearish_target_pct` /
`bearish_invalidation_pct`, and `scan.py` already selects PUT contracts for
bearish (`option_type = "C" if direction == "Bullish" else "P"`).

The gaps are operational, and they differ per workflow:

### Options screener gaps
1. **Regime gate fights bearish scans.** Step 3 maps `Bear` regime → `REJECT`
   tone unconditionally. A bearish scan in a bear market — ideal conditions —
   hits the same REJECT confirmation gate meant to block bullish trades in a
   downturn.
2. **No multi-leg spreads.** The contract schema carries a single `right` field
   (`'C' | 'P'`). No bear put / bear call spreads.
3. **Order side is implicitly BUY.** `SendToBrokerDialog` exposes no
   action/side; every order is a long-premium BUY.

### Stock scanner gaps (the footgun)
The stock scanner accepts `direction: Literal["Bullish", "Bearish"]` but does
not honor it where it matters:
- All 4 strategy signal generators in `strategy_engine.py` are hardcoded to
  `direction="Bullish"` and only detect uptrend setups.
- `strategy_backtest.py` always calls `self.buy()`; the `direction` parameter is
  stored on the result but never used.
- `StockPositionCard` computes T1/T2/T3 as `entry + N×risk` (always above
  entry), but its action button reads
  `card.direction === 'Bullish' ? 'BUY' : 'SELL'`.

**Net effect today:** a bearish stock scan places a SELL order with a stop
*below* entry and targets *above* entry — mechanically backwards for a short.
This is a live money risk, not just a missing feature.

---

## Scope (locked decisions)

| Decision | Choice |
|---|---|
| Options bearish scope | Long puts + spreads |
| Spread types | Both bear put (debit) **and** bear call (credit); screener picks the better per IV environment, the other attaches as an alternative |
| Broker routing | Manual copy-trade for now; IBKR button built but greyed ("coming soon") |
| Strike selection | Driven by editable Settings defaults, per horizon |
| Regime model | Regime is a **descriptor** (Bull / Bear / Choppy-Sideways); **alignment** of chosen direction vs. regime is the PASS / CAUTION / REJECT gate |
| Stock bearish | Build proper short signals for all 4 strategies (reverses an earlier "no stock shorts" decision) |

### Out of scope
- Live IBKR order routing (button is greyed; wiring stubbed behind it).
- Naked short calls/puts as standalone options positions (spreads only for the
  short-premium side).
- Inverse-ETF substitution.
- Margin/borrow/uptick-rule modelling beyond what a backtest needs to be
  directionally correct.

---

## Part 1 — Shared regime fix

Reframe `scanStore.regime` from a verdict into a descriptor, and add a separate
alignment verdict.

- **Regime descriptor** (right panel): `Bull | Bear | Choppy-Sideways`, shown
  plainly with no pass/fail coloring on the descriptor itself. EMA and VIX remain
  sub-indicators feeding the descriptor; VIX keeps its own pass/fail.
- **Alignment verdict** (status / gate), computed from `direction × regime`:

  | Direction | Regime | Verdict |
  |---|---|---|
  | Bearish | Bear | PASS |
  | Bullish | Bull | PASS |
  | Bearish | Bull | REJECT |
  | Bullish | Bear | REJECT |
  | either | Choppy-Sideways | CAUTION |

- The Step 3 confirmation overlay fires on **misalignment** (verdict = REJECT),
  not on "Bear regime exists."
- From direction+horizon onward, the existing PASS / CAUTION / REJECT status
  system is unchanged; it simply now carries the aligned direction context.

This logic is shared by both workflows (both read `scanStore.context.direction`
and `scanStore.regime`).

---

## Part 2 — Options workflow (Steps 6–7 + types)

### Step 6 — Contracts
For each candidate, surface three bearish structures:

| Structure | Mechanics | Primary when |
|---|---|---|
| Long put | Buy a put | Low IV |
| Bear put spread (debit) | Buy higher-strike put + sell lower-strike put | Low–medium IV |
| Bear call spread (credit) | Sell lower-strike call + buy higher-strike call | High IV |

- IV rank (from Step 5) vs. the Settings threshold decides the **primary**
  structure; the others attach via the existing `AlternativeContract` pattern.
- New table columns for spread rows: spread-type badge, net debit/credit, max
  gain, max loss, breakeven.
- Strikes chosen from Settings defaults (short-leg delta target + spread width).

### Step 7 — Trade card
- Single-leg put: unchanged card.
- Spread: a **two-leg panel** showing each leg (action, strike, right, expiry,
  qty), net debit/credit, max profit, max loss, breakeven.
- `SendToBrokerDialog`: **two states** —
  - *Manual (active):* clear copy-trade table of both legs to execute by hand.
  - *IBKR (greyed):* visible, disabled, labelled "IBKR — coming soon"; combo-order
    wiring stubbed behind it for later activation.

### Type changes
- Extend the contract/trade-card schema to carry `legs[]` for multi-leg
  structures (today: single `right`). A single-leg put is the 1-leg case.
- Spread entry carries: `spreadType: 'bear_put' | 'bear_call'`, `legs[]`,
  `netDebitCredit`, `maxProfit`, `maxLoss`, `breakeven`.

---

## Part 3 — Stock workflow (the big build)

Add a **bearish mirror** for each of the 4 strategies, and make the pipeline
direction-correct end to end.

| Strategy | Bullish (today) | Bearish (new) |
|---|---|---|
| pullback_ema | Pullback to EMA in uptrend | Pullback to EMA *resistance* in downtrend |
| breakout_base | Breakout above tight base | Breakdown below tight base |
| ma_crossover | Fast crosses above slow | Fast crosses below slow |
| mean_reversion_rsi | RSI oversold in uptrend | RSI *overbought* in downtrend |

Changes:
1. **Signal functions** in `strategy_engine.py` accept `direction` and branch
   (currently hardcoded `"Bullish"`). Bearish variants detect the mirror setup
   and return short-shaped entry/stop/target (stop **above** entry, target
   **below** entry).
2. **Backtest** (`strategy_backtest.py`) calls `self.sell()` when bearish; the
   long-only guard `if sl < entry < tp` gets a bearish branch `if tp < entry <
   sl`. The `direction` parameter becomes functional.
3. **Targets** T1/T2/T3 flip to `entry − N×risk`; stop moves above entry.
4. **`StockPositionCard`** renders short-aware targets and an explicit short
   label so the card is unambiguous.

This **removes the footgun**: bearish stock scans become mechanically correct.

---

## Part 4 — Settings

New **Spreads** section under "Score weights & parameters", following the
existing per-horizon tab pattern (Intraday / Swing / Position / Custom). All
fields ship with editable defaults:

| Param | Default | Meaning |
|---|---|---|
| Short-leg delta target | 0.30 | Where the sold leg sits on the delta curve |
| Spread width (points) | 5 | Distance between strikes |
| IV rank threshold (credit vs debit) | 50 | Above → credit spread is primary |
| Min credit to accept | $0.50 | Reject credit spreads below this |
| Max debit (% of width) | 40% | Cap debit relative to max gain |

---

## Untouched

Steps 1–2, the direction-aware scoring engine, watchlist, portfolio, calendar,
and the entire bullish path. The regime fix is conditional on chosen direction,
so existing bullish behavior is preserved.

---

## Testing strategy

- **Regime alignment:** unit-test the `direction × regime → verdict` matrix
  (all 5 rows), and that the Step 3 overlay fires only on REJECT.
- **Stock bearish signals:** for each strategy, a fixture where the bearish
  setup is present asserts a short signal with `stop > entry > target`; a bullish
  fixture asserts no bearish signal. Extend `test_stock_scan_router.py`.
- **Bearish backtest:** assert `self.sell()` path executes and PnL sign is
  correct for a known short trade.
- **Spread construction:** given IV rank above/below threshold, assert the
  correct primary structure and that net debit/credit, max gain/loss, and
  breakeven compute correctly for both spread types.
- **Settings:** defaults load; overrides persist per horizon.
- `npm run typecheck` clean; `pytest` green before each commit.

---

## Open risks / notes

- The earlier "no stock shorts" decision is reversed here. If short-selling
  stocks is undesirable in practice (margin, borrow), the bearish stock path can
  later be repointed at inverse ETFs without changing the signal logic.
- Spread pricing depends on an options chain with bid/ask per leg; confirm the
  data layer (`frontend/lib/api.ts` / backend contracts router) returns
  per-strike quotes needed to compute net debit/credit.
- **OPEN POINT — bearish option order side mapping.** Step 7 maps direction →
  action as `Bullish → BUY`, `Bearish → SELL`
  (`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:228`). The Tradier
  adapter now turns `SELL` into `sell_to_open`
  (`backend/app/data/tradier_paper.py`), i.e. **writing/shorting** the option. If
  the bearish strategy is meant to **buy puts** (long put, debit), this is wrong:
  a bearish entry should send `BUY` on a put contract, not `SELL`. Decide whether
  bearish = long puts (fix the frontend mapping to `BUY`) or = short calls/credit
  (current mapping is correct). Bullish buys are unaffected — they already work
  after the side fix. Surfaced 2026-06-15 while fixing the Tradier 502.
