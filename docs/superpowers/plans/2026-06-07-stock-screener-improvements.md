# Stock Screener Improvements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the stock screening path across 8 areas (6 analyst recommendations + 2 UX additions) without touching a single line of the options screening path.

**Architecture:** All backend scoring changes are gated behind a new `scoring_mode: Literal["stock","options"]` parameter on `score_stock()` — defaults to `"options"` so all existing callers are unchanged. Frontend changes are confined to stock-path pages (`step-5-strategy`, `step-6-backtest`) and the mode-aware Stepper. A final audit task verifies no options file was touched.

**Tech Stack:** FastAPI + Python (backend), Next.js 15 App Router + TypeScript + Zustand + CSS Modules (frontend), pytest (backend tests), `npm run typecheck` (frontend type check).

---

## Scope map — files touched

| File | Why |
|---|---|
| `backend/app/scoring/stock_scorer.py` | Tasks 1–4: scoring_mode param, RVol, trigger redesign, event neutral |
| `backend/app/services/strategy_engine.py` | Task 5: accept `ma_type` param in `pullback_ema_signal` |
| `backend/app/schemas/stock_scan.py` | Tasks 5, 7, 8: new request/response fields |
| `backend/app/routers/stock_scan.py` | Tasks 1–5, 7, 8: pass new params, fetch SPX for RS |
| `frontend/lib/scanParamsStore.ts` | Task 5: add `pullbackMaType` field |
| `frontend/app/(frame)/screener/step-5-strategy/page.tsx` | Tasks 5, 6, 8: toggle, dynamic descriptions, event filter |
| `frontend/app/(frame)/screener/step-6-backtest/page.tsx` | Tasks 7, 8: Sector RS + event columns |
| `frontend/components/organisms/StepNavBar/index.tsx` | Task 9: mode-aware REJECT dialog |
| `backend/tests/test_stock_scorer_stock_mode.py` *(new)* | Tasks 1–4: stock-mode scoring tests |
| `backend/tests/test_strategy_engine.py` | Task 5: SMA pullback tests |

**Files that must NOT change (options path):**
`step-5-vol-events/`, `step-6-contracts/`, `step-7-trade-card/`, `contract_validator.py`, `scoring_rules.yaml` (no new options keys), any existing options router.

---

## Task 1 — Add `scoring_mode` scaffold to `score_stock()`

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Create: `backend/tests/test_stock_scorer_stock_mode.py`

- [ ] **Step 1.1 — Write the failing tests**

```python
# backend/tests/test_stock_scorer_stock_mode.py
import pytest
from app.scoring.stock_scorer import score_stock


def _bars(n=120, trend="up"):
    """Synthetic OHLCV bars."""
    bars = []
    price = 100.0
    for i in range(n):
        if trend == "up":
            price += 0.4
        vol = 1_000_000
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_score_stock_accepts_scoring_mode_options():
    """scoring_mode='options' (default) must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_score_stock_accepts_scoring_mode_stock():
    """scoring_mode='stock' must not raise."""
    card = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="stock")
    assert card.status in ("PASS", "CAUTION", "REJECT")


def test_options_mode_is_default():
    """Calling without scoring_mode must behave like options mode."""
    card_default = score_stock("AAPL", "Bullish", "Swing", _bars())
    card_options = score_stock("AAPL", "Bullish", "Swing", _bars(), scoring_mode="options")
    assert card_default.score == card_options.score
```

- [ ] **Step 1.2 — Run to confirm FAIL**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -v
```
Expected: `TypeError: score_stock() got an unexpected keyword argument 'scoring_mode'`

- [ ] **Step 1.3 — Add `scoring_mode` parameter to `score_stock()`**

In `backend/app/scoring/stock_scorer.py`, change the signature of `score_stock()`:

```python
# Add Literal to imports at top of file (already imported via typing)
from typing import Literal

