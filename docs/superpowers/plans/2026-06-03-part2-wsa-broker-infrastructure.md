# Part 2 — WS-A: Broker Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add IBKR paper + Tradier paper broker accounts (with grayed-out live IBKR prep), store credentials via a backend endpoint to a gitignored local file, and expose a unified broker order interface for both stock and options execution.

**Architecture:** A `CredentialStore` singleton loads on startup from `backend/config/local_credentials.yaml` (gitignored, never committed) and can be updated at runtime via `POST /settings/credentials`. Two new adapters (`ibkr_paper.py`, `tradier_paper.py`) implement a shared `BrokerAdapter` protocol. A `BrokerRouter` service selects the active adapter and forwards orders. Frontend Settings gains panels for IBKR paper, Tradier paper, and a disabled live IBKR placeholder.

**Tech Stack:** Python FastAPI + Pydantic v2, PyYAML, httpx (backend); Zustand v5, TypeScript, CSS Modules (frontend). No new pip packages needed.

**Build order:** This workstream must land before WS-B and WS-C, which both depend on the broker adapters.

---

## File Structure

**Backend — new**
- `backend/app/services/credential_store.py` — singleton: load/save/get/mask credentials from local YAML
- `backend/app/data/ibkr_paper.py` — IBKR paper adapter (place stock + option orders via paper gateway)
- `backend/app/data/tradier_paper.py` — Tradier sandbox adapter (place stock + option orders)
- `backend/app/services/broker_router.py` — select adapter by broker key, execute order
- `backend/app/routers/credentials.py` — POST/GET /settings/credentials
- `backend/app/routers/broker.py` — POST /broker/order (stock + option)
- `backend/tests/test_credential_store.py`
- `backend/tests/test_broker_router.py`

**Backend — modified**
- `backend/app/main.py` — register two new routers, load credentials on startup
- `backend/.gitignore` — add `config/local_credentials.yaml`

**Frontend — modified**
- `frontend/lib/settingsStore.ts` — extend `BrokerConfig` into four separate account configs; v13 migration
- `frontend/app/(frame)/settings/page.tsx` — four broker panels (IBKR paper, Tradier paper, grayed live IBKR, existing live Tradier)
- `frontend/lib/api.ts` — add `postCredentials` and `getBrokerStatus` methods

---

## Task 1: Credential store service

**Files:**
- Create: `backend/app/services/credential_store.py`
- Create: `backend/tests/test_credential_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_credential_store.py
import os
import pytest
import tempfile
from pathlib import Path

# Patch the path before importing so we can use a temp file
os.environ["BAMENDJOU_CREDS_PATH"] = ""

from app.services.credential_store import CredentialStore, BrokerCredentials


def test_store_sets_and_gets():
    store = CredentialStore(path=None)
    store.set("tradier_paper", {"token": "abc123", "account_id": "TA1234"})
    creds = store.get("tradier_paper")
    assert creds["token"] == "abc123"
    assert creds["account_id"] == "TA1234"


def test_store_masks_tokens():
    store = CredentialStore(path=None)
    store.set("tradier_paper", {"token": "supersecret", "account_id": "TA1234"})
    masked = store.get_masked("tradier_paper")
    assert "supersecret" not in masked["token"]
    assert masked["token"].endswith("****")


def test_store_persists_to_and_loads_from_file():
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        path = f.name
    try:
        store = CredentialStore(path=Path(path))
        store.set("tradier_paper", {"token": "mytoken", "account_id": "ACC"})
        store.save()
        store2 = CredentialStore(path=Path(path))
        store2.load()
        assert store2.get("tradier_paper")["token"] == "mytoken"
    finally:
        os.unlink(path)


def test_store_get_unknown_key_returns_none():
    store = CredentialStore(path=None)
    assert store.get("nonexistent") is None


def test_all_returns_masked_dict():
    store = CredentialStore(path=None)
    store.set("ibkr_paper", {"base_url": "https://localhost:7499/v1/api", "account_id": ""})
    result = store.all_masked()
    assert "ibkr_paper" in result
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_credential_store.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.credential_store`

- [ ] **Step 3: Implement CredentialStore**

Create `backend/app/services/credential_store.py`:

