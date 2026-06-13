from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import hashlib
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone, date, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from app.services.audit import new_rec_id
from app.schemas.stock_scan import (
    StockScanRequest, StockScanResult, PositionCardOut,
    StrategySignalOut, BacktestOut, StockPipeline,
)
from app.data.market import fetch_company_name_async, fetch_price_async, fetch_quotes
from app.services.historical_store import get_bars as get_historical_bars
from app.scoring.stock_scorer import score_stock
from app.services.strategy_engine import (
    pullback_ema_signal, breakout_base_signal,
    ma_crossover_signal, mean_reversion_rsi_signal,
)
from app.services.strategy_backtest import run_strategy_backtest
from app.data.confidence_cache import cache_key as conf_cache_key, get_cached, set_cached
from app.scoring.signal_confidence import compute_confidence, interpret

router = APIRouter(prefix="/api", tags=["stock-scan"])
logger = logging.getLogger(__name__)

_SIGNAL_FNS = {
    "pullback_ema":        pullback_ema_signal,
    "breakout_base":       breakout_base_signal,
    "ma_crossover":        ma_crossover_signal,
    "mean_reversion_rsi":  mean_reversion_rsi_signal,
}

_SIGNAL_KWARGS: dict[str, Callable[[StockScanRequest], dict[str, Any]]] = {
    "pullback_ema":       lambda r: {"tolerance": r.pullback_tolerance_pct, "ema_period": r.pullback_ema_period, "trend_ema": r.pullback_trend_ema, "ma_type": r.pullback_ma_type, "require_reversal": r.pullback_require_reversal},
    "breakout_base":      lambda r: {"volume_mult": r.breakout_volume_mult},
    "ma_crossover":       lambda r: {"fast": r.ma_crossover_fast, "slow": r.ma_crossover_slow, "lookback": r.ma_crossover_lookback},
    "mean_reversion_rsi": lambda r: {"rsi_period": r.rsi_period, "rsi_oversold": r.rsi_oversold, "trend_sma": r.rsi_trend_sma},
}

_HISTORY_YEARS = 5
_SCAN_SEM = asyncio.Semaphore(5)

_BACKTEST_TTL = 24 * 3600  # daily — bar history doesn't change within a trading day
_BACKTEST_CACHE: dict[str, tuple] = {}  # key → (BacktestResult, expires_at)
_BACKTEST_POOL = concurrent.futures.ProcessPoolExecutor(
    max_workers=max(1, (os.cpu_count() or 2) // 2)
)


def _backtest_key(symbol: str, strategy: str, direction: str, bars: list[dict]) -> str:
    bars_hash = hashlib.md5(
        str([(b["time"], b["close"]) for b in bars[-20:]]).encode()
    ).hexdigest()[:8]
    return f"{symbol.upper()}|{strategy}|{direction.lower()}|{bars_hash}"


def _get_backtest_cached(key: str):
    entry = _BACKTEST_CACHE.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


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

            card = score_stock(
                symbol=symbol,
                direction=req.direction,
                horizon=req.horizon,
                bars=bars[-120:],
                scoring_mode="stock",
            )
            if card.status == "REJECT":
                return {"symbol": symbol, "reason": f"REJECT score={card.score}"}

            signal_fn = _SIGNAL_FNS.get(req.strategy)
            if not signal_fn:
                return {"symbol": symbol, "reason": f"unknown strategy {req.strategy}"}
            signal_kwargs = _SIGNAL_KWARGS.get(req.strategy, lambda r: {})(req)
            signal = signal_fn(bars[-120:], **signal_kwargs)
            if signal is None:
                return {"symbol": symbol, "reason": f"no {req.strategy} setup"}

            _bt_key = _backtest_key(symbol, req.strategy, req.direction, bars)
            bt_result = _get_backtest_cached(_bt_key)
            if bt_result is None:
                bt_result = await asyncio.get_running_loop().run_in_executor(
                    _BACKTEST_POOL,
                    functools.partial(
                        run_strategy_backtest, bars,
                        strategy=req.strategy, direction=req.direction,
                        min_trades=req.bt_min_trades, min_win_rate=req.bt_min_win_rate,
                    ),
                )
                _BACKTEST_CACHE[_bt_key] = (bt_result, time.time() + _BACKTEST_TTL)
            if not bt_result.passes_gate:
                return {"symbol": symbol, "reason": f"backtest gate: {bt_result.summary_text}"}

            _ck = conf_cache_key(symbol, req.direction, req.horizon)
            _cached = get_cached(_ck)
            if _cached is None:
                _res = await asyncio.to_thread(
                    compute_confidence, bars, direction=req.direction, horizon=req.horizon
                )
                _cached = {"confidence": _res.confidence, "sample_size": _res.sample_size}
                set_cached(_ck, _cached)
            conf_val = _cached["confidence"]
            conf_txt = interpret(conf_val, sample_size=_cached["sample_size"], symbol=symbol) if conf_val is not None else None

            shares, dollar_risk = _position_size(
                req.account_size, req.risk_pct, req.risk_fixed_usd,
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
            )
        except Exception as exc:
            logger.exception("Error processing %s", symbol)
            return {"symbol": symbol, "reason": str(exc)}


@router.post("/stock-scan")
async def run_stock_scan(req: StockScanRequest) -> StockScanResult:
    from app.data.universe_presets import expand_universe, PresetUnavailableError

    scan_id = new_rec_id()

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

    tasks = [_process_stock(s, req, scan_id, price_map, benchmark_closes) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    candidates, rejected = [], []
    for r in results:
        if isinstance(r, Exception):
            rejected.append({"symbol": "unknown", "reason": str(r)})
        elif isinstance(r, PositionCardOut):
            candidates.append(r)
        else:
            rejected.append(r)

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
        other_rejected=sum(
            1 for r in rejected
            if isinstance(r, dict)
            and not any(k in r.get("reason", "") for k in _hist_kw)
            and not r.get("reason", "").startswith("price $")
            and not r.get("reason", "").startswith("REJECT score=")
            and not (r.get("reason", "").startswith("no ") and "setup" in r.get("reason", ""))
            and not r.get("reason", "").startswith("backtest gate:")
        ),
        candidates=len(candidates),
    )
    logger.info(
        "STOCK SCAN pipeline: scanned=%d hist_fail=%d score_fail=%d signal_fail=%d bt_fail=%d other=%d candidates=%d",
        _pipeline.scanned, _pipeline.failed_history, _pipeline.failed_score,
        _pipeline.failed_signal, _pipeline.failed_backtest, _pipeline.other_rejected, _pipeline.candidates,
    )
    return StockScanResult(
        scan_id=scan_id, timestamp=datetime.now(timezone.utc).isoformat(),
        candidates=candidates, rejected=rejected, pipeline=_pipeline,
    )
