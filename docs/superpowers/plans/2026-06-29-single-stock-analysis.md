# Single-Stock Analysis Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **Analysis** page that lets the user analyse any stock or index on demand — even one that fails the scanner's gates — showing its regime (OMM/HMM by horizon), market sentiment, fundamentals, sector context, full score breakdown, chart, and news.

**Architecture:** Instead of mutating the gated scan pipeline, add a dedicated **gate-free** `_analyze_core()` in `backend/app/routers/stock_scan.py` that reuses the same sub-services (`score_stock`, `compute_omm`, `compute_directional_hmm`, the strategy signal fns, `run_strategy_backtest`, fundamentals) but performs **no early-return gates** and treats the strategy `signal` as optional. It records which gates a symbol *would* have failed as advisory `gate_flags`. The scan path (`_process_stock`) is left completely untouched (zero regression risk). A new `POST /api/analyze-stock` endpoint assembles a `StockAnalysisOut`. On the frontend, a new top-level Analysis page (cloned from the Stock Ranking layout) is driven by a non-persisted Zustand store.

**Tech Stack:** FastAPI + Pydantic v2 (backend), Next.js 15 + TypeScript + Zustand v5 + lightweight-charts v5 (frontend), pytest + Jest (tests).

**Reference spec:** `docs/superpowers/specs/2026-06-29-single-stock-analysis-design.md`

**Verified codebase facts this plan relies on:**
- `StockScanRequest` (schemas/stock_scan.py:10-15) requires `universe, direction, horizon, strategy` (no defaults).
- `RuleResult` (stock_scorer.py:20-25) has ONLY `name, status, score, detail` — no `weight`/`points`/`signal`.
- `PositionCardOut.strategy` / `.backtest` are **required, non-Optional** (schemas:91-92) — so the no-signal case must NOT use `PositionCardOut`.
- Frontend `NewsItem` (types/domain.ts:362) is `{ id, symbol, headline, source, timestamp, sentiment }` — no `title`/`url`.
- `api.getNews(symbols)` hits `/api/news?symbols=...`; empty list returns `[]` (news.py:16). General market news = `getNews(['SPY','QQQ'])`.
- `lib/api.ts` does NOT export `StrategySignal/Backtest/Sentiment/Fundamentals/Candle/NewsItem` — define/alias locally.
- `ScanContext.horizon` (scanStore.ts:15) is a DISPLAY LABEL like `"Swing (5–15d)"` — must be mapped to the `Intraday|Swing|Position` enum before sending.
- `regime.py:_ema(closes, period) -> float|None` exists — reuse it. `compute_overall_regime() -> str` (regime.py:94) is the cheap backdrop source.
- `stock_scan_router` IS registered in main.py:259.
- symbol→sector: `data/sp500.csv` has `symbol,sector`; `data/sector_names.py:NORMALIZE` canonicalises; `routers/sectors.py:_ETF_NAME` maps ETF→canonical name (reverse it for name→ETF).

---

## File Structure

**Backend:**
- Modify `backend/app/schemas/stock_scan.py` — add analysis output schemas.
- Create `backend/app/data/sector_map.py` — symbol→(sector_name, etf) lookup.
- Modify `backend/app/routers/stock_scan.py` — `_analyze_core`, helper builders, `POST /api/analyze-stock`.
- Test `backend/tests/test_analyze_stock.py`, `backend/tests/test_sector_map.py`.

**Frontend:**
- Modify `frontend/lib/api.ts` — `analyzeStock(...)` + response types.
- Create `frontend/lib/analysisStore.ts` — Zustand store (+ horizon-label mapping).
- Modify `frontend/components/organisms/NavItems/index.tsx` — Analysis nav item + icon.
- Create `frontend/app/(frame)/analysis/page.tsx` + `page.module.css`.
- Create `frontend/app/(frame)/@contextRail/analysis/default.tsx`.
- Test `frontend/lib/__tests__/analysisStore.test.ts`.

---

## Task 1: Backend analysis schemas

**Files:**
- Modify: `backend/app/schemas/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_analyze_stock.py`:

```python
from app.schemas.stock_scan import (
    StockAnalysisOut, StockAnalysisRequest, GateFlag, RuleContribution,
    EmaTrendOut, RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)


def test_stock_analysis_out_minimal():
    out = StockAnalysisOut(
        symbol="AMD", company="Advanced Micro Devices Inc", price=100.0,
        direction="Bullish", stock_score=55, stock_status="PASS",
        is_index=False,
    )
    assert out.symbol == "AMD"
    assert out.is_index is False
    assert out.gate_flags == []
    assert out.regime_by_horizon == {}
    assert out.strategy is None      # optional — None when no signal
    assert out.backtest is None


def test_gate_flag_shape():
    g = GateFlag(gate="backtest", status="CAUTION", detail="win rate 0.41 < 0.50")
    assert g.gate == "backtest"
    assert g.status == "CAUTION"


def test_rule_contribution_matches_ruleresult_fields():
    r = RuleContribution(name="trend", status="PASS", score=80, detail={"adx": 34})
    assert r.name == "trend"
    assert r.status == "PASS"
    assert r.score == 80


def test_analysis_request_defaults():
    # StockAnalysisRequest must be constructible from symbol alone (defaults supply the rest).
    req = StockAnalysisRequest(symbol="AMD")
    assert req.symbol == "AMD"
    assert req.horizon == "Swing"
    assert req.direction == "Bullish"
    assert req.strategy == "pullback_ema"
    assert req.universe == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: FAIL — `ImportError: cannot import name 'StockAnalysisOut'`.

- [ ] **Step 3: Add the schemas**

Append to `backend/app/schemas/stock_scan.py` (after `PositionCardOut`). The file already imports `BaseModel, ConfigDict, Field` (line 3), `Optional, Literal, Any` (line 2), and `SentimentData, FundamentalsOut` (line 4). `StrategySignalOut`/`BacktestOut`/`StockScanRequest` are defined above in the same file.

```python
class GateFlag(BaseModel):
    gate: str
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'
    detail: str


