from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import PortfolioPositionModel
from app.schemas import AlertItem
from app.services.audit import log_event
from app.services.position_alert_log import log_position_alert

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"


@lru_cache(maxsize=1)
def _load_risk_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _premium_stop_pct() -> float:
    return float(_load_risk_config().get("reward_risk", {}).get("premium_stop_pct", 0.60))


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
        if targets and price is not None:
            first_target = targets[0]
            target_stock_price = (
                first_target.get("stock_price") or first_target.get("stockPrice") or 0
            )
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
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Target reached — {symbol} at ${price:.2f}",
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
        if pos.stop is not None and price is not None and _sustained("STOP_REACHED", stop_breached_raw):
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
        if pos.structural_stop is not None and price is not None and _sustained("STRUCTURAL_STOP_BREACHED", structural_breached_raw):
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

        # PREMIUM_STOP
        premium_hit_raw = bool(
            opt_price is not None and pos.entry_price > 0
            and opt_price <= pos.entry_price * (1 - _premium_stop_pct())
        )
        if _sustained("PREMIUM_STOP", premium_hit_raw):
            counter += 1
            threshold_price = round(pos.entry_price * (1 - _premium_stop_pct()), 4)
            log_event("alert_fired", pos.rec_id, {
                "symbol": symbol,
                "alertType": "PREMIUM_STOP",
                "optPrice": opt_price,
                "entryPrice": pos.entry_price,
                "thresholdPct": _premium_stop_pct(),
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
                reason=f"Premium stop — {symbol} option at ${opt_price:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="PREMIUM_STOP",
                price=opt_price,
                referenceValue=threshold_price,
                direction=pos.direction,
                contract=pos.contract,
            ))

        # TIME_STOP — day-granularity already; sustain does not apply.
        expiry = parse_expiry_from_contract(pos.contract)
        if expiry is not None:
            days_to_expiry = (expiry - date.today()).days
            if 0 <= days_to_expiry <= 3:
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

        pos.alert_state = alert_state

    return alerts