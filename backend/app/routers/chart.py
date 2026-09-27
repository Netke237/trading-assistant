# backend/app/routers/chart.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.data.chart_cache import get_intraday, get_intraday_with_fetched_at
from app.data.tradier_stream import get_stream_client
from app.services.market_structure import compute_structure

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chart", tags=["chart"])

# CHART-WS-1D-1W-RULES: the chart opens the WS with 'daily'/'weekly'; rules are
# stored '1D'/'1W'. The fetch keeps the WS spelling; alert evaluation uses this.
_RULE_INTERVAL = {"daily": "1D", "weekly": "1W"}
# 1D/1W alerts are checked on this cadence (the scheduler's default), not on the
# tick's time: a daily bar is judged once, by the WS or the scheduler, whichever
# claims it first (chart_alert_scheduler.evaluate_closed_candles).
_DAILY_ALERT_CHECK_SECONDS = 60


@router.get("/history")
async def history(
    symbol: str = Query(...),
    interval: str = Query("15min"),
    days: Optional[int] = Query(None, ge=1),
) -> list[dict]:
    return await get_intraday(symbol.upper(), interval, days)


@router.websocket("/stream/{symbol}")
async def stream(
    websocket: WebSocket,
    symbol: str,
    interval: str = Query("15min"),
) -> None:
    await websocket.accept()
    symbol = symbol.upper()
    rule_interval = _RULE_INTERVAL.get(interval, interval)
    daily_alerts = rule_interval in ("1D", "1W")
    next_daily_check = 0.0
    sc = get_stream_client()
    queue: Optional[asyncio.Queue] = None

    try:
        candles = await get_intraday(symbol, interval)
        if not candles:
            await websocket.send_json({
                "type": "error",
                "message": f"No chart data available for {symbol} at interval {interval}. "
                           "Try a different timeframe or check the symbol.",
            })
            return
        await websocket.send_json({"type": "history", "candles": candles})

        # Phase 2: fetch higher timeframe candles for MTF alignment (1h → 1D)
        ht_candles = None
        if interval == "1h":
            ht_candles = await get_intraday(symbol, "1D")

        # Phase 2: compute and send market structure signals
        signals = await asyncio.to_thread(compute_structure, candles, interval, symbol, ht_candles)
        await websocket.send_json({
            "type": "structure",
            "symbol": symbol,
            "interval": interval,
            "signals": signals,
        })

        last_candle_time = candles[-1]["time"] if candles else None

        queue = await sc.subscribe(symbol)

        while True:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json({"type": "tick", "data": tick})

                # Phase 2: re-send structure on new candle close
                tick_time = tick.get("timestamp", "") if isinstance(tick, dict) else ""
                if tick_time and tick_time != last_candle_time:
                    last_candle_time = tick_time
                    try:
                        candles, _fetched_at = await get_intraday_with_fetched_at(symbol, interval)
                        ht_candles = None
                        if interval == "1h":
                            ht_candles = await get_intraday(symbol, "1D")
                        signals = await asyncio.to_thread(
                            compute_structure, candles, interval, symbol, ht_candles)
                        await websocket.send_json({
                            "type": "structure",
                            "symbol": symbol,
                            "interval": interval,
                            "signals": signals,
                        })
                        # Phase 4: evaluate alert rules on candle-close. Intraday
                        # only: 1D/1W are evaluated below, once per closed bar.
                        if not daily_alerts:
                            try:
                                from app.routers.chart_alerts import (
                                    closed_candle_structure, evaluate_and_notify_for_symbol,
                                )
                                # candles[-2] is the just-closed candle; candles[-1] is the new open
                                closed = candles[-2] if len(candles) >= 2 else candles[-1]
                                # A4e: the alert decision gets structure computed up to the
                                # closed candle; `signals` above (full list) is display only.
                                alert_signals = await asyncio.to_thread(
                                    closed_candle_structure, candles, closed, interval, symbol, ht_candles)
                                triggered = await evaluate_and_notify_for_symbol(
                                    symbol, interval, closed, candles, alert_signals, as_of=_fetched_at,
                                )
                                for entry in triggered:
                                    await websocket.send_json({
                                        "type": "alert_triggered",
                                        "entry": entry,
                                    })
                            except Exception:
                                logger.warning("Alert evaluation failed", exc_info=True)
                    except Exception:
                        logger.debug("Failed to re-compute structure on candle close", exc_info=True)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})

            # CHART-WS-1D-1W-RULES: after a tick OR a ping, so it does not depend
            # on the tick's time. Only for a pair with an enabled rule: a claim
            # without one would make a rule drawn next skip its first sighting.
            if daily_alerts and time.monotonic() >= next_daily_check:
                next_daily_check = time.monotonic() + _DAILY_ALERT_CHECK_SECONDS
                try:
                    from app.services.chart_alert_scheduler import (
                        evaluate_closed_candles, has_enabled_rule,
                    )
                    if await has_enabled_rule(symbol, rule_interval):
                        d_candles, d_fetched = await get_intraday_with_fetched_at(symbol, interval)
                        for entry in await evaluate_closed_candles(symbol, rule_interval, d_candles, d_fetched):
                            await websocket.send_json({"type": "alert_triggered", "entry": entry})
                except WebSocketDisconnect:
                    raise
                except Exception:
                    logger.warning("Daily/weekly alert evaluation failed for %s [%s]",
                                   symbol, rule_interval, exc_info=True)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error for %s: %s", symbol, exc)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Chart stream error for {symbol}. Please try again.",
            })
        except Exception:
            pass
    finally:
        if queue is not None:
            sc.unsubscribe(symbol, queue)
        try:
            await websocket.close()
        except Exception:
            pass
