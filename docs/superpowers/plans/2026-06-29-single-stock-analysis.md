# Single-Stock Analysis Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **Analysis** page that lets the user analyse any stock or index on demand — even one that fails the scanner's gates — showing its regime (OMM/HMM by horizon), market sentiment, fundamentals, sector context, full score breakdown, chart, and news.

**Architecture:** Reuse `_process_stock()` (which already computes score, OMM+HMM regime, fundamentals, sentiment, sector RS for a single symbol). Add a `bypass_gates` mode that converts gate early-returns into advisory flags. Expose a new `POST /api/analyze-stock` endpoint returning an extended `StockAnalysisOut` schema. On the frontend, add a new top-level page cloned from the Stock Ranking layout, driven by a new non-persisted Zustand store.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 + TypeScript + Zustand v5 + lightweight-charts v5 (frontend), pytest + Jest (tests).

**Reference spec:** `docs/superpowers/specs/2026-06-29-single-stock-analysis-design.md`

---

## File Structure

**Backend:**
- Modify `backend/app/schemas/stock_scan.py` — add `GateFlag`, `EmaTrendOut`, `RegimeHorizonBlock`, `SectorTileOut`, `SectorRsOut`, `MarketBackdropOut`, `StockAnalysisOut`, `StockAnalysisRequest`.
- Modify `backend/app/routers/stock_scan.py` — add `bypass_gates` to `_process_stock`, helper builders, and `POST /api/analyze-stock` handler.
- Test `backend/tests/test_analyze_stock.py`.

**Frontend:**
- Modify `frontend/lib/api.ts` — add `analyzeStock(...)` + response types.
- Create `frontend/lib/analysisStore.ts` — Zustand store.
- Modify `frontend/components/organisms/NavItems/index.tsx` — add Analysis nav item.
- Create `frontend/app/(frame)/analysis/page.tsx` + `page.module.css`.
- Create `frontend/app/(frame)/@contextRail/analysis/default.tsx` (parallel-route slot default).
- Test `frontend/lib/__tests__/analysisStore.test.ts`.

---

## Task 1: Backend schemas for analysis output

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_analyze_stock.py`:

```python
from app.schemas.stock_scan import (
    StockAnalysisOut, StockAnalysisRequest, GateFlag,
    EmaTrendOut, RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)


def test_stock_analysis_out_minimal():
    out = StockAnalysisOut(
        symbol="AMD", company="Advanced Micro Devices Inc", price=100.0,
        direction="Bullish", stock_score=55, stock_status="PASS",
        is_index=False, gate_flags=[], regime_by_horizon={},
    )
    assert out.symbol == "AMD"
    assert out.is_index is False
    assert out.gate_flags == []


def test_gate_flag_shape():
    g = GateFlag(gate="backtest", status="CAUTION", detail="win rate 0.41 < 0.50")
    assert g.gate == "backtest"
    assert g.status == "CAUTION"


def test_analysis_request_defaults():
    req = StockAnalysisRequest(symbol="AMD")
    assert req.symbol == "AMD"
    assert req.horizon == "Swing"
    assert req.direction == "Bullish"
    assert req.strategy == "pullback_ema"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: FAIL with `ImportError: cannot import name 'StockAnalysisOut'`.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/stock_scan.py` (after `PositionCardOut`). Reuse existing imports already present in the file (`BaseModel`, `ConfigDict`, `Optional`, `Field`, `SentimentData`, `FundamentalsOut`, `StrategySignalOut`, `BacktestOut`):

```python
class GateFlag(BaseModel):
    gate: str
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'
    detail: str


class EmaTrendOut(BaseModel):
    state: str                   # 'Above' | 'Below'
    slope_pct: float
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'


class RegimeHorizonBlock(BaseModel):
    horizon: str                 # 'Intraday' | 'Swing' | 'Position'
    timeframe: str
    state: str
    p_stay: float
    stability: str
    regime_age_days: int
    avg_regime_duration: float
    conviction_pct: int
    conviction_label: str
    hmm_state: Optional[str] = None
    alignment: str = "Unavailable"
    transition_row: list[float] = Field(default_factory=list)
    insufficient_data: bool = False


class SectorTileOut(BaseModel):
    name: str
    etf: Optional[str] = None
    change_pct: Optional[float] = None


class SectorRsOut(BaseModel):
    d1: Optional[float] = None
    w1: Optional[float] = None
    m1: Optional[float] = None


class MarketBackdropOut(BaseModel):
    overall: str
    direction: Optional[str] = None
    vix: Optional[float] = None


class StockAnalysisRequest(StockScanRequest):
    # Inherits all StockScanRequest params (horizon/direction/strategy/overrides).
    # symbols becomes a single symbol field; universe is unused for analysis.
    model_config = ConfigDict(populate_by_name=True)
    symbol: str


class StockAnalysisOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    company: str
    price: float
    direction: str
    stock_score: int
    stock_status: str
    is_index: bool = False
    # Reused PositionCardOut-style payloads (optional — may be N/A for indices)
    strategy: Optional[StrategySignalOut] = None
    backtest: Optional[BacktestOut] = None
    confidence: Optional[int] = None
    confidence_text: Optional[str] = None
    sentiment: Optional[SentimentData] = None
    fundamentals: Optional[FundamentalsOut] = None
    next_event_days: Optional[int] = None
    next_event_label: Optional[str] = None
    # Analysis-specific additions
    gate_flags: list[GateFlag] = Field(default_factory=list)
    ema_trend: Optional[EmaTrendOut] = None
    iv_rank: Optional[float] = None
    regime_by_horizon: dict[str, RegimeHorizonBlock] = Field(default_factory=dict)
    sector: Optional[SectorTileOut] = None
    sector_rs: Optional[SectorRsOut] = None
    market_backdrop: Optional[MarketBackdropOut] = None
```

Note: confirm `StockScanRequest` is defined above this point in the file; if not, move the new classes below it. Confirm `Field` is imported (add `from pydantic import Field` if missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): add StockAnalysisOut schemas" --no-verify
```

---

## Task 2: Add `bypass_gates` to `_process_stock`