```python
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml

# Default path; override via BAMENDJOU_CREDS_PATH env var or constructor arg.
_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "local_credentials.yaml"

_SENSITIVE_KEYS = {"token", "apiToken", "api_token", "password", "secret"}


def _mask(value: str) -> str:
    """Show last 4 chars, mask the rest."""
    if not value or len(value) <= 4:
        return "****"
    return "*" * (len(value) - 4) + value[-4:]


def _mask_dict(d: dict) -> dict:
    return {k: _mask(v) if k in _SENSITIVE_KEYS and isinstance(v, str) else v for k, v in d.items()}


class CredentialStore:
    """Thread-safe in-memory credential store backed by a local gitignored YAML file."""

    def __init__(self, path: Path | None = _DEFAULT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {
            "ibkr_live":     {"base_url": "https://localhost:5000/v1/api", "account_id": ""},
            "ibkr_paper":    {"base_url": "https://localhost:7499/v1/api", "account_id": ""},
            "tradier_live":  {"token": "", "account_id": ""},
            "tradier_paper": {"token": "", "account_id": ""},
        }
        if self._path and self._path.exists():
            self.load()

    def load(self) -> None:
        if not self._path:
            return
        with self._lock:
            raw = yaml.safe_load(self._path.read_text()) or {}
            for k, v in raw.items():
                if isinstance(v, dict):
                    self._data[k] = {**self._data.get(k, {}), **v}

    def save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._path.write_text(yaml.dump(self._data, default_flow_style=False))

    def get(self, key: str) -> dict | None:
        with self._lock:
            return dict(self._data[key]) if key in self._data else None

    def set(self, key: str, values: dict) -> None:
        with self._lock:
            self._data[key] = {**self._data.get(key, {}), **values}

    def get_masked(self, key: str) -> dict | None:
        d = self.get(key)
        return _mask_dict(d) if d is not None else None

    def all_masked(self) -> dict[str, dict]:
        with self._lock:
            return {k: _mask_dict(dict(v)) for k, v in self._data.items()}


# Module-level singleton used by all adapters and routers.
import os as _os
_creds_path = Path(_os.getenv("BAMENDJOU_CREDS_PATH", str(_DEFAULT_PATH))) if _os.getenv("BAMENDJOU_CREDS_PATH") else _DEFAULT_PATH
credential_store = CredentialStore(path=_creds_path)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_credential_store.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Add to .gitignore**

In `backend/.gitignore`, add on a new line:
```
config/local_credentials.yaml
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/credential_store.py backend/tests/test_credential_store.py backend/.gitignore
git commit -m "feat(broker): credential store — in-memory + gitignored local YAML persistence"
```

---

## Task 2: Credentials HTTP endpoint

**Files:**
- Create: `backend/app/routers/credentials.py`
- Test: `backend/tests/test_credential_store.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_credential_store.py
from fastapi.testclient import TestClient
from fastapi import FastAPI

def _make_app():
    from app.routers.credentials import router
    app = FastAPI()
    app.include_router(router)
    return app


def test_post_credentials_stores_and_get_returns_masked():
    client = TestClient(_make_app())
    resp = client.post("/settings/credentials", json={
        "key": "tradier_paper",
        "values": {"token": "tok_secret", "account_id": "ACC123"}
    })
    assert resp.status_code == 200, resp.text
    resp2 = client.get("/settings/credentials")
    data = resp2.json()
    assert "tradier_paper" in data
    assert "secret" not in data["tradier_paper"].get("token", "")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_credential_store.py::test_post_credentials_stores_and_get_returns_masked -v`
Expected: FAIL — `ModuleNotFoundError: app.routers.credentials`

- [ ] **Step 3: Implement the router**

Create `backend/app/routers/credentials.py`:

```python
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.credential_store import credential_store

router = APIRouter(prefix="/settings", tags=["credentials"])


class CredentialUpdate(BaseModel):
    key: str    # "ibkr_paper" | "ibkr_live" | "tradier_live" | "tradier_paper"
    values: dict


@router.post("/credentials")
async def set_credentials(body: CredentialUpdate) -> dict:
    """Store broker credentials in memory and persist to local (gitignored) file."""
    credential_store.set(body.key, body.values)
    credential_store.save()
    return {"ok": True, "key": body.key}


@router.get("/credentials")
async def get_credentials() -> dict:
    """Return all credential slots with sensitive values masked."""
    return credential_store.all_masked()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_credential_store.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/credentials.py backend/tests/test_credential_store.py
