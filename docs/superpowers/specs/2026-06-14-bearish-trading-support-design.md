# Bearish Trading Support — Design (v2)

**Date:** 2026-06-14 (rev. 2026-06-17 after full codebase screen)
**Status:** Approved design; implementation plan derived in
`docs/superpowers/plans/2026-06-17-bearish-trading-support.md`
**Author:** Kenneth + Claude

---

## Goal

Make Bamendjou able to make money in a bearish market across **both** workflows —
the **options screener** (7-step) and the **stock scanner** (strategy-based) — by
**mirroring the existing bullish logic wherever applicable**, and fixing the
places where a bearish path exists in name but is broken or backwards.

---

## Method: full codebase screen (2026-06-17)

Four parallel read-only screens covered: the options trade/execution path, the
stock scanner + strategies + backtest, the newer analytics layers (Markov
regime, conviction, sentiment, fundamental health, walk-forward optimization),
and the frontend direction plumbing. Disputed findings were re-read line-by-line
against source before being recorded here.

### Already direction-aware (no change needed)
- `backend/app/scoring/stock_scorer.py` — trend (crossover + additive), relative
  strength, FVG, pullback (Fibonacci), candle triggers all branch on
  `direction`.
- `backend/app/services/regime_omm.py` — `conviction(signal, direction)` returns
  a **signed** value (positive = tailwind). The regime gate, conviction sizing,
  and regime filter all consume signed conviction, so they are symmetric across
  directions.
- `backend/app/services/regime_hmm_daily.py` — HMM labels states by mean return
  (objective), no direction needed.
- `backend/app/routers/scan.py` — option type (`"C" if Bullish else "P"`),
  target/stop math (`bullish_*`/`bearish_*` pcts), and `is_call` flag to
  `reward_risk` are all correct for bearish.
- `backend/app/scoring/reward_risk.py`, `contract_validator.py` — delta logic
  branches on `is_call`; validator uses `abs(delta)`. Correct.
- Walk-forward optimizer (`walk_forward.py`, `strategy_param_optimizer.py`) and
  `strategy_tuning.py` thread `direction` through every backtest call.
- Frontend rendering ternaries (watchlist, portfolio, SymbolHeader,
  ValidationTable, AutoTradeArm, StockSendDialog) correctly branch Bull/Bear.

### Broken or bullish-only (the work)

| # | Location | Problem |
|---|---|---|
| B1 | `step-7-trade-card/page.tsx:230,254` | Order action `direction === 'Bullish' ? 'BUY' : 'SELL'`. A bearish **long put** must be BUY; this sends SELL → `sell_to_open` (naked short) via `tradier_paper.py:23`. |
| B2 | `step-6-contracts/page.tsx:70` | Hardcodes `api.getContracts(c.symbol, 'C', …)`. `/api/contracts` (`contracts.py:23`) honors the passed `right` and **ignores** `direction`, so a bearish scan shows **calls**. |
| B3 | `strategy_engine.py` (all 4 signal fns) | Hardcode `direction="Bullish"`, only detect uptrend setups, no `direction` param. |
| B4 | `strategy_backtest.py:105–106` | Guard `if sl < entry < tp` + always `self.buy()`. Bearish (stop>entry>target) never trades. |
| B5 | `stock_scan.py` signal call | Calls `signal_fn(bars, …)` without `direction`. |
| B6 | `StockPositionCard/index.tsx:45,138,141` | `risk = entry - stop` goes negative for shorts; `riskDollars` negative; `rrAt` guard `riskPerShare > 0` returns 0 → R:R always shows 0 for shorts. |
| B7 | `RunScanButton/index.tsx:106,191` | Regime confirm gate fires only for `direction === 'Bullish'`; dialog text hardcodes "Bullish". |
| B8 | `step-1-regime` → `scanStore` | `combinedRegime` (a `Status`) is set from `r.overall` (direction-agnostic market health), baking a verdict into a market reading. Should be **alignment** of direction × regime descriptor. |
| B9 | `strategy_watch_evaluator.py:7,100,151` | Strategy-watch alerts are bullish-only ("buy setup"); reversal "wired but dormant". |
| B10 | `fundamentals_scorer`/`stock_scorer.py:1031–1043` | Gate demotes weak fundamentals for bullish; bearish is display-only. The true mirror should demote **strong** fundamentals for shorts. |
| B11 | `strategy_param_store.py:36–42,85–112` + `strategy_params.yaml` | Tuned `active` params are **not keyed by direction**; a bearish tuning run would overwrite bullish params. `mean_reversion_rsi` has only `rsi_oversold`, no `rsi_overbought`. |
| B12 | Options contract schema (`types/domain.ts`, backend) | Single `right` only; no multi-leg / spread structure. |

---

## Scope (locked decisions)

