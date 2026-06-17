# Bearish Trading Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bamendjou trade bearish setups correctly across the options screener and the stock scanner by mirroring existing bullish logic and fixing the broken/backwards bearish paths.

**Architecture:** Seven independently-shippable phases, ordered by risk and dependency. Phase A removes a live money-loss bug; Phase B reframes regime as a shared alignment gate; Phases C–E make the stock scanner directionally correct; Phases F–G add options spreads. Each phase ends green (`pytest` + `npm run typecheck`) and is committable on its own.

**Tech Stack:** FastAPI + Pydantic v2 + pytest (backend), Next.js 15 + TypeScript + Zustand + Jest (frontend). Design doc: `docs/superpowers/specs/2026-06-14-bearish-trading-support-design.md`.

**Branch:** Work on `feat/bearish-trading-support` (create from `main`).

---

## File map

| File | Phase | Responsibility / change |
|---|---|---|
| `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` | A | Order action from structure, not direction |
| `frontend/app/(frame)/screener/step-6-contracts/page.tsx` | A | Fetch `'P'` chain when bearish |
| `frontend/lib/regimeAlignment.ts` *(new)* | B | `alignmentVerdict(direction, descriptor)` helper |
| `frontend/app/(frame)/screener/step-1-regime/page.tsx` | B | Set `combinedRegime` from alignment |
| `frontend/app/(frame)/screener/step-3-direction/page.tsx` | B | Recompute alignment on direction change |
| `frontend/components/organisms/RunScanButton/index.tsx` | B | Gate fires on REJECT for both directions; dynamic text |
| `backend/app/services/strategy_engine.py` | C | `direction` param + bearish branch in all 4 signal fns |
| `backend/app/services/strategy_backtest.py` | C | Direction-aware guard + `self.sell()` |
| `backend/app/routers/stock_scan.py` | C, E | Pass `direction` to signal fn; direction-keyed params |
| `frontend/components/organisms/StockPositionCard/index.tsx` | C | `Math.abs` risk/RR; direction-aware tone |
| `backend/app/services/strategy_watch_evaluator.py` | C | Direction-aware alert text |
| `backend/app/scoring/stock_scorer.py` | D | Fundamentals gate bearish mirror |
| `backend/config/scoring_rules.yaml` | D | `cautionAbove`/`rejectAbove` |
| `backend/app/services/strategy_param_store.py` | E | `get_active(strategy, direction)`, `adopt(..., direction)`, migration |
| `backend/config/strategy_params.yaml` | E | `active.bullish`/`active.bearish`; `rsi_overbought` |
| `backend/app/scoring/spread_builder.py` *(new)* | F | Build bear put / bear call spreads, compute economics |
| `backend/app/routers/scan.py` | F | Attach spread structures to candidates |
| `frontend/types/domain.ts` | F | `SpreadType`, `OptionLeg`, spread fields on `TradeCardData` |
| `frontend/components/organisms/TradeCard/index.tsx` | F | Two-leg panel |
| `frontend/lib/settingsStore.ts` | G | Spread settings + versioned migrate |
| `frontend/app/(frame)/settings/page.tsx` | G | Spreads section |

---

# Phase A — Options single-leg footgun (B1, B2)

**Why first:** Today a bearish scan fetches *calls* and sends *SELL* → a naked short via Tradier paper. This is a live money-loss path. Fix is tiny and unblocks "buy a put" end to end.

### Task A1: Step 6 fetches puts for bearish

**Files:**
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx:70`

- [ ] **Step 1: Apply the change**

Replace line 70's hardcoded `'C'` with a direction-derived right:

```tsx
    const right = (context?.direction ?? 'Bullish') === 'Bullish' ? 'C' : 'P';
    Promise.all(candidates.map((c) => api.getContracts(c.symbol, right, {
      stock_score: stockScoreBySymbol[c.symbol] ?? 70,
      direction:   context?.direction ?? 'Bullish',
      horizon:     context?.horizon ?? 'swing',
      limit:       maxContractsPerChain,
      max_price:   maxContractPrice,
    })))
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors).

- [ ] **Step 3: Commit**

```bash
git add "frontend/app/(frame)/screener/step-6-contracts/page.tsx"
git commit -m "fix(screener): fetch put chain for bearish scans (B2)"
```

### Task A2: Order action derives from structure, not direction (ALL options paths)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:230,254`
- Modify: `frontend/components/organisms/AutoTradeArm/index.tsx:39`

**Rationale:** A long single-leg option (call or put) is always BUY-to-open. The bearish thesis is expressed by the *put*, not by selling. **Both** the manual trade-card path AND the auto-trade arm path are options orders that hit `tradier_paper.py` (`SELL → sell_to_open` = naked short). Both must be fixed, or arming a bearish auto-trade writes a naked short put.

- [ ] **Step 1: Enumerate every options BUY/SELL ternary**

Run: `cd frontend && rg "=== 'Bullish' \? 'BUY' : 'SELL'" -n`
Expected matches and their classification:
- `step-7-trade-card/page.tsx:230,254` — **options** (fix here)
- `components/organisms/AutoTradeArm/index.tsx:39` — **options** (`api.armAutoTrade({ option_symbol, action })`) (fix here)
- `components/organisms/StockPositionCard/index.tsx`, `StockSendDialog/index.tsx`, and `@contextRail/.../step-7-position-card/page.tsx` — **stock** paths. For a stock, bearish genuinely = short = SELL, so these are CORRECT. **Do not change them.**

- [ ] **Step 2: Replace the options action expressions**

At `step-7-trade-card/page.tsx:230` (limit) and `:254` (market), and at `AutoTradeArm/index.tsx:39`, change:

```tsx
        action:        card.direction === 'Bullish' ? 'BUY' : 'SELL',
```

to:

```tsx
        action:        'BUY',   // long single-leg option (call or put) is always buy-to-open
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-7-trade-card/page.tsx" frontend/components/organisms/AutoTradeArm/index.tsx
git commit -m "fix(screener): long option always buys to open — manual + auto-trade (B1 footgun)"
```

---

# Phase B — Shared regime alignment (B7, B8)

**Why:** `combinedRegime` (a `Status`) currently equals direction-agnostic market health (`r.overall`). Reframe it as the alignment of chosen direction × regime descriptor. Downstream consumers (StepNavBar, `REGIME_FIT`, RunScanButton) already read `combinedRegime`, so they auto-correct once it is alignment-derived.

### Task B1: `alignmentVerdict` helper (TDD)

**Files:**
- Create: `frontend/lib/regimeAlignment.ts`
- Test: `frontend/lib/__tests__/regimeAlignment.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { alignmentVerdict } from '@/lib/regimeAlignment';

describe('alignmentVerdict', () => {
  it('PASS when direction agrees with descriptor', () => {
    expect(alignmentVerdict('Bearish', 'Bear')).toBe('REJECT' === 'REJECT' ? 'PASS' : 'PASS');
    expect(alignmentVerdict('Bullish', 'Bull')).toBe('PASS');
    expect(alignmentVerdict('Bearish', 'Bear')).toBe('PASS');
  });
  it('REJECT when direction opposes descriptor', () => {
    expect(alignmentVerdict('Bearish', 'Bull')).toBe('REJECT');
    expect(alignmentVerdict('Bullish', 'Bear')).toBe('REJECT');
  });
  it('CAUTION on choppy regardless of direction', () => {
    expect(alignmentVerdict('Bullish', 'Choppy')).toBe('CAUTION');
    expect(alignmentVerdict('Bearish', 'Choppy')).toBe('CAUTION');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=regimeAlignment`
Expected: FAIL — `alignmentVerdict` not found.

- [ ] **Step 3: Implement the helper**

```ts
import type { Direction, HmmState } from '@/types/domain';   // HmmState = 'Bull'|'Bear'|'Choppy' (domain.ts:273)
import type { Status } from '@/lib/status';   // Status lives in lib/status, NOT re-exported from domain.ts

/** Regime descriptor as produced by the OMM/HMM layer. Reuse HmmState to avoid drift. */
export type RegimeDescriptor = HmmState;

/**
 * Alignment of the trader's chosen direction with the market regime descriptor.
 * - agree  → PASS
 * - oppose → REJECT
 * - choppy → CAUTION
 * Single source of truth for the regime gate (Step 1 + Step 3 + StepNavBar).
 */
export function alignmentVerdict(direction: Direction, descriptor: RegimeDescriptor): Status {
  if (descriptor === 'Choppy') return 'CAUTION';
  const agrees =
    (direction === 'Bullish' && descriptor === 'Bull') ||
    (direction === 'Bearish' && descriptor === 'Bear');
  return agrees ? 'PASS' : 'REJECT';
}

/** Map a raw OMM state string to the canonical descriptor. */
export function descriptorFromState(state: string): RegimeDescriptor {
  if (state === 'Bull') return 'Bull';
  if (state === 'Bear') return 'Bear';
  return 'Choppy';
}
```

