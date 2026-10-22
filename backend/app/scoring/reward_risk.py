from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Literal, Optional

from app.models.heston import HestonParams, heston_price_detail
from app.models.black_scholes import bs_iv, bs_price

_log = logging.getLogger(__name__)

RrModel = Literal["Heston repriced", "BS repriced (IV-derived)", "Delta approximation"]


@dataclass
class RrResult:
    rr_ratio: float
    model_used: RrModel
    estimated_exit_premium: float
    risk_basis: Literal["premium_stop", "stock_stop", "full_premium"] = "premium_stop"


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
) -> tuple[float, bool]:
    """Reprice at t_price via Black-Scholes using the given sigma. Falls back
    to the crude flat-delta guess (the pre-fix behavior) only if bs_price
    itself is unusable — kept as a last-resort safety net. Expected to be
    rare in practice (dte_at_target is provably positive via its own floor;
    t_price and strike come from caller-supplied market/config data that is
    not independently validated here), but not proven unreachable — callers
    do not enforce t_price > 0 or strike > 0.

    Returns (price, used_bs_reprice) — callers label the result "BS repriced
    (IV-derived)" vs "Delta approximation" from used_bs_reprice rather than
    assuming every call here is a real BS reprice (that assumption was itself
    a bug: see PricingMethod.DELTA_APPROX's history)."""
    price = bs_price(t_price, strike, dte_at_target, r, sigma, is_call)
    if math.isfinite(price) and price > 0:
        return price, True
    delta = 0.5 if (is_call and t_price > strike) or (not is_call and t_price < strike) else 0.3
    price_move = abs(t_price - stock_price)
    return current_premium + delta * price_move, False


# The repricing horizon: "how far ahead do we reprice, when we ask what the
# option is worth AT a level". Historically this was hardcoded here and in
# first_passage.py as `max(expiry_years * 0.5, 7/365)` — a fixed half-life that
# ignores both how long the user intends to hold and what the simulation itself
# observed. app.scoring.reprice_horizon.resolve_reprice_days() now owns that
# rule; both functions below accept the resolved value as `reprice_years` and
# fall back to the historical formula when a caller does not supply one, so
# every existing call site keeps its current numbers.
#
# NOT WIRED UP, AND THAT NOW COSTS SOMETHING. No caller anywhere passes
# `reprice_years` (`grep -rn reprice_years app/` finds only these definitions),
# so trade_plan.py, scan.py and contracts.py all still get the historical
# half-life via _default_reprice_years. first_passage.py's Stage 1 DID switch,
# so on one TradeCard the Monte Carlo card's "Stock price" per target is now
# back-solved at `dte - resolve_reprice_days(...)` while the Fixed % Ladder's
# target prices are still back-solved at `expiry_years * 0.5` — two answers to
# the same question, a few inches apart: $189.28 against $191.70 on a 30-DTE
# contract ($2.43), and $191.25 against $201.47 on a one-year contract at
# sigma = 0.2165 ($10.22; $12.93 at sigma = 0.31). An earlier version of this
# note quoted $4.84 for the LEAP, which only reproduces at the reference
# contract's $5.20 premium — a 3.4% implied vol on a one-year 190 call over a
# $185 stock, i.e. a contract that cannot exist. At any realistic vol the gap is
# roughly twice to three times what that said.
#
# Deliberately not fixed here: wiring it changes numbers on the Fixed % Ladder,
# a card outside the barrier race's remit, and rewrites ~30 tests in
# test_reward_risk.py and test_multi_target.py that assert half-expiry pricing.
# It needs its own change with its own sign-off. Until then, spec 2.2's claim
# that resolve_reprice_days is "the ONLY place that rule lives" is aspirational,
# not true.
#
# `reprice_years` IS A TIME TO EXPIRY REMAINING, in years — it goes straight
# into bs_price's T. resolve_reprice_days() returns the opposite quantity (days
# ELAPSED until the barrier), so a caller wiring these two together must convert
# with reprice_horizon.remaining_years_at_barrier(dte, days) and must not pass
# `resolve_reprice_days(...) / 365`. Passing elapsed days inverts theta: the
# later a barrier is reached, the more the contract appears to be worth at it.
def _default_reprice_years(expiry_years: float) -> float:
    return max(expiry_years * 0.5, 7 / 365)


