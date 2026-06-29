from __future__ import annotations

from app.data.ibkr_paper import BrokerOrder, OrderResult

_LIVE_BROKERS = {"ibkr_live", "alpaca_live"}  # Blocked until manually enabled in a future release.


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
    credential_store.load()  # pick up any yaml edits without requiring a restart
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
    import os as _os
    tradier = credential_store.get("tradier_paper") or {}
    tradier_token = (tradier.get("token") or "").strip() or _os.environ.get("TRADIER_PAPER_TOKEN", "").strip()
    tradier_account = (tradier.get("account_id") or "").strip() or _os.environ.get("TRADIER_PAPER_ACCOUNT_ID", "").strip()
    if tradier_token and tradier_account:
        adapters["tradier_paper"] = TradierPaperAdapter(
            token=tradier_token,
            account_id=tradier_account,
        )
    alpaca = credential_store.get("alpaca_paper")
    if alpaca and alpaca.get("key_id") and alpaca.get("secret_key"):
        adapters["alpaca_paper"] = AlpacaPaperAdapter(
            key_id=alpaca["key_id"],
            secret_key=alpaca["secret_key"],
        )
    return BrokerRouter(adapters=adapters)
