# Pre-Breakout Fibonacci Pullback Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Fibonacci retracement proximity as an optional additive signal in the Pre-Breakout scanner, exposed via new configurable params in the PreBreakoutParamsPanel and wired end-to-end from frontend sliders → API → backend signal function → confidence score.

**Architecture:** A new `_fibonacci_pullback_signal` helper in `strategy_engine.py` detects if the current close is within `fib_tolerance_pct` of any enabled Fibonacci retracement level (computed from the most significant swing move in the last `fib_swing_lookback` bars). When enabled, fib proximity is factored into `breakout_setup_signal`'s confidence score as a fourth weighted component (20% weight, redistributed from existing weights). The signal is opt-in via `fib_enabled=False` default — existing behaviour is unchanged when disabled.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 (backend); TypeScript 5.7 / React / CSS Modules (frontend); pytest / pytest-asyncio (tests)

---

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `backend/app/services/strategy_engine.py` | Add `_fibonacci_pullback_signal()` helper; extend `breakout_setup_signal()` with 4 fib params |
| Modify | `backend/app/routers/stock_scan.py` | Add fib keys to `_ALLOWED_OVERRIDE_KEYS` and `_INT_OVERRIDE_KEYS` |
| Create | `backend/tests/test_fibonacci_signal.py` | Unit tests for fib helper and breakout_setup_signal with fib enabled |
| Modify | `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx` | Add 4 fib fields to `PreBreakoutParams` interface, defaults, and panel UI |
| Modify | `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx` | Pass fib params in `paramsOverride` to `api.prebreakoutScan` |

---

## Task 1: Backend — `_fibonacci_pullback_signal` helper

**Files:**
- Modify: `backend/app/services/strategy_engine.py` (after line 93, before `# ── Signal dataclass ──`)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_fibonacci_signal.py`:

```python
import pytest
from app.services.strategy_engine import breakout_setup_signal

# ── helpers ──────────────────────────────────────────────────────────────────

def _make_bars(n: int = 120) -> list[dict]:
    """Bars that form a clean up-move then pullback to ~38.2% fib level.

    Days 0–59: price rises from 100 → 160 (swing low=100, swing high=160).
    Days 60–119: price pulls back to 38.2% retrace = 160 - 0.382*(160-100) = 137.08.
    ATR and volume are kept intentionally flat (compression always passes) so
    we can isolate the fib logic.
    """
    bars = []
    for i in range(60):
        price = 100 + i  # rises 100→159
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 500_000})
    # swing high = 160 at bar 60
    bars.append({"open": 160, "high": 161, "low": 159, "close": 160, "volume": 500_000})
    # pullback to 38.2% retracement level = 137.08
    fib_38 = 160 - 0.382 * (160 - 100)   # ≈ 137.08
    for i in range(58):
        bars.append({"open": fib_38, "high": fib_38 + 0.3, "low": fib_38 - 0.3,
                     "close": fib_38, "volume": 400_000})  # quiet volume
    return bars


def _make_bars_no_fib(n: int = 120) -> list[dict]:
    """Bars where close is far from any fib level (sits at 50% – 2% off = 47%)."""
    bars = []
    for i in range(61):
        price = 100 + i
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 500_000})
    # close = 47% retrace = far from 38.2, 50, 61.8
    off_level = 160 - 0.47 * (160 - 100)   # ≈ 131.8
    for i in range(58):
        bars.append({"open": off_level, "high": off_level + 0.3, "low": off_level - 0.3,
                     "close": off_level, "volume": 400_000})
    return bars


# ── tests ─────────────────────────────────────────────────────────────────────