class RuleContribution(BaseModel):
    # Mirrors stock_scorer.RuleResult EXACTLY (name/status/score/detail).
    name: str
    status: str                  # 'PASS' | 'CAUTION' | 'REJECT'
    score: int
    detail: dict = Field(default_factory=dict)


class EmaTrendOut(BaseModel):
    state: str                   # 'Above' | 'Below'
    ema: float
    last: float
    status: str                  # 'PASS' | 'CAUTION'


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
    benchmark: str                          # ETF actually used (sector ETF or SPY fallback)
    d1: Optional[float] = None
    w1: Optional[float] = None
    m1: Optional[float] = None


class MarketBackdropOut(BaseModel):
    overall: str
    direction: Optional[str] = None
    vix: Optional[float] = None


class StockAnalysisRequest(StockScanRequest):
    # Override the four required StockScanRequest fields with defaults so the
    # endpoint is callable from `{symbol}` alone (the frontend always sends the
    # real horizon/direction/strategy; defaults exist for tests + safety).
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    universe: list[str] = Field(default_factory=list)
    direction: Literal["Bullish", "Bearish"] = "Bullish"
    horizon: Literal["Intraday", "Swing", "Position"] = "Swing"
    strategy: Strategy = "pullback_ema"


class StockAnalysisOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    symbol: str
    company: str
    price: float
    direction: str
    stock_score: int
    stock_status: str
    is_index: bool = False
    # Signal-dependent payloads — None when no strategy setup exists (bypass path)
    strategy: Optional[StrategySignalOut] = None
    backtest: Optional[BacktestOut] = None
    confidence: Optional[int] = None
    confidence_text: Optional[str] = None
    sentiment: Optional[SentimentData] = None
    fundamentals: Optional[FundamentalsOut] = None
    next_event_days: Optional[int] = None
    next_event_label: Optional[str] = None
    # Analysis-specific additions
    rules: list[RuleContribution] = Field(default_factory=list)
    gate_flags: list[GateFlag] = Field(default_factory=list)
    ema_trend: Optional[EmaTrendOut] = None
    iv_rank: Optional[float] = None
    regime_by_horizon: dict[str, RegimeHorizonBlock] = Field(default_factory=dict)
    sector: Optional[SectorTileOut] = None
    sector_rs: Optional[SectorRsOut] = None
    market_backdrop: Optional[MarketBackdropOut] = None
```

Confirm `Strategy` (the `Literal[...]` alias) is defined at module top (line 7) — it is.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): add StockAnalysisOut schemas"
```

---

## Task 2: Symbol → sector lookup

A real `symbol → (sector_name, etf)` map, built from `sp500.csv` + `NORMALIZE` + reversed `_ETF_NAME`. Falls back to `(None, None)` for unknown symbols (analysis then benchmarks RS against SPY).

**Files:**
- Create: `backend/app/data/sector_map.py`
- Test: `backend/tests/test_sector_map.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sector_map.py`:

```python
from app.data.sector_map import sector_for_symbol


def test_known_sp500_symbol_maps_to_sector_and_etf():
    name, etf = sector_for_symbol("MMM")   # Industrials in sp500.csv
    assert name == "Industrials"
    assert etf == "XLI"


def test_unknown_symbol_returns_none():
    name, etf = sector_for_symbol("ZZZZ_NOT_A_TICKER")
    assert name is None
    assert etf is None


def test_case_insensitive():
    name, etf = sector_for_symbol("mmm")
    assert etf == "XLI"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_sector_map.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.data.sector_map'`.

- [ ] **Step 3: Implement the lookup**

Create `backend/app/data/sector_map.py`:

```python
from __future__ import annotations

import csv
import functools
from pathlib import Path

from app.data.sector_names import NORMALIZE

_SP500_CSV = Path(__file__).parent / "sp500.csv"

# Reverse of routers.sectors._ETF_NAME: canonical sector name → ETF symbol.
_NAME_TO_ETF: dict[str, str] = {
    "Technology": "XLK",
    "Comm. Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Industrials": "XLI",
    "Financials": "XLF",
    "Consumer Staples": "XLP",
    "Health Care": "XLV",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Energy": "XLE",
}


@functools.lru_cache(maxsize=1)
def _symbol_to_raw_sector() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        with open(_SP500_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sym = (row.get("symbol") or "").strip().upper()
                sec = (row.get("sector") or "").strip()
                if sym and sec:
                    out[sym] = sec
    except FileNotFoundError:
        pass
    return out


def sector_for_symbol(symbol: str) -> tuple[str | None, str | None]:
    """Return (canonical_sector_name, sector_etf) or (None, None) if unknown."""
    raw = _symbol_to_raw_sector().get(symbol.strip().upper())
    if not raw:
        return None, None
    name = NORMALIZE.get(raw, raw)
    return name, _NAME_TO_ETF.get(name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_sector_map.py -v`
