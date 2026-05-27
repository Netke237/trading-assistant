# backend/app/routers/chart.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.data.chart_cache import get_intraday
from app.data.tradier_stream import get_stream_client
from app.services.market_structure import compute_structure

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chart", tags=["chart"])


@router.get("/history")
async def history(
    symbol: str = Query(...),
    interval: str = Query("15min"),
    days: int = Query(55),
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
    sc = get_stream_client()
    queue: Optional[asyncio.Queue] = None

    try:
        candles = await get_intraday(symbol, interval)
        await websocket.send_json({"type": "history", "candles": candles})

        # Phase 2: fetch higher timeframe candles for MTF alignment (1h → 1D)
        ht_candles = None
        if interval == "1h":
            ht_candles = await get_intraday(symbol, "1D")

        # Phase 2: compute and send market structure signals
        signals = compute_structure(candles, interval, symbol, ht_candles)
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
                        candles = await get_intraday(symbol, interval)
                        ht_candles = None
                        if interval == "1h":
                            ht_candles = await get_intraday(symbol, "1D")
                        signals = compute_structure(candles, interval, symbol, ht_candles)
                        await websocket.send_json({
                            "type": "structure",
                            "symbol": symbol,
                            "interval": interval,
                            "signals": signals,
                        })
                    except Exception:
                        logger.debug("Failed to re-compute structure on candle close", exc_info=True)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WS error for %s: %s", symbol, exc)
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        if queue is not None:
            sc.unsubscribe(symbol, queue)
        try:
            await websocket.close()
        except Exception:
            pass
