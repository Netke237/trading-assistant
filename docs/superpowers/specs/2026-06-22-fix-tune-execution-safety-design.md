# Bamendjou — Fix, Tune & Execution Safety Design
Date: 2026-06-22

## Background

A senior trader review identified three correctness bugs, several calibration gaps, and missing
execution safety guards. This document specifies what changes are made, why, and what the
acceptance criteria are. The plan is split into three phases, each independently committed and
verified by the pytest suite.

---

## Scope

| In scope | Out of scope |
|---|---|
| Bearish trigger momentum direction bug | Multi-leg spreads, PMCC |
| Pullback REJECT → overall CAUTION cap | Frontend UI changes |
| Confidence backtest per-strategy ATR | Walk-forward optimizer changes |
| RSI floor / breakout volume / min-DTE tuning | New data adapters or brokers |
| Daily loss circuit breaker | Auto-close of open positions |
| Halt-check before fire | Intraday HMM wiring into score gate |
| Regime-flip alert (WebSocket, no auto-close) | Historical backfill changes |
| Volatility-scaled sizing (enable existing block) | |

---

## Phase 1 — Bug Fixes

### Fix 1A — Bearish trigger momentum direction

**File:** `backend/app/scoring/stock_scorer.py` — `_rule_trigger()`

**Problem:** MACD, RSI, and Stochastic checks are identical for Bullish and Bearish. All three
fire on bullish momentum signals (histogram crosses up, RSI crosses up from oversold, Stoch
exits oversold). A bearish trade scores highest when the stock shows bullish momentum — the
opposite of a proper fib-rejection entry.

**Fix:** Branch on `direction` before computing the three momentum booleans.

Bearish checks:
- `macd_pass` (bearish): `hist[-2] > 0 and hist[-1] <= 0` — histogram crosses down
- `rsi_pass` (bearish): `rsi_vals[-2] > rsi_ceiling >= rsi_vals[-1]` — RSI falls through ceiling.
  RSI divergence check also flipped: price making *higher* highs while RSI makes *lower* highs.
- `stoch_pass` (bearish): `stoch_k[-2] >= overbought_threshold and stoch_k[-1] < stoch_d[-1]`
  — stochastics exiting overbought

New config keys added to **each** horizon block in `scoring_rules.yaml` under `trigger:`:
```yaml
trigger:
  rsi_ceiling: 60        # bearish RSI threshold (symmetric to rsi_floor)
  stoch_overbought: 70   # bearish stoch threshold (symmetric to stoch_oversold: 30)
```

All three horizons (swing, intraday, position) get these keys at the same values (60/70) since
they are direction-symmetric to the existing bullish values.

**Acceptance criteria:**
- A mock bar sequence where RSI falls from 65→59 (crossing ceiling of 60) fires `rsi_pass=True`
  when direction=Bearish
- Same sequence fires `rsi_pass=False` when direction=Bullish
- A mock bar sequence where MACD histogram goes +0.1 → -0.1 fires `macd_pass=True` for Bearish,
  `False` for Bullish
- All existing tests pass (no bullish regression)

---

### Fix 1B — Pullback REJECT caps overall verdict at CAUTION

**File:** `backend/app/scoring/stock_scorer.py` — `score_stock()`

**Problem:** The weighted score can reach PASS even when the pullback component returns REJECT
(score=10). A stock that hasn't pulled back, or has pulled back too deeply, can still be
recommended as a PASS candidate. The pullback is the entry timing gate; if it fails, there is no
valid setup.

**Fix:** After computing `final_score` / `final_status` and before applying the confidence gate,
inspect the pullback rule result:

```python
pullback_rule = next((r for r in rules if r.name == "pullback"), None)
if pullback_rule and pullback_rule.status == "REJECT":
    final_status = _worse(final_status, "CAUTION")
```

`_worse(a, b)` already exists — it returns the worse of two statuses. Capping at CAUTION (not
REJECT) means the stock remains visible in the screener for manual review; the candidate is
flagged but not hidden. If the confidence or regime gate independently triggers REJECT, the
combined result still reaches REJECT.

**Acceptance criteria:**
- `score_stock(...)` with trend=PASS (90), pullback=REJECT (10), trigger=PASS (70) → status CAUTION
- Same call with trend=PASS, pullback=PASS → status PASS (unchanged)
- REJECT pullback + REJECT confidence gate → status REJECT (worst of both)

---

### Fix 1C — Confidence backtest: per-strategy asymmetric ATR

**File:** `backend/app/scoring/signal_confidence.py`

**Problem:** `evaluate_fire` uses a single symmetric `atr_mult` (1.5) for both target and stop,
measuring a 1:1 R/R game. The actual strategy signals target 2.0–3.0 ATR while risking 0.5–1.5
ATR. The confidence number claims to measure win rate, but it's measuring a different trade than
the one placed.

