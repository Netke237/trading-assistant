from __future__ import annotations

from app.data.ibkr_paper import BrokerOrder, OrderResult
from app.services.credential_store import LIVE_BROKER_KEYS as _LIVE_BROKERS  # single source of truth


class BrokerRouter:
    """Routes a BrokerOrder to the correct adapter by broker key.

    broker_key values: "ibkr_paper" | "tradier_paper" | "alpaca_paper" | "tastytrade_paper"
    "ibkr_live" / "tradier_live" / "alpaca_live" / "tastytrade_live" are prepared but
    blocked (raises ValueError).
    """

    def __init__(self, adapters: dict) -> None:
        self._adapters = adapters

    def resolve(self, broker_key: str):
        """The adapter for `broker_key`, or ValueError. CONTACTS NOTHING.

        SPLIT OUT OF `execute` BY F2 OF 2A-ALERT ROUND 1, and the split is the
        fix rather than a tidy-up. Both raises below happen BEFORE
        `adapter.place_order` — the only call in this file that can put an order
        in front of a broker — but a caller that only saw `execute` raise could
        not tell them from a submission that errored mid-flight. `auto_trader`
        paged "THE ORDER MAY HAVE LANDED. Check the broker" for both, and the
        common way in is mundane: credentials expire or get rotated,
        `build_router_from_credentials` silently omits that adapter, and the
        dict lookup below raises "Unknown broker". Nothing was sent, and Kenneth
        was sent hunting a position that does not exist.

        The unknown-broker message therefore has to carry weight it did not
        before: it is what the operator reads in the alert, and an empty
        `Available:` list is the signal that the credential store came back
        bare rather than that a key was mistyped.
        """
        if broker_key in _LIVE_BROKERS:
            raise ValueError(
                f"live trading via '{broker_key}' is not yet activated. "
                "Enable it explicitly before use."
            )
        adapter = self._adapters.get(broker_key)
        if adapter is None:
            raise ValueError(
                f"Unknown broker '{broker_key}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        return adapter

    def execute(self, broker_key: str, order: BrokerOrder) -> OrderResult:
        """Resolve then submit. Unchanged for every caller that does not need
        the boundary — `routers/broker.py` handles its own errors per request
        and has a human watching the response, so it keeps the one-call form.
        """
        return self.resolve(broker_key).place_order(order)


def build_router_from_credentials() -> BrokerRouter:
    """Build a BrokerRouter using live credentials from the credential store."""
    from app.services.credential_store import credential_store
    credential_store.load()  # pick up any yaml edits without requiring a restart
    from app.data.ibkr_paper import IbkrPaperAdapter
    from app.data.tradier_paper import TradierPaperAdapter
    from app.data.alpaca_paper_execution import AlpacaPaperAdapter
    from app.data.tastytrade_paper import TastytradePaperAdapter

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
    tastytrade = credential_store.get("tastytrade_paper")
    if tastytrade and tastytrade.get("client_secret") and tastytrade.get("refresh_token") and tastytrade.get("account_id"):
        adapters["tastytrade_paper"] = TastytradePaperAdapter(account_id=tastytrade["account_id"])
    return BrokerRouter(adapters=adapters)
