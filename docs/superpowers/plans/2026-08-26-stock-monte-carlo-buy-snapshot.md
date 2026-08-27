# Stock Monte Carlo First-Passage + Buy-Time Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give stock positions the same Monte Carlo first-passage estimate (probability + expected days to hit target/stop) that option positions already get in the TradeCard, and make sure every stock buy path (manual/paper AND broker auto-send) captures the buy-time "why was this bought" snapshot that the estimate depends on — then wire an "Estimate" button into the Portfolio EditDrawer for both position shapes.

**Architecture:** A new stock-native Monte Carlo function (`estimate_stock_first_passage`) sits next to the existing option one (`estimate_first_passage`) in `backend/app/scoring/first_passage.py`, reusing its GBM/ATR-volatility machinery but skipping option repricing entirely — a stock position has no strike/premium/IV, so it's a straight barrier-touch simulation against two absolute stock prices (target, stop). A new `POST /api/stocks/first-passage` endpoint exposes it. On the frontend, the existing `tradeCardSnapshotOf`/`stockCardSnapshotOf` buy-time snapshots gain the couple of fields the new endpoint needs (`strike` for options, `horizon`/`holdMax`/`stock_score` for stocks), the stock buy paths are fixed so a snapshot — and real stop/target prices — are captured on EVERY stock buy (today only the manual/paper checkbox path in `StockSendDialog` does this; the broker auto-send branch and the single-candidate `step-7-position-card` page currently create no local position record at all), and the Portfolio `EditDrawer` gets a new "Estimate" section that branches on `position.contract.endsWith('|STOCK')`-style detection to call the right endpoint.

**Tech Stack:** FastAPI + Pydantic v2 (backend), numpy GBM simulation, Next.js/TypeScript + Zustand (frontend), Jest + pytest.

---

## Investigation summary (read this before touching code)

A few things this plan depends on, found by reading the current code (no prior plan doc for this feature exists on disk — it was not found in `docs/superpowers/plans/`, so this plan reconstructs Phase 3 from the task description and the actual codebase state):

