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
) -> list[AlertItem]:
    """Generate alerts for all open portfolio positions."""
    result = await db.execute(select(PortfolioPositionModel).order_by(PortfolioPositionModel.created_at))
    positions = result.scalars().all()

    alerts: list[AlertItem] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    counter = 0

    for pos in positions:
        symbol = pos.symbol
        price = current_prices.get(symbol)
        opt_price = (current_option_prices or {}).get(pos.contract) if current_option_prices else None
        targets = pos.targets or []

        # TP_HIT — direction-aware: bullish targets are above current price, bearish below
        is_bearish = pos.direction == "Bearish"
        if targets and price is not None:
            first_target = targets[0]
            target_stock_price = (
                first_target.get("stock_price") or first_target.get("stockPrice") or 0
            )
            hit = (price <= target_stock_price) if is_bearish else (price >= target_stock_price)
            if hit:
                counter += 1
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Target reached — {symbol} at ${price:.2f}",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TP_HIT",
                ))

        # STOP_REACHED — direction-aware: puts are invalidated when stock rises above stop
        stop_breached = (
            (price >= pos.stop) if is_bearish
            else (price <= pos.stop)
        )
        if pos.stop is not None and price is not None and stop_breached:
            counter += 1
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Stop breached — {symbol} below ${pos.stop:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="STOP_REACHED",
            ))

        # PREMIUM_STOP
        if opt_price is not None and pos.entry_price > 0 and opt_price <= pos.entry_price * _premium_stop_pct():
            counter += 1
            alerts.append(AlertItem(
                id=f"a{counter}",
                kind="Critical",
                symbol=symbol,
                reason=f"Premium stop — {symbol} option at ${opt_price:.2f}",
                timestamp=now_iso,
                recId=pos.rec_id,
                alertType="PREMIUM_STOP",
            ))

        # TIME_STOP — parse expiry from contract, check 0 <= days_to_expiry <= 3
        expiry = parse_expiry_from_contract(pos.contract)
        if expiry is not None:
            days_to_expiry = (expiry - date.today()).days
            if 0 <= days_to_expiry <= 3:
                counter += 1
                alerts.append(AlertItem(
                    id=f"a{counter}",
                    kind="Action",
                    symbol=symbol,
                    reason=f"Time stop — {symbol} {days_to_expiry} DTE",
                    timestamp=now_iso,
                    recId=pos.rec_id,
                    alertType="TIME_STOP",
                ))

        # EVENT_RISK — TODO: wire to event calendar when available
        # For now, skip if no event data on the position model

    return alerts