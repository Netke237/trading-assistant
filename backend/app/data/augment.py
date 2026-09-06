"""
augment.py — shared contract augmentation helper.

Extracted from app.routers.scan so it can be reused by other routers
(e.g., /api/contracts) without creating circular imports.
"""
from __future__ import annotations

from app.models.black_scholes import bs_delta


def opt_int(v) -> int | None:
    """Round an optional numeric to int, preserving None.

    `ivRank` is None on every chain where neither IBKR nor tastytrade answered
    -- the common case -- and `int(chain.get("ivRank", 50))` raised TypeError
    on it, because the key is PRESENT and holds None so the 50 default never
    applied (PHASE-A-NULL-IVRANK-2026-09-06). None must survive to the wire:
    it is what tells the UI it has no percentile to show.
    """
    return None if v is None else int(round(float(v)))


def opt_float(v) -> float | None:
    """Round an optional numeric to 1dp, preserving None. See opt_int."""
    return None if v is None else round(float(v), 1)


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
          - iv_rank    (the resolved volatility figure for contract_validator --
                        a percentile when one exists, otherwise the absolute
                        level; None when neither does)
          - iv_basis   ("rank" | "absolute" | "none") -- WHICH quantity iv_rank
                        holds, and therefore which threshold set may judge it
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

    # ── Resolve the volatility figure (PHASE-A-NULL-IVRANK-2026-09-06) ───────
    # `ivRank` and `iv` are TWO DIFFERENT QUANTITIES and usually only one is
    # present:
    #   ivRank -- a TRUE PERCENTILE (where today's IV sits in this name's own
    #             52-week range), supplied only when IBKR or tastytrade
    #             answered.
    #   iv     -- ABSOLUTE implied volatility, 0-100, from Tradier per strike,
    #             the yfinance backfill, or scan.py's Black-Scholes inversion.
    # Prefer the rank, exactly as routers/scan.py does: a percentile says where
    # this vol sits FOR THIS NAME, which an absolute level cannot. `iv_basis`
    # records which one won so contract_validator judges it against the
    # matching thresholds -- scoring a 45% absolute IV as though it were the
    # 45th percentile is the defect this split exists to prevent.
    #
    # Note the deliberate asymmetry, matching scan.py's resolution: a rank of
    # 0.0 is MEANINGFUL (bottom of the 52-week range) so it is tested with
    # `is not None`, whereas an absolute IV of 0 is a missing-data sentinel and
    # is tested for truthiness.
    _rank = c.get("ivRank")
    _abs = c.get("iv")
    if _rank is not None:
        iv_value: float | None = round(float(_rank), 1)
        iv_basis = "rank"
    elif _abs:
        iv_value, iv_basis = round(float(_abs), 1), "absolute"
    else:
        iv_value, iv_basis = None, "none"

    _pct = c.get("ivPercentile")

    return {
        **c,
        "bid": round(max(0.01, mid - spread / 2), 2),
        "ask": round(mid + spread / 2, 2),
        "delta": delta,
        "iv_rank":       iv_value,   # snake_case alias for contract_validator
        "iv_basis":      iv_basis,
        "iv_percentile": round(float(_pct), 1) if _pct is not None else None,
    }