Fix the sloppy first assertion in the test (artifact): change the first line of the first `it` block to `expect(alignmentVerdict('Bullish', 'Bull')).toBe('PASS');`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=regimeAlignment`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/regimeAlignment.ts frontend/lib/__tests__/regimeAlignment.test.ts
git commit -m "feat(regime): add direction×descriptor alignment helper (B8)"
```

### Task B2: Step 1 sets `combinedRegime` from alignment

**Files:**
- Modify: `frontend/app/(frame)/screener/step-1-regime/page.tsx:88–90`

**Context:** Lines 88–90 currently do `setRegimeData(r); setRegime(r.overall); setCombinedRegime(r.overall);`. `r` is `MarketRegime`; the descriptor comes from the OMM state used by `toneForOmmState`. Keep `setRegime(r.overall)` as the raw market-health value (still used for display) but derive `combinedRegime` from alignment using the **current chosen direction** (read from `scanStore.context.direction`, default `'Bullish'`).

- [ ] **Step 1: Update the effect**

```tsx
import { alignmentVerdict, descriptorFromState } from '@/lib/regimeAlignment';
// ... inside the effect that has `r`:
      setRegimeData(r);
      setRegime(r.overall);
      const direction = useScanStore.getState().context?.direction ?? 'Bullish';
      const descriptor = descriptorFromState(r.omm?.state ?? '');
      setCombinedRegime(alignmentVerdict(direction, descriptor));
```

If `r.omm` is not the field name on `MarketRegime`, use the field the page already reads for `toneForOmmState(omm.state)` (the page destructures an `omm` object near line 289). Use that same state value.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add "frontend/app/(frame)/screener/step-1-regime/page.tsx"
git commit -m "feat(regime): combinedRegime = alignment at Step 1 (B8)"
```

### Task B3: Step 3 recomputes alignment when direction changes

**Files:**
- Modify: `frontend/app/(frame)/screener/step-3-direction/page.tsx:720–724,738`

**Context (verified against source):** The mount effect at lines 720–724 fetches regime and calls `setRegime(r.overall)` but **does not keep the descriptor** in component state, so it is not in scope at direction-change time. The direction handler is `handleDirChange(d: Direction)` at **line 738** (it calls `setDir(d)` then `syncToStore(...)`). We must (a) capture the descriptor into a ref when regime is fetched, then (b) recompute `combinedRegime` inside `handleDirChange`.

- [ ] **Step 1: Capture the descriptor in a ref on fetch**

Add a ref and store the descriptor in the existing mount effect:

```tsx
import { useRef } from 'react';
import { alignmentVerdict, descriptorFromState, type RegimeDescriptor } from '@/lib/regimeAlignment';
// near other refs in the component:
  const descriptorRef = useRef<RegimeDescriptor>('Choppy');
// in the effect (lines 720–724):
  useEffect(() => {
    api.getRegime().then((r) => {
      useScanStore.getState().setRegime(r.overall);
      descriptorRef.current = descriptorFromState(r.omm?.state ?? '');
      // seed alignment for the direction already chosen (default Bullish)
      const dir = useScanStore.getState().context?.direction ?? 'Bullish';
      useScanStore.getState().setCombinedRegime(alignmentVerdict(dir, descriptorRef.current));
    }).catch(() => {});
  }, []);
```

- [ ] **Step 2: Recompute alignment inside `handleDirChange` (line 738)**

```tsx
  const handleDirChange = (d: Direction) => {
    setDir(d);
    useScanStore.getState().setCombinedRegime(alignmentVerdict(d, descriptorRef.current));
    // ...existing body (syncToStore etc.) unchanged
  };
```

Requirement after this handler: `combinedRegime === alignmentVerdict(chosenDirection, descriptorRef.current)`. If `MarketRegime.omm` is not the field name, use the same `omm.state` path Step 1 reads (confirmed at `types/domain.ts` `OmmData.state` / `MarketRegime.omm`).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/screener/step-3-direction/page.tsx"
git commit -m "feat(regime): recompute alignment on direction change (B8)"
```

### Task B4: RunScanButton gate fires for both directions

**Files:**
- Modify: `frontend/components/organisms/RunScanButton/index.tsx:106,186–210`

- [ ] **Step 1: Read `combinedRegime` (not raw `regime`) and drop the bullish-only condition**

**Verified:** line 105 reads `useScanStore.getState().regime` — the raw market-health value, NOT the alignment value. The whole Phase B reframe lands in `combinedRegime`, so this gate must read `combinedRegime` or the alignment never reaches the gate. Change lines 105–106 from:

```tsx
    const currentRegime = useScanStore.getState().regime;
    if (currentRegime === 'REJECT' && direction === 'Bullish' && !regimeConfirmedRef.current) {
```

to:

```tsx
    const currentRegime = useScanStore.getState().combinedRegime;
    if (currentRegime === 'REJECT' && !regimeConfirmedRef.current) {
```

- [ ] **Step 2: Make the dialog text direction-aware**

Replace the hardcoded body (around line 191) with:

```tsx
        Running a {direction} scan while the regime opposes it (REJECT) carries
        elevated risk. Proceed anyway?
```

- [ ] **Step 3: Add a Jest test for the bearish gate**

Test file: `frontend/components/organisms/RunScanButton/__tests__/regimeGate.test.tsx` (or extend existing). Assert that with `combinedRegime='REJECT'` and `direction='Bearish'`, clicking Run shows the confirm dialog (mirrors the existing CR-07 e2e for bullish).

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && npm run test -- --testPathPattern=RunScanButton && npm run typecheck`
Expected: PASS, clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/RunScanButton/
git commit -m "fix(regime): confirm gate fires on misalignment for both directions (B7)"
```

---

# Phase C — Stock scanner bearish (B3, B4, B5, B6, B9)

**Why:** The big build. Mirror all four strategies, make the backtest short-aware, pass direction through, and fix the position card. Backend dollar-risk (`_position_size`) and backtest cache key already use `abs`/direction — do not change those.

### Task C1: `pullback_ema_signal` accepts direction (TDD)

**Files:**
- Modify: `backend/app/services/strategy_engine.py:90–142`
- Test: `backend/tests/test_strategy_engine_bearish.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from app.services.strategy_engine import pullback_ema_signal

def _downtrend_pullback_bars():
    # 130 bars trending DOWN, with the last bar bouncing UP toward the falling 50-EMA
    bars = []
    price = 200.0
    for i in range(130):
        price -= 0.6                      # steady downtrend
        o = price + 0.1; c = price
        bars.append({"open": o, "high": o + 0.5, "low": c - 0.5,
                     "close": c, "volume": 1_000_000, "time": i})
    # final bar: small bounce up to just under the 50-EMA (resistance)
    last = bars[-1]["close"]
    bars[-1] = {"open": last, "high": last + 1.0, "low": last - 0.2,
                "close": last + 0.8, "volume": 1_000_000, "time": 129}
    return bars

def test_pullback_ema_bearish_returns_short_shaped_signal():
    sig = pullback_ema_signal(_downtrend_pullback_bars(), direction="Bearish")
    assert sig is not None
    assert sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price

def test_pullback_ema_bullish_unchanged_default():
    # default direction stays Bullish (no regression)
    import inspect
    assert inspect.signature(pullback_ema_signal).parameters["direction"].default == "Bullish"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py::test_pullback_ema_bearish_returns_short_shaped_signal -v`
Expected: FAIL — `direction` is an unexpected keyword argument.

- [ ] **Step 3: Implement the bearish branch**

Add `direction: Literal["Bullish", "Bearish"] = "Bullish"` to the signature, then replace the trend/pullback/stop/target block (lines 112–136) with:

```python
    current  = closes[-1]
    fast_val = fast_ma[-1]
    slow_val = slow_ma[-1]
    atr      = _atr(bars)
    last     = bars[-1]
    if direction == "Bullish":
        if current <= fast_val:            return None   # price above fast MA
        if fast_val <= slow_val:           return None   # fast above slow (uptrend stack)
        if not (0 <= (current - fast_val) / fast_val <= tolerance): return None
        if require_reversal and last["close"] <= last["open"]:      return None
        stop   = _swing_low(bars, lookback=10) - atr * 0.2
        target = current + atr * rr_target_mult * atr_stop_mult
    else:  # Bearish — mirror
        if current >= fast_val:            return None   # price below fast MA
        if fast_val >= slow_val:           return None   # fast below slow (downtrend stack)
        if not (0 <= (fast_val - current) / fast_val <= tolerance): return None
        if require_reversal and last["close"] >= last["open"]:      return None
        stop   = _swing_high(bars, lookback=10) + atr * 0.2
        target = current - atr * rr_target_mult * atr_stop_mult
    ma_label = ma_type.upper()
    return StrategySignal(
        strategy="pullback_ema",
        direction=direction,
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

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_engine_bearish.py
git commit -m "feat(strategy): pullback_ema bearish mirror (B3)"
```

