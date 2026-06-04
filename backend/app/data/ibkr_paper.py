from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Literal, Optional

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
