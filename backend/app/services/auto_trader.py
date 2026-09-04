from __future__ import annotations

import functools
import logging
import threading
import yaml
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from app.services.premium_stop import resolve_premium_stop_pct

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
    # Piece 4 — the per-trade premium stop the card was showing when this was
    # armed. None inherits auto_trade.premium_stop_pct. Threaded through rather
    # than left to the global: the auto-trader is placing the same trade the
    # card described, so sizing it off a different number than the one the user
    # set is a silent divergence — which is how three globals happened.
    premium_stop_pct: Optional[float] = None
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
    Must NOT be called while holding threading.Lock (3-second network deadline).
    fetch_price has no built-in timeout; wrap in a thread and use shutdown(wait=False)
    after timeout so we never block the caller beyond the deadline.
    """
    import concurrent.futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        from app.data.market import fetch_price
        future = ex.submit(fetch_price, symbol)
        try:
            price = future.result(timeout=3.0)
        except concurrent.futures.TimeoutError:
            ex.shutdown(wait=False)
            return False
        ex.shutdown(wait=False)
        return price is not None and float(price) > 0
    except Exception:
        ex.shutdown(wait=False)
        return False


_SCORING_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "scoring_rules.yaml"


@functools.lru_cache(maxsize=1)
def _load_scoring_config() -> dict:
    """Load regime_sizing block from scoring_rules.yaml (cached)."""
    try:
        with open(_SCORING_CONFIG_PATH) as f:
            return yaml.safe_load(f).get("regime_sizing", {})
    except Exception as exc:
        logger.warning("_load_scoring_config: failed to load %s — vol sizing disabled: %s",
                       _SCORING_CONFIG_PATH, exc)
        return {}


def _apply_vol_sizing(strategy: ArmedStrategy) -> ArmedStrategy:
    """Return a (possibly quantity-adjusted) copy of strategy based on regime conviction.

    Reads cached conviction from regime_monitor (no network call).
    If conviction is None or regime_sizing is disabled, returns strategy unchanged.
    """
    cfg = _load_scoring_config()
    if not cfg.get("enabled", False):
        return strategy

    from app.services.regime_monitor import get_last_conviction
    conviction = get_last_conviction()
    if conviction is None:
        return strategy

    min_mult        = float(cfg.get("min_mult", 0.5))
    full_conviction = float(cfg.get("full_conviction_pct", 40))

    # Direction-aware: BUY scales with bullish conviction; SELL scales with bearish conviction
    # (bearish conviction = 100 - bullish conviction, capped to full_conviction scale)
    directional_conv = conviction if strategy.action == "BUY" else (100 - conviction)
    mult = max(min_mult, min(1.0, directional_conv / full_conviction))
    adjusted_qty = max(1, round(strategy.quantity * mult))

    if adjusted_qty == strategy.quantity:
        return strategy

    logger.info(
        "vol_sizing: %s qty %d → %d (conviction=%.1f, mult=%.2f)",
        strategy.symbol, strategy.quantity, adjusted_qty, directional_conv, mult,
    )
    return _dc_replace(strategy, quantity=adjusted_qty)


def execute_option_order(strategy: ArmedStrategy):
    """Execute the armed option order via the broker router. Importable for mocking."""
    from app.services.broker_router import build_router_from_credentials
    from app.data.ibkr_paper import BrokerOrder
    order = BrokerOrder(
        symbol=strategy.symbol,
        action=strategy.action,
        # Auto-trade is structurally entry-only — arm()/fire() have no existing-position
        # lookup anywhere, and the only caller (AutoTradeArm/index.tsx) always requests a
        # buy-to-open. Hardcoded rather than added to ArmRequest/ArmedStrategy so there's
        # no way to call this endpoint with the wrong effect.
        effect="OPEN",
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
        if strategy.entry_premium <= 0:
            raise ValueError(
                f"entry_premium must be > 0 before arming (got {strategy.entry_premium}). "
                "Set it from the contract's mid price so the exposure check can run."
            )
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
            _symbol = self._state.strategy.symbol

        # Halt check outside lock — network call must not hold the lock.
        # Armed state is preserved: we haven't disarmed yet.
        if not _market_is_open(_symbol):
            raise RuntimeError(
                f"Market closed or {_symbol} halted "
                f"— armed state preserved for retry"
            )

        with self._lock:
            # Re-check: another thread may have disarmed while we checked market.
            if not self._state.armed or self._state.strategy is None:
                raise RuntimeError("AutoTrader not armed — cannot fire")
            strategy = self._state.strategy
            self._state.armed = False
            self._state.strategy = None

        # Vol-scaled sizing: adjust quantity using cached regime conviction (no network call)
        strategy = _apply_vol_sizing(strategy)

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
        # Daily loss circuit breaker — runs after cap check, before order submission.
        # Armed state is already cleared above; circuit breaker blocks permanently (no retry).
        with self._lock:
            _history_snapshot = list(self._state.history)
        try:
            self._check_daily_loss(strategy, _history_snapshot, pv)
        except RuntimeError:
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          "daily_loss_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                })
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

        stop_pct = resolve_premium_stop_pct(
            strategy.premium_stop_pct,
            float(self._risk_config().get("premium_stop_pct", 0.60)),
        )
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
        except Exception as exc:
            logger.warning("_risk_config: failed to load %s — risk limits disabled: %s",
                           _RISK_CONFIG_PATH, exc)
            return {}

    @staticmethod
    def _check_daily_loss(strategy: ArmedStrategy, history: list[dict], portfolio_value: float) -> None:
        """Raise RuntimeError if today's premium-at-risk exceeds the daily loss limit."""
        risk_cfg = AutoTradeService._risk_config()
        max_pct  = float(risk_cfg.get("max_daily_loss_pct", 0.02))
        # NOTE, and it is a real one: since piece 4 this denominator can come
        # from the ARM REQUEST rather than from risk_rules.yaml. A tighter
        # declared stop shrinks `this_risk` and so lets more trades through the
        # daily-loss gate, and nothing here enforces the declared stop -- the
        # auto-trader places no protective order, so the true exposure is the
        # whole premium either way. That was already true when this read the
        # global; what changed is that the optimism is now client-settable
        # (bounded to (0, 1) by ArmRequest, so it cannot be zeroed).
        #
        # Deliberately NOT clamped here. Threading the per-trade stop is what
        # piece 4 was approved to do, and clamping it to the global would make
        # a genuinely tighter stop book MORE risk than it takes. Sizing the
        # gate on the full premium instead is the honest fix and a change to
        # risk behaviour Kenneth has not agreed to -- recorded as an open
        # question in PROJECT_STATE.json rather than made here.
        stop_pct = resolve_premium_stop_pct(
            strategy.premium_stop_pct,
            float(risk_cfg.get("premium_stop_pct", 0.60)),
        )
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