def estimate_rr(
    stock_price: float,
    target_price: float,
    invalidation_price: float,   # kept for call-site symmetry; risk_fraction supplies the independently priced stock-stop loss
    strike: float,
    expiry_years: float,
    current_premium: float,
    is_call: bool,
    r: float = 0.05,
    heston_params: HestonParams | None = None,
    sigma_fallback: float = 0.25,
    premium_stop_pct: float = 0.60,   # fraction of premium at risk (stop-loss basis)
    risk_fraction: float | None = None,
    reprice_years: float | None = None,   # remaining_years_at_barrier(...); None = historical half-life
    protective_stop_order: bool = False,
) -> RrResult:
    """Reward/risk of buying the contract at current_premium and selling it
    when the stock reaches target_price.

    protective_stop_order (TRADING-REVIEW-PHASE-C-RR, review M7, decision D5):
    no protective option order is ever placed -- the premium stop is an alert
    level (services/premium_stop.py) and sizing already assumes the whole
    premium can be lost. So by default (False, every caller today) the risk leg
    is the FULL premium and risk_basis is "full_premium". True restores the
    premium-stop / captured stock-stop basis (resolved_risk_dollars) unchanged,
    for the day a real protective order exists.
    """
    if captured_stock_risk(current_premium, risk_fraction) is not None:
        current_premium = round(current_premium, 2)
    model_used: RrModel
    heston_ok = False
    dte_at_target = reprice_years if reprice_years is not None else _default_reprice_years(expiry_years)

    if heston_params is not None:
        try:
            detail = heston_price_detail(target_price, strike, dte_at_target, r, heston_params, is_call)
            # fell_back: the integration failed and the price is Black-Scholes
            # at sqrt(v0), not Heston -- treat it exactly like a failed Heston
            # price so it is never labelled "Heston repriced" (DECISION-23 H-1).
            heston_exit_premium = 0.0 if detail.fell_back else detail.price
        except Exception:
            heston_exit_premium = 0.0
        heston_ok = math.isfinite(heston_exit_premium) and heston_exit_premium > 0

    if heston_ok:
        exit_premium = heston_exit_premium
        model_used = "Heston repriced"
    else:
        sigma = _derive_fallback_sigma(current_premium, stock_price, strike, expiry_years, r, is_call, sigma_fallback)
        exit_premium, used_bs_reprice = _bs_reprice_or_delta_approx(
            target_price, stock_price, strike, dte_at_target, r, sigma, is_call, current_premium,
        )
        model_used = "BS repriced (IV-derived)" if used_bs_reprice else "Delta approximation"

    exit_premium = max(exit_premium, 0.01)

    if captured_stock_risk(current_premium, risk_fraction) is not None:
        exit_premium = round(exit_premium, 2)
    basis: Literal["premium_stop", "stock_stop", "full_premium"]
    if protective_stop_order:
        risk = resolved_risk_dollars(current_premium, premium_stop_pct, risk_fraction)
        basis = ("stock_stop" if captured_stock_risk(current_premium, risk_fraction) is not None
                 and risk < round(current_premium * premium_stop_pct, 2) else "premium_stop")
    else:
        risk = current_premium   # already cents-rounded above when a stock risk is captured
        basis = "full_premium"
    reward = exit_premium - current_premium

    if risk <= 0:
        return RrResult(rr_ratio=0.0, model_used=model_used, estimated_exit_premium=round(exit_premium, 2), risk_basis=basis)

    rr_ratio = round(reward / risk, 2)
    return RrResult(
        rr_ratio=rr_ratio,
        model_used=model_used,
        estimated_exit_premium=round(exit_premium, 2),
        risk_basis=basis,
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
    risk_fraction: float | None = None,
    reprice_years: float | None = None,   # remaining_years_at_barrier(...); None = historical half-life
    protective_stop_order: bool = False,
) -> list:
    """
    Build 3 target levels: T1=base, T2=base*1.5 move, T3=base*2.0 move.
    For Bullish calls: T2 = stock_price + 1.5 * (T1 - stock_price)
    For Bearish puts:  T2 = stock_price - 1.5 * (stock_price - T1)
    Each level repriced via Heston if available, else delta approximation.

    premium_stop_pct: premium risk ceiling; a valid risk_fraction can lower it.
                      Read only when protective_stop_order is True.
    protective_stop_order: False (every caller today) divides each level's
                      reward by the FULL premium -- see estimate_rr.
    """
    from app.schemas import TargetLevel as TargetLevelSchema, PricingMethod

    if captured_stock_risk(current_premium, risk_fraction) is not None:
        current_premium = round(current_premium, 2)

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
    dte_at_target = (reprice_years if reprice_years is not None
                     else _default_reprice_years(expiry_years))   # invariant across T1/T2/T3 —
                                                        # same reasoning as fallback_sigma above.
    for t_price in targets_prices:
        opt_price: float
        method: PricingMethod
        raw_price = None
        heston_ok = False          # was the raw Heston price numerically usable?
        use_heston_price = False   # does this level's (post-floor) Heston price also
                                    # clear the display-consistency check below?

        if heston_params is not None:
            try:
                detail = heston_price_detail(t_price, strike, dte_at_target, r, heston_params, is_call)
                # fell_back: Black-Scholes at sqrt(v0), not Heston -- treated
                # exactly like a failed Heston price (DECISION-23 H-1).
                raw_price = None if detail.fell_back else detail.price
            except Exception:
                raw_price = None
            heston_ok = raw_price is not None and math.isfinite(raw_price) and raw_price > 0

        if heston_ok:
            floored_price = raw_price
            # T1/T2/T3 share dte_at_target and only differ in t_price, so a
            # correctly-priced option must be monotonically increasing ACROSS
            # THAT LADDER. A Heston price that comes out lower than the
            # previous level's Heston price therefore cannot be a real option
            # value.
            #
            # WHAT IT IS, HOWEVER, IS NOW UNKNOWN — read this before trusting
            # the floor (Phase F1, 2026-09-12). This floor was written when
            # the dip was believed to be an inherent quirk of heston_price()'s
            # numerical integration for deep-OTM/long-dated inputs. That
            # belief was wrong: the dip was a defect in heston_price's Fourier
            # inversion (a doubled frequency, 2i*phi*ln(S/K)), now fixed --
            # see docs/superpowers/plans/2026-09-12-heston-calibration-spec.md.
            # No fixture in the suite produces a natural dip any more, so
            # there is no longer a known mechanism that reaches this branch.
            #
            # The floor is DELIBERATELY RETAINED, with its cost stated: it
            # only ever raises a level, and "no dip on the fixtures in this
            # suite" is not "no dip on every live chain". But because the one
            # mechanism it was built for is gone, a dip that DOES appear here
            # now most likely means the pricer has regressed -- and a SILENT
            # floor would quietly raise it instead of surfacing it. The two
            # rewritten fixture tests assert STRICT increase for exactly that
            # reason. Floor it against the true Heston reference rather than
            # discarding the whole Heston computation for a cruder model —
            # this keeps the level labelled "Heston repriced" and, critically,
            # keeps prev_heston_price anchored to real Heston output so a
            # LATER level's own legitimate Heston price is never compared
            # against an inflated fallback value.
            #
            # AND IT NOW SAYS SO WHEN IT FIRES (decision LADDER-FLOOR-LOG-
            # 2026-09-13). Keeping the floor silent is what made it a mask
            # rather than a guard. This line is the mechanism by which the
            # live evidence accumulates on its own -- spec section 6.3 says
            # remove the floor "only after F1 has run against live chains
            # long enough to say the artifact never appears", and without a
            # log there is nothing to read that back off. WARNING, not INFO,
            # and that is measured: under uvicorn's default logging config
            # the root logger has no handler and sits at WARNING, so an
            # `app.*` INFO record is dropped outright.
            if prev_heston_price is not None and floored_price < prev_heston_price:
                _log.warning(
                    "Heston target ladder dipped and was floored: strike %.2f %s, "
                    "%.4fy to expiry, repriced at %.4fy, target spot %.2f — Heston "
                    "returned %.4f against the previous level's %.4f, raised to match. "
                    "F1 removed the only known cause of this (the Fourier-inversion "
                    "defect); a dip here now most likely means the pricer has regressed.",
                    strike, "C" if is_call else "P", expiry_years, dte_at_target,
                    t_price, floored_price, prev_heston_price,
                )
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
            # params, raised, fell back to Black-Scholes at sqrt(v0), or
            # returned a non-finite/non-positive price; heston_ok is False)
            # or because its own artifact-floored price
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
            raw_fallback_price, used_bs_reprice = _bs_reprice_or_delta_approx(
                t_price, stock_price, strike, dte_at_target, r, fallback_sigma, is_call, current_premium,
            )
            opt_price = max(0.01, raw_fallback_price)
            method = PricingMethod.BS_REPRICED if used_bs_reprice else PricingMethod.DELTA_APPROX

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

        if captured_stock_risk(current_premium, risk_fraction) is not None:
            opt_price = round(opt_price, 2)
        reward = opt_price - current_premium
        risk_basis = (resolved_risk_dollars(current_premium, premium_stop_pct, risk_fraction)
                      if protective_stop_order else current_premium)
        rr = round(reward / risk_basis, 2) if risk_basis > 0 else 0.0

        results.append(TargetLevelSchema(
            targetPrice=round(t_price, 2),
            stockPrice=round(t_price, 2),
            estimatedOptionPrice=round(opt_price, 2),
            pricingMethod=method,
            rrContribution=rr,
        ))

    return results

def captured_stock_risk(premium: float, risk_fraction: float | None) -> float | None:
    """Cents-valued stop loss published to the card; sub-cent zero is unmeasured."""
    if risk_fraction is not None and math.isfinite(risk_fraction) and risk_fraction > 0:
        amount = round(round(premium, 2) * risk_fraction, 2)
        if amount > 0:
            return amount
    return None


def resolved_risk_dollars(premium: float, premium_stop_pct: float, risk_fraction: float | None) -> float:
    """New captured plans use the same cents risk as the editable card fields.

    Without captured stock loss, retain the legacy raw premium-stop calculation.
    """
    stock_loss = captured_stock_risk(premium, risk_fraction)
    if stock_loss is not None:
        return min(round(premium * premium_stop_pct, 2), stock_loss)
    return premium * premium_stop_pct
