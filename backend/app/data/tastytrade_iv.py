"""tastytrade IV Rank/Percentile — Governor-paced, routed through the shared
event-loop bridge (Task 6's tastytrade_bridge.run_coro) rather than a raw
asyncio.run() call, so it can be called from market.py's synchronous
fetch_option_chain without risking the cross-loop Governor-lock hazard
Task 6 exists to fix.

Inserted as a fallback tier between IBKR's real IV Rank/Percentile
(backend/app/data/ibkr.py:fetch_iv_metrics_ibkr) and the raw-IV-as-proxy
fallback in market.py — see market.py's fetch_option_chain for the full
tier order.
"""
from __future__ import annotations

import logging

from tastytrade.metrics import get_market_metrics

from app.data.governor import get_governor, ProviderUnavailable
from app.data.tastytrade_bridge import run_coro
from app.data.tastytrade_session import get_session

logger = logging.getLogger(__name__)


async def _fetch_async(symbols: list[str], slot: str) -> dict[str, dict] | None:
    session = get_session(slot)
    if session is None:
        return None
    try:
        metrics = await get_governor().call(
            "tastytrade",
            lambda: get_market_metrics(session, symbols),
        )
    except ProviderUnavailable:
        logger.warning("tastytrade circuit open — skipping IV metrics fetch")
        return None
    except Exception as exc:
        logger.debug("tastytrade market-metrics fetch failed: %s", exc)
        return None

    result: dict[str, dict] = {}
    for m in metrics:
        rank = getattr(m, "implied_volatility_index_rank", None)
        pct = getattr(m, "implied_volatility_percentile", None)
        if rank is None or pct is None:
            continue
        try:
            result[m.symbol] = {"ivRank": float(rank), "ivPercentile": float(pct)}
        except (TypeError, ValueError):
            continue
    return result or None


def fetch_iv_metrics_tastytrade(
    symbols: list[str], slot: str = "tastytrade_paper"
) -> dict[str, dict] | None:
    """Sync wrapper. Returns {symbol: {"ivRank": float, "ivPercentile": float}}
    or None if unconfigured / the call failed. `slot` defaults to the paper
    account credentials since that's the one Kenneth will have funded and
    active; pass "tastytrade_live" explicitly once that account is in use
    for something other than credential storage."""
    try:
        return run_coro(_fetch_async(symbols, slot))
    except Exception as exc:
        logger.warning("fetch_iv_metrics_tastytrade failed: %s", exc)
        return None
