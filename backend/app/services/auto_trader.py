from __future__ import annotations

import asyncio
import functools
import logging
import threading
import yaml
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from app.schemas import Direction
from app.services.premium_stop import resolve_premium_stop_pct
from app.scoring.conviction_sizing import (
    SizingConfigError,
    conviction_mult,
    resolve_sizing,
)

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

logger = logging.getLogger(__name__)


class RegimeHeadwindError(RuntimeError):
    """The regime opposes this trade hard enough that the scan would have dropped it.

    A RuntimeError so `/auto-trade/fire` maps it to a 400 exactly as the exposure
    cap does. DELIBERATELY NOT a ValueError and not SizingConfigError: round 3 of
    the plan audit measured what happens when a new refusal is dropped into an
    existing bucket -- it files under `sizing_data_blocked`, logs "the regime
    conviction is not a usable number" (which is false; the conviction is fine
    and is exactly why we are refusing), and pages under a shared rec_id that can
    suppress a genuine config refusal. Its own type, its own history status, its
    own message.
    """


@dataclass
class ArmedStrategy:
    broker:          str
    symbol:          str
    option_symbol:   str
    action:          Literal["BUY", "SELL"]
    # The trade's own direction, carried from the card rather than inferred.
    # Required and non-defaulted, which is legal here because every field above
    # is non-defaulted too and `entry_premium` below is the first with a default.
    #
    # THIS DATACLASS IS THE CARRIER, NOT THE VALIDATOR: `Literal` is not enforced
    # at runtime on a plain dataclass, so only `ArmRequest` (pydantic) actually
    # refuses a bad value. A direct constructor passing "bullish", "" or None
    # therefore still lands on the bearish branch in `_apply_vol_sizing` below.
    # Closing that hole is its own piece (docs/superpowers/plans/
    # 2026-09-18-B-armed-strategy-runtime-validation.md) because the obvious
    # `raise ValueError` lands in fire()'s `sizing_data_blocked` bucket with a
    # false log line, and sits after both full-size early returns -- absent
    # exactly where the blast radius is largest.
    direction:       Direction
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
    # Piece 5 (Phase G, build step 5) -- the method pick the card was showing
    # when this was armed, carried through by `ArmedStrategy(**req.model_dump())`
    # in routers/auto_trade.py. Names and bounds are validated on ArmRequest;
    # this dataclass is the carrier, not the validator.
    #
    # THEY TRAVEL, THEY DO NOT ACT. Nothing submitted to any broker depends on
    # the method (spec S8): the order built by `execute_option_order` reads
    # symbol, action, quantity, order_type, limit_price, conid and option_symbol
    # and none of these. They are here so that the pick is frozen at arm time
    # (Q2) and available to whatever eventually books a position for a fired
    # auto-trade.
    #
    # THE FIRE PATH CREATES NO PortfolioPosition TODAY. That is a pre-existing,
    # separately-documented limitation, NOT something build step 5 introduced
    # and NOT something it closes -- see PROJECT_STATE.json's
    # phase_g_step5_followups. Until that path books a position these five are
    # captured and unread, which is the honest state of it.
    picked_method:           Optional[str]   = None
    picked_row_stock_price:  Optional[float] = None
    picked_row_option_price: Optional[float] = None
    picked_stop_basis:       Optional[str]   = None
    picked_at:               Optional[str]   = None
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
def _load_scoring_doc() -> dict:
    """Load and validate scoring_rules.yaml itself (cached).

    Raises SizingConfigError if the file cannot be read or parsed. It used to
    swallow that into an empty dict, which reads as "sizing disabled" and so
    sized the order at FULL — the loudest possible failure producing the
    largest possible position. §9.1's fail-closed posture (Kenneth,
    2026-09-17) is that a config this path cannot read stops the trade.

    An absent regime_sizing block is NOT a failure and still returns {}: the
    file parsed, and it says sizing is off. A block that is PRESENT and cannot
    be read as on or off is a failure — resolve_sizing decides that, not this.

    lru_cache does not cache exceptions, so a file that could not be READ or
    PARSED is re-read on the next fire attempt. THAT IS NOT TRUE OF A BAD
    VALUE, and round 1 corrected an earlier claim here that said it was: a
    block that parses and is then refused by resolve_sizing was already cached
    by this function, so the refusal stands until the process restarts even
    after the YAML is fixed. Deliberately not plumbed around: §9.2 is settled
    ("he never edits while the backend runs; he always restarts", no reload
    endpoint), so a restart is the documented way this file takes effect at
    all, and cache invalidation here would be a mechanism §9.2 says to omit.
    """
    try:
        with open(_SCORING_CONFIG_PATH) as f:
            doc = yaml.safe_load(f)
    except Exception as exc:
        raise SizingConfigError(
            f"cannot read {_SCORING_CONFIG_PATH}: {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise SizingConfigError(
            f"{_SCORING_CONFIG_PATH} did not parse to a mapping "
            f"(got {type(doc).__name__})"
        )
    return doc


