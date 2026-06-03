from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ArmedStrategy:
    broker:        str
    symbol:        str
    option_symbol: str
    action:        Literal["BUY", "SELL"]
    quantity:      int
    order_type:    Literal["MKT", "LMT"]
    limit_price:   Optional[float]
    conid:         Optional[int]


@dataclass
class AutoTradeState:
    armed:    bool
    strategy: Optional[ArmedStrategy]
    history:  list[dict] = field(default_factory=list)


def execute_option_order(strategy: ArmedStrategy):
    """Execute the armed option order via the broker router. Importable for mocking."""
    from app.services.broker_router import build_router_from_credentials
    from app.data.ibkr_paper import BrokerOrder
    order = BrokerOrder(
        symbol=strategy.symbol,
        action=strategy.action,
        quantity=strategy.quantity,
        order_type=strategy.order_type,
        limit_price=strategy.limit_price,
        conid=strategy.conid,
        sec_type="OPT",
        option_symbol=strategy.option_symbol,
    )
    router = build_router_from_credentials()
    return router.execute(strategy.broker, order)


class AutoTradeService:
    """Manages an armed options strategy and fires it on demand or on scan completion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = AutoTradeState(armed=False, strategy=None)

    def arm(self, strategy: ArmedStrategy) -> None:
        with self._lock:
            self._state.armed = True
            self._state.strategy = strategy
        logger.info("AutoTrader armed: %s %s", strategy.action, strategy.symbol)

    def disarm(self) -> None:
        with self._lock:
            self._state.armed = False
            self._state.strategy = None
        logger.info("AutoTrader disarmed")

    def get_state(self) -> AutoTradeState:
        with self._lock:
            return AutoTradeState(
                armed=self._state.armed,
                strategy=self._state.strategy,
                history=list(self._state.history),
            )

    def fire(self):
        """Execute the armed strategy. Disarms after successful fire."""
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
        result = execute_option_order(strategy)
        with self._lock:
            self._state.armed = False
            self._state.strategy = None
            self._state.history.append({
                "order_id": result.order_id,
                "status":   result.status,
                "broker":   result.broker,
                "symbol":   strategy.symbol,
                "option":   strategy.option_symbol,
            })
        logger.info("AutoTrader fired: order %s status %s", result.order_id, result.status)
        return result

    def maybe_fire_on_scan(self) -> None:
        """Trigger #2: called after each scan completes. Fires if armed."""
        with self._lock:
            should_fire = self._state.armed
        if should_fire:
            try:
                self.fire()
                logger.info("AutoTrader: fired on scan completion trigger")
            except Exception as exc:
                logger.error("AutoTrader scan-trigger fire failed: %s", exc)


# Module-level singleton
auto_trader = AutoTradeService()
