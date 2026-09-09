from __future__ import annotations

import asyncio
import concurrent.futures
import dataclasses
import functools
import hashlib
import logging
import math
import os
import time
from collections.abc import Callable
from decimal import Decimal
from datetime import datetime, timezone, date, timedelta
from pathlib import Path as _Path
from typing import Any, Literal, Optional

import httpx
import yaml as _yaml
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.models.scan_session import ScanSession

from app.services.audit import new_rec_id
from app.schemas.stock_scan import (
    StockScanRequest, StockScanResult, PositionCardOut,
    StrategySignalOut, BacktestOut, StockPipeline, StockAnalysisRequest,
    StockAnalysisOut, GateFlag, RuleContribution, EmaTrendOut,
    RegimeHorizonBlock, SectorTileOut, SectorRsOut, MarketBackdropOut,
)
from app.data.sector_map import sector_for_symbol
from app.routers.regime import _ema as _regime_ema, compute_overall_regime
from app.schemas import SentimentData, ScanSessionStatus
from app.data.market import (
    fetch_company_name_async, fetch_price_async, fetch_quotes, fetch_intraday_candles,
    fetch_candles_async,
)
from app.services.historical_store import get_bars as get_historical_bars
# _atr is the SAME ATR(14) /contracts/exit-plan uses (contracts.py imports it
# from here too) -- not strategy_engine's same-named one, which is a different
# implementation. The two endpoints must build their ATR floor on one number.
from app.scoring.stock_scorer import score_stock, _atr
from app.services.strategy_engine import (
    pullback_ema_signal, breakout_base_signal,
    ma_crossover_signal, mean_reversion_rsi_signal,
    mean_reversion_bb_signal,
    mean_reversion_vwap_signal,
    mean_reversion_vwap_daily_signal,
    breakout_setup_signal,
    resolve_multi_signal,
)
from app.services.strategy_backtest import run_strategy_backtest
from app.services.strategy_param_store import get_active, get_costs, get_exit
from app.data.confidence_cache import cache_key as conf_cache_key, get_cached, set_cached
from app.scoring.signal_confidence import compute_confidence, interpret, load_backtest_cfg
from app.scoring.first_passage import estimate_stock_first_passage
# compute_final_stop / compute_target_row take candles, a direction, a price
# and config -- no contract input, and never had one. /stocks/exit-plan calls
# the SAME two functions with the SAME arguments as /contracts/exit-plan; that
# is what makes the stock plan the options plan minus the premium half rather
# than a second implementation of it.
from app.scoring.exit_plan import compute_final_stop, compute_target_row
from app.services.config_loader import (
    load_first_passage_cfg as _fp_cfg, load_exit_plan_cfg,
)
# _load_config is lru_cached AND cache_cleared by POST /settings/risk, so the
# risk budget below follows a saved settings change without a restart. A
# private-name import is deliberate: adding a public wrapper would be a second
# door onto one cache that the settings route would then have to know about.
from app.services import portfolio_risk
# Reused rather than redeclared: the stock estimate's invalidation block is an
# exact shape match for the option one, and two copies would drift apart.
# No cycle — contracts.py does not import this module.
from app.routers.contracts import FirstPassageInvalidationOut
from app.services.regime_omm import compute_omm
from app.services.regime_hmm_daily import compute_directional_hmm, alignment
from app.services.fundamentals_store import get_fundamentals as _get_fundamentals
from app.scoring.fundamentals_scorer import score_fundamentals as _score_fundamentals, FundamentalHealth
from app.schemas import FundamentalsOut
from app.services.fundamentals_gate import resolve_fundamentals_gate as _resolve_fundamentals_gate
from app.data.universe_presets import expand_universe, PresetUnavailableError


class PreBreakoutScanRequest(BaseModel):
    symbols: list[str] = []
    universe: list[str] | None = None   # e.g. ["SP500"] or ["SECTOR:XLK"] or individual tickers
    direction: str = "Bullish"
    params_override: dict | None = None


class PreBreakoutResult(BaseModel):
    symbol: str
    confidence: int
    direction: str
    metrics: dict


_SCORING_CFG = _Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"