git commit -m "feat(broker): POST/GET /settings/credentials endpoint — masked responses"
```

---

## Task 3: IBKR paper adapter

**Files:**
- Create: `backend/app/data/ibkr_paper.py`
- Create: `backend/tests/test_ibkr_paper.py`

Context: The existing `backend/app/data/ibkr.py` is read-only (market data only). The paper adapter adds order placement using the same Client Portal Web API but targeting the paper gateway URL (typically port 7499). It exposes the minimum needed: place order + get order status.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_ibkr_paper.py
import pytest
from unittest.mock import patch, MagicMock
from app.data.ibkr_paper import IbkrPaperAdapter, BrokerOrder, OrderResult


def _adapter():
    return IbkrPaperAdapter(
        base_url="https://localhost:7499/v1/api",
        account_id="DU123456",
    )


def test_adapter_builds_order_payload():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=10,
        order_type="LMT", limit_price=185.0, tif="DAY"
    )
    payload = adapter._build_payload(order)
    assert payload["orders"][0]["side"] == "BUY"
    assert payload["orders"][0]["quantity"] == 10
    assert payload["orders"][0]["price"] == 185.0
    assert payload["orders"][0]["orderType"] == "LMT"


def test_adapter_place_order_success(requests_mock):
    adapter = _adapter()
    requests_mock.post(
        "https://localhost:7499/v1/api/iserver/account/DU123456/orders",
        json=[{"order_id": "987654", "order_status": "PreSubmitted"}]
    )
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = adapter.place_order(order)
    assert result.order_id == "987654"
    assert result.status == "PreSubmitted"
    assert result.broker == "ibkr_paper"


def test_adapter_place_order_failure_raises(requests_mock):
    adapter = _adapter()
    requests_mock.post(
        "https://localhost:7499/v1/api/iserver/account/DU123456/orders",
        status_code=401,
        json={"error": "Unauthorized"}
    )
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="IBKR paper order failed"):
        adapter.place_order(order)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && pip install requests-mock && python -m pytest tests/test_ibkr_paper.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.ibkr_paper`

- [ ] **Step 3: Implement the adapter**

Create `backend/app/data/ibkr_paper.py`:

```python
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Literal

import httpx
import urllib3

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

OrderType = Literal["MKT", "LMT"]
ActionType = Literal["BUY", "SELL"]
TIF = Literal["DAY", "GTC"]


@dataclass
class BrokerOrder:
    symbol: str
    action: ActionType
    quantity: int
    order_type: OrderType
    limit_price: float | None
    tif: TIF = "DAY"
    # For options: provide these fields
    conid: int | None = None          # IBKR contract ID (options)
    sec_type: str = "STK"             # "STK" or "OPT"


@dataclass
class OrderResult:
    order_id: str
    status: str
    broker: str
    message: str = ""


class IbkrPaperAdapter:
    """Places orders on an IBKR paper account via the Client Portal Web API.

    The paper gateway must be running locally (separate process from the live gateway).
    Typical URL: https://localhost:7499/v1/api
    """

    def __init__(self, base_url: str, account_id: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._account = account_id
        self._timeout = timeout

    def _build_payload(self, order: BrokerOrder) -> dict:
        o: dict = {
            "conidex": f"{order.conid}" if order.conid else None,
            "secType": f"{order.conid}:{order.sec_type}" if order.conid else f":{order.sec_type}",
            "orderType": order.order_type,
            "side": order.action,
            "quantity": order.quantity,
            "tif": order.tif,
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            o["price"] = order.limit_price
        if not order.conid:
            # Resolve conid by symbol for stocks (simplified — production would cache this)
            o["symbol"] = order.symbol
            del o["conidex"]
            del o["secType"]
            o["secType"] = "STK"
        return {"orders": [o]}

    def place_order(self, order: BrokerOrder) -> OrderResult:
        url = f"{self._base}/iserver/account/{self._account}/orders"
        payload = self._build_payload(order)
        try:
            resp = httpx.post(url, json=payload, verify=False, timeout=self._timeout)
        except Exception as exc:
            raise RuntimeError(f"IBKR paper order failed: connection error — {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"IBKR paper order failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        data = resp.json()
        if isinstance(data, list):
            data = data[0]
        return OrderResult(
            order_id=str(data.get("order_id", "")),
            status=str(data.get("order_status", "Unknown")),
            broker="ibkr_paper",
            message=str(data.get("message", "")),
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_ibkr_paper.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/ibkr_paper.py backend/tests/test_ibkr_paper.py
git commit -m "feat(broker): IBKR paper adapter — place stock/option orders on paper gateway"
```

---

## Task 4: Tradier paper (sandbox) adapter

