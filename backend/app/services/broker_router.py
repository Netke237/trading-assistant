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