_ALLOWED_OVERRIDE_KEYS = frozenset({
    "atr_compression_ratio",
    "atr_avg_lookback",
    "range_atr_mult",
    "range_lookback_bars",
    "vol_compression_ratio",
    "resistance_proximity_pct",
    "swing_lookback",
    "require_trend",
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


@functools.lru_cache(maxsize=1)
def _load_full_scoring_cfg() -> dict:
    return _yaml.safe_load(_SCORING_CFG.read_text())


def _load_regime_cfg(horizon: str) -> dict:
    return _load_full_scoring_cfg()["regime"][horizon.lower()]


def _conviction_mult(conviction_pct: int, sizing: dict) -> float:
    if not sizing.get("enabled", False):
        return 1.0
    full = sizing["full_conviction_pct"]
    lo = sizing["min_mult"]
    frac = max(0.0, min(conviction_pct / full, 1.0)) if full else 0.0
    return lo + (1.0 - lo) * frac

router = APIRouter(prefix="/api", tags=["stock-scan"])
logger = logging.getLogger(__name__)

_SIGNAL_FNS = {
    "pullback_ema":              pullback_ema_signal,
    "breakout_base":             breakout_base_signal,
    "ma_crossover":              ma_crossover_signal,
    "mean_reversion_rsi":        mean_reversion_rsi_signal,
    "mean_reversion_bb":         mean_reversion_bb_signal,
    "mean_reversion_vwap":       mean_reversion_vwap_signal,
    "mean_reversion_vwap_daily": mean_reversion_vwap_daily_signal,
}

# Strategies that require intraday (15m) bars instead of daily bars for signal + backtest.
_INTRADAY_STRATEGIES = frozenset({"mean_reversion_vwap"})

_SIGNAL_KWARGS: dict[str, Callable[[StockScanRequest], dict[str, Any]]] = {
    "pullback_ema":          lambda r: {"tolerance": r.pullback_tolerance_pct, "ema_period": r.pullback_ema_period, "trend_ema": r.pullback_trend_ema, "ma_type": r.pullback_ma_type, "require_reversal": r.pullback_require_reversal},
    "breakout_base":         lambda r: {"volume_mult": r.breakout_volume_mult},
    "ma_crossover":          lambda r: {"fast": r.ma_crossover_fast, "slow": r.ma_crossover_slow, "lookback": r.ma_crossover_lookback},
    "mean_reversion_rsi":    lambda r: {"rsi_period": r.rsi_period, "rsi_oversold": r.rsi_oversold, "rsi_overbought": getattr(r, "rsi_overbought", 70.0), "trend_sma": r.rsi_trend_sma, "require_choppy_regime": r.require_choppy_regime},
    "mean_reversion_vwap":   lambda r: {"interval": "15m"},
    "mean_reversion_bb":  lambda r: {"require_choppy_regime": r.require_choppy_regime},
}

def _backtest_commission() -> float:
    """Per-leg cost drag sourced from the same strategy_params.yaml `costs`
    block the WFO tuner (strategy_param_optimizer.py) already uses — keeps
    the Step-6 trader-facing backtest gate cost-aware instead of the
    commission-free number it showed before (2026-08-18 audit finding)."""
    costs = get_costs()
    return costs.get("fee_pct", 0.001) + costs.get("slippage_pct", 0.001)


def _merge_strategy_params(strategy: str, direction: str, request_kwargs: dict) -> dict:
    """Exit policy, then adopted defaults for this direction, then per-request kwargs.

    Precedence is deliberately exit < active < request: the exit block is a
    baseline the tuner may later override into `active:` (WFO's adopt() writes
    there), and an explicit per-scan override always wins over both.

    Note this widens `_backtest_key`'s inputs — `_bt_params` is part of the
    backtest cache key — so every cached BacktestResult is invalidated the first
    time this ships. That is correct: the exits genuinely changed.
    """
    merged = get_exit(strategy)
    merged.update(get_active(strategy, direction))
    merged.update({k: v for k, v in request_kwargs.items() if v is not None})
    return merged


_HISTORY_YEARS = 5
_SCAN_SEM = asyncio.Semaphore(5)

_BACKTEST_TTL = 24 * 3600  # daily — bar history doesn't change within a trading day
_BACKTEST_CACHE: dict[str, tuple] = {}  # key → (BacktestResult, expires_at)
_BACKTEST_POOL = concurrent.futures.ProcessPoolExecutor(
    max_workers=max(1, (os.cpu_count() or 2) // 2)
)

_last_stock_request: StockScanRequest | None = None
_last_stock_result: StockScanResult | None = None
_last_stock_status: str = "idle"
_last_stock_updated_at: str | None = None


async def _upsert_stock_session(
    db: AsyncSession,
    req: StockScanRequest | None,
    result: StockScanResult | None,
    status: str = "complete",
) -> None:
    """Persist the last stocks-mode scan to the same scan_sessions table the
    options-mode scan uses, under a distinct id so the two never collide.

    Single place that reassigns the in-memory "last stock scan" globals, so
    `status`/`strategy` (sourced from `_last_stock_request`) always stay in
    sync with each other at every write, including the running/idle writes
    from run_stock_scan() below — not just the final completed write."""
    global _last_stock_request, _last_stock_result, _last_stock_status, _last_stock_updated_at
    await db.merge(
        ScanSession(
            id="stock-current",
            status=status,
            last_result_json=result.model_dump_json() if result else None,
            last_request_json=req.model_dump_json() if req else None,
        )
    )
    await db.commit()
    _last_stock_request = req
    _last_stock_result = result
    _last_stock_status = status
    _last_stock_updated_at = datetime.now(timezone.utc).isoformat()


async def restore_stock_from_db() -> None:
    """Restore _last_stock_result from DB on startup — mirrors scan.py's restore_from_db()."""
    global _last_stock_request, _last_stock_result, _last_stock_status, _last_stock_updated_at
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(ScanSession).where(ScanSession.id == "stock-current"))
        except Exception:
            # Table may not exist (e.g., test_app.py with no DB)
            return
        row = result.scalar_one_or_none()
        if row is None:
            return
        if row.last_result_json:
            _last_stock_result = StockScanResult.model_validate_json(row.last_result_json)
        if row.last_request_json:
            _last_stock_request = StockScanRequest.model_validate_json(row.last_request_json)
        # A restored "running" status means the process was killed mid-scan
        # (OOM, container restart) — unlike options mode's continuous-scan
        # scheduler, no in-flight stock-scan request can survive a restart
        # to resume it, so treat it as idle rather than reporting a scan
        # that will never finish as permanently "running".
        _last_stock_status = row.status if row.status != "running" else "idle"
        _last_stock_updated_at = row.updated_at.isoformat() if row.updated_at else None


def _backtest_key(symbol: str, strategy: str, direction: str, bars: list[dict], params: dict | None = None,
                   commission: float = 0.0) -> str:
    bars_hash = hashlib.md5(
        str([(b["time"], b["close"]) for b in bars[-20:]]).encode()
    ).hexdigest()[:8]
    params_hash = hashlib.md5(str(sorted((params or {}).items())).encode()).hexdigest()[:8]
    # commission is folded into the key (not just the run_strategy_backtest call)
    # so that editing strategy_params.yaml's costs.fee_pct/slippage_pct doesn't
    # leave a stale pre-edit BacktestResult (including passes_gate) served out of
    # _BACKTEST_CACHE for up to _BACKTEST_TTL (24h) under an unchanged key.
    return f"{symbol.upper()}|{strategy}|{direction.lower()}|{bars_hash}|{params_hash}|{commission:.6f}"


def _get_backtest_cached(key: str):
    entry = _BACKTEST_CACHE.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


_INDEX_SYMBOLS = {"SPY", "QQQ", "DIA", "IWM", "SPX", "NDX", "VIX",
                  "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"}


def _is_index(symbol: str) -> bool:
    return symbol.upper() in _INDEX_SYMBOLS


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
    intraday_bars: list[dict]
    gate_flags: list[dict]


async def _analyze_core(symbol: str, req: "StockAnalysisRequest") -> "_AnalyzeCore | None":
    """Gate-free single-symbol computation for the analysis page."""
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

    # Price-range advisory
    if req.min_price is not None and price < req.min_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} < min"})
    if req.max_price is not None and price > req.max_price:
        gate_flags.append({"gate": "price", "status": "REJECT", "detail": f"price ${price:.2f} > max"})

    # Always fetch intraday bars — the analysis page shows all three horizon blocks
    # (Intraday / Swing / Position) regardless of req.horizon, so we always need them.
    try:
        _intraday_bars = await asyncio.to_thread(fetch_intraday_candles, symbol, "15min", 80)
    except Exception:
        _intraday_bars = []

    full_cfg = _load_full_scoring_cfg()
    rcfg = _load_regime_cfg(req.horizon)
    regime_signal = None
    regime_bars = _intraday_bars if rcfg["timeframe"] == "15min" else bars
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
                "interpretation": omm.interpretation or "", "hmm_state": dh.state if dh else None,
                "alignment": alignment(omm.state, dh.state if dh else None), "insufficient_data": False,
            }

    # Fundamentals — the gate already carries the bearish cautionAbove/rejectAbove
    # overrides (applied once in services/fundamentals_gate.resolve_fundamentals_gate);
    # no per-site re-application here. Note: if the YAML fundamentals_gate block is
    # ever removed, the resolver returns {} and scoring would run on all-default cfg
    # instead of being skipped — acceptable, documented.
    fund_gate = None if is_index else _resolve_fundamentals_gate(req)
    _fh = None
    if fund_gate is not None and req.horizon.lower() != "intraday":
        _snap = await _get_fundamentals(symbol, staleness_days=fund_gate.get("staleness_days", 90))
        _fh = _score_fundamentals(_snap, req.direction, fund_gate) if _snap else None

    _regime_gate = dict(full_cfg.get("regime_gate") or {})
    card = score_stock(
        symbol=symbol, direction=req.direction, horizon=req.horizon, bars=bars[-120:],
        scoring_mode="stock", regime_signal=regime_signal,
        regime_gate=(_regime_gate or None) if regime_signal else None,
        fundamentals=_fh, fundamentals_gate=fund_gate,
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
        _sig_bars = (_intraday_bars[-300:] if req.strategy in _INTRADAY_STRATEGIES
                     else bars[-120:])
        # Pass live price so signal uses current price, not yesterday's close.
        _live_price = price if req.strategy not in _INTRADAY_STRATEGIES else None
        try:
            signal = signal_fn(_sig_bars, direction=req.direction,
                               current_price=_live_price, **signal_kwargs)
        except Exception:
            signal = None
    if signal is None:
        gate_flags.append({"gate": "signal", "status": "CAUTION", "detail": f"no {req.strategy} setup"})

    # Backtest + confidence
    bt_result = None
    conf_val = conf_txt = None
    if signal is not None:
        _bt_bars = _intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
        _bt_commission = _backtest_commission()
        _bt_key = _backtest_key(symbol, req.strategy, req.direction, _bt_bars, signal_kwargs,
                                 commission=_bt_commission)
        bt_result = _get_backtest_cached(_bt_key)
        if bt_result is None:
            bt_result = await asyncio.get_running_loop().run_in_executor(
                _BACKTEST_POOL,
                functools.partial(run_strategy_backtest, _bt_bars, strategy=req.strategy,
                                  direction=req.direction, min_trades=req.bt_min_trades,
                                  min_win_rate=req.bt_min_win_rate, params=signal_kwargs,
                                  commission=_bt_commission))
            _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
        if not bt_result.passes_gate:
            gate_flags.append({"gate": "backtest", "status": "CAUTION", "detail": bt_result.summary_text})
        # Asymmetric ATR override — a lone target or stop is ignored (both or neither).
        _atr_target = req.confidence_atr_mult_target
        _atr_stop = req.confidence_atr_mult_stop
        if _atr_target is None or _atr_stop is None:
            _atr_target = _atr_stop = None
        _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_target, _atr_stop, scoring_mode="stock")
        _cached = get_cached(_ck)
        if _cached is None:
            _res = await asyncio.to_thread(compute_confidence, bars, direction=req.direction,
                                           horizon=req.horizon, scoring_mode="stock",
                                           atr_mult_target=_atr_target, atr_mult_stop=_atr_stop)
            _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
            await set_cached(_ck, _cached)
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
        daily_bars=bars, intraday_bars=_intraday_bars, gate_flags=gate_flags,
    )


def _ema_trend(closes: list[float], period: int = 200) -> "EmaTrendOut | None":
    if len(closes) < period + 1:
        return None
    ema = _regime_ema(closes, period)
    if ema is None:
        return None
    last = closes[-1]
    state = "Above" if last >= ema else "Below"
    return EmaTrendOut(state=state, ema=round(ema, 2), last=round(last, 2),
                       status="PASS" if state == "Above" else "CAUTION")


def _regime_block_for_horizon(
    symbol: str,
    bars: list[dict],
    horizon: str,
    direction: str,
    intraday_bars: list[dict] | None = None,
) -> "RegimeHorizonBlock":
    rcfg = _load_regime_cfg(horizon)
    if rcfg["timeframe"] == "15min":
        # Use pre-loaded bars when provided to avoid blocking the event loop.
        rbars = intraday_bars if intraday_bars is not None else []
    else:
        rbars = bars

    def _empty() -> "RegimeHorizonBlock":
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
        transition_row=list(omm.transition_row),
        state_order=list(omm.state_order),
        insufficient_data=False)


async def _sector_context(symbol: str, closes: list[float]) -> "tuple[SectorTileOut, SectorRsOut]":
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


async def _market_backdrop() -> "MarketBackdropOut | None":
    """Cheap macro backdrop — uses compute_overall_regime() (no heavy recompute)."""
    try:
        overall = await asyncio.to_thread(compute_overall_regime)
        return MarketBackdropOut(overall=overall, direction=None, vix=None)
    except Exception:
        return None


