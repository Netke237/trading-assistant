"""tastytrade IV Rank/Percentile — Governor-paced, routed through the shared
event-loop bridge (Task 6's tastytrade_bridge.run_coro) rather than a raw
asyncio.run() call, so it can be called from market.py's synchronous
fetch_option_chain without risking the cross-loop Governor-lock hazard
Task 6 exists to fix.

Inserted as a fallback tier between IBKR's real IV Rank/Percentile
(backend/app/data/ibkr.py:fetch_iv_metrics_ibkr) and the raw-IV-as-proxy
fallback in market.py — see market.py's fetch_option_chain for the full
tier order.

Both fields arrive as 0-1 decimal strings on the wire ("0.3897" = 38.97) and
are normalized to 0-100 in _fetch_async. The SDK's tos_/tw_ rank variants are
the same scale; the raw fields already follow the API's
implied_volatility_index_rank_source selection, so we keep them.
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
            # Wire format: 0-1 decimal strings ("0.3897" = rank 38.97; values
            # > 1.0 are legitimate — current IV above the 52-week high — and
            # must NOT be clamped). Normalize to the 0-100 scale
            # fetch_iv_metrics_ibkr returns and every consumer (market.py
            # enrichment, stock_scorer's vol rule, contract_validator,
            # spread_builder, ContractDetails' int fields, Step 5/6 UI)
            # expects. round(..., 1) matches the precision market.py applies
            # to the IBKR tier and avoids float dust (0.623*100 =
            # 62.300000000000004).
            result[m.symbol] = {
                "ivRank": round(float(rank) * 100, 1),
                "ivPercentile": round(float(pct) * 100, 1),
            }
        except (TypeError, ValueError):
            continue
    return result or None


def fetch_iv_metrics_tastytrade(
    symbols: list[str], slot: str = "tastytrade_paper"
) -> dict[str, dict] | None:
    """Sync wrapper. Returns {symbol: {"ivRank": float, "ivPercentile": float}}
    on the 0-100 scale (wire format is 0-1 decimal strings; conversion happens
    in _fetch_async), or None if unconfigured / the call failed. `slot` defaults
    to the paper account credentials since that's the one Kenneth will have
    funded and active; pass "tastytrade_live" explicitly once that account is in
    use for something other than credential storage."""
    try:
        return run_coro(_fetch_async(symbols, slot))
    except Exception as exc:
        logger.warning("fetch_iv_metrics_tastytrade failed: %s", exc)
        return None
