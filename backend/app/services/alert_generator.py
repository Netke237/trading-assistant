from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config_health import config_health
from app.models.portfolio import PortfolioPositionModel
from app.schemas import AlertItem
from app.services.audit import log_event
from app.services.position_alert_log import log_position_alert
from app.services.premium_stop import (
    resolve_premium_stop_pct,
    is_short_stock_position,
    percent_stop_threshold_price,
    premium_stop_side,
)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"


@lru_cache(maxsize=1)
def _load_risk_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="risk_rules.yaml",
    loader="alert_generator._load_risk_config",
    fn=_load_risk_config,
    project=lambda doc: doc,
)


def _premium_stop_pct() -> float:
    return float(_load_risk_config().get("reward_risk", {}).get("premium_stop_pct", 0.60))


# Position-scoped alert types — the only ones a per-position override can
# switch. Mirrors frontend `POSITION_ALERT_TYPES` in types/domain.ts.
POSITION_ALERT_TYPES = frozenset({
    "TP_HIT", "STOP_REACHED", "STRUCTURAL_STOP_BREACHED",
    "PREMIUM_STOP", "TIME_STOP", "EVENT_RISK",
})

# Human label for the TP method that fired, appended to the TP_HIT reason so
# the alert says WHICH target was reached. Mirrors frontend
# `alertEngine.TP_METHOD_LABEL` — keep the two in step. 'ladder' is the
# historical default and stays unlabelled, same as the frontend.
_TP_METHOD_LABEL = {
    "monte_carlo": "Monte Carlo target",
    "exit_plan_2r": "2R exit plan",
    "exit_plan_3r": "3R exit plan",
}


def effective_enabled(overrides: Optional[dict], alert_type: str) -> Optional[bool]:
    """Resolve one position's per-type alert override (Feature D).

    Returns True/False when the position carries an EXPLICIT override for the
    type, and None when it doesn't — None means "inherit", i.e. defer to the
    global ``alert_delivery.enabledTypes`` gate that already lives in
    ``notify_alert``. The three-way return is what keeps this composable with
    that existing gate instead of duplicating it here.

    Mirrors frontend ``alertEngine.effectiveEnabled`` — keep the two in step.
    A non-bool stored value (hand-edited JSON, an older shape) is treated as
    absent rather than coerced, so a truthy string can never silently force an
    alert type on. So is a key for an account-wide type (REGIME_CHANGE, the
    SCAN_* lifecycle types): those are never raised per position, so a stray
    entry for one must not be allowed to override the user's global setting.
    """
    if not overrides or alert_type not in POSITION_ALERT_TYPES:
        return None
    value = overrides.get(alert_type)
    return value if isinstance(value, bool) else None


def parse_expiry_from_contract(contract: str) -> Optional[date]:
    """Extract expiry date from contract string format: SYMBOL|STRIKE|EXPIRY|C/P."""
    try:
        parts = contract.split("|")
        if len(parts) >= 3:
            return date.fromisoformat(parts[2])
    except (ValueError, IndexError):
        pass
    return None