Expected: PASS (3 tests). If `sp500.csv`'s first data row symbol differs, adjust the test symbol to one present in the file (`head -5 backend/app/data/sp500.csv`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/sector_map.py backend/tests/test_sector_map.py
git commit -m "feat(analysis): symbol->sector lookup"
```

---

## Task 3: `_analyze_core` — gate-free single-symbol computation

A new function that mirrors `_process_stock`'s computation but with **no early-return gates** and an **optional** signal. Returns a dataclass the endpoint maps to `StockAnalysisOut`. The existing `_process_stock` and the scan path are NOT modified.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analyze_stock.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_analyze_core_low_score_still_returns(monkeypatch):
    """A symbol the scanner would REJECT still yields a core result + gate_flags."""
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest

    # Stub history + price so the test is deterministic & offline.
    bars = [{"time": i, "open": 100, "high": 101, "low": 99, "close": 100 + (i % 3)} for i in range(300)]

    async def _fake_bars(symbol, start, end):
        return bars

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})

    async def _fake_name(client, symbol):
        return "Test Co"

    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)

    req = StockAnalysisRequest(symbol="TEST", direction="Bullish", horizon="Swing",
                               strategy="pullback_ema")
    core = await ss._analyze_core("TEST", req)
    assert core.card is not None
    assert hasattr(core, "gate_flags")
    assert isinstance(core.gate_flags, list)
    # signal may be None (flat synthetic series → no setup); that is allowed.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py::test_analyze_core_low_score_still_returns -v`
Expected: FAIL — `module 'app.routers.stock_scan' has no attribute '_analyze_core'`.

- [ ] **Step 3: Implement `_analyze_core`**

Add to `backend/app/routers/stock_scan.py` (imports first — most already present; add the missing ones):

```python
import dataclasses
from app.scoring.stock_scorer import score_stock   # already imported at top — keep single import
```

Define the result container and the core near the other module functions:

```python
@dataclasses.dataclass
class _AnalyzeCore:
    company: str
    price: float
    card: object                      # StockScoreCard
    regime_signal: dict | None
    fundamentals: object | None       # FundamentalHealth | None
    signal: object | None             # StrategySignal | None
    bt_result: object | None
    conf_val: int | None
    conf_txt: str | None
    sector_rs_pct: float | None
    next_event_days: int | None
    next_event_label: str | None
    daily_bars: list[dict]
    gate_flags: list[dict]


async def _analyze_core(symbol: str, req: StockAnalysisRequest) -> _AnalyzeCore | None:
    """Gate-free single-symbol computation for the analysis page.

    Mirrors _process_stock's pipeline but records gate failures as advisory
    flags instead of returning early, and tolerates a missing strategy signal.
    Returns None if there is no usable price history at all.
    """
    is_index = _is_index(symbol)
    end = date.today()
    start = end - timedelta(days=_HISTORY_YEARS * 365)
    bars = await get_historical_bars(symbol, start, end)
    if not bars or len(bars) < 60:
        return None

    gate_flags: list[dict] = []

    # Price
    try:
        price_map = await asyncio.to_thread(fetch_quotes, [symbol])
    except Exception:
        price_map = {}
    quote = price_map.get(symbol)
    price = (float(quote.get("last") or 0) or None) if quote else None
    if not price:
        price = float(bars[-1]["close"]) or None
    async with httpx.AsyncClient(timeout=10) as client:
        if not price:
            price = await fetch_price_async(client, symbol)
        if not price:
            return None
        company = await fetch_company_name_async(client, symbol)

    # Price-range advisory (does not block)
    if req.min_price is not None and price < req.min_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} < min"})
    if req.max_price is not None and price > req.max_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} > max"})

    # Regime sentiment (selected horizon) — reuse the same config + services
    full_cfg = _load_full_scoring_cfg()
    rcfg = _load_regime_cfg(req.horizon)
    regime_signal = None
    if rcfg["timeframe"] == "15min":
        try:
            regime_bars = await asyncio.to_thread(fetch_intraday_candles, symbol, "15min", 55)
        except Exception:
            regime_bars = []
    else:
        regime_bars = bars
    if regime_bars and len(regime_bars) >= rcfg.get("min_obs", 10):
        omm = compute_omm([b["close"] for b in regime_bars], direction=req.direction,
                          lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"])
        if omm:
            dh = None
            try:
                dh = compute_directional_hmm(regime_bars)
            except Exception:
                pass
            regime_signal = {
                "horizon": req.horizon, "timeframe": rcfg["timeframe"], "state": omm.state,
                "p_stay": omm.p_stay, "stability": omm.stability,
                "regime_age_days": omm.regime_age_days, "avg_regime_duration": omm.avg_regime_duration,
                "conviction_pct": omm.conviction_pct, "conviction_label": omm.conviction_label,
                "interpretation": omm.interpretation, "hmm_state": dh.state if dh else None,
                "alignment": alignment(omm.state, dh.state if dh else None), "insufficient_data": False,
            }

    # Fundamentals (skip for index / intraday)
    _fh = None
    if not is_index and req.horizon.lower() != "intraday":
        fund_gate = _resolve_fundamentals_gate(req)
        if fund_gate is not None:
            _snap = await _get_fundamentals(symbol, staleness_days=fund_gate.get("staleness_days", 90))
            _fh = _score_fundamentals(_snap, req.direction, fund_gate) if _snap else None

    _regime_gate = dict(full_cfg.get("regime_gate") or {})
    card = score_stock(
        symbol=symbol, direction=req.direction, horizon=req.horizon, bars=bars[-120:],
        scoring_mode="stock", regime_signal=regime_signal,
        regime_gate=(_regime_gate or None) if regime_signal else None,
        fundamentals=_fh, fundamentals_gate=(None if is_index else _resolve_fundamentals_gate(req)),
        overrides=req.overrides,
    )
    if card.status == "REJECT":
        gate_flags.append({"gate": "score", "status": "REJECT", "detail": f"score={card.score}"})

    if regime_signal and regime_signal["conviction_pct"] <= _regime_gate.get("headwind_caution_pct", -15):
        gate_flags.append({"gate": "regime_headwind", "status": "CAUTION",
                           "detail": f"conviction {regime_signal['conviction_pct']}%"})

    # Strategy signal (optional)
    signal = None
    signal_fn = _SIGNAL_FNS.get(req.strategy)
    if signal_fn:
        signal_kwargs = _merge_strategy_params(
            req.strategy, req.direction, _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req))
        try:
            signal = signal_fn(bars[-120:], direction=req.direction, **signal_kwargs)
        except Exception:
            signal = None
    if signal is None:
        gate_flags.append({"gate": "signal", "status": "CAUTION", "detail": f"no {req.strategy} setup"})

    # Backtest + confidence (only meaningful with a signal)
    bt_result = None
    conf_val = conf_txt = None
    if signal is not None:
        _bt_key = _backtest_key(symbol, req.strategy, req.direction, bars)
        bt_result = _get_backtest_cached(_bt_key)
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, bars, strategy=req.strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate))
            _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
        if not bt_result.passes_gate:
            gate_flags.append({"gate": "backtest", "status": "CAUTION", "detail": bt_result.summary_text})
        _ck = conf_cache_key(symbol, req.direction, req.horizon)
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, atr_mult=req.confidence_atr_mult)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            set_cached(_ck, _cached)
        conf_val = _cached["confidence"]
        conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol) if conf_val is not None else None
        if conf_val is not None and req.confidence_reject_below is not None and conf_val < req.confidence_reject_below:
            gate_flags.append({"gate": "confidence", "status": "REJECT",
                               "detail": f"{conf_val:.0f}% < {req.confidence_reject_below:.0f}%"})

    # Event proximity
    next_event_days = next_event_label = None
    if quote:
        for field_name, label in [("earnings_date", "earnings"), ("ex_dividend_date", "dividend")]:
            raw = quote.get(field_name)
            if raw:
                try:
                    ev = date.fromisoformat(str(raw)[:10])
                    days = (ev - date.today()).days
                    if days >= 0 and (next_event_days is None or days < next_event_days):
                        next_event_days, next_event_label = days, label
                except (ValueError, TypeError):
                    pass

    return _AnalyzeCore(
        company=company or symbol, price=price, card=card, regime_signal=regime_signal,
        fundamentals=_fh, signal=signal, bt_result=bt_result, conf_val=conf_val, conf_txt=conf_txt,
        sector_rs_pct=None, next_event_days=next_event_days, next_event_label=next_event_label,
        daily_bars=bars, gate_flags=gate_flags,
    )
```

