# Stage 4: Alpaca Paper Execution Adapter + Position Card Button — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Alpaca Paper as a fourth execution venue for stock orders: adapter → broker router → REST endpoint update → Position Card UI button.

**Architecture:** Mirrors the existing IBKR Paper / Tradier Paper pattern exactly. A new `AlpacaPaperAdapter.place_order()` calls Alpaca's `POST /v2/orders` using credentials from the credential store. `build_router_from_credentials()` builds it when the `alpaca_paper` slot has a `key_id`. `alpaca_live` is added to `_LIVE_BROKERS` (blocked). The Position Card page fetches `/broker/status` at mount and shows an "Alpaca Paper" execution mode button when `alpaca_paper.configured == true`.

**Tech Stack:** Python 3.14, FastAPI, httpx (sync), pytest; TypeScript 5.7, React, CSS Modules.

**Source spec:** `docs/superpowers/specs/2026-06-11-data-loading-and-provider-governor-design.md` §5.8.

---

## File Structure

- **Create** `backend/app/data/alpaca_paper_execution.py` — `AlpacaPaperAdapter` stock order adapter
- **Modify** `backend/app/services/broker_router.py` — register `alpaca_paper`, add `alpaca_live` to `_LIVE_BROKERS`
- **Modify** `backend/app/routers/broker.py` — extend `BrokerKey` type + update `/broker/status`
- **Create** `backend/tests/test_alpaca_paper_execution.py` — unit tests for the adapter
- **Modify** `frontend/app/(frame)/screener/step-7-position-card/page.tsx` — add `alpaca_paper` execution mode button

Run backend tests from `backend/`. Frontend changes: verify visually; typecheck with `cd frontend && npm run typecheck`.

---

### Task 1: AlpacaPaperAdapter + broker_router registration

**Files:**
- Create: `backend/app/data/alpaca_paper_execution.py`
- Create: `backend/tests/test_alpaca_paper_execution.py`
- Modify: `backend/app/services/broker_router.py`
- Modify: `backend/app/routers/broker.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_alpaca_paper_execution.py`:

```python
"""Unit tests for AlpacaPaperAdapter — no real network calls."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.data.alpaca_paper_execution import AlpacaPaperAdapter
from app.data.ibkr_paper import BrokerOrder, OrderResult


def _alpaca_order_resp(order_id: str = "abc123", status: str = "accepted") -> httpx.Response:
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    return httpx.Response(
        200,
        json={"id": order_id, "status": status, "symbol": "AAPL"},
        request=request,
    )


def test_place_market_order_returns_order_result():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=10,
        order_type="MKT", limit_price=None, tif="DAY", sec_type="STK",
    )
    with patch.object(httpx, "post", return_value=_alpaca_order_resp("order-001", "accepted")):
        result = adapter.place_order(order)
    assert isinstance(result, OrderResult)
    assert result.order_id == "order-001"
    assert result.status == "accepted"
    assert result.broker == "alpaca_paper"


def test_place_limit_order_includes_limit_price():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="MSFT", action="BUY", quantity=5,
        order_type="LMT", limit_price=380.50, tif="GTC", sec_type="STK",
    )
    captured = {}

    def mock_post(url, *, json, headers, timeout):
        captured.update(json)
        return _alpaca_order_resp("order-002")

    with patch.object(httpx, "post", side_effect=mock_post):
        adapter.place_order(order)

    assert captured.get("limit_price") == 380.50
    assert captured.get("type") == "limit"
    assert captured.get("time_in_force") == "gtc"


def test_place_order_raises_on_http_error():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="TSLA", action="BUY", quantity=1,
        order_type="MKT", limit_price=None, sec_type="STK",
    )
    request = httpx.Request("POST", "https://paper-api.alpaca.markets/v2/orders")
    bad_resp = httpx.Response(403, json={"message": "forbidden"}, request=request)
    with patch.object(httpx, "post", return_value=bad_resp):
        with pytest.raises(RuntimeError, match="403"):
            adapter.place_order(order)


def test_options_order_raises_not_supported():
    adapter = AlpacaPaperAdapter(key_id="key1", secret_key="secret1")
    order = BrokerOrder(
        symbol="AAPL", action="BUY", quantity=1,
        order_type="MKT", limit_price=None, sec_type="OPT",
        option_symbol="AAPL250117C00200000",
    )
    with pytest.raises(ValueError, match="stock"):
        adapter.place_order(order)
```

- [ ] **Step 2: Run tests — confirm FAIL**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_alpaca_paper_execution.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.data.alpaca_paper_execution'`

- [ ] **Step 3: Create `backend/app/data/alpaca_paper_execution.py`**