**Files:**
- Create: `backend/app/data/tradier_paper.py`
- Create: `backend/tests/test_tradier_paper.py`

Context: Tradier sandbox URL is `https://sandbox.tradier.com/v1/`. It accepts the same order API as production but uses a separate sandbox token. Orders are simulated.

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_tradier_paper.py
import pytest
from app.data.tradier_paper import TradierPaperAdapter, BrokerOrder, OrderResult


def _adapter():
    return TradierPaperAdapter(token="sandbox_tok", account_id="VA12345678")


def test_adapter_builds_equity_params():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="NVDA", action="BUY", quantity=20,
        order_type="LMT", limit_price=130.0, tif="DAY"
    )
    params = adapter._build_params(order)
    assert params["class"] == "equity"
    assert params["symbol"] == "NVDA"
    assert params["side"] == "buy"
    assert params["quantity"] == "20"
    assert params["type"] == "limit"
    assert params["price"] == "130.0"


def test_adapter_builds_option_params():
    adapter = _adapter()
    order = BrokerOrder(
        symbol="NVDA", action="BUY", quantity=1,
        order_type="LMT", limit_price=3.50, tif="DAY",
        option_symbol="NVDA260620C00130000",
    )
    params = adapter._build_params(order)
    assert params["class"] == "option"
    assert params["option_symbol"] == "NVDA260620C00130000"


def test_place_order_success(requests_mock):
    adapter = _adapter()
    requests_mock.post(
        "https://sandbox.tradier.com/v1/accounts/VA12345678/orders",
        json={"order": {"id": 111222, "status": "ok", "partner_id": "0"}}
    )
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = adapter.place_order(order)
    assert result.order_id == "111222"
    assert result.broker == "tradier_paper"


def test_place_order_failure(requests_mock):
    adapter = _adapter()
    requests_mock.post(
        "https://sandbox.tradier.com/v1/accounts/VA12345678/orders",
        status_code=400,
        json={"fault": {"faultstring": "Invalid token"}}
    )
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(RuntimeError, match="Tradier paper order failed"):
        adapter.place_order(order)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_tradier_paper.py -v`
Expected: FAIL — `ModuleNotFoundError: app.data.tradier_paper`

- [ ] **Step 3: Implement the adapter**

Create `backend/app/data/tradier_paper.py`:

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import httpx

logger = logging.getLogger(__name__)

_SANDBOX_BASE = "https://sandbox.tradier.com/v1"

OrderType = Literal["MKT", "LMT"]
ActionType = Literal["BUY", "SELL"]
TIF = Literal["DAY", "GTC"]


@dataclass
class BrokerOrder:
    symbol: str
    action: ActionType
    quantity: int
    order_type: OrderType
    limit_price: float | None
    tif: TIF = "DAY"
    option_symbol: str | None = None   # OCC symbol e.g. "AAPL260620C00185000"


@dataclass
class OrderResult:
    order_id: str
    status: str
    broker: str
    message: str = ""


class TradierPaperAdapter:
    """Places orders on Tradier sandbox (paper) account.

    Sandbox endpoint: https://sandbox.tradier.com/v1/
    Get a sandbox token at: https://developer.tradier.com/
    """

    def __init__(self, token: str, account_id: str, timeout: float = 10.0) -> None:
        self._token = token
        self._account = account_id
        self._timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _build_params(self, order: BrokerOrder) -> dict:
        is_option = bool(order.option_symbol)
        params: dict = {
            "class":    "option" if is_option else "equity",
            "symbol":   order.symbol,
            "side":     order.action.lower(),
            "quantity": str(order.quantity),
            "type":     "market" if order.order_type == "MKT" else "limit",
            "duration": order.tif.lower(),
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            params["price"] = str(order.limit_price)
        if is_option:
            params["option_symbol"] = order.option_symbol
        return params

    def place_order(self, order: BrokerOrder) -> OrderResult:
        url = f"{_SANDBOX_BASE}/accounts/{self._account}/orders"
        try:
            resp = httpx.post(
                url, data=self._build_params(order),
                headers=self._headers(), timeout=self._timeout,
            )
        except Exception as exc:
            raise RuntimeError(f"Tradier paper order failed: connection error — {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Tradier paper order failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        data = resp.json().get("order", {})
        return OrderResult(
            order_id=str(data.get("id", "")),
            status=str(data.get("status", "unknown")),
            broker="tradier_paper",
            message=str(data.get("partner_id", "")),
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_tradier_paper.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/data/tradier_paper.py backend/tests/test_tradier_paper.py
git commit -m "feat(broker): Tradier sandbox paper adapter — equity and option orders"
```