**Fix:** Change `evaluate_fire` to accept separate `atr_mult_target` and `atr_mult_stop`:

```python
def evaluate_fire(
    history, forward, *, direction, atr,
    atr_mult_target: float,
    atr_mult_stop: float,
) -> Outcome
```

Win = favorable `atr_mult_target × ATR` reached before adverse `atr_mult_stop × ATR`.

`compute_confidence` passes these from config. New config structure in `scoring_rules.yaml`:

```yaml
confidence_backtest:
  swing:
    atr_mult_target: 3.0    # target: pullback_ema typical
    atr_mult_stop:   1.5
  position:
    atr_mult_target: 2.5
    atr_mult_stop:   1.5
  intraday:
    atr_mult_target: 2.0
    atr_mult_stop:   1.5
```

Old config key `atr_mult` is removed. Any call site that passes a single `atr_mult` override
receives a deprecation log warning and uses it for `atr_mult_target` only (backward compat).

**Acceptance criteria:**
- `evaluate_fire` with `atr_mult_target=3.0, atr_mult_stop=1.5` returns "win" only when the
  forward window reaches +3.0 ATR before −1.5 ATR
- `aggregate()` and `status_cap()` require no changes
- Test using the existing fixture bars with known outcome confirms the new logic

---

## Phase 2 — Parameter Tuning

Single commit. All changes are to config files or one function default. No logic changes.

### 2A — RSI floor (scoring_rules.yaml)

| Horizon | Key | Old | New | Reason |
|---|---|---|---|---|
| swing | `trigger.rsi_floor` | 44 | 38 | 44 is mid-neutral, not oversold |
| intraday | `trigger.rsi_floor` | 44 | 40 | Faster TF, slightly looser |
| position | `trigger.rsi_floor` | 37 | 37 | Already appropriate — no change |

### 2B — Breakout volume confirmation (strategy_engine.py)

`breakout_base_signal(volume_mult=1.1)` default → **1.5**. A 10% volume surge is statistical
noise. Institutional participation in a breakout typically shows 1.5–2.5× average volume.

### 2C — Options minimum DTE (contract_rules.yaml)

`hard_reject.min_dte: 14` → **21**. The existing `soft_rank.preferred_dte_min: 21` already
signals 21 as the target. At 14 DTE theta decay is exponential; hard and soft preferences
should agree.

**Acceptance criteria:**
- `pytest` passes (no scoring change, only threshold values)
- Manual spot-check: a contract with DTE=18 now gets REJECT (was previously allowed)
- A stock with RSI=40 crossing up through 38 now fires `rsi_pass=True` on swing (was blocked
  by floor of 44)

---

## Phase 3 — Execution Safety

### 3A — Daily loss circuit breaker

**Files:** `backend/app/services/auto_trader.py`, `backend/config/risk_rules.yaml`

New config under `auto_trade`:
```yaml
auto_trade:
  max_daily_loss_pct: 0.02   # 2% of portfolio_value
```

**P&L tracking approach:** Since current broker adapters do not return P&L on fills, the circuit
breaker uses *premium at risk* as a proxy: each history entry records
`premium_at_risk = entry_premium × quantity × 100 × premium_stop_pct`. This is the maximum loss
per trade assuming the stop is hit. Summing these across today's entries gives the worst-case daily
exposure, which is a conservative but immediately usable metric (no adapter changes required).

In `AutoTradeService.fire()`, before calling `execute_option_order`, call new method
`_check_daily_loss(strategy, portfolio_value)`. This method:
1. Reads `self._state.history` filtering to today's UTC date (using the `timestamp` field
   already recorded in history entries — add UTC timestamp if missing)
2. Sums `premium_at_risk` for all today's entries
3. Adds the current trade's `entry_premium × strategy.quantity × 100 × premium_stop_pct`
4. If total exceeds `max_daily_loss_pct × portfolio_value`:
   raise `RuntimeError("Daily loss limit reached — no further trades today")`
5. The disarm already happened before this check (existing pattern), so the block is permanent
   for the session.

`premium_at_risk` is added to the history dict in `fire()` using values already present in
`ArmedStrategy` (`entry_premium`, `quantity`). `premium_stop_pct` is loaded from risk_rules.yaml.

**Acceptance criteria:**
- Mock history with two today-entries where premium_at_risk sums to > 2% of $100k →
  `fire()` raises before reaching `execute_option_order`
- Mock history with premium_at_risk < 2% → `fire()` proceeds normally
- Entries from prior UTC days are excluded from the sum

---

### 3B — Market-open / halt check

**File:** `backend/app/services/auto_trader.py`