def _load_scoring_config() -> dict:
    """The `regime_sizing` block. Kept as its own name because every existing
    caller and test means this block by it.

    UNCACHED ON PURPOSE -- the cache moved UP to `_load_scoring_doc`, where the
    file read is. Caching here as well would mean two caches over one file, and
    a caller clearing one would get a stale answer from the other. That is not
    hypothetical: it is exactly what broke three fail-closed tests the moment
    this split was made, because they cleared this function's cache and the doc
    underneath stayed warm. Tests now clear `_load_scoring_doc.cache_clear()`.

    The property the fail-closed posture depends on still holds: lru_cache does
    not cache exceptions, and the raise happens inside the cached doc loader, so
    an unreadable file is re-read on the next fire attempt.
    """
    return _load_scoring_doc().get("regime_sizing", {})


def _load_regime_gate_config() -> dict:
    """The `regime_gate` block, from the SAME read as regime_sizing.

    A second `open()` here would be a second reader of one file, which is how
    two call sites come to disagree about what it says -- the defect
    conviction_sizing.py exists to prevent, one layer down. An absent block
    returns {} and the gate treats that as disabled, matching `_regime_cap`,
    which requires `enabled` to be truthy before it caps anything.
    """
    return _load_scoring_doc().get("regime_gate", {})


def _apply_regime_gate(strategy: ArmedStrategy, directional_conv: float,
                       raw_conviction: float) -> None:
    """Refuse a fire the scan's `regime_gate` would have hard-dropped.

    THE RULE IS NOT REIMPLEMENTED -- it is the same function the scan uses.
    `stock_scorer._regime_cap` returns the status cap the gate imposes, and a
    cap of REJECT is the scan's hard drop. Calling it rather than re-deriving
    `<= headwind_reject_pct` here is deliberate: two copies of a threshold rule
    is exactly how the scan card and the auto-trader came to size the same setup
    1.5x apart, which is the defect `conviction_sizing.py` exists to prevent.

    CAUTION IS NOT A REFUSAL HERE, and that asymmetry is real rather than an
    oversight. On the scan a CAUTION cap demotes a candidate's status, which a
    human then reads. An armed trade has no status left to demote -- it is
    fire-or-not -- so the caution band is logged and fires, and only the REJECT
    band refuses. Sizing already handles the middle: every conviction at or
    below 0 in the trade's frame floors at min_mult.
    """
    from app.scoring.stock_scorer import _regime_cap
    from app.services.regime_monitor import get_last_stability

    gate = _load_regime_gate_config()
    if not gate.get("enabled", False):
        return

    stability = get_last_stability()
    if stability is None:
        # The conviction cache was filled by `set_last_conviction` alone, or by
        # an older build. Refusing on a guess would invent a rule; firing
        # silently would hide one. Neither: fire, and say the gate abstained.
        logger.warning(
            "regime_gate: %s %s NOT evaluated — conviction %.1f is cached "
            "without the stability it was measured with, and "
            "require_stable_for_reject is %s",
            strategy.symbol, strategy.direction, raw_conviction,
            gate.get("require_stable_for_reject", True),
        )
        return

    cap = _regime_cap(int(round(directional_conv)), stability, gate)
    if cap == "REJECT":
        raise RegimeHeadwindError(
            f"regime headwind: conviction {directional_conv:+.0f} in this trade's "
            f"own frame is at or below headwind_reject_pct "
            f"({gate.get('headwind_reject_pct')}) with a {stability} regime — "
            f"the scan would have dropped this setup"
        )
    if cap == "CAUTION":
        logger.info(
            "regime_gate: %s %s fires into a headwind (conviction=%.1f, "
            "directional=%+.1f, %s) — CAUTION band, not a refusal",
            strategy.symbol, strategy.direction, raw_conviction,
            directional_conv, stability,
        )