### Task C2: `breakout_base_signal` accepts direction (TDD)

**Files:**
- Modify: `backend/app/services/strategy_engine.py:147–189`
- Test: extend `backend/tests/test_strategy_engine_bearish.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.strategy_engine import breakout_base_signal

def _breakdown_bars():
    bars = []
    price = 100.0
    for i in range(30):                   # tight base around 100
        bars.append({"open": price, "high": price + 0.4, "low": price - 0.4,
                     "close": price, "volume": 1_000_000, "time": i})
    # breakdown bar: closes below base low on high volume
    bars.append({"open": 99.6, "high": 99.7, "low": 96.0, "close": 96.5,
                 "volume": 3_000_000, "time": 30})
    return bars

def test_breakout_base_bearish_breakdown():
    sig = breakout_base_signal(_breakdown_bars(), direction="Bearish")
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py::test_breakout_base_bearish_breakdown -v`
Expected: FAIL (unexpected `direction` kwarg).

- [ ] **Step 3: Implement**

Add `direction: Literal["Bullish", "Bearish"] = "Bullish"`. Replace the breakout/volume/stop/target block (lines 171–189) with:

```python
    current = closes[-1]
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else vols[-1]
    if vols[-1] < avg_vol * volume_mult:
        return None
    if direction == "Bullish":
        if current <= base_high:   return None
        stop   = base_low - atr * 0.2
        target = current + (current - stop) * rr_target_mult
        # keep the existing bullish detail key unchanged (no regression for consumers)
        detail = {"base_high": round(base_high, 2), "base_range_pct": round(base_range_pct * 100, 1)}
    else:  # Bearish breakdown below base low
        if current >= base_low:    return None
        stop   = base_high + atr * 0.2
        target = current - (stop - current) * rr_target_mult
        detail = {"base_low": round(base_low, 2), "base_range_pct": round(base_range_pct * 100, 1)}
    return StrategySignal(
        strategy="breakout_base",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail=detail,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_engine_bearish.py
git commit -m "feat(strategy): breakout_base bearish breakdown mirror (B3)"
```

### Task C3: `ma_crossover_signal` accepts direction (TDD)

**Files:**
- Modify: `backend/app/services/strategy_engine.py:194–225`
- Test: extend `backend/tests/test_strategy_engine_bearish.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.strategy_engine import ma_crossover_signal

def _death_cross_bars():
    bars = []
    price = 150.0
    for i in range(60):                   # rise then fall to force fast-below-slow cross
        price += 0.8
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 1_000_000, "time": i})
    for i in range(60, 90):
        price -= 1.5
        bars.append({"open": price, "high": price + 0.5, "low": price - 0.5,
                     "close": price, "volume": 1_000_000, "time": i})
    return bars

def test_ma_crossover_bearish_death_cross():
    sig = ma_crossover_signal(_death_cross_bars(), direction="Bearish")
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py::test_ma_crossover_bearish_death_cross -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `direction: Literal["Bullish", "Bearish"] = "Bullish"`. Replace the cross-scan loop (lines 210–225) with:

```python
    for i in range(-lookback, 0):
        crossed = (
            (fast_ma[i - 1] <= slow_ma[i - 1] and fast_ma[i] > slow_ma[i])
            if direction == "Bullish"
            else (fast_ma[i - 1] >= slow_ma[i - 1] and fast_ma[i] < slow_ma[i])
        )
        if crossed:
            current = closes[-1]
            atr = _atr(bars)
            if direction == "Bullish":
                stop   = slow_ma[-1] - atr * 0.5
                target = current + atr * 3.0
            else:
                stop   = slow_ma[-1] + atr * 0.5
                target = current - atr * 3.0
            return StrategySignal(
                strategy="ma_crossover",
                direction=direction,
                entry_price=round(current, 2),
                stop_price=round(stop, 2),
                target_price=round(target, 2),
                atr=round(atr, 2),
                detail={f"sma_{fast}": round(fast_ma[-1], 2), f"sma_{slow}": round(slow_ma[-1], 2)},
            )
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_engine_bearish.py
git commit -m "feat(strategy): ma_crossover death-cross mirror (B3)"
```

### Task C4: `mean_reversion_rsi_signal` accepts direction + `rsi_overbought` (TDD)

**Files:**
- Modify: `backend/app/services/strategy_engine.py:230–262`
- Test: extend `backend/tests/test_strategy_engine_bearish.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.strategy_engine import mean_reversion_rsi_signal

def _overbought_downtrend_bars():
    bars = []
    price = 300.0
    for i in range(230):                  # long downtrend (price below 200-SMA)
        price -= 0.5
        bars.append({"open": price, "high": price + 0.4, "low": price - 0.4,
                     "close": price, "volume": 1_000_000, "time": i})
    # sharp 6-bar rally to push RSI > 70 and make it tick down on the last bar
    for j in range(6):
        price += 3.0
        bars.append({"open": price - 2.9, "high": price + 0.3, "low": price - 3.0,
                     "close": price, "volume": 1_000_000, "time": 230 + j})
    bars[-1]["close"] = bars[-1]["open"] - 0.5   # last bar ticks down (RSI falling)
    return bars

def test_mean_reversion_rsi_bearish_overbought():
    sig = mean_reversion_rsi_signal(_overbought_downtrend_bars(),
                                    direction="Bearish", rsi_overbought=70.0)
    assert sig is not None and sig.direction == "Bearish"
    assert sig.stop_price > sig.entry_price > sig.target_price
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py::test_mean_reversion_rsi_bearish_overbought -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

Change the signature to add `direction: Literal["Bullish", "Bearish"] = "Bullish"` and `rsi_overbought: float = 70.0`. Replace the trend/RSI/stop/target block (lines 242–262) with:

```python
    trend = _sma(closes, trend_sma)
    if not trend:
        return None
    rsi = _rsi(closes, rsi_period)
    if not rsi or len(rsi) < 2:
        return None
    current = closes[-1]
    atr = _atr(bars)
    if direction == "Bullish":
        if closes[-1] <= trend[-1]:        return None   # uptrend context
        if rsi[-1] >= rsi_oversold:        return None   # oversold
        if rsi[-1] <= rsi[-2]:             return None   # RSI recovering
        stop   = _swing_low(bars, lookback=10) - atr * 0.2
        target = current + atr * 2.5
    else:  # Bearish — overbought in downtrend
        if closes[-1] >= trend[-1]:        return None   # downtrend context
        if rsi[-1] <= rsi_overbought:      return None   # overbought
        if rsi[-1] >= rsi[-2]:             return None   # RSI rolling over
        stop   = _swing_high(bars, lookback=10) + atr * 0.2
        target = current - atr * 2.5
    return StrategySignal(
        strategy="mean_reversion_rsi",
        direction=direction,
        entry_price=round(current, 2),
        stop_price=round(stop, 2),
        target_price=round(target, 2),
        atr=round(atr, 2),
        detail={"rsi": round(rsi[-1], 1), f"sma_{trend_sma}": round(trend[-1], 2)},
    )
```

- [ ] **Step 4: Run to verify pass + no regression**

Run: `cd backend && pytest tests/test_strategy_engine_bearish.py -v && pytest tests/test_stock_scan_router.py -v`
Expected: new tests PASS; existing PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_engine.py backend/tests/test_strategy_engine_bearish.py
git commit -m "feat(strategy): mean_reversion_rsi overbought mirror + rsi_overbought (B3)"
```

### Task C5: Backtest is direction-aware (TDD via extracted decision helper)

**Files:**
- Modify: `backend/app/services/strategy_backtest.py:97–106` (+ new module-level `_entry_side` helper near the top)
- Test: `backend/tests/test_strategy_backtest_bearish.py` (new)

**Why a helper:** asserting `n_trades >= 1` on a synthetic fixture is unreliable — `backtesting.py` only fills a `self.sell(limit=entry)` when price trades **up to** `entry`, which a death-cross fixture may never do. The *entry-side decision* is the actual logic to test; extract it into a pure function and unit-test it deterministically. `run_strategy_backtest` has **no default** for `direction` (it is keyword-only, `direction: str`), so all call sites already pass it — no regression risk to the bullish path.

- [ ] **Step 1: Write the failing test (pure decision function)**

```python
from app.services.strategy_backtest import _entry_side