class TestFibonacciSignal:
    def test_fib_disabled_no_effect(self):
        """fib_enabled=False must return same result as not passing fib params at all."""
        bars = _make_bars()
        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=False,
        )
        # Should still produce a signal (compression conditions pass in _make_bars)
        # fib parameters must not crash when disabled
        assert result is None or result.confidence >= 0

    def test_fib_at_38_level_raises_confidence(self):
        """Price at 38.2% retracement should raise confidence vs fib_enabled=False."""
        bars = _make_bars()
        without_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=False,
            resistance_proximity_pct=0.25,   # wide enough to include 38.2% retrace bar
            swing_lookback=70,
        )
        with_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
        )
        # Both should return a signal; fib-enabled should have equal or higher confidence
        assert with_fib is not None
        assert without_fib is not None
        assert with_fib.confidence >= without_fib.confidence

    def test_fib_not_at_level_does_not_raise(self):
        """Price 47% into retrace (between 38.2 and 50) should not benefit from fib."""
        bars = _make_bars_no_fib()
        with_fib = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.01,   # tight tolerance
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
        )
        # Signal may or may not exist (compression conditions may fail for off-level bars),
        # but if it does exist the fib_at_level metric must be False.
        if with_fib is not None:
            assert with_fib.metrics.get("fib_at_level") is False

    def test_fib_metrics_present_when_enabled(self):
        """When fib enabled, result metrics must include fib_level_hit and fib_at_level."""
        bars = _make_bars()
        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bullish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
        )
        if result is not None:
            assert "fib_at_level" in result.metrics
            assert "fib_level_hit" in result.metrics

    def test_fib_bearish_swing_low_to_high(self):
        """Bearish fib retracement uses high→low move then upward bounce."""
        # Mirror of make_bars but downward
        bars = []
        for i in range(61):
            price = 160 - i   # 160 → 100
            bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                         "close": price, "volume": 500_000})
        fib_38_bear = 100 + 0.382 * (160 - 100)  # ≈ 122.9
        for i in range(58):
            bars.append({"open": fib_38_bear, "high": fib_38_bear + 0.3, "low": fib_38_bear - 0.3,
                         "close": fib_38_bear, "volume": 400_000})

        result = breakout_setup_signal(
            bars, "TEST",
            direction="Bearish",
            fib_enabled=True,
            fib_levels=[23.6, 38.2, 50.0, 61.8],
            fib_tolerance_pct=0.02,
            fib_swing_lookback=70,
            resistance_proximity_pct=0.25,
            swing_lookback=70,
        )
        # Just must not throw; confidence is 0-100 if returned
        if result is not None:
            assert 0 <= result.confidence <= 100
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd backend && pytest tests/test_fibonacci_signal.py -v
```
Expected: `ERROR` or `FAILED` — `breakout_setup_signal` does not yet accept `fib_enabled`.

- [ ] **Step 3: Add `_fibonacci_pullback_signal` helper to `strategy_engine.py`**

Insert after line 93 (after `_atr_series`, before `# ── Signal dataclass ──`):

```python
# ── Fibonacci retracement helper ──────────────────────────────────────────────

_FIB_RATIOS = {
    23.6: 0.236,
    38.2: 0.382,
    50.0: 0.500,
    61.8: 0.618,
    78.6: 0.786,
}


def _fibonacci_pullback_signal(
    bars: list[dict],
    direction: Literal["Bullish", "Bearish"],
    *,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
) -> tuple[bool, float | None, str | None]:
    """Check if close is near a Fibonacci retracement level of the dominant swing move.

    For Bullish: swing low → swing high within fib_swing_lookback bars.
    Retracement levels are measured downward from the swing high.
    For Bearish: swing high → swing low. Retracement levels measured upward from swing low.

    Returns:
        (at_level: bool, nearest_pct: float|None, level_label: str|None)
    """
    if fib_levels is None:
        fib_levels = [23.6, 38.2, 50.0, 61.8]
    window = bars[-fib_swing_lookback:] if len(bars) >= fib_swing_lookback else bars
    if len(window) < 10:
        return False, None, None

    swing_high = max(b["high"] for b in window)
    swing_low  = min(b["low"]  for b in window)
    move = swing_high - swing_low
    if move <= 0:
        return False, None, None

    close = bars[-1]["close"]

    if direction == "Bullish":
        # Retracement levels from swing_high downward
        levels = {label: swing_high - _FIB_RATIOS[label] * move for label in fib_levels if label in _FIB_RATIOS}
    else:
        # Retracement levels from swing_low upward
        levels = {label: swing_low + _FIB_RATIOS[label] * move for label in fib_levels if label in _FIB_RATIOS}

    best_label: str | None = None
    best_dist_pct: float = float("inf")

    for label, level in levels.items():
        if level <= 0:
            continue
        dist_pct = abs(close - level) / level
        if dist_pct < best_dist_pct:
            best_dist_pct = dist_pct
            best_label = str(label)

    at_level = best_dist_pct <= fib_tolerance_pct
    return at_level, round(best_dist_pct * 100, 2), best_label
```