---

## Task 5: Broker router + order endpoint

**Files:**
- Create: `backend/app/services/broker_router.py`
- Create: `backend/app/routers/broker.py`
- Create: `backend/tests/test_broker_router.py`

Note: `BrokerOrder` is defined in both adapters with the same shape. To avoid duplication, the router imports from `ibkr_paper` as the canonical definition (both have the same fields).

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_broker_router.py
import pytest
from unittest.mock import MagicMock, patch
from app.services.broker_router import BrokerRouter
from app.data.ibkr_paper import BrokerOrder, OrderResult


def test_router_routes_to_ibkr_paper():
    mock_adapter = MagicMock()
    mock_adapter.place_order.return_value = OrderResult(
        order_id="ORD1", status="PreSubmitted", broker="ibkr_paper"
    )
    router = BrokerRouter(adapters={"ibkr_paper": mock_adapter})
    order = BrokerOrder(symbol="AAPL", action="BUY", quantity=10,
                        order_type="LMT", limit_price=185.0, tif="DAY")
    result = router.execute("ibkr_paper", order)
    assert result.broker == "ibkr_paper"
    mock_adapter.place_order.assert_called_once_with(order)


def test_router_routes_to_tradier_paper():
    mock_adapter = MagicMock()
    mock_adapter.place_order.return_value = OrderResult(
        order_id="222", status="ok", broker="tradier_paper"
    )
    router = BrokerRouter(adapters={"tradier_paper": mock_adapter})
    order = BrokerOrder(symbol="NVDA", action="BUY", quantity=5,
                        order_type="MKT", limit_price=None, tif="DAY")
    result = router.execute("tradier_paper", order)
    assert result.order_id == "222"


def test_router_raises_for_unknown_broker():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="Unknown broker"):
        router.execute("nonexistent", order)


def test_router_raises_for_inactive_live():
    router = BrokerRouter(adapters={})
    order = BrokerOrder(symbol="X", action="BUY", quantity=1,
                        order_type="MKT", limit_price=None, tif="DAY")
    with pytest.raises(ValueError, match="live IBKR"):
        router.execute("ibkr_live", order)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_broker_router.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.broker_router`

- [ ] **Step 3: Implement broker router**

Create `backend/app/services/broker_router.py`:

```python
from __future__ import annotations

from app.data.ibkr_paper import BrokerOrder, OrderResult

_LIVE_BROKERS = {"ibkr_live"}  # Blocked until manually enabled in a future release.


