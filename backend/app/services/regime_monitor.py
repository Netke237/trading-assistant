"""Lightweight regime-flip monitor.

Runs as an asyncio background task. Every N minutes:
  1. Checks overall market regime.
  2. If REJECT and open positions exist → broadcasts a WebSocket warning.
  3. Updates the module-level conviction cache (used by auto_trader vol sizing).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

_RISK_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_rules.yaml"

# ── Module-level conviction cache (read by auto_trader._apply_vol_sizing) ─────
_last_conviction: float | None = None


def get_last_conviction() -> float | None:
    """Return cached OMM conviction_pct (bullish frame). None = not yet computed."""
    return _last_conviction


def set_last_conviction(pct: float) -> None:
    global _last_conviction
    _last_conviction = float(pct)


# ── Internal helpers (thin wrappers so tests can mock them easily) ─────────────

async def _get_overall_regime() -> str:
    """Return 'PASS', 'CAUTION', 'REJECT', or 'PENDING'."""
    loop = asyncio.get_running_loop()
    from app.routers.regime import compute_overall_regime
    return await loop.run_in_executor(None, compute_overall_regime)


async def _has_open_positions() -> bool:
    """Return True if any open positions exist in the DB."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM portfolio_positions"))
            count = result.scalar()
            return (count or 0) > 0
    except Exception as exc:
        logger.debug("regime_monitor: position count failed: %s", exc)
        return False


async def _broadcast_alert(payload: dict) -> None:
    """Send a WebSocket alert via the alert_service broadcast mechanism."""
    try:
        from app.services.alert_service import alert_service
        await alert_service.broadcast(payload)
    except Exception as exc:
        logger.warning("regime_monitor: broadcast failed: %s", exc)


async def _update_conviction_cache() -> None:
    """Refresh the module-level conviction cache from the current OMM result."""
    try:
        loop = asyncio.get_running_loop()

        def _compute():
            from app.data.market import fetch_candles
            from app.services.regime_omm import compute_omm
            candles = fetch_candles("SPX", bars=600)
            if not candles:
                return None
            closes = [c["close"] for c in candles]
            result = compute_omm(closes, direction="Bullish")
            return result.conviction_pct if result else None

        pct = await loop.run_in_executor(None, _compute)
        if pct is not None:
            set_last_conviction(pct)
    except Exception as exc:
        logger.debug("regime_monitor: conviction cache update failed: %s", exc)


# ── Tick ──────────────────────────────────────────────────────────────────────

async def _tick() -> None:
    """One monitoring cycle."""
    try:
        await _update_conviction_cache()

        regime = await _get_overall_regime()
        if regime != "REJECT":
            return

        has_pos = await _has_open_positions()
        if not has_pos:
            return

        payload = {
            "type": "REGIME_FLIP_WARNING",
            "regime": "REJECT",
            "message": "Market regime has turned REJECT while positions are open",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning("regime_monitor: REJECT regime with open positions — alert broadcast")

    except Exception as exc:
        logger.error("regime_monitor _tick failed: %s", exc)


# ── Long-running coroutine ─────────────────────────────────────────────────────

async def run_regime_monitor() -> None:
    """Asyncio coroutine: runs forever, ticking then sleeping."""
    while True:
        await _tick()
        try:
            loop = asyncio.get_running_loop()

            def _read_interval() -> int:
                with open(_RISK_CONFIG_PATH) as f:
                    cfg = yaml.safe_load(f)
                return int(cfg.get("auto_trade", {}).get("regime_monitor_interval_minutes", 15))

            interval = await loop.run_in_executor(None, _read_interval)
        except Exception:
            interval = 15
        await asyncio.sleep(interval * 60)
