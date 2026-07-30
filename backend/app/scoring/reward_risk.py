from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Optional

from app.models.heston import HestonParams, heston_price
from app.models.black_scholes import bs_iv, bs_price

RrModel = Literal["Heston repriced", "BS repriced (IV-derived)"]


@dataclass
class RrResult:
    rr_ratio: float
    model_used: RrModel
    estimated_exit_premium: float


def _derive_fallback_sigma(
    current_premium: float,
    stock_price: float,
    strike: float,
    expiry_years: float,
    r: float,
    is_call: bool,
    sigma_fallback: float,
) -> float:
    """Back out the contract's own market-implied vol from its current quote
    (at the full time-to-expiry the quote was made at, expiry_years). Falls
    back to sigma_fallback when bs_iv can't converge (e.g. degenerate or
    extreme-moneyness quotes)."""
    sigma = bs_iv(current_premium, stock_price, strike, expiry_years, r, is_call)
    return sigma if sigma is not None else sigma_fallback


def _bs_reprice_or_delta_approx(
    t_price: float,
    stock_price: float,
    strike: float,
    dte_at_target: float,
    r: float,
    sigma: float,
    is_call: bool,
    current_premium: float,
) -> float:
    """Reprice at t_price via Black-Scholes using the given sigma. Falls back
    to the crude flat-delta guess (the pre-fix behavior) only if bs_price
    itself is unusable — kept as a last-resort safety net. Expected to be
    rare in practice (dte_at_target is provably positive via its own floor;
    t_price and strike come from caller-supplied market/config data that is
    not independently validated here), but not proven unreachable — callers
    do not enforce t_price > 0 or strike > 0."""
    price = bs_price(t_price, strike, dte_at_target, r, sigma, is_call)
    if math.isfinite(price) and price > 0:
        return price
    delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
    price_move = abs(t_price - stock_price)
    return current_premium + delta * price_move


def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,   # reserved: kept for call-site symmetry; risk is now premium * premium_stop_pct, not invalidation-based
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,   # fraction of premium at risk (stop-loss basis)
) -> RrResult:
    model_used: RrModel
    heston_ok = False
    dte_at_target = max(expiry_years * 0.5, 7 / 365)

    if heston_params is not None:
        try:
            heston_exit_premium = heston_price(target_price, strike, dte_at_target, r, heston_params, is_call)
        except Exception:
            heston_exit_premium = 0.0
        heston_ok = math.isfinite(heston_exit_premium) and heston_exit_premium > 0

    if heston_ok:
        exit_premium = heston_exit_premium
        model_used = "Heston repriced"
    else:
        sigma = _derive_fallback_sigma(current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback)
        exit_premium = _bs_reprice_or_delta_approx(
            target_price, stock_price, strike, dte_at_target, r, sigma, is_call, current_premium,
        )
        model_used = "BS repriced (IV-derived)"

    exit_premium = max(exit_premium, 0.01)

    risk = current_premium * premium_stop_pct   # only risk the stop-loss fraction
    reward = exit_premium - current_premium

    if reward <= 0 or risk <= 0:
        return RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=round(exit_premium, 2))

    rr_ratio = round(reward / risk, 2)
    return RrResult(
        rr_ratio=rr_ratio,
        model_used=model_used,
        estimated_exit_premium=round(exit_premium, 2),
    )