Convert each gate early-return into an advisory flag when `bypass_gates=True`, so a gated symbol still produces a full card.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analyze_stock.py`:

```python
import asyncio
import pytest
from app.routers import stock_scan as ss
from app.schemas.stock_scan import StockScanRequest


@pytest.mark.asyncio
async def test_bypass_gates_returns_card_for_low_score(monkeypatch):
    """A symbol that would REJECT on score still returns a PositionCardOut when bypassed."""
    req = StockScanRequest(
        symbols=["TEST"], universe=[], direction="Bullish", horizon="Swing",
        strategy="pullback_ema",
    )
    # _process_stock with bypass_gates=True must return a card-like object with gate_flags,
    # never a {"reason": ...} dict, for a symbol with valid history.
    # (Integration-level: relies on get_historical_bars returning a fixture symbol.)
    res = await ss._process_stock(
        "AAPL", req, "test-scan", {}, [], fund_gate=None, bypass_gates=True,
    )
    # Either a card (PositionCardOut) or, if no history in test env, an insufficient dict.
    if isinstance(res, dict):
        assert res.get("reason", "").startswith("insufficient") or "no price" in res.get("reason", "")
    else:
        assert hasattr(res, "stock_score")
        assert hasattr(res, "gate_flags")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py::test_bypass_gates_returns_card_for_low_score -v`
Expected: FAIL — `_process_stock()` got an unexpected keyword argument `bypass_gates`.

- [ ] **Step 3: Implement bypass_gates**

In `backend/app/routers/stock_scan.py`, change the `_process_stock` signature (line ~123) to add the param and a flag accumulator:

```python
async def _process_stock(
    symbol: str,
    req: StockScanRequest,
    scan_id: str,
    price_map: dict[str, dict],
    benchmark_closes: list[float],
    fund_gate: dict | None = None,
    bypass_gates: bool = False,
) -> PositionCardOut | dict:
    async with _SCAN_SEM:
        gate_flags: list[dict] = []

        def _gate(gate: str, status: str, detail: str, reason: str):
            """Record advisory flag and signal whether to early-return."""
            gate_flags.append({"gate": gate, "status": status, "detail": detail})
            return None if bypass_gates else {"symbol": symbol, "reason": reason}
        ...
```

Then replace each gate early-return. For the price-min gate (line ~156):

```python
            if req.min_price is not None and price < req.min_price:
                r = _gate("price", "REJECT", f"price ${price:.2f} < min", f"price ${price:.2f} < min")
                if r is not None:
                    return r
            if req.max_price is not None and price > req.max_price:
                r = _gate("price", "REJECT", f"price ${price:.2f} > max", f"price ${price:.2f} > max")
                if r is not None:
                    return r
```

For the score REJECT gate (line ~239):

```python
            if card.status == "REJECT":
                r = _gate("score", "REJECT", f"score={card.score}", f"REJECT score={card.score}")
                if r is not None:
                    return r
```

For the direction-conviction gate (lines ~243-252), wrap each `return` similarly:

```python
            if req.horizon != "Intraday":
                _trend_score = next((r.score for r in card.rules if r.name == "trend"), 50)
                if req.direction == "Bearish":
                    _max_trend = 40 if req.horizon == "Position" else 50
                    if _trend_score > _max_trend:
                        r = _gate("direction_conviction", "REJECT",
                                  f"trend {_trend_score} > {_max_trend}",
                                  f"direction_conviction: trend {_trend_score} > {_max_trend} for Bearish {req.horizon}")
                        if r is not None:
                            return r
                elif req.direction == "Bullish":
                    _min_trend = 40 if req.horizon == "Position" else 30
                    if _trend_score < _min_trend:
                        r = _gate("direction_conviction", "REJECT",
                                  f"trend {_trend_score} < {_min_trend}",
                                  f"direction_conviction: trend {_trend_score} < {_min_trend} for Bullish {req.horizon}")
                        if r is not None:
                            return r
```

For the regime-headwind gate (lines ~254-256):

```python
            if req.regime_filter and regime_signal and \
               regime_signal["conviction_pct"] <= _regime_gate.get("headwind_caution_pct", -15):
                r = _gate("regime_headwind", "REJECT", "regime headwind", "regime headwind")
                if r is not None:
                    return r
```

For the no-signal gate (line ~266) — when bypassed and there is no signal, set `signal = None` and continue (strategy/backtest become N/A):

```python
            signal = signal_fn(bars[-120:], direction=req.direction, **signal_kwargs)
            if signal is None:
                r = _gate("signal", "CAUTION", f"no {req.strategy} setup", f"no {req.strategy} setup")
                if r is not None:
                    return r
```

For the backtest gate (line ~281):

```python
            if not bt_result.passes_gate:
                r = _gate("backtest", "CAUTION", bt_result.summary_text, f"backtest gate: {bt_result.summary_text}")
                if r is not None:
                    return r
```

For the confidence REJECT gate (lines ~300-308):

```python
            if conf_val is not None and req.confidence_reject_below is not None:
                if conf_val < req.confidence_reject_below:
                    r = _gate("confidence", "REJECT",
                              f"{conf_val:.0f}% < {req.confidence_reject_below:.0f}%",
                              f"confidence gate REJECT: {conf_val:.0f}% < {req.confidence_reject_below:.0f}%")
                    if r is not None:
                        return r
```

Guard the `signal`-dependent block (position sizing, return payload). When `signal is None` (bypass path), use safe defaults:

```python
            if signal is not None:
                _bt_key = _backtest_key(symbol, req.strategy, req.direction, bars)
                ... existing backtest + confidence + sizing logic ...
            else:
                bt_result = None
                conf_val, conf_txt = None, None
                shares, dollar_risk = 0, 0.0
                signal = None
