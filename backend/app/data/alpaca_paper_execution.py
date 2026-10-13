"""Alpaca Paper execution adapter.

Places stock (STK) orders via the Alpaca Paper trading API.
Options orders are not supported (stock orders only).

Mirrors the IbkrPaperAdapter interface: synchronous place_order().
"""
from __future__ import annotations

import logging

import httpx

from app.data.ibkr_paper import BrokerOrder, OrderResult
from app.data.order_errors import OrderPreflightRefusedError, OrderSubmissionUnknownError

logger = logging.getLogger(__name__)

_PAPER_BASE = "https://paper-api.alpaca.markets"
_ORDERS_ENDPOINT = f"{_PAPER_BASE}/v2/orders"

_TIF_MAP = {"DAY": "day", "GTC": "gtc"}
_TYPE_MAP = {"MKT": "market", "LMT": "limit"}


class AlpacaPaperAdapter:
    def __init__(self, key_id: str, secret_key: str, timeout: float = 10.0) -> None:
        self._headers = {
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _build_payload(self, order: BrokerOrder) -> dict:
        # order.effect is intentionally unused here — Alpaca infers open-vs-close from
        # current account position given a plain buy/sell side, same as IBKR.
        payload: dict = {
            "symbol":        order.symbol,
            "qty":           str(order.quantity),
            "side":          order.action.lower(),
            "type":          _TYPE_MAP[order.order_type],
            "time_in_force": _TIF_MAP.get(order.tif, "day"),
        }
        if order.order_type == "LMT" and order.limit_price is not None:
            payload["limit_price"] = order.limit_price
        return payload

    def place_order(self, order: BrokerOrder) -> OrderResult:
        """Place a paper stock order on Alpaca. Raises RuntimeError on failure."""
        if order.sec_type != "STK":
            raise OrderPreflightRefusedError(
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
            raise OrderSubmissionUnknownError(
                f"Alpaca paper order failed: connection error — {exc}"
            ) from exc
        if resp.status_code >= 400:
            raise OrderSubmissionUnknownError(
                f"Alpaca paper order failed: HTTP {resp.status_code} — {resp.text[:200]}"
            )
        try:
            data = resp.json()
        except ValueError as exc:
            raise OrderSubmissionUnknownError(
                f"Alpaca paper order failed: response was not JSON — {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise OrderSubmissionUnknownError(
                "Alpaca paper order failed: response was not an order object"
            )
        return OrderResult(
            order_id=data.get("id", "unknown"),
            status=data.get("status", "unknown"),
            broker="alpaca_paper",
        )