def estimate_targets(
    stock_price: float,
    base_target_price: float,   # T1 = the existing single target
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,
) -> list:
    """
    Build 3 target levels: T1=base, T2=base*1.5 move, T3=base*2.0 move.
    For Bullish calls: T2 = stock_price + 1.5 * (T1 - stock_price)
    For Bearish puts:  T2 = stock_price - 1.5 * (stock_price - T1)
    Each level repriced via Heston if available, else delta approximation.

    premium_stop_pct: fraction of current_premium used as risk basis for R/R (default 0.60).
    """
    from app.schemas import TargetLevel as TargetLevelSchema, PricingMethod

    move = abs(base_target_price - stock_price)
    direction_sign = 1 if base_target_price > stock_price else -1

    targets_prices = [
        stock_price + direction_sign * move,          # T1
        stock_price + direction_sign * move * 1.5,    # T2
        stock_price + direction_sign * move * 2.0,    # T3
    ]

    results = []
    prev_display_price = None  # the displayed/chosen price of the previous level — used
                                # only for the final non-decreasing-display invariant below.
    prev_heston_price = None   # the previous level's TRUE Heston-derived price (raw, or
                                # floored against this same reference) — used only to decide
                                # whether the current level's raw Heston price is a numerical
                                # artifact. Deliberately never set from a delta-approximation
                                # fallback value, so a fallback at one level can never distort
                                # the artifact check for a later, independently-legitimate
                                # Heston price.
    fallback_sigma = None       # the fallback sigma, derived at most once per ladder (lazily,
                                 # on whichever level first needs it) and reused for every
                                 # later level that also needs it — current_premium,
                                 # stock_price, strike, expiry_years and is_call are identical
                                 # across T1/T2/T3, only t_price changes per level.
    dte_at_target = max(expiry_years * 0.5, 7 / 365)  # invariant across T1/T2/T3 — same
                                                        # reasoning as fallback_sigma above.
    for t_price in targets_prices:
        opt_price: float
        method: PricingMethod
        raw_price = None
        heston_ok = False          # was the raw Heston price numerically usable?
        use_heston_price = False   # does this level's (post-floor) Heston price also
                                    # clear the display-consistency check below?

        if heston_params is not None:
            try:
                raw_price = heston_price(t_price, strike, dte_at_target, r, heston_params, is_call)
            except Exception:
                raw_price = None
            heston_ok = raw_price is not None and math.isfinite(raw_price) and raw_price > 0

        if heston_ok:
            floored_price = raw_price
            # T1/T2/T3 share dte_at_target and only differ in t_price, so a
            # correctly-priced option must be monotonically increasing ACROSS
            # THAT LADDER — a Heston price that comes out lower than the
            # previous level's TRUE Heston price is a numerical-integration
            # artifact — a real, reproducible quirk of heston_price()'s
            # integration for deep-OTM/long-dated inputs, not a real option
            # value or a sign that Heston is unusable for this level. Floor it
            # against the true Heston reference rather than discarding the whole
            # Heston computation for a cruder model — this keeps the level
            # labelled "Heston repriced" and, critically, keeps
            # prev_heston_price anchored to real Heston output so a LATER
            # level's own legitimate Heston price is never compared against
            # an inflated fallback value.
            if prev_heston_price is not None and floored_price < prev_heston_price:
                floored_price = prev_heston_price
            # Even after flooring against the TRUE Heston chain, this level
            # can still be lower than what's already on display, if an
            # earlier, unrelated level had a genuine Heston failure and its
            # fallback was itself inflated. This level cannot honestly stay
            # labelled "Heston repriced" in that case — the number that would
            # end up on screen (after the invariant clamp below) would not be
            # what Heston computed for THIS level, it would be inherited from
            # that earlier, unrelated fallback. Fall back to the delta
            # approximation for this level too, exactly as if Heston had
            # failed outright — this is the pre-existing behavior for every
            # case that isn't a pure numerical artifact, unchanged by this fix.
            if prev_display_price is not None and floored_price < prev_display_price:
                use_heston_price = False
            else:
                use_heston_price = True
                opt_price = floored_price
                method = PricingMethod.HESTON
                prev_heston_price = opt_price

        if not use_heston_price:
            # Heston is unusable for this level — either genuinely (no
            # params, raised, or returned a non-finite/non-positive price;
            # heston_ok is False) or because its own artifact-floored price
            # still can't clear the display check above (heston_ok was True
            # but use_heston_price was rejected). Either way, fall back to a
            # Black-Scholes reprice using the contract's own market-implied
            # vol. This level does NOT update prev_heston_price: a later
            # level's Heston price is still judged against the last real
            # Heston reference, not this fallback.
            if fallback_sigma is None:
                fallback_sigma = _derive_fallback_sigma(
                    current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback,
                )
            opt_price = max(0.01, _bs_reprice_or_delta_approx(
                t_price, stock_price, strike, dte_at_target, r, fallback_sigma, is_call, current_premium,
            ))
            method = PricingMethod.DELTA_APPROX

        # Hard invariant: the *displayed* ladder must be non-decreasing
        # regardless of which pricing path produced each level. A
        # delta-approximation fallback can itself undershoot the previous
        # level's displayed price — clamp it up to prev_display_price rather
        # than leave a visibly-wrong ladder. This only ever raises a level,
        # never lowers one, and prev_display_price is None for T1 so T1 is
        # never clamped against anything (including current_premium, which
        # is intentionally never part of this chain). Note this clamp also
        # raises rrContribution below for the clamped level (reward =
        # opt_price - current_premium uses the post-clamp price) —
        # intentional: rrContribution must stay consistent with the
        # estimatedOptionPrice actually shown on that same row. For a level
        # that was just accepted on the Heston branch above, this clamp is
        # provably a no-op: acceptance already required
        # floored_price >= prev_display_price, so opt_price already satisfies
        # the invariant here — this clamp only ever does real work when the
        # level fell back to the delta approximation.
        if prev_display_price is not None:
            opt_price = max(opt_price, prev_display_price)

        prev_display_price = opt_price

        reward = opt_price - current_premium
        risk_basis = current_premium * premium_stop_pct
        rr = round(reward / risk_basis, 2) if risk_basis > 0 and reward > 0 else 0.0

        results.append(TargetLevelSchema(
            targetPrice=round(t_price, 2),
            stockPrice=round(t_price, 2),
            estimatedOptionPrice=round(opt_price, 2),
            pricingMethod=method,
            rrContribution=rr,
        ))

    return results