async def generate_alerts(
    db: AsyncSession,
    current_prices: dict[str, float],
    current_option_prices: Optional[dict[str, float]] = None,
    sustain_minutes: int = 0,
) -> list[AlertItem]:
    """Generate alerts for all open portfolio positions.

    sustain_minutes: if > 0, a stop/target/premium condition must stay true
    across checks spanning at least this many minutes before it alerts (state
    persisted per-position in PortfolioPositionModel.alert_state). 0 preserves
    the original instant-fire behavior.
    """
    result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    positions = result.scalars().all()

    alerts: list[AlertItem] = []
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    counter = 0

    for pos in positions:
        symbol = pos.symbol
        price = current_prices.get(symbol)
        opt_price = (current_option_prices or {}).get(pos.contract) if current_option_prices else None
        targets = pos.targets or []
        alert_state = dict(pos.alert_state or {})
        overrides = pos.alert_overrides or {}

        def _muted(alert_type: str) -> bool:
            """True when this position explicitly turned the type OFF.

            Only an explicit False suppresses here. An explicit True and an
            absent key both fall through to the existing global
            ``enabledTypes`` gate in ``notify_alert`` — which the caller
            bypasses for an explicit True (see `type_enabled`), giving the
            full `override ?? global` semantics without this function having
            to know the global config at all. Suppressing here (rather than at
            dispatch) is deliberate: a muted type must produce no alert row,
            no WS broadcast, and no history entry, because for this position
            it genuinely never fired.

            Muting also drops any half-elapsed ``sustain_minutes`` clock for
            the type: the branches below short-circuit before ``_sustained``,
            so without this the stale ``pending_since`` would survive the
            mute and fire the instant the user switched the type back on.
            Un-muting therefore starts a fresh sustain window, which is what
            "this alert was off" should mean.
            """
            if effective_enabled(overrides, alert_type) is False:
                alert_state.pop(alert_type, None)
                return True
            return False

        def _sustained(alert_type: str, met: bool) -> bool:
            if not sustain_minutes:
                return met
            if not met:
                alert_state.pop(alert_type, None)
                return False
            pending_since_str = alert_state.get(alert_type)
            if pending_since_str is None:
                alert_state[alert_type] = now_iso
                return False
            try:
                pending_since = datetime.fromisoformat(pending_since_str)
                elapsed_min = (now - pending_since).total_seconds() / 60.0
                return elapsed_min >= sustain_minutes
            except (ValueError, TypeError):
                # Corrupted alert_state entry -- restart the clock instead of
                # raising, which would abort alert generation for every
                # remaining position in this tick.
                alert_state[alert_type] = now_iso
                return False

        # TP_HIT — direction-aware: bullish targets are above current price, bearish below
        is_bearish = pos.direction == "Bearish"
        # The price compared against is whatever the position's ACTIVE TP
        # method resolved to (Feature D). `resolved_tp_price` is a snapshot
        # refreshed only on a manual re-estimate/re-compute — read here
        # exactly as `structural_stop` already is, never recomputed. It is
        # NULL for the 'ladder' method, which falls back to the live first
        # ladder target below (also the fallback for a non-ladder method whose
        # snapshot was never stamped, so such a position keeps alerting rather
        # than going silent).
        first_target = targets[0] if targets else None
        ladder_price = (
            (first_target.get("stock_price") or first_target.get("stockPrice") or 0)
            if first_target else None
        )
        # `> 0`, not truthiness: 0 AND negative are never real stock prices
        # (the same convention `_floor_stop` applies to stops) and an
        # unguarded write path could persist either. A non-positive snapshot
        # falls back to the ladder rather than making `price >= <=0` true on
        # every tick for a Bullish position, or never true for a Bearish one.
        raw_resolved = pos.resolved_tp_price
        target_stock_price = raw_resolved if raw_resolved and raw_resolved > 0 else ladder_price
        if target_stock_price and target_stock_price > 0 and price is not None and not _muted("TP_HIT"):
            hit_raw = (price <= target_stock_price) if is_bearish else (price >= target_stock_price)
            if _sustained("TP_HIT", hit_raw):
                counter += 1
                log_event("alert_fired", pos.rec_id, {
                    "symbol": symbol,
                    "alertType": "TP_HIT",
                    "price": price,
                    "target": target_stock_price,
                    "direction": pos.direction,
                })
                await log_position_alert(
                    db, rec_id=pos.rec_id, symbol=symbol, alert_type="TP_HIT",
                    source="backend", price=price, reference_value=target_stock_price,
                    reference_kind="price", direction=pos.direction, contract=pos.contract,
                )
                # Only label a non-ladder method that actually supplied the
                # price — a non-positive raw_resolved falsy/negative means it
                # fell back to the ladder above (same `> 0` guard as line 177,
                # not the plain truthiness this used to re-test here, which
                # let a negative resolved_tp_price mislabel a ladder-sourced
                # fire as the exit-plan method). Mirrors frontend's
                # `tpMethodNote`.
                tp_method_note = (
                    f" ({_TP_METHOD_LABEL[pos.active_tp_method]})"
                    if raw_resolved and raw_resolved > 0 and pos.active_tp_method in _TP_METHOD_LABEL
                    else ""
                )
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Target reached — {symbol} at ${price:.2f}{tp_method_note}",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TP_HIT",
                    price=price,
                    referenceValue=target_stock_price,
                    direction=pos.direction,
                    contract=pos.contract,
                ))

        # STOP_REACHED — direction-aware: puts are invalidated when stock rises above stop
        stop_breached_raw = (
            (price >= pos.stop) if is_bearish
            else (price <= pos.stop)
        ) if (pos.stop is not None and price is not None) else False
        if pos.stop is not None and price is not None and not _muted("STOP_REACHED") \
                and _sustained("STOP_REACHED", stop_breached_raw):
            counter += 1
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "STOP_REACHED",
                "price": price,
                "stop": pos.stop,
                "direction": pos.direction,
            })
            await log_position_alert(
                db, rec_id=pos.rec_id, symbol=symbol, alert_type="STOP_REACHED",
                source="backend", price=price, reference_value=pos.stop,
                reference_kind="price", direction=pos.direction, contract=pos.contract,
            )
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} {'above' if is_bearish else 'below'} ${pos.stop:.2f} (price ${price:.2f})",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
                price=price,
                referenceValue=pos.stop,
                direction=pos.direction,
                contract=pos.contract,
            ))

        # STRUCTURAL_STOP_BREACHED — same direction-aware comparison as STOP_REACHED,
        # but against the structural (order-block/swing) level instead of the
        # premium-based invalidation. Optional: only fires for positions where the
        # user ran "Check structure" before sending to the broker.
        structural_breached_raw = (
            (price >= pos.structural_stop) if is_bearish
            else (price <= pos.structural_stop)
        ) if (pos.structural_stop is not None and price is not None) else False
        if pos.structural_stop is not None and price is not None \
                and not _muted("STRUCTURAL_STOP_BREACHED") \
                and _sustained("STRUCTURAL_STOP_BREACHED", structural_breached_raw):
            counter += 1
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "STRUCTURAL_STOP_BREACHED",
                "price": price,
                "structuralStop": pos.structural_stop,
                "direction": pos.direction,
            })
            await log_position_alert(
                db, rec_id=pos.rec_id, symbol=symbol, alert_type="STRUCTURAL_STOP_BREACHED",
                source="backend", price=price, reference_value=pos.structural_stop,
                reference_kind="price", direction=pos.direction, contract=pos.contract,
            )
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Structural stop breached — {symbol} {'above' if is_bearish else 'below'} ${pos.structural_stop:.2f} (price ${price:.2f})",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STRUCTURAL_STOP_BREACHED",
                price=price,
                referenceValue=pos.structural_stop,
                direction=pos.direction,
                contract=pos.contract,
            ))

        # PREMIUM_STOP — piece 4: this position's own percentage when it has
        # one, otherwise the global. Resolved ONCE here so the comparison, the
        # reported threshold price and the logged thresholdPct can never
        # disagree with each other.
        resolved_premium_stop_pct = resolve_premium_stop_pct(
            pos.premium_stop_pct, _premium_stop_pct()
        )
        #
        # STOP-SEMANTICS-2026-10-02: a SHORT stock (Bearish `|STOCK`) loses on a
        # rise, so its stop fires at `price >= entry * (1 + pct)`. Every other
        # position keeps the fall-side rule. `opt_price > 0` matches the
        # frontend engine's `currentPrice > 0`: a quote that rounded to $0.00 is
        # no quote, not a fill at zero, so it fires nothing on either side.
        short_stock = is_short_stock_position(pos.contract, pos.direction)
        premium_threshold = (
            percent_stop_threshold_price(
                pos.entry_price, resolved_premium_stop_pct, short_stock)
            if pos.entry_price > 0 else None
        )
        premium_hit_raw = bool(
            opt_price is not None and opt_price > 0 and premium_threshold is not None
            and (opt_price >= premium_threshold if short_stock
                 else opt_price <= premium_threshold)
        )
        if not _muted("PREMIUM_STOP") and _sustained("PREMIUM_STOP", premium_hit_raw):
            counter += 1
            threshold_price = round(premium_threshold, 4)
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "PREMIUM_STOP",
                "optPrice": opt_price,
                "entryPrice": pos.entry_price,
                # The RESOLVED value, never the global — otherwise the alert's
                # own payload misreports why it fired.
                "thresholdPct": resolved_premium_stop_pct,
            })
            await log_position_alert(
                db, rec_id=pos.rec_id, symbol=symbol, alert_type="PREMIUM_STOP",
                source="backend", price=opt_price, reference_value=threshold_price,
                reference_kind="price", direction=pos.direction, contract=pos.contract,
            )
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                # A short's reason is price-only and identical in both engines
                # (pnlPct is not direction-aware, so "down N%" would be wrong).
                reason=(
                    f"Stock stop — {symbol} at ${opt_price:.2f}" if short_stock
                    else f"Premium stop — {symbol} {'stock' if pos.contract.endswith('|STOCK') else 'option'} at ${opt_price:.2f}"
                ),
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="PREMIUM_STOP",
                price=opt_price,
                referenceValue=threshold_price,
                # The same resolved fraction the comparison and the event log
                # above already use, now carried on the alert itself so a row
                # reports the threshold it FIRED at rather than whatever the
                # position resolves to when it is later looked at
                # (ALERT-THRESHOLD-STAMP-2026-09-05).
                premiumStopPct=resolved_premium_stop_pct,
                stopSide=premium_stop_side(pos.contract, pos.direction),
                direction=pos.direction,
                contract=pos.contract,
            ))

        # TIME_STOP — day-granularity already; sustain does not apply.
        expiry = parse_expiry_from_contract(pos.contract)
        if expiry is not None:
            days_to_expiry = (expiry - date.today()).days
            if 0 <= days_to_expiry <= 3 and not _muted("TIME_STOP"):
                counter += 1
                log_event("alert_fired", pos.rec_id, {
                    "symbol": symbol,
                    "alertType": "TIME_STOP",
                    "daysToExpiry": days_to_expiry,
                    "direction": pos.direction,
                })
                await log_position_alert(
                    db, rec_id=pos.rec_id, symbol=symbol, alert_type="TIME_STOP",
                    source="backend", reference_value=days_to_expiry,
                    reference_kind="days", direction=pos.direction, contract=pos.contract,
                )
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Time stop — {symbol} {days_to_expiry} DTE",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TIME_STOP",
                    referenceValue=float(days_to_expiry),
                    direction=pos.direction,
                    contract=pos.contract,
                ))
        elif getattr(pos, "hold_max_days", None) is not None:
            # STOCKS-HORIZON-T1 H6 -- a stock position held for its scan's hold.
            # End-of-day rule, the same one the backtest's time exit uses: days
            # held >= hold_max_days. Both dates are the server's local date, as
            # days_to_expiry above uses date.today(). No automatic close.
            try:
                entered = date.fromisoformat(str(pos.entry_date)[:10])
            except (TypeError, ValueError):
                entered = None
            if entered is not None:
                days_held = (date.today() - entered).days
                hold = pos.hold_max_days
                if days_held >= hold and not _muted("TIME_STOP"):
                    counter += 1
                    log_event("alert_fired", pos.rec_id, {
                        "symbol": symbol,
                        "alertType": "TIME_STOP",
                        "daysHeld": days_held,
                        "holdMaxDays": hold,
                        "direction": pos.direction,
                    })
                    await log_position_alert(
                        db, rec_id=pos.rec_id, symbol=symbol, alert_type="TIME_STOP",
                        source="backend", reference_value=days_held,
                        reference_kind="days", direction=pos.direction, contract=pos.contract,
                    )
                    alerts.append(AlertItem(
                        id=f"a{counter}",
                        kind="Action",
                        symbol=symbol,
                        reason=f"Time stop — {symbol} held {days_held}d (hold {hold}d)",
                        timestamp=now_iso,
                        recId=pos.rec_id,
                        alertType="TIME_STOP",
                        referenceValue=float(days_held),
                        direction=pos.direction,
                        contract=pos.contract,
                    ))

        pos.alert_state = alert_state

    return alerts