@router.post("/analyze-stock")
async def analyze_stock(req: StockAnalysisRequest) -> StockAnalysisOut:
    symbol = req.symbol.upper()
    is_index = _is_index(symbol)

    core = await _analyze_core(symbol, req)
    if core is None:
        raise HTTPException(status_code=404, detail=f"No usable data for {symbol}")

    card = core.card
    closes = [b["close"] for b in core.daily_bars]

    # Intraday bars already fetched inside _analyze_core — reuse to avoid a second call.
    intraday_bars = core.intraday_bars

    # Run all three regime blocks + sector context + backdrop concurrently,
    # each CPU-bound block in a thread so the event loop stays free.
    (intra_blk, swing_blk, pos_blk), (sector_tile, sector_rs), backdrop = await asyncio.gather(
        asyncio.gather(
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Intraday", req.direction, intraday_bars),
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Swing",    req.direction, None),
            asyncio.to_thread(_regime_block_for_horizon, symbol, core.daily_bars, "Position", req.direction, None),
        ),
        _sector_context(symbol, closes),
        _market_backdrop(),
    )
    regime_by_horizon: dict[str, RegimeHorizonBlock] = {
        "Intraday": intra_blk, "Swing": swing_blk, "Position": pos_blk,
    }

    strategy_out = backtest_out = None
    if core.signal is not None:
        strategy_out = StrategySignalOut(
            strategy=core.signal.strategy, entry_price=core.signal.entry_price,
            stop_price=core.signal.stop_price, target_price=core.signal.target_price,
            targets=list(core.signal.targets),
            rr_ratio=round(core.signal.rr_ratio, 2), atr=core.signal.atr, detail=core.signal.detail)
    if core.bt_result is not None:
        bt = core.bt_result
        backtest_out = BacktestOut(
            n_trades=bt.n_trades, win_rate=round(bt.win_rate, 3),
            total_return_pct=round(bt.total_return_pct, 2),
            max_drawdown_pct=round(bt.max_drawdown_pct, 2), expectancy=bt.expectancy,
            sharpe=bt.sharpe, confidence=getattr(bt, 'confidence', None), passes_gate=bt.passes_gate,
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


def _position_size(account: float, risk_pct: float | None, risk_fixed: float | None,
                   entry: float, stop: float) -> tuple[int, float]:
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0, 0.0
    dollar_risk = risk_fixed if risk_fixed else (account * (risk_pct or 0.01))
    shares = max(1, int(dollar_risk / risk_per_share))
    return shares, round(dollar_risk, 2)


async def _process_stock(
    symbol: str,
    req: StockScanRequest,
    scan_id: str,
    price_map: dict[str, dict],
    benchmark_closes: list[float],
    fund_gate: dict | None = None,
) -> PositionCardOut | dict:
    async with _SCAN_SEM:
        try:
            end = date.today()
            start = end - timedelta(days=_HISTORY_YEARS * 365)
            # DB-first: reads from ohlcv_daily table; fetches delta from Tiingo if stale.
            # Eliminates parallel Tiingo calls for large universes (avoids rate-limit errors).
            bars = await get_historical_bars(symbol, start, end)
            if not bars or len(bars) < 60:
                return {"symbol": symbol, "reason": "insufficient history"}

            # For intraday strategies, fetch 15m bars used for signal + backtest.
            intraday_bars: list[dict] = []
            if req.strategy in _INTRADAY_STRATEGIES:
                try:
                    intraday_bars = await asyncio.to_thread(
                        fetch_intraday_candles, symbol, "15min", 55
                    )
                except Exception as exc:
                    logger.warning("fetch_intraday_candles failed for %s: %s", symbol, exc)
                if len(intraday_bars) < 30:
                    return {"symbol": symbol, "reason": "insufficient intraday history"}

            # Price fallback chain mirrors the options scan: Tradier batch quote →
            # last stored close (history table) → yfinance. Keeps the stock track
            # usable when Tradier is unavailable.
            quote = price_map.get(symbol)
            price = (float(quote.get("last") or 0) or None) if quote else None
            if not price:
                price = float(bars[-1]["close"]) or None

            async with httpx.AsyncClient(timeout=10) as client:
                if not price:
                    price = await fetch_price_async(client, symbol)
                if not price:
                    return {"symbol": symbol, "reason": "no price data"}
                company = await fetch_company_name_async(client, symbol)

            if req.min_price is not None and price < req.min_price:
                return {"symbol": symbol, "reason": f"price ${price:.2f} < min"}
            if req.max_price is not None and price > req.max_price:
                return {"symbol": symbol, "reason": f"price ${price:.2f} > max"}

            # --- regime sentiment ---
            full_cfg = _load_full_scoring_cfg()
            rcfg = _load_regime_cfg(req.horizon)
            regime_signal = None
            if rcfg["timeframe"] == "15min":
                try:
                    regime_bars = await asyncio.to_thread(
                        fetch_intraday_candles, symbol, "15min", 55
                    )
                except Exception as exc:
                    logger.warning("fetch_intraday_candles failed for %s: %s", symbol, exc)
                    regime_bars = []
            else:
                regime_bars = bars   # daily bars already fetched

            if regime_bars and len(regime_bars) >= rcfg.get("min_obs", 10):
                omm = compute_omm(
                    [b["close"] for b in regime_bars],
                    direction=req.direction,
                    lookback=rcfg["lookback"],
                    window=rcfg["window"],
                    min_obs=rcfg["min_obs"],
                )
                if omm:
                    dh = None
                    try:
                        dh = compute_directional_hmm(regime_bars)
                    except Exception as exc:
                        logger.debug("HMM unavailable for %s: %s", symbol, exc)
                    regime_signal = {
                        "horizon": req.horizon,
                        "timeframe": rcfg["timeframe"],
                        "state": omm.state,
                        "p_stay": omm.p_stay,
                        "stability": omm.stability,
                        "regime_age_days": omm.regime_age_days,
                        "avg_regime_duration": omm.avg_regime_duration,
                        "conviction_pct": omm.conviction_pct,
                        "conviction_label": omm.conviction_label,
                        "interpretation": omm.interpretation,
                        "hmm_state": dh.state if dh else None,
                        "alignment": alignment(omm.state, dh.state if dh else None),
                        "insufficient_data": False,
                    }

            # Fundamentals (skipped for intraday) — the gate already carries the
            # bearish overrides from services/fundamentals_gate.resolve_fundamentals_gate
            # (see the matching note in _analyze_core); no per-site re-application.

            _fh: FundamentalHealth | None = None
            if req.horizon.lower() != "intraday" and fund_gate is not None:
                _staleness = fund_gate.get("staleness_days", 90)
                _snap = await _get_fundamentals(symbol, staleness_days=_staleness)
                _fh = _score_fundamentals(_snap, req.direction, fund_gate) if _snap else None

            _regime_gate = dict(full_cfg.get("regime_gate") or {})
            if req.regime_headwind_caution_pct is not None:
                _regime_gate["headwind_caution_pct"] = req.regime_headwind_caution_pct
            if req.regime_headwind_reject_pct is not None:
                _regime_gate["headwind_reject_pct"] = req.regime_headwind_reject_pct

            card = score_stock(
                symbol=symbol,
                direction=req.direction,
                horizon=req.horizon,
                bars=bars[-120:],
                scoring_mode="stock",
                regime_signal=regime_signal,
                regime_gate=(_regime_gate or None) if regime_signal else None,
                fundamentals=_fh,
                fundamentals_gate=fund_gate,
                overrides=req.overrides,
            )
            if card.status == "REJECT":
                return {"symbol": symbol, "reason": f"REJECT score={card.score}"}

            # Direction conviction filter (Swing/Position only)
            if req.horizon != "Intraday":
                _trend_score = next((r.score for r in card.rules if r.name == "trend"), 50)
                if req.direction == "Bearish":
                    _max_trend = 40 if req.horizon == "Position" else 50
                    if _trend_score > _max_trend:
                        return {"symbol": symbol, "reason": f"direction_conviction: trend {_trend_score} > {_max_trend} for Bearish {req.horizon}"}
                elif req.direction == "Bullish":
                    _min_trend = 40 if req.horizon == "Position" else 30
                    if _trend_score < _min_trend:
                        return {"symbol": symbol, "reason": f"direction_conviction: trend {_trend_score} < {_min_trend} for Bullish {req.horizon}"}

            if req.regime_filter and regime_signal and \
               regime_signal["conviction_pct"] <= _regime_gate.get("headwind_caution_pct", -15):
                return {"symbol": symbol, "reason": "regime headwind"}

            if req.strategy == "mean_reversion_multi":
                valid_variants = [v for v in req.mean_reversion_variants if v in _SIGNAL_FNS]
                fired: list = []
                for variant in valid_variants:
                    fn = _SIGNAL_FNS[variant]
                    if variant == "mean_reversion_vwap_daily":
                        extra_kw = {"vwap_lookback": req.vwap_lookback, "vwap_deviation_pct": req.vwap_deviation_pct}
                    else:
                        extra_kw = {}
                    variant_kwargs = _merge_strategy_params(
                        variant, req.direction,
                        {**_SIGNAL_KWARGS.get(variant, lambda r: {})(req), **extra_kw},
                    )
                    try:
                        sig = fn(bars[-120:], direction=req.direction, **variant_kwargs)
                    except Exception:
                        sig = None
                    if sig is not None:
                        fired.append(sig)
                if len(fired) < req.mean_reversion_min_confirmations:
                    return {"symbol": symbol, "reason": f"no mean_reversion_multi: {len(fired)}/{len(valid_variants)} signals fired"}
                # Order-independent resolution: widest stop, tightest target,
                # pooled ladder. Previously this took fired[0]'s levels verbatim,
                # so reordering the variant checkboxes changed every level.
                signal = resolve_multi_signal(fired, strategy="mean_reversion_multi")
                if signal is None:
                    return {"symbol": symbol, "reason": "mean_reversion_multi: variants produced no valid combined levels"}
                # Use RSI as canonical backtest proxy for multi-signal — deterministic regardless of fired order
                _bt_strategy = "mean_reversion_rsi"
                bt_bars = bars
                _bt_params = _merge_strategy_params(
                    "mean_reversion_rsi", req.direction,
                    _SIGNAL_KWARGS.get("mean_reversion_rsi", lambda r: {})(req),
                )
            else:
                signal_fn = _SIGNAL_FNS.get(req.strategy)
                if not signal_fn:
                    return {"symbol": symbol, "reason": f"unknown strategy {req.strategy}"}
                signal_kwargs = _merge_strategy_params(
                    req.strategy, req.direction,
                    _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req),
                )
                # Intraday strategies use intraday bars for both signal and backtest.
                signal_bars = intraday_bars[-300:] if req.strategy in _INTRADAY_STRATEGIES else bars[-120:]
                _live_price = price if req.strategy not in _INTRADAY_STRATEGIES else None
                signal = signal_fn(signal_bars, direction=req.direction,
                                   current_price=_live_price, **signal_kwargs)
                if signal is None:
                    return {"symbol": symbol, "reason": f"no {req.strategy} setup"}
                _bt_strategy = req.strategy
                bt_bars = intraday_bars if req.strategy in _INTRADAY_STRATEGIES else bars
                _bt_params = signal_kwargs

            _bt_commission = _backtest_commission()
            _bt_key = _backtest_key(symbol, _bt_strategy, req.direction, bt_bars, _bt_params,
                                     commission=_bt_commission)
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bt_bars,
                        strategy=_bt_strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                        params=_bt_params, commission=_bt_commission,
                    ),
                )
                _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
            if not bt_result.passes_gate:
                return {"symbol": symbol, "reason": f"backtest gate: {bt_result.summary_text}"}

            # Asymmetric ATR override — a lone target or stop is ignored (both or neither).
            _atr_target = req.confidence_atr_mult_target
            _atr_stop = req.confidence_atr_mult_stop
            if _atr_target is None or _atr_stop is None:
                _atr_target = _atr_stop = None
            _ck = conf_cache_key(symbol, req.direction, req.horizon, _atr_target, _atr_stop, scoring_mode="stock")
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon,
                    scoring_mode="stock", atr_mult_target=_atr_target, atr_mult_stop=_atr_stop,
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                await set_cached(_ck, _cached)
            conf_val = _cached["confidence"]
            conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol) if conf_val is not None else None

            _SEVERITY = {"PASS": 0, "CAUTION": 1, "REJECT": 2}

            if conf_val is not None and req.confidence_reject_below is not None:
                if conf_val < req.confidence_reject_below:
                    return {
                        "symbol": symbol,
                        "reason": (
                            f"confidence gate REJECT: {conf_val:.0f}% "
                            f"< {req.confidence_reject_below:.0f}%"
                        ),
                    }
            if conf_val is not None and req.confidence_caution_below is not None:
                if conf_val < req.confidence_caution_below:
                    if _SEVERITY.get(card.status, 0) < _SEVERITY["CAUTION"]:
                        card = dataclasses.replace(card, status="CAUTION")

            sizing_cfg = full_cfg.get("regime_sizing", {"enabled": False})
            mult = _conviction_mult(regime_signal["conviction_pct"], sizing_cfg) if regime_signal else 1.0
            sized_risk_pct = (req.risk_pct * mult) if req.risk_pct is not None else None
            sized_risk_fixed = (req.risk_fixed_usd * mult) if req.risk_fixed_usd is not None else None
            shares, dollar_risk = _position_size(
                req.account_size, sized_risk_pct, sized_risk_fixed,
                signal.entry_price, signal.stop_price,
            )

            # Sector RS vs benchmark
            horizon_period = {"Intraday": 2, "Swing": 20, "Position": 50}.get(req.horizon, 20)
            stock_closes_all = [b["close"] for b in bars]
            sector_rs_pct: float | None = None
            if len(stock_closes_all) > horizon_period and len(benchmark_closes) > horizon_period:
                stock_roc = (stock_closes_all[-1] - stock_closes_all[-(horizon_period + 1)]) / stock_closes_all[-(horizon_period + 1)] * 100
                bench_roc = (benchmark_closes[-1] - benchmark_closes[-(horizon_period + 1)]) / benchmark_closes[-(horizon_period + 1)] * 100
                sector_rs_pct = round(stock_roc - bench_roc, 2)

            # Event proximity from quote data
            next_event_days: int | None = None
            next_event_label: str | None = None
            if quote:
                for field_name, label in [("earnings_date", "earnings"), ("ex_dividend_date", "dividend")]:
                    raw = quote.get(field_name)
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
                symbol=symbol, company=company or symbol, price=price, direction=req.direction,
                strategy=StrategySignalOut(
                    strategy=signal.strategy, entry_price=signal.entry_price,
                    stop_price=signal.stop_price, target_price=signal.target_price,
                    targets=list(signal.targets),
                    rr_ratio=round(signal.rr_ratio, 2), atr=signal.atr, detail=signal.detail,
                ),
                backtest=BacktestOut(
                    n_trades=bt_result.n_trades, win_rate=round(bt_result.win_rate, 3),
                    total_return_pct=round(bt_result.total_return_pct, 2),
                    max_drawdown_pct=round(bt_result.max_drawdown_pct, 2),
                    expectancy=bt_result.expectancy, sharpe=bt_result.sharpe,
                    confidence=bt_result.confidence, passes_gate=bt_result.passes_gate,
                    summary_text=bt_result.summary_text,
                ),
                stock_score=card.score, stock_status=card.status,
                shares=shares, dollar_risk=dollar_risk,
                dollar_size=round(shares * signal.entry_price, 2),
                confidence=conf_val, confidence_text=conf_txt,
                sector_rs_pct=sector_rs_pct,
                next_event_days=next_event_days, next_event_label=next_event_label,
                sentiment=SentimentData(**regime_signal) if regime_signal else None,
                fundamentals=FundamentalsOut(
                    score=_fh.score, quality_label=_fh.quality_label, risk_label=_fh.risk_label,
                    growth_score=_fh.growth_score, quality_score=_fh.quality_score,
                    risk_score=_fh.risk_score, safety_flags=_fh.safety_flags, detail=_fh.detail,
                ) if _fh else None,
            )
        except Exception as exc:
            logger.exception("Error processing %s", symbol)
            return {"symbol": symbol, "reason": str(exc)}