```python
"""Alpaca Paper execution adapter.

Places stock (STK) orders via the Alpaca Paper trading API.
Options orders are not supported (Alpaca requires options-trading approval
which is separate from data entitlements; stay in scope: stocks only).

Mirrors the IbkrPaperAdapter interface: synchronous place_order().
"""
from __future__ import annotations

import logging

import httpx

from app.data.ibkr_paper import BrokerOrder, OrderResult

logger = logging.getLogger(__name__)

_PAPER_BASE = "https://paper-api.alpaca.markets"
_ORDERS_ENDPOINT = f"{_PAPER_BASE}/v2/orders"

# Alpaca TIF mapping (our internal → Alpaca's lowercase strings)
_TIF_MAP = {"DAY": "day", "GTC": "gtc"}
# Alpaca order type mapping
_TYPE_MAP = {"MKT": "market", "LMT": "limit"}


class AlpacaPaperAdapter:
    """Places stock orders on an Alpaca Paper account.

    Uses the Alpaca v2 orders REST API. Supports market and limit orders,
    DAY and GTC time-in-force. Stock orders only.
    """

    def __init__(self, key_id: str, secret_key: str, timeout: float = 10.0) -> None:
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _build_payload(self, order: BrokerOrder) -> dict:
        payload: dict = {
            "symbol":        order.symbol,
            "qty":           str(order.quantity),
            "side":          order.action.lower(),   # "buy" | "sell"
            "type":          _TYPE_MAP[order.order_type],
            "time_in_force": _TIF_MAP.get(order.tif, "day"),
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            payload["limit_price"] = order.limit_price
        return payload

    def place_order(self, order: BrokerOrder) -> OrderResult:
        """Place a paper stock order on Alpaca. Raises RuntimeError on failure."""
        if order.sec_type != "STK":
            raise ValueError(
                "AlpacaPaperAdapter only supports stock (STK) orders — "
                f"received sec_type='{order.sec_type}'"
            )
        payload = self._build_payload(order)
        try:
            resp = httpx.post(
                _ORDERS_ENDPOINT,
                json=payload,
                headers=self._headers,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise RuntimeError(f"Alpaca paper order failed: connection error — {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(
                f"Alpaca paper order failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        data = resp.json()
        return OrderResult(
            order_id=data.get("id", "unknown"),
            status=data.get("status", "unknown"),
            broker="alpaca_paper",
        )
```

- [ ] **Step 4: Run tests — confirm PASS**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest tests/test_alpaca_paper_execution.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Update `backend/app/services/broker_router.py`**

Replace the contents of the file:

```python
from __future__ import annotations

from app.data.ibkr_paper import BrokerOrder, OrderResult

# "alpaca_live" prepared end-to-end but blocked at the router until manually enabled.
_LIVE_BROKERS = {"ibkr_live", "alpaca_live"}


class BrokerRouter:
    """Routes a BrokerOrder to the correct adapter by broker key.

    broker_key values: "ibkr_paper" | "tradier_paper" | "alpaca_paper"
    "ibkr_live" and "alpaca_live" are prepared but blocked.
    """

    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters

    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        if broker_key in _LIVE_BROKERS:
            raise ValueError(
                f"live trading on '{broker_key}' is not yet activated. "
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
    from app.data.alpaca_paper_execution import AlpacaPaperAdapter

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

    alpaca_paper = credential_store.get("alpaca_paper")
    if alpaca_paper and alpaca_paper.get("key_id") and alpaca_paper.get("secret_key"):
        adapters["alpaca_paper"] = AlpacaPaperAdapter(
            key_id=alpaca_paper["key_id"],
            secret_key=alpaca_paper["secret_key"],
        )

    return BrokerRouter(adapters=adapters)
```

- [ ] **Step 6: Update `/broker/status` and `BrokerKey` in `backend/app/routers/broker.py`**

Change `BrokerKey` type alias:
```python
BrokerKey = Literal["ibkr_paper", "tradier_paper", "alpaca_paper"]
```

Replace the `broker_status` function:
```python
@router.get("/status")
async def broker_status() -> dict:
    """Return which brokers are configured (no credentials exposed)."""
    r = build_router_from_credentials()
    ibkr_ok    = "ibkr_paper"    in r._adapters
    trad_ok    = "tradier_paper" in r._adapters
    alpaca_ok  = "alpaca_paper"  in r._adapters
    return {
        "ibkr_paper":    {"configured": ibkr_ok},
        "tradier_paper": {"configured": trad_ok},
        "alpaca_paper":  {"configured": alpaca_ok},
        "ibkr_live":     {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
        "alpaca_live":   {"configured": False, "enabled": False, "note": "Locked — not yet activated"},
    }
```