def test_entry_side_bullish_admits_stop_below_target_above():
    assert _entry_side("Bullish", entry=100, sl=95, tp=110) == "buy"
    assert _entry_side("Bullish", entry=100, sl=105, tp=110) is None  # stop wrong side

def test_entry_side_bearish_admits_stop_above_target_below():
    assert _entry_side("Bearish", entry=100, sl=105, tp=90) == "sell"
    assert _entry_side("Bearish", entry=100, sl=95, tp=90) is None    # stop wrong side
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_backtest_bearish.py -v`
Expected: FAIL — `_entry_side` does not exist.

- [ ] **Step 3: Add the helper and use it in the backtest**

Add near the top of `strategy_backtest.py` (module level):

```python
def _entry_side(direction: str, *, entry: float, sl: float, tp: float) -> str | None:
    """Decide the order side, or None if the stop/target are on the wrong side of entry.

    Bullish: stop below entry, target above  → 'buy'
    Bearish: stop above entry, target below  → 'sell'
    """
    if direction == "Bullish":
        return "buy" if sl < entry < tp else None
    return "sell" if tp < entry < sl else None
```

Replace lines 97–106 with:

```python
            if not self.position:
                sig = fn(slice_bars, direction=direction, **(params or {}))
                if sig is not None:
                    side = _entry_side(direction, entry=sig.entry_price,
                                       sl=sig.stop_price, tp=sig.target_price)
                    if side == "buy":
                        self.buy(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)
                    elif side == "sell":
                        self.sell(limit=sig.entry_price, sl=sig.stop_price, tp=sig.target_price)
```

`fn` now must accept `direction` — guaranteed by Tasks C1–C4.

- [ ] **Step 4: Add an integration smoke test (no trade-count assertion)**

```python
from app.services.strategy_backtest import run_strategy_backtest
from tests.test_strategy_engine_bearish import _death_cross_bars

def test_bearish_backtest_runs_and_tags_direction():
    bars = []
    for _ in range(6):
        for b in _death_cross_bars():
            nb = dict(b); nb["time"] = len(bars); bars.append(nb)
    res = run_strategy_backtest(bars, strategy="ma_crossover",
                                direction="Bearish", min_trades=0, min_win_rate=0.0)
    assert res.direction == "Bearish"   # propagates; does not crash on the sell path
```

- [ ] **Step 5: Run to verify pass + no bullish regression**

Run: `cd backend && pytest tests/test_strategy_backtest_bearish.py -v && pytest tests/ -k backtest -v`
Expected: PASS; existing bullish backtests unaffected.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/strategy_backtest.py backend/tests/test_strategy_backtest_bearish.py
git commit -m "feat(backtest): direction-aware entry-side helper + sell path (B4)"
```

### Task C6: Stock-scan router passes direction to the signal fn

**Files:**
- Modify: `backend/app/routers/stock_scan.py:236`
- Test: extend `backend/tests/test_stock_scan_router.py`

- [ ] **Step 1: Write the failing test**

Add a test that runs the scan with `direction="Bearish"` against a downtrend fixture and asserts the returned position card has `direction == "Bearish"` and `stop_price > entry_price > target_price`. Use the router's existing test harness/fixtures pattern in `test_stock_scan_router.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_stock_scan_router.py -k bearish -v`
Expected: FAIL — signal generated with bullish shape (no direction passed).

- [ ] **Step 3: Implement**

Change line 236 from:

```python
            signal = signal_fn(bars[-120:], **signal_kwargs)
```

to:

```python
            signal = signal_fn(bars[-120:], direction=req.direction, **signal_kwargs)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_stock_scan_router.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_stock_scan_router.py
git commit -m "feat(stock-scan): thread direction into signal generation (B5)"
```

### Task C7: StockPositionCard risk/RR/tone are direction-correct

**Files:**
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx:45,138,141` and the target-tone block (~284)

- [ ] **Step 1: Fix risk magnitude in `defaultOverlay` (line 45)**

```tsx
  const risk  = Math.abs(entry - stop);
```

Targets must still move in the trade's favor. Because bearish stop > entry, change t2/t3 (lines 47–48) to be direction-aware:

```tsx
  const dir   = card.direction;
  const sign  = dir === 'Bullish' ? 1 : -1;
  const t1    = card.strategy.target_price;
  const t2    = Math.round((entry + sign * 2 * risk) * 100) / 100;
  const t3    = Math.round((entry + sign * 3 * risk) * 100) / 100;
```

- [ ] **Step 2: Fix derived risk + R:R (lines 138, 141)**

```tsx
  const riskPerShare = Math.abs(overlay.entry - overlay.stop);
  const riskDollars  = overlay.shares * riskPerShare;
  const sizeDollars  = overlay.shares * overlay.entry;
  const rrAt = (t: number) =>
    riskPerShare > 0 ? Math.abs(t - overlay.entry) / riskPerShare : 0;
```

- [ ] **Step 3: Fix target-tone / return-pct (~line 284)**

Make profit direction-aware so a downward move shows `pass`:

```tsx
  const profitPct = (price: number) =>
    overlay.entry > 0
      ? (card.direction === 'Bullish'
          ? (price - overlay.entry) / overlay.entry
          : (overlay.entry - price) / overlay.entry) * 100
      : 0;
  // use profitPct(price) where retPct was computed; tone = profitPct(...) > 0 ? 'pass' : 'reject'
```

- [ ] **Step 4: Typecheck + existing tests**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=StockPositionCard`
Expected: clean; tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/organisms/StockPositionCard/
git commit -m "fix(stock-card): direction-correct risk, R:R and target tone (B6)"
```

### Task C8: Strategy-watch alerts are direction-aware (record + evaluator + text)

**Files:**
- Modify: `backend/app/services/strategy_watch_store.py:77–106` (add `direction` to record + `add_watch`/`add_watches_bulk`)
- Modify: `backend/app/routers/` strategy-watch create endpoint + its request schema (add optional `direction`)
- Modify: `backend/app/services/strategy_watch_evaluator.py:80,83,100,150–162` (pass direction to `get_active` AND `fn`; direction-aware text), docstring line 7
- Test: `backend/tests/test_strategy_watch_bearish.py` (new)

**Verified facts (no assumptions):** in the evaluator loop `w` is a **dict** (`w["id"]`, `w.get("params_override")`, `w["last_state"]`); it has **no `direction`** today. The signal is generated by `fn(bars, **adopted)` at line 83 **without** direction, so watches detect only bullish setups even after C1–C4. The alert subject comes from the `_SUBJECT_PREFIX` dict (line 150–155) consumed in `_format_event` (line 158) — line 151 is a dict literal, not an interpolated string, so the verb fix belongs in `_format_event`, not on line 151.

- [ ] **Step 1: Write the failing test**

```python
import backend.app.services.strategy_watch_evaluator as ev_mod  # adjust to real import path

def test_bearish_watch_emits_short_setup(monkeypatch):
    # a watch carrying direction="Bearish" whose strategy fires a short entry
    # should produce an entry event with direction "Bearish" and "short" in the reason.
    # Use the evaluator's public entrypoint with a stubbed bar source + a watch dict
    # that includes "direction": "Bearish". Assert event.direction == "Bearish"
    # and "short" in event.reason.lower() and "buy" not in event.reason.lower().
    ...
```

Wire it through the evaluator's real public function and watch-store fixture (see existing evaluator tests for the harness).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_watch_bearish.py -v`
Expected: FAIL — direction not stored/passed; reason says "buy setup".

- [ ] **Step 3a: Store direction on the watch record**

In `strategy_watch_store.py`, extend `add_watch` and the record:

```python
    def add_watch(self, symbol: str, strategy_key: str,
                  params_override: dict | None = None,
                  direction: str = "Bullish") -> dict:
        ...
            entry = {
                "id": f"wch_{uuid.uuid4().hex[:12]}",
                "symbol": symbol,
                "strategy_key": strategy_key,
                "direction": direction,            # NEW
                "params_override": dict(params_override or {}),
                "enabled": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_state": _fresh_state(),
            }
```

Thread `direction` through `add_watches_bulk(symbols, strategy_key, direction="Bullish")` AND both watch endpoints in `backend/app/routers/strategy_watch.py`: the create endpoint (schema `AddWatch`, ~line 16) and the bulk endpoint (schema `BulkAdd`, ~line 22, handler ~line 56) — each gets an optional `direction: str = "Bullish"` field passed to the store. Existing rows without the key fall back via `.get("direction", "Bullish")`.

- [ ] **Step 3b: Evaluator passes direction to both `get_active` and the signal fn**

At evaluator lines 80–83:

```python
            wdir = w.get("direction", "Bullish")
            adopted = get_active(key, wdir)
            params_override = w.get("params_override") or {}
            adopted.update(params_override)
            signal = fn(bars, direction=wdir, **adopted)
```