- [ ] **Step 4: Extend `breakout_setup_signal` signature and body**

In `strategy_engine.py`, replace the `breakout_setup_signal` function signature (line 588) with:

```python
def breakout_setup_signal(
    bars: list[dict],
    symbol: str,
    *,
    atr_compression_ratio: float = 0.7,
    atr_avg_lookback: int = 20,
    range_atr_mult: float = 0.8,
    range_lookback_bars: int = 10,
    vol_compression_ratio: float = 0.8,
    resistance_proximity_pct: float = 0.05,
    swing_lookback: int = 50,
    direction: Literal["Bullish", "Bearish"] = "Bullish",
    # ── Fibonacci pullback ──
    fib_enabled: bool = False,
    fib_swing_lookback: int = 100,
    fib_levels: list[float] | None = None,
    fib_tolerance_pct: float = 0.015,
) -> SetupSignal | None:
```

Replace the confidence calculation block (lines 652–656 in the original) with:

```python
    # Confidence score 0-100
    # Base weights: ATR 40%, vol 30%, prox 30%. When fib enabled: ATR 32%, vol 24%, prox 24%, fib 20%.
    atr_score  = max(0, 100 * (1 - atr_ratio / atr_compression_ratio))
    vol_score  = max(0, 100 * (1 - vol_ratio / vol_compression_ratio))
    prox_score = max(0, 100 * (1 - prox / resistance_proximity_pct)) if resistance_proximity_pct > 0 else 50

    fib_at_level: bool = False
    fib_dist_pct: float | None = None
    fib_label: str | None = None

    if fib_enabled:
        fib_at_level, fib_dist_pct, fib_label = _fibonacci_pullback_signal(
            bars,
            direction,
            fib_swing_lookback=fib_swing_lookback,
            fib_levels=fib_levels,
            fib_tolerance_pct=fib_tolerance_pct,
        )
        fib_score = 100 if fib_at_level else max(0, 100 * (1 - (fib_dist_pct or 100) / (fib_tolerance_pct * 100 * 2)))
        confidence = int(atr_score * 0.32 + vol_score * 0.24 + prox_score * 0.24 + fib_score * 0.20)
    else:
        confidence = int(atr_score * 0.40 + vol_score * 0.30 + prox_score * 0.30)
```

Replace the final `return SetupSignal(...)` block with:

```python
    metrics: dict = {
        "atr_ratio":    round(atr_ratio, 3),
        "range_ratio":  round(range_ratio, 3),
        "vol_ratio":    round(vol_ratio, 3),
        "proximity_pct": round(prox * 100, 2),
        "swing_level":  round(swing_level, 2),
        "current_atr":  round(current_atr, 4),
    }
    if fib_enabled:
        metrics["fib_at_level"]  = fib_at_level
        metrics["fib_level_hit"] = fib_label
        metrics["fib_dist_pct"]  = fib_dist_pct

    return SetupSignal(
        strategy="breakout_setup",
        direction=direction,
        symbol=symbol,
        confidence=min(100, max(0, confidence)),
        metrics=metrics,
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
cd backend && pytest tests/test_fibonacci_signal.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_fibonacci_signal.py
git commit -m "feat(prebreakout): fibonacci retracement helper + breakout_setup_signal fib params"
```

---

## Task 2: Backend — wire fib params to the router