Add the `_is_index` helper (also used by the endpoint):

```python
_INDEX_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM", "SPX", "NDX", "VIX",
                  "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"}


def _is_index(symbol: str) -> bool:
    return symbol.upper() in _INDEX_SYMBOLS
```

Note: this code references names already imported at the top of `stock_scan.py` (`get_historical_bars`, `fetch_quotes`, `fetch_price_async`, `fetch_company_name_async`, `fetch_intraday_candles`, `compute_omm`, `compute_directional_hmm`, `alignment`, `_get_fundamentals`, `_score_fundamentals`, `_resolve_fundamentals_gate`, `compute_confidence`, `interpret`, `conf_cache_key`, `get_cached`, `set_cached`, `run_strategy_backtest`, `score_stock`, `_SIGNAL_FNS`, `_SIGNAL_KWARGS`, `_merge_strategy_params`, `_backtest_key`, `_get_backtest_cached`, `_BACKTEST_POOL`, `_BACKTEST_CACHE`, `_BACKTEST_TTL`, `_load_full_scoring_cfg`, `_load_regime_cfg`). Verify each exists; all are defined/imported in the current file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py::test_analyze_core_low_score_still_returns -v`
Expected: PASS.

- [ ] **Step 5: Run the full stock suite to confirm no regression**

Run: `cd backend && pytest tests/ -k "stock or scan" -q`
Expected: existing tests still PASS (the scan path is untouched).

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): gate-free _analyze_core"
```

---

## Task 4: `POST /api/analyze-stock` endpoint

Assembles `StockAnalysisOut` from `_analyze_core` plus EMA trend, all-three-horizon regime, sector tile + 1D/1W/1M RS, and a cheap market backdrop.

**Files:**
- Modify: `backend/app/routers/stock_scan.py`
- Test: `backend/tests/test_analyze_stock.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_analyze_stock.py`:

```python
@pytest.mark.asyncio
async def test_analyze_endpoint_offline(monkeypatch):
    from app.routers import stock_scan as ss
    from app.schemas.stock_scan import StockAnalysisRequest, StockAnalysisOut

    bars = [{"time": i, "open": 100, "high": 101, "low": 99, "close": 100 + (i % 5)} for i in range(400)]

    async def _fake_bars(symbol, start, end):
        return bars
    async def _fake_name(client, symbol):
        return "Test Co"

    monkeypatch.setattr(ss, "get_historical_bars", _fake_bars)
    monkeypatch.setattr(ss, "fetch_quotes", lambda syms: {})
    monkeypatch.setattr(ss, "fetch_company_name_async", _fake_name)
    monkeypatch.setattr(ss, "_market_backdrop", _make_async_none)

    req = StockAnalysisRequest(symbol="SPY", direction="Bullish", horizon="Swing",
                               strategy="pullback_ema")
    out = await ss.analyze_stock(req)
    assert isinstance(out, StockAnalysisOut)
    assert out.symbol == "SPY"
    assert out.is_index is True
    assert out.fundamentals is None         # index → fundamentals N/A
    assert set(out.regime_by_horizon.keys()) <= {"Intraday", "Swing", "Position"}


async def _make_async_none():
    return None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_analyze_stock.py::test_analyze_endpoint_offline -v`
Expected: FAIL — `module 'app.routers.stock_scan' has no attribute 'analyze_stock'`.

- [ ] **Step 3: Implement helpers + endpoint**

Add imports and helpers to `backend/app/routers/stock_scan.py`:

```python
from app.schemas.stock_scan import (
    StockAnalysisRequest, StockAnalysisOut, GateFlag, RuleContribution, EmaTrendOut,
    RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)
from app.data.sector_map import sector_for_symbol
from app.routers.regime import _ema as _regime_ema, compute_overall_regime


def _ema_trend(closes: list[float], period: int = 200) -> EmaTrendOut | None:
    if len(closes) < period + 1:
        return None
    ema = _regime_ema(closes, period)
    if ema is None:
        return None
    last = closes[-1]
    state = "Above" if last >= ema else "Below"
    return EmaTrendOut(state=state, ema=round(ema, 2), last=round(last, 2),
                       status="PASS" if state == "Above" else "CAUTION")


def _regime_block_for_horizon(symbol: str, bars: list[dict], horizon: str, direction: str) -> RegimeHorizonBlock:
    rcfg = _load_regime_cfg(horizon)
    if rcfg["timeframe"] == "15min":
        try:
            rbars = fetch_intraday_candles(symbol, "15min", 55)
        except Exception:
            rbars = []
    else:
        rbars = bars

    def _empty() -> RegimeHorizonBlock:
        return RegimeHorizonBlock(horizon=horizon, timeframe=rcfg["timeframe"], state="Unknown",
                                  p_stay=0.0, stability="Fragile", regime_age_days=0,
                                  avg_regime_duration=0.0, conviction_pct=0,
                                  conviction_label="Neutral", insufficient_data=True)

    if not rbars or len(rbars) < rcfg.get("min_obs", 10):
        return _empty()
    omm = compute_omm([b["close"] for b in rbars], direction=direction,
                      lookback=rcfg["lookback"], window=rcfg["window"], min_obs=rcfg["min_obs"])
    if not omm:
        return _empty()
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
        transition_row=list(omm.transition_row), insufficient_data=False)


async def _sector_context(symbol: str, closes: list[float]) -> tuple[SectorTileOut, SectorRsOut]:
    name, etf = sector_for_symbol(symbol)
    benchmark = etf or "SPY"
    end = date.today()
    start = end - timedelta(days=_HISTORY_YEARS * 365)
    try:
        bench_bars = await get_historical_bars(benchmark, start, end)
        bench = [b["close"] for b in bench_bars] if bench_bars else []
    except Exception:
        bench = []
    rs = SectorRsOut(benchmark=benchmark)
    for attr, lookback in (("d1", 1), ("w1", 5), ("m1", 21)):
        if len(closes) > lookback and len(bench) > lookback:
            s = (closes[-1] - closes[-(lookback + 1)]) / closes[-(lookback + 1)] * 100
            bm = (bench[-1] - bench[-(lookback + 1)]) / bench[-(lookback + 1)] * 100
            setattr(rs, attr, round(s - bm, 2))
    tile = SectorTileOut(name=name or "Unknown", etf=etf, change_pct=None)
    return tile, rs


async def _market_backdrop() -> MarketBackdropOut | None:
    """Cheap macro backdrop — uses compute_overall_regime() (no heavy recompute)."""
    try:
        overall = await asyncio.to_thread(compute_overall_regime)
        return MarketBackdropOut(overall=overall, direction=None, vix=None)
    except Exception:
        return None
```

Add the endpoint:

```python
@router.post("/analyze-stock")
async def analyze_stock(req: StockAnalysisRequest) -> StockAnalysisOut:
    symbol = req.symbol.upper()
    is_index = _is_index(symbol)

    core = await _analyze_core(symbol, req)
    if core is None:
        raise HTTPException(status_code=404, detail=f"No usable data for {symbol}")

    card = core.card
    closes = [b["close"] for b in core.daily_bars]

    regime_by_horizon: dict[str, RegimeHorizonBlock] = {
        h: _regime_block_for_horizon(symbol, core.daily_bars, h, req.direction)
        for h in ("Intraday", "Swing", "Position")
    }

    sector_tile, sector_rs = await _sector_context(symbol, closes)
    backdrop = await _market_backdrop()

    strategy_out = backtest_out = None
    if core.signal is not None:
        strategy_out = StrategySignalOut(
            strategy=core.signal.strategy, entry_price=core.signal.entry_price,
            stop_price=core.signal.stop_price, target_price=core.signal.target_price,
            rr_ratio=round(core.signal.rr_ratio, 2), atr=core.signal.atr, detail=core.signal.detail)
    if core.bt_result is not None:
        bt = core.bt_result
        backtest_out = BacktestOut(
            n_trades=bt.n_trades, win_rate=round(bt.win_rate, 3),
            total_return_pct=round(bt.total_return_pct, 2),
            max_drawdown_pct=round(bt.max_drawdown_pct, 2), expectancy=bt.expectancy,
            sharpe=bt.sharpe, confidence=bt.confidence, passes_gate=bt.passes_gate,
            summary_text=bt.summary_text)

    fundamentals_out = None
    if core.fundamentals is not None and not is_index:
        _fh = core.fundamentals
        fundamentals_out = FundamentalsOut(
            score=_fh.score, quality_label=_fh.quality_label, risk_label=_fh.risk_label,
            growth_score=_fh.growth_score, quality_score=_fh.quality_score,
            risk_score=_fh.risk_score, safety_flags=_fh.safety_flags, detail=_fh.detail)

    return StockAnalysisOut(
        symbol=symbol, company=core.company, price=core.price, direction=req.direction,
        stock_score=card.score, stock_status=card.status, is_index=is_index,
        strategy=strategy_out, backtest=backtest_out,
        confidence=core.conf_val, confidence_text=core.conf_txt,
        sentiment=SentimentData(**core.regime_signal) if core.regime_signal else None,
        fundamentals=fundamentals_out,
        next_event_days=core.next_event_days, next_event_label=core.next_event_label,
        rules=[RuleContribution(name=r.name, status=r.status, score=r.score, detail=r.detail or {})
               for r in card.rules],
        gate_flags=[GateFlag(**g) for g in core.gate_flags],
        ema_trend=_ema_trend(closes), iv_rank=None,
        regime_by_horizon=regime_by_horizon, sector=sector_tile, sector_rs=sector_rs,
        market_backdrop=backdrop)
```