- [ ] **Step 3c: Direction-aware alert text**

Line 100 `reason=` — derive the verb from `signal.direction`:

```python
                    reason=(f"{symbol}: {key} {'short' if signal.direction == 'Bearish' else 'long'} setup — "
                            f"entry {signal.entry_price}, stop {signal.stop_price}, "
                            f"target {signal.target_price} (R:R {round(signal.rr_ratio, 2)})"),
```

In `_format_event` (line 158–162), make the entry subject direction-aware using `ev.direction`:

```python
    if ev.event_type == "entry":
        label = f"{'Short' if ev.direction == 'Bearish' else 'Long'} setup"
    else:
        label = _SUBJECT_PREFIX.get(ev.event_type, ev.event_type)
```

Update the module docstring (line 7–8) to drop "Bullish-only".

- [ ] **Step 3d: Make the armed-phase EXIT transitions direction-aware (critical)**

The armed-phase exits at lines 111/120 are hardcoded bullish (`close <= stop_price` for stop, `close >= target_price` for target). For a bearish watch, stop > entry > target, so a bullish stop check fires spuriously on the first evaluation after arming. Mirror the comparisons by the armed `state["direction"]`:

```python
        elif phase == "armed":
            sdir = state.get("direction", "Bullish")
            stop_price = state.get("stop_price")
            target_price = state.get("target_price")
            stop_hit = (
                (close <= stop_price) if sdir == "Bullish" else (close >= stop_price)
            ) if stop_price is not None else False
            target_hit = (
                (close >= target_price) if sdir == "Bullish" else (close <= target_price)
            ) if target_price is not None else False
            if stop_hit:
                # ...existing exit_stop event + state reset...
            elif target_hit:
                # ...existing exit_target event + state reset...
            elif signal is not None and signal.direction != state.get("direction"):
                # ...existing reversal branch (unchanged)...
```

Keep the existing event payloads/state resets inside each branch; only the trigger conditions change. `state["direction"]` is already stored at arm time (line 104).

Add a watch test fixture: arm a bearish watch (entry 100, stop 105, target 90), feed `close=104` → assert NO exit_stop (104 < 105 is not a bearish stop), then `close=106` → exit_stop, and from a fresh arm `close=89` → exit_target.

- [ ] **Step 4: Run to verify pass + no bullish regression**

Run: `cd backend && pytest tests/test_strategy_watch_bearish.py -v && pytest tests/ -k watch -v`
Expected: new PASS; existing watch tests PASS (default `direction="Bullish"` preserves behavior).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_watch_store.py backend/app/services/strategy_watch_evaluator.py backend/app/routers/ backend/tests/test_strategy_watch_bearish.py
git commit -m "feat(alerts): direction-aware strategy watches — record, signal, text (B9)"
```

### Task C9: Step-4 strategy descriptions are direction-aware (spec Part 4)

**Files:**
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx` (the `STRATEGIES` description array)

- [ ] **Step 1: Show direction-appropriate copy**

The `STRATEGIES` array describes each setup in bullish terms ("Steady uptrends", "Dip to 20-EMA … in uptrend", "Below recent swing low"). Make the displayed `when`/`entry`/`stop`/`exit` text switch on the chosen direction (`scanStore.context.direction`). Provide a bearish string for each strategy mirroring the bullish one (e.g. pullback_ema bearish: "Steady downtrends" / "Bounce to 20-EMA in downtrend" / "Above recent swing high" / "Prior low / trailing stop under lower highs"). Purely presentational — no scan-logic change.

- [ ] **Step 2: Typecheck + commit**

Run: `cd frontend && npm run typecheck`
Expected: clean.

```bash
git add "frontend/app/(frame)/screener/step-4-stocks/page.tsx"
git commit -m "feat(stock-scan): direction-aware strategy descriptions (Part 4)"
```

---

# Phase D — Fundamentals gate mirror (B10)