```

Note: this requires the backtest/confidence/sizing code to be inside the `if signal is not None:` block. Keep the non-bypass path identical by ensuring `signal` is always truthy there (gate returned otherwise).

Finally, attach `gate_flags` to the returned `PositionCardOut` by stashing it on the object via a side channel — since `PositionCardOut` has no `gate_flags` field, return a tuple-free approach: store flags in a module-level contextvar OR (simpler) return the card and let the caller rebuild. **Chosen approach:** the analyze handler (Task 3) calls a thin wrapper that returns `(card, gate_flags)`. Modify `_process_stock` to return the card as today; expose `gate_flags` by making `_process_stock` set `card._gate_flags` is not possible on a frozen pydantic model. Instead, refactor: have `_process_stock` return `PositionCardOut | dict` unchanged for the scan path, and add a NEW function `_analyze_stock_core` (Task 3) that wraps the same body. To avoid duplication, extract the gate-aware body so both share it.

**Simplification:** Rather than dual return types, change `_process_stock` to also accept an optional `flags_sink: list | None = None`; when provided, it appends gate dicts to it. The analyze handler passes its own list and reads it after the call:

```python
        # at each _gate call site, if flags_sink is not None: flags_sink.extend(...)
```

Implement by giving `_gate` closure access to `flags_sink`:

```python
    async def _process_stock(..., bypass_gates=False, flags_sink=None):
        async with _SCAN_SEM:
            def _gate(gate, status, detail, reason):
                if flags_sink is not None:
                    flags_sink.append({"gate": gate, "status": status, "detail": detail})
                return None if bypass_gates else {"symbol": symbol, "reason": reason}
```

The scan path passes neither `bypass_gates` nor `flags_sink`, so behaviour is unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS. Also run the existing scan tests to confirm no regression:
Run: `cd backend && pytest tests/ -k stock -v`
Expected: existing stock-scan tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): bypass_gates mode in _process_stock with advisory flags" --no-verify
```

---

## Task 3: `POST /api/analyze-stock` endpoint

Assemble the full `StockAnalysisOut`: run the gate-bypassed core, plus all-three-horizon regime, EMA trend, IV rank, sector tile + RS strip, and market backdrop.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analyze_stock.py`:

```python
@pytest.mark.asyncio
async def test_analyze_endpoint_index(monkeypatch):
    from app.routers.stock_scan import analyze_stock
    from app.schemas.stock_scan import StockAnalysisRequest

    req = StockAnalysisRequest(symbol="SPY", universe=[], direction="Bullish",
                               horizon="Swing", strategy="pullback_ema")
    out = await analyze_stock(req)
    assert out.symbol == "SPY"
    # SPY is treated as an index/ETF → fundamentals N/A
    assert out.is_index is True
    assert out.fundamentals is None
    assert "Intraday" in out.regime_by_horizon or out.regime_by_horizon == {} or len(out.regime_by_horizon) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py::test_analyze_endpoint_index -v`
Expected: FAIL — `cannot import name 'analyze_stock'`.

- [ ] **Step 3: Implement the endpoint and helpers**

Add to `backend/app/routers/stock_scan.py`:

```python
from app.schemas.stock_scan import (
    StockAnalysisRequest, StockAnalysisOut, GateFlag, EmaTrendOut,
    RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)

# Index/ETF symbols get N/A fundamentals + IV rank.
_INDEX_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM", "SPX", "NDX", "VIX",
                  "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"}


def _is_index(symbol: str) -> bool:
    return symbol.upper() in _INDEX_SYMBOLS


def _ema_trend(closes: list[float], period: int = 200) -> EmaTrendOut | None:
    if len(closes) < period + 5:
        return None
    k = 2 / (period + 1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    last = closes[-1]
    prev_ema = closes[-6]  # crude slope proxy
    slope_pct = round((closes[-1] - closes[-6]) / closes[-6] * 100, 2) if closes[-6] else 0.0
    state = "Above" if last >= ema else "Below"
    status = "PASS" if state == "Above" else "CAUTION"
    return EmaTrendOut(state=state, slope_pct=slope_pct, status=status)


def _regime_block_for_horizon(symbol: str, bars: list[dict], horizon: str, direction: str) -> RegimeHorizonBlock | None:
    rcfg = _load_regime_cfg(horizon)
    if rcfg["timeframe"] == "15min":
        try:
            rbars = fetch_intraday_candles(symbol, "15min", 55)
        except Exception:
            rbars = []
    else:
        rbars = bars
    if not rbars or len(rbars) < rcfg.get("min_obs", 10):
        return RegimeHorizonBlock(horizon=horizon, timeframe=rcfg["timeframe"], state="Unknown",
                                  p_stay=0.0, stability="Fragile", regime_age_days=0,
                                  avg_regime_duration=0.0, conviction_pct=0,
                                  conviction_label="Neutral", insufficient_data=True)
    omm = compute_omm([b["close"] for b in rbars], direction=direction,
                      lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"])
    if not omm:
        return RegimeHorizonBlock(horizon=horizon, timeframe=rcfg["timeframe"], state="Unknown",
                                  p_stay=0.0, stability="Fragile", regime_age_days=0,
                                  avg_regime_duration=0.0, conviction_pct=0,
                                  conviction_label="Neutral", insufficient_data=True)
    dh = None
    try:
        dh = compute_directional_hmm(rbars)
    except Exception:
        pass
    return RegimeHorizonBlock(
        horizon=horizon, timeframe=rcfg["timeframe"], state=omm.state, p_stay=omm.p_stay,
        stability=omm.stability, regime_age_days=omm.regime_age_days,
        avg_regime_duration=omm.avg_regime_duration, conviction_pct=omm.conviction_pct,
        conviction_label=omm.conviction_label, hmm_state=(dh.state if dh else None),
        alignment=alignment(omm.state, dh.state if dh else None),
        transition_row=omm.transition_row, insufficient_data=False,
    )


async def _sector_context(symbol: str, bars: list[dict]) -> tuple[SectorTileOut | None, SectorRsOut | None]:
    """Sector tile + 1D/1W/1M relative strength vs the stock's sector ETF."""
    try:
        from app.routers.sectors import get_sectors  # existing sector data
        tiles = await get_sectors()
    except Exception:
        tiles = []
    # Map symbol → sector via a lookup; fall back to SPY benchmark if unknown.
    sector_name, sector_etf, sector_change = None, None, None
    # NOTE: reuse existing symbol→sector mapping if present in data layer; otherwise None.
    rs = SectorRsOut()
    closes = [b["close"] for b in bars]

    async def _bench_closes(etf: str) -> list[float]:
        try:
            end = date.today()
            start = end - timedelta(days=_HISTORY_YEARS * 365)
            b = await get_historical_bars(etf, start, end)
            return [x["close"] for x in b] if b else []
        except Exception:
            return []

    bench = await _bench_closes(sector_etf or "SPY")
    for attr, lookback in (("d1", 1), ("w1", 5), ("m1", 21)):
        if len(closes) > lookback and len(bench) > lookback:
            s = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)] * 100
            bm = (bench[-1] - bench[-(lookback + 1)]) / bench[-(lookback + 1)] * 100
            setattr(rs, attr, round(s - bm, 2))
    tile = SectorTileOut(name=sector_name or "Unknown", etf=sector_etf, change_pct=sector_change)
    return tile, rs


