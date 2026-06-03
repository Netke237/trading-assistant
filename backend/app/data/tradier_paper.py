from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

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
    limit_price: Optional[float]
    tif: TIF = "DAY"
    option_symbol: Optional[str] = None   # OCC symbol e.g. "AAPL260620C00185000"
    conid: Optional[int] = None           # unused by Tradier, kept for interface compat
    sec_type: str = "STK"                 # unused by Tradier, kept for interface compat


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