1. **Options already do this end-to-end correctly.** `frontend/app/(frame)/screener/step-7-trade-card/page.tsx`'s `positionFromOrder()` (buy basket) and `buildPaperPosition()` (single-candidate broker order) both call `tradeCardSnapshotOf(card)` and both paths persist a local `PortfolioPosition` with that snapshot attached — regardless of whether the order is a broker order or a manual/paper entry. That's the pattern stocks need to match.
2. **Stocks only capture the snapshot on SOME buy paths, and there are six call sites of `buildPaperStockPosition`/`stockCardSnapshotOf` total, not the two this plan originally assumed** (confirmed by `grep -rn "buildPaperStockPosition|stockCardSnapshotOf" frontend`):
   - `frontend/components/organisms/StockSendDialog/index.tsx` (manual branch, 2 call sites) — captures a snapshot correctly today. Its **auto-send branch** (broker order) calls only `api.postStockOrder(...)` and never creates a local position at all. Fixed in Task 5.
   - `frontend/components/organisms/StockPositionCard/index.tsx:212` (`onAddToPortfolio`) — captures a snapshot correctly today (same pattern as `StockSendDialog`'s manual branch). Its signature needs updating for Task 4's changes, but no behavior gap to fix. Updated in Task 4.
   - `frontend/components/organisms/StockPositionCard/index.tsx`'s OWN `submit()` (lines 183-204, "Section 5 — Order buttons") is a SEPARATE, DIFFERENT code path from `onAddToPortfolio` above, in the same file — it places a real broker order via `api.postStockOrder(...)` and never calls `addPosition`/`buildPaperStockPosition` at all. This is a live, reachable gap (this component is rendered from `step-4-stocks/page.tsx` and exposes IBKR/Tradier/Alpaca/Tastytrade paper buttons) with the exact same shape as `step-7-position-card/page.tsx`'s gap below. Fixed in Task 5.
   - `frontend/app/(frame)/screener/step-4-stocks/page.tsx:184` (`onRun`'s after-scan auto-execute loop) — calls `buildPaperStockPosition` with **no snapshot and no strategy at all** (`buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction)`), even though `c` is a full `PositionCardData` right there. This is the auto-buy-after-scan path — today it silently creates positions with `stop: 0, targets: []` and no "why bought" record. Fixed in Task 5.
   - `frontend/app/(frame)/screener/step-7-position-card/page.tsx`'s `submit()` calls only `api.postStockOrder(...)` — no local position, no snapshot. Fixed in Task 5.
   - `frontend/components/organisms/ChartWorkspace/index.tsx:851` (chart-click buy popover) — calls `buildPaperStockPosition(symbol, price, qty, 'Bullish')` with **no card at all** by design (its own comment: "Chart-click buy popover has no direction context to draw from — it's a manual point-and-click entry"). There is no `PositionCardData`/strategy object available here. This call site is intentionally left with `stop: 0, targets: []` (unchanged, pre-existing behavior) — Task 4's new signature must stay backward-compatible with this 4-arg call, not require a strategy object.
   - `frontend/lib/paperTrade.test.ts` (pre-existing, separate from the new test file this plan adds) calls `buildPaperStockPosition` with the current 4-arg shape. Task 4's signature change must not break it.
3. **`buildPaperStockPosition()` currently zeroes out `stop`/`targets`** (`frontend/lib/paperTrade.ts:35-36`) for every call site — even the ones that DO have `c.strategy.stop_price`/`c.strategy.target_price` right there in the candidate data. Without a fix, there's nothing for the new Monte Carlo call to target. Fixed in Task 4 — as an **optional** 5th parameter (not a required one), since the ChartWorkspace call site above has no strategy data to pass.
4. **Stock candidates have no per-component trend score** (unlike options' `stockBreakdown.trend`) — `PositionCardData` only exposes an aggregate `stock_score` (0-100). This plan uses `stock_score` as the drift-strength input to the stock Monte Carlo simulation (a documented approximation, not a new backend scoring change). This is weakest for the four mean-reversion strategies (`mean_reversion_rsi/bb/vwap/multi`), where a high aggregate score reflects "good entry into a counter-trend setup" rather than "strong continuation in the trade's own direction" the way a genuine trend sub-score would — the Monte Carlo drift formula's assumption ("higher score = stronger conviction the trade succeeds") is a reasonable, if imperfect, reading of that regardless of strategy family, but a follow-up that exposes a real per-strategy signal-strength metric (out of scope here — it would need backend scoring changes, not just plumbing) would be a meaningfully better input than `stock_score`.
5. **No `strike`/`right` field exists on `PortfolioPosition`** — only a display label (`contract: "AAPL 220C 05/16"`) and a real `expiry` (ISO date). Rather than parsing the label with regex (fragile — breaks on any label-format change), Task 3 adds `strike` into the already-generic `tradeCardSnapshotOf()` JSON blob, which already round-trips through the backend unchanged. `right` isn't needed: `is_call = direction === 'Bullish'` already covers it (see `contracts.py`'s existing `first_passage` endpoint).
6. **Portfolio positions already carry `currentStockPrice`, `delta`, `dteRemaining`** — all live-synced periodically by the existing portfolio sync. The EditDrawer's Monte Carlo button reuses these directly instead of firing its own fresh-quote fetch (unlike TradeCard's "Estimate" button, which fetches fresh quotes because it's working from a scan-time snapshot that could be stale — a portfolio position is already kept reasonably fresh by the sync).

---

## Task 1: Backend — stock-native Monte Carlo function

**Files:**
- Modify: `backend/app/scoring/first_passage.py`
- Test: `backend/tests/test_first_passage.py`

- [ ] **Step 1: Write the failing tests**

Modify the existing import at the top of `backend/tests/test_first_passage.py` to add the new name:

```python
from app.scoring.first_passage import (
    _vectorized_bs_price,
    _solve_target_stock_price,
    estimate_first_passage,
    estimate_stock_first_passage,
)
```

Add a new test class anywhere after the existing ones:

```python
class TestEstimateStockFirstPassage:
    def test_bullish_target_above_price_has_nonzero_probability_with_upward_drift(self):
        result = estimate_stock_first_passage(
            stock_price=100.0,
            is_bullish=True,
            signal_strength=80.0,   # strong bullish signal -> upward drift
            invalidation_price=90.0,
            target_price=110.0,
            horizon_days=30,
            candles=_FLAT_CANDLES,
            seed=42,
        )
        assert 0.0 < result.target.probability <= 1.0
        assert result.target.expected_days is not None
        assert result.mu > 0

    def test_bearish_high_signal_strength_drifts_downward(self):
        # signal_strength is already direction-relative (mirrors trend_score on the
        # option side, which is computed FOR the trade's own direction, not raw
        # market bullishness) — a HIGH score on a bearish trade means strong
        # confirmation of the bearish thesis, i.e. price expected to fall.
        # Verified against the real option-side test (test_first_passage.py's
        # test_mu_sign_flips_for_bearish): trend_score=100, is_call=False -> mu=-0.40.
        result = estimate_stock_first_passage(
            stock_price=100.0,
            is_bullish=False,
            signal_strength=100.0,
            invalidation_price=110.0,
            target_price=90.0,
            horizon_days=30,
            candles=_FLAT_CANDLES,
            seed=42,
        )
        assert result.mu < 0
        assert 0.0 <= result.target.probability <= 1.0

    def test_bearish_low_signal_strength_drifts_upward_against_the_trade(self):
        # A LOW score on a bearish trade means weak/no confirmation of the bearish
        # thesis — the drift formula correctly pushes AGAINST the trade (upward)
        # in that case, not toward it. Getting this backwards silently overstates
        # the target-hit probability shown to the user for a weak-signal trade.
        result = estimate_stock_first_passage(
            stock_price=100.0,
            is_bullish=False,
            signal_strength=0.0,
            invalidation_price=110.0,
            target_price=90.0,
            horizon_days=30,
            candles=_FLAT_CANDLES,
            seed=42,
        )
        assert result.mu > 0

    def test_zero_horizon_returns_zero_probability_without_crashing(self):
        result = estimate_stock_first_passage(
            stock_price=100.0,
            is_bullish=True,
            signal_strength=50.0,
            invalidation_price=90.0,
            target_price=110.0,
            horizon_days=0,
            candles=_FLAT_CANDLES,
            seed=42,
        )
        assert result.target.probability == 0.0
        assert result.target.expected_days is None
        assert result.invalidation.probability == 0.0

    def test_deterministic_for_same_seed(self):
        kwargs = dict(
            stock_price=100.0, is_bullish=True, signal_strength=65.0,
            invalidation_price=90.0, target_price=115.0, horizon_days=20,
            candles=_FLAT_CANDLES, seed=7,
        )
        r1 = estimate_stock_first_passage(**kwargs)
        r2 = estimate_stock_first_passage(**kwargs)
        assert r1.target.probability == r2.target.probability
        assert r1.invalidation.probability == r2.invalidation.probability

    def test_target_and_invalidation_probabilities_sane_for_far_barriers(self):
        # Target and stop both implausibly far away at a short horizon with low vol
        # (flat candles => near-zero ATR => sigma floors at sigma_floor): both should
        # rarely or never be hit.
        result = estimate_stock_first_passage(
            stock_price=100.0,
            is_bullish=True,
            signal_strength=50.0,
            invalidation_price=10.0,
            target_price=500.0,
            horizon_days=5,
            candles=_FLAT_CANDLES,
            seed=1,
        )
        assert result.target.probability < 0.05
        assert result.invalidation.probability < 0.05
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_first_passage.py::TestEstimateStockFirstPassage -v`
Expected: FAIL with `ImportError: cannot import name 'estimate_stock_first_passage'`

- [ ] **Step 3: Implement `estimate_stock_first_passage`**

Add to `backend/app/scoring/first_passage.py`, after the existing `FirstPassageResult` dataclass (around line 61, before `_vectorized_bs_price`):

```python
@dataclass
class StockFirstPassageResult:
    target:       InvalidationEstimate   # same shape as invalidation — a single absolute-price barrier
    invalidation: InvalidationEstimate
    sigma_stock:  float
    mu:           float
```

Add the function itself at the end of the file:

```python
def estimate_stock_first_passage(
    *,
    stock_price: float,
    is_bullish: bool,
    signal_strength: float,
    invalidation_price: float,
    target_price: float,
    horizon_days: int,
    candles: list[dict],
    max_drift_pct: float = 0.40,
    n_paths: int = 2000,
    sigma_floor: float = 0.10,
    sigma_ceiling: float = 1.50,
    seed: int = 0,
) -> StockFirstPassageResult:
    """Stock-native counterpart to estimate_first_passage: simulates the stock
    under GBM (same ATR-derived volatility and signal-strength-derived drift
    as the option version) and checks first-passage against two absolute
    stock-price barriers (target, stop) directly — no option repricing, no
    strike/premium/IV, because a stock position has none of those.

    `signal_strength` plays the same role `trend_score` plays for options: a
    0-100 signal-strength value that sets the drift's sign and magnitude via
    (signal_strength - 50) / 50 * max_drift_pct, direction-signed by
    is_bullish. Callers pass whatever 0-100 "how strong is this trade" number
    they have — the stock scanner's aggregate stock_score today, since stock
    candidates don't (yet) expose a standalone trend sub-score the way option
    candidates' stockBreakdown.trend does.

    `seed` makes this deterministic for a given set of inputs, same
    convention as estimate_first_passage — callers derive it from the
    request's own fields.
    """
    atr = _atr(candles, 14) if candles else 0.0
    sigma_stock = sigma_floor
    if stock_price > 0:
        sigma_stock = max(sigma_floor, min(sigma_ceiling, (atr / stock_price) * math.sqrt(252)))

    direction_sign = 1.0 if is_bullish else -1.0
    mu = direction_sign * (signal_strength - 50) / 50 * max_drift_pct

    if horizon_days < 1:
        zero = InvalidationEstimate(probability=0.0, expected_days=None)
        return StockFirstPassageResult(target=zero, invalidation=zero, sigma_stock=sigma_stock, mu=mu)

    rng = np.random.default_rng(seed)
    n_days = horizon_days
    dt = 1 / 365

    z = rng.standard_normal((n_paths, n_days))
    log_returns = (mu - 0.5 * sigma_stock ** 2) * dt + sigma_stock * math.sqrt(dt) * z
    log_paths = np.cumsum(log_returns, axis=1)
    stock_paths = stock_price * np.exp(log_paths)   # shape (n_paths, n_days)

    def _barrier_estimate(hit_mask: np.ndarray) -> InvalidationEstimate:
        ever_hit = hit_mask.any(axis=1)
        probability = float(ever_hit.mean())
        expected_days: Optional[float] = None
        if ever_hit.any():
            first_hit_day = np.argmax(hit_mask, axis=1)
            expected_days = float(np.median(first_hit_day[ever_hit]) + 1)
        return InvalidationEstimate(probability=probability, expected_days=expected_days)

    target_hit_mask = stock_paths >= target_price if is_bullish else stock_paths <= target_price
    stop_hit_mask = stock_paths <= invalidation_price if is_bullish else stock_paths >= invalidation_price

    return StockFirstPassageResult(
        target=_barrier_estimate(target_hit_mask),
        invalidation=_barrier_estimate(stop_hit_mask),
        sigma_stock=sigma_stock,
        mu=mu,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_first_passage.py::TestEstimateStockFirstPassage -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full first-passage test module to confirm no regression**

Run: `cd backend && pytest tests/test_first_passage.py -v`
Expected: PASS (all existing + 5 new tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scoring/first_passage.py backend/tests/test_first_passage.py
git commit -m "feat(scoring): add stock-native Monte Carlo first-passage estimator"
```

---

## Task 2: Backend — `/api/stocks/first-passage` endpoint

**Files:**
- Modify: `backend/app/routers/contracts.py`
- Test: `backend/tests/test_first_passage.py` (add a router-level test class)

- [ ] **Step 1: Write the failing test**

First check how the existing `/contracts/first-passage` endpoint is tested end-to-end (it may be tested elsewhere, e.g. `backend/tests/test_contracts_router.py` or similar) — search before writing a new harness:

Run: `cd backend && grep -rl "first_passage\b" tests/ --include=*.py`

Add a new test class to whichever file already exercises `contracts.py`'s router (mirror its FastAPI `TestClient` + `AsyncMock` patching setup for `fetch_candles_async`). If no such file exists, add this class to `backend/tests/test_first_passage.py`:

```python
class TestStockFirstPassageEndpoint:
    def _make_app(self):
        from app.routers.contracts import router
        app = FastAPI()
        app.include_router(router)
        return app

    def test_endpoint_returns_target_and_invalidation(self):
        app = self._make_app()
        with patch("app.routers.contracts.fetch_candles_async", new=AsyncMock(return_value=_FLAT_CANDLES)):
            client = TestClient(app)
            res = client.post("/api/stocks/first-passage", json={
                "symbol": "AAPL",
                "direction": "Bullish",
                "stock_price": 100.0,
                "target_price": 110.0,
                "invalidation_price": 90.0,
                "horizon_days": 20,
                "signal_strength": 70.0,
            })
        assert res.status_code == 200
        body = res.json()
        assert "target" in body and "probability" in body["target"]
        assert "invalidation" in body and "probability" in body["invalidation"]

    def test_identical_requests_return_identical_results(self):
        app = self._make_app()
        payload = {
            "symbol": "MSFT", "direction": "Bearish", "stock_price": 250.0,
            "target_price": 220.0, "invalidation_price": 265.0,
            "horizon_days": 15, "signal_strength": 30.0,
        }
        with patch("app.routers.contracts.fetch_candles_async", new=AsyncMock(return_value=_FLAT_CANDLES)):
            client = TestClient(app)
            r1 = client.post("/api/stocks/first-passage", json=payload).json()
            r2 = client.post("/api/stocks/first-passage", json=payload).json()
        assert r1 == r2

    def test_rejects_non_positive_stock_price(self):
        app = self._make_app()
        client = TestClient(app)
        res = client.post("/api/stocks/first-passage", json={
            "symbol": "AAPL", "direction": "Bullish", "stock_price": 0.0,
            "target_price": 110.0, "invalidation_price": 90.0,
            "horizon_days": 20, "signal_strength": 70.0,
        })
        assert res.status_code == 422
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_first_passage.py::TestStockFirstPassageEndpoint -v`
Expected: FAIL — 404 (route doesn't exist yet)

- [ ] **Step 3: Add the request/response models and endpoint**

Modify `backend/app/routers/contracts.py` — change the existing `first_passage` import (line 18) to add the new name:

```python
from app.scoring.first_passage import estimate_first_passage, estimate_stock_first_passage
```

Add the models and endpoint after the existing `first_passage` endpoint (after line 421, the closing of the existing function):

```python
class StockFirstPassageRequest(BaseModel):
    symbol:              str
    direction:           Literal["Bullish", "Bearish"]
    stock_price:         float = Field(..., gt=0)
    target_price:        float = Field(..., gt=0)
    invalidation_price:  float = Field(..., gt=0)
    horizon_days:        int = Field(..., ge=0, le=400)
    signal_strength:     float = Field(..., ge=0, le=100)


class StockFirstPassageResponse(BaseModel):
    target:       FirstPassageInvalidationOut
    invalidation: FirstPassageInvalidationOut


@router.post('/stocks/first-passage', response_model=StockFirstPassageResponse)
async def stock_first_passage(req: StockFirstPassageRequest) -> StockFirstPassageResponse:
    """On-demand Monte Carlo first-passage-time estimate for a STOCK position's
    target and stop: probability and expected days to hit each within
    horizon_days. Stock-native counterpart to first_passage() above — no
    option repricing, since a stock position has no strike/premium/IV.

    Fired only by the Portfolio EditDrawer's "Estimate" button for a stock
    position, never automatically.
    """
    fp_cfg = _fp_cfg()

    async with httpx.AsyncClient(timeout=8) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    seed_key = (
        f"{req.symbol.upper()}|{req.horizon_days}|{round(req.stock_price, 2)}|"
        f"{req.target_price}|{req.invalidation_price}|{req.signal_strength}"
    )
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    # Sourced from risk_rules.yaml's first_passage block, same as the option
    # endpoint above — without this, a future edit to that config would apply
    # to options and silently NOT apply to stocks.
    result = estimate_stock_first_passage(
        stock_price=req.stock_price,
        is_bullish=(req.direction == "Bullish"),
        signal_strength=req.signal_strength,
        invalidation_price=req.invalidation_price,
        target_price=req.target_price,
        horizon_days=req.horizon_days,
        candles=candles,
        max_drift_pct=fp_cfg["max_drift_pct"],
        n_paths=fp_cfg["n_paths"],
        sigma_floor=fp_cfg["sigma_floor"],
        sigma_ceiling=fp_cfg["sigma_ceiling"],
        seed=seed,
    )

    return StockFirstPassageResponse(
        target=FirstPassageInvalidationOut(
            probability=round(result.target.probability, 4),
            expectedDays=result.target.expected_days,
        ),
        invalidation=FirstPassageInvalidationOut(
            probability=round(result.invalidation.probability, 4),
            expectedDays=result.invalidation.expected_days,
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_first_passage.py::TestStockFirstPassageEndpoint -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full backend test suite for this area**

Run: `cd backend && pytest tests/test_first_passage.py -v`
Expected: PASS (all tests, options + stock)

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/contracts.py backend/tests/test_first_passage.py
git commit -m "feat(api): add POST /api/stocks/first-passage endpoint"
```

---

## Task 3: Frontend — `api.getStockFirstPassage()`

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add the client function**

Modify `frontend/lib/api.ts` — add immediately after the existing `getFirstPassageEstimate` entry (after line 380):

```ts
  /** Stock-native counterpart to getFirstPassageEstimate — no strike/premium/IV,
   *  target and invalidation are absolute stock prices. Fired only by the
   *  Portfolio EditDrawer's "Estimate" button for a stock position. */
  getStockFirstPassage: (req: {
    symbol: string;
    direction: 'Bullish' | 'Bearish';
    stock_price: number;
    target_price: number;
    invalidation_price: number;
    horizon_days: number;
    signal_strength: number;
  }, signal?: AbortSignal) =>
    post<{
      target: { probability: number; expectedDays: number | null };
      invalidation: { probability: number; expectedDays: number | null };
    }>('/api/stocks/first-passage', req, signal),
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors)

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(api): add getStockFirstPassage client function"
```

---

## Task 4: Frontend — extend buy-time snapshots with what the estimate needs

**Files:**
- Modify: `frontend/lib/paperTrade.ts`
- Modify: `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:57-68` (`tradeCardSnapshotOf`)
- Test: `frontend/lib/__tests__/paperTrade.test.ts` (new file)

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/paperTrade.test.ts`:

```ts
import { stockCardSnapshotOf, buildPaperStockPosition } from '@/lib/paperTrade';
import type { PositionCardData } from '@/types/stockDomain';

function makeCard(overrides: Partial<PositionCardData> = {}): PositionCardData {
  return {
    symbol: 'AAPL', company: 'Apple Inc.', price: 190, direction: 'Bullish',
    strategy: {
      strategy: 'pullback_ema', entry_price: 190, stop_price: 182,
      target_price: 205, rr_ratio: 1.9, atr: 3.2, detail: {},
    },
    backtest: {
      n_trades: 40, win_rate: 0.55, total_return_pct: 12, max_drawdown_pct: 8,
      expectancy: 0.4, sharpe: 1.1, confidence: 70, passes_gate: true, summary_text: 'ok',
    },
    stock_score: 78, stock_status: 'PASS', shares: 10, dollar_risk: 80, dollar_size: 1900,
    confidence: 70, confidence_text: 'Solid',
    ...overrides,
  };
}

describe('stockCardSnapshotOf', () => {
  it('includes the horizon and hold-day range passed in', () => {
    const snap = stockCardSnapshotOf(makeCard(), { horizon: 'Swing (5-15d)', holdMax: 15 });
    expect(snap.horizon).toBe('Swing (5-15d)');
    expect(snap.holdMax).toBe(15);
    expect(snap.stock_score).toBe(78);
  });
});

describe('buildPaperStockPosition', () => {
  it('populates stop and a single target when a strategy signal is passed', () => {
    const card = makeCard();
    const pos = buildPaperStockPosition(card.symbol, card.strategy.entry_price, 10, 'Bullish', card.strategy,
      stockCardSnapshotOf(card, { horizon: 'Swing (5-15d)', holdMax: 15 }));
    expect(pos.stop).toBe(182);
    expect(pos.targets).toHaveLength(1);
    expect(pos.targets[0]!.stockPrice).toBe(205);
    expect(pos.targets[0]!.targetPrice).toBe(205);
  });

  it('stays backward-compatible with a 4-arg call that has no strategy data (chart-click buy)', () => {
    const pos = buildPaperStockPosition('AAPL', 150, 10, 'Bullish');
    expect(pos.stop).toBe(0);
    expect(pos.targets).toEqual([]);
  });
});
```

- [ ] **Step 1b: Confirm the pre-existing `paperTrade.test.ts` still passes unmodified**

`frontend/lib/paperTrade.test.ts` (a separate, pre-existing file from the new `frontend/lib/__tests__/paperTrade.test.ts` above) calls `buildPaperStockPosition('AAPL', 150, 10, 'Bullish')` / `('TSLA', 250, 5, 'Bearish')` with the current 4-arg shape and asserts on `symbol`/`contract`/`entryPrice`/`contracts`/`direction` only — none of the fields this plan changes. It does not need to be modified, but re-run it in Step 5 below to confirm.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=paperTrade`
Expected: FAIL — `stockCardSnapshotOf` doesn't accept a second argument yet; `buildPaperStockPosition`'s signature doesn't match; `pos.stop`/`pos.targets` are `0`/`[]`.

- [ ] **Step 3: Implement**

Replace the full contents of `frontend/lib/paperTrade.ts`:

```ts
import type { Direction, PortfolioPosition, TargetLevel } from '@/types/domain';
import type { PositionCardData } from '@/types/stockDomain';

// The "why was this bought" snapshot for the stocks path — attached once at
// buy time so it survives independent of later scans overwriting scanStore.
// `horizon`/`holdMax` come from the caller (scanStore.context at the moment
// of the buy, not from the candidate itself — a stock scan's horizon is a
// scan-level choice, not per-candidate) because the Monte Carlo estimate on
// the Portfolio EditDrawer needs a day-count to simulate forward and stock
// candidates carry no expiry to derive one from, unlike options' dte.
// `stock_score` doubles as the drift-strength input to that same estimate —
// stock candidates have no standalone trend sub-score the way options'
// stockBreakdown.trend does, so the aggregate score stands in for it.
export function stockCardSnapshotOf(
  c: PositionCardData,
  horizonCtx: { horizon: string; holdMax: number },
): Record<string, unknown> {
  return {
    stock_score: c.stock_score,
    stock_status: c.stock_status,
    strategy: c.strategy,
    backtest: c.backtest,
    confidence: c.confidence,
    confidence_text: c.confidence_text,
    sector_rs_pct: c.sector_rs_pct,
    fundamentals: c.fundamentals,
    horizon: horizonCtx.horizon,
    holdMax: horizonCtx.holdMax,
  };
}

// `strategy` is OPTIONAL and appended, not inserted — buildPaperStockPosition
// has one call site (ChartWorkspace's chart-click buy popover) with no
// PositionCardData available at all, so a required strategy/card parameter
// would be a breaking change with nothing to satisfy it. When omitted, stop/
// targets fall back to their pre-existing zero/empty values (unchanged
// behavior for that call site).
export function buildPaperStockPosition(
  symbol: string,
  price: number,
  shares: number,
  direction: Direction,
  strategy?: Pick<StrategySignalData, 'stop_price' | 'target_price'>,
  snapshot?: Record<string, unknown>,
): PortfolioPosition {
  const today = new Date().toISOString().slice(0, 10);
  const targets: TargetLevel[] = strategy
    ? [{ id: 't1', stockPrice: strategy.target_price, targetPrice: strategy.target_price, status: 'PENDING' }]
    : [];
  return {
    symbol,
    contract:     `${symbol}|STOCK`,
    direction,
    entryPrice:   price,
    contracts:    shares,
    entryDate:    today,
    expiry:       '',
    stop:         strategy?.stop_price ?? 0,
    targets,
    dteTotal:     0,
    dteRemaining: 0,
    status:       'PENDING',
    recId:        'PAPER-' + Date.now().toString(36),
    currentPrice: price,
    pnlDollar:    0,
    pnlPct:       0,
    source:       'paper',
    tradeCardSnapshot: snapshot,
  };
}
```

Also update the `paperTrade.ts` import line at the top of the file to include `StrategySignalData`:

```ts
import type { Direction, PortfolioPosition, TargetLevel } from '@/types/domain';
import type { PositionCardData, StrategySignalData } from '@/types/stockDomain';
```

- [ ] **Step 4: Update `stockCardSnapshotOf`/`buildPaperStockPosition` call sites for the new signatures**

The scan-context horizon read (`useScanStore((s) => ({ horizon: s.context?.horizon ?? '', holdMax: s.context?.holdMax ?? 15 }))`) is needed at three call sites in this task (`StockSendDialog`, `StockPositionCard`) and two more in Task 5 (`step-4-stocks`, `step-7-position-card`). Verify `useScanStore`'s state shape has a top-level `context: ScanContext` field with `horizon: string` and `holdMax: number` (per `frontend/lib/scanStore.ts`'s `ScanContext` interface) before using this snippet anywhere — do not assume the field name without checking, since a wrong field name here fails silently (optional chaining just returns the fallback) rather than with a compile error.

Modify `frontend/components/organisms/StockSendDialog/index.tsx` — add the `useScanStore` import near the top (after the existing imports, line 11):

```ts
import { useScanStore } from '@/lib/scanStore';
```

Add a hook read inside `StockSendDialog` (right after the existing `addPosition`/`ibkrPaper`/`tradierPaper` hooks, around line 46-48):

```ts
  const scanHorizon = useScanStore((s) => ({ horizon: s.context?.horizon ?? '', holdMax: s.context?.holdMax ?? 15 }));
```

Update both `buildPaperStockPosition` call sites (lines 106 and 129) to match the new signature:

```ts
        const res = await addPosition(
          buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction, c.strategy, stockCardSnapshotOf(c, scanHorizon)),
        );
```

(Same replacement text for both occurrences — the manual branch at line ~106 and the auto-send-falls-back-to-recommendation branch at line ~129.)

Modify `frontend/components/organisms/StockPositionCard/index.tsx` — `useScanStore` is ALREADY imported here (it's already used 3 times for `stockBasket`/`addToStockBasket`/`removeFromStockBasket`) — do not add a second import, or `npm run typecheck` fails with "Duplicate identifier 'useScanStore'" (TS2300). Just add the new hook read alongside the component's existing `useScanStore` calls:

```ts
  const scanHorizon = useScanStore((s) => ({ horizon: s.context?.horizon ?? '', holdMax: s.context?.holdMax ?? 15 }));
```

Then update the single call site at line 212. Use `overlay.stop`/`overlay.t1` here, NOT `card.strategy.stop_price`/`target_price` — unlike every other call site in this plan, `StockPositionCard` lets the user edit stop/target via the `EditableField` inputs above (Section 1/2 of the JSX) before clicking "Add to Portfolio," and `overlay.entry`/`overlay.shares` (already used in this exact call) are that same user-edited state, not the original scan values:

```ts
      const res = await addPosition(
        buildPaperStockPosition(card.symbol, overlay.entry, overlay.shares, card.direction as Direction, { stop_price: overlay.stop, target_price: overlay.t1 }, stockCardSnapshotOf(card, scanHorizon)),
      );
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=paperTrade`
Expected: PASS (both `frontend/lib/__tests__/paperTrade.test.ts` and the pre-existing `frontend/lib/paperTrade.test.ts`)

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

Run: `grep -rn "buildPaperStockPosition\|stockCardSnapshotOf" frontend --include=*.tsx --include=*.ts`
Confirm every call site found is one of: `paperTrade.ts` (the definitions), `StockSendDialog/index.tsx` / `StockPositionCard/index.tsx` (updated above), a test file, or one of `step-4-stocks/page.tsx` / `ChartWorkspace/index.tsx` / `step-7-position-card/page.tsx` — the first two are handled in Task 5, the third gets `buildPaperStockPosition` introduced fresh in Task 5 (it currently doesn't call it at all). `ChartWorkspace/index.tsx`'s 4-arg call is intentionally left untouched (see the investigation summary) — confirm it still typechecks as-is, don't add arguments to it.

- [ ] **Step 7: Extend `tradeCardSnapshotOf` (options) with `strike`**

Modify `frontend/app/(frame)/screener/step-7-trade-card/page.tsx:57-68`:

```ts
function tradeCardSnapshotOf(card: TradeCardData): Record<string, unknown> {
  return {
    stockScore: card.stockScore,
    stockConfidence: card.stockConfidence,
    stockBreakdown: card.stockBreakdown,
    contractScore: card.contractScore,
    contractConfidence: card.contractConfidence,
    contractBreakdown: card.contractBreakdown,
    rrRatio: card.rrRatio,
    rrModel: card.rrModel,
    strike: card.contractDetails?.strike ?? null,
  };
}
```

- [ ] **Step 8: Typecheck again**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 9: Commit**

```bash
git add frontend/lib/paperTrade.ts frontend/lib/__tests__/paperTrade.test.ts frontend/components/organisms/StockSendDialog/index.tsx "frontend/app/(frame)/screener/step-7-trade-card/page.tsx"
git commit -m "feat(portfolio): extend buy-time snapshots with horizon/strike for Monte Carlo"
```

---

## Task 5: Frontend — capture the snapshot on EVERY stock buy path, not just manual

**Files:**
- Modify: `frontend/components/organisms/StockSendDialog/index.tsx`
- Modify: `frontend/components/organisms/StockPositionCard/index.tsx`
- Modify: `frontend/app/(frame)/screener/step-7-position-card/page.tsx`
- Modify: `frontend/app/(frame)/screener/step-4-stocks/page.tsx`
- Test: `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx`

**Design note on the retry-safety invariant:** `StockSendDialog.submit()` deliberately retries only `cards.filter(c => c.symbol in errors)` on a re-click, specifically to avoid double-placing a broker order (see the function's own comment, lines 84-99). That means a broker order that has ALREADY succeeded must never end up back in `errs` on this pass — if it did, a retry click would call `api.postStockOrder` a second time for an order that already filled. So below, once `api.postStockOrder` resolves successfully, a failure to also mirror it into the local portfolio (`addPosition`) is tracked as a separate non-blocking `warn` bucket, never added to `errs`/`q` (which are what actually mark a symbol as "not yet fully placed" for the retry logic and the "stay open" gate).

- [ ] **Step 1: Read the existing auto-send test to match its mocking style**

Run: `cd frontend && sed -n '1,60p' components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx`

(Confirms how `api.postStockOrder` and `usePortfolioStore` are currently mocked in that file — match that style exactly in the new test below rather than inventing a different mock shape.)

- [ ] **Step 2: Write the failing tests**

Add to `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx` (append at the END of the existing `describe` block — not interspersed among the earlier tests — so a leftover mocked `addPosition` from these two tests can't leak into an earlier test that relies on the real store's queued/pending behavior; also add `usePortfolioStore.setState({ addPosition: <the real implementation> })` — or simply re-import and restore it — in an `afterEach` at the top of this new block if the file's existing `beforeEach` doesn't already reset the whole store, since `beforeEach` in this file only resets `{ positions: [] }`, not `addPosition` itself). The file's real helper is `function makeCard(symbol: string): PositionCardData` — it takes a REQUIRED symbol argument (confirm by reading the file first); do not call it with zero arguments, which is a different helper local to `StockSendDialog.pending.test.tsx` and would fail `npm run typecheck` (TS2554) in this file:

```ts
  it('creates a local position with a snapshot after a successful auto-send broker order', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-1', status: 'filled', broker: 'tradier_paper' });
    const addPosition = jest.fn().mockResolvedValue({ status: 'ok' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('Tradier Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));

    await waitFor(() => expect(addPosition).toHaveBeenCalled());
    const created = addPosition.mock.calls[0][0];
    expect(created.source).toBe('broker');
    expect(created.tradeCardSnapshot).toBeDefined();
    expect(created.tradeCardSnapshot.strategy.strategy).toBe('pullback_ema');
  });

  it('does NOT re-submit the broker order on retry when the order succeeded but local tracking failed', async () => {
    (api.postStockOrder as jest.Mock).mockResolvedValueOnce({ order_id: 'ORD-2', status: 'filled', broker: 'tradier_paper' });
    const addPosition = jest.fn().mockResolvedValueOnce({ status: 'rejected', detail: 'exposure limit' });
    usePortfolioStore.setState({ addPosition } as any);

    render(<StockSendDialog cards={[makeCard('AAPL')]} onClose={jest.fn()} onSubmit={jest.fn()} />);
    fireEvent.click(screen.getByText('Tradier Paper'));
    fireEvent.click(screen.getByText(/Submit 1 order/));
    await waitFor(() => expect(api.postStockOrder).toHaveBeenCalledTimes(1));

    // A local-tracking failure must not put the symbol back in the retryable
    // error set. Unlike a genuine `errs` failure (which relabels the button
    // "Retry N failed order(s)"), a warn-only outcome leaves the button
    // showing its ORIGINAL "Submit 1 order" label — `errors`/`queued` are
    // both still empty, only `warnings` is set — and it stays clickable. So
    // the real regression check is: click that same button again and confirm
    // it does NOT re-fire the broker order (the retry-target-selection logic
    // filters on `errors`, which this symbol was never added to).
    fireEvent.click(await screen.findByText(/Submit 1 order/));
    await new Promise((r) => setTimeout(r, 0));
    expect(api.postStockOrder).toHaveBeenCalledTimes(1);

    // The failure must still be VISIBLE to the user — silently swallowing it
    // (computing `warn` and never rendering it) would mean a real broker
    // order succeeds with zero local record and zero indication anything
    // needs attention.
    expect(await screen.findByText(/not yet tracked in Portfolio/)).toBeInTheDocument();
  });
```

(Reuse whatever `makeCard()` helper the existing test file already defines — do not redefine it if one exists.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npm run test -- --testPathPattern=StockSendDialog`
Expected: FAIL — `addPosition` never called on the auto-send path (first test); second test may pass vacuously today since there's no retry path for this branch yet — re-check it after Step 4's fix, not just before.

- [ ] **Step 4: Fix the auto-send branch in `StockSendDialog`**

Add a `warn` bucket alongside the existing `errs`/`q` locals inside `submit()` (right after the existing `const q: Record<string, string> = ...` line, around line 100):

```ts
    const warn: Record<string, string> = hasSubmittedOnce ? { ...warnings } : {};
```

This requires a `warnings` state (mirrors the existing `queued` state's pattern) — add it near the other `useState` declarations at the top of `StockSendDialog` (after `const [queued, setQueued] = useState<Record<string, string>>({});`):

```ts
  const [warnings, setWarnings] = useState<Record<string, string>>({});
```

Modify `frontend/components/organisms/StockSendDialog/index.tsx`'s `submit()` — replace the `else if (broker !== 'recommendation')` branch (around lines 110-125):

```ts
      } else if (broker !== 'recommendation') {
        // Auto-send → broker, then mirror the fill into the local portfolio
        // (same pattern as options' step-7-trade-card placeLimitPaper/
        // placeMarketNow) so this position carries a tradeCardSnapshot and
        // real stop/target too — without this, a broker-executed stock
        // position has no local record at all and the EditDrawer's Monte
        // Carlo estimate has nothing to work from.
        try {
          const res = await api.postStockOrder({
            broker,
            symbol: c.symbol,
            action: c.direction === 'Bullish' ? 'BUY' : 'SELL',
            effect: 'OPEN',
            quantity: r.shares,
            order_type: 'LMT',
            limit_price: c.strategy.entry_price,
            tif: 'DAY',
          });
          // The broker order has ALREADY succeeded at this point — a failure
          // below must never be written to `errs`/`q` (those drive the retry
          // set; retrying here would resubmit an already-filled order). It's
          // tracked in `warn` instead, purely informational.
          try {
            const pos = buildPaperStockPosition(c.symbol, c.strategy.entry_price, r.shares, c.direction as Direction, c.strategy, stockCardSnapshotOf(c, scanHorizon));
            const addRes = await addPosition({ ...pos, source: 'broker', sourceLabel: `${broker} — Limit (ID: ${res.order_id})`, orderedAt: new Date().toISOString() });
            if (addRes.status === 'rejected' || addRes.status === 'pending') {
              warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
            }
          } catch {
            warn[c.symbol] = 'Order placed but not yet tracked in Portfolio — check there directly.';
          }
        } catch (e) {
          errs[c.symbol] = String(e);
        }
      } else {
```

Update the end of `submit()` to persist `warn` into the `warnings` state (find the existing `setSubmitting(false); setErrors(errs); setQueued(q);` block and add):

```ts
    setSubmitting(false);
    setErrors(errs);
    setQueued(q);
    setWarnings(warn);
```

**The "stay open" gate MUST also include `warn`, or the warning is computed and then never seen.** The real `submit()` calls `onSubmit(orders)` immediately after this gate when it's false, and the only real caller — `frontend/app/(frame)/screener/step-4-stocks/page.tsx`'s `onSubmit={(_orders) => { setShowSendDialog(false); }}` — unmounts the dialog in that same render pass. A `warn`-only symbol is never in `errors`/`queued`, so without this change the gate is false, the dialog closes immediately, and the warning text (set via `setWarnings` a few lines above) is never painted to the screen even once — the exact silent-swallow failure this whole mechanism exists to prevent. Change the gate (previously `if (Object.keys(errs).length > 0 || Object.keys(q).length > 0) return;`) to:

```ts
    if (Object.keys(errs).length > 0 || Object.keys(q).length > 0 || Object.keys(warn).length > 0) return;
```

This does NOT reintroduce the double-order hazard: the retry-target-selection line (`hasSubmittedOnce ? cards.filter(c => c.symbol in errors) : cards`) still keys off `errors` alone, so a `warn`-only symbol is excluded from `targets` on any later submit click regardless of whether the dialog stayed open — clicking "Submit" again with only a warning pending processes zero cards and immediately hits this same gate again. The user dismisses the dialog via the existing Cancel/× button (`onClose`, unaffected by this gate) once they've read the warning — same UX as a `queued` row today, which also just leaves the dialog open until the user closes it or a background resync clears it.

**This `warnings` state must actually be shown to the user** — computing it and never rendering it means a real broker order can succeed with zero local record and zero visible indication anything needs attention (the dialog closes normally via `onSubmit`, reporting the whole basket as cleanly placed). Add a warning display in the table body, mirroring the existing `hasErr`/`isQueued` pattern — find this block in the row rendering (inside the `cards.map((c) => { ... })` body):

```tsx
                {hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="reject">{errors[c.symbol]}</Text>
                  </span>
                )}
                {isQueued && !hasErr && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{queued[c.symbol]}</Text>
                  </span>
                )}
```

and add a third branch immediately after it:

```tsx
                {warnings[c.symbol] && !hasErr && !isQueued && (
                  <span className={styles.errCell}>
                    <Text size={11} tone="caution">{warnings[c.symbol]}</Text>
                  </span>
                )}
```

No new local is needed — `warnings[c.symbol]` is referenced directly, same as `queued[c.symbol]` is in the existing `isQueued` branch above it.

- [ ] **Step 4b: Fix the pre-existing `"only resubmits symbols that failed on the previous attempt"` test, which this change breaks**

Read `frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx:51-92` first — this pre-existing test selects `IBKR Paper` (auto-send) for all 3 cards and mocks only `api.postStockOrder`, not `addPosition`. Before Step 4's fix, the auto-send branch never called `addPosition`, so this didn't matter. After Step 4's fix, every successful `postStockOrder` now also calls the REAL (unmocked) `usePortfolioStore.addPosition`, which hits a real `fetch` this test never mocks — in the `npm run test` environment (no backend running), that `fetch` fails, `addPosition` resolves `status: 'pending'`, and Step 4's new code treats `'pending'` as warn-worthy (`warn[c.symbol] = '...'`). With NO code in this test ever clearing `warnings`, all three symbols end up permanently in `warn` after the retry succeeds — the "stay open" gate (now `errs.length>0 || q.length>0 || warn.length>0`) stays true forever, `onSubmit` is never called, and this test's `await waitFor(() => expect(onSubmit).toHaveBeenCalled())` times out and fails. This is a real regression this plan's change causes in an unrelated, currently-passing test — not optional cleanup.

Fix it by making `addPosition` succeed in this test, the same way the OTHER pre-existing test in this file ("does not permanently disable Submit...") already deliberately controls `fetch`/`addPosition` behavior for its own scenario — but note that test ALSO explicitly restores what it overrides afterward (`global.fetch = originalFetch;`, line 151). `usePortfolioStore` is a module-level Zustand singleton shared across every `it()` in this file — a `setState` override with no matching restore leaks into every test that runs after it, which would break the "does not permanently disable Submit..." test two tests later (it relies on the REAL `addPosition` hitting its own mocked-to-reject `global.fetch` to produce a `'pending'` status and the "queued" UI text it asserts on). Capture and restore the real implementation at the `describe` level, once, rather than inline in a single test with no cleanup:

Add near the top of the `describe('StockSendDialog — partial basket failure retry', ...)` block (right after its opening brace, before the existing `beforeEach`):

```ts
  const realAddPosition = usePortfolioStore.getState().addPosition;

  afterEach(() => {
    usePortfolioStore.setState({ addPosition: realAddPosition });
  });
```

Then add the override at the top of the `it('only resubmits symbols that failed on the previous attempt', ...)` test body, before `render(...)`:

```ts
    usePortfolioStore.setState({ addPosition: jest.fn().mockResolvedValue({ ok: true, status: 'ok' as const }) });
```

The `afterEach` above restores the real `addPosition` after THIS test (and is a harmless no-op after every other test, which never touches it) — so the "does not permanently disable Submit..." test still exercises the real `addPosition` → real (mocked-to-reject) `fetch` → `'pending'` path it depends on. This makes every successful broker order's follow-up `addPosition` call resolve cleanly (`status: 'ok'`) within the "only resubmits" test specifically, so no `warn` entry is ever set for AAPL/NVDA/MSFT there, and the gate behaves exactly as it did before Step 4's change for that test's purposes — it's verifying retry-target-selection (`errors`-only filtering), not the new local-tracking behavior, so stubbing `addPosition` to succeed keeps it testing what it was always testing.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=StockSendDialog`
Expected: PASS (all tests in the file, including `.test.tsx` and `.pending.test.tsx`)

- [ ] **Step 6: Fix `step-7-position-card/page.tsx` the same way**

Modify `frontend/app/(frame)/screener/step-7-position-card/page.tsx` — `useScanStore` is ALREADY imported here (line 7) — do not add it again, or `npm run typecheck` fails with "Duplicate identifier 'useScanStore'" (TS2300). Add only the two genuinely-missing imports (after line 9):

```ts
import { usePortfolioStore } from '@/lib/portfolioStore';
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
```

Add a hook read and a new `warning` state inside `Step7PositionCardPage` (near the other hooks, around line 45 — `warning` sits alongside the existing `error` state):

```ts
  const addPosition = usePortfolioStore((s) => s.addPosition);
  const scanHorizon = useScanStore((s) => ({ horizon: s.context?.horizon ?? '', holdMax: s.context?.holdMax ?? 15 }));
  const [warning, setWarning] = useState<string | null>(null);
```

Replace the `submit()` function (lines 85-106). Unlike this plan's original draft claimed, this page DOES have the same duplicate-order hazard `StockSendDialog` was fixed for in Step 4: nothing here disables "Place Limit Order"/"Right Now — Market Order" after a *successful* placement — only `placingType !== null` (which resets in `finally` regardless of outcome) gates them today. A failed local `addPosition` mirror must therefore (a) never be shown via the `error` state, which a user would reasonably read as "the order failed, try again" and re-click, firing a second broker order for an order that already filled, and (b) the buttons must be explicitly disabled once an order has been placed, not just while one is in flight:

```ts
  async function submit(orderType: 'LMT' | 'MKT') {
    if (!card || execMode === 'recommendation' || orderId !== null) return;
    setPlacingType(orderType);
    setError(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: card.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? card.strategy.entry_price : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
      try {
        const pos = buildPaperStockPosition(card.symbol, card.strategy.entry_price, card.shares, card.direction as 'Bullish' | 'Bearish', card.strategy, stockCardSnapshotOf(card, scanHorizon));
        const addRes = await addPosition({ ...pos, source: 'broker', sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`, orderedAt: new Date().toISOString() });
        if (addRes.status === 'rejected' || addRes.status === 'pending') {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setPlacingType(null);
    }
  }
```

Add `orderId !== null` to both order buttons' `disabled` props (they currently read `disabled={placingType !== null}` — around lines 178 and 182 of the original file) so neither can fire again once an order has actually been placed:

```tsx
          <button type="button" className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={() => submit('LMT')} disabled={placingType !== null || orderId !== null}>
            {placingType === 'LMT' ? 'Placing…' : `Place Limit Order @ $${card.strategy.entry_price}`}
          </button>
          <button type="button" className={`${styles.btn} ${styles.btnMarket}`}
            onClick={() => submit('MKT')} disabled={placingType !== null || orderId !== null}>
            {placingType === 'MKT' ? 'Placing…' : 'Right Now — Market Order'}
          </button>
```

Add a `warning` display alongside the existing `orderId`/`error` display at the bottom of the component (near `{orderId && ...}` / `{error && ...}`):

```tsx
      {warning && <Text size={12} tone="caution">{warning}</Text>}
```

(These buttons already reset via the candidate-nav `onClick={() => { setSelectedIdx(i); setOrderId(null); setError(null); }}` — add `setWarning(null);` there too so switching candidates clears a stale warning.)

- [ ] **Step 7: Fix `StockPositionCard/index.tsx`'s OWN `submit()` the same way**

This is a DIFFERENT function from `onAddToPortfolio` (updated in Task 4) in the SAME file — `submit()` (lines 183-204, wired to the "Section 5 — Order buttons" JSX) places a real broker order and has never called `addPosition` at all. `useScanStore` is ALREADY imported and used 3 times in this file (lines 5, 153-155). **`scanHorizon` is ALSO already declared** — Task 4 Step 4 (above, earlier in this same plan) added `const scanHorizon = useScanStore((s) => ({ horizon: ..., holdMax: ... }));` to this exact component for `onAddToPortfolio`'s call. Do NOT declare it again here — `submit()` below reuses that same `scanHorizon` binding. Only add the new `warning` state, alongside the component's other hooks (near line 156-168):

```ts
  const [warning, setWarning] = useState<string | null>(null);
```

Replace `submit()` (lines 183-204). Same duplicate-order reasoning as `step-7-position-card` above: nothing here disables the order buttons after a *successful* placement (only `placingType !== null`, which resets in `finally`), so a local-tracking failure must go through `warning`, never `err` (which the existing JSX at line 417 already renders with `tone="reject"` — the same tone a genuine order failure uses, so reusing it here would read as "this failed, try again"):

```ts
  async function submit(orderType: 'LMT' | 'MKT') {
    if (execMode === 'recommendation' || orderId !== null) return;
    setPlacingType(orderType);
    setErr(null);
    setWarning(null);
    try {
      const res = await api.postStockOrder({
        broker: execMode,
        symbol: card.symbol,
        action: card.direction === 'Bullish' ? 'BUY' : 'SELL',
        effect: 'OPEN',
        quantity: overlay.shares,
        order_type: orderType,
        limit_price: orderType === 'LMT' ? overlay.entry : null,
        tif: 'DAY',
      });
      setOrderId(res.order_id);
      try {
        const pos = buildPaperStockPosition(card.symbol, overlay.entry, overlay.shares, card.direction as Direction, { stop_price: overlay.stop, target_price: overlay.t1 }, stockCardSnapshotOf(card, scanHorizon));
        const addRes = await addPosition({ ...pos, source: 'broker', sourceLabel: `${execMode} — ${orderType} (ID: ${res.order_id})`, orderedAt: new Date().toISOString() });
        if (addRes.status === 'rejected' || addRes.status === 'pending') {
          setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
        }
      } catch {
        setWarning('Order placed but not yet tracked in Portfolio — check there directly.');
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setPlacingType(null);
    }
  }
```

Add `orderId !== null` to both order buttons' `disabled` props (lines 400 and 408):

```tsx
            disabled={placingType !== null || orderId !== null}
```

(same replacement for both buttons)

Add a `warning` display next to the existing `orderId`/`err`/`queued` display (Section 6, around line 416-418):

```tsx
      {warning && <Text size={12} tone="caution">{warning}</Text>}
```

Add `setWarning(null);` to the existing `card.symbol`-change cleanup effect (lines 131-139), alongside its other resets.

- [ ] **Step 8: Fix `step-4-stocks/page.tsx`'s after-scan auto-execute loop the same way**

Modify `frontend/app/(frame)/screener/step-4-stocks/page.tsx` — add the `stockCardSnapshotOf` import alongside the existing `buildPaperStockPosition` import (line 21):

```ts
import { buildPaperStockPosition, stockCardSnapshotOf } from '@/lib/paperTrade';
```

This page already reads `const context = useScanStore((s) => s.context);` (line 82) — confirms `context` is the real field name referenced elsewhere in this plan. Reuse it directly rather than adding a new selector; update the call at line 184 (inside `onRun`'s after-scan auto-execute loop):

```ts
        const addRes = await addPosition(buildPaperStockPosition(c.symbol, c.strategy.entry_price, c.shares, c.direction as Direction, c.strategy, stockCardSnapshotOf(c, { horizon: context?.horizon ?? '', holdMax: context?.holdMax ?? 15 })));
```

- [ ] **Step 9: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 10: Commit**

```bash
git add frontend/components/organisms/StockSendDialog/index.tsx frontend/components/organisms/StockSendDialog/__tests__/StockSendDialog.test.tsx frontend/components/organisms/StockPositionCard/index.tsx "frontend/app/(frame)/screener/step-7-position-card/page.tsx" "frontend/app/(frame)/screener/step-4-stocks/page.tsx"
git commit -m "fix(portfolio): capture buy-time snapshot on every stock buy path, not just manual"
```

---

## Task 6: Frontend — Monte Carlo "Estimate" section in the Portfolio EditDrawer

**Files:**
- Modify: `frontend/app/(frame)/portfolio/page.tsx`
- Modify: `frontend/app/(frame)/portfolio/page.module.css`
- Test: `frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx` (new file)

- [ ] **Step 1: Export `EditDrawer` so it's testable in isolation**

Modify `frontend/app/(frame)/portfolio/page.tsx:461` — change `function EditDrawer({` to `export function EditDrawer({`.

- [ ] **Step 2: Write the failing tests**

Create `frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditDrawer } from '../page';
import { api } from '@/lib/api';
import type { PortfolioPosition } from '@/types/domain';

jest.mock('@/lib/api', () => ({
  api: {
    getFirstPassageEstimate: jest.fn(),
    getStockFirstPassage: jest.fn(),
  },
}));

function makeStockPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL|STOCK', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '', dteRemaining: 0, dteTotal: 0,
    entryPrice: 190, currentPrice: 195, pnlDollar: 50, pnlPct: 2.6,
    stop: 182, targets: [{ id: 't1', stockPrice: 205, targetPrice: 205, status: 'PENDING' }],
    status: 'PASS', contracts: 10, recId: 'REC-1',
    tradeCardSnapshot: { stock_score: 78, horizon: 'Swing (5-15d)', holdMax: 15 },
    ...overrides,
  };
}

function makeOptionPosition(overrides: Partial<PortfolioPosition> = {}): PortfolioPosition {
  return {
    symbol: 'AAPL', contract: 'AAPL 220C 05/16', direction: 'Bullish',
    entryDate: '2026-08-01', expiry: '2026-09-16', dteRemaining: 20, dteTotal: 30,
    entryPrice: 4.2, currentPrice: 4.5, currentStockPrice: 195,
    pnlDollar: 30, pnlPct: 7.1, stop: 3.0, targets: [], status: 'PASS',
    delta: 0.5, contracts: 2, recId: 'REC-2',
    tradeCardSnapshot: { strike: 220, stockBreakdown: { trend: 72 } },
    ...overrides,
  };
}

describe('EditDrawer Monte Carlo estimate', () => {
  const noop = () => {};

  it('calls getStockFirstPassage with target/stop prices for a stock position', async () => {
    (api.getStockFirstPassage as jest.Mock).mockResolvedValueOnce({
      target: { probability: 0.6, expectedDays: 12 },
      invalidation: { probability: 0.1, expectedDays: null },
    });
    render(<EditDrawer position={makeStockPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getStockFirstPassage).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', stock_price: 195,
      target_price: 205, invalidation_price: 182, signal_strength: 78,
    })));
    expect(await screen.findByText('60%')).toBeInTheDocument();
  });

  it('calls getFirstPassageEstimate with strike/trend from the snapshot and the settings-store target percents for an option position', async () => {
    (api.getFirstPassageEstimate as jest.Mock).mockResolvedValueOnce({
      targets: [
        { pct: 0.2, stockPrice: 215, optionPrice: 5.4, probability: 0.6, expectedDays: 5 },
        { pct: 0.5, stockPrice: 230, optionPrice: 6.75, probability: 0.4, expectedDays: 10 },
        { pct: 1.0, stockPrice: 250, optionPrice: 9.0, probability: 0.35, expectedDays: 18 },
      ],
      // Deliberately distinct from every target probability above (0.6/0.4/0.35) —
      // this and the stock test's own '60%' assertion are in separate renders/
      // describe blocks (RTL's render() mounts fresh each time and screen queries
      // the current document body), so no cross-test collision; the risk this
      // guards against is a same-render duplicate (T3 vs STOP HIT), not cross-test.
      invalidation: { probability: 0.10, expectedDays: null },
    });
    render(<EditDrawer position={makeOptionPosition()} onClose={noop} onChange={noop} onRemove={noop} />);
    fireEvent.click(screen.getByText('Estimate'));
    await waitFor(() => expect(api.getFirstPassageEstimate).toHaveBeenCalledWith(expect.objectContaining({
      symbol: 'AAPL', direction: 'Bullish', stock_price: 195, strike: 220,
      dte: 20, premium: 4.5, delta: 0.5, trend_score: 72, invalidation_price: 3.0,
      t1_pct: expect.any(Number), t2_pct: expect.any(Number), t3_pct: expect.any(Number),
    })));
    // All three targets are rendered, not just the first — the drawer must not
    // silently discard T2/T3 the way an earlier draft of this feature did.
    expect(await screen.findByText('60%')).toBeInTheDocument();
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(await screen.findByText('35%')).toBeInTheDocument();
    expect(await screen.findByText('10%')).toBeInTheDocument();
  });

  it('disables Estimate for a stock position with no target captured yet', () => {
    render(<EditDrawer position={makeStockPosition({ targets: [] })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('Estimate')).toBeDisabled();
  });

  it('disables Estimate for an option position missing strike in its snapshot', () => {
    render(<EditDrawer position={makeOptionPosition({ tradeCardSnapshot: {} })} onClose={noop} onChange={noop} onRemove={noop} />);
    expect(screen.getByText('Estimate')).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npm run test -- --testPathPattern=EditDrawer`
Expected: FAIL — no "Estimate" button exists yet.

- [ ] **Step 4: Implement the Monte Carlo section**

Modify `frontend/app/(frame)/portfolio/page.tsx`. `useState` is already imported at the top of the file (line 10: `import { useEffect, useState } from 'react';`) — no React import changes needed.

Add the `api` import (after line 16, `import { usePortfolioStore, flushPendingPositionPatches } from '@/lib/portfolioStore';`):

```ts
import { api } from '@/lib/api';
```

Inside `EditDrawer` (in `frontend/app/(frame)/portfolio/page.tsx`, right after the existing `useEffect` cleanup block at line 476-478), add the Monte Carlo state and handler:

```ts
  const isStock = position.contract.endsWith('|STOCK');
  const snapshot = position.tradeCardSnapshot ?? {};
  const stockTarget = position.targets[0]?.targetPrice ?? position.targets[0]?.stockPrice ?? null;
  const optionStrike = typeof snapshot.strike === 'number' ? snapshot.strike : null;
  const optionTrend = (snapshot.stockBreakdown as { trend?: number } | undefined)?.trend;
  const defaultTargetPct = useSettingsStore((s) => s.targetProfitPct);

  const estimateDisabled = isStock
    ? stockTarget == null || !position.stop
    : optionStrike == null || position.currentStockPrice == null || position.dteRemaining == null || !position.stop;

  // Guards against setting state after this drawer instance has unmounted —
  // mirrors the existing flushPendingPositionPatches cleanup effect above,
  // which already establishes that this component can go away mid-request
  // (closing the drawer, or the parent switching `editing` to a different row).
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, [position.recId]);

  const [mcLoading, setMcLoading] = useState(false);
  const [mcError, setMcError] = useState(false);
  const [mcHorizonExpired, setMcHorizonExpired] = useState(false);
  const [mcResult, setMcResult] = useState<{
    target: { probability: number; expectedDays: number | null };
    invalidation: { probability: number; expectedDays: number | null };
    // All three option targets when isStock is false; a single entry when isStock is true.
    targets?: { pct: number; probability: number; expectedDays: number | null }[];
  } | null>(null);

  const runEstimate = async () => {
    setMcLoading(true);
    setMcError(false);
    setMcHorizonExpired(false);
    setMcResult(null);
    try {
      if (isStock) {
        if (stockTarget == null || !position.stop) throw new Error('missing target/stop');
        const holdMax = typeof snapshot.holdMax === 'number' ? snapshot.holdMax : 15;
        const daysSinceEntry = Math.max(0, Math.round((Date.now() - new Date(position.entryDate).getTime()) / 86_400_000));
        const horizonExpired = daysSinceEntry >= holdMax;
        const horizonDays = Math.max(1, holdMax - daysSinceEntry);
        const res = await api.getStockFirstPassage({
          symbol: position.symbol,
          direction: position.direction,
          stock_price: position.currentPrice,
          target_price: stockTarget,
          invalidation_price: position.stop,
          horizon_days: horizonDays,
          signal_strength: typeof snapshot.stock_score === 'number' ? snapshot.stock_score : 50,
        });
        if (!mountedRef.current) return;
        setMcResult(res);
        setMcHorizonExpired(horizonExpired);
      } else {
        if (optionStrike == null || position.currentStockPrice == null || position.dteRemaining == null || !position.stop) {
          throw new Error('missing option context');
        }
        const res = await api.getFirstPassageEstimate({
          symbol: position.symbol,
          direction: position.direction,
          stock_price: position.currentStockPrice,
          strike: optionStrike,
          dte: position.dteRemaining,
          premium: position.currentPrice,
          delta: position.delta ?? 0.45,
          trend_score: optionTrend ?? 50,
          invalidation_price: position.stop,
          t1_pct: defaultTargetPct.t1,
          t2_pct: defaultTargetPct.t2,
          t3_pct: defaultTargetPct.t3,
        });
        if (!mountedRef.current) return;
        const first = res.targets[0] ?? { probability: 0, expectedDays: null };
        setMcResult({
          target: first,
          invalidation: res.invalidation,
          targets: res.targets.map((t) => ({ pct: t.pct, probability: t.probability, expectedDays: t.expectedDays })),
        });
      }
    } catch {
      if (mountedRef.current) setMcError(true);
    } finally {
      if (mountedRef.current) setMcLoading(false);
    }
  };
```

Add the section markup between the closing `</div>` of `.editGrid` (line 522) and the `.editFooter` div (line 524):

```tsx
      <div className={styles.mcSection}>
        <Text size={12} weight={500}>Monte Carlo estimate</Text>
        <div className={styles.mcRow}>
          <button type="button" className={styles.mcBtn} onClick={runEstimate} disabled={mcLoading || estimateDisabled}>
            <Text size={12} weight={500}>{mcLoading ? 'Estimating…' : 'Estimate'}</Text>
          </button>
          {mcError && <Text size={11} tone="reject">Couldn&apos;t compute an estimate — try again.</Text>}
        </div>
        {mcHorizonExpired && (
          <Text size={10} tone="caution">
            This position is already past its intended hold window — showing a 1-day estimate, which will read as near-zero for both. Not a genuine risk read.
          </Text>
        )}
        {mcResult && (
          <>
            {isStock ? (
              <div className={styles.mcResultRow}>
                <div>
                  <Text size={10} tone="dim">TARGET HIT</Text>
                  <Data size={14} weight={500} tone="pass">{`${Math.round(mcResult.target.probability * 100)}%`}</Data>
                  <Text size={10} tone="dim">{mcResult.target.expectedDays != null ? `~${Math.round(mcResult.target.expectedDays)}d` : 'unlikely'}</Text>
                </div>
                <div>
                  <Text size={10} tone="dim">STOP HIT</Text>
                  <Data size={14} weight={500} tone="reject">{`${Math.round(mcResult.invalidation.probability * 100)}%`}</Data>
                  <Text size={10} tone="dim">{mcResult.invalidation.expectedDays != null ? `~${Math.round(mcResult.invalidation.expectedDays)}d` : 'unlikely'}</Text>
                </div>
              </div>
            ) : (
              <div className={styles.mcResultRow}>
                {(mcResult.targets ?? []).map((t, i) => (
                  <div key={`${t.pct}-${i}`}>
                    <Text size={10} tone="dim">{`T${Math.round(t.pct * 100)}%`}</Text>
                    <Data size={14} weight={500} tone="pass">{`${Math.round(t.probability * 100)}%`}</Data>
                    <Text size={10} tone="dim">{t.expectedDays != null ? `~${Math.round(t.expectedDays)}d` : 'unlikely'}</Text>
                  </div>
                ))}
                <div>
                  <Text size={10} tone="dim">STOP HIT</Text>
                  <Data size={14} weight={500} tone="reject">{`${Math.round(mcResult.invalidation.probability * 100)}%`}</Data>
                  <Text size={10} tone="dim">{mcResult.invalidation.expectedDays != null ? `~${Math.round(mcResult.invalidation.expectedDays)}d` : 'unlikely'}</Text>
                </div>
              </div>
            )}
          </>
        )}
      </div>
```

`frontend/app/(frame)/portfolio/page.tsx:10` currently reads `import { useEffect, useState } from 'react';` — `useRef` is NOT already imported. Change it to:

```ts
import { useEffect, useRef, useState } from 'react';
```

- [ ] **Step 5: Add the CSS classes**

Add to `frontend/app/(frame)/portfolio/page.module.css`, near the existing `.editGrid`/`.editField` rules:

```css
.mcSection {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--border-subtle);
}

.mcRow {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.mcBtn {
  height: 30px;
  padding: 0 var(--space-4);
  background: transparent;
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  border-radius: var(--radius-md);
  font-family: var(--font-dm);
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms, color 120ms;
}

.mcBtn:hover:not(:disabled) {
  background: var(--bg-surface);
}

.mcBtn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.mcResultRow {
  display: grid;
  grid-template-columns: repeat(2, minmax(120px, 1fr));
  gap: var(--space-3);
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- --testPathPattern=EditDrawer`
Expected: PASS (4 tests)

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 8: Commit**

```bash
git add "frontend/app/(frame)/portfolio/page.tsx" "frontend/app/(frame)/portfolio/page.module.css" "frontend/app/(frame)/portfolio/__tests__/EditDrawer.test.tsx"
git commit -m "feat(portfolio): wire Monte Carlo estimate into the EditDrawer for stock and option positions"
```

---

## Task 7: Full verification pass

- [ ] **Step 1: Full backend test suite**

Run: `cd backend && pytest -q`
Expected: PASS, no regressions

- [ ] **Step 2: Full frontend test suite**

Run: `cd frontend && npm run test`
Expected: PASS, no regressions

- [ ] **Step 3: Full typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 4: Manual smoke check (if a browser/dev server is available in this session)**

Start the backend and `npm run dev` (localhost:3001), open Portfolio with at least one open stock position (manual/paper) and one option position, open each one's edit drawer, click "Estimate", confirm both branches return a result without a console error. If no dev environment is available in this session, state that explicitly instead of claiming it was checked.