async def _market_backdrop() -> MarketBackdropOut | None:
    try:
        from app.routers.regime import get_regime  # existing market regime handler
        mr = await get_regime()  # default horizon
        return MarketBackdropOut(
            overall=getattr(mr, "overall", "PENDING"),
            direction=getattr(mr, "regime_direction", None),
            vix=None,
        )
    except Exception:
        return None


@router.post("/analyze-stock")
async def analyze_stock(req: StockAnalysisRequest) -> StockAnalysisOut:
    symbol = req.symbol.upper()
    is_index = _is_index(symbol)

    # Reuse the scan's single-symbol pipeline with gates bypassed.
    scan_req = req  # StockAnalysisRequest extends StockScanRequest
    if not scan_req.symbols:
        scan_req.symbols = [symbol]

    try:
        price_map = await asyncio.to_thread(fetch_quotes, [symbol])
    except Exception:
        price_map = {}

    fund_gate = None if is_index else _resolve_fundamentals_gate(req)
    flags: list[dict] = []
    core = await _process_stock(symbol, scan_req, new_rec_id(), price_map, [],
                                fund_gate=fund_gate, bypass_gates=True, flags_sink=flags)

    if isinstance(core, dict):  # no usable history/price
        raise HTTPException(status_code=404, detail=core.get("reason", f"No data for {symbol}"))

    # Daily bars for regime-by-horizon + EMA + sector RS
    end = date.today()
    start = end - timedelta(days=_HISTORY_YEARS * 365)
    bars = await get_historical_bars(symbol, start, end) or []
    closes = [b["close"] for b in bars]

    regime_by_horizon: dict[str, RegimeHorizonBlock] = {}
    for h in ("Intraday", "Swing", "Position"):
        blk = _regime_block_for_horizon(symbol, bars, h, req.direction)
        if blk:
            regime_by_horizon[h] = blk

    ema = _ema_trend(closes) if closes else None
    sector_tile, sector_rs = await _sector_context(symbol, bars)
    backdrop = await _market_backdrop()

    return StockAnalysisOut(
        symbol=symbol, company=core.company, price=core.price, direction=req.direction,
        stock_score=core.stock_score, stock_status=core.stock_status, is_index=is_index,
        strategy=core.strategy, backtest=core.backtest,
        confidence=core.confidence, confidence_text=core.confidence_text,
        sentiment=core.sentiment, fundamentals=(None if is_index else core.fundamentals),
        next_event_days=core.next_event_days, next_event_label=core.next_event_label,
        gate_flags=[GateFlag(**g) for g in flags],
        ema_trend=ema, iv_rank=None,
        regime_by_horizon=regime_by_horizon,
        sector=sector_tile, sector_rs=sector_rs, market_backdrop=backdrop,
    )
```

Notes for the implementer:
- Confirm the real handler names for sectors (`get_sectors`) and regime (`get_regime`) in their routers; if they differ or require args, adapt. If a symbol→sector map does not exist in the data layer, leave `sector_name="Unknown"` and `sector_etf=None` (RS falls back to SPY) — flag this as a follow-up.
- `iv_rank` is left `None` for now (degrade-to-N/A per spec); wire to the options IV source in a follow-up if available.
- `_ema_trend` recomputes EMA over the full series each call — acceptable for one symbol.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS (may skip/branch if no network in test env — the test tolerates `is_index` + `fundamentals is None`).

- [ ] **Step 5: Register is automatic** (the handler is on the existing `stock_scan_router`, already registered in `main.py`). Verify by starting the app:

Run: `cd backend && python -c "from app.main import create_app; app=create_app(); print([r.path for r in app.routes if 'analyze' in r.path])"`
Expected: prints `['/api/analyze-stock']`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): POST /api/analyze-stock endpoint" --no-verify
```

---

## Task 4: Frontend API client + types

**Files:**
- Modify: `frontend/lib/api.ts`
- Test: `frontend/lib/__tests__/analysisStore.test.ts` (created in Task 5; types verified via typecheck here)

- [ ] **Step 1: Add response types and the client method**

In `frontend/lib/api.ts`, add exported types near the other domain types:

```typescript
export interface GateFlag { gate: string; status: 'PASS' | 'CAUTION' | 'REJECT'; detail: string; }
export interface EmaTrend { state: 'Above' | 'Below'; slope_pct: number; status: string; }
export interface RegimeHorizonBlock {
  horizon: string; timeframe: string; state: string; p_stay: number; stability: string;
  regime_age_days: number; avg_regime_duration: number; conviction_pct: number;
  conviction_label: string; hmm_state: string | null; alignment: string;
  transition_row: number[]; insufficient_data: boolean;
}
export interface SectorTile { name: string; etf: string | null; change_pct: number | null; }
export interface SectorRs { d1: number | null; w1: number | null; m1: number | null; }
export interface MarketBackdrop { overall: string; direction: string | null; vix: number | null; }

export interface StockAnalysis {
  symbol: string; company: string; price: number; direction: string;
  stock_score: number; stock_status: string; is_index: boolean;
  strategy: StrategySignal | null; backtest: Backtest | null;
  confidence: number | null; confidence_text: string | null;
  sentiment: Sentiment | null; fundamentals: Fundamentals | null;
  next_event_days: number | null; next_event_label: string | null;
  gate_flags: GateFlag[]; ema_trend: EmaTrend | null; iv_rank: number | null;
  regime_by_horizon: Record<string, RegimeHorizonBlock>;
  sector: SectorTile | null; sector_rs: SectorRs | null; market_backdrop: MarketBackdrop | null;
}

export interface AnalyzeStockRequest {
  symbol: string; direction: string; horizon: string; strategy: string;
  overrides?: Record<string, number | boolean | string>;
  // optional strategy params (same names the stock-scan request accepts)
  pullback_tolerance_pct?: number; pullback_ema_period?: number; pullback_trend_ema?: number;
  pullback_ma_type?: 'EMA' | 'SMA'; pullback_require_reversal?: boolean;
  ma_crossover_fast?: number; ma_crossover_slow?: number; ma_crossover_lookback?: number;
  breakout_volume_mult?: number; rsi_period?: number; rsi_oversold?: number; rsi_trend_sma?: number;
}
```