@router.get('/stock-scan/last', response_model=StockScanResult | None)
async def get_last_stock_scan() -> StockScanResult | None:
    """Return the most recently completed stocks-mode scan, if any."""
    return _last_stock_result


@router.get('/stock-scan/last-run', response_model=ScanSessionStatus)
async def get_last_stock_scan_status() -> ScanSessionStatus:
    """Return last-run metadata (status/timestamp/strategy) for stock-mode scans."""
    return ScanSessionStatus(
        status=_last_stock_status,
        updated_at=_last_stock_updated_at,
        strategy=_last_stock_request.strategy if _last_stock_request else None,
    )


@router.post("/stock-scan")
async def run_stock_scan(req: StockScanRequest, db: AsyncSession = Depends(get_db)) -> StockScanResult:
    # mean_reversion_multi's per-variant loop (in _process_stock) always calls
    # each variant on DAILY `bars`, unlike the single-strategy path, which
    # correctly special-cases _INTRADAY_STRATEGIES to fetch and use 15m bars.
    # "mean_reversion_vwap" (the intraday variant, NOT "_daily") is not itself
    # in _INTRADAY_STRATEGIES either, so nothing routes intraday bars into the
    # multi-signal loop for it. A third independent audit round found this
    # would silently run the intraday variant's VWAP/ATR/entry-gate math on
    # daily candles mislabeled as 15-minute bars — no error, just quietly
    # wrong numbers with a plausible shape. Not reachable through the shipped
    # UI today (MeanReversionConfirmPanel only offers rsi/bb/vwap_daily), but
    # rejected here rather than left as a live API footgun for the next
    # caller (a future feature, a test, a script) that adds it.
    if req.strategy == "mean_reversion_multi" and "mean_reversion_vwap" in req.mean_reversion_variants:
        raise HTTPException(
            status_code=422,
            detail="mean_reversion_vwap (intraday) is not supported in mean_reversion_multi — "
                   "its variant loop only evaluates daily bars. Use mean_reversion_vwap_daily instead.",
        )
    # NOTE: nothing serializes overlapping requests to this endpoint (unlike
    # scan.py's run_scan(), _SCAN_SEM above only throttles per-symbol work
    # inside _process_stock, not the endpoint itself) — two concurrent
    # POST /api/stock-scan calls race on the single shared "stock-current"
    # row/globals below (e.g. one request's failure-triggered idle-revert
    # could clobber another's genuine in-flight/completed state). Accepted as
    # a low-probability edge case given this app is single-user and the UI
    # only issues one stock scan at a time, rather than engineered around
    # with a lock/sequence-token.
    _prev_request, _prev_result, _prev_status = _last_stock_request, _last_stock_result, _last_stock_status
    await _upsert_stock_session(db, req=req, result=_prev_result, status="running")

    try:
        result = await _execute_stock_scan_core(req, db, previous_result=_prev_result)
        await _upsert_stock_session(db, req, result, status="complete")
        return result
    except Exception:
        # Revert to the request/result/status that were current before THIS
        # attempt started (not `req`/"idle" unconditionally) — otherwise a
        # scan that fails right after a genuinely completed one would
        # mislabel that still-valid prior result as "idle" instead of
        # "complete". `_prev_status` is "idle" only when there really was no
        # prior scan (module default / a fresh DB). Manual-run-only: Part 3's
        # scheduled runner never touches this global slot at all, so this
        # revert dance doesn't apply there — see _execute_stock_scan_core.
        await _upsert_stock_session(db, req=_prev_request, result=_prev_result, status=_prev_status)
        raise