def _apply_vol_sizing(strategy: ArmedStrategy) -> ArmedStrategy:
    """Return a (possibly quantity-adjusted) copy of strategy based on regime conviction.

    Reads cached conviction from regime_monitor (no network call).
    If conviction is None or regime_sizing is disabled, returns strategy
    unchanged. RAISES SizingConfigError if the regime_sizing block is present
    and cannot be honoured — the §9.1 fail-closed posture, which fire() turns
    into a recorded refusal rather than an order at full size.
    """
    cfg = _load_scoring_config()
    # Validated BEFORE the conviction lookup, and that order is load-bearing:
    # `conviction is None` below returns the strategy unchanged (full size), so
    # validating after it would let a broken config through on every fire that
    # happens before regime_monitor has cached anything.
    if resolve_sizing(cfg) is None:
        # Logged for the same reason as the unchanged-quantity line below: this
        # returns at FULL SIZE, and round 2 caught it as the one full-size path
        # still leaving no trace. It is the "off versus broken" case a reader
        # most needs to be able to tell apart afterwards — a block that carries
        # real min_mult/full_conviction_pct values but says `enabled: false`
        # comes through here, not through a refusal.
        logger.info(
            "vol_sizing: %s qty %d unchanged — regime_sizing is off by "
            "configuration", strategy.symbol, strategy.quantity,
        )
        return strategy

    from app.services.regime_monitor import get_last_conviction
    conviction = get_last_conviction()
    if conviction is None:
        return strategy

    # Direction-aware: `conviction` is the SIGNED BULLISH FRAME
    # (regime_omm.conviction over P(Bull) - P(Bear), scaled to [-100, +100]), so
    # the bearish mirror is -conviction, NOT 100 - conviction. On a signed scale
    # `100 - conviction` is a mirror of an unsigned [0, 100] one: with
    # full_conviction_pct at 40, `(100 - conviction) / 40` saturates whenever
    # `100 - conviction >= 40`, i.e. for every conviction <= 60 -- FULL SIZE in
    # essentially every regime. (<= 60, not <= 40: the tight bound, because a
    # comment whose job is to be checkable has to survive being checked.)
    #
    # Direction is carried explicitly from the card. It is NOT inferred from
    # `action`, which is always "BUY" for a long single-leg option and never
    # encoded direction -- that inference is the defect this replaces, and
    # keeping it alongside would be a second source of truth for the same fact.
    directional_conv = conviction if strategy.direction == "Bullish" else -conviction
    #
    # THE GATE, wired 2026-09-19 on Kenneth's explicit instruction. It is applied
    # HERE, immediately after the mirror, because this is the first and only
    # place the conviction exists in the TRADE's own frame -- which is the frame
    # `regime_gate`'s thresholds are written in. The scan gets there by calling
    # compute_omm(direction=req.direction); this path gets there by mirroring a
    # cached bullish number, and before `direction` existed it could not get
    # there at all. That is why the gap was unreachable until this piece.
    _apply_regime_gate(strategy, directional_conv, conviction)
    #
    # SUPERSEDED, ROUND 1 finding 4 -- kept as the record of why this was once
    # deferred and what changed. `regime_gate` IS NOW APPLIED (line above). The
    # block directly above `regime_sizing` in scoring_rules.yaml carries
    # headwind_caution_pct: -15 / headwind_reject_pct: -40, and the scan path
    # enforces it (stock_scan.py -- CAUTION, then a hard "regime headwind"
    # drop). This path reads only `regime_sizing`, so a trade at -80 in its own
    # frame is sized to min_mult and STILL FIRES: `max(1, ...)` guarantees at
    # least one contract. The scan would have refused the same setup.
    #
    # Not closed in this piece on purpose: wiring it makes trades that fire
    # today stop firing, which is a real-money behaviour change and Kenneth's
    # call, not an audit-fix. Before this piece the auto-trader COULD NOT
    # evaluate headwind for a bearish trade -- it had no direction -- so this
    # gap only becomes reachable now. That is why it is written down here
    # rather than left for the next reader to rediscover.
    mult = conviction_mult(directional_conv, cfg)
    adjusted_qty = max(1, round(strategy.quantity * mult))

    if adjusted_qty == strategy.quantity:
        # Logged too, and round 1 is why: every case where a bad-but-honourable
        # config produced mult 1.0 (full size) returned here and left NO trace
        # at any level, so the one outcome worth noticing was the only silent
        # one. Includes the honest no-op (conviction at or above full).
        logger.info(
            # `direction` and the RAW conviction are both printed, and that is
            # the point: `directional_conv` is POST-mirror, so Bearish@+80 and
            # Bullish@-80 both render as -80.0 and are indistinguishable. Since
            # direction now decides size, a post-mortem has to be able to tell
            # which one it was.
            "vol_sizing: %s %s qty %d unchanged (conviction=%.1f, "
            "directional=%.1f, mult=%.2f)",
            strategy.symbol, strategy.direction, strategy.quantity,
            conviction, directional_conv, mult,
        )
        return strategy

    logger.info(
        # Same reason as the unchanged line above: raw conviction AND direction,
        # because the post-mirror number alone cannot say which trade this was.
        "vol_sizing: %s %s qty %d → %d (conviction=%.1f, directional=%.1f, "
        "mult=%.2f)",
        strategy.symbol, strategy.direction, strategy.quantity, adjusted_qty,
        conviction, directional_conv, mult,
    )
    return _dc_replace(strategy, quantity=adjusted_qty)