| Decision | Choice |
|---|---|
| Options bearish scope | Long puts + bear put spread (debit) + bear call spread (credit) |
| Spread primary selection | IV rank (Step 5) vs Settings threshold: above → credit primary; below → debit primary; the other(s) attach as `AlternativeContract` |
| **Order side** | **Derived from structure/leg, never from direction.** Long put = BUY. Bear put spread = BUY higher-strike put + SELL lower-strike put. Bear call spread = SELL lower call + BUY higher call. |
| Broker routing | Manual copy-trade now; IBKR button built but greyed ("coming soon") |
| Strike selection | Editable Settings defaults, per horizon |
| Regime model | Regime = descriptor (Bull / Bear / Choppy-Sideways). `combinedRegime` Status = **alignment** of chosen direction × descriptor. |
| Stock bearish | Mirror all 4 strategies, fix backtest + position card + alerts |
| Fundamentals gate | **Full mirror**: bullish demotes weak; bearish demotes strong (don't short quality). Safety reject still applies to both. |
| Tuned params | Keyed by direction (`active.bullish` / `active.bearish`); add `rsi_overbought` |

### Out of scope
- Live IBKR routing (greyed; wiring stubbed).
- Naked short calls/puts as standalone positions (short premium only inside a
  defined-risk spread).
- Inverse-ETF substitution.
- Margin/borrow/uptick modelling beyond backtest correctness.

---

## Part 1 — Shared regime alignment (B7, B8)

Reframe regime from verdict to descriptor; make the gate an alignment verdict.

- **Descriptor** (right panel / Step 1): `Bull | Bear | Choppy-Sideways` from
  `omm.state`, shown plainly. EMA + VIX remain sub-indicators; VIX keeps its own
  pass/fail. No pass/fail tint on the descriptor itself.
- **Alignment verdict** drives `scanStore.combinedRegime` (`Status`), computed
  from `direction × descriptor`:

  | Direction | Descriptor | Verdict |
  |---|---|---|
  | Bearish | Bear | PASS |
  | Bullish | Bull | PASS |
  | Bearish | Bull | REJECT |
  | Bullish | Bear | REJECT |
  | either | Choppy-Sideways | CAUTION |

- Because StepNavBar, `REGIME_FIT`, and the gate already consume the
  `combinedRegime` Status, recomputing it as alignment auto-fixes them. Only
  `RunScanButton` needs its hardcoded `direction === 'Bullish'` removed and its
  dialog text made direction-aware.
- Alignment must recompute when direction changes (direction is chosen at
  `step-3-direction`, after Step 1 sets the descriptor). A pure helper
  `alignmentVerdict(direction, descriptor): Status` is the single source of
  truth, called from both Step 1 and Step 3.

---

## Part 2 — Options single-leg fix (B1, B2)

The footgun, fixed first because it is small and currently dangerous.

- **B2:** Step 6 fetches `right = direction === 'Bullish' ? 'C' : 'P'`.
- **B1:** Order action derives from the contract/structure, not direction. A
  long single-leg option (call or put) is always **BUY to open**. Replace
  `direction === 'Bullish' ? 'BUY' : 'SELL'` with the structure's leg action
  (single long leg → `'BUY'`).

This alone makes "buy a put on a bearish setup" correct end to end.

---

## Part 3 — Options spreads (B12)

- **Types:** extend the contract/trade-card schema with an optional `legs[]` and
  spread metadata. A single-leg option is the 1-leg case.
  ```ts
  type SpreadType = 'single' | 'bear_put' | 'bear_call';
  interface OptionLeg { right: 'C'|'P'; strike: number; expiry: string;
    action: 'BUY'|'SELL'; qty: number; bid: number; ask: number; }
  // TradeCardData gains: spreadType, legs[], netDebitCredit, maxProfit,
  //   maxLoss, breakeven  (all optional; absent ⇒ legacy single-leg)
  ```
- **Construction (backend):** from the put/call chain + Settings defaults
  (short-leg delta target, width), build the two legs, compute net debit/credit,
  max profit, max loss, breakeven. IV rank vs threshold picks the primary
  structure; the others attach via the existing `AlternativeContract` list.
- **Step 6:** new columns for spread rows (type badge, net debit/credit, max
  gain/loss, breakeven).
- **Step 7:** two-leg panel for spreads; `SendToBrokerDialog` manual copy-trade
  table active, IBKR greyed.

---

## Part 4 — Stock scanner bearish (B3, B4, B5, B6, B9)

Mirror each strategy and make the pipeline direction-correct end to end.

| Strategy | Bullish (today) | Bearish mirror |
|---|---|---|
| pullback_ema | Pullback to EMA in uptrend | Pullback to EMA resistance in downtrend |
| breakout_base | Breakout above tight base | Breakdown below tight base |
| ma_crossover | Fast crosses above slow | Fast crosses below slow |
| mean_reversion_rsi | RSI oversold in uptrend | RSI overbought in downtrend |

- **B3:** each signal fn takes `direction`, inverts its checks, and returns
  short-shaped entry/stop/target (stop **above** entry, target **below**).
- **B4:** backtest branches — `if direction == "Bullish": if sl < entry < tp:
  self.buy(...)` else `if tp < entry < sl: self.sell(...)`. Signal call passes
  `direction`.
- **B5:** `stock_scan.py` passes `direction=req.direction` into the signal fn.
- **B6:** `StockPositionCard` uses `Math.abs(entry - stop)` for risk, dollar
  risk, and R:R; profit/tone computed direction-aware.
- **B9:** strategy-watch alerts use direction-aware text ("short setup" /
  "long setup") and fire on bearish signals now that they exist.
- Step-4 strategy descriptions become direction-aware (shown per chosen
  direction).

---

## Part 5 — Fundamentals gate mirror (B10)

`stock_scorer.py` fundamentals gate: keep safety reject for both directions.
Replace the bearish display-only branch with the mirror:

- Bullish: `health < rejectBelow → REJECT`, `< cautionBelow → CAUTION`.
- Bearish: `health > rejectAbove → REJECT`, `> cautionAbove → CAUTION`
  (don't short strong companies).

Config gains symmetric thresholds:
```yaml
fundamentals_gate:
  enabled: true
  cautionBelow: 45   # bullish
  rejectBelow: 30    # bullish
  cautionAbove: 70   # bearish mirror
  rejectAbove: 80    # bearish mirror
```

---

## Part 6 — Direction-keyed tuned params (B11)

- `strategy_params.yaml`: `active` and `proposal` become `active.bullish` /
  `active.bearish` (migrate existing `active` → `active.bullish`).
- `strategy_param_store.get_active(strategy, direction)` and `adopt(...,
  direction)`; `stock_scan.py` merges params for the request direction.
- Add `rsi_overbought: 70` to `mean_reversion_rsi` search/active for bearish.
- WFO proposal records the `direction` it was tuned for.

---

## Part 7 — Settings: Spreads section

New **Spreads** section under "Score weights & parameters", per-horizon tabs
(Intraday / Swing / Position / Custom), editable defaults:

| Param | Default | Meaning |
|---|---|---|
| Short-leg delta target | 0.30 | Where the sold leg sits on the delta curve |
| Spread width (points) | 5 | Distance between strikes |
| IV rank threshold (credit vs debit) | 50 | Above → credit spread primary |
| Min credit to accept | $0.50 | Reject credit spreads below this |
| Max debit (% of width) | 40% | Cap debit relative to max gain |

Stored in `settingsStore` with versioned `migrate()` (per project Zustand
convention) and SSR guard.

---

## Untouched

Steps 1–2 universe/direction pickers (both directions already offered), the
direction-aware scoring engine, regime conviction math, watchlist, calendar,
and the entire bullish path. The regime change is alignment-based, so bullish
behavior is preserved exactly when direction = Bullish.

---

## Testing strategy

- **Regime alignment:** unit-test `alignmentVerdict()` for all 5 rows; assert
  RunScanButton confirm fires on REJECT for **both** directions and not on PASS.
- **Stock bearish signals:** per strategy, a downtrend fixture asserts a short
  signal with `stop > entry > target`; an uptrend fixture asserts no bearish
  signal (and vice-versa). Extend `test_stock_scan_router.py`.
- **Bearish backtest:** known short trade → `self.sell()` path executes, PnL
  sign correct, guard `tp < entry < sl` admits the trade.
- **Position card:** bearish overlay → positive dollar risk and non-zero R:R;
  target tone is `pass` when price moves down.
- **Options side:** bearish single-leg → `right='P'` fetched and `action='BUY'`
  sent; spread legs carry correct per-leg actions.
- **Spread construction:** IV rank above/below threshold selects correct primary;
  net debit/credit, max gain/loss, breakeven correct for both types.
- **Fundamentals mirror:** strong-fundamental bearish candidate → CAUTION/REJECT;
  weak-fundamental bearish candidate → PASS; safety_flags → REJECT both.
- **Tuned params:** `get_active(s,'Bearish')` independent of bullish; migration
  maps legacy `active` → `active.bullish`.
- `npm run typecheck` clean; `pytest` green before each commit.

---

## Open risks / notes

- Spread pricing needs per-strike bid/ask from the chain. `/api/contracts`
  already returns `bid`/`ask` per contract via `_augment`; confirm both
  call and put chains are fetchable (they are — `fetch_option_chain` takes
  `option_type`).
- Fundamentals mirror thresholds (70/80) are starting defaults; expose later if
  tuning is desired.
- Direction-keyed param migration must not break existing bullish tuning
  schedules; migration is one-way and additive.