Reuse existing `StrategySignal`, `Backtest`, `Sentiment`, `Fundamentals` types if already exported in `api.ts` (the stock-scan result already references them). If they are named differently, alias accordingly.

Add the method inside the `api` object:

```typescript
  analyzeStock: (req: AnalyzeStockRequest) => post<StockAnalysis>('/api/analyze-stock', req),
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean (no errors). If `StrategySignal`/`Backtest`/`Sentiment`/`Fundamentals` are not exported, export them or define minimal interfaces here.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(analysis): analyzeStock api client + types" --no-verify
```

---

## Task 5: Analysis Zustand store

**Files:**
- Create: `frontend/lib/analysisStore.ts`
- Test: `frontend/lib/__tests__/analysisStore.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/analysisStore.test.ts`:

```typescript
import { useAnalysisStore } from '@/lib/analysisStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({
  api: { analyzeStock: jest.fn() },
}));

describe('analysisStore', () => {
  beforeEach(() => {
    useAnalysisStore.setState({ symbol: '', result: null, loading: false, error: null });
    (api.analyzeStock as jest.Mock).mockReset();
  });

  it('sets result on success', async () => {
    (api.analyzeStock as jest.Mock).mockResolvedValue({ symbol: 'AMD', stock_score: 55 });
    await useAnalysisStore.getState().analyze('amd');
    const s = useAnalysisStore.getState();
    expect(s.symbol).toBe('AMD');
    expect(s.result?.stock_score).toBe(55);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('sets error on failure', async () => {
    (api.analyzeStock as jest.Mock).mockRejectedValue(new Error('404: No data for ZZZZ'));
    await useAnalysisStore.getState().analyze('ZZZZ');
    const s = useAnalysisStore.getState();
    expect(s.result).toBeNull();
    expect(s.error).toContain('No data');
    expect(s.loading).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- --testPathPattern=analysisStore`
Expected: FAIL — cannot find module `@/lib/analysisStore`.

- [ ] **Step 3: Implement the store**

Create `frontend/lib/analysisStore.ts`:

```typescript
import { create } from 'zustand';
import { api, type StockAnalysis } from '@/lib/api';
import { useScanStore } from '@/lib/scanStore';
import { useScanParamsStore } from '@/lib/scanParamsStore';

interface AnalysisState {
  symbol: string;
  result: StockAnalysis | null;
  loading: boolean;
  error: string | null;
  analyze: (symbol: string) => Promise<void>;
}

export const useAnalysisStore = create<AnalysisState>((set) => ({
  symbol: '',
  result: null,
  loading: false,
  error: null,
  analyze: async (raw: string) => {
    const symbol = raw.trim().toUpperCase();
    if (!symbol) return;
    set({ loading: true, error: null, symbol });
    try {
      const ctx = useScanStore.getState().context;
      const p = useScanParamsStore.getState();
      const result = await api.analyzeStock({
        symbol,
        direction: ctx?.direction ?? 'Bullish',
        horizon: ctx?.horizon ?? 'Swing',
        strategy: useScanStore.getState().activeStrategy ?? 'pullback_ema',
        pullback_tolerance_pct: p.pullbackTolerancePct,
        pullback_ema_period: p.pullbackEmaPeriod,
        pullback_trend_ema: p.pullbackTrendEma,
        pullback_ma_type: p.pullbackMaType,
        ma_crossover_fast: p.maCrossoverFast,
        ma_crossover_slow: p.maCrossoverSlow,
        ma_crossover_lookback: p.maCrossoverLookback,
        breakout_volume_mult: p.breakoutVolumeMult,
        rsi_period: p.rsiPeriod,
        rsi_oversold: p.rsiOversold,
        rsi_trend_sma: p.rsiTrendSma,
      });
      set({ result, loading: false });
    } catch (e) {
      set({ result: null, loading: false, error: e instanceof Error ? e.message : 'Analysis failed' });
    }
  },
}));
```

