# backend/app/routers/chart.py
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.data.chart_cache import get_intraday
from app.data.tradier_stream import get_stream_client

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

        queue = await sc.subscribe(symbol)

        while True:
            try:
                tick = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json({"type": "tick", "data": tick})
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
