from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
logging.getLogger("asyncio").setLevel(logging.ERROR)

from app.data.market import get_tradier_creds, _tradier_get_async


class TradierStreamClient:
    """One persistent Tradier streaming connection; fans out ticks to per-symbol Queues."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._task: Optional[asyncio.Task] = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def subscribe(self, symbol: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        already_subscribed = symbol in self._queues
        self._queues.setdefault(symbol, []).append(q)
        if already_subscribed:
            # Symbol already in the running session — no reconnect needed
            self._ensure_running()
        else:
            # New symbol: cancel the current session so _run() reconnects with the updated list
            if self._task is not None and not self._task.done():
                self._task.cancel()
                self._task = None
            self._ensure_running()
        return q

    def unsubscribe(self, symbol: str, q: asyncio.Queue) -> None:
        bucket = self._queues.get(symbol, [])
        try:
            bucket.remove(q)
        except ValueError:
            pass
        if not bucket:
            self._queues.pop(symbol, None)
        if not self._queues and self._task is not None and not self._task.done():
            self._task.cancel()
            self._task = None

    def _dispatch(self, symbol: str, tick: dict) -> None:
        for q in self._queues.get(symbol, []):
            try:
                q.put_nowait(tick)
            except asyncio.QueueFull:
                pass

    # ── Internals ─────────────────────────────────────────────────────────────

    def _ensure_running(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _create_session(self) -> Optional[str]:
        try:
            async with httpx.AsyncClient() as client:
                _tok, _base = get_tradier_creds()
                # Admitted on the governor's `tradier` bucket (TRADIER-GOVERNOR D4).
                resp = await _tradier_get_async(
                    client,
                    f"{_base}/v1/markets/events/session",
                    headers={"Authorization": f"Bearer {_tok}", "Accept": "application/json"},
                    timeout=10,
                    method="POST",
                )
                resp.raise_for_status()
                return resp.json().get("stream", {}).get("url")
        except Exception as exc:
            logger.error("Tradier session create failed: %s", exc)
            return None

    async def _run(self) -> None:
        backoff = 1
        while True:
            if not self._queues:
                return  # no subscribers; _ensure_running() restarts when next client subscribes

            url = await self._create_session()
            if not url:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue

            symbols = list(self._queues.keys())
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST", url,
                        json={"symbols": symbols, "filter": ["trade"], "linebreak": True},
                        headers={"Authorization": f"Bearer {get_tradier_creds()[0]}", "Accept": "application/json"},
                        timeout=None,
                    ) as resp:
                        backoff = 1
                        async for line in resp.aiter_lines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                msg = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if msg.get("type") == "trade":
                                sym = msg.get("symbol", "")
                                self._dispatch(sym, {
                                    "symbol": sym,
                                    "price": float(msg.get("price", 0)),
                                    "volume": int(msg.get("size", 0)),
                                    "timestamp": msg.get("timestamp", ""),
                                })
            except Exception as exc:
                logger.warning("Tradier stream error: %s — retry in %ds", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)


_client = TradierStreamClient()


def get_stream_client() -> TradierStreamClient:
    return _client