async def _execute_stock_scan_core(
    req: StockScanRequest, db: AsyncSession, *, previous_result: StockScanResult | None = None,
) -> StockScanResult:
    """The actual stock-scan-running logic — same body run_stock_scan() has
    always run through result construction, with NO write to
    `_last_stock_request`/`_last_stock_result`/`_last_stock_status` (that
    happens in `_upsert_stock_session`, called only by run_stock_scan() and
    Part 3's scheduled runner after this returns, never from inside here).

    `previous_result` is accepted for signature symmetry with the
    options-mode core (_execute_scan_core) — Part 3's scheduled runner passes
    each entry's own prior successful result — but is unused internally
    today: unlike options mode, stock-mode scans compute no rank/score
    deltas (StockScanResult carries no `deltas` field), so there is nothing
    here to compute against it yet."""
    scan_id = new_rec_id()
    # Deliberately NOT hoisted to the module-level import at line 57 — tests
    # patch `app.data.universe_presets.expand_universe` (not
    # `app.routers.stock_scan.expand_universe`), which only takes effect if
    # this name is re-resolved from the source module at call time.
    from app.data.universe_presets import expand_universe, PresetUnavailableError

    if req.symbols:
        symbols = req.symbols
    else:
        try:
            symbols = expand_universe(req.universe)
        except PresetUnavailableError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Pre-fetch all prices in one Tradier call (removes 519 individual HTTP requests)
    try:
        price_map = await asyncio.to_thread(fetch_quotes, symbols)
    except Exception as exc:
        logger.warning("stock_scan: batch price fetch failed (%s) — falling back to empty map", exc)
        price_map = {}

    # Fetch SPY closes once for sector RS calculation
    benchmark_closes: list[float] = []
    try:
        spy_end = date.today()
        spy_start = spy_end - timedelta(days=_HISTORY_YEARS * 365)
        spy_bars = await get_historical_bars("SPY", spy_start, spy_end)
        benchmark_closes = [b["close"] for b in spy_bars] if spy_bars else []
    except Exception:
        pass   # RS column shows None — non-fatal

    fund_gate = _resolve_fundamentals_gate(req)
    tasks = [_process_stock(s, req, scan_id, price_map, benchmark_closes, fund_gate=fund_gate) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates, rejected = [], []
    for r in results:
        if isinstance(r, Exception):
            rejected.append({"symbol": "unknown", "reason": str(r)})
        elif isinstance(r, PositionCardOut):
            candidates.append(r)
        else:
            rejected.append(r)

    original_count = len(candidates)
    shortlist_truncated = original_count > req.shortlist_max_candidates
    candidates = candidates[: req.shortlist_max_candidates]

    _direction_banner: str | None = None
    _side = "short-side" if req.direction == "Bearish" else "long-side"
    _dir_filtered = sum(
        1 for r in rejected
        if isinstance(r, dict) and r.get("reason", "").startswith("direction_conviction:")
    )
    if not candidates and _dir_filtered > 0:
        _direction_banner = (
            f"No confirmed {req.direction.lower()} setups in this universe. "
            f"All candidates were removed — market structure does not support {_side} entries."
        )
    elif candidates and all(c.stock_status == "CAUTION" for c in candidates):
        _direction_banner = (
            f"No strong {req.direction.lower()} setups detected. "
            "All candidates are CAUTION-grade — consider reducing size or waiting for a clearer signal."
        )

    _hist_kw = ("insufficient history", "no price data")
    _pipeline = StockPipeline(
        scanned=len(symbols),
        failed_history=sum(
            1 for r in rejected
            if isinstance(r, dict) and (
                any(k in r.get("reason", "") for k in _hist_kw)
                or r.get("reason", "").startswith("price $")
            )
        ),
        failed_score=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason", "").startswith("REJECT score=")
        ),
        failed_signal=sum(
            1 for r in rejected
            if isinstance(r, dict)
            and r.get("reason", "").startswith("no ")
            and "setup" in r.get("reason", "")
        ),
        failed_backtest=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason", "").startswith("backtest gate:")
        ),
        failed_regime=sum(
            1 for r in rejected
            if isinstance(r, dict) and r.get("reason") == "regime headwind"
        ),
        other_rejected=sum(
            1 for r in rejected
            if isinstance(r, dict)
            and not any(k in r.get("reason", "") for k in _hist_kw)
            and not r.get("reason", "").startswith("price $")
            and not r.get("reason", "").startswith("REJECT score=")
            and not (r.get("reason", "").startswith("no ") and "setup" in r.get("reason", ""))
            and not r.get("reason", "").startswith("backtest gate:")
            and r.get("reason") != "regime headwind"
        ),
        candidates=len(candidates),
    )
    logger.info(
        "STOCK SCAN pipeline: scanned=%d hist_fail=%d score_fail=%d signal_fail=%d bt_fail=%d regime_fail=%d other=%d candidates=%d",
        _pipeline.scanned, _pipeline.failed_history, _pipeline.failed_score,
        _pipeline.failed_signal, _pipeline.failed_backtest, _pipeline.failed_regime, _pipeline.other_rejected, _pipeline.candidates,
    )
    result = StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
        original_count=original_count, shortlist_truncated=shortlist_truncated,
        direction_banner=_direction_banner,
    )
    return result


_FIB_ALLOWED_OVERRIDE_KEYS = frozenset({
    "fib_swing_lookback",
    "fib_levels",
    "fib_tolerance_pct",
    "impulse_min_pct",
    "retracement_recency_bars",
    "ema_filter_period",
})
_FIB_INT_OVERRIDE_KEYS = frozenset({"fib_swing_lookback", "retracement_recency_bars", "ema_filter_period"})

_FIB_DEFAULTS = {
    "fib_swing_lookback": 100,
    "fib_levels": [38.2, 61.8],
    "fib_tolerance_pct": 0.015,
    "impulse_min_pct": 0.08,
    "retracement_recency_bars": 40,
    "ema_filter_period": 20,
}


class FibPullbackScanRequest(BaseModel):
    symbols: list[str] = []
    direction: Literal["Bullish", "Bearish"] = "Bullish"
    params_override: dict | None = None
    universe: list[str] | None = None


@router.post("/scan/fib-pullback")
async def fib_pullback_scan(body: FibPullbackScanRequest) -> list[dict]:
    """Scan symbols for Fibonacci retracement setups using fibonacci_pullback_signal."""
    from app.services.strategy_engine import fibonacci_pullback_signal

    end = date.today()
    start = end - timedelta(days=365)

    if body.universe:
        try:
            symbols_to_scan = expand_universe(body.universe)
        except PresetUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

    if not symbols_to_scan:
        return []

    scan_params: dict = dict(_FIB_DEFAULTS)
    if body.params_override:
        unknown = set(body.params_override) - _FIB_ALLOWED_OVERRIDE_KEYS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown override keys: {sorted(unknown)}")
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _FIB_INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
                if k == "fib_swing_lookback" and coerced[k] < 10:
                    raise HTTPException(status_code=422, detail="fib_swing_lookback must be >= 10")
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                if len(v) == 0:
                    raise HTTPException(status_code=422, detail="fib_levels must contain at least one level")
                _VALID_FIB_LEVELS = {23.6, 38.2, 50.0, 61.8, 78.6}
                parsed_levels = [float(x) for x in v]
                invalid_levels = [x for x in parsed_levels if x not in _VALID_FIB_LEVELS]
                if invalid_levels:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid fib_levels values: {invalid_levels}. Allowed: {sorted(_VALID_FIB_LEVELS)}",
                    )
                coerced[k] = parsed_levels
            else:
                try:
                    coerced[k] = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be a number")
                if k == "fib_tolerance_pct" and not (0 < coerced[k] <= 0.20):
                    raise HTTPException(status_code=422, detail="fib_tolerance_pct must be between 0 (exclusive) and 0.20")
                if k == "impulse_min_pct" and not (0.0 <= coerced[k] <= 0.50):
                    raise HTTPException(status_code=422, detail="impulse_min_pct must be between 0 and 0.50")
        scan_params.update(coerced)

    results: list[dict] = []
    for sym in symbols_to_scan:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            bars = await get_historical_bars(sym, start, end)
        except Exception as exc:
            logger.warning("fib-pullback scan: get_bars failed for %s — %s", sym, exc)
            continue
        if not bars:
            continue
        try:
            at_level, dist_pct, level_hit = fibonacci_pullback_signal(
                bars,
                body.direction,
                fib_swing_lookback=scan_params["fib_swing_lookback"],
                fib_levels=scan_params["fib_levels"],
                fib_tolerance_pct=scan_params["fib_tolerance_pct"],
                impulse_min_pct=scan_params["impulse_min_pct"],
                retracement_recency_bars=scan_params["retracement_recency_bars"],
            )
        except Exception as exc:
            logger.warning("fib-pullback scan: signal failed for %s — %s", sym, exc)
            continue
        if level_hit is None:
            # Insufficient bars or no swing found — skip
            continue

        # EMA trend filter: price must be on the correct side of the EMA.
        # Bullish: close > EMA; Bearish: close < EMA. 0 disables.
        ema_period = int(scan_params["ema_filter_period"])
        if ema_period > 0 and len(bars) >= ema_period:
            closes = [b["close"] for b in bars]
            k = 2 / (ema_period + 1)
            ema_val = sum(closes[:ema_period]) / ema_period
            for c in closes[ema_period:]:
                ema_val = c * k + ema_val * (1 - k)
            current_close = closes[-1]
            if body.direction == "Bullish" and current_close < ema_val:
                continue
            if body.direction == "Bearish" and current_close > ema_val:
                continue

        # Confidence: 100 if at level, scaled by proximity otherwise
        tol = scan_params["fib_tolerance_pct"] * 100  # convert to pct units
        if dist_pct is None:
            confidence = 0
        elif at_level:
            confidence = max(60, round(100 - (dist_pct / tol) * 40))
        else:
            confidence = max(0, round(60 - ((dist_pct - tol) / tol) * 30))
        results.append({
            "symbol": sym,
            "direction": body.direction,
            "fib_level_hit": level_hit,
            "fib_dist_pct": dist_pct,
            "at_level": at_level,
            "confidence": confidence,
        })

    # Sort: at-level hits first, then by proximity ascending (closer = better rank).
    results.sort(key=lambda r: (
        not r["at_level"],  # False (0) = at-level → sorts first
        r["fib_dist_pct"] if r["fib_dist_pct"] is not None else float("inf"),
    ))
    return results