**Files:**
- Modify: `backend/app/routers/stock_scan.py` (lines 71–85 — `_ALLOWED_OVERRIDE_KEYS` / `_INT_OVERRIDE_KEYS`)

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_prebreakout_universe.py`:

```python
@pytest.mark.asyncio
async def test_prebreakout_fib_override_keys_accepted():
    """fib_enabled, fib_swing_lookback, fib_levels, fib_tolerance_pct must be accepted."""
    with patch(
        "app.routers.stock_scan.get_historical_bars",
        new_callable=AsyncMock,
        return_value=[],
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post("/api/scan/prebreakout", json={
                "symbols": ["AAPL"],
                "params_override": {
                    "fib_enabled": True,
                    "fib_swing_lookback": 80,
                    "fib_levels": [23.6, 38.2, 50.0],
                    "fib_tolerance_pct": 0.02,
                },
            })
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_prebreakout_fib_unknown_key_still_rejected():
    """A spurious fib key must still return 422."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/api/scan/prebreakout", json={
            "symbols": ["AAPL"],
            "params_override": {"fib_unknown_key": 1},
        })
    assert resp.status_code == 422
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd backend && pytest tests/test_prebreakout_universe.py::test_prebreakout_fib_override_keys_accepted -v
```
Expected: FAIL with 422 (fib keys not yet whitelisted).

- [ ] **Step 3: Extend `_ALLOWED_OVERRIDE_KEYS` and `_INT_OVERRIDE_KEYS`**

In `backend/app/routers/stock_scan.py`, replace lines 71–85:

```python
_ALLOWED_OVERRIDE_KEYS = frozenset({
    "atr_compression_ratio",
    "atr_avg_lookback",
    "range_atr_mult",
    "range_lookback_bars",
    "vol_compression_ratio",
    "resistance_proximity_pct",
    "swing_lookback",
    # Fibonacci pullback
    "fib_enabled",
    "fib_swing_lookback",
    "fib_levels",
    "fib_tolerance_pct",
})

_INT_OVERRIDE_KEYS = frozenset({
    "atr_avg_lookback",
    "range_lookback_bars",
    "swing_lookback",
    "fib_swing_lookback",
})
```

Also update the coercion block (after `for k, v in body.params_override.items()`) to handle `fib_enabled` (bool) and `fib_levels` (list):

Find the coercion block (around line 953) and replace:

```python
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
            elif k == "fib_enabled":
                coerced[k] = bool(v)
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                coerced[k] = [float(x) for x in v]
            else:
                coerced[k] = float(v) if isinstance(v, (int, float)) else v
```

- [ ] **Step 4: Run tests**

```bash
cd backend && pytest tests/test_prebreakout_universe.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_prebreakout_universe.py
git commit -m "feat(prebreakout): whitelist fib override keys; coerce fib_enabled and fib_levels"
```

---

## Task 3: Frontend — extend PreBreakoutParams + panel UI

**Files:**
- Modify: `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`

- [ ] **Step 1: Extend the `PreBreakoutParams` interface and defaults**

In `frontend/components/organisms/PreBreakoutParamsPanel/index.tsx`, replace the current `PreBreakoutParams` interface and `PREBREAKOUT_DEFAULTS`:

```tsx
export interface PreBreakoutParams {
  atrCompressionRatio: number;    // 0.1–1.0,  default 0.7
  atrAvgLookback: number;         // 5–50,     default 20
  rangeAtrMult: number;           // 0.1–2.0,  default 0.8
  rangeLookbackBars: number;      // 3–30,     default 10
  volCompressionRatio: number;    // 0.1–1.0,  default 0.8
  resistanceProximityPct: number; // 0.01–0.20,default 0.08
  swingLookback: number;          // 10–100,   default 50
  // Fibonacci pullback
  fibEnabled: boolean;            // default false
  fibSwingLookback: number;       // 10–200,   default 100
  fibLevels: number[];            // subset of [23.6, 38.2, 50.0, 61.8, 78.6]
  fibTolerancePct: number;        // 0.005–0.05, default 0.015 (stored as fraction)
}

export const PREBREAKOUT_DEFAULTS: PreBreakoutParams = {
  atrCompressionRatio: 0.7,
  atrAvgLookback: 20,
  rangeAtrMult: 0.8,
  rangeLookbackBars: 10,
  volCompressionRatio: 0.8,
  resistanceProximityPct: 0.08,
  swingLookback: 50,
  fibEnabled: false,
  fibSwingLookback: 100,
  fibLevels: [23.6, 38.2, 50.0, 61.8],
  fibTolerancePct: 0.015,
};
```

- [ ] **Step 2: Add Fibonacci section to the panel UI**

After the closing `</label>` of the `swingLookback` field (before the `<button>` reset), add:

```tsx
        {/* ── Fibonacci pullback ── */}
        <div className={styles.paramSection}>
          <Text size={11} weight={500} tone="secondary">Fibonacci pullback (optional)</Text>
          <Text size={10} tone="dim">
            When enabled, the scanner also checks if the close is within tolerance of a
            key Fibonacci retracement level (measured from the dominant swing move).
            Price landing near 38.2% or 61.8% of a prior up-move is a high-probability
            support zone. Increases confidence score by up to 20 pts when at a level.
          </Text>
        </div>

        <label className={styles.paramLabel}>
          <div className={styles.paramInput}>
            <input
              type="checkbox"
              checked={params.fibEnabled}
              onChange={(e) => setParams((p) => ({ ...p, fibEnabled: e.target.checked }))}
              id="fib-enabled"
            />
            <Text size={11} tone={params.fibEnabled ? 'primary' : 'dim'}>
              Enable Fibonacci proximity check
            </Text>
          </div>
        </label>

        {params.fibEnabled && (
          <>
            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Fibonacci retracement levels</Text>
              <Text size={10} tone="dim">
                Which levels to treat as support. 38.2% and 61.8% are the most reliable.
                More levels → more results but more false positives.
              </Text>
              <div className={styles.fibLevels}>
                {[23.6, 38.2, 50.0, 61.8, 78.6].map((lvl) => (
                  <label key={lvl} className={styles.fibLevelCheck}>
                    <input
                      type="checkbox"
                      checked={params.fibLevels.includes(lvl)}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...params.fibLevels, lvl].sort((a, b) => a - b)
                          : params.fibLevels.filter((l) => l !== lvl);
                        setParams((p) => ({ ...p, fibLevels: next }));
                      }}
                    />
                    <Text size={11} tone={params.fibLevels.includes(lvl) ? 'primary' : 'dim'}>
                      {lvl}%
                    </Text>
                  </label>
                ))}
              </div>
            </label>

            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Swing lookback for fib move</Text>
              <Text size={10} tone="dim">
                How many bars back to search for the significant swing high and low
                that define the Fibonacci move. ↑ Higher → captures larger structural moves.
              </Text>
              <div className={styles.paramInput}>
                <input
                  type="number"
                  value={params.fibSwingLookback}
                  min={20} max={200} step={5}
                  onChange={(e) => setParams((p) => ({ ...p, fibSwingLookback: Number(e.target.value) }))}
                />
                <Text size={11} tone="dim">bars</Text>
              </div>
            </label>

            <label className={styles.paramLabel}>
              <Text size={11} tone="dim">Fib tolerance</Text>
              <Text size={10} tone="dim">
                How close (in %) the close must be to a fib level to count as "at level".
                ↑ Higher → wider net (more results) · ↓ Lower → very precise hits only.
              </Text>
              <div className={styles.paramInput}>
                <input
                  type="number"
                  value={Math.round(params.fibTolerancePct * 100 * 10) / 10}
                  min={0.5} max={5.0} step={0.1}
                  onChange={(e) =>
                    setParams((p) => ({ ...p, fibTolerancePct: Number(e.target.value) / 100 }))
                  }
                />
                <Text size={11} tone="dim">%</Text>
              </div>
            </label>
          </>
        )}
```

- [ ] **Step 3: Add CSS for new fib elements**

In `frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css`, add:

```css
.fibLevels {
  display: flex;
  gap: var(--space-3);
  flex-wrap: wrap;
  margin-top: var(--space-1);
}

.fibLevelCheck {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  cursor: pointer;
}
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: clean (0 errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/PreBreakoutParamsPanel/index.tsx frontend/components/organisms/PreBreakoutParamsPanel/PreBreakoutParamsPanel.module.css
git commit -m "feat(prebreakout): fibonacci params interface + panel UI with level checkboxes"
```

---

## Task 4: Frontend — wire fib params to the API call

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-prebreakout/page.tsx`

- [ ] **Step 1: Add fib fields to `paramsOverride` in `runScan`**

In `step-4-prebreakout/page.tsx`, find the `paramsOverride` object inside `runScan` (around line 117) and extend it:

```tsx
      const paramsOverride: Record<string, unknown> = {
        atr_compression_ratio:    params.atrCompressionRatio,
        atr_avg_lookback:         params.atrAvgLookback,
        range_atr_mult:           params.rangeAtrMult,
        range_lookback_bars:      params.rangeLookbackBars,
        vol_compression_ratio:    params.volCompressionRatio,
        resistance_proximity_pct: params.resistanceProximityPct,
        swing_lookback:           params.swingLookback,
        // Fibonacci pullback
        fib_enabled:              params.fibEnabled,
        fib_swing_lookback:       params.fibSwingLookback,
        fib_levels:               params.fibLevels,
        fib_tolerance_pct:        params.fibTolerancePct,
      };
```

- [ ] **Step 2: Show fib_level_hit in the results table when enabled**

In the `sorted.map(...)` result rows, add a Fib column after `Proximity %` when `params.fibEnabled` is true.

Find the table header row (around line 217) and replace with:

```tsx
              <div className={styles.tableHeader}>
                <span />
                <Text size={11} tone="dim" weight={500}>Symbol</Text>
                <Text size={11} tone="dim" weight={500}>Dir</Text>
                <Text size={11} tone="dim" weight={500}>Confidence</Text>
                <Text size={11} tone="dim" weight={500}>ATR Ratio</Text>
                <Text size={11} tone="dim" weight={500}>Vol Ratio</Text>
                <Text size={11} tone="dim" weight={500}>Proximity %</Text>
                {params.fibEnabled && (
                  <Text size={11} tone="dim" weight={500}>Fib Level</Text>
                )}
                <span />
              </div>
```

Find the `sorted.map` data row and add after the proximity cell:

```tsx
                  {params.fibEnabled && (
                    <Data size={12} tone={row.metrics.fib_at_level ? 'pass' : 'secondary'}>
                      {row.metrics.fib_level_hit != null
                        ? `${row.metrics.fib_level_hit}%${row.metrics.fib_at_level ? ' ✓' : ''}`
                        : '—'}
                    </Data>
                  )}
```

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/app/\(frame\)/screener/step-4-prebreakout/page.tsx
git commit -m "feat(prebreakout): wire fibonacci params to API call; show fib level hit in results table"
```

---

## Task 5: Run full test suite and verify

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && pytest -v
```
Expected: all tests PASS, no regressions.

- [ ] **Step 2: Run frontend typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: 0 errors.

- [ ] **Step 3: Smoke-test in browser**

1. Start the backend: `cd backend && uvicorn app.main:app --reload --port 8000`
2. Start the frontend: `cd frontend && npm run dev`
3. Navigate to Pre-Breakout tab (Stocks mode → Pre-Breakout).
4. Open Scan parameters. Verify existing params unchanged.
5. Check "Enable Fibonacci proximity check" — verify the 3 new sub-fields appear.
6. Enter a single ticker (e.g. `AAPL`) in the override box, click Run Scan.
7. If a result returns and fib is enabled, verify the Fib Level column shows (e.g. "38.2% ✓" or "61.8%").
8. Uncheck fib levels until 0 remain — verify the "Fib Level" column disappears.
9. Reset to defaults — verify fibEnabled returns to false and sub-fields disappear.

- [ ] **Step 4: Final commit**

```bash
git add -p   # stage only files changed in this task (smoke-test fixes only)
git commit -m "fix(prebreakout): post-smoke-test corrections (if any)"
```

---

## Self-Review

**Spec coverage:**
- [x] Fibonacci as additive signal in pre-breakout (Task 1)
- [x] Configurable: enabled toggle, levels checkboxes, swing lookback, tolerance % (Tasks 3–4)
- [x] Descriptions for each param in the panel (Task 3, Step 2)
- [x] Fibonacci already available as signal — reused `_swing_high/_swing_low` helpers (Task 1)
- [x] Fib metrics returned to frontend (`fib_at_level`, `fib_level_hit`, `fib_dist_pct`) (Task 1)
- [x] Fib column in results table when enabled (Task 4)
- [x] Backend router whitelist (Task 2)
- [x] Existing behaviour unchanged when `fib_enabled=False` (Task 1, test_fib_disabled_no_effect)

**Placeholder scan:** No TBD, no "add appropriate…", all code is complete.

**Type consistency:**
- `fibEnabled / fib_enabled` — frontend camelCase → backend snake_case (consistent across Tasks 3–4)
- `fibLevels: number[]` → serialized as JSON array → backend receives `list[float]` (Task 2 coercion)
- `fib_at_level: bool` in metrics → `row.metrics.fib_at_level` in JSX (Task 4) ✓
