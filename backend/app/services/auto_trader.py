from __future__ import annotations

import functools
import logging
import threading
import yaml
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

logger = logging.getLogger(__name__)


@dataclass
class ArmedStrategy:
    broker:          str
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    quantity:        int
    order_type:      Literal["MKT", "LMT"]
    limit_price:     Optional[float]
    conid:           Optional[int]
    entry_premium:   float = 0.0
    portfolio_value: float = 50_000.0
    armed_at:        datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AutoTradeState:
    armed:    bool
    strategy: Optional[ArmedStrategy]
    history:  list[dict] = field(default_factory=list)


def _market_is_open(symbol: str) -> bool:
    """Return True if the market appears open for this symbol.

    Calls fetch_price — conservative: if no price returns (None, 0, or exception),
    treat as closed and block the fire.
    Runs inside threading.Lock so must complete quickly.
    fetch_price has no built-in timeout; wrap in a thread with a 3-second deadline
    to prevent holding the lock across a slow network call.
    """
    import concurrent.futures
    try:
        from app.data.market import fetch_price
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(fetch_price, symbol)
            try:
                price = future.result(timeout=3.0)
            except concurrent.futures.TimeoutError:
                return False
        return price is not None and float(price) > 0
    except Exception:
        return False


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

    def fire(self, portfolio_snapshot: list | None = None, portfolio_value: float | None = None):
        """Execute the armed strategy.

        Disarms on the fire attempt (fail-closed). If portfolio_snapshot is
        provided, runs an exposure cap check before executing — raises if the
        caps would be breached. Pass portfolio_snapshot=None to skip the check
        (backward-compat path for tests and callers without DB access).
        """
        with self._lock:
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            # Halt check before disarm: if market is closed, preserve armed state
            if not _market_is_open(self._state.strategy.symbol):
                raise RuntimeError(
                    f"Market closed or {self._state.strategy.symbol} halted "
                    f"— armed state preserved for retry"
                )
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None

        # Exposure cap check — runs after disarm so a double-fire is impossible.
        pv = portfolio_value if portfolio_value is not None else strategy.portfolio_value
        if portfolio_snapshot is not None and strategy.entry_premium > 0:
            try:
                self._check_exposure(strategy, portfolio_snapshot, pv)
            except RuntimeError:
                with self._lock:
                    self._state.history.append({
                        "order_id":        None,
                        "status":          "cap_blocked",
                        "broker":          strategy.broker,
                        "symbol":          strategy.symbol,
                        "option":          strategy.option_symbol,
                        "timestamp":       datetime.now(timezone.utc).isoformat(),
                        "premium_at_risk": 0.0,
                    })
                raise
        elif portfolio_snapshot is not None and strategy.entry_premium == 0.0:
            logger.warning(
                "AutoTrader: exposure check skipped for %s — entry_premium is 0.0 (set it in ArmRequest)",
                strategy.symbol,
            )

        # Daily loss circuit breaker — runs after cap check, before order submission.
        with self._lock:
            _history_snapshot = list(self._state.history)
        try:
            self._check_daily_loss(strategy, _history_snapshot, pv)
        except RuntimeError:
            with self._lock:
                self._state.armed = False
                self._state.strategy = None
            raise

        try:
            result = execute_option_order(strategy)
        except Exception as exc:
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          "order_failed",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error("AutoTrader order failed for %s: %s", strategy.symbol, exc)
            raise RuntimeError(f"Order failed: {exc}") from exc

        stop_pct = float(self._risk_config().get("premium_stop_pct", 0.60))
        with self._lock:
            self._state.history.append({
                "order_id":        result.order_id,
                "status":          result.status,
                "broker":          result.broker,
                "symbol":          strategy.symbol,
                "option":          strategy.option_symbol,
                "timestamp":       datetime.now(timezone.utc).isoformat(),
                "premium_at_risk": strategy.entry_premium * strategy.quantity * 100 * stop_pct,
            })
        logger.info("AutoTrader fired: order %s status %s", result.order_id, result.status)
        return result

    @staticmethod
    def _check_exposure(strategy: ArmedStrategy, portfolio_snapshot: list, portfolio_value: float) -> None:
        """Raise RuntimeError if the armed order would breach exposure caps."""
        from app.services.portfolio_risk import check_position_risk
        result = check_position_risk(
            symbol=strategy.symbol,
            contract_id=strategy.option_symbol,
            proposed_contracts=strategy.quantity,
            entry_premium=strategy.entry_premium,
            current_price=strategy.entry_premium,
            portfolio=portfolio_snapshot,
            portfolio_value=portfolio_value,
        )
        if not result.approved:
            logger.warning("AutoTrader fire blocked by exposure cap: %s", result.reasons)
            raise RuntimeError(f"Exposure cap breach: {result.reasons}")
        if result.adjusted_size is not None:
            logger.warning(
                "AutoTrader fire blocked: quantity %d exceeds cap, re-arm with %d contracts",
                strategy.quantity, result.adjusted_size,
            )
            raise RuntimeError(
                f"Quantity {strategy.quantity} exceeds exposure cap — re-arm with {result.adjusted_size} contracts"
            )

    def maybe_fire_on_scan(
        self,
        portfolio_snapshot: list | None = None,
        portfolio_value: float | None = None,
    ) -> None:
        """Trigger #2: called after each scan completes. Fires if armed and fresh."""
        with self._lock:
            should_fire = self._state.armed
            strategy = self._state.strategy

        if not should_fire or strategy is None:
            return

        # Staleness guard — disarm without firing if the order is too old.
        max_age = self._max_arm_age_minutes()
        age_minutes = (datetime.now(timezone.utc) - strategy.armed_at).total_seconds() / 60
        if age_minutes > max_age:
            self.disarm()
            logger.warning(
                "AutoTrader: disarming stale armed order for %s (armed %.0f min ago, limit %d min)",
                strategy.symbol, age_minutes, max_age,
            )
            return

        try:
            self.fire(portfolio_snapshot=portfolio_snapshot, portfolio_value=portfolio_value)
            logger.info("AutoTrader: fired on scan completion trigger")
        except Exception as exc:
            logger.error("AutoTrader scan-trigger fire failed: %s", exc)

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _max_arm_age_minutes() -> int:
        """Load max_arm_age_minutes from risk_rules.yaml (cached; restart to reload)."""
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return int(cfg.get("auto_trade", {}).get("max_arm_age_minutes", 30))
        except Exception:
            return 30

    @staticmethod
    @functools.lru_cache(maxsize=1)
    def _risk_config() -> dict:
        """Load full auto_trade config section (cached; restart to reload)."""
        try:
            with open(_RISK_CONFIG_PATH) as f:
                cfg = yaml.safe_load(f)
            return cfg.get("auto_trade", {})
        except Exception:
            return {}

    @staticmethod
    def _check_daily_loss(strategy: ArmedStrategy, history: list[dict], portfolio_value: float) -> None:
        """Raise RuntimeError if today's premium-at-risk exceeds the daily loss limit."""
        risk_cfg = AutoTradeService._risk_config()
        max_pct  = float(risk_cfg.get("max_daily_loss_pct", 0.02))
        stop_pct = float(risk_cfg.get("premium_stop_pct", 0.60))
        limit    = max_pct * portfolio_value

        today_str = datetime.now(timezone.utc).date().isoformat()   # UTC date "YYYY-MM-DD"

        # Sum premium_at_risk from today's history entries only
        today_risk = sum(
            float(e.get("premium_at_risk") or 0)
            for e in history
            if isinstance(e.get("timestamp"), str) and e["timestamp"].startswith(today_str)
        )

        # Add this trade's prospective risk
        this_risk = strategy.entry_premium * strategy.quantity * 100 * stop_pct
        if today_risk + this_risk > limit:
            raise RuntimeError(
                f"Daily loss limit reached: {today_risk + this_risk:.0f} at risk "
                f"vs limit {limit:.0f} — no further trades today"
            )


# Module-level singleton
auto_trader = AutoTradeService()