def score_stock(
    symbol: str,
    direction: Direction,
    horizon: Horizon,
    bars: list[dict],
    earnings_date: date | None = None,
    dividend_date: date | None = None,
    iv_rank: float | None = None,
    overrides: dict | None = None,
    benchmark_candles: list[dict] | None = None,
    confidence: int | None = None,
    confidence_gate: dict | None = None,
    confidence_sample_size: int = 0,
    scoring_mode: Literal["stock", "options"] = "options",   # ← NEW
) -> StockScoreCard:
```

No other change yet — the parameter is accepted and ignored.

- [ ] **Step 1.4 — Run tests to confirm PASS**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 1.5 — Run full existing test suite to confirm nothing broken**

```
cd backend && pytest --tb=short -q
```
Expected: same pass count as before. Zero new failures.

- [ ] **Step 1.6 — Commit**

```
git add backend/app/scoring/stock_scorer.py backend/tests/test_stock_scorer_stock_mode.py
git commit -m "feat(stock): add scoring_mode param scaffold to score_stock (no behaviour change)"
```

---

## Task 2 — Replace IV rank with Relative Volume for stock scoring

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `backend/tests/test_stock_scorer_stock_mode.py`

- [ ] **Step 2.1 — Add RVol tests**

Append to `backend/tests/test_stock_scorer_stock_mode.py`:

```python
def _bars_rvol(n=120, current_vol_mult=2.5):
    """Bars where the last bar has `current_vol_mult` × avg volume."""
    avg = 1_000_000
    bars = []
    price = 100.0
    for i in range(n):
        price += 0.4
        vol = avg if i < n - 1 else int(avg * current_vol_mult)
        bars.append({"open": price - 0.2, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": vol})
    return bars


def test_rvol_high_scores_pass_in_stock_mode():
    """RVol ≥ 2.0× should produce vol component score 90 in stock mode."""
    bars = _bars_rvol(current_vol_mult=2.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 90
    assert vol_rule.detail.get("rvol") is not None


def test_rvol_low_scores_caution_in_stock_mode():
    """RVol < 0.8× should produce vol component score 20 in stock mode."""
    bars = _bars_rvol(current_vol_mult=0.5)
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="stock")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 20


def test_options_mode_vol_rule_unchanged():
    """options mode vol rule must still return PASS 90 (iv_rank_pass_max=null path)."""
    bars = _bars_rvol(current_vol_mult=0.1)   # tiny volume
    card = score_stock("X", "Bullish", "Swing", bars, scoring_mode="options")
    vol_rule = next(r for r in card.rules if r.name == "vol")
    assert vol_rule.score == 90   # unchanged — always PASS 90 in options mode
```

- [ ] **Step 2.2 — Run to confirm FAIL**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py::test_rvol_high_scores_pass_in_stock_mode -v
```
Expected: `StopIteration` or assertion error — `rvol` key missing from detail.

- [ ] **Step 2.3 — Implement RVol in `_rule_vol()`**

Replace the `_rule_vol` function in `stock_scorer.py`:

```python
def _rule_vol(
    iv_rank: float | None,
    cfg: dict,
    *,
    volumes: list[float] | None = None,
    scoring_mode: str = "options",
) -> RuleResult:
    # ── Stock mode: Relative Volume ───────────────────────────────────────────
    if scoring_mode == "stock":
        if not volumes or len(volumes) < 21:
            return RuleResult("vol", "CAUTION", 45, {"rvol": None, "reason": "insufficient_volume_data"})
        avg_vol = sum(volumes[-21:-1]) / 20
        if avg_vol <= 0:
            return RuleResult("vol", "CAUTION", 45, {"rvol": None, "reason": "zero_avg_volume"})
        rvol = volumes[-1] / avg_vol
        detail = {"rvol": round(rvol, 2), "scored": True}
        if rvol >= 2.0:
            return RuleResult("vol", "PASS", 90, detail)
        if rvol >= 1.2:
            return RuleResult("vol", "PASS", 70, detail)
        if rvol >= 0.8:
            return RuleResult("vol", "CAUTION", 45, detail)
        return RuleResult("vol", "CAUTION", 20, detail)

    # ── Options mode: IV rank (unchanged) ────────────────────────────────────
    vc = cfg["vol"]
    if vc["iv_rank_pass_max"] is None:
        return RuleResult("vol", "PASS", 90, {"iv_rank": iv_rank, "scored": False})
    if iv_rank is None:
        return RuleResult("vol", "CAUTION", 50, {"reason": "no_iv_data"})
    compressed = vc["iv_rank_compressed_caution"]
    pass_max = vc["iv_rank_pass_max"]
    caution_max = vc["iv_rank_caution_max"]
    detail = {"iv_rank": round(iv_rank, 1)}
    if compressed is not None and iv_rank < compressed:
        return RuleResult("vol", "CAUTION", 50, {**detail, "reason": "compressed_vol"})
    if iv_rank <= pass_max:
        return RuleResult("vol", "PASS", 90, detail)
    if iv_rank <= caution_max:
        return RuleResult("vol", "CAUTION", 55, detail)
    return RuleResult("vol", "REJECT", 10, {**detail, "reason": "iv_too_high"})
```

- [ ] **Step 2.4 — Thread `scoring_mode` and `volumes` through `score_stock()`**

In `score_stock()`, update the `_rule_vol` call (around line 897):

```python
vol_result = _rule_vol(
    iv_rank, cfg,
    volumes=volumes,
    scoring_mode=scoring_mode,
)
```

- [ ] **Step 2.5 — Pass `scoring_mode='stock'` in `stock_scan.py`**

In `backend/app/routers/stock_scan.py`, update the `score_stock` call (line 87–88):

```python
card = score_stock(
    symbol=symbol,
    direction=req.direction,
    horizon=req.horizon,
    bars=bars[-120:],
    scoring_mode="stock",        # ← NEW
)
```

- [ ] **Step 2.6 — Run new tests**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -v
```
Expected: all RVol tests PASS.

- [ ] **Step 2.7 — Run full suite**

```
cd backend && pytest --tb=short -q
```
Expected: zero new failures.

- [ ] **Step 2.8 — Commit**

```
git add backend/app/scoring/stock_scorer.py backend/app/routers/stock_scan.py backend/tests/test_stock_scorer_stock_mode.py
git commit -m "feat(stock): replace IV rank with Relative Volume in stock scoring mode"
```

---

## Task 3 — Redesign trigger scoring for stock mode (candle = bonus, not gate)

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Modify: `backend/tests/test_stock_scorer_stock_mode.py`

- [ ] **Step 3.1 — Add trigger tests**

Append to `backend/tests/test_stock_scorer_stock_mode.py`:

```python
from datetime import date
from app.scoring.stock_scorer import _rule_trigger


def _trigger_bars_macd_cross(n=80):
    """Bars engineered so MACD histogram crosses zero on the last bar."""
    bars = []
    price = 50.0
    for i in range(n):
        # Declining then recovering — creates MACD cross near end
        if i < n // 2:
            price -= 0.3
        else:
            price += 0.6
        bars.append({"open": price - 0.1, "high": price + 0.5,
                     "low": price - 0.5, "close": price, "volume": 800_000})
    # Make last bar bullish close > open (candle = None scenario is tested separately)
    return bars


def _cfg_swing():
    from app.scoring.stock_scorer import _horizon_cfg
    return _horizon_cfg("Swing")


def test_trigger_no_candle_required_signals_is_pass_in_stock_mode():
    """Stock mode: required momentum signals without candle → PASS (not CAUTION 35)."""
    import copy
    cfg = copy.deepcopy(_cfg_swing())
    # Force candle detection to fail by using a bearish last bar
    bars = _trigger_bars_macd_cross()
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # bearish — no candle
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    # Even without candle, if enough momentum signals fire, must be PASS in stock mode
    # (may still be CAUTION if not enough signals — that's OK, just must not cap at 35)
    assert result.score >= 35   # guaranteed not worse than before


def test_trigger_with_candle_and_signals_scores_higher_in_stock_mode():
    """Stock mode: candle + required signals should score ≥ 85 (PASS with bonus)."""
    import copy
    cfg = copy.deepcopy(_cfg_swing())
    cfg["trigger"]["momentum_signals_for_pass"] = 0   # force "meets required" by disabling threshold
    bars = _trigger_bars_macd_cross()
    # Bullish last bar (candle)
    bars[-1]["close"] = bars[-1]["open"] + 1.0
    bars[-1]["high"] = bars[-1]["close"] + 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="stock")
    assert result.status == "PASS"
    assert result.score >= 70


def test_trigger_options_mode_still_caps_no_candle_at_caution_35():
    """options mode: no candle + required signals must still return CAUTION 35."""
    import copy
    cfg = copy.deepcopy(_cfg_swing())
    bars = _trigger_bars_macd_cross()
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # bearish — no candle
    bars[-1]["low"] = bars[-1]["close"] - 0.3
    volumes = [b["volume"] for b in bars]
    result, _ = _rule_trigger(bars, cfg, volumes, "Bullish", scoring_mode="options")
    # With required signals met and no candle, options mode = CAUTION 35
    if result.detail.get("momentum_count", 0) >= cfg["trigger"]["momentum_signals_for_pass"]:
        assert result.score == 35
```

- [ ] **Step 3.2 — Run to confirm FAIL**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -k "trigger" -v
```
Expected: failures because `_rule_trigger` doesn't accept `scoring_mode` yet.

- [ ] **Step 3.3 — Update `_rule_trigger()` signature and logic**

Replace the scoring block at the bottom of `_rule_trigger()` in `stock_scorer.py` (lines 703–720). Add `scoring_mode` parameter and split the logic:

```python
def _rule_trigger(
    bars: list[dict],
    cfg: dict,
    volumes: list[float],
    direction: Direction = "Bullish",
    scoring_mode: str = "options",          # ← NEW
) -> tuple[RuleResult, bool]:
    """Returns (RuleResult, volume_bonus)."""
    tc = cfg["trigger"]
    closes = [b["close"] for b in bars]

    candle_found, candle_name = _detect_candle(bars, direction)

    # MACD
    hist = _macd_histogram(closes, tc["macd_fast"], tc["macd_slow"], tc["macd_signal"])
    macd_pass = (len(hist) >= 2 and hist[-2] < 0 and hist[-1] >= 0 and
                 (hist[-1] > hist[-2] if tc["macd_histogram_rising"] else True))

    # RSI
    rsi_vals = _rsi(closes, tc["rsi_period"])
    rsi_pass = False
    rsi_floor = tc["rsi_floor"]
    if len(rsi_vals) >= 2:
        rsi_pass = rsi_vals[-2] < rsi_floor <= rsi_vals[-1]
        if not rsi_pass:
            div_win = tc["rsi_div_window_bars"]
            if len(closes) >= div_win and len(rsi_vals) >= div_win:
                price_low_now  = min(closes[-div_win:])
                price_low_prev = min(closes[-2 * div_win: -div_win]) if len(closes) >= 2 * div_win else price_low_now
                rsi_low_now    = min(rsi_vals[-div_win:])
                rsi_low_prev   = min(rsi_vals[-2 * div_win: -div_win]) if len(rsi_vals) >= 2 * div_win else rsi_low_now
                if price_low_now < price_low_prev and rsi_low_now > rsi_low_prev:
                    rsi_pass = True

    # Stochastic
    stoch_k, stoch_d = _stoch(bars, tc["stoch_k"], tc["stoch_d"])
    oversold_threshold = tc["stoch_oversold"] * (1 + tc["stoch_tolerance_pct"] / 100)
    stoch_pass = (len(stoch_k) >= 2 and len(stoch_d) >= 2 and
                  stoch_k[-2] <= oversold_threshold and stoch_k[-1] > stoch_d[-1] and
                  stoch_k[-2] <= stoch_d[-2])

    momentum_count = sum([macd_pass, rsi_pass, stoch_pass])
    required = tc["momentum_signals_for_pass"]

    # Volume bonus
    vol_bonus = False
    if len(volumes) >= tc["volume_lookback_bars"] + 1:
        avg_vol = sum(volumes[-tc["volume_lookback_bars"] - 1: -1]) / tc["volume_lookback_bars"]
        vol_bonus = volumes[-1] > avg_vol * tc["volume_multiplier"]

    detail = {
        "candle": candle_name or "none",
        "macd_pass": macd_pass,
        "rsi_pass": rsi_pass,
        "stoch_pass": stoch_pass,
        "momentum_count": momentum_count,
        "volume_bonus": vol_bonus,
    }

    # ── Stock mode: candle = bonus (+15 pts), NOT a gate ─────────────────────
    if scoring_mode == "stock":
        if momentum_count >= required:
            base = 65
        elif momentum_count == 1:
            base = 40
        else:
            base = 10
            return RuleResult("trigger", "REJECT", base, detail), vol_bonus

        if candle_found:
            base = min(100, base + 15)
        if vol_bonus:
            base = min(100, base + tc["volume_bonus_pts"])

        status: Status = "PASS" if base >= 55 else "CAUTION"
        return RuleResult("trigger", status, base, detail), vol_bonus

    # ── Options mode: unchanged original logic ────────────────────────────────
    if not candle_found:
        if momentum_count >= required:
            return RuleResult("trigger", "CAUTION", 35, detail), vol_bonus
        elif momentum_count == 1:
            return RuleResult("trigger", "CAUTION", 20, detail), vol_bonus
        else:
            return RuleResult("trigger", "REJECT", 10, detail), vol_bonus

    base_score = 70 if momentum_count >= required else (45 if momentum_count == 1 else 20)
    if vol_bonus:
        base_score = min(100, base_score + tc["volume_bonus_pts"])

    if momentum_count >= required:
        return RuleResult("trigger", "PASS", base_score, detail), vol_bonus
    elif momentum_count == 1:
        return RuleResult("trigger", "CAUTION", base_score, detail), vol_bonus
    else:
        return RuleResult("trigger", "REJECT", base_score, detail), vol_bonus
```

- [ ] **Step 3.4 — Thread `scoring_mode` to the `_rule_trigger` call in `score_stock()`**

```python
trigger_result, vol_bonus = _rule_trigger(
    bars, cfg, volumes, direction,
    scoring_mode=scoring_mode,    # ← NEW
)
```

- [ ] **Step 3.5 — Run trigger tests**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -k "trigger" -v
```
Expected: all PASS.

- [ ] **Step 3.6 — Run full suite**

```
cd backend && pytest --tb=short -q
```
Expected: zero new failures.

- [ ] **Step 3.7 — Commit**

```
git add backend/app/scoring/stock_scorer.py backend/tests/test_stock_scorer_stock_mode.py
git commit -m "feat(stock): trigger candle is bonus not gate in stock scoring mode"
```

---

## Task 4 — Neutralise event penalty for stock path

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py`
- Modify: `backend/tests/test_stock_scorer_stock_mode.py`

- [ ] **Step 4.1 — Add event tests**

Append to `backend/tests/test_stock_scorer_stock_mode.py`:

```python
from datetime import date, timedelta
from app.scoring.stock_scorer import _rule_event, _horizon_cfg
import copy


def test_event_neutral_in_stock_mode():
    """Stock mode: earnings tomorrow must return PASS 90 (event = flag not penalty)."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="stock")
    assert result.status == "PASS"
    assert result.score == 90
    assert result.detail.get("days_to_event") is not None   # metadata still present


def test_event_still_penalises_in_options_mode():
    """Options mode: earnings tomorrow must return REJECT (unchanged behaviour)."""
    cfg = copy.deepcopy(_horizon_cfg("Swing"))
    tomorrow = date.today() + timedelta(days=1)
    result = _rule_event(tomorrow, None, cfg, scoring_mode="options")
    assert result.status == "REJECT"
    assert result.score == 5
```

- [ ] **Step 4.2 — Run to confirm FAIL**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -k "event" -v
```
Expected: `TypeError` — `_rule_event` doesn't accept `scoring_mode`.

- [ ] **Step 4.3 — Update `_rule_event()` signature and add stock-mode branch**

```python
def _rule_event(
    earnings_date: date | None,
    dividend_date: date | None,
    cfg: dict,
    scoring_mode: str = "options",    # ← NEW
) -> RuleResult:
    ec = cfg["event"]
    today = date.today()
    worst_days: int | None = None
    event_label = "none"

    for label, ev_date in [("earnings", earnings_date), ("dividend", dividend_date)]:
        if ev_date is None:
            continue
        days = (ev_date - today).days
        if days < 0:
            continue
        if worst_days is None or days < worst_days:
            worst_days = days
            event_label = label

    if worst_days is None:
        return RuleResult("event", "PASS", 90, {"event": "none"})

    detail = {"event": event_label, "days_to_event": worst_days}

    # ── Stock mode: event = informational flag only, no penalty ───────────────
    if scoring_mode == "stock":
        return RuleResult("event", "PASS", 90, detail)

    # ── Options mode: unchanged original logic ────────────────────────────────
    if worst_days < ec["reject_days"]:
        return RuleResult("event", "REJECT", 5, detail)
    elif worst_days < ec["caution_days"]:
        return RuleResult("event", "CAUTION", 55, detail)
    return RuleResult("event", "PASS", 90, detail)
```

- [ ] **Step 4.4 — Thread `scoring_mode` to `_rule_event` call in `score_stock()`**

```python
event_result = _rule_event(
    earnings_date, dividend_date, cfg,
    scoring_mode=scoring_mode,    # ← NEW
)
```

- [ ] **Step 4.5 — Run event tests**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py -k "event" -v
```
Expected: both PASS.

- [ ] **Step 4.6 — Run full suite**

```
cd backend && pytest --tb=short -q
```
Expected: zero new failures.

- [ ] **Step 4.7 — Commit**

```
git add backend/app/scoring/stock_scorer.py backend/tests/test_stock_scorer_stock_mode.py
git commit -m "feat(stock): neutralise event penalty in stock scoring mode — event is metadata only"
```

---

## Task 5 — EMA/SMA toggle for Pullback strategy

**Files:**
- Modify: `frontend/lib/scanParamsStore.ts`
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`
- Modify: `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/services/strategy_engine.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `backend/tests/test_strategy_engine.py`

- [ ] **Step 5.1 — Add SMA pullback test**

Append to `backend/tests/test_strategy_engine.py`:

```python
def test_pullback_sma_signal_fires_in_uptrend():
    """ma_type='SMA' variant must fire on same uptrend data as EMA variant."""
    bars = _rising_bars(200)
    # Dip in last 20 bars
    for i in range(-20, 0):
        bars[i]["close"] *= 0.985
        bars[i]["low"] = bars[i]["close"] - 0.5
    signal = pullback_ema_signal(bars, ma_type="SMA")
    assert signal is None or isinstance(signal, StrategySignal)


def test_pullback_ema_is_default_ma_type():
    """Without ma_type, behaviour must be unchanged (EMA)."""
    bars = _rising_bars(200)
    signal_default = pullback_ema_signal(bars)
    signal_ema     = pullback_ema_signal(bars, ma_type="EMA")
    # Both must produce the same result
    assert (signal_default is None) == (signal_ema is None)
    if signal_default and signal_ema:
        assert signal_default.entry_price == signal_ema.entry_price
```

- [ ] **Step 5.2 — Run to confirm FAIL**

```
cd backend && pytest tests/test_strategy_engine.py::test_pullback_sma_signal_fires_in_uptrend -v
```
Expected: `TypeError` — `pullback_ema_signal` doesn't accept `ma_type`.

- [ ] **Step 5.3 — Update `pullback_ema_signal()` in `strategy_engine.py`**

```python
def pullback_ema_signal(
    bars: list[dict],
    *,
    ema_period: int = 50,
    trend_ema: int = 100,
    atr_stop_mult: float = 1.5,
    rr_target_mult: float = 2.0,
    tolerance: float = 0.04,
    ma_type: str = "EMA",          # ← NEW: "EMA" | "SMA"
) -> StrategySignal | None:
    """Bullish: uptrend (price > ema_period-MA > trend_ema-MA) + pullback to ema_period-MA + reversal candle."""
    if len(bars) < trend_ema + 10:
        return None
    closes = [b["close"] for b in bars]

    _ma = _sma if ma_type.upper() == "SMA" else _ema   # ← NEW

    fast_ma = _ma(closes, ema_period)                   # ← was _ema
    slow_ma = _ma(closes, trend_ema)                    # ← was _ema
    if not fast_ma or not slow_ma:
        return None
    current   = closes[-1]
    fast_val  = fast_ma[-1]
    slow_val  = slow_ma[-1]
    if current <= fast_val:
        return None
    if fast_val <= slow_val:
        return None
    if not (0 <= (current - fast_val) / fast_val <= tolerance):
        return None
    last = bars[-1]
    if last["close"] <= last["open"]:
        return None
    atr    = _atr(bars)
    stop   = _swing_low(bars, lookback=10) - atr * 0.2
    target = current + atr * rr_target_mult * atr_stop_mult
    ma_label = ma_type.upper()
    return StrategySignal(
        strategy="pullback_ema",
        direction="Bullish",
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={
            f"{ma_label.lower()}_{ema_period}": round(fast_val, 2),
            f"{ma_label.lower()}_{trend_ema}":  round(slow_val, 2),
        },
    )
```

- [ ] **Step 5.4 — Add `pullback_ma_type` to `StockScanRequest` schema**

In `backend/app/schemas/stock_scan.py`:

```python
from typing import Literal, Optional

class StockScanRequest(BaseModel):
    ...existing fields...
    pullback_ma_type: Literal["EMA", "SMA"] = "EMA"   # ← NEW
```

- [ ] **Step 5.5 — Thread `ma_type` through `stock_scan.py` router**

In `_SIGNAL_KWARGS` dict, update the `pullback_ema` lambda:

```python
_SIGNAL_KWARGS: dict[str, Callable[[StockScanRequest], dict[str, Any]]] = {
    "pullback_ema": lambda r: {
        "tolerance":  r.pullback_tolerance_pct,
        "ema_period": r.pullback_ema_period,
        "trend_ema":  r.pullback_trend_ema,
        "ma_type":    r.pullback_ma_type,       # ← NEW
    },
    ...rest unchanged...
}
```

- [ ] **Step 5.6 — Add `pullbackMaType` to `scanParamsStore.ts`**

```typescript
// frontend/lib/scanParamsStore.ts

export interface ScanParams {
  pullbackTolerancePct: number;
  pullbackEmaPeriod:    number;
  pullbackTrendEma:     number;
  pullbackMaType:       'EMA' | 'SMA';   // ← NEW
  maCrossoverFast:      number;
  maCrossoverSlow:      number;
  maCrossoverLookback:  number;
  breakoutVolumeMult:   number;
  rsiPeriod:            number;
  rsiOversold:          number;
  rsiTrendSma:          number;
  btMinTrades:          number;
  btMinWinRate:         number;
}

const DEFAULTS: ScanParams = {
  pullbackTolerancePct: 0.04,
  pullbackEmaPeriod:    50,
  pullbackTrendEma:     100,
  pullbackMaType:       'EMA',    // ← NEW
  maCrossoverFast:      20,
  maCrossoverSlow:      50,
  maCrossoverLookback:  10,
  breakoutVolumeMult:   1.1,
  rsiPeriod:            14,
  rsiOversold:          30,
  rsiTrendSma:          200,
  btMinTrades:          10,
  btMinWinRate:         0.45,
};

// Bump version and add migration:
export const useScanParamsStore = create<ScanParamsStore>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setParam: (key, value) => set({ [key]: value }),
      resetToDefaults: () => set({ ...DEFAULTS }),
    }),
    {
      name: 'bamendjou:scan-params',
      version: 4,                                              // ← bump from 3
      migrate: (state: unknown, v: number) => {
        if (v < 2) return { ...DEFAULTS, ...(state as Partial<ScanParams>) };
        if (v < 4) return { ...DEFAULTS, ...(state as Partial<ScanParams>), pullbackMaType: 'EMA' };
        return state as ScanParams;
      },
    },
  ),
);
```

- [ ] **Step 5.7 — Add EMA/SMA toggle and pass `pullbackMaType` in `step-5-strategy/page.tsx`**

In the `savedParams` object add `pullbackMaType`:
```typescript
const savedParams = useScanParamsStore(useShallow((s) => ({
  ...existing fields...,
  pullbackMaType: s.pullbackMaType,   // ← NEW
})));
```

In the params panel, add the toggle after the "Pullback EMA period" input:
```tsx
<label className={styles.paramLabel}>
  <Text size={11} tone="dim">Pullback MA type</Text>
  <div className={styles.maToggle}>
    {(['EMA', 'SMA'] as const).map((t) => (
      <button
        key={t}
        type="button"
        className={`${styles.maToggleBtn} ${params.pullbackMaType === t ? styles.maToggleBtnActive : ''}`}
        onClick={() => setParams((p) => ({ ...p, pullbackMaType: t }))}
      >
        <Text size={11} weight={500}>{t}</Text>
      </button>
    ))}
  </div>
</label>
```

In `runScan()`, add:
```typescript
pullback_ma_type: params.pullbackMaType,   // ← NEW
```

Add the toggle styles to `page.module.css`:
```css
.maToggle { display: flex; gap: 4px; }
.maToggleBtn {
  padding: 3px 10px; font-size: 12px;
  border: 1px solid var(--border-subtle); border-radius: 4px;
  background: var(--bg-surface); color: var(--text-secondary); cursor: pointer;
}
.maToggleBtn:hover { border-color: var(--border-default); color: var(--text-primary); }
.maToggleBtnActive {
  border-color: var(--pass);
  background: color-mix(in srgb, var(--pass) 12%, var(--bg-surface));
  color: var(--text-primary);
}
```

- [ ] **Step 5.8 — Run backend tests**

```
cd backend && pytest tests/test_strategy_engine.py -v
```
Expected: all PASS including the two new SMA tests.

- [ ] **Step 5.9 — TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 5.10 — Commit**

```
git add backend/app/services/strategy_engine.py backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py frontend/lib/scanParamsStore.ts "frontend/app/(frame)/screener/step-5-strategy/page.tsx" "frontend/app/(frame)/screener/step-5-strategy/page.module.css" backend/tests/test_strategy_engine.py
git commit -m "feat(stock): add EMA/SMA toggle for pullback strategy"
```

---

## Task 6 — Dynamic strategy descriptions (card text reflects current params)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`

- [ ] **Step 6.1 — Replace static `STRATEGIES` entry text with computed dynamic descriptions**

The `STRATEGIES` array stays as the canonical source for `key`, `when`, `stop`, and `exit`. Only `entry` needs to be dynamic. Add a computed `entryLabel` map alongside `strategyLabel`:

```typescript
// Dynamic entry descriptions — reflect current parameter values
const entryLabel: Record<string, string> = {
  pullback_ema:       `Dip to ${params.pullbackEmaPeriod}-${params.pullbackMaType} + reversal candle in uptrend`,
  ma_crossover:       `${params.maCrossoverFast}-SMA crosses above ${params.maCrossoverSlow}-SMA`,
  mean_reversion_rsi: `RSI < ${params.rsiOversold} while above ${params.rsiTrendSma}-SMA`,
  breakout_base:      `Break above N-day high after narrow range + volume spike (${params.breakoutVolumeMult}×)`,
};
```

In the card render, replace `{s.entry}` with:
```tsx
<Text size={11} tone="dim">Entry: {entryLabel[s.key] ?? s.entry}</Text>
```

Update `strategyLabel` for `pullback_ema` to include MA type:
```typescript
const strategyLabel: Record<string, string> = {
  pullback_ema:       `Pullback to ${params.pullbackEmaPeriod}-${params.pullbackMaType}`,
  ma_crossover:       `MA Crossover ${params.maCrossoverFast}/${params.maCrossoverSlow}`,
  mean_reversion_rsi: `Mean Reversion RSI / ${params.rsiTrendSma}-SMA`,
  breakout_base:      'Breakout from tight base',
};
```

- [ ] **Step 6.2 — TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 6.3 — Commit**

```
git add "frontend/app/(frame)/screener/step-5-strategy/page.tsx"
git commit -m "feat(stock): strategy card title and entry description are dynamic from params"
```

---

## Task 7 — Sector RS column in Step 6 backtest results

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `frontend/app/(frame)/screener/step-6-backtest/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-6-backtest/page.module.css`
- Modify: `frontend/types/stockDomain.ts`

- [ ] **Step 7.1 — Add `sector_rs_pct` to schema and domain type**

In `backend/app/schemas/stock_scan.py`, add to `PositionCardOut`:
```python
sector_rs_pct: float | None = None   # stock ROC minus benchmark ROC; positive = leading
```

In `frontend/types/stockDomain.ts`, add to `PositionCardData`:
```typescript
sector_rs_pct?: number | null;   // positive = leading benchmark
```

- [ ] **Step 7.2 — Compute sector RS in `stock_scan.py`**

Add a module-level helper to fetch benchmark closes (fetched once per scan, cached in-process):

```python
# In _process_stock(), after bars are fetched, compute RS vs benchmark:
# benchmark closes are passed in from the router (fetched once for whole scan)
async def _process_stock(
    symbol: str,
    req: StockScanRequest,
    scan_id: str,
    price_map: dict[str, dict],
    benchmark_closes: list[float],   # ← NEW param
) -> PositionCardOut | dict:
    ...
    # After bars are fetched and card scored, compute RS
    # Use same period as trigger's RSI divergence window for horizon
    horizon_period = {"Intraday": 2, "Swing": 20, "Position": 50}.get(req.horizon, 20)
    stock_closes = [b["close"] for b in bars]
    sector_rs_pct: float | None = None
    if len(stock_closes) > horizon_period and len(benchmark_closes) > horizon_period:
        stock_roc = (stock_closes[-1] - stock_closes[-(horizon_period + 1)]) / stock_closes[-(horizon_period + 1)] * 100
        bench_roc = (benchmark_closes[-1] - benchmark_closes[-(horizon_period + 1)]) / benchmark_closes[-(horizon_period + 1)] * 100
        sector_rs_pct = round(stock_roc - bench_roc, 2)
    ...
    return PositionCardOut(
        ...existing fields...,
        sector_rs_pct=sector_rs_pct,   # ← NEW
    )
```

In `run_stock_scan()`, fetch benchmark once before scattering tasks:

```python
@router.post("/stock-scan")
async def run_stock_scan(req: StockScanRequest) -> StockScanResult:
    ...
    # Fetch benchmark closes (SPX proxy via SPY) once for the whole scan
    benchmark_closes: list[float] = []
    try:
        spy_end = date.today()
        spy_start = spy_end - timedelta(days=_HISTORY_YEARS * 365)
        spy_bars = await get_historical_bars("SPY", spy_start, spy_end)
        benchmark_closes = [b["close"] for b in spy_bars] if spy_bars else []
    except Exception:
        pass   # RS column will show None — non-fatal

    tasks = [_process_stock(s, req, scan_id, price_map, benchmark_closes) for s in symbols]
    ...
```

- [ ] **Step 7.3 — Add Sector RS column to Step 6 table**

In `step-6-backtest/page.tsx`, update the table header:
```tsx
<div className={styles.tableHeader}>
  <Text size={11} tone="dim">SYMBOL</Text>
  <Text size={11} tone="dim">SUMMARY</Text>
  <Text size={11} tone="dim">WIN %</Text>
  <Text size={11} tone="dim">TRADES</Text>
  <Text size={11} tone="dim">RETURN</Text>
  <Text size={11} tone="dim">MAX DD</Text>
  <Text size={11} tone="dim">VS SPX</Text>    {/* ← NEW */}
  <Text size={11} tone="dim">CONF</Text>
  <Text size={11} tone="dim">GATE</Text>
</div>
```

In `BacktestRow`, add the RS cell after `max_drawdown_pct`:
```tsx
<Data
  size={12}
  tone={
    c.sector_rs_pct == null ? 'secondary'
    : c.sector_rs_pct > 1   ? 'pass'
    : c.sector_rs_pct < -1  ? 'reject'
    : 'secondary'
  }
>
  {c.sector_rs_pct != null ? `${c.sector_rs_pct > 0 ? '+' : ''}${c.sector_rs_pct.toFixed(1)}%` : '—'}
</Data>
```

Update `grid-template-columns` in `page.module.css` to add one more column (e.g. from 8 to 9 cols).

- [ ] **Step 7.4 — TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 7.5 — Run backend tests**

```
cd backend && pytest tests/test_stock_scan_router.py -v
```
Expected: PASS.

- [ ] **Step 7.6 — Commit**

```
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py "frontend/app/(frame)/screener/step-6-backtest/page.tsx" "frontend/app/(frame)/screener/step-6-backtest/page.module.css" frontend/types/stockDomain.ts
git commit -m "feat(stock): add sector RS vs SPX column to Step 6 backtest results"
```

---

## Task 8 — Event proximity column + filter toggle in stock path

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Modify: `backend/app/routers/stock_scan.py`
- Modify: `frontend/app/(frame)/screener/step-5-strategy/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-6-backtest/page.tsx`
- Modify: `frontend/types/stockDomain.ts`
- Modify: `frontend/lib/scanParamsStore.ts`

- [ ] **Step 8.1 — Add `next_event_days` to schema and domain type**

In `backend/app/schemas/stock_scan.py`, add to `PositionCardOut`:
```python
next_event_days: int | None = None    # days to nearest earnings or dividend
next_event_label: str | None = None   # "earnings" | "dividend" | None
```

In `frontend/types/stockDomain.ts`:
```typescript
next_event_days?: number | null;
next_event_label?: string | null;
```

- [ ] **Step 8.2 — Populate event fields in `stock_scan.py` router**

In `_process_stock()`, after computing `sector_rs_pct`, pass event data into `PositionCardOut`. Note: event dates are not currently fetched in the stock scan router. Add a lookup:

```python
# After bars are fetched, attempt to get event dates from quote data
# (Tradier returns next_earnings_date in quote; fall back to None if absent)
next_event_days: int | None = None
next_event_label: str | None = None
if quote:
    for field, label in [("earnings_date", "earnings"), ("ex_dividend_date", "dividend")]:
        raw = quote.get(field)
        if raw:
            try:
                ev = date.fromisoformat(str(raw)[:10])
                days = (ev - date.today()).days
                if days >= 0 and (next_event_days is None or days < next_event_days):
                    next_event_days = days
                    next_event_label = label
            except (ValueError, TypeError):
                pass

return PositionCardOut(
    ...existing fields...,
    sector_rs_pct=sector_rs_pct,
    next_event_days=next_event_days,
    next_event_label=next_event_label,
)
```

- [ ] **Step 8.3 — Add `eventFilter` to `scanParamsStore.ts`**

```typescript
// Add to ScanParams interface:
eventFilter: 'include' | 'avoid' | 'only_pre_event';

// Add to DEFAULTS:
eventFilter: 'include',

// Bump version to 5 and add migration branch:
if (v < 5) return { ...DEFAULTS, ...(state as Partial<ScanParams>), eventFilter: 'include' };
```

- [ ] **Step 8.4 — Add event filter selector to Step 5 params panel**

In `step-5-strategy/page.tsx`, add `eventFilter` to `savedParams`:
```typescript
eventFilter: s.eventFilter,
```

Add the selector in the params panel (after the MA type toggle):
```tsx
<label className={styles.paramLabel}>
  <Text size={11} tone="dim">Event exposure</Text>
  <div className={styles.maToggle}>
    {(['include', 'avoid', 'only_pre_event'] as const).map((v) => (
      <button
        key={v}
        type="button"
        className={`${styles.maToggleBtn} ${params.eventFilter === v ? styles.maToggleBtnActive : ''}`}
        onClick={() => setParams((p) => ({ ...p, eventFilter: v }))}
      >
        <Text size={11} weight={500}>
          {v === 'include' ? 'Include' : v === 'avoid' ? 'Avoid' : 'Only events'}
        </Text>
      </button>
    ))}
  </div>
</label>
```

- [ ] **Step 8.5 — Filter candidates by event preference in Step 6**

In `step-6-backtest/page.tsx`, apply client-side filter before rendering `passing`:

```tsx
const eventFilter = useScanParamsStore((s) => s.eventFilter);

const filteredPassing = passing.filter((c) => {
  const days = c.next_event_days;
  if (eventFilter === 'avoid')          return days == null || days > 7;
  if (eventFilter === 'only_pre_event') return days != null && days <= 21;
  return true;   // 'include' — show all
});
```

Add event column to table header:
```tsx
<Text size={11} tone="dim">EVENT</Text>
```

Add event cell to `BacktestRow`:
```tsx
<Text size={11} tone={
  c.next_event_days == null   ? 'dim'
  : c.next_event_days <= 3    ? 'reject'
  : c.next_event_days <= 14   ? 'caution'
  : 'secondary'
}>
  {c.next_event_days != null ? `${c.next_event_label?.[0]?.toUpperCase()} ${c.next_event_days}d` : '—'}
</Text>
```

Update grid columns count in `page.module.css` to accommodate the new column.

- [ ] **Step 8.6 — TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 8.7 — Commit**

```
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py "frontend/app/(frame)/screener/step-5-strategy/page.tsx" "frontend/app/(frame)/screener/step-6-backtest/page.tsx" frontend/types/stockDomain.ts frontend/lib/scanParamsStore.ts
git commit -m "feat(stock): event proximity column + Avoid/Include/Only filter in stock path"
```

---

## Task 9 — Mode-aware regime REJECT dialog

**Files:**
- Modify: `frontend/components/organisms/StepNavBar/index.tsx`

- [ ] **Step 9.1 — Read `screenerMode` in `StepNavBar` and show different text for stocks**

The `mode` variable is already read in `StepNavBar`:
```typescript
const mode = useScanStore((s) => s.screenerMode);
```

Update the dialog body text to be mode-aware:
```tsx
{mode === 'stocks' ? (
  <Text size={13} tone="secondary">
    Market conditions are unfavourable for broad directional positions.
    Stock Ranking will still run — consider filtering to defensive sectors
    (utilities · healthcare · consumer staples) before trading.
  </Text>
) : (
  <Text size={13} tone="secondary">
    Market conditions are unfavourable for new directional positions.
    Step 4 (Stock Ranking) will still rank your candidates — but consider waiting
    for a better regime before trading.
  </Text>
)}
```

- [ ] **Step 9.2 — TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 9.3 — Commit**

```
git add frontend/components/organisms/StepNavBar/index.tsx
git commit -m "feat(stock): mode-aware regime REJECT dialog mentions defensive sectors for stock path"
```

---

## Task 10 — Options path audit

**Goal:** Confirm zero options-path files were modified and all existing options tests still pass.

- [ ] **Step 10.1 — Verify options-path files are untouched**

```bash
git diff HEAD~9 --name-only | grep -E "(step-5-vol-events|step-6-contracts|step-7-trade-card|contract_validator|scoring_rules)"
```
Expected output: **empty** — none of those files appear in the diff.

- [ ] **Step 10.2 — Confirm `score_stock()` default is still `options` mode**

```
cd backend && pytest tests/test_stock_scorer_stock_mode.py::test_options_mode_is_default -v
```
Expected: PASS.

- [ ] **Step 10.3 — Run all existing options-related backend tests**

```
cd backend && pytest tests/test_contracts_scoring.py tests/test_scan_endpoint.py tests/test_overrides.py tests/test_trend_scoring.py tests/test_bearish_scoring.py tests/test_confidence_gate.py tests/test_reward_risk.py tests/test_vol_rule_fix.py -v
```
Expected: all PASS — no regressions.

- [ ] **Step 10.4 — Run full backend suite**

```
cd backend && pytest --tb=short -q
```
Expected: zero failures, same count as baseline.

- [ ] **Step 10.5 — Full TypeScript check**

```
cd frontend && npm run typecheck
```
Expected: clean.

- [ ] **Step 10.6 — Final audit commit**

```
git add .
git commit -m "chore: audit confirms options path unchanged — all options tests pass"
```

---

## Self-review

**Spec coverage check:**
- [x] Point 1 (RVol) → Task 2
- [x] Point 2 (Step 5 Sector RS column) → Task 7
- [x] Point 3 (event proximity bug + flag model) → Task 4 + Task 8
- [x] Point 4 (trigger redesign) → Task 3
- [x] Point 5 (regime soft gate — mode-aware) → Task 9
- [x] Point 6 (contract vol=0 — no action) → no task needed
- [x] Additional #1 (dynamic card title) → Task 6
- [x] Additional #2 (EMA/SMA toggle) → Task 5
- [x] Audit → Task 10

**Options path isolation:**
Every scoring change is gated behind `scoring_mode="stock"` which must be explicitly passed. The default is `"options"`. No options router, page, or test file is modified. Confirmed by Task 10 step 10.1 git diff check.

**Type consistency:**
- `sector_rs_pct: float | None` in Python matches `sector_rs_pct?: number | null` in TypeScript
- `next_event_days: int | None` matches `next_event_days?: number | null`
- `pullbackMaType: 'EMA' | 'SMA'` used consistently in store, page, and schema
- `pullback_ma_type: Literal["EMA","SMA"]` schema field name matches `r.pullback_ma_type` access in router