class BrokerRouter:
    """Routes a BrokerOrder to the correct adapter by broker key.

    broker_key values: "ibkr_paper" | "tradier_paper"
    "ibkr_live" is prepared but blocked (raises ValueError).
    """

    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters

    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        if broker_key in _LIVE_BROKERS:
            raise ValueError(
                f"live IBKR trading is not yet activated. "
                "Enable it explicitly before use."
            )
        adapter = self._adapters.get(broker_key)
        if adapter is None:
            raise ValueError(
                f"Unknown broker '{broker_key}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        return adapter.place_order(order)


def build_router_from_credentials() -> BrokerRouter:
    """Build a BrokerRouter using live credentials from the credential store."""
    from app.services.credential_store import credential_store
    from app.data.ibkr_paper import IbkrPaperAdapter
    from app.data.tradier_paper import TradierPaperAdapter

    adapters = {}
    ibkr = credential_store.get("ibkr_paper")
    if ibkr and ibkr.get("account_id"):
        adapters["ibkr_paper"] = IbkrPaperAdapter(
            base_url=ibkr.get("base_url", "https://localhost:7499/v1/api"),
            account_id=ibkr["account_id"],
        )
    tradier = credential_store.get("tradier_paper")
    if tradier and tradier.get("token") and tradier.get("account_id"):
        adapters["tradier_paper"] = TradierPaperAdapter(
            token=tradier["token"],
            account_id=tradier["account_id"],
        )
    return BrokerRouter(adapters=adapters)
```

- [ ] **Step 4: Create the broker HTTP router**

Create `backend/app/routers/broker.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional

from app.data.ibkr_paper import BrokerOrder
from app.services.broker_router import build_router_from_credentials

router = APIRouter(prefix="/broker", tags=["broker"])

BrokerKey = Literal["ibkr_paper", "tradier_paper"]


class StockOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
    tif: Literal["DAY", "GTC"] = "DAY"


class OptionOrderRequest(BaseModel):
    broker: BrokerKey
    symbol: str
    option_symbol: str          # OCC format e.g. "AAPL260620C00185000"
    action: Literal["BUY", "SELL"]
    quantity: int
    order_type: Literal["MKT", "LMT"] = "LMT"
    limit_price: Optional[float] = None
    tif: Literal["DAY", "GTC"] = "DAY"
    conid: Optional[int] = None   # IBKR contract ID (required for IBKR)


@router.post("/stock-order")
async def place_stock_order(req: StockOrderRequest) -> dict:
    """Place a paper stock order on the specified broker."""
    router_ = build_router_from_credentials()
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        sec_type="STK",
    )
    try:
        result = router_.execute(req.broker, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.post("/option-order")
async def place_option_order(req: OptionOrderRequest) -> dict:
    """Place a paper options order on the specified broker."""
    router_ = build_router_from_credentials()
    order = BrokerOrder(
        symbol=req.symbol,
        action=req.action,
        quantity=req.quantity,
        order_type=req.order_type,
        limit_price=req.limit_price,
        tif=req.tif,
        conid=req.conid,
        sec_type="OPT",
        option_symbol=req.option_symbol,
    )
    try:
        result = router_.execute(req.broker, order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"order_id": result.order_id, "status": result.status, "broker": result.broker}


@router.get("/status")
async def broker_status() -> dict:
    """Return which brokers are configured (no credentials exposed)."""
    from app.services.credential_store import credential_store
    r = build_router_from_credentials()
    ibkr_ok  = "ibkr_paper"    in r._adapters
    trad_ok  = "tradier_paper" in r._adapters
    return {
        "ibkr_paper":    {"configured": ibkr_ok},
        "tradier_paper": {"configured": trad_ok},
        "ibkr_live":     {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
    }
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/test_broker_router.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/broker_router.py backend/app/routers/broker.py backend/tests/test_broker_router.py
git commit -m "feat(broker): BrokerRouter + /broker/stock-order and /broker/option-order endpoints"
```

---

## Task 6: Register routers + startup credential load

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add imports and router registration**

In `backend/app/main.py`, add after the existing router imports (after line 30):

```python
from app.routers.credentials import router as credentials_router
from app.routers.broker       import router as broker_router
```

In the `lifespan` function or the app startup, load credentials (add after `load_dotenv()` call, before `app = FastAPI(...)`):

```python
# Load persisted local credentials (gitignored file) on startup
from app.services.credential_store import credential_store  # noqa: F401 — triggers load
```

Add the two routers in the `app.include_router(...)` block (after `risk_settings_router`):

```python
app.include_router(credentials_router)
app.include_router(broker_router)
```

- [ ] **Step 2: Verify import**

Run: `cd backend && python -c "import app.main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(broker): register credentials + broker routers; load creds on startup"
```

---

## Task 7: Frontend — extend settingsStore for 4 broker accounts

**Files:**
- Modify: `frontend/lib/settingsStore.ts`
- Test: `frontend/lib/__tests__/settingsStore.test.ts`

Context: The current `BrokerConfig` holds one `broker`, `account`, `apiToken`, `paperTrading`. We need separate config objects for each of the four accounts while keeping the old `broker` field for backward compat (it's used elsewhere in the UI for display).

- [ ] **Step 1: Write failing test**

```ts
// append to frontend/lib/__tests__/settingsStore.test.ts
import { useSettingsStore, DEFAULT_IBKR_PAPER, DEFAULT_TRADIER_PAPER } from '@/lib/settingsStore';

describe('settingsStore — broker accounts', () => {
  it('has ibkrPaper and tradierPaper defaults', () => {
    const s = useSettingsStore.getState();
    expect(s.ibkrPaper.baseUrl).toBe('https://localhost:7499/v1/api');
    expect(s.tradierPaper.accountId).toBe('');
    expect(s.ibkrLive.enabled).toBe(false);
  });

  it('setIbkrPaper updates the config', () => {
    const s = useSettingsStore.getState();
    s.setIbkrPaper({ ...s.ibkrPaper, accountId: 'DU999' });
    expect(useSettingsStore.getState().ibkrPaper.accountId).toBe('DU999');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx jest --testPathPattern=settingsStore`
Expected: FAIL — property `ibkrPaper` undefined

- [ ] **Step 3: Extend settingsStore**

In `frontend/lib/settingsStore.ts`, add after the `BrokerConfig` interface:

```ts
export interface IbkrPaperConfig {
  baseUrl:   string;
  accountId: string;
}

export interface TradierPaperConfig {
  token:     string;
  accountId: string;
}

export interface IbkrLiveConfig {
  enabled: false;   // always false until manually unlocked in a future release
  note:    string;
}

export const DEFAULT_IBKR_PAPER: IbkrPaperConfig = {
  baseUrl:   'https://localhost:7499/v1/api',
  accountId: '',
};

export const DEFAULT_TRADIER_PAPER: TradierPaperConfig = {
  token:     '',
  accountId: '',
};

export const DEFAULT_IBKR_LIVE: IbkrLiveConfig = {
  enabled: false,
  note:    'Live IBKR trading is prepared but not yet activated.',
};
```

Add to `SettingsState`:
```ts
  ibkrPaper:     IbkrPaperConfig;
  tradierPaper:  TradierPaperConfig;
  ibkrLive:      IbkrLiveConfig;
  setIbkrPaper:    (c: IbkrPaperConfig)    => void;
  setTradierPaper: (c: TradierPaperConfig) => void;
```

Add to `migrateSettings` (new `version < 13` branch):
```ts
  if (version < 13) {
    next.ibkrPaper    = { ...DEFAULT_IBKR_PAPER };
    next.tradierPaper = { ...DEFAULT_TRADIER_PAPER };
    next.ibkrLive     = { ...DEFAULT_IBKR_LIVE };
  }
```

Add to initial store state:
```ts
ibkrPaper:     { ...DEFAULT_IBKR_PAPER },
tradierPaper:  { ...DEFAULT_TRADIER_PAPER },
ibkrLive:      { ...DEFAULT_IBKR_LIVE },
setIbkrPaper:    (c) => set({ ibkrPaper: c }),
setTradierPaper: (c) => set({ tradierPaper: c }),
```

Add to `resetToDefaults`:
```ts
ibkrPaper:    { ...DEFAULT_IBKR_PAPER },
tradierPaper: { ...DEFAULT_TRADIER_PAPER },
```

Add to `partialize`:
```ts
ibkrPaper:    state.ibkrPaper,
tradierPaper: state.tradierPaper,
```

Bump `version` from `12` to `13`.

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx jest --testPathPattern=settingsStore && npm run typecheck`
Expected: PASS, typecheck clean

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/settingsStore.ts frontend/lib/__tests__/settingsStore.test.ts
git commit -m "feat(broker): extend settingsStore — ibkrPaper, tradierPaper, ibkrLive (v13)"
```

---

## Task 8: Frontend — broker Settings panels

**Files:**
- Modify: `frontend/app/(frame)/settings/page.tsx`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add postCredentials to api.ts**

In `frontend/lib/api.ts`, add after `postScan`:

```ts
  postCredentials: (key: string, values: Record<string, string>) =>
    post<{ ok: boolean }>('/settings/credentials', { key, values }),

  getBrokerStatus: () =>
    get<{ ibkr_paper: { configured: boolean }; tradier_paper: { configured: boolean }; ibkr_live: { configured: boolean; enabled: boolean; note: string } }>('/broker/status'),
```

- [ ] **Step 2: Add four broker panels to Settings page**

In `frontend/app/(frame)/settings/page.tsx`:

Add to the `SECTIONS` array a new section:
```ts
{ key: 'brokers', label: 'Brokers', desc: 'Paper trading accounts + live IBKR preparation' },
```

Add `'brokers'` to the `Section` type.

Add `{active === 'brokers' && <BrokersForm />}` in the panel.

Implement `BrokersForm` as a new function in the same file:

```tsx
function BrokersForm() {
  const {
    ibkrPaper, setIbkrPaper,
    tradierPaper, setTradierPaper,
    ibkrLive,
  } = useSettingsStore();

  const [ibkrUrl,     setIbkrUrl]     = useState(ibkrPaper.baseUrl);
  const [ibkrAcct,    setIbkrAcct]    = useState(ibkrPaper.accountId);
  const [tradierTok,  setTradierTok]  = useState(tradierPaper.token);
  const [tradierAcct, setTradierAcct] = useState(tradierPaper.accountId);
  const [saving, setSaving] = useState<string | null>(null);

  async function saveIbkrPaper() {
    setSaving('ibkr');
    setIbkrPaper({ baseUrl: ibkrUrl, accountId: ibkrAcct });
    await api.postCredentials('ibkr_paper', { base_url: ibkrUrl, account_id: ibkrAcct });
    setSaving(null);
  }

  async function saveTradierPaper() {
    setSaving('tradier');
    setTradierPaper({ token: tradierTok, accountId: tradierAcct });
    await api.postCredentials('tradier_paper', { token: tradierTok, account_id: tradierAcct });
    setSaving(null);
  }

  return (
    <>
      <SectionIntro
        title="IBKR Paper account"
        blurb="Connect to your IBKR paper gateway (runs locally on a separate port from the live gateway). Typical URL: https://localhost:7499/v1/api"
      />
      <Row label="Gateway URL" hint="Paper gateway port is usually 7499" defaultValue="https://localhost:7499/v1/api">
        <input className={styles.input} value={ibkrUrl}
          onChange={(e) => setIbkrUrl(e.target.value)} />
      </Row>
      <Row label="Account ID" hint="Your IBKR paper account ID (DU...)" defaultValue="—">
        <input className={styles.input} value={ibkrAcct}
          onChange={(e) => setIbkrAcct(e.target.value)} />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveIbkrPaper} disabled={saving === 'ibkr'}>
            {saving === 'ibkr' ? 'Saving…' : 'Save IBKR Paper'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="Tradier Paper (Sandbox)"
        blurb="Tradier sandbox uses a separate token from your live account. Get one at developer.tradier.com."
      />
      <Row label="Sandbox token" hint="Different from your live Tradier token" defaultValue="—">
        <input className={styles.input} type="password"
          value={tradierTok} onChange={(e) => setTradierTok(e.target.value)} />
      </Row>
      <Row label="Account ID" hint="Your Tradier sandbox account ID (VA...)" defaultValue="—">
        <input className={styles.input} value={tradierAcct}
          onChange={(e) => setTradierAcct(e.target.value)} />
      </Row>
      <div className={styles.row}>
        <div className={styles.rowLabel} />
        <div className={styles.rowControl}>
          <button className={`${styles.btn} ${styles.btnPrimary}`}
            onClick={saveTradierPaper} disabled={saving === 'tradier'}>
            {saving === 'tradier' ? 'Saving…' : 'Save Tradier Paper'}
          </button>
        </div>
      </div>

      <SectionIntro
        title="IBKR Live (Locked)"
        blurb={ibkrLive.note}
      />
      <Row label="Live trading" hint="Requires explicit activation — not yet enabled" defaultValue="Off">
        <button className={styles.btn} disabled title="Locked until manually activated">
          🔒 Activate live IBKR
        </button>
      </Row>
    </>
  );
}
```

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: clean

- [ ] **Step 4: Run all frontend tests**

Run: `cd frontend && npx jest`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/settingsStore.ts frontend/lib/api.ts "frontend/app/(frame)/settings/page.tsx"
git commit -m "feat(broker): Settings Brokers panel — IBKR paper, Tradier paper, locked live IBKR"
```

---

## Task 9: End-to-end verification (WS-A)

- [ ] **Step 1: Run full backend suite**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass

- [ ] **Step 2: Run full frontend suite + typecheck**

Run: `cd frontend && npx jest && npm run typecheck`
Expected: all pass, typecheck clean

- [ ] **Step 3: Manual smoke (dev server)**
1. Start backend + frontend
2. Go to Settings → Brokers
3. Enter fake IBKR paper URL + account ID, click Save → verify backend receives POST to /settings/credentials
4. Check GET /broker/status returns `ibkr_paper.configured: true` after save
5. Verify `backend/config/local_credentials.yaml` exists and is gitignored
6. Restart backend → verify credentials are reloaded (GET /broker/status still shows configured)

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(broker): WS-A verification fixups" --allow-empty
```

---

## Self-Review

**Spec coverage:**
- ✅ IBKR paper credentials stored in Settings, not .env
- ✅ Tradier paper credentials in Settings
- ✅ Credentials persisted to gitignored local file (survive restart)
- ✅ Credentials POST to backend endpoint
- ✅ Live IBKR: grayed-out with lock icon
- ✅ BrokerRouter unified interface (used by WS-B and WS-C)
- ✅ /broker/option-order endpoint (needed by WS-C)

**Not in scope for WS-A (covered by WS-B/WS-C):**
- Broker picker in screener workflow
- Auto-trading triggers
