# LLM Context — Alerts WebSocket Skeleton (Workstream 17)

> **Self-contained.** Read this document fully before touching any code.
> Do not read any other file unless something is genuinely ambiguous after reading this document.
> Project root: `F:\Git\GitHub\Trading assistant`. All work lives in `backend/`.

---

## Section 1 — Mission

**Conflict class: Zero conflict.**
This workstream creates three new files and modifies `main.py`. It does not touch `frontend/`, any existing router, any fixture, or any schema file.

**Goal:**
Build the WebSocket server skeleton that will later receive alert events from the scan engine (WS-28). For now, it:
1. Accepts WebSocket connections on `GET /ws/alerts`
2. Broadcasts the 5 fixture alerts to every client on connect
3. Keeps a connected-client registry so WS-28 can call `broadcast()` later

**What NOT to touch:**
- Any file under `frontend/`
- `backend/app/routers/health.py`, `watchlist.py`, `contracts.py`, `candles.py`, `regime.py`, `sectors.py`, `tradecards.py`, `portfolio.py`, `alerts.py`, `events.py` — read-only
- Any fixture or schema file

**Conflict note with WS-18:**
WS-17 creates `backend/app/services/__init__.py`. WS-18 also creates a file in that directory. If both run in parallel, the `__init__.py` will have a trivial merge conflict (empty file). Resolve by keeping either copy — both are identical.

---

## Section 2 — Owned files

| File path | Create / Modify | Purpose |
|---|---|---|
| `backend/app/services/__init__.py` | **Create** | Empty package init for `services/` |
| `backend/app/services/alert_service.py` | **Create** | Connected-client registry + `broadcast()` |
| `backend/app/routers/ws_alerts.py` | **Create** | `GET /ws/alerts` WebSocket endpoint |
| `backend/app/main.py` | **Modify** | Add WebSocket router import and include |

---

## Section 3 — Read-only references

| File | Reason |
|---|---|
| `backend/app/fixtures/alerts.py` | Source fixture — broadcast these 5 alerts on connect |
| `backend/app/schemas/__init__.py` | `AlertItem` schema — alerts must match this shape |
| `backend/app/main.py` | Existing app factory — add router include here |

---

## Section 4 — Implementation

### 4.1 `backend/app/services/__init__.py`

```python
# empty
```

### 4.2 `backend/app/services/alert_service.py`

```python
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


# Module-level singleton — imported by routers and services that need to broadcast
alert_service = AlertService()
```

### 4.3 `backend/app/routers/ws_alerts.py`

```python
from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.fixtures.alerts import MOCK_ALERTS
from app.services.alert_service import alert_service

router = APIRouter(tags=["alerts-ws"])


@router.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for live alert streaming.

    On connect:
      1. Accept the connection.
      2. Register the client with alert_service.
      3. Send the current fixture alerts as a JSON array immediately.
      4. Keep the connection open, waiting for the client to disconnect.

    On disconnect (or any error): unregister the client silently.
    """
    await websocket.accept()
    alert_service.connect(websocket)

    try:
        # Send fixture alerts immediately on connect
        await websocket.send_text(json.dumps(MOCK_ALERTS))

        # Hold connection open until client disconnects
        while True:
            # We don't expect client messages in this version, but we must
            # await something to keep the loop alive without busy-spinning.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        alert_service.disconnect(websocket)
```

### 4.4 `backend/app/main.py` — add two lines

Find the existing router import block and add:
```python
from app.routers.ws_alerts import router as ws_alerts_router
```

Find the `app.include_router()` block and add:
```python
app.include_router(ws_alerts_router)
```

The existing `app/main.py` already imports and includes 9 trading routers. Add `ws_alerts_router` after `events_router` — preserve everything else exactly.

---

## Section 5 — Fixture reference

