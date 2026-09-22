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

# ── Module-level regime cache (read by auto_trader's fire path) ───────────────
_last_conviction: float | None = None
# STABILITY IS CACHED BECAUSE THE GATE NEEDS IT, and it was being discarded.
# `compute_omm` returns it from the same call that produces conviction, but only
# the pct was kept -- so the fire path could not apply `regime_gate`, whose
# REJECT arm is conditioned on `require_stable_for_reject` (true today). Half a
# rule is not the rule: applying the conviction half alone would refuse trades
# in a Fragile regime that the scan lets through, which is a DIFFERENT gate
# wearing the same name.
_last_stability: str | None = None


def get_last_conviction() -> float | None:
    """Return cached OMM conviction_pct (bullish frame). None = not yet computed."""
    return _last_conviction


def get_last_stability() -> str | None:
    """Return cached OMM stability ('Stable' | 'Fragile'). None = not yet computed."""
    return _last_stability


def set_last_conviction(pct: float) -> None:
    global _last_conviction
    _last_conviction = float(pct)


def set_last_regime(pct: float, stability: str | None) -> None:
    """Set both halves from ONE compute_omm result.

    One setter, because they are one fact: a conviction cached without the
    stability it was measured with invites a reader to pair a fresh number with
    a stale one. `set_last_conviction` is kept for callers that genuinely have
    only the pct; it leaves stability untouched rather than guessing.
    """
    global _last_stability
    set_last_conviction(pct)
    _last_stability = stability


# ── Module-level REJECT-flip sustain clock ─────────────────────────────────
_reject_since: "datetime | None" = None


def _load_risk_config() -> dict:
    with open(_RISK_CONFIG_PATH) as f:
        return yaml.safe_load(f) or {}


async def _load_regime_flip_sustain_minutes() -> int:
    loop = asyncio.get_running_loop()

    def _read() -> int:
        cfg = _load_risk_config()
        # max(0, ...) defends against a manually-edited risk_rules.yaml -- this
        # value has no API endpoint/Pydantic validation gate at all.
        return max(0, int(cfg.get("auto_trade", {}).get("regime_flip_sustain_minutes", 0)))

    return await loop.run_in_executor(None, _read)


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


async def _get_open_positions() -> list[dict]:
    """Return list of {symbol, direction, stop} for all open positions."""
    try:
        from app.database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                text("SELECT symbol, direction, stop FROM portfolio_positions")
            )
            rows = result.fetchall()
            return [
                {"symbol": row[0], "direction": row[1], "stop": row[2]}
                for row in rows
            ]
    except Exception as exc:
        logger.debug("regime_monitor: get_open_positions failed: %s", exc)
        return []


async def _fetch_stock_price(symbol: str) -> float | None:
    """Fetch current stock price. Returns None on failure."""
    try:
        loop = asyncio.get_running_loop()
        from app.data.market import fetch_price
        price = await loop.run_in_executor(None, fetch_price, symbol)
        return float(price) if price else None
    except Exception as exc:
        logger.debug("regime_monitor: price fetch failed for %s: %s", symbol, exc)
        return None


async def _check_overnight_gaps() -> None:
    """Broadcast OVERNIGHT_GAP_RISK for any position whose stock has crossed its stop level.

    Bullish: alert if current_price <= stop.
    Bearish: alert if current_price >= stop.
    Positions with stop=None are skipped.
    """
    positions = await _get_open_positions()
    if not positions:
        return

    seen_symbols: set[str] = set()
    for pos in positions:
        symbol = pos.get("symbol")
        direction = pos.get("direction", "Bullish")
        stop = pos.get("stop")

        if not symbol or stop is None:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)

        price = await _fetch_stock_price(symbol)
        if price is None:
            continue

        breached = (
            (direction == "Bullish" and price <= stop) or
            (direction == "Bearish" and price >= stop)
        )
        if not breached:
            continue

        payload = {
            "type": "OVERNIGHT_GAP_RISK",
            "symbol": symbol,
            "direction": direction,
            "current_price": price,
            "stop_level": stop,
            "message": (
                f"{symbol} has gapped through its stop level (stop={stop}, current={price}). "
                "Consider closing this position before the next session."
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _broadcast_alert(payload)
        logger.warning(
            "regime_monitor: gap risk — %s current=%.2f stop=%.2f (%s)",
            symbol, price, stop, direction,
        )


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
            return (result.conviction_pct, result.stability) if result else None

        got = await loop.run_in_executor(None, _compute)
        if got is not None:
            set_last_regime(*got)
    except Exception as exc:
        logger.debug("regime_monitor: conviction cache update failed: %s", exc)


# ── Tick ──────────────────────────────────────────────────────────────────────

async def _tick() -> None:
    """One monitoring cycle."""
    global _reject_since
    try:
        await _update_conviction_cache()
        await _check_overnight_gaps()

        regime = await _get_overall_regime()
        if regime != "REJECT":
            _reject_since = None
            return

        has_pos = await _has_open_positions()
        if not has_pos:
            _reject_since = None
            return

        now = datetime.now(timezone.utc)
        if _reject_since is None:
            _reject_since = now

        sustain_minutes = await _load_regime_flip_sustain_minutes()
        if sustain_minutes:
            elapsed_min = (now - _reject_since).total_seconds() / 60.0
            if elapsed_min < sustain_minutes:
                return  # REJECT hasn't held long enough yet

        payload = {
            "type": "REGIME_FLIP_WARNING",
            "regime": "REJECT",
            "message": (
                "Market regime has turned REJECT while positions are open. "
                "Consider closing positions before next session."
            ),
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
                cfg = _load_risk_config()
                return int(cfg.get("auto_trade", {}).get("regime_monitor_interval_minutes", 15))

            interval = await loop.run_in_executor(None, _read_interval)
        except Exception:
            interval = 15
        await asyncio.sleep(interval * 60)