Confirm `StrategySignalOut`, `BacktestOut`, `FundamentalsOut`, `SentimentData` are imported in `stock_scan.py` (they are — used by `_process_stock`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_analyze_stock.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Verify route registration (router already in main.py:259)**

Run: `cd backend && python -c "from app.main import create_app; app=create_app(); print([r.path for r in app.routes if 'analyze' in getattr(r,'path','')])"`
Expected: prints `['/api/analyze-stock']`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_scan.py backend/tests/test_analyze_stock.py
git commit -m "feat(analysis): POST /api/analyze-stock endpoint"
```

---

## Task 5: Frontend API client + types

**Files:**
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add response types and the client method**

In `frontend/lib/api.ts`, add these exported interfaces (define them locally — none of the underlying shapes are currently exported). Place near the other `export interface` blocks:

```typescript
export interface AnalysisStrategySignal {
  strategy: string; entry_price: number; stop_price: number; target_price: number;
  rr_ratio: number; atr: number; detail: Record<string, unknown>;
}
export interface AnalysisBacktest {
  n_trades: number; win_rate: number; total_return_pct: number; max_drawdown_pct: number;
  expectancy: number; sharpe: number; confidence: number | null; passes_gate: boolean; summary_text: string;
}
export interface AnalysisSentiment {
  horizon: string; timeframe: string; state: string; p_stay: number; stability: string;
  regime_age_days: number; avg_regime_duration: number; conviction_pct: number;
  conviction_label: string; interpretation: string; hmm_state: string | null;
  alignment: string; insufficient_data: boolean;
}
export interface AnalysisFundamentals {
  score: number; quality_label: string; risk_label: string; growth_score: number;
  quality_score: number; risk_score: number; safety_flags: string[]; detail: Record<string, unknown>;
}
export interface RuleContribution { name: string; status: 'PASS' | 'CAUTION' | 'REJECT'; score: number; detail: Record<string, unknown>; }
export interface GateFlag { gate: string; status: 'PASS' | 'CAUTION' | 'REJECT'; detail: string; }
export interface EmaTrend { state: 'Above' | 'Below'; ema: number; last: number; status: string; }
export interface RegimeHorizonBlock {
  horizon: string; timeframe: string; state: string; p_stay: number; stability: string;
  regime_age_days: number; avg_regime_duration: number; conviction_pct: number;
  conviction_label: string; hmm_state: string | null; alignment: string;
  transition_row: number[]; insufficient_data: boolean;
}
export interface SectorTileLite { name: string; etf: string | null; change_pct: number | null; }
export interface SectorRs { benchmark: string; d1: number | null; w1: number | null; m1: number | null; }
export interface MarketBackdrop { overall: string; direction: string | null; vix: number | null; }

export interface StockAnalysis {
  symbol: string; company: string; price: number; direction: string;
  stock_score: number; stock_status: 'PASS' | 'CAUTION' | 'REJECT'; is_index: boolean;
  strategy: AnalysisStrategySignal | null; backtest: AnalysisBacktest | null;
  confidence: number | null; confidence_text: string | null;
  sentiment: AnalysisSentiment | null; fundamentals: AnalysisFundamentals | null;
  next_event_days: number | null; next_event_label: string | null;
  rules: RuleContribution[]; gate_flags: GateFlag[]; ema_trend: EmaTrend | null; iv_rank: number | null;
  regime_by_horizon: Record<string, RegimeHorizonBlock>;
  sector: SectorTileLite | null; sector_rs: SectorRs | null; market_backdrop: MarketBackdrop | null;
}

export interface AnalyzeStockRequest {
  symbol: string; direction: string; horizon: 'Intraday' | 'Swing' | 'Position'; strategy: string;
  overrides?: Record<string, number | boolean | string>;
  pullback_tolerance_pct?: number; pullback_ema_period?: number; pullback_trend_ema?: number;
  pullback_ma_type?: 'EMA' | 'SMA'; pullback_require_reversal?: boolean;
  ma_crossover_fast?: number; ma_crossover_slow?: number; ma_crossover_lookback?: number;
  breakout_volume_mult?: number; rsi_period?: number; rsi_oversold?: number; rsi_trend_sma?: number;
}
```

Add the method inside the `api` object (e.g. after `getNews`, line 142):

```typescript
  analyzeStock: (req: AnalyzeStockRequest) => post<StockAnalysis>('/api/analyze-stock', req),
```

- [ ] **Step 2: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat(analysis): analyzeStock api client + types"
```

---

## Task 6: Analysis Zustand store (with horizon-label mapping)

**Files:**
- Create: `frontend/lib/analysisStore.ts`
- Test: `frontend/lib/__tests__/analysisStore.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/__tests__/analysisStore.test.ts`:

```typescript
import { useAnalysisStore, _horizonEnum } from '@/lib/analysisStore';
import { api } from '@/lib/api';

jest.mock('@/lib/api', () => ({ api: { analyzeStock: jest.fn() } }));

describe('analysisStore', () => {
  beforeEach(() => {
    useAnalysisStore.setState({ symbol: '', result: null, loading: false, error: null });
    (api.analyzeStock as jest.Mock).mockReset();
  });

  it('maps display horizon labels to the backend enum', () => {
    expect(_horizonEnum('Swing (5–15d)')).toBe('Swing');
    expect(_horizonEnum('Position (1–6m)')).toBe('Position');
    expect(_horizonEnum('Intraday')).toBe('Intraday');
    expect(_horizonEnum('weird')).toBe('Swing');   // safe default
  });

  it('sets result on success and uppercases symbol', async () => {
    (api.analyzeStock as jest.Mock).mockResolvedValue({ symbol: 'AMD', stock_score: 55 });
    await useAnalysisStore.getState().analyze('amd');
    const s = useAnalysisStore.getState();
    expect((api.analyzeStock as jest.Mock).mock.calls[0][0].symbol).toBe('AMD');
    expect(s.result?.stock_score).toBe(55);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('sets error on failure', async () => {
    (api.analyzeStock as jest.Mock).mockRejectedValue(new Error('404: No usable data for ZZZZ'));
    await useAnalysisStore.getState().analyze('ZZZZ');
    const s = useAnalysisStore.getState();
    expect(s.result).toBeNull();
    expect(s.error).toContain('No usable data');
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

export type HorizonEnum = 'Intraday' | 'Swing' | 'Position';

/** ScanContext.horizon is a display label like "Swing (5–15d)" — map to the backend enum. */
export function _horizonEnum(label: string | undefined): HorizonEnum {
  const l = (label ?? '').toLowerCase();
  if (l.startsWith('intraday')) return 'Intraday';
  if (l.startsWith('position')) return 'Position';
  return 'Swing';
}

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
        horizon: _horizonEnum(ctx?.horizon),
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

Confirm `scanParamsStore` exposes the field names used (`pullbackTolerancePct`, `pullbackEmaPeriod`, `pullbackTrendEma`, `pullbackMaType`, `maCrossoverFast`, `maCrossoverSlow`, `maCrossoverLookback`, `breakoutVolumeMult`, `rsiPeriod`, `rsiOversold`, `rsiTrendSma`) — these are the same fields `step-4-stocks/page.tsx` reads (lines 79-83). If any differ, adjust.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- --testPathPattern=analysisStore`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/analysisStore.ts frontend/lib/__tests__/analysisStore.test.ts
git commit -m "feat(analysis): analysisStore with horizon mapping"
```

---

## Task 7: Add Analysis nav item

**Files:**
- Modify: `frontend/components/organisms/NavItems/index.tsx`

- [ ] **Step 1: Add the nav item**

In `frontend/components/organisms/NavItems/index.tsx`, add to the `ITEMS` array after the `Screener` entry (line 18):

```typescript
  { label: 'Analysis',  match: '/analysis',  href: '/analysis',  Icon: AnalysisIcon },
```

- [ ] **Step 2: Add the icon**

In the same file's icon section (after `ScreenerIcon`, near line 87), add an `AnalysisIcon` following the existing inline-SVG pattern used by the other icons (match their `viewBox`, `stroke`, `fill` conventions — copy the shape of `ScreenerIcon` and change the path):

```tsx
function AnalysisIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 3v18h18" />
      <path d="M7 14l3-3 3 3 4-5" />
    </svg>
  );
}
```

Adjust attributes to match the existing icons exactly if they differ (check `ScreenerIcon`'s SVG attributes first).

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/organisms/NavItems/index.tsx
git commit -m "feat(analysis): add Analysis nav item"
```