```python
# From backend/app/fixtures/alerts.py
# MOCK_ALERTS is a list[dict] — each dict must match AlertItem schema:
# { id: str, kind: 'Info'|'Action'|'Critical', symbol: str, reason: str, timestamp: str }

# Example:
MOCK_ALERTS = [
    {"id": "a1", "kind": "Critical", "symbol": "META",  "reason": "Broke trail stop",                    "timestamp": "09:38"},
    {"id": "a2", "kind": "Action",   "symbol": "NVDA",  "reason": "Earnings in 3 days — roll or close",  "timestamp": "09:41"},
    {"id": "a3", "kind": "Action",   "symbol": "AAPL",  "reason": "Target 80% reached",                  "timestamp": "09:47"},
    {"id": "a4", "kind": "Info",     "symbol": "SPY",   "reason": "Regime flipped to PASS",              "timestamp": "09:15"},
    {"id": "a5", "kind": "Info",     "symbol": "TSLA",  "reason": "IV rank > 70",                        "timestamp": "09:02"},
]
```

---

## Section 6 — Task spec

### Acceptance criteria

1. `uvicorn app.main:app --reload --port 8000` starts without error.
2. Connecting a WebSocket client to `ws://localhost:8000/ws/alerts` receives a JSON array of 5 alert items within 1 second.
3. The fixture HTTP endpoint `GET /api/alerts` (the existing REST endpoint) still returns HTTP 200 with 5 items — the WebSocket must not interfere.
4. `GET /health` still returns `{"status": "ok"}`.
5. Two clients connecting simultaneously both receive the fixture alerts independently.

### Verify

```bash
cd backend
uvicorn app.main:app --reload --port 8000 &

# In another terminal — use Python's websockets library to test:
python -c "
import asyncio, websockets, json

async def test():
    async with websockets.connect('ws://localhost:8000/ws/alerts') as ws:
        msg = await ws.recv()
        data = json.loads(msg)
        print('received', len(data), 'alerts')
        print('first:', data[0])

asyncio.run(test())
"
# Expected: received 5 alerts / first: {'id': 'a1', 'kind': 'Critical', ...}

# REST endpoint still works:
curl http://localhost:8000/api/alerts | python -m json.tool | head -5
curl http://localhost:8000/health
```

If `websockets` is not installed: `pip install websockets` for the test only — do not add it to `requirements.txt`.

---

## Section 7 — Hard rules

1. Do NOT touch any file under `frontend/`.
2. Do NOT modify any existing router file (health, watchlist, contracts, etc.).
3. Do NOT add `websockets` to `requirements.txt` — FastAPI's built-in WebSocket support (starlette) is already included via `uvicorn[standard]`.
4. The `alert_service` singleton must be importable from `app.services.alert_service`. WS-28 will import it to call `broadcast()`.
5. The WebSocket endpoint path must be exactly `/ws/alerts` — no prefix.
6. `GET /health` and all 9 REST trading routes must continue to work unchanged.

---

## Section 8 — Dev workflow

```bash
cd backend
uvicorn app.main:app --reload --port 8000
# Test WebSocket per Section 6
python -c "from app.main import app; print('App loaded OK')"
```

---

## Section 9 — Copy/paste prompt

```
Use the superpowers:using-git-worktrees skill to create your worktree first,
branching from feature/1-api-integration, branch name feature/ws-17-alerts-ws.

Read `llm-contexts/17-alerts-websocket.md` fully before writing any code.
It is your single source of truth.

You are building the WebSocket alerts skeleton for the Bamendjou options screener
(FastAPI / Python 3.11).

Your owned files:
  - backend/app/services/__init__.py        (CREATE — empty)
  - backend/app/services/alert_service.py   (CREATE)
  - backend/app/routers/ws_alerts.py        (CREATE)
  - backend/app/main.py                     (MODIFY — add two lines)

Do not modify any file outside this list.

Task: Create the AlertService registry, the /ws/alerts WebSocket endpoint,
and wire it into main.py. On connect, broadcast the 5 fixture alerts as a JSON array.

After implementation run the verification block in Section 6.
Commit after all checks pass.
```
