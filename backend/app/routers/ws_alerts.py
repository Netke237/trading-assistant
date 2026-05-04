from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.alert_service import alert_service

router = APIRouter(tags=["alerts-ws"])


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for live alert streaming.

    On connect:
      1. Accept the connection.
      2. Register the client with alert_service.
      3. Send an empty JSON array immediately.
      4. Keep the connection open, waiting for the client to disconnect.

    On disconnect (or any error): unregister the client silently.
    """
    await websocket.accept()
    alert_service.connect(websocket)

    try:
        await websocket.send_text(json.dumps([]))

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        alert_service.disconnect(websocket)
