from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Literal, Optional

import httpx
import urllib3

warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)

import time
import threading

_PAPER_BASE = "https://localhost:7499/v1/api"
_PAPER_TIMEOUT = 8
_auth_cache: dict | None = None
_AUTH_TTL = 40.0
_auth_lock = threading.Lock()


def paper_gateway_available() -> bool:
    """Return True if the IBKR paper gateway is running and authenticated.

    Mirrors app.data.ibkr.ibkr_available() — separate cache because the paper
    and live gateways run as independent processes on different ports.
    Result is cached for 60 seconds. On success, also fires a POST /tickle
    keep-alive (fire-and-forget, errors ignored).
    """
    global _auth_cache
    now = time.monotonic()
    with _auth_lock:
        if _auth_cache is not None and now < _auth_cache["expires"]:
            return _auth_cache["result"]

    try:
        resp = httpx.get(f"{_PAPER_BASE}/iserver/auth/status", verify=False, timeout=_PAPER_TIMEOUT)
        resp.raise_for_status()
        authenticated = bool(resp.json().get("authenticated", False))
    except Exception as exc:
        logger.debug("IBKR paper auth check failed: %s", exc)
        with _auth_lock:
            _auth_cache = {"result": False, "expires": now + _AUTH_TTL}
        return False

    with _auth_lock:
        _auth_cache = {"result": authenticated, "expires": now + _AUTH_TTL}

    if authenticated:
        try:
            httpx.post(f"{_PAPER_BASE}/tickle", verify=False, timeout=_PAPER_TIMEOUT)
        except Exception:
            pass

    return authenticated


OrderType = Literal["MKT", "LMT"]
ActionType = Literal["BUY", "SELL"]
TIF = Literal["DAY", "GTC"]


@dataclass
class BrokerOrder:
    symbol: str
    action: ActionType
    quantity: int
    order_type: OrderType
    limit_price: Optional[float]
    tif: TIF = "DAY"
    conid: Optional[int] = None          # IBKR contract ID (options)
    sec_type: str = "STK"                # "STK" or "OPT"
    option_symbol: Optional[str] = None  # OCC symbol for options


@dataclass
class OrderResult:
    order_id: str
    status: str
    broker: str
    message: str = ""


class IbkrPaperAdapter:
    """Places orders on an IBKR paper account via the Client Portal Web API.

    The paper gateway must be running locally (separate from the live gateway).
    Typical URL: https://localhost:7499/v1/api
    """

    def __init__(self, base_url: str, account_id: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._account = account_id
        self._timeout = timeout

    def _build_payload(self, order: BrokerOrder) -> dict:
        o: dict = {
            "orderType": order.order_type,
            "side": order.action,
            "quantity": order.quantity,
            "tif": order.tif,
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            o["price"] = order.limit_price
        if order.conid:
            o["conidex"] = str(order.conid)
            o["secType"] = f"{order.conid}:{order.sec_type}"
        else:
            o["symbol"] = order.symbol
            o["secType"] = order.sec_type
        return {"orders": [o]}

    def place_order(self, order: BrokerOrder) -> OrderResult:
        if not paper_gateway_available():
            raise RuntimeError(
                "IBKR paper order failed: gateway session is not authenticated. "
                "Re-login to the IBKR paper Client Portal Gateway and retry."
            )
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