---

## Task 8: Analysis page — search, header, regime context

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

- [ ] **Step 2: Create the page with search + header + regime context**

Create `frontend/app/(frame)/analysis/page.tsx`:

```tsx
'use client';

import { useState } from 'react';
import { Title, Text, Data } from '@/components/primitives';
import { StatusBadge } from '@/components/atoms/StatusBadge';
import { useAnalysisStore } from '@/lib/analysisStore';
import styles from './page.module.css';

export default function AnalysisPage() {
  const { result, loading, error, analyze } = useAnalysisStore();
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
            <StatusBadge status={result.stock_status} />
            <span className={styles.dirPill}>{result.direction}</span>
            {result.market_backdrop && (
              <span className={styles.backdropChip}>Market: {result.market_backdrop.overall}</span>
            )}
          </div>

          <div className={styles.contextRow}>
            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">EMA / IV</Text>
              {result.ema_trend ? (
                <Data size={14} tone={result.ema_trend.state === 'Above' ? 'pass' : 'caution'}>
                  {result.ema_trend.state} 200-EMA
                </Data>
              ) : <Text size={12} tone="dim">N/A</Text>}
              <Text size={11} tone="secondary">
                IV rank: {result.iv_rank != null ? result.iv_rank.toFixed(0) : (result.is_index ? 'N/A' : '—')}
              </Text>
            </article>

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Market sentiment</Text>
              {result.sentiment ? (
                <Data size={14} tone={result.sentiment.conviction_pct >= 0 ? 'pass' : 'reject'}>
                  {result.sentiment.conviction_label} ({result.sentiment.conviction_pct > 0 ? '+' : ''}{result.sentiment.conviction_pct}%)
                </Data>
              ) : <Text size={12} tone="dim">—</Text>}
            </article>

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

            <article className={styles.ctxCard}>
              <Text size={11} tone="dim">Sector</Text>
              <Data size={13}>{result.sector?.name ?? 'Unknown'}</Data>
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
              {result.sector_rs && (
                <Text size={10} tone="dim">vs {result.sector_rs.benchmark}</Text>
              )}
            </article>
          </div>

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

Create `frontend/app/(frame)/analysis/page.module.css`:

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
.headerStrip {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px;
}
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
git commit -m "feat(analysis): page search + header + regime context"
```

---

## Task 9: Analysis page — chart, score row, gate flags, score cards, news

**Files:**
- Modify: `frontend/app/(frame)/analysis/page.tsx`
- Modify: `frontend/app/(frame)/analysis/page.module.css`

- [ ] **Step 1: Add candle + news fetching and the lower regions**

Update the imports at the top of `page.tsx`:

```tsx
import { useState, useEffect } from 'react';
import type { Candle } from '@/types/chart';
import type { NewsItem } from '@/types/domain';
import { api } from '@/lib/api';
import { CandlestickChart } from '@/components/organisms/CandlestickChart';
```

