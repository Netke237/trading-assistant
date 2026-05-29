"""
augment.py — shared contract augmentation helper.

Extracted from app.routers.scan so it can be reused by other routers
(e.g., /api/contracts) without creating circular imports.
"""
from __future__ import annotations

from app.models.black_scholes import bs_delta


def _augment(c: dict, stock_price: float = 0.0) -> dict:
    """
    Enrich a raw contract dict with computed fields required by validate_contract().

    Args:
        c:           Raw contract dict from fetch_option_chain / Tradier.
        stock_price: Current stock price; used to compute BS delta when greeks
                     are missing but IV is available.

    Returns:
        New dict with all original keys plus:
          - bid / ask  (derived from price ± spread/2)
          - delta      (from greeks or BS approximation)
          - iv_rank    (snake_case alias of ivRank for contract_validator)
    """
    mid = float(c.get("price", 0))
    spread = float(c.get("spread", 0))
    iv = float(c.get("implied_volatility") or 0)
    delta = float(c.get("delta") or 0)

    # Compute BS delta when greeks are missing but IV is available
    if delta == 0 and iv > 0 and stock_price > 0:
        K = float(c.get("strike", stock_price))
        T = int(float(c.get("dte", 30))) / 365.0
        is_call = c.get("right", "C") == "C"
        computed = bs_delta(stock_price, K, T, r=0.05, sigma=iv, is_call=is_call)
        if computed != 0.0:
            delta = round(computed, 4)

    return {
        **c,
        "bid": round(max(0.01, mid - spread / 2), 2),
        "ask": round(mid + spread / 2, 2),
        "delta": delta,
        "iv_rank":       round(float(c.get("ivRank", 0)), 1),       # snake_case alias for contract_validator
        "iv_percentile": round(float(c.get("ivPercentile", 0)), 1),  # forwarded for future scoring rules
    }