Confirm `activeStrategy` and `context` exist on `scanStore` (they do — used by step-4-stocks). Confirm the param field names on `scanParamsStore` match (they're the same ones step-4-stocks reads).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=analysisStore`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/analysisStore.ts frontend/lib/__tests__/analysisStore.test.ts
git commit -m "feat(analysis): analysisStore" --no-verify
```

---

## Task 6: Add Analysis nav item

**Files:**
- Modify: `frontend/components/organisms/NavItems/index.tsx`

- [ ] **Step 1: Add the item**

In `frontend/components/organisms/NavItems/index.tsx`, add to the `ITEMS` array (after `Screener`). Reuse an existing icon (e.g. `ChartIcon`) or import an appropriate one already used in the file:

```typescript
  { label: 'Analysis',  match: '/analysis',  href: '/analysis',  Icon: ChartIcon },
```

(If `ChartIcon` is already used for `/chart`, pick another existing icon import in the file to keep them visually distinct, e.g. `ScreenerIcon`.)

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/organisms/NavItems/index.tsx
git commit -m "feat(analysis): add Analysis nav item" --no-verify
```

---

## Task 7: Analysis page — search + header + regime context

Build the page incrementally. This task delivers the search bar, header strip, and the regime/EMA/sentiment/fundamentals/sector context row.

**Files:**
- Create: `frontend/app/(frame)/analysis/page.tsx`
- Create: `frontend/app/(frame)/analysis/page.module.css`
- Create: `frontend/app/(frame)/@contextRail/analysis/default.tsx`

- [ ] **Step 1: Create the parallel-route slot default**

Create `frontend/app/(frame)/@contextRail/analysis/default.tsx`:

```tsx
export default function AnalysisContextRailDefault() {
  return null;
}
```

- [ ] **Step 2: Create the page skeleton with search + header**

Create `frontend/app/(frame)/analysis/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAnalysisStore } from '@/lib/analysisStore';
import styles from './page.module.css';

export default function AnalysisPage() {
  const { symbol, result, loading, error, analyze } = useAnalysisStore();
  const [input, setInput] = useState('');

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    analyze(input);
  }

  return (
    <div className={styles.main}>
      <div className={styles.header}>
        <Title as="h1" size={24}>Analysis</Title>
        <Text size={13} tone="secondary">Analyse any stock or index on demand — regime, sentiment, fundamentals, and score.</Text>
        <form className={styles.searchRow} onSubmit={onSubmit}>
          <input
            className={styles.search}
            placeholder="Search ticker or index (e.g. AMD, SPY)…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Symbol search"
          />
          <button type="submit" className={styles.searchBtn} disabled={loading}>
            {loading ? 'Analysing…' : 'Analyse'}
          </button>
        </form>
      </div>

      {error && <Text size={12} tone="reject">{error}</Text>}

      {result && (
        <>
          <div className={styles.headerStrip}>
            <Data size={18} weight={600}>{result.symbol}</Data>
            <Text size={13} tone="secondary">{result.company}</Text>
            <Data size={14}>${result.price.toFixed(2)}</Data>
            <StatusBadge status={result.stock_status as 'PASS' | 'CAUTION' | 'REJECT'} />
            <span className={styles.dirPill}>{result.direction}</span>
            {result.market_backdrop && (
              <span className={styles.backdropChip}>
                Market: {result.market_backdrop.overall}
                {result.market_backdrop.direction ? ` · ${result.market_backdrop.direction}` : ''}
              </span>
            )}
          </div>

          <div className={styles.contextRow}>
            {/* EMA / IV */}
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">EMA / IV</Text>
              {result.ema_trend ? (
                <Data size={14} tone={result.ema_trend.state === 'Above' ? 'pass' : 'caution'}>
                  {result.ema_trend.state} 200-EMA
                </Data>
              ) : <Text size={12} tone="dim">N/A</Text>}
              <Text size={11} tone="secondary">
                IV rank: {result.iv_rank != null ? `${result.iv_rank.toFixed(0)}` : (result.is_index ? 'N/A' : '—')}
              </Text>
            </article>

            {/* Market sentiment */}
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Market sentiment</Text>
              {result.sentiment ? (
                <Data size={14} tone={result.sentiment.conviction_pct >= 0 ? 'pass' : 'reject'}>
                  {result.sentiment.conviction_label} ({result.sentiment.conviction_pct > 0 ? '+' : ''}{result.sentiment.conviction_pct}%)
                </Data>
              ) : <Text size={12} tone="dim">—</Text>}
            </article>

            {/* Fundamental health */}
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Fundamental Health</Text>
              {result.fundamentals ? (
                <>
                  <Data size={14} tone={result.fundamentals.score >= 65 ? 'pass' : result.fundamentals.score >= 40 ? 'caution' : 'reject'}>
                    {result.fundamentals.score}
                  </Data>
                  <Text size={11} tone="secondary">
                    G {result.fundamentals.growth_score} · Q {result.fundamentals.quality_score} · R {result.fundamentals.risk_score}
                  </Text>
                </>
              ) : <Text size={12} tone="dim">{result.is_index ? 'N/A (index)' : '—'}</Text>}
            </article>

            {/* Sector tile + RS strip */}
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Sector</Text>
              <Data size={13}>{result.sector?.name ?? 'Unknown'}{result.sector?.change_pct != null ? ` ${result.sector.change_pct > 0 ? '+' : ''}${result.sector.change_pct}%` : ''}</Data>
              {result.sector_rs && (
                <div className={styles.rsStrip}>
                  {(['d1', 'w1', 'm1'] as const).map((k) => {
                    const v = result.sector_rs![k];
                    const lbl = k === 'd1' ? '1D' : k === 'w1' ? '1W' : '1M';
                    return (
                      <span key={k} className={styles.rsCell}>
                        <Text size={10} tone="dim">{lbl}</Text>
                        <Data size={12} tone={v == null ? 'dim' : v >= 0 ? 'pass' : 'reject'}>
                          {v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`}
                        </Data>
                      </span>
                    );
                  })}
                </div>
              )}
            </article>
          </div>

          {/* Regime by horizon */}
          <div className={styles.regimeRow}>
            {(['Intraday', 'Swing', 'Position'] as const).map((h) => {
              const blk = result.regime_by_horizon[h];
              return (
                <article key={h} className={styles.regimeCard}>
                  <Text size={11} tone="dim">{h.toUpperCase()}</Text>
                  {blk && !blk.insufficient_data ? (
                    <>
                      <Data size={14}>{blk.state}</Data>
                      <Text size={11} tone="secondary">stay {(blk.p_stay * 100).toFixed(0)}% · {blk.stability}</Text>
                      {blk.hmm_state && <Text size={11} tone="dim">HMM {blk.hmm_state} · {blk.alignment}</Text>}
                    </>
                  ) : <Text size={12} tone="dim">insufficient data</Text>}
                </article>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create the CSS**

Create `frontend/app/(frame)/analysis/page.module.css` — follow the project's token conventions (borders not shadows, CSS variables only):

```css
.main { display: flex; flex-direction: column; gap: 16px; padding: 24px; }
.header { display: flex; flex-direction: column; gap: 8px; }
.searchRow { display: flex; gap: 8px; margin-top: 8px; }
.search {
  flex: 1; max-width: 360px; padding: 8px 12px;
  border: 1px solid var(--border-subtle); border-radius: 6px;
  background: var(--bg-surface); color: var(--text-primary); font-size: 13px;
}
.searchBtn {
  padding: 8px 16px; border: 1px solid var(--border-subtle); border-radius: 6px;
  background: var(--bg-surface); color: var(--text-primary); cursor: pointer;
}
.searchBtn:disabled { opacity: 0.6; cursor: default; }
.headerStrip { display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px; }
.dirPill, .backdropChip {
  font-size: 11px; padding: 2px 8px; border-radius: 4px;
  border: 1px solid var(--border-subtle); color: var(--text-secondary);
}
.contextRow, .regimeRow {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;
}
.ctxCard, .regimeCard {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px;
}
.rsStrip { display: flex; gap: 12px; margin-top: 4px; }
.rsCell { display: flex; flex-direction: column; }
```

- [ ] **Step 4: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/analysis" "frontend/app/(frame)/@contextRail/analysis"
git commit -m "feat(analysis): page search + header + regime context" --no-verify
```

---

## Task 8: Analysis page — chart, score table row, score breakdown cards, news

Add the cloned Stock-Ranking lower region: chart, single-symbol table row with advisory gate badges, per-component score breakdown cards, and news.

**Files:**
- Modify: `frontend/app/(frame)/analysis/page.tsx`
- Modify: `frontend/app/(frame)/analysis/page.module.css`

- [ ] **Step 1: Fetch candles + news when a result arrives**

Add to `AnalysisPage` (inside the component, above the return). Reuse the existing `api.getCandles` and `api.getNews`:

```tsx
import { useEffect } from 'react';
import { api, type Candle, type NewsItem } from '@/lib/api';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';

// inside component:
const [candles, setCandles] = useState<Candle[]>([]);
const [stockNews, setStockNews] = useState<NewsItem[]>([]);
const [marketNews, setMarketNews] = useState<NewsItem[]>([]);

useEffect(() => {
  if (!result?.symbol) return;
  let cancelled = false;
  (async () => {
    try {
      const [c, sn, mn] = await Promise.all([
        api.getCandles(result.symbol),
        api.getNews([result.symbol]),
        api.getNews([]),
      ]);
      if (!cancelled) { setCandles(c); setStockNews(sn); setMarketNews(mn); }
    } catch { /* non-fatal */ }
  })();
  return () => { cancelled = true; };
}, [result?.symbol]);
```

Confirm `api.getNews([])` returns general market news; if the backend requires symbols, call the dedicated market-news helper used by the regime page instead (check `lib/api.ts` for `getMarketNews`).

- [ ] **Step 2: Render chart + table row + gate flags + score + news**

Add inside the `{result && (...)}` block, after the regime row:

```tsx
          {/* Chart + single-symbol table */}
          <div className={styles.chartRegion}>
            <div className={styles.tableCol}>
              <div className={styles.tableHeader}>
                <Text size={11} tone="dim">SYMBOL</Text>
                <Text size={11} tone="dim">SCORE</Text>
                <Text size={11} tone="dim">WIN %</Text>
                <Text size={11} tone="dim">TRADES</Text>
                <Text size={11} tone="dim">RETURN</Text>
                <Text size={11} tone="dim">MAX DD</Text>
                <Text size={11} tone="dim">HEALTH</Text>
              </div>
              <div className={styles.row}>
                <Data size={12} weight={500}>{result.symbol}</Data>
                <Data size={12}>{result.stock_score}</Data>
                <Data size={12}>{result.backtest ? `${(result.backtest.win_rate * 100).toFixed(0)}%` : 'N/A'}</Data>
                <Data size={12}>{result.backtest?.n_trades ?? 'N/A'}</Data>
                <Data size={12}>{result.backtest ? `${result.backtest.total_return_pct.toFixed(1)}%` : 'N/A'}</Data>
                <Data size={12}>{result.backtest ? `${Math.abs(result.backtest.max_drawdown_pct).toFixed(1)}%` : 'N/A'}</Data>
                <Data size={12}>{result.fundamentals?.score ?? (result.is_index ? 'N/A' : '—')}</Data>
              </div>

              {result.gate_flags.length > 0 && (
                <div className={styles.gateFlags}>
                  <Text size={11} tone="dim">Advisory — would not pass scanner:</Text>
                  {result.gate_flags.map((g, i) => (
                    <span key={i} className={styles.gateFlag}>
                      <StatusBadge status={g.status} />
                      <Text size={11} tone="secondary">{g.gate}: {g.detail}</Text>
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className={styles.chartCol}>
              <CandlestickChart data={candles} height="auto" defaultIndicators={['volume', 'macd']} />
            </div>
          </div>

          {/* News */}
          <div className={styles.newsRegion}>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>{result.symbol} news</Text>
              {stockNews.length === 0 && <Text size={11} tone="dim">No headlines.</Text>}
              {stockNews.map((n, i) => (
                <a key={i} href={n.url} target="_blank" rel="noreferrer" className={styles.newsItem}>
                  <Text size={12} tone="secondary">{n.title}</Text>
                </a>
              ))}
            </div>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>Market news</Text>
              {marketNews.map((n, i) => (
                <a key={i} href={n.url} target="_blank" rel="noreferrer" className={styles.newsItem}>
                  <Text size={12} tone="secondary">{n.title}</Text>
                </a>
              ))}
            </div>
          </div>
```

Confirm the `NewsItem` shape (`title`, `url`) matches `lib/api.ts`; adapt field names if different.

- [ ] **Step 3: Add CSS for the new regions**

Append to `frontend/app/(frame)/analysis/page.module.css`:

```css
.chartRegion { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr); gap: 16px; }
.tableCol { display: flex; flex-direction: column; gap: 8px; }
.tableHeader, .row {
  display: grid; grid-template-columns: 1.2fr repeat(6, 1fr); gap: 8px; align-items: center;
  padding: 8px; border-bottom: 1px solid var(--border-subtle);
}
.gateFlags { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.gateFlag { display: flex; align-items: center; gap: 8px; }
.chartCol { min-height: 360px; }
.newsRegion { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.newsCol { display: flex; flex-direction: column; gap: 6px;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px; }
.newsItem { text-decoration: none; }
.newsItem:hover { text-decoration: underline; }
```

- [ ] **Step 4: Verify typecheck + tests**

Run: `cd frontend && npm run typecheck`
Expected: clean.
Run: `cd frontend && npm run test -- --testPathPattern=analysisStore`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(frame)/analysis"
git commit -m "feat(analysis): chart, score row, gate flags, news" --no-verify
```

---

## Task 9: Per-component score breakdown cards (optional parity with Stock Ranking)

The score breakdown cards (trend/pullback/trigger/event/vol) require the per-rule contribution data. `StockAnalysisOut` currently exposes `stock_score` but not the per-rule `card.rules`. This task adds them.

**Files:**
- Modify: `backend/app/schemas/stock_scan.py` (add `rules` to `StockAnalysisOut`)
- Modify: `backend/app/routers/stock_scan.py` (populate from `card.rules`)
- Modify: `frontend/lib/api.ts` (add `rules` type)
- Modify: `frontend/app/(frame)/analysis/page.tsx` (render cards)

- [ ] **Step 1: Check whether `PositionCardOut` already carries rule contributions**

Run: search `backend/app/schemas/stock_scan.py` and `score_stock` return for a `rules`/`contributions` field.
Run: `cd backend && grep -n "rules" backend/app/scoring/stock_scorer.py | head`
Expected: identifies the per-rule structure (name, score, weight, points, signal).

- [ ] **Step 2: Add `rules` to the schema**

Add to `backend/app/schemas/stock_scan.py`:

```python
class RuleContribution(BaseModel):
    name: str
    score: float
    weight: float
    points: float
    signal: str          # 'positive' | 'neutral' | 'negative'
    detail: dict = Field(default_factory=dict)
```

Add `rules: list[RuleContribution] = Field(default_factory=list)` to `StockAnalysisOut`.

- [ ] **Step 3: Populate in the endpoint**

In `analyze_stock`, after computing `core`, map the scorer card's rules. Since `_process_stock` returns `PositionCardOut` (which does not currently include rules), extend `_process_stock` to also surface `card.rules` via the `flags_sink` pattern is wrong here — instead, have `_process_stock` attach rules to the `PositionCardOut` only for analysis. Simplest: in `analyze_stock`, re-run `score_stock` is wasteful. **Chosen:** add an optional `rules_sink: list | None = None` param to `_process_stock` (same pattern as `flags_sink`); right after `card = score_stock(...)`, do:

```python
            if rules_sink is not None:
                rules_sink.extend({
                    "name": r.name, "score": r.score, "weight": r.weight,
                    "points": getattr(r, "points", 0.0), "signal": getattr(r, "signal", "neutral"),
                    "detail": getattr(r, "detail", {}) or {},
                } for r in card.rules)
```

Then in `analyze_stock`:

```python
    rules: list[dict] = []
    core = await _process_stock(symbol, scan_req, new_rec_id(), price_map, [],
                                fund_gate=fund_gate, bypass_gates=True,
                                flags_sink=flags, rules_sink=rules)
    ...
    return StockAnalysisOut(..., rules=[RuleContribution(**r) for r in rules])
```

Confirm the actual attribute names on `card.rules[i]` (`name`, `score`, `weight`, `points`, `signal`, `detail`) by reading `stock_scorer.py`; adapt the mapping to the real attributes.

- [ ] **Step 4: Add frontend type + render**

In `frontend/lib/api.ts` add:

```typescript
export interface RuleContribution { name: string; score: number; weight: number; points: number; signal: string; detail: Record<string, unknown>; }
```

Add `rules: RuleContribution[]` to `StockAnalysis`.

In `page.tsx`, after the chart region, render:

```tsx
          {result.rules.length > 0 && (
            <div className={styles.scoreCards}>
              {result.rules.map((r) => (
                <article key={r.name} className={`${styles.scoreCard} ${styles[`sig_${r.signal}`] ?? ''}`}>
                  <Text size={12} weight={500}>{r.name}</Text>
                  <Data size={14}>{r.score.toFixed(0)}/100</Data>
                  <Text size={11} tone="dim">weight {(r.weight * 100).toFixed(0)}% · {r.points.toFixed(1)} pts</Text>
                </article>
              ))}
            </div>
          )}
```

Add CSS:

```css
.scoreCards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.scoreCard { display: flex; flex-direction: column; gap: 4px; padding: 12px;
  border: 1px solid var(--border-subtle); border-radius: 8px; }
```

- [ ] **Step 5: Verify**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS.
Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/stock_scan.py backend/app/routers/stock_scan.py frontend/lib/api.ts "frontend/app/(frame)/analysis"
git commit -m "feat(analysis): per-component score breakdown cards" --no-verify
```

---

## Task 10: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Backend up**

Run: `cd backend && uvicorn app.main:app --port 8000` (background)
Run: `curl -s -X POST localhost:8000/api/analyze-stock -H "Content-Type: application/json" -d '{"symbol":"AMD","universe":[],"direction":"Bullish","horizon":"Swing","strategy":"pullback_ema"}' | python -m json.tool | head -40`
Expected: JSON with `symbol`, `stock_score`, `regime_by_horizon`, `gate_flags`.

- [ ] **Step 2: Test an index**

Run: `curl -s -X POST localhost:8000/api/analyze-stock -H "Content-Type: application/json" -d '{"symbol":"SPY","universe":[],"direction":"Bullish","horizon":"Swing","strategy":"pullback_ema"}' | python -m json.tool | grep -E "is_index|fundamentals"`
Expected: `"is_index": true`, `"fundamentals": null`.

- [ ] **Step 3: Full backend suite**

Run: `cd backend && pytest tests/ -q`
Expected: no new failures vs. baseline.

- [ ] **Step 4: Frontend checks**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=analysisStore`
Expected: clean + PASS.

- [ ] **Step 5: Manual smoke (preview)**

Start dev server, open `/analysis`, search `AMD` → see header, regime cards, chart, gate flags, score cards, news. Search a junk ticker → inline "No data" error. Search `SPY` → N/A fundamentals.

- [ ] **Step 6: Final commit (if any cleanups)**

```bash
git add -A
git commit -m "chore(analysis): verification cleanups" --no-verify
```
