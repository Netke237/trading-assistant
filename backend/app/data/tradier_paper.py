from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional

import httpx

from app.data.option_symbol import to_occ
from app.data.order_errors import OrderAdmissionRefusedError

logger = logging.getLogger(__name__)

_SANDBOX_BASE = "https://sandbox.tradier.com/v1"

OrderType = Literal["MKT", "LMT"]
ActionType = Literal["BUY", "SELL"]
Effect = Literal["OPEN", "CLOSE"]
TIF = Literal["DAY", "GTC"]

# Tradier option orders require explicit open/close side semantics — plain "buy"/"sell"
# is only valid for equity orders. Keyed on (action, effect).
_OPTION_SIDE = {
    ("BUY",  "OPEN"):  "buy_to_open",
    ("SELL", "OPEN"):  "sell_to_open",
    ("SELL", "CLOSE"): "sell_to_close",
    ("BUY",  "CLOSE"): "buy_to_close",
}

# Tradier equity orders also distinguish open vs. close explicitly — sell_short opens
# a new short, buy_to_cover closes one. Plain buy/sell close-a-long/open-a-long only.
_EQUITY_SIDE = {
    ("BUY",  "OPEN"):  "buy",
    ("SELL", "OPEN"):  "sell_short",
    ("SELL", "CLOSE"): "sell",
    ("BUY",  "CLOSE"): "buy_to_cover",
}


@dataclass
class BrokerOrder:
    symbol: str
    action: ActionType
    effect: Effect  # see ibkr_paper.BrokerOrder.effect — same shape, separate dataclass
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
            "side":     (_OPTION_SIDE if is_option else _EQUITY_SIDE)[(order.action, order.effect)],
            "quantity": str(order.quantity),
            "type":     "market" if order.order_type == "MKT" else "limit",
            "duration": order.tif.lower(),
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            params["price"] = str(order.limit_price)
        if is_option:
            params["option_symbol"] = to_occ(order.option_symbol)
        return params

    def place_order(self, order: BrokerOrder) -> OrderResult:
        from app.data.governor import get_governor
        url = f"{_SANDBOX_BASE}/accounts/{self._account}/orders"
        # Admitted on the sandbox account's own budget before anything is sent
        # (TRADIER-GOVERNOR D4). A typed refusal proves no POST was attempted,
        # allowing dispatch callers to release their durable risk reservation.
        if not get_governor().admit_sync("tradier_paper", admit_timeout=float(self._timeout)):
            msg = "Tradier paper order failed: rate-limit budget busy — order not sent"
            logger.error(msg)
            raise OrderAdmissionRefusedError(msg)
        try:
            resp = httpx.post(
                url, data=self._build_params(order),
                headers=self._headers(), timeout=self._timeout,
            )
        except Exception as exc:
            msg = f"Tradier paper order failed: connection error — {exc}"
            logger.error(msg)
            raise RuntimeError(msg) from exc
        if resp.status_code == 401:
            # A live (api.tradier.com) token does NOT work against the sandbox
            # endpoint, and sandbox tokens are rotated/expire — the most common
            # cause of this once-working path breaking. Make the fix actionable
            # instead of surfacing a raw "Invalid Access Token".
            msg = (
                "Tradier paper order rejected: 401 Invalid Access Token. The "
                "sandbox (paper) token is missing or expired. Re-generate it at "
                "developer.tradier.com and paste it under Settings → Brokers → "
                "Tradier Paper. Note: a live api.tradier.com token cannot place "
                "sandbox/paper orders."
            )
            logger.error("%s (raw: %s)", msg, resp.text[:300])
            raise RuntimeError(msg)
        if resp.status_code >= 400:
            msg = f"Tradier paper order failed: HTTP {resp.status_code} — {resp.text[:500]}"
            logger.error(msg)
            raise RuntimeError(msg)
        data = resp.json().get("order", {})
        return OrderResult(
            order_id=str(data.get("id", "")),
            status=str(data.get("status", "unknown")),
            broker="tradier_paper",
            message=str(data.get("partner_id", "")),
        )