Inside `AnalysisPage`, above the `return`, add:

```tsx
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
        api.getNews(['SPY', 'QQQ']),   // general market news
      ]);
      if (!cancelled) { setCandles(c); setStockNews(sn); setMarketNews(mn); }
    } catch { /* non-fatal */ }
  })();
  return () => { cancelled = true; };
}, [result?.symbol]);

// Per-component weights for the score-breakdown cards (matches stock-mode HORIZON_WEIGHTS).
const HORIZON_WEIGHTS: Record<string, Record<string, number>> = {
  Intraday: { trend: 35, pullback: 20, trigger: 30, event: 5, vol: 10 },
  Swing:    { trend: 30, pullback: 20, trigger: 25, event: 15, vol: 10 },
  Position: { trend: 30, pullback: 20, trigger: 20, event: 20, vol: 10 },
};
```

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

          {/* Per-component score breakdown */}
          {result.rules.length > 0 && (
            <div className={styles.scoreCards}>
              {result.rules.map((r) => {
                const w = HORIZON_WEIGHTS[result.regime_by_horizon ? 'Swing' : 'Swing'][r.name] ?? 0;
                const tone = r.status === 'PASS' ? 'pass' : r.status === 'CAUTION' ? 'caution' : 'reject';
                return (
                  <article key={r.name} className={styles.scoreCard}>
                    <Text size={12} weight={500}>{r.name}</Text>
                    <Data size={14} tone={tone}>{r.score}/100</Data>
                    <Text size={11} tone="dim">weight {w}% · {((r.score * w) / 100).toFixed(1)} pts</Text>
                  </article>
                );
              })}
            </div>
          )}

          {/* News */}
          <div className={styles.newsRegion}>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>{result.symbol} news</Text>
              {stockNews.length === 0 && <Text size={11} tone="dim">No headlines.</Text>}
              {stockNews.map((n) => (
                <Text key={n.id} size={12} tone="secondary">{n.headline}</Text>
              ))}
            </div>
            <div className={styles.newsCol}>
              <Text size={12} weight={500}>Market news</Text>
              {marketNews.length === 0 && <Text size={11} tone="dim">No headlines.</Text>}
              {marketNews.map((n) => (
                <Text key={n.id} size={12} tone="secondary">{n.headline}</Text>
              ))}
            </div>
          </div>
```

Note: the weight lookup uses a fixed `'Swing'` map for simplicity. If you want it to follow the active horizon, derive the horizon from `useAnalysisStore`/`scanStore` and index `HORIZON_WEIGHTS[horizon]`. `r.name` values are `trend|pullback|trigger|event|vol` (per `RuleResult` comment). `NewsItem` has `headline` (no URL) — render as text, not a link.

Confirm `CandlestickChart` props: `data: Candle[]`, `height?: number | 'auto'`, `defaultIndicators?: IndicatorType[]` where `IndicatorType` includes `'volume' | 'rsi' | 'macd'` (CandlestickChart/index.tsx). If `IndicatorType` is exported and strict, import it; otherwise the string literals satisfy it.

- [ ] **Step 2: Add CSS for the new regions**

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
.scoreCards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.scoreCard {
  display: flex; flex-direction: column; gap: 4px; padding: 12px;
  border: 1px solid var(--border-subtle); border-radius: 8px;
}
.newsRegion { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.newsCol {
  display: flex; flex-direction: column; gap: 6px;
  padding: 12px; border: 1px solid var(--border-subtle); border-radius: 8px;
}
```

- [ ] **Step 3: Verify typecheck + store test**

Run: `cd frontend && npm run typecheck`
Expected: clean.
Run: `cd frontend && npm run test -- --testPathPattern=analysisStore`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add "frontend/app/(frame)/analysis"
git commit -m "feat(analysis): chart, score row, gate flags, score cards, news"
```

---

## Task 10: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Backend full suite**

Run: `cd backend && pytest tests/ -q`
Expected: no new failures vs. baseline (run `git stash` baseline comparison if unsure).

- [ ] **Step 2: Live endpoint smoke (requires backend running + network)**

Start backend, then:
Run: `curl -s -X POST localhost:8000/api/analyze-stock -H "Content-Type: application/json" -d '{"symbol":"AMD","direction":"Bullish","horizon":"Swing","strategy":"pullback_ema"}' | python -m json.tool | head -40`
Expected: JSON with `symbol`, `stock_score`, `regime_by_horizon` (3 keys), `gate_flags`, `rules` (5 entries), `sector`, `sector_rs`.

Run: `curl -s -X POST localhost:8000/api/analyze-stock -H "Content-Type: application/json" -d '{"symbol":"SPY","direction":"Bullish","horizon":"Swing","strategy":"pullback_ema"}' | python -m json.tool | grep -E "is_index|fundamentals"`
Expected: `"is_index": true`, `"fundamentals": null`.

Run: `curl -s -o /dev/null -w "%{http_code}" -X POST localhost:8000/api/analyze-stock -H "Content-Type: application/json" -d '{"symbol":"ZZZZNOPE"}'`
Expected: `404`.

- [ ] **Step 3: Frontend checks**

Run: `cd frontend && npm run typecheck && npm run test -- --testPathPattern=analysisStore`
Expected: clean + PASS.

- [ ] **Step 4: Manual smoke (preview)**

Start `npm run dev`, open `/analysis`. Search `AMD` → header strip, 4 context cards, 3 regime cards, chart, score row, gate flags (if any), 5 score cards, news columns. Search `SPY` → fundamentals/IV show N/A, `is_index` behaviour. Search junk → inline "No usable data" error.

- [ ] **Step 5: Final commit (if cleanups)**

```bash
git add -A
git commit -m "chore(analysis): verification cleanups"
```