**Why:** Bullish demotes weak fundamentals; the true mirror demotes **strong** fundamentals for shorts (don't short quality companies). Safety reject stays for both.

### Task D1: Config thresholds

**Files:**
- Modify: `backend/config/scoring_rules.yaml` (`fundamentals_gate` block, ~lines 266–269)

- [ ] **Step 1: Add the bearish mirror thresholds**

```yaml
fundamentals_gate:
  enabled: true
  cautionBelow: 45   # bullish: demote weak fundamentals
  rejectBelow: 30    # bullish
  cautionAbove: 70   # bearish: caution shorting strong companies
  rejectAbove: 80    # bearish: reject shorting very strong companies
```

- [ ] **Step 2: Commit**

```bash
git add backend/config/scoring_rules.yaml
git commit -m "feat(fundamentals): add bearish mirror gate thresholds (B10)"
```

### Task D2: Gate logic mirror (TDD)

**Files:**
- Modify: `backend/app/scoring/stock_scorer.py:1031–1043`
- Test: `backend/tests/test_fundamentals_gate_bearish.py` (new)

- [ ] **Step 1: Write the failing test**

The real `score_stock` signature (verified, `stock_scorer.py:870`) is
`score_stock(symbol, direction, horizon, bars, ..., fundamentals=None, fundamentals_gate=None)`.
The gate block only runs when **both** `fundamentals` and `fundamentals_gate` are
non-None **and** horizon is not Intraday. `fundamentals` must be a
`FundamentalHealth` dataclass (`fundamentals_scorer.py:14`) with required fields
`score, quality_label, risk_label, growth_score, quality_score, risk_score`.
No fixtures exist — construct them inline.

```python
from app.scoring.stock_scorer import score_stock
from app.scoring.fundamentals_scorer import FundamentalHealth

_GATE = {"enabled": True, "cautionBelow": 45, "rejectBelow": 30,
         "cautionAbove": 70, "rejectAbove": 80}

def _flat_bars(n=260, price=100.0):
    return [{"open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1_000_000, "time": i} for i in range(n)]

def _health(score: int) -> FundamentalHealth:
    return FundamentalHealth(score=score, quality_label="x", risk_label="x",
                             growth_score=score, quality_score=score, risk_score=score,
                             safety_flags=[], detail={})

def _fund_rule(card):
    return next(r for r in card.rules if r.name == "fundamentals")

def test_bearish_demotes_strong_fundamentals():
    card = score_stock("AAPL", direction="Bearish", horizon="Swing",
                       bars=_flat_bars(), fundamentals=_health(90),
                       fundamentals_gate=_GATE)
    assert _fund_rule(card).status in ("CAUTION", "REJECT")

def test_bearish_passes_weak_fundamentals():
    card = score_stock("XYZ", direction="Bearish", horizon="Swing",
                       bars=_flat_bars(), fundamentals=_health(20),
                       fundamentals_gate=_GATE)
    assert _fund_rule(card).status == "PASS"
```

If `horizon`/`direction` are typed `Literal`s, the string values `"Swing"`/`"Bearish"` match. If `_flat_bars()` is rejected by an upstream rule before the gate appends its result, increase the count or add gentle trend — the only requirement is that a `"fundamentals"` rule is appended (the gate runs regardless of other rule outcomes).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_fundamentals_gate_bearish.py -v`
Expected: FAIL — bearish is currently display-only (always PASS).

- [ ] **Step 3: Implement the mirror**

Replace the `else: # Bearish: display only` branch (lines 1041–1043) with:

```python
            elif direction in ("Bearish", "bearish"):
                caution_above = fundamentals_gate.get("cautionAbove", 70)
                reject_above = fundamentals_gate.get("rejectAbove", 80)
                if health_score > reject_above:
                    final_status = _worse(final_status, "REJECT")
                    fund_status = "REJECT"
                elif health_score > caution_above:
                    final_status = _worse(final_status, "CAUTION")
                    fund_status = "CAUTION"
                else:
                    fund_status = "PASS"
            else:
                fund_status = "PASS"
```

- [ ] **Step 4: Run to verify pass + bullish regression**

Run: `cd backend && pytest tests/test_fundamentals_gate_bearish.py -v && pytest tests/ -k fundamentals -v`
Expected: new PASS; bullish fundamentals tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/stock_scorer.py backend/tests/test_fundamentals_gate_bearish.py
git commit -m "feat(fundamentals): bearish mirror demotes strong fundamentals (B10)"
```

---

# Phase E — Direction-keyed tuned params (B11)

**Why:** Once bearish backtests run, a bearish tuning run would overwrite bullish `active` params. Storage must separate them. Migrate existing `active` → `active.bullish`.

### Task E1: Store reads/writes per direction (TDD)

**Files:**
- Modify: `backend/app/services/strategy_param_store.py:36–42,85–113`
- Test: `backend/tests/test_strategy_param_store_direction.py` (new)

- [ ] **Step 1: Write the failing test**

```python
from app.services import strategy_param_store as store

def test_get_active_is_direction_keyed(tmp_path, monkeypatch):
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(
        "strategies:\n"
        "  pullback_ema:\n"
        "    active:\n"
        "      bullish: { ema_period: 50 }\n"
        "      bearish: { ema_period: 35 }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    assert store.get_active("pullback_ema", "Bullish")["ema_period"] == 50
    assert store.get_active("pullback_ema", "Bearish")["ema_period"] == 35

def test_get_active_migrates_legacy_flat_active(tmp_path, monkeypatch):
    cfg = tmp_path / "strategy_params.yaml"
    cfg.write_text(
        "strategies:\n  pullback_ema:\n    active: { ema_period: 50 }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "CFG", cfg)
    store._CACHE = None
    # legacy flat active is treated as the bullish set
    assert store.get_active("pullback_ema", "Bullish")["ema_period"] == 50
    assert store.get_active("pullback_ema", "Bearish") == {}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_strategy_param_store_direction.py -v`
Expected: FAIL — `get_active` takes one arg.

- [ ] **Step 3: Implement direction-keyed access with legacy fallback**

```python
def get_active(strategy: str, direction: str = "Bullish") -> dict:
    """Active params for a strategy + direction.

    Supports both the new nested shape `active: {bullish: {...}, bearish: {...}}`
    and the legacy flat shape `active: {...}` (treated as the bullish set).
    """
    active = _load().get("strategies", {}).get(strategy, {}).get("active", {})
    key = direction.lower()
    if key in ("bullish", "bearish") and (
        "bullish" in active or "bearish" in active
    ):
        return dict(active.get(key, {}))
    # legacy flat active = bullish only
    return dict(active) if key == "bullish" else {}


def adopt(strategy: str, params: dict, direction: str = "Bullish") -> None:
    """Archive then write `active[direction]` = params (atomic, backup-first)."""
    global _CACHE
    data = copy.deepcopy(_load())
    if CFG.exists():
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = CFG.with_suffix(f".bak.{timestamp}-{uuid.uuid4().hex[:8]}.yaml")
        shutil.copy(CFG, backup_path)
    strat = data.setdefault("strategies", {}).setdefault(strategy, {})
    active = strat.get("active", {})
    # migrate legacy flat active → nested bullish on first nested write
    if active and not ({"bullish", "bearish"} & set(active.keys())):
        active = {"bullish": active}
    active[direction.lower()] = copy.deepcopy(params)
    strat["active"] = active
    tmp = CFG.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CFG)
    _CACHE = None
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_strategy_param_store_direction.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/strategy_param_store.py backend/tests/test_strategy_param_store_direction.py
git commit -m "feat(tuning): direction-keyed active params with legacy migration (B11)"
```

### Task E2: Callers pass direction

**Files:**
- Modify: `backend/app/routers/stock_scan.py:83` (`_merge_strategy_params`)
- Modify: any `adopt(` and `get_active(` callers — find them.

- [ ] **Step 1: Find all callers**

Run: `cd backend && rg "get_active\(|\.adopt\(|adopt\(" -n app/`
Expected callers to update:
- `stock_scan.py:_merge_strategy_params` (reads active) — this task.
- `strategy_watch_evaluator.py:80` — `get_active(key)` → already handled in **Task C8 Step 3b** (passes `wdir`); do not duplicate here.
- `strategy_tuning.py` `/adopt` endpoint — the only `adopt()` caller (verified: `tuning_scheduler.py` does NOT call adopt, so no scheduler-clobber risk). Updated in Step 3 below.
- The one-arg default `direction="Bullish"` keeps the 8+ existing optimizer tests green (they read `active.bullish` / legacy-flat).

- [ ] **Step 2: Thread direction through `_merge_strategy_params`**

```python
def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
    """Adopted defaults for this direction, overridden by per-request kwargs."""
    merged = get_active(strategy, direction)
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged
```

Update the call site (line 233–235):

```python
            signal_kwargs = _merge_strategy_params(
                req.strategy, req.direction,
                _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req),
            )
```

Add `rsi_overbought` to the `mean_reversion_rsi` kwargs lambda (line 78) so a bearish request forwards it:

```python
    "mean_reversion_rsi": lambda r: {"rsi_period": r.rsi_period, "rsi_oversold": r.rsi_oversold, "rsi_overbought": getattr(r, "rsi_overbought", 70.0), "trend_sma": r.rsi_trend_sma},
```

(Add `rsi_overbought: float = 70.0` to `StockScanRequest` in `backend/app/schemas/stock_scan.py`.)

- [ ] **Step 3: Update the adopt endpoint to pass + echo direction**

- Add an explicit `direction: str = "Bullish"` field to `AdoptRequest` (`strategy_tuning.py:23–25`). (Do **not** silently couple to the global `get_direction()` YAML key — make it explicit in the request.)
- Pass it into `store.adopt(body.strategy, body.params, direction=body.direction)`.
- Fix the endpoint's echo return (line ~178) from `store.get_active(body.strategy)` to `store.get_active(body.strategy, body.direction)` so the response reflects the adopted direction, not always bullish.
- (The watch-evaluator caller is handled in Task C8 Step 3b — not here.)

- [ ] **Step 4: Run full backend suite**

Run: `cd backend && pytest -q`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/app/schemas/stock_scan.py backend/app/services/strategy_param_optimizer.py backend/app/services/strategy_tuning.py
git commit -m "feat(tuning): callers pass direction; forward rsi_overbought (B11)"
```

---

# Phase F — Options spreads (B12)

**Why:** Add bear put (debit) and bear call (credit) spreads; surface the IV-appropriate one as primary, the other as an alternative.

### Task F1: Spread economics builder (TDD)

**Files:**
- Create: `backend/app/scoring/spread_builder.py`
- Test: `backend/tests/test_spread_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from app.scoring.spread_builder import build_bear_put, build_bear_call

CHAIN_PUTS = [   # strike, bid, ask, delta
    {"strike": 180, "bid": 4.0, "ask": 4.2, "delta": -0.45},
    {"strike": 175, "bid": 2.0, "ask": 2.2, "delta": -0.30},
]
CHAIN_CALLS = [
    {"strike": 175, "bid": 3.0, "ask": 3.2, "delta": 0.55},
    {"strike": 180, "bid": 1.4, "ask": 1.6, "delta": 0.35},
]

def test_bear_put_is_a_debit_with_capped_risk():
    sp = build_bear_put(CHAIN_PUTS, expiry="2026-07-17", width=5, short_delta=0.30)
    assert sp.spread_type == "bear_put"
    assert sp.net_debit_credit > 0                      # debit (you pay)
    assert sp.max_loss == round(sp.net_debit_credit, 2) # loss = debit
    assert sp.max_profit == round(5 - sp.net_debit_credit, 2)
    assert sp.legs[0].action == "BUY" and sp.legs[0].right == "P"   # higher strike
    assert sp.legs[1].action == "SELL" and sp.legs[1].right == "P"  # lower strike

def test_bear_call_is_a_credit_with_capped_risk():
    sp = build_bear_call(CHAIN_CALLS, expiry="2026-07-17", width=5, short_delta=0.35)
    assert sp.spread_type == "bear_call"
    assert sp.net_debit_credit < 0                      # credit (you collect)
    credit = abs(sp.net_debit_credit)
    assert sp.max_profit == round(credit, 2)
    assert sp.max_loss == round(5 - credit, 2)
    assert sp.legs[0].action == "SELL" and sp.legs[0].right == "C"  # lower strike
    assert sp.legs[1].action == "BUY" and sp.legs[1].right == "C"   # higher strike
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_spread_builder.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the builder**

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass
class SpreadLeg:
    right: Literal["C", "P"]
    strike: float
    expiry: str
    action: Literal["BUY", "SELL"]
    qty: int
    bid: float
    ask: float


@dataclass
class Spread:
    spread_type: Literal["bear_put", "bear_call"]
    legs: list[SpreadLeg]
    net_debit_credit: float   # >0 debit (paid), <0 credit (collected)
    max_profit: float
    max_loss: float
    breakeven: float


def _nearest_by_delta(chain: list[dict], target_abs_delta: float) -> dict:
    return min(chain, key=lambda c: abs(abs(c.get("delta", 0)) - target_abs_delta))


def build_bear_put(puts: list[dict], *, expiry: str, width: float, short_delta: float) -> Spread:
    """Buy a higher-strike put, sell a put `width` lower. Debit spread."""
    short = _nearest_by_delta(puts, short_delta)
    long_strike = short["strike"] + width
    long = min(puts, key=lambda c: abs(c["strike"] - long_strike))
    debit = round(long["ask"] - short["bid"], 2)
    w = long["strike"] - short["strike"]
    return Spread(
        spread_type="bear_put",
        legs=[
            SpreadLeg("P", long["strike"], expiry, "BUY", 1, long["bid"], long["ask"]),
            SpreadLeg("P", short["strike"], expiry, "SELL", 1, short["bid"], short["ask"]),
        ],
        net_debit_credit=debit,
        max_profit=round(w - debit, 2),
        max_loss=round(debit, 2),
        breakeven=round(long["strike"] - debit, 2),
    )


def build_bear_call(calls: list[dict], *, expiry: str, width: float, short_delta: float) -> Spread:
    """Sell a lower-strike call, buy a call `width` higher. Credit spread."""
    short = _nearest_by_delta(calls, short_delta)
    long_strike = short["strike"] + width
    long = min(calls, key=lambda c: abs(c["strike"] - long_strike))
    credit = round(short["bid"] - long["ask"], 2)
    w = long["strike"] - short["strike"]
    return Spread(
        spread_type="bear_call",
        legs=[
            SpreadLeg("C", short["strike"], expiry, "SELL", 1, short["bid"], short["ask"]),
            SpreadLeg("C", long["strike"], expiry, "BUY", 1, long["bid"], long["ask"]),
        ],
        net_debit_credit=round(-credit, 2),
        max_profit=round(credit, 2),
        max_loss=round(w - credit, 2),
        breakeven=round(short["strike"] + credit, 2),
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && pytest tests/test_spread_builder.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/scoring/spread_builder.py backend/tests/test_spread_builder.py
git commit -m "feat(options): bear put/call spread economics builder (B12)"
```

### Task F2: Primary-structure selection by IV rank (TDD)

**Files:**
- Modify: `backend/app/scoring/spread_builder.py` (add `choose_primary`)
- Test: extend `backend/tests/test_spread_builder.py`

- [ ] **Step 1: Write the failing test**

```python
from app.scoring.spread_builder import choose_primary

def test_high_iv_prefers_credit_spread():
    assert choose_primary(iv_rank=70, threshold=50) == "bear_call"

def test_low_iv_prefers_debit_spread():
    assert choose_primary(iv_rank=30, threshold=50) == "bear_put"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_spread_builder.py::test_high_iv_prefers_credit_spread -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def choose_primary(*, iv_rank: float, threshold: float) -> Literal["bear_call", "bear_put"]:
    """High IV → sell premium (credit / bear call). Low IV → buy premium (debit / bear put)."""
    return "bear_call" if iv_rank >= threshold else "bear_put"
```

- [ ] **Step 4: Run + commit**

Run: `cd backend && pytest tests/test_spread_builder.py -v`
Expected: PASS.

```bash
git add backend/app/scoring/spread_builder.py backend/tests/test_spread_builder.py
git commit -m "feat(options): IV-rank primary-structure selection (B12)"
```

### Task F3: Frontend spread types

**Files:**
- Modify: `frontend/types/domain.ts:168–197`

- [ ] **Step 1: Add types (no behavior change yet)**

```ts
export type SpreadType = 'single' | 'bear_put' | 'bear_call';

export interface OptionLeg {
  right:  'C' | 'P';
  strike: number;
  expiry: string;
  action: 'BUY' | 'SELL';
  qty:    number;
  bid:    number;
  ask:    number;
}
```

Extend `TradeCardData` (after line 188) with optional fields so existing single-leg cards are unaffected:

```ts
  spreadType?:       SpreadType;     // absent ⇒ legacy single-leg
  legs?:             OptionLeg[];
  netDebitCredit?:   number;         // >0 debit, <0 credit
  maxProfit?:        number;
  maxLoss?:          number;
  breakeven?:        number;
```

Also extend `AlternativeContract` (`types/domain.ts:246`) with the same optional spread fields, so the non-primary spread can be carried as an alternative (today it only models single-leg contracts):

```ts
  // add to AlternativeContract:
  spreadType?:     SpreadType;
  legs?:           OptionLeg[];
  netDebitCredit?: number;
  maxProfit?:      number;
  maxLoss?:        number;
  breakeven?:      number;
```

- [ ] **Step 2: Mirror the fields on the BACKEND Pydantic models (critical)**

FastAPI serializes the scan response through Pydantic models, so fields absent there are silently dropped before reaching the frontend. In `backend/app/schemas/__init__.py`, add a leg sub-model and the optional spread fields to `TradeCardData` (~line 378) and `AlternativeContract` (~line 359):

```python
class OptionLeg(BaseModel):
    right: Literal["C", "P"]
    strike: float
    expiry: str
    action: Literal["BUY", "SELL"]
    qty: int
    bid: float
    ask: float

# add to both TradeCardData and AlternativeContract:
    spread_type: Optional[Literal["single", "bear_put", "bear_call"]] = None
    legs: Optional[list[OptionLeg]] = None
    net_debit_credit: Optional[float] = None
    max_profit: Optional[float] = None
    max_loss: Optional[float] = None
    breakeven: Optional[float] = None
```

Note the snake_case↔camelCase boundary: if the schema uses a `populate_by_name`/alias generator, follow the existing field-naming convention in that file; otherwise map snake_case → the frontend camelCase fields in `api.ts` where the response is adapted.

- [ ] **Step 3: Typecheck + backend import check**

Run: `cd frontend && npm run typecheck && cd ../backend && python -c "import app.schemas"`
Expected: clean; no import error.

- [ ] **Step 4: Commit**

```bash
git add frontend/types/domain.ts backend/app/schemas/__init__.py
git commit -m "feat(options): spread types on TradeCardData — frontend + backend schema (B12)"
```

### Task F4: Backend attaches spreads to scan candidates

**Files:**
- Modify: `backend/app/routers/scan.py` (Pass-2 contract build, ~lines 342–344 fetch + 505–594 attach)
- Modify: `backend/app/schemas/` scan request — add spread params here (NOT in Phase G), with defaults
- Test: extend the scan router test for a bearish request asserting a `bear_put`/`bear_call` structure appears with correct legs.

**Verified facts:** the chain fetcher is `fetch_option_chain_async(client, symbol, option_type=...)` (async, takes the httpx `client`) at `scan.py:50,344` — not a sync `fetch_option_chain`. Pass 2 fetches one chain per **survivor** (a small shortlist, not the whole universe), so fetching a second chain doubles only the shortlist's fetches; do it with `asyncio.gather` to keep it parallel.

- [ ] **Step 1: Add spread params to the scan request schema (with defaults)**

In the real request model `ScanRequest` (`backend/app/schemas/__init__.py:410`), add nested-or-flat fields with defaults: `spread_width: float = 5`, `short_leg_delta: float = 0.30`, `iv_rank_threshold: float = 50`, `min_credit: float = 0.50`, `max_debit_pct: float = 40`. These ship with defaults so F4 is self-contained.

**Channel note (resolves the F4→G2 seam):** the frontend currently calls `api.postScan(universe, direction, horizon, filters, overrides)` (`RunScanButton:159`); these spread fields are top-level on `ScanRequest`, not inside `filters`/`overrides`. Add an explicit optional 6th argument `spreads?: { spread_width; short_leg_delta; iv_rank_threshold; min_credit; max_debit_pct }` to `api.postScan` that maps to the top-level `ScanRequest` fields. F4 leaves it `undefined` (defaults apply); G2 Step 2 populates it from the settings slice. State this contract here so G2 has a defined channel.

- [ ] **Step 2: Write the failing test**

Add a bearish scan test asserting the response's primary structure matches `choose_primary(iv_rank, threshold)` and that the non-primary spread is present in `alternatives` with `spreadType`/`legs` populated.

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/ -k "scan and spread" -v`
Expected: FAIL.

- [ ] **Step 4: Implement**

For bearish candidates in Pass 2, decide the primary via `choose_primary(iv_rank, threshold)` FIRST, then fetch the chain(s) needed (`fetch_option_chain_async(client, symbol, option_type="P")` and/or `"C"`) via `asyncio.gather`. Build the primary spread (`build_bear_put`/`build_bear_call`) with `spread_width`/`short_leg_delta` from the request; attach its `legs`/economics to the trade card. Build the other spread as an `AlternativeContract` (now carries spread fields, Task F3) with a `reason`. Reject credit spreads below `min_credit` and debit spreads whose debit exceeds `max_debit_pct%` of width.

- [ ] **Step 5: Run + commit (include the `api.ts` arg added in Step 1)**

Run: `cd backend && pytest tests/ -k scan -v && cd ../frontend && npm run typecheck`
Expected: PASS; clean.

```bash
git add backend/app/routers/scan.py backend/app/schemas/__init__.py backend/tests/ frontend/lib/api.ts
git commit -m "feat(options): attach bear spreads to bearish candidates + postScan spreads arg (B12)"
```

### Task F5: Spread display — Step 6 columns + Step 7 two-leg panel

**Files:**
- Modify: `frontend/app/(frame)/screener/step-6-contracts/page.tsx` (spread columns)
- Modify: `frontend/components/organisms/TradeCard/index.tsx` (two-leg panel)
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx` (order submission for spreads)

- [ ] **Step 0: Step 6 — spread columns (spec Part 3)**

When a candidate carries a spread structure, render the extra columns in the Step 6 table: spread-type badge (BPS/BCS), net debit/credit, max gain, max loss, breakeven. Single-leg rows keep the existing columns (render the spread columns empty/`—` when `spreadType` is absent). Follow the existing sortable-table conventions in this file.

- [ ] **Step 1: Render legs when `card.spreadType && card.spreadType !== 'single'`**

Show each leg (action, qty, strike, right, expiry), then net debit/credit, max profit, max loss, breakeven. Keep the existing single-leg layout when `spreadType` is absent.

- [ ] **Step 2: Manual order path for spreads**

In `SendToBrokerDialog`, when a spread is present, render the copy-trade table with one row per leg (each leg's own BUY/SELL). The IBKR button stays greyed. (No live multi-leg routing — out of scope.)

- [ ] **Step 3: Typecheck + tests**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=TradeCard`
Expected: clean; pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/TradeCard/ "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(options): two-leg spread panel + manual copy-trade (B12)"
```

---

# Phase G — Settings: Spreads section (Part 7)

**Why:** Make the spread strike/width/IV rules editable per horizon, with defaults.

### Task G1: settingsStore spread fields (TDD)

**Files:**
- Modify: `frontend/lib/settingsStore.ts`
- Test: `frontend/lib/__tests__/settingsStore.spreads.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { useSettingsStore } from '@/lib/settingsStore';

test('spread defaults exist', () => {
  const s = useSettingsStore.getState();
  expect(s.spreads.shortLegDelta).toBe(0.30);
  expect(s.spreads.widthPoints).toBe(5);
  expect(s.spreads.ivRankThreshold).toBe(50);
  expect(s.spreads.minCredit).toBe(0.50);
  expect(s.spreads.maxDebitPctOfWidth).toBe(40);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=settingsStore.spreads`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add a `spreads` slice with the five defaults and a setter. Bump the persist `version` and add a `migrate` branch that injects `spreads` defaults for older persisted state (per the project's Zustand convention — versioned migrate, SSR guard, `skipHydration`). Do not use `?? []`-style fallbacks in selectors (project rule).

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npm run test -- --testPathPattern=settingsStore.spreads`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/settingsStore.ts frontend/lib/__tests__/settingsStore.spreads.test.ts
git commit -m "feat(settings): spread defaults in settingsStore (Part 7)"
```

### Task G2: Spreads UI section

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx`

- [ ] **Step 1: Add a Spreads sub-section under Score weights & parameters**

Render the five fields as editable inputs, following the existing per-horizon tab pattern (Intraday / Swing / Position / Custom). Read/write via the `spreads` slice. Match existing form conventions: `weight={400}` labels, CSS-module styling, no inline color literals.

- [ ] **Step 2: Wire Settings → scan request**

The `ScanRequest` schema fields and the `api.postScan` `spreads?` argument already exist (Task F4 Step 1). Here, at the Run Scan call site (`RunScanButton`), pass `spreads: { spread_width, short_leg_delta, iv_rank_threshold, min_credit, max_debit_pct }` read from the `settingsStore` `spreads` slice, so the screener uses configured values instead of the F4 defaults.

- [ ] **Step 3: Typecheck + tests**

Run: `cd frontend && npm run typecheck && npm run test`
Expected: clean; all pass.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/settings/page.tsx" frontend/lib/api.ts
git commit -m "feat(settings): editable Spreads section wired to scan (Part 7)"
```

---

## Final verification (run after all phases)

- [ ] `cd backend && pytest -q` — all green
- [ ] `cd frontend && npm run typecheck` — clean
- [ ] `cd frontend && npm run test` — all green
- [ ] Manual smoke: bearish stock scan → position card shows stop above entry, positive R:R, downward targets; bearish options scan → puts fetched, long put sends BUY, spread card shows two legs with correct per-leg sides and economics; regime gate confirms on misalignment for both directions.

---

## Self-review notes (author)

- **Spec coverage:** Part 1→Phase B; Part 2→Phase A; Part 3→Phase F; Part 4→Phase C; Part 5→Phase D; Part 6→Phase E; Part 7→Phase G. All parts mapped.
- **Type consistency:** `SpreadType`, `OptionLeg`, `Spread`/`SpreadLeg`, `alignmentVerdict`, `get_active(strategy, direction)`, `_merge_strategy_params(strategy, direction, kwargs)` used consistently across tasks.
- **Round-1 adversarial audit (BMAD) findings — all resolved:**
  - BLOCKER: A2 now also fixes `AutoTradeArm/index.tsx:39` (options path → was leaving naked-short footgun).
  - BLOCKER: B4 now reads `combinedRegime` (not raw `regime:105`), so the alignment reframe reaches the gate.
  - MAJOR: D2 test now passes `fundamentals_gate` + `horizon="Swing"` and constructs `FundamentalHealth` inline (no nonexistent fixtures).
  - MAJOR: B3 corrected to `handleDirChange:738` + descriptor captured in a ref (regime not previously kept in state).
  - MAJOR: F4 uses real async `fetch_option_chain_async(client, symbol, option_type=...)`, bounds the N×2 fetch to the survivor shortlist via `asyncio.gather`, defines request-schema spread fields in F4, and `AlternativeContract` gains spread fields (F3) so it can carry the non-primary spread.
  - MAJOR: C5 reworked around a pure `_entry_side` helper (deterministic test) instead of an unprovable `n_trades>=1` assertion; corrected the false "default Bullish" claim (`direction` is keyword-only, no default).
  - MAJOR: C2 keeps the bullish `base_high` detail key (no silent regression); bearish uses `base_low`.
  - MINOR: E2 updates `strategy_watch_evaluator.py:80` caller and adds explicit `direction` to `AdoptRequest`.
- **B2/B3 interdependence:** B2 seeds `combinedRegime` on Step 1 mount; B3 seeds on fetch AND recomputes in `handleDirChange`, so a direction change on Step 3 (where direction is actually chosen) always refreshes alignment despite B2's mount-only deps.
- **Round-2 adversarial audit (BMAD) findings — all resolved (round-1 fixes re-confirmed correct against source):**
  - BLOCKER: strategy-watch records had no `direction` and the evaluator called the signal fn with no direction (watches stayed bullish). C8 now adds `direction` to the watch record + `add_watch`/bulk + create endpoint, and the evaluator passes `wdir` to BOTH `get_active` and `fn`.
  - MAJOR: `Status` is imported from `@/lib/status` (not re-exported by `domain.ts`); Phase B helper import corrected so typecheck passes.
  - MINOR: C8 alert subject fix moved to `_format_event` (line 151 is a dict literal, not interpolated).
  - MINOR: `/adopt` endpoint echo now returns `get_active(strategy, direction)`.
  - MINOR: F4→G2 channel made explicit — `api.postScan` gains a `spreads?` arg mapping to top-level `ScanRequest` fields.
  - Verified: E1 migration is back-compat — `adopt` migrates flat→`{bullish:…}`, one-arg `get_active` reads the bullish branch, existing one-arg optimizer tests stay green.
- **Round-3 adversarial audit (BMAD) findings — all resolved (R1+R2 re-confirmed CLEARED against source):**
  - MAJOR: backend Pydantic `TradeCardData`/`AlternativeContract` now also gain spread fields + `OptionLeg` sub-model (F3 Step 2) — without this, FastAPI drops spread fields at serialization and the UI never receives them.
  - MAJOR: C8 Step 3d makes the armed-phase EXIT transitions direction-aware (lines 111/120 were hardcoded bullish → bearish watches mis-fired exit_stop immediately).
  - MINOR: Step-6 spread columns covered (F5 Step 0); Step-4 direction-aware descriptions covered (new Task C9); bulk-watch direction threaded through `AddWatch`/`BulkAdd` endpoints (C8 Step 3a); F4 commit now includes `api.ts` + frontend typecheck; `RegimeDescriptor` reuses `HmmState`.
- **Line-number note for the implementer:** cited line ranges (e.g. C1 "112–136") are anchors, not exact bounds — each code block is content-complete (full new body + return). Replace through the END of the function's existing return, not the literal cited line. Re-grep the target before editing; the repo drifts.