New private method `_market_is_open(symbol: str) -> bool`:
- Attempts `fetch_price(symbol)` from the existing data adapter
- Returns True if a valid non-zero price is returned
- Returns False on exception or None result (conservative: if we can't confirm open, block)

**Thread-safety constraint:** The existing `fire()` disarms inside the lock at the very start
(before any checks). The halt check must therefore run inside the same lock section, **before**
the disarm, so we can abort cleanly without ever having changed state:

```python
with self._lock:
    if not self._state.armed or self._state.strategy is None:
        raise RuntimeError("AutoTrader not armed")
    # Halt check BEFORE disarm — if halted, leave state unchanged
    if not _market_is_open(self._state.strategy.symbol):
        raise RuntimeError(
            f"Market closed or {self._state.strategy.symbol} halted — armed state preserved"
        )
    strategy = self._state.strategy
    self._state.armed = False        # disarm only when we intend to fire
    self._state.strategy = None
```

This is the **only** code path that preserves armed state after a `fire()` call. All other
failures (exposure cap, daily loss, order error) leave the trader disarmed per the existing
fail-closed design.

**Acceptance criteria:**
- Mock `fetch_price` returning None → fire raises without executing the order, state remains armed
- Mock `fetch_price` returning a valid price → fire proceeds normally

---

### 3C — Regime-flip mid-trade alert

**Files:** New `backend/app/services/regime_monitor.py`, `backend/app/main.py` (lifespan hook),
`backend/config/risk_rules.yaml`

New config:
```yaml
auto_trade:
  regime_monitor_interval_minutes: 15
```

`regime_monitor.py` exposes a single async function `start_regime_monitor(app)` that registers
a background task running every `regime_monitor_interval_minutes` minutes.

Each tick:
1. Calls `compute_overall_regime()` (already exists in `regime.py`)
2. If result is `'REJECT'`, checks whether any open positions exist (queries the DB positions
   table via existing SQLAlchemy session)
3. If both conditions true, emits a WebSocket message on the `ws_alerts` channel:
   ```json
   {"type": "REGIME_FLIP_WARNING", "regime": "REJECT", "message": "Market regime has turned REJECT while positions are open"}
   ```
4. Does NOT close positions — alert only

`main.py` lifespan hook calls `start_regime_monitor(app)` on startup.

**Acceptance criteria:**
- Mock `compute_overall_regime()` returning REJECT + mock open position → WebSocket message emitted
- Monitor runs without blocking the FastAPI event loop
- No alert when regime is PASS or CAUTION

---

### 3D — Volatility-scaled sizing

**Files:** `backend/config/scoring_rules.yaml`, `backend/app/services/auto_trader.py`

Enable existing config block:
```yaml
regime_sizing:
  enabled: true        # was: false
  min_mult: 0.5
  full_conviction_pct: 40
```

In `AutoTradeService._check_exposure()`, after the cap check passes, retrieve the current
`conviction_pct` from a **module-level cached value** (not from a live network call):

- `regime_monitor.py` (3C) updates a module-level `_last_regime_conviction: int | None = None`
  each time it ticks.
- `_check_exposure` reads this cached value. If `None` (monitor hasn't run yet or first startup),
  skip the sizing adjustment and use full size.
- This avoids any network call inside the synchronous exposure check and introduces no latency.

```python
mult = max(min_mult, min(1.0, conviction_pct / full_conviction_pct))
adjusted_qty = max(1, round(strategy.quantity * mult))
```

If `adjusted_qty < strategy.quantity`, log the adjustment and pass `adjusted_qty` to the
broker order. The adjusted quantity is reflected in the history entry so the UI can display it.

`regime_monitor.py` gains a module-level setter `set_last_conviction(pct: int)` called on each
successful tick before the WebSocket emit.

**Acceptance criteria:**
- `conviction_pct = 20`, `full_conviction_pct = 40` → mult = 0.5 → quantity halved
- `conviction_pct = 50` → mult = 1.0 (capped) → quantity unchanged
- `conviction_pct = -10` → mult = max(0.5, -0.25) = 0.5 → quantity halved

---

## Rollback Strategy

One git commit per phase. If Phase 3 introduces a bug, `git revert` to the Phase 2 commit.
No feature flags — the changes are small enough that git history is the rollback mechanism.

## Files Changed

| File | Phase |
|---|---|
| `backend/app/scoring/stock_scorer.py` | 1A, 1B |
| `backend/app/scoring/signal_confidence.py` | 1C |
| `backend/config/scoring_rules.yaml` | 1A, 1C, 2A, 3D |
| `backend/config/contract_rules.yaml` | 2C |
| `backend/app/services/strategy_engine.py` | 2B |
| `backend/app/services/auto_trader.py` | 3A, 3B, 3D |
| `backend/config/risk_rules.yaml` | 3A, 3B, 3C |
| `backend/app/services/regime_monitor.py` | 3C (new file) |
| `backend/app/main.py` | 3C (lifespan hook) |