- [ ] **Step 7: Run full backend suite**

```bash
cd "F:/Git/GitHub/Trading assistant/backend"
python -m pytest -q
```

Expected: all pass.

- [ ] **Step 8: Commit backend changes**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add backend/app/data/alpaca_paper_execution.py backend/tests/test_alpaca_paper_execution.py backend/app/services/broker_router.py backend/app/routers/broker.py
git commit -m "feat(broker): AlpacaPaperAdapter, register alpaca_paper, lock alpaca_live"
```

---

### Task 2: Position Card — Alpaca Paper execution mode button

**Files:**
- Modify: `frontend/app/(frame)/screener/step-7-position-card/page.tsx`

The Position Card page already has `ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper'` and renders `ExecutionModeButton` for each mode. We add `'alpaca_paper'` to the type, fetch broker status at mount, and render a fourth button.

- [ ] **Step 1: Update the file**

Open `frontend/app/(frame)/screener/step-7-position-card/page.tsx`.

**Change 1:** Add `alpaca_paper` to the `ExecutionMode` type at the top of the file:
```typescript
type ExecutionMode = 'recommendation' | 'ibkr_paper' | 'tradier_paper' | 'alpaca_paper';
```

**Change 2:** Add `alpacaPaperConfigured` state (fetched from `/broker/status` at mount). Add this after the existing `tradierConfigured` declaration:
```typescript
  const [alpacaPaperConfigured, setAlpacaPaperConfigured] = useState(false);
```

**Change 3:** Add a `useEffect` that calls `api.getBrokerStatus()` at mount to check if Alpaca Paper is configured. Add it after the existing state declarations:
```typescript
  useEffect(() => {
    api.getBrokerStatus()
      .then((s) => setAlpacaPaperConfigured(s.alpaca_paper?.configured ?? false))
      .catch(() => {});
  }, []);
```

**Change 4:** Update the `api.ts` return type so `getBrokerStatus()` knows about `alpaca_paper`. In `frontend/lib/api.ts`, find the `getBrokerStatus` return type and add `alpaca_paper`:

```typescript
  getBrokerStatus: () =>
    get<{
      ibkr_paper:    { configured: boolean };
      tradier_paper: { configured: boolean };
      alpaca_paper:  { configured: boolean };
      ibkr_live:     { configured: boolean; enabled: boolean; note: string };
      alpaca_live?:  { configured: boolean; enabled: boolean; note: string };
    }>('/broker/status'),
```

**Change 5:** Add the `ExecutionModeButton` for Alpaca Paper in the button group. Find where the existing `ibkr_paper` and `tradier_paper` buttons are rendered and add a third one after them:

```tsx
              <ExecutionModeButton
                label="Alpaca Paper"
                desc="Direct stock order"
                active={execMode === 'alpaca_paper'}
                disabled={!alpacaPaperConfigured}
                onClick={() => setExecMode('alpaca_paper')}
              />
```

- [ ] **Step 2: Run typecheck**

```bash
cd "F:/Git/GitHub/Trading assistant/frontend"
npm run typecheck
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
cd "F:/Git/GitHub/Trading assistant"
git add "frontend/app/(frame)/screener/step-7-position-card/page.tsx" frontend/lib/api.ts
git commit -m "feat(position-card): Alpaca Paper execution mode button"
```

---

## Self-Review

**Spec coverage (§5.8):**
- ✅ `AlpacaPaperAdapter.place_order()` → `POST {paper-api}/v2/orders`; returns `OrderResult(broker="alpaca_paper")`
- ✅ `alpaca_paper` registered in `build_router_from_credentials()`
- ✅ `alpaca_live` added to `_LIVE_BROKERS` (prepared-but-locked)
- ✅ `/broker/status` includes `alpaca_paper: {configured}` and `alpaca_live: {..., note: "Locked"}`
- ✅ Stock orders only (OPT raises `ValueError`)
- ✅ Position Card "Alpaca Paper" button, disabled until configured
- ✅ Uses same credentials as data adapter (`alpaca_paper.key_id` / `secret_key`)

**Not in scope:**
- Options execution via Alpaca (spec: "stock orders only")
- Frontend Settings page for Alpaca credentials (settings store update)
- Alpaca live execution (blocked at router)

**Type consistency:** `AlpacaPaperAdapter(key_id, secret_key)`, `place_order(order: BrokerOrder) → OrderResult`, `BrokerKey = "ibkr_paper" | "tradier_paper" | "alpaca_paper"` — consistent across Task 1.
