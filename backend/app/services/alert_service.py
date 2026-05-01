from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class AlertService:
    """Registry of active WebSocket clients. Thread-safe for asyncio."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    def connect(self, ws: WebSocket) -> None:
        self._clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.remove(ws)

    async def broadcast(self, payload: Any) -> None:
        """
        Send `payload` (any JSON-serialisable object) to all connected clients.
        Disconnected clients are removed silently.
        """
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass


alert_service = AlertService()