def _alert_sizing_config_refusal(symbol: str, exc: Exception) -> None:
    """Push a sizing-config refusal to a channel that reaches a phone.

    §9.1 is "refuse to fire AND alert". The manual trigger needs no help — the
    refusal is the 400 body of POST /auto-trade/fire, with a human reading it.
    The scan trigger has no reader at all: POST /scan calls it through
    `asyncio.to_thread` and discards the outcome, so without this the refusal
    is a log line on a box nobody is watching while an armed order silently
    does not happen.

    WHY asyncio.run IS CORRECT HERE: this runs in the worker thread
    `asyncio.to_thread` created, which has no event loop of its own, so a
    fresh loop is the only way to await an async notifier. Keeping it at the
    scan-trigger boundary rather than inside fire() is what makes that true —
    fire() is also reachable from the event-loop thread, via the /fire
    endpoint, where asyncio.run raises.

    THE RUNNING-LOOP GUARD IS UNREACHABLE TODAY and round 1 was right to say
    so: the only caller is maybe_fire_on_scan, whose only caller is POST
    /scan through asyncio.to_thread. It stays because the cost of being wrong
    about that later is §9.1's "and alert" half silently not happening, and a
    logged skip is the difference between finding that out and not.

    type_enabled=True is deliberate and is the documented per-call override:
    CONFIG_ERROR is not one of the portfolio alert types in `enabledTypes`, so
    the global check would drop it. masterEnabled is NOT bypassed — that is
    Kenneth's account-wide kill switch.

    Nothing here may raise: the refusal has already happened and has already
    been recorded by fire(). A dead SMTP server must not turn a safe refusal
    into an unhandled exception in the scan endpoint's worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # no loop in this thread — a fresh one is safe
    else:
        logger.error(
            "AutoTrader: sizing-config refusal for %s NOT alerted (an event loop "
            "is already running in this thread): %s", symbol, exc,
        )
        return

    try:
        from app.services.notifications.alert_notifier import notify_alert
        delivered = asyncio.run(notify_alert(
            symbol=symbol,
            alert_type="CONFIG_ERROR",
            reason=(
                f"Auto-trade REFUSED to fire {symbol}: "
                + ("scoring_rules.yaml's regime_sizing block cannot be honoured"
                   if isinstance(exc, SizingConfigError)
                   else "the regime conviction is not a usable number")
                + f", so the position size is unknown. Nothing was sent and the "
                  f"auto-trader is disarmed. {exc}"
            ),
            # Stable, symbol-independent key: the file is broken, not the
            # symbol, so the dedup window collapses a run of scans into one
            # alert instead of one per armed order.
            rec_id="auto-trade-sizing-config",
            type_enabled=True,
        ))
        if not delivered:
            # notify_alert returns False for the master kill switch, an armed
            # dedup window (persisted in alert_dedup.json, so it survives a
            # restart) and a genuine delivery failure alike. Without this line
            # "and alert" could be a silent no-op -- which is how this whole
            # class of defect got here.
            logger.error(
                "AutoTrader: sizing-config refusal for %s was NOT delivered by "
                "any channel (master switch off, dedup window armed, or "
                "delivery failed). The refusal itself stands.", symbol,
            )
    except Exception as notify_exc:
        logger.error(
            "AutoTrader: failed to alert the sizing-config refusal for %s "
            "(the refusal itself stands): %s", symbol, notify_exc,
        )


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
        logger.info(
            # `direction`, not `action`: this piece established that `action`
            # carries no directional meaning (and it is now narrowed to "BUY",
            # so it is a constant). Direction is what decides the size.
            "AutoTrader armed: %s %s qty %d",
            strategy.symbol, strategy.direction, strategy.quantity,
        )

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
        # A config this cannot honour refuses the fire (§9.1, fail closed). The
        # order matters: disarm has already happened above, so a refusal here
        # leaves nothing armed and nothing sent — the same shape as the two
        # blocks below. SizingConfigError is a RuntimeError, so /auto-trade/fire
        # still maps it to a 400 and maybe_fire_on_scan can single it out to alert.
        try:
            strategy = _apply_vol_sizing(strategy)
        except RegimeHeadwindError as exc:
            # ITS OWN BRANCH, ITS OWN STATUS. Folding this into the handler
            # below would file a refusal we CHOSE under a status meaning "the
            # conviction is unusable", and log that the number is bad when the
            # number is good and is precisely why we refused. A post-mortem
            # could not tell a headwind refusal from a data fault, and the
            # remedies are opposites: "the market moved against this trade" vs
            # "the regime feed is broken".
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          "regime_headwind_blocked",
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s %s — %s",
                strategy.symbol, strategy.direction, exc,
            )
            raise
        except (SizingConfigError, ValueError) as exc:
            # ValueError too, and round 2 is why. Round 1 correctly stopped
            # reporting a bad CONVICTION as a broken config file (the message
            # named a key that does not exist in scoring_rules.yaml) by raising
            # a plain ValueError — and thereby walked the refusal out of this
            # handler entirely: no history entry, no alert, `/auto-trade/status`
            # still showing the PREVIOUS order as last_order. Nothing shipped,
            # which is why it was below the gate, but it was strictly worse than
            # what it replaced on both halves of §9.1.
            with self._lock:
                self._state.history.append({
                    "order_id":        None,
                    "status":          ("sizing_config_blocked"
                                        if isinstance(exc, SizingConfigError)
                                        else "sizing_data_blocked"),
                    "broker":          strategy.broker,
                    "symbol":          strategy.symbol,
                    "option":          strategy.option_symbol,
                    "timestamp":       datetime.now(timezone.utc).isoformat(),
                    "premium_at_risk": 0.0,
                    "error":           str(exc),
                })
            logger.error(
                "AutoTrader fire REFUSED for %s — %s, so the order size is "
                "unknown: %s", strategy.symbol,
                "regime_sizing unusable" if isinstance(exc, SizingConfigError)
                else "the regime conviction is not a usable number", exc,
            )
            raise

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
        except (SizingConfigError, ValueError) as exc:
            # fire() has already logged and recorded it; this trigger has no
            # reader, so it is also the half of §9.1 that says "and alert".
            # ValueError is here for the same reason it is in fire() — see the
            # handler there.
            _alert_sizing_config_refusal(strategy.symbol, exc)
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