@router.post("/scan/prebreakout")
async def prebreakout_scan(body: PreBreakoutScanRequest) -> list[dict]:
    """Scan symbols for pre-breakout consolidation setups using breakout_setup_signal."""
    end = date.today()
    start = end - timedelta(days=365)

    # Resolve symbol list: universe takes precedence over manual symbols list
    if body.universe:
        try:
            symbols_to_scan = expand_universe(body.universe)
        except PresetUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        symbols_to_scan = [s.strip().upper() for s in body.symbols if s.strip()]

    if not symbols_to_scan:
        return []

    base_params = get_active("breakout_setup", body.direction)
    if body.params_override:
        unknown = set(body.params_override) - _ALLOWED_OVERRIDE_KEYS
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown override keys: {sorted(unknown)}")
        # Coerce params to their expected types
        coerced: dict = {}
        for k, v in body.params_override.items():
            if k in _INT_OVERRIDE_KEYS:
                try:
                    coerced[k] = int(v)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"Override key '{k}' must be an integer")
            elif k in ("fib_enabled", "require_trend"):
                coerced[k] = bool(v)
            elif k == "fib_levels":
                if not isinstance(v, list):
                    raise HTTPException(status_code=422, detail="fib_levels must be a list of numbers")
                coerced[k] = [float(x) for x in v]
            else:
                coerced[k] = float(v) if isinstance(v, (int, float)) else v
        base_params.update(coerced)

    results: list[dict] = []
    for sym in symbols_to_scan:
        sym = sym.strip().upper()
        if not sym:
            continue
        try:
            bars = await get_historical_bars(sym, start, end)
        except Exception as exc:
            logger.warning("prebreakout scan: get_bars failed for %s — %s", sym, exc)
            continue
        if not bars:
            continue
        try:
            signal = breakout_setup_signal(bars, sym, direction=body.direction, **base_params)
        except Exception as exc:
            logger.warning("prebreakout scan: signal failed for %s — %s", sym, exc)
            continue
        if signal is None:
            continue
        results.append({
            "symbol": sym,
            "confidence": signal.confidence,
            "direction": signal.direction,
            "metrics": signal.metrics,
        })

    results.sort(key=lambda r: r["confidence"], reverse=True)
    return results


# ── Stock first-passage (Approach B) ──────────────────────────────────────────

class StockFirstPassageRequest(BaseModel):
    symbol:       str
    direction:    Literal["Bullish", "Bearish"]
    horizon:      Literal["Intraday", "Swing", "Position"]
    strategy:     str
    stock_price:  float = Field(..., gt=0)
    stop_price:   float = Field(..., gt=0)
    targets:      list[float] = Field(..., min_length=1, max_length=5)
    trend_score:  float = Field(..., ge=0, le=100)


class StockFirstPassageTargetOut(BaseModel):
    price:        float
    probability:  float
    expectedDays: Optional[float] = None


class StockFirstPassageResponse(BaseModel):
    targets:      list[StockFirstPassageTargetOut]
    invalidation: FirstPassageInvalidationOut
    horizonDays:  int
    #: Non-null when the GBM model is a poor fit for this strategy; the card
    #: renders it verbatim. See the plan's "GBM caveat" decision — labelled, not
    #: suppressed, and decided HERE (next to the model) rather than in the UI so
    #: the rule lives in exactly one place.
    modelCaveat:  Optional[str] = None


#: Surfaced whenever the requested strategy's thesis contradicts the estimator's
#: generative model. Kept as a module constant so the endpoint test can assert on
#: the exact string the user sees rather than a substring guess.
_MEAN_REVERSION_CAVEAT = (
    "Approximate for mean-reversion strategies: this model assumes a constant "
    "drift from the trend score, while a mean-reversion trade's thesis is that "
    "the recent drift is transient. Treat the target probabilities as a rough "
    "upper bound; the stop probability is less affected."
)

#: mean_reversion_vwap's signal and backtest run on 15m intraday bars — its
#: thesis is a same-day reversion — but this estimator always simulates daily
#: closes over `horizon_days` TRADING days (see fetch_candles_async below,
#: unconditional on strategy). The sigma/drift inputs describe a slower,
#: coarser process than the one the strategy actually trades, on top of the
#: mean-reversion mismatch above.
_INTRADAY_MEAN_REVERSION_CAVEAT = (
    _MEAN_REVERSION_CAVEAT + " It also simulates daily closes, not the "
    "intraday moves this strategy's signal and backtest are based on, so "
    "treat the probabilities as an even rougher guide than for other "
    "mean-reversion strategies."
)


def _model_caveat_for(strategy: Optional[str]) -> Optional[str]:
    """The one place the "is the GBM a fair model for this strategy?" rule lives.

    Extracted when /stocks/exit-plan arrived, because it reports probabilities
    from the SAME estimator over the SAME paths: two copies of this rule would
    eventually caption one card and not the other for the same number, which is
    worse than no caption at all. `None` strategy (the exit plan's request makes
    it optional — the arithmetic plan stands on its own without one) returns no
    caveat, same as any non-mean-reversion strategy.
    """
    if not strategy:
        return None
    if strategy in _INTRADAY_STRATEGIES:
        return _INTRADAY_MEAN_REVERSION_CAVEAT
    if strategy.startswith("mean_reversion"):
        return _MEAN_REVERSION_CAVEAT
    return None


@router.post('/stocks/first-passage', response_model=StockFirstPassageResponse)
async def stock_first_passage(req: StockFirstPassageRequest) -> StockFirstPassageResponse:
    """On-demand Monte Carlo first-passage estimate for a stock position's exit
    ladder: probability and expected TRADING days to reach each target, and to
    hit the stop, within this horizon's holding window.

    Fired only by the stock position card's "Estimate" button — never by the scan
    — for the same latency reasons as the options `/contracts/first-passage`.
    The holding window comes from scoring_rules.yaml's
    `confidence_backtest.<horizon>.n_days`, this app's existing definition of how
    long a signal in that horizon takes to resolve.
    """
    # The GBM first-passage model assumes a stop below entry and targets above
    # it (Bullish) or the mirror (Bearish). A target already on the wrong side
    # of entry isn't a valid exit ladder — it's already "hit," which is what
    # silently produced a bogus ~100% probability instead of a real error.
    if req.direction == "Bullish":
        if req.stop_price >= req.stock_price:
            raise HTTPException(status_code=422, detail="stop_price must be below stock_price for a Bullish position")
        if any(t <= req.stock_price for t in req.targets):
            raise HTTPException(status_code=422, detail="all targets must be above stock_price for a Bullish position")
    else:
        if req.stop_price <= req.stock_price:
            raise HTTPException(status_code=422, detail="stop_price must be above stock_price for a Bearish position")
        if any(t >= req.stock_price for t in req.targets):
            raise HTTPException(status_code=422, detail="all targets must be below stock_price for a Bearish position")

    fp_cfg = _fp_cfg()
    try:
        horizon_days = int(load_backtest_cfg(req.horizon)["n_days"])
    except (KeyError, TypeError, ValueError):
        horizon_days = 10   # Swing default; never fail the request over config shape

    async with httpx.AsyncClient(timeout=10) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # Deterministic per-request seed, same construction and same reasoning as
    # contracts.py's: identical inputs return an identical answer instead of
    # visible Monte Carlo noise on repeated presses, while genuinely different
    # inputs still draw independently. sha256, not hash() — the latter is salted
    # per process (PYTHONHASHSEED) and so is not stable across restarts/workers.
    seed_key = (f"{req.symbol.upper()}|{req.direction}|{req.horizon}|"
                f"{round(req.stock_price, 2)}|{round(req.stop_price, 2)}|"
                f"{','.join(f'{t:.2f}' for t in req.targets)}")
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    # CPU-bound NumPy over n_paths simulated paths. asyncio.to_thread keeps it off
    # the event loop, matching how this module already offloads compute_confidence
    # and fetch_intraday_candles. NOT _BACKTEST_POOL — that is a process pool
    # sized for the backtester, and this work is far too small to justify pickling.
    result = await asyncio.to_thread(
        functools.partial(
            estimate_stock_first_passage,
            stock_price=req.stock_price,
            direction=req.direction,
            trend_score=req.trend_score,
            stop_price=req.stop_price,
            targets=req.targets,
            candles=candles,
            horizon_days=horizon_days,
            max_drift_pct=fp_cfg["max_drift_pct"],
            n_paths=fp_cfg["n_paths"],
            sigma_floor=fp_cfg["sigma_floor"],
            sigma_ceiling=fp_cfg["sigma_ceiling"],
            seed=seed,
        )
    )

    caveat = _model_caveat_for(req.strategy)

    return StockFirstPassageResponse(
        targets=[
            StockFirstPassageTargetOut(
                price=round(t.price, 2),
                probability=round(t.probability, 4),
                expectedDays=t.expected_days,
            )
            for t in result.targets
        ],
        invalidation=FirstPassageInvalidationOut(
            probability=round(result.invalidation.probability, 4),
            expectedDays=result.invalidation.expected_days,
        ),
        horizonDays=result.horizon_days,
        modelCaveat=caveat,
    )


