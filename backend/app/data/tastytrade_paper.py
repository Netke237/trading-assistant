"""Tastytrade paper-account order execution.

Places stock (STK) and option (OPT) orders on a tastytrade paper-trading
account via the tastytrade SDK. Synchronous place_order() wraps the SDK's
async calls via tastytrade_bridge.run_coro (Task 6) rather than a raw
asyncio.run() — this adapter's calls compete for the same Governor-gated
"tastytrade" token bucket as the IV-metrics fetcher (Task 7) and the health
probe (Task 11), and routing all three through the same shared event loop
avoids the cross-loop asyncio.Lock hazard a bare asyncio.run() per call site
would reintroduce. The resulting place_order(order) -> OrderResult interface
is otherwise identical to IbkrPaperAdapter / AlpacaPaperAdapter — broker_router.py
and every caller in this codebase expects a synchronous place_order(order).

Only "tastytrade_paper" credentials are ever used here. "tastytrade_live" is
prepared in the credential store and in broker_router.py's _KNOWN_LIVE_BROKERS
block list, but no adapter reads tastytrade_live credentials for order
placement anywhere in this codebase — mirrors the ibkr_live/tradier_live/
alpaca_live pattern exactly.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from tastytrade import Account
from tastytrade.instruments import Equity, get_option_chain
from tastytrade.order import LimitOrder, OrderAction

from app.data.ibkr_paper import BrokerOrder, OrderResult
from app.data.tastytrade_bridge import run_coro
from app.data.tastytrade_session import get_session

logger = logging.getLogger(__name__)

# NOTE: only covers opening/closing a long position (BUY -> BUY_TO_OPEN,
# SELL -> SELL_TO_CLOSE) for both STK and OPT. tastytrade's real OrderAction
# is a 4-way enum (BUY_TO_OPEN/BUY_TO_CLOSE/SELL_TO_OPEN/SELL_TO_CLOSE), but
# BrokerOrder has no field indicating open-vs-close intent, so there is
# currently no way for any caller to request "sell to open" (writing/shorting
# an option) through this shared interface — not just through tastytrade's
# adapter specifically. This matches the shape of every existing BrokerOrder
# caller in this codebase today (long calls/puts, long stock). Known,
# accepted limitation — not fixed in this task.
_ACTION_MAP = {
    ("BUY", "STK"):  OrderAction.BUY_TO_OPEN,
    ("SELL", "STK"): OrderAction.SELL_TO_CLOSE,
    ("BUY", "OPT"):  OrderAction.BUY_TO_OPEN,
    ("SELL", "OPT"): OrderAction.SELL_TO_CLOSE,
}


class TastytradePaperAdapter:
    def __init__(self, account_id: str) -> None:
        self._account_id = account_id

    async def _resolve_leg(self, session, order: BrokerOrder):
        action = _ACTION_MAP.get((order.action, order.sec_type))
        if action is None:
            raise ValueError(
                f"Unsupported action/sec_type combination: {order.action}/{order.sec_type}"
            )
        if order.sec_type == "STK":
            instrument = await Equity.get(session, order.symbol)
            return instrument.build_leg(order.quantity, action)
        if order.sec_type == "OPT":
            if not order.option_symbol:
                raise ValueError("OPT orders require order.option_symbol (OCC symbol)")
            chain = await get_option_chain(session, order.symbol)
            for expiry_options in chain.values():
                for opt in expiry_options:
                    if opt.symbol == order.option_symbol:
                        return opt.build_leg(order.quantity, action)
            raise ValueError(f"Option contract not found in chain: {order.option_symbol}")
        raise ValueError(f"Unsupported sec_type: {order.sec_type}")

    async def _place_order_async(self, order: BrokerOrder) -> OrderResult:
        session = get_session("tastytrade_paper")
        if session is None:
            raise RuntimeError(
                "tastytrade paper order failed: account not configured. "
                "Add client_secret/refresh_token in Settings → Brokers."
            )
        try:
            account = await Account.get(session, self._account_id)
        except Exception as acct_exc:
            # "record_not_found / Couldn't find Account" means the configured
            # account number doesn't belong to the logged-in tastytrade user
            # (or is mistyped). Surface an actionable message rather than the
            # raw SDK error — and raise it directly (not through the generic
            # try/except below) so it isn't re-wrapped as
            # "tastytrade paper order failed: tastytrade could not find...".
            # A RuntimeError from anywhere else in this method (place_order,
            # SDK internals) is NOT this case and must still get the generic
            # wrap for consistency with every other failure path.
            if "record_not_found" in str(acct_exc) or "find Account" in str(acct_exc):
                raise RuntimeError(
                    f"tastytrade could not find account '{self._account_id}'. "
                    "Check the account number under Settings → Brokers → "
                    "Tastytrade Paper matches an account on the logged-in "
                    "tastytrade profile (client_secret / refresh_token)."
                ) from acct_exc
            raise RuntimeError(f"tastytrade paper order failed: {acct_exc}") from acct_exc

        try:
            leg = await self._resolve_leg(session, order)
            if order.order_type != "LMT" or order.limit_price is None:
                raise ValueError(
                    "TastytradePaperAdapter only supports limit orders "
                    "(tastytrade options orders require a price)."
                )
            # tastytrade LimitOrder price convention: negative = debit (you
            # pay), positive = credit (you receive) — a BUY is always a debit.
            # Confirmed against the installed tastytrade SDK source itself
            # (order.py's get_sign/set_sign_for), not just documentation, and
            # locked in by test_place_order_stock_success's exact
            # Decimal("-150.0") assertion. Still worth a real paper-account
            # order as a final sanity check before this is trusted with size.
            price = Decimal(str(order.limit_price))
            if order.action == "BUY":
                price = -abs(price)
            else:
                price = abs(price)
            new_order = LimitOrder(legs=[leg], price=price)
            response = await account.place_order(session, new_order, dry_run=False)
        except Exception as exc:
            raise RuntimeError(f"tastytrade paper order failed: {exc}") from exc

        return OrderResult(
            order_id=str(response.order.id),
            status=str(response.order.status),
            broker="tastytrade_paper",
        )

    def place_order(self, order: BrokerOrder) -> OrderResult:
        return run_coro(self._place_order_async(order))