# ── POST /stocks/exit-plan ────────────────────────────────────────────────────
#
# Piece 6, "the stocks arithmetic plan" (docs/superpowers/plans/
# 2026-09-02-piece-6-stocks-arithmetic-plan-spec.md). The options exit-plan
# pipeline with the whole premium half removed:
#
#   compute_final_stop   -> survives verbatim (it never took a contract)
#   compute_target_row   -> survives verbatim (same)
#   estimate_rr          -> DROPPED (it reprices a contract)
#   estimate_first_passage -> replaced by estimate_stock_first_passage
#   stop-vs-premium gate -> DROPPED
#
# THERE IS NO STOCKS STOP-COST GATE, and this is a decision, not an omission.
# The options gate answers "what share of the premium does the stop cost?", a
# question that exists only because an option can be near-worthless before the
# stock reaches the stop. A stock has no such nonlinearity: a 5% stop costs 5%,
# exactly, and `recommendedShares` below already turns that into the only
# protection it needs. A badge that looked like the options one but answered a
# different question is the specific thing spec section 1 forbids.
#
# Its own endpoint rather than a branch of /contracts/exit-plan because that one
# requires strike > 0, dte and premium > 0 — none of which a stock has.


class StockExitPlanRequest(BaseModel):
    symbol:      str
    direction:   Literal["Bullish", "Bearish"]
    entry_price: float = Field(..., gt=0)
    trend_score: float = Field(..., ge=0, le=100)
    #: Picks the holding window the probabilities are measured over, via
    #: scoring_rules.yaml's confidence_backtest.<horizon>.n_days.
    horizon:     Literal["Intraday", "Swing", "Position"]
    #: Only ever used to caption the probabilities with the GBM model caveat —
    #: the arithmetic plan itself does not depend on which strategy found the
    #: candidate, so it is optional.
    strategy:    Optional[str] = None
    #: None -> risk_rules.yaml's exit_plan.target.rr_ratios.
    rr_ratios:   Optional[list[float]] = Field(default=None, min_length=1, max_length=5)

    @field_validator("rr_ratios")
    @classmethod
    def _positive_finite_ratios(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        # An R:R of 0 puts the target ON the entry price and a negative one puts
        # it on the losing side — both would render as a "profit target" that is
        # nothing of the kind. Pydantic's gt= cannot reach inside a list.
        if v is None:
            return v
        for r in v:
            if not math.isfinite(r) or r <= 0:
                raise ValueError("rr_ratios must all be finite and greater than 0")
        return v


class StockExitPlanStopOut(BaseModel):
    price:                float
    source:               Literal["structural", "atr_widened"]
    structuralSource:     Optional[Literal["order_block", "swing_low", "swing_high"]] = None
    structuralConfidence: Optional[int] = None
    structuralPrice:      Optional[float] = None
    atrFloorPrice:        float
    distanceDollar:       Optional[float] = None
    #: |entry - stop|. THE WHOLE "cost of the stop" for a stock, exactly and
    #: without a model — which is why there is no gate above it.
    riskPerShare:         float
    probability:          float
    expectedDays:         Optional[float] = None


class StockExitPlanTargetRowOut(BaseModel):
    rrRatio:         float
    arithmeticPrice: float
    price:           float
    tpSource:        Literal["arithmetic", "structural_snap"]
    structuralPrice: Optional[float] = None
    distanceDollar:  Optional[float] = None   # |structural - arithmetic|
    toleranceDollar: float                    # the snap band
    rewardPerShare:  float                    # |target - entry|
    probability:     float
    expectedDays:    Optional[float] = None
    qualityGood:     bool
    qualityReasons:  list[str]


class StockRaceOutcomeOut(BaseModel):
    """One target's row of the two-barrier stock race (spec section 5).

    Three probabilities that sum to exactly 100% because every simulated path is
    assigned to exactly one of them — unlike `stop.probability` and
    `targets[].probability`, which are each measured on their own and routinely
    sum past 100% (a path can touch both barriers).
    """
    targetPrice:    float
    pTargetFirst:   float
    pStopFirst:     float
    pNeither:       float
    daysTarget:     Optional[float] = None   # CONDITIONAL median: paths where the target won
    daysStop:       Optional[float] = None   # CONDITIONAL median: paths where the stop won
    #: Allocated to hundredths so the three ALWAYS sum to exactly 1.00. The card
    #: prints these; the raw p* above are what any bar is drawn from. One
    #: rounding rule, one implementation — see _allocated_weights.
    weightTarget:   float
    weightStop:     float
    weightNeither:  float
    #: Mean price at the end of the window over the pNeither paths. A stock that
    #: reached no barrier is still an open position at a knowable average price,
    #: not a write-off — which is why this bucket carries a number here and the
    #: option race's does not.
    terminalMean:   Optional[float] = None


class StockBarrierRaceOut(BaseModel):
    outcomes:  list[StockRaceOutcomeOut]
    stopPrice: float
    nPaths:    int


class StockExitPlanResponse(BaseModel):
    stop:              StockExitPlanStopOut
    targets:           list[StockExitPlanTargetRowOut]
    atr:               float
    #: floor(riskBudget / riskPerShare). None when either input is non-positive.
    recommendedShares: Optional[int] = None
    #: The numerator above, surfaced so the division is checkable on the card
    #: rather than being a number the user has to trust. portfolio_value x
    #: max_loss_per_trade_pct, from risk_rules.yaml — the same file and the same
    #: keys the Settings > Risk form reads and writes.
    riskBudget:        float
    #: Spec section 3.2, the one real inconsistency, DISCLOSED rather than
    #: unified: this engine counts TRADING days (its window is a bar count and
    #: its sigma is annualized with sqrt(252)); the options card counts CALENDAR
    #: days (its window is DTE). Both are internally consistent; silently making
    #: them one number would break whichever card lost. The card renders the
    #: word.
    daysBasis:         Literal["trading"] = "trading"
    horizonDays:       int
    #: Non-null when the GBM is a poor generative model for the strategy that
    #: found this candidate. Same rule, same text, same single implementation as
    #: /stocks/first-passage — see _model_caveat_for.
    modelCaveat:       Optional[str] = None
    race:              Optional[StockBarrierRaceOut] = None


@router.post('/stocks/exit-plan', response_model=StockExitPlanResponse)
async def stock_exit_plan(req: StockExitPlanRequest) -> StockExitPlanResponse:
    """The arithmetic profit plan for a STOCK: a structurally-grounded stop (the
    wider of the structural level and an ATR floor), one target row per R:R
    ratio (arithmetic, snapped onto a real structural level when one is close
    enough), each with its probability and expected TRADING days, plus the
    two-barrier race and a risk-budget share count.

    Fired only by the stock position card's button, never by the scan — same
    latency reasoning as /contracts/exit-plan and /stocks/first-passage.
    """
    ep_cfg = load_exit_plan_cfg()
    fp_cfg = _fp_cfg()
    is_bullish = req.direction == "Bullish"

    try:
        horizon_days = int(load_backtest_cfg(req.horizon)["n_days"])
    except (KeyError, TypeError, ValueError):
        horizon_days = 10   # Swing default; never fail the request over config shape

    async with httpx.AsyncClient(timeout=10) as client:
        candles = await fetch_candles_async(client, req.symbol.upper())

    # BOTH guards carried over from /contracts/exit-plan verbatim, same message,
    # for the same reason. Fewer than 2 candles means _atr cannot form even one
    # true range, and find_structural_stop's own len<10 guard also returns None:
    # the ATR floor then collapses onto entry_price exactly, producing a
    # zero-width "final stop" and every target row landing on the entry price
    # too. That is a plan built on no data wearing the clothes of a computed
    # one — refuse it rather than return it.
    if len(candles) < 2:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    atr = _atr(candles, 14)

    # A flat or duplicated candle feed (stale upstream data, one bar repeated)
    # clears the guard above and still collapses the ATR floor to zero — the
    # same outcome reached a different way.
    if atr <= 0:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    # Identical arguments, identical function, as /contracts/exit-plan: this call
    # IS the guarantee that the stock path is the options path with the premium
    # half removed, rather than a second implementation that drifts.
    raw_stop = compute_final_stop(
        candles, req.direction, req.entry_price, atr,
        ep_cfg["stop"]["atr_multiplier"],
    )

    # QUANTIZED TO CENTS BEFORE IT IS USED, not just before it is printed — and
    # this is the one place the stock path deliberately does something the
    # options path does not. This card's entire value is arithmetic the user can
    # check in his head: "stop $96.00, risk $4.00, so 2R is $108.00". An
    # atr_widened stop is entry - 2 x ATR, and ATR is a mean of true ranges, so
    # it is sub-cent-irrational essentially always. Building the targets off the
    # raw stop and printing the rounded one makes that check fail by a penny on
    # most rows. Rounding first makes every printed number reconcile exactly.
    #
    # The cent FLOOR is the same guard, for the same reason, as
    # resolve_stock_stop's: a wide multiplier on a low-priced name (entry 3.00,
    # ATR 2.00, multiplier 2.0 -> -1.00) drives a bullish floor negative, and a
    # stop at or below zero is not a level. atrFloorPrice below still reports
    # the raw floor, so the card can show WHY the stop sits where it does.
    stop_price = round(raw_stop.price, 2)
    if is_bullish and stop_price < 0.01:
        stop_price = 0.01
    final_stop = dataclasses.replace(raw_stop, price=stop_price)

    risk_per_share = round(abs(req.entry_price - stop_price), 2)

    # The quantized stop landing ON the entry price is the collapsed-plan
    # condition the two guards above exist to prevent, reached by a third route:
    # an ATR small enough that 2 x ATR rounds to nothing at this price. Every
    # target would land on entry and every R:R would be infinite. Refuse it with
    # the same message rather than emit a plan of zeroes.
    if risk_per_share <= 0:
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    rr_ratios = req.rr_ratios if req.rr_ratios is not None else ep_cfg["target"]["rr_ratios"]
    snap_mult = ep_cfg["target"]["structural_snap"]["atr_multiplier"]

    rows = [
        compute_target_row(
            candles, req.direction, req.entry_price, final_stop, atr, float(rr), snap_mult,
        )
        for rr in rr_ratios
    ]
    target_prices = [round(row.price, 2) for row in rows]

    # Deterministic per-request seed — same construction and same reasoning as
    # /stocks/first-passage's and contracts.py's: identical inputs return an
    # identical answer instead of visible Monte Carlo noise on repeated presses,
    # while genuinely different inputs still draw independently. sha256, not
    # hash(), which is salted per process and so unstable across workers.
    seed_key = (
        f"{req.symbol.upper()}|{req.direction}|{req.horizon}|"
        f"{round(req.entry_price, 2)}|{stop_price}|"
        f"{','.join(f'{t:.2f}' for t in target_prices)}"
    )
    seed = int(hashlib.sha256(seed_key.encode()).hexdigest(), 16) % (2 ** 32)

    # CPU-bound NumPy; asyncio.to_thread keeps it off the event loop, exactly as
    # /stocks/first-passage does. The barrier race rides on the SAME simulated
    # paths — no second simulation and no extra work beyond the attribution.
    fp = await asyncio.to_thread(
        functools.partial(
            estimate_stock_first_passage,
            stock_price=req.entry_price,
            direction=req.direction,
            trend_score=req.trend_score,
            stop_price=stop_price,
            targets=target_prices,
            candles=candles,
            horizon_days=horizon_days,
            max_drift_pct=fp_cfg["max_drift_pct"],
            n_paths=fp_cfg["n_paths"],
            sigma_floor=fp_cfg["sigma_floor"],
            sigma_ceiling=fp_cfg["sigma_ceiling"],
            seed=seed,
            compute_race=True,
        )
    )

    structural_price = round(raw_stop.structural.price, 2) if raw_stop.structural else None
    atr_floor_price = round(raw_stop.atr_floor_price, 2)

    stop_out = StockExitPlanStopOut(
        price=stop_price,
        source=raw_stop.source,
        structuralSource=raw_stop.structural.source if raw_stop.structural else None,
        structuralConfidence=raw_stop.structural.confidence if raw_stop.structural else None,
        structuralPrice=structural_price,
        atrFloorPrice=atr_floor_price,
        distanceDollar=(
            round(abs(structural_price - atr_floor_price), 2)
            if structural_price is not None else None
        ),
        riskPerShare=risk_per_share,
        # Spec section 3.3: the options endpoint never reports a probability for
        # its stop row; this engine returns one in the same call, and "this stop
        # is reached on 34% of paths, typically in 6 trading days" is the most
        # decision-relevant number on the card.
        probability=round(fp.invalidation.probability, 4),
        expectedDays=fp.invalidation.expected_days,
    )

    targets_out = [
        StockExitPlanTargetRowOut(
            rrRatio=row.rr_ratio,
            arithmeticPrice=round(row.arithmetic_price, 2),
            price=price,
            tpSource=row.tp_source,
            structuralPrice=round(row.structural.price, 2) if row.structural else None,
            distanceDollar=round(row.distance_dollar, 2) if row.distance_dollar is not None else None,
            toleranceDollar=round(row.tolerance_dollar, 2),
            rewardPerShare=round(abs(price - req.entry_price), 2),
            probability=round(est.probability, 4),
            expectedDays=est.expected_days,
            qualityGood=row.quality_good,
            qualityReasons=row.quality_reasons,
        )
        # zip over fp.targets rather than re-indexing: estimate_stock_first_passage
        # drops non-finite/non-positive targets, so positions are only guaranteed
        # to line up while the lists are the same length — asserted below.
        for row, price, est in zip(rows, target_prices, fp.targets)
    ]
    if len(targets_out) != len(rows):
        raise HTTPException(
            status_code=422,
            detail="insufficient price history to compute an exit plan",
        )

    portfolio_cfg = portfolio_risk._load_config().get("portfolio", {})
    risk_budget = round(
        float(portfolio_cfg.get("portfolio_value", 0.0))
        * float(portfolio_cfg.get("max_loss_per_trade_pct", 0.0)),
        2,
    )
    # shares = risk budget / risk per share. This IS the protective mechanism a
    # stocks stop-cost gate would have duplicated (spec section 1) — sizing off
    # the risk budget bounds the loss at the stop exactly, with no model.
    #
    # DECIMAL, NOT FLOAT FLOOR-DIVISION. Both operands are cent-quantized
    # decimals, and neither is exactly representable in binary: `2000.0 // 1.6`
    # is 1249, not 1250, because 1.6 is stored fractionally below itself. The
    # card prints this number as the answer to the division it shows right
    # beside it, and Apply writes it onto a broker order and into a persisted
    # position — so being one share light is a wrong number in three places at
    # once. Decimal over the string forms is exact for values that are decimal
    # by construction, where `math.floor(a / b)` merely moves the error.
    #
    # None, never a division by zero and never an unbounded size, when either
    # input is non-positive. risk_per_share > 0 is already guaranteed by the 422
    # above; the guard stays because this arithmetic must not depend on a
    # caller's guard staying where it is.
    #
    # A floor of ZERO is also None, not 0. Zero is not a size — it is "the risk
    # budget cannot buy one share at this stop" — and returning it let the card
    # print a SHARES readout of 0 and offer an "Apply 0 shares" button that
    # wrote a 0-share position into the portfolio. Reachable on a small account:
    # a $2,000 portfolio at 0.1% per trade is a $2.00 budget against a $15.69
    # stop.
    recommended_shares: Optional[int] = None
    if risk_budget > 0 and risk_per_share > 0:
        floored = int(Decimal(str(risk_budget)) // Decimal(str(risk_per_share)))
        recommended_shares = floored if floored > 0 else None

    race_out = None
    if fp.race is not None:
        race_out = StockBarrierRaceOut(
            outcomes=[
                StockRaceOutcomeOut(
                    targetPrice=round(o.target_price, 2),
                    pTargetFirst=round(o.p_target_first, 4),
                    pStopFirst=round(o.p_stop_first, 4),
                    pNeither=round(o.p_neither, 4),
                    daysTarget=o.days_target,
                    daysStop=o.days_stop,
                    weightTarget=o.weight_target,
                    weightStop=o.weight_stop,
                    weightNeither=o.weight_neither,
                    terminalMean=round(o.terminal_mean, 2) if o.terminal_mean is not None else None,
                )
                for o in fp.race.outcomes
            ],
            stopPrice=round(fp.race.stop_price, 2),
            nPaths=fp.race.n_paths,
        )

    return StockExitPlanResponse(
        stop=stop_out,
        targets=targets_out,
        atr=round(atr, 2),
        recommendedShares=recommended_shares,
        riskBudget=risk_budget,
        horizonDays=fp.horizon_days,
        modelCaveat=_model_caveat_for(req.strategy),
        race=race_out,
    )
