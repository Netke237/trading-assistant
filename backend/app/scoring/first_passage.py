"""Monte Carlo first-passage-time estimator for option profit targets.

Two-stage design:

  Stage 1 (display only): given a desired profit % on the option's premium,
  solve backward for the underlying stock price that would deliver it, at a
  fixed reprice horizon (the same dte_at_target convention
  reward_risk.estimate_targets already uses). This number is shown to the
  user as "roughly what stock price gets you there" — it is NOT what
  Stage 2 tests against.

  Stage 2 (the actual estimate): simulate the stock under GBM using an
  ATR-derived volatility and a signal-strength-derived drift, reprice the
  OPTION along every simulated day (shrinking time-to-expiry, not the fixed
  Stage-1 horizon), and record the first day each path's repriced option
  value crosses the profit threshold. This is what makes delta's effect on
  time-to-target implicit and correct instead of a hand-wavy day-count
  conversion: a low-delta contract's repriced value moves less per day for
  the same stock path, so it naturally takes longer, or never happens, in
  the simulation.

sigma_iv (the option's own implied vol, used for repricing) and sigma_stock
(the stock's own ATR-derived realized vol, used to drive the GBM path) are
DELIBERATELY different quantities — never conflate them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import norm

from app.models.black_scholes import bs_iv, bs_price
from app.scoring.reprice_horizon import remaining_years_at_barrier, resolve_reprice_days
from app.scoring.stock_scorer import _atr


@dataclass
class TargetEstimate:
    pct: float
    stock_price: Optional[float]   # None if unreachable within the Stage-1 bisection bracket
    option_price: float            # premium * (1 + pct) — trivial, kept for display convenience
    probability: float
    expected_days: Optional[float]   # None if probability == 0


@dataclass
class InvalidationEstimate:
    probability: float
    expected_days: Optional[float]


@dataclass
class RaceOutcome:
    """One target's row of the barrier race.

    The four probabilities are an ATTRIBUTION, not four independent estimates:
    every simulated path is assigned to exactly one of them, so they sum to 1.0
    by construction. That is the whole point of the race — the pre-existing
    TargetEstimate.probability and InvalidationEstimate.probability are each
    measured on their own and can sum past 100%.

    Every days_* is a CONDITIONAL median: the median day of the paths that
    resolved to that outcome, not of all paths.
    """
    target_pct:            float
    target_option_price:   float

    p_target_first:        float
    p_stock_stop_first:    float
    p_premium_stop_first:  float
    p_neither:             float

    days_target:           Optional[float]
    days_stock_stop:       Optional[float]
    days_premium_stop:     Optional[float]
    # The UNCONDITIONAL median day any path reaches the stock stop — the basis
    # of reprice_days_stock_stop, and a different statistic from
    # days_stock_stop, which is conditional on the stop winning the race. None
    # when no path reached the stop at all, in which case the horizon came from
    # the preset table. The card names which, rather than printing a bare "Nd"
    # that matches neither number in the table beside it.
    days_any_path_reached_stop: Optional[float]

    # The four shares allocated to hundredths, summing to exactly 1.00. These
    # are the weights the edge below was computed with and the values the card
    # prints in its chain and derives its whole-percent labels from. The raw
    # p_* above stay raw: the bars are drawn from those.
    weight_target:         float
    weight_stock_stop:     float
    weight_premium_stop:   float
    weight_neither:        float

    terminal_mean:         Optional[float]   # mean option value at expiry, over p_neither paths

    # -- Printable arithmetic (barrier-race spec 2.4) ------------------------
    # The card renders the full chain, so the response carries the INPUTS to
    # each number, not just the number.
    reward_dollar:           float           # target_option_price - premium
    # Days ELAPSED from today until the stock stop is reached — not a time to
    # expiry. Identical on all three rows: the stop leg is a property of the
    # stop, not of the target being raced against it.
    reprice_days_stock_stop: float
    stop_repriced_value:     Optional[float] # contract value AT the stock stop, repriced
    risk_stock_stop:         Optional[float] # premium - stop_repriced_value
    risk_premium_stop:       float           # premium * premium_stop_pct
    rr_stock_stop:           Optional[float] # THE measurement; None when risk <= 0
    # Constant by construction: exactly pct / premium_stop_pct. None only when
    # premium_stop_pct is non-positive, which the API rejects but the default
    # argument cannot.
    rr_premium_stop:         Optional[float]
    edge_per_contract:       Optional[float]


@dataclass
class BarrierRaceResult:
    outcomes:            list[RaceOutcome]   # one per target, same order as `targets`
    premium_stop_price:  float               # the option-value barrier actually used
    premium_stop_pct:    float
    stock_stop_price:    float               # echo of invalidation_price, for auditability
    # The premium every printed chain subtracts, already quantized to cents
    # here. The card must print THIS rather than re-rounding its own copy:
    # Python's round() is banker's rounding and JavaScript's toFixed() is not,
    # so the two disagree on exact halves and the chain would stop adding up.
    premium_used:        float
    # False when the contract's own IV could not be backed out of its quote and
    # the simulation fell back to a generic volatility. Every number on the card
    # is then about a contract the market is not pricing — the card says so
    # rather than presenting a confident dollar edge.
    iv_solved:           bool
    n_paths:             int


@dataclass
class FirstPassageResult:
    targets: list[TargetEstimate]
    invalidation: InvalidationEstimate
    sigma_stock: float
    mu: float
    # None means "no race here", and now covers two cases: the simulation was
    # refused (dte < 1 — deliberately NOT four zeroes, since a refusal is not a
    # 100%-summing result; spec 2.1.1), or the caller passed compute_race=False
    # and never wanted one. Only /contracts/first-passage asks for a race, so
    # nothing downstream has to tell them apart today; a caller that did would
    # need a separate flag rather than more meaning loaded onto this one.
    race: Optional["BarrierRaceResult"] = None


def _allocated_weights(shares: list[float]) -> list[float]:
    """The four shares as hundredths that sum to EXACTLY 1.00.

    ONE SOURCE OF TRUTH, and the reason there is no longer a Python imitation
    of JavaScript's toFixed here. There used to be: the edge was weighted with
    `floor(p*100 + 0.5)/100` while the card printed the same p through
    `toFixed(2)`, and the two disagree on 44 of the 2001 shares reachable at
    n_paths=2000 — every k/2000 whose third decimal is a 5, because multiplying
    by 100 first perturbs the double that decides the tie. On the reference
    contract itself the card printed "+ 0.04 x -$1.56" while the backend had
    weighted the term with 0.05, so the four printed terms summed to -$1.93
    beside a printed total of -$1.95. Two implementations of one rounding rule,
    in two languages, is a bug generator; the fix is to have one.

    These values are what the card prints, what the edge is weighted with, AND
    what the table's whole-percent labels are derived from — so the chain, the
    labels and the total cannot disagree, and every row still sums to 100%.

    Largest-remainder allocation: floor everything to a hundredth, then give the
    leftover hundredths to whichever shares lost the most to the floor. Ties
    break by index so the same shares always allocate the same way.
    """
    scaled = [s * 100.0 for s in shares]
    floors = [math.floor(x) for x in scaled]
    remaining = 100 - sum(floors)
    order = sorted(range(len(scaled)), key=lambda i: (-(scaled[i] - floors[i]), i))
    out = list(floors)
    for i in order:
        if remaining <= 0:
            break
        out[i] += 1
        remaining -= 1
    return [v / 100.0 for v in out]


def _first_day(mask: np.ndarray, n_days: int) -> np.ndarray:
    """Index of each row's first True, or `n_days` where the row never hits.

    THE TRAP THIS EXISTS FOR: np.argmax on a boolean row returns 0 both for
    "first True at index 0" (a hit on day 1) and for "no True anywhere". Used
    bare in a first-hit race, every never-hitting path would masquerade as the
    fastest possible hit and win outright. So every argmax here is paired with
    its own .any(axis=1), and non-hitting rows are pushed to n_days — an index
    no real hit can occupy, so a never-hit path always LOSES a first-hit race
    against any path that did hit.
    """
    ever = mask.any(axis=1)
    day = np.argmax(mask, axis=1)
    return np.where(ever, day, n_days)


def _attribute(
    d_tgt: np.ndarray, d_stop: np.ndarray, d_prem: np.ndarray, n_days: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Assign every path to exactly one of four outcomes, given each barrier's
    first-hit day (with `n_days` meaning "never").

    Returns (target_first, stock_stop_first, premium_stop_first, neither, best).
    The four masks are mutually exclusive and jointly exhaustive, so their means
    sum to exactly 1.0 by construction.

    TIE RULE: the simulation resolves to daily closes, so two barriers can be
    crossed on the same simulated day. Ties resolve PESSIMISTICALLY — a stop
    ahead of the target, and the premium stop ahead of the stock stop (in
    option-value terms it is the tighter of the two whenever both are hit the
    same day). This never flatters the trade. Deliberate and documented, not an
    accident of evaluation order.
    """
    best = np.minimum(np.minimum(d_tgt, d_stop), d_prem)
    neither = best == n_days
    prem_first = (d_prem == best) & ~neither
    stop_first = (d_stop == best) & ~prem_first & ~neither
    tgt_first = (d_tgt == best) & ~prem_first & ~stop_first & ~neither
    return tgt_first, stop_first, prem_first, neither, best


def _vectorized_bs_price(
    S: np.ndarray, K: float, T: float, r: float, sigma: float, is_call: bool,
) -> np.ndarray:
    """Numpy-vectorized Black-Scholes price — mathematically identical to
    app.models.black_scholes.bs_price, operating on a whole array of spot
    prices at once. bs_price itself cannot be vectorized: its d1/d2 helpers
    use Python's math module (math.log, math.sqrt), which raise on ndarray
    input. Kept private to this module's Monte Carlo hot path — the scalar
    bs_price is still used everywhere else here (Stage 1's bisection, the
    sigma_iv fallback derivation) where call counts are low and duplicating
    the formula isn't worth it. Unit-tested against bs_price for agreement
    (test_first_passage.py) so the two can never silently diverge.
    """
    if T <= 0 or sigma <= 0:
        return np.zeros_like(S, dtype=float)
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _solve_target_stock_price(
    stock_price: float,
    strike: float,
    dte_at_target: float,
    r: float,
    sigma_iv: float,
    is_call: bool,
    target_option_price: float,
    max_iter: int = 100,
    tol: float = 1e-4,
) -> Optional[float]:
    """Bisection: find S such that bs_price(S, ...) == target_option_price.

    Bracket is [stock_price * 0.01, stock_price * 5] — scaled to the stock's
    own price rather than a bare absolute floor (which would be nonsensically
    tight for a $500 stock and numerically dicey for a $2 one). bs_price is
    monotonic in S for a fixed-sign option (increasing for calls, decreasing
    for puts), so a target outside the bracket's reachable range genuinely
    isn't reachable at this dte_at_target/sigma_iv — not a solver failure —
    and this returns None rather than a garbage extrapolated price.
    """
    lo, hi = stock_price * 0.01, stock_price * 5.0
    f_lo = bs_price(lo, strike, dte_at_target, r, sigma_iv, is_call)
    f_hi = bs_price(hi, strike, dte_at_target, r, sigma_iv, is_call)

    if is_call:
        if not (f_lo <= target_option_price <= f_hi):
            return None
    else:
        if not (f_hi <= target_option_price <= f_lo):
            return None

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = bs_price(mid, strike, dte_at_target, r, sigma_iv, is_call)
        if abs(f_mid - target_option_price) < tol:
            return mid
        higher_than_target = f_mid < target_option_price
        if is_call:
            lo, hi = (mid, hi) if higher_than_target else (lo, mid)
        else:
            lo, hi = (lo, mid) if higher_than_target else (mid, hi)
    return (lo + hi) / 2


def estimate_first_passage(
    *,
    stock_price: float,
    strike: float,
    dte: int,
    premium: float,
    delta: float,
    is_call: bool,
    trend_score: float,
    invalidation_price: float,
    candles: list[dict],
    t1_pct: float,
    t2_pct: float,
    t3_pct: float,
    premium_stop_pct: float = 0.60,
    compute_race: bool = True,
    horizon_preset: Optional[str] = None,
    hold_min: Optional[float] = None,
    hold_max: Optional[float] = None,
    reprice_cfg: Optional[dict] = None,
    r: float = 0.05,
    sigma_fallback: float = 0.25,
    max_drift_pct: float = 0.40,
    n_paths: int = 2000,
    sigma_floor: float = 0.10,
    sigma_ceiling: float = 1.50,
    seed: int = 0,
) -> FirstPassageResult:
    """Estimate, for each of t1_pct/t2_pct/t3_pct, the probability and
    expected days to hit that profit level before expiry, plus the same for
    the invalidation price — via Monte Carlo GBM simulation of the stock,
    repricing the option along every simulated day.

    `delta` is accepted for API symmetry with the rest of this codebase's
    trade-plan functions but is not used directly: its effect on time-to-
    target is implicit in the option repricing itself (see module
    docstring), not a separate day-count adjustment.

    `premium_stop_pct` is the barrier race's THIRD barrier: the option-value
    level at which the premium stop fires, premium * (1 - premium_stop_pct). It
    is defaulted so that every pre-existing caller keeps compiling and simply
    ignores the `race` field on the result.

    `compute_race=False` skips the race outright. Ignoring the field does not
    make it free: the exit-plan endpoint calls this once PER TARGET ROW with
    t1=t2=t3, so leaving it on ran three full attributions plus a Black-Scholes
    reprice over a 2000-row array for every row, and then discarded all of it.

    `horizon_preset` / `hold_min` / `hold_max` feed resolve_reprice_days()'s
    fallback when the simulation itself produced no median days to a barrier.

    `seed` makes this deterministic for a given set of inputs — callers
    (the API endpoint) are expected to derive it from the request's own
    fields so identical button presses return identical answers, while
    genuinely different inputs still get an independent draw. Pass an
    explicit fixed seed in tests.
    """
    del delta  # see docstring — folded in via option repricing, not used directly here

    # Quantized before it is used as a barrier, for the same reason
    # premium_stop_price is: the card echoes this level "for auditability", and
    # echoing a rounded number for a barrier the paths were tested against at
    # full precision is exactly the mismatch that echo exists to rule out.
    invalidation_price = round(float(invalidation_price), 2)

    expiry_years = dte / 365.0
    premium = max(float(premium), 0.01)

    # bs_iv called directly rather than through _derive_fallback_sigma, which
    # discards the one bit we need: WHETHER it converged. When it does not
    # (a degenerate or extreme-moneyness quote), sigma silently becomes the
    # 0.25 default and the simulation then runs on a volatility that has
    # nothing to do with this contract — on a quote far below intrinsic it
    # prices day 1 above the target and reports 100% target-first with a
    # confident dollar edge. Every other consumer of that fallback shows a
    # probability; the race is the first to turn it into money, so it says so.
    solved_iv = bs_iv(premium, stock_price, strike, expiry_years, r, is_call)
    iv_solved = solved_iv is not None
    sigma_iv = solved_iv if solved_iv is not None else sigma_fallback

    atr = _atr(candles, 14) if candles else 0.0
    sigma_stock = sigma_floor
    if stock_price > 0:
        sigma_stock = max(sigma_floor, min(sigma_ceiling, (atr / stock_price) * math.sqrt(252)))

    direction_sign = 1.0 if is_call else -1.0
    mu = direction_sign * (trend_score - 50) / 50 * max_drift_pct

    # Stage 1's display-only back-solve reprices at the same resolved horizon
    # as everything else. sim_median is None here by necessity — Stage 1 runs
    # before the simulation exists — so this always takes the preset fallback.
    #
    # resolve_reprice_days returns days ELAPSED to the barrier; bs_price wants
    # the life REMAINING at that moment. Converting is mandatory, not cosmetic:
    # without it a 365-DTE LEAP's target stock price is solved as though 7 days
    # of life were left, because "Swing: 7" is a table about how long you hold,
    # not about how much contract is left.
    dte_at_target = remaining_years_at_barrier(
        float(dte),
        resolve_reprice_days(horizon_preset, hold_min, hold_max, float(dte), None, reprice_cfg),
    )
    pcts = [t1_pct, t2_pct, t3_pct]
    target_option_prices = [premium * (1 + p) for p in pcts]
    target_stock_prices = [
        _solve_target_stock_price(stock_price, strike, dte_at_target, r, sigma_iv, is_call, top)
        for top in target_option_prices
    ]

    # Zero/near-zero DTE guard: this app's Intraday horizon routinely has
    # contracts at or near 0 DTE. A zero-length simulation would either crash
    # (median() on an empty array) or return meaningless stats — skip it
    # outright rather than attempt it.
    if dte < 1:
        targets = [
            TargetEstimate(pct=p, stock_price=sp, option_price=top, probability=0.0, expected_days=None)
            for p, sp, top in zip(pcts, target_stock_prices, target_option_prices)
        ]
        return FirstPassageResult(
            targets=targets,
            invalidation=InvalidationEstimate(probability=0.0, expected_days=None),
            sigma_stock=sigma_stock,
            mu=mu,
        )

    rng = np.random.default_rng(seed)
    n_days = dte
    dt = 1 / 365

    z = rng.standard_normal((n_paths, n_days))
    log_returns = (mu - 0.5 * sigma_stock ** 2) * dt + sigma_stock * math.sqrt(dt) * z
    log_paths = np.cumsum(log_returns, axis=1)
    stock_paths = stock_price * np.exp(log_paths)   # shape (n_paths, n_days); column i = end of day i+1

    option_paths = np.empty_like(stock_paths)
    for day in range(n_days):
        t_remaining = max(expiry_years - (day + 1) * dt, 1e-6)
        option_paths[:, day] = _vectorized_bs_price(stock_paths[:, day], strike, t_remaining, r, sigma_iv, is_call)

    targets: list[TargetEstimate] = []
    for pct, target_stock, target_option in zip(pcts, target_stock_prices, target_option_prices):
        # "Profit" always means the option's own value rose past the target —
        # true for both calls and puts alike, since bs_price already accounts
        # for direction; no separate is_call branch needed here.
        hit_mask = option_paths >= target_option
        ever_hit = hit_mask.any(axis=1)
        probability = float(ever_hit.mean())
        expected_days: Optional[float] = None
        if ever_hit.any():
            first_hit_day = np.argmax(hit_mask, axis=1)   # index of first True per row
            expected_days = float(np.median(first_hit_day[ever_hit]) + 1)   # +1: column 0 == day 1
        targets.append(TargetEstimate(
            pct=pct, stock_price=target_stock, option_price=target_option,
            probability=probability, expected_days=expected_days,
        ))

    # Invalidation is a stock-price barrier already computed by trade_plan.py
    # (delta-linear back-solve) — checked directly against the raw stock
    # path, no option repricing needed.
    stop_hit_mask = stock_paths <= invalidation_price if is_call else stock_paths >= invalidation_price
    stop_ever_hit = stop_hit_mask.any(axis=1)
    stop_probability = float(stop_ever_hit.mean())
    stop_expected_days: Optional[float] = None
    if stop_ever_hit.any():
        stop_first_hit_day = np.argmax(stop_hit_mask, axis=1)
        stop_expected_days = float(np.median(stop_first_hit_day[stop_ever_hit]) + 1)

    # -- Barrier race ---------------------------------------------------------
    if not compute_race:
        return FirstPassageResult(
            targets=targets,
            invalidation=InvalidationEstimate(
                probability=stop_probability, expected_days=stop_expected_days,
            ),
            sigma_stock=sigma_stock,
            mu=mu,
        )

    # A REFEREE, not a fourth profit-target method: it proposes no level of its
    # own, it only compares per-path first-hit days of levels the existing cards
    # already produced. Runs over the SAME stock_paths / option_paths arrays
    # built above — no second simulation, no extra paths, no new model.
    # Quantized to cents BEFORE it is used as a barrier, not just before it is
    # printed. Rounding it only on the way out meant the level the card showed
    # as "the option-value barrier actually used" was up to half a cent away
    # from the one the paths were actually tested against.
    #
    # Derived from the CENT-ROUNDED premium, so that
    # `premium_used - premium_stop_price == risk_premium_stop` holds exactly.
    # Quantizing the barrier off the raw premium and the risk leg off the
    # rounded one broke that identity on 1 contract in 6: the card showed a
    # $0.24 barrier against a $0.35 premium and then printed a $0.10 risk leg,
    # and a user checking 0.35 - 0.24 got 0.11.
    premium_stop_price = round(round(premium, 2) * (1.0 - premium_stop_pct), 2)
    prem_hit_mask = option_paths <= premium_stop_price

    d_stop = _first_day(stop_hit_mask, n_days)
    d_prem = _first_day(prem_hit_mask, n_days)

    # -- The stop leg: computed ONCE, outside the per-target loop --------------
    # It is a property of the STOP, not of which target you happen to be aiming
    # at. Deriving its reprice horizon from a per-target conditional median
    # (the median day the stop won the race against THAT target) made the same
    # stop, at the same level, carry three different dollar risks on one card —
    # three "Risk" chains reading "$6.00 premium - $1.27 / $1.64 / $1.64 at the
    # stop" with nothing on screen explaining why. The unconditional median day
    # the stock stop is reached (stop_expected_days, computed above over every
    # path that ever touched it) is the honest input, and it makes the printed
    # horizon one number the user can check.
    reprice_days = resolve_reprice_days(
        horizon_preset, hold_min, hold_max, float(dte), stop_expected_days, reprice_cfg,
    )
    # ELAPSED -> REMAINING. See remaining_years_at_barrier: feeding elapsed days
    # into bs_price's T inverts theta and makes a fast stop-out look like a
    # total loss while a slow one looks cheap.
    stop_repriced_years = remaining_years_at_barrier(float(dte), reprice_days)
    if invalidation_price > 0:
        stop_repriced = float(bs_price(
            invalidation_price, strike, stop_repriced_years, r, sigma_iv, is_call,
        ))
        stop_repriced_value: Optional[float] = (
            round(stop_repriced, 2) if math.isfinite(stop_repriced) else None
        )
    else:
        # A non-positive stop price is not a $0.00 contract, it is an absent
        # barrier: bs_price returns 0.0 for S <= 0, which would print as
        # "worth nothing at the stop" and silently make risk == the whole
        # premium. None renders "could not reprice at the stop" instead.
        stop_repriced_value = None

    risk_stock_stop: Optional[float] = None
    if stop_repriced_value is not None:
        # Money is quantized to cents. See the note on the printed chains below.
        risk_stock_stop = round(round(premium, 2) - stop_repriced_value, 2)

    race_outcomes: list[RaceOutcome] = []
    for pct, target_option in zip(pcts, target_option_prices):
        d_tgt = _first_day(option_paths >= target_option, n_days)
        tgt_first, stop_first, prem_first, none_hit, best = _attribute(
            d_tgt, d_stop, d_prem, n_days,
        )

        def _median_days(m: np.ndarray, _best: np.ndarray = best) -> Optional[float]:
            # +1: column 0 is the end of day 1.
            return float(np.median(_best[m]) + 1) if bool(m.any()) else None

        p_target = float(tgt_first.mean())
        p_stock = float(stop_first.mean())
        p_prem = float(prem_first.mean())
        p_none = float(none_hit.mean())

        # Allocated once, up here: they weight the edge below AND are what the
        # card prints, so nothing downstream re-rounds them.
        weights = _allocated_weights([p_target, p_stock, p_prem, p_none])

        days_target = _median_days(tgt_first)
        days_stock = _median_days(stop_first)
        days_prem = _median_days(prem_first)

        # Terminal value of the paths that reached NO barrier. Uses the payoff,
        # not a repriced value: at expiry there is no time value left.
        terminal_mean: Optional[float] = None
        if bool(none_hit.any()):
            s_t = stock_paths[none_hit, -1]
            payoff = np.maximum(s_t - strike, 0.0) if is_call else np.maximum(strike - s_t, 0.0)
            terminal_mean = float(payoff.mean())

        # -- The arithmetic the card prints -----------------------------------
        # QUANTIZED TO THE PRECISION IT IS PRINTED AT, ON PURPOSE. The card
        # renders every term of these chains ("$5.20 premium - $1.09 at the stop
        # = $4.11"), so a chain that visibly fails to add up is a bug the user
        # sees. Two quantizations, for the same reason:
        #
        #   money -> cents. An option does not quote below a cent, and sub-cent
        #   precision is far inside the Monte Carlo's own noise at n_paths=2000.
        #
        #   the four probabilities -> 2dp, but ONLY where they weight the edge.
        #   The card prints them as "0.27 x $1.04", so computing the edge from
        #   anything finer makes the printed terms sum to a different number
        #   than the printed total (it was out by 1.6c per share before this).
        #   At n_paths=2000 one standard error on a share is ~0.011, so 0.01
        #   quantization is strictly smaller than the noise already present —
        #   it discards nothing real. The SHARES THEMSELVES are reported raw:
        #   rounding those would let a row's four bars sum to 101%, and "every
        #   row sums to 100% because each path is counted once" is the whole
        #   claim of this card.
        prem_c = round(premium, 2)
        tgt_c = round(target_option, 2)
        reward_dollar = round(tgt_c - prem_c, 2)   # round() only trims binary-float tails here

        # The complement of the barrier, not an independent rounding of the
        # same product — see premium_stop_price above.
        risk_premium_stop = round(prem_c - premium_stop_price, 2)

        # WHY PREMIUM DOES NOT CANCEL HERE — the trap that killed two earlier
        # designs. reward_dollar is premium * pct by construction, so ANY risk
        # leg proportional to premium cancels it. risk_stock_stop is
        # premium - BS(stop, ...), and BS(stop, ...) is not proportional to
        # premium — it depends on strike, spot at the stop, time and IV
        # independently. So rr_stock_stop genuinely varies by contract.
        rr_stock_stop: Optional[float] = None
        if risk_stock_stop is not None and risk_stock_stop > 0:
            rr_stock_stop = reward_dollar / risk_stock_stop

        # rr_premium_stop DOES cancel, and is therefore taken straight from the
        # DEFINITION rather than by dividing the two rounded dollar legs.
        # Dividing them does not reproduce it: at premium $1.03 the rounded legs
        # give 0.21/0.62 = 0.339 and at $1.07 they give 0.21/0.64 = 0.328, so
        # the "identical on every contract you could pick" the card prints
        # beside it would have been false by up to 14% on sub-$1 premiums — the
        # exact degeneracy this column exists to disclose. It is a labelled
        # constant, not a measurement; compute it as one.
        rr_premium_stop: Optional[float] = (
            (pct / premium_stop_pct) if premium_stop_pct > 0 else None
        )

        edge_per_contract: Optional[float] = None
        if risk_stock_stop is not None:
            # The last term is a SIGNED contribution, not a loss: a no-barrier
            # path can end above the premium paid. Writing it as
            # `- p_none * loss` would be wrong whenever terminal_mean > premium.
            neither_term = (round(terminal_mean, 2) - prem_c) if terminal_mean is not None else 0.0
            e_target, e_stock, e_prem, e_none = weights
            # x100: one US equity option contract covers 100 shares. Assumed,
            # not looked up — an adjusted contract (post-split or merger
            # deliverable) can cover something else, and this figure would be
            # wrong by that ratio.
            # Rounded again after the x100: `round(-0.58, 2) * 100` is
            # -57.99999999999999 in binary floating point, and that tail reaches
            # the DOM verbatim if anything interpolates it un-formatted.
            # NOTE: when risk_premium_stop rounds to $0.00 (a 5c contract with
            # a 5% stop), the third term contributes exactly nothing and the
            # edge is overstated by the un-quantized fraction of a cent. Left
            # as-is deliberately: quantizing the money is what makes the
            # printed chain checkable, and a sub-cent term on a 5c contract is
            # far inside the simulation's own noise. The RATIO for that state
            # is handled — it comes from the definition, not the division.
            edge = round(round(
                e_target * reward_dollar
                - e_stock * risk_stock_stop
                - e_prem * risk_premium_stop
                + e_none * neither_term,
                2,
            ) * 100.0, 2)
            if math.isfinite(edge):
                edge_per_contract = edge

        race_outcomes.append(RaceOutcome(
            target_pct=pct,
            target_option_price=target_option,
            p_target_first=p_target,
            p_stock_stop_first=p_stock,
            p_premium_stop_first=p_prem,
            p_neither=p_none,
            days_target=days_target,
            days_stock_stop=days_stock,
            days_premium_stop=days_prem,
            days_any_path_reached_stop=stop_expected_days,
            weight_target=weights[0],
            weight_stock_stop=weights[1],
            weight_premium_stop=weights[2],
            weight_neither=weights[3],
            terminal_mean=terminal_mean,
            reward_dollar=reward_dollar,
            reprice_days_stock_stop=reprice_days,
            stop_repriced_value=stop_repriced_value,
            risk_stock_stop=risk_stock_stop,
            risk_premium_stop=risk_premium_stop,
            rr_stock_stop=rr_stock_stop,
            rr_premium_stop=rr_premium_stop,
            edge_per_contract=edge_per_contract,
        ))

    race = BarrierRaceResult(
        outcomes=race_outcomes,
        premium_stop_price=premium_stop_price,
        premium_stop_pct=premium_stop_pct,
        stock_stop_price=invalidation_price,
        premium_used=round(premium, 2),
        iv_solved=iv_solved,
        n_paths=n_paths,
    )

    return FirstPassageResult(
        targets=targets,
        invalidation=InvalidationEstimate(probability=stop_probability, expected_days=stop_expected_days),
        sigma_stock=sigma_stock,
        mu=mu,
        race=race,
    )


# ── Stock first-passage ───────────────────────────────────────────────────────

@dataclass
class StockTargetEstimate:
    price: float
    probability: float
    expected_days: Optional[float]   # None if probability == 0


@dataclass
class StockFirstPassageResult:
    targets: list[StockTargetEstimate]
    invalidation: InvalidationEstimate
    sigma_stock: float
    mu: float
    horizon_days: int


def estimate_stock_first_passage(
    *,
    stock_price: float,
    direction: str,
    trend_score: float,
    stop_price: float,
    targets: list[float],
    candles: list[dict],
    horizon_days: int,
    max_drift_pct: float = 0.40,
    n_paths: int = 2000,
    sigma_floor: float = 0.10,
    sigma_ceiling: float = 1.50,
    seed: int = 0,
) -> StockFirstPassageResult:
    """Monte Carlo first-passage estimate for a STOCK position's exit ladder.

    Strict subset of estimate_first_passage(): it keeps the three
    instrument-agnostic stages — ATR -> annualized sigma, trend score -> drift,
    GBM path simulation — and the barrier test, and drops the three
    option-specific ones (sigma_iv back-out from premium, the Stage-1 bisection
    for "what stock price yields premium x (1+pct)", and the per-day
    Black-Scholes repricing loop). Dropping the repricing loop is why this is
    materially FASTER than its option sibling, not merely smaller: that loop is
    the expensive part.

    A stock profit target is the invalidation branch with the comparison flipped
    (``stock_paths >= target`` instead of ``<=``), which is exactly the shape the
    option version already uses for its stop barrier.

    horizon_days replaces ``dte``: stocks have no expiry, so the simulation needs
    an explicit holding window. Callers pass scoring_rules.yaml's
    ``confidence_backtest.<horizon>.n_days`` (Intraday 5 / Swing 10 / Position
    40), which is this app's existing definition of "how long a signal in this
    horizon takes to resolve" — reusing it keeps the Monte Carlo window
    consistent with the empirical confidence window rather than inventing a
    second answer.

    UNITS — the one place this deliberately differs from its option sibling.
    ``n_days`` counts TRADING days (signal_confidence walks forward N bars), and
    ``sigma_stock`` is annualized from a daily ATR with ``sqrt(252)``, so the
    time step here is ``1/252``. The option version steps at ``1/365`` because
    its window is ``dte``, which is CALENDAR days to expiry. Both are internally
    consistent — annualized vol times the right year fraction — and copying
    ``1/365`` here would have understated the simulated variance over the window
    by 252/365 (about 20% in vol terms). ``expected_days`` is therefore also in
    trading days; the endpoint and the card say so.

    NOTE ON MODEL VALIDITY: a constant drift derived from a trend score is a poor
    generative model for the mean_reversion_* strategies, whose whole thesis is
    that the recent drift is transient. That caveat is surfaced to the user by
    the caller (see the endpoint's ``model_caveat``), not silently absorbed here.
    """
    is_bullish = direction == "Bullish"
    sign = 1.0 if is_bullish else -1.0

    atr = _atr(candles, 14) if candles else 0.0
    sigma_stock = sigma_floor
    if stock_price > 0 and math.isfinite(stock_price) and math.isfinite(atr):
        sigma_stock = max(sigma_floor, min(sigma_ceiling, (atr / stock_price) * math.sqrt(252)))

    # trend_score is DIRECTION-ALIGNED by the time it reaches here: the stock
    # scorer scores in the requested direction, so 80 means "strongly favours
    # this trade" for a Bearish scan just as much as for a Bullish one. Hence
    # sign * (score - 50): a favourable score drifts WITH the trade, an
    # unfavourable one drifts against it. Same construction as the option
    # sibling's `direction_sign * (trend_score - 50)`.
    mu = sign * (trend_score - 50) / 50 * max_drift_pct

    clean_targets = [
        float(t) for t in targets
        if t is not None and math.isfinite(float(t)) and float(t) > 0
    ]

    # Degenerate inputs: a non-positive price or an empty window can't be
    # simulated. Return zero-probability rather than crashing on median() of an
    # empty array — the same guard the option version applies at dte < 1.
    if stock_price <= 0 or not math.isfinite(stock_price) or horizon_days < 1:
        return StockFirstPassageResult(
            targets=[StockTargetEstimate(price=t, probability=0.0, expected_days=None)
                     for t in clean_targets],
            invalidation=InvalidationEstimate(probability=0.0, expected_days=None),
            sigma_stock=sigma_stock, mu=mu, horizon_days=max(horizon_days, 0),
        )

    rng = np.random.default_rng(seed)
    dt = 1 / 252   # horizon_days is a TRADING-day count — see the docstring
    z = rng.standard_normal((n_paths, horizon_days))
    log_returns = (mu - 0.5 * sigma_stock ** 2) * dt + sigma_stock * math.sqrt(dt) * z
    stock_paths = stock_price * np.exp(np.cumsum(log_returns, axis=1))

    def _barrier(mask: np.ndarray) -> tuple[float, Optional[float]]:
        ever = mask.any(axis=1)
        probability = float(ever.mean())
        if not ever.any():
            return probability, None
        first = np.argmax(mask, axis=1)
        return probability, float(np.median(first[ever]) + 1)   # +1: column 0 == day 1

    target_estimates: list[StockTargetEstimate] = []
    for t in clean_targets:
        prob, days = _barrier(stock_paths >= t if is_bullish else stock_paths <= t)
        target_estimates.append(StockTargetEstimate(price=t, probability=prob, expected_days=days))

    if math.isfinite(stop_price) and stop_price > 0:
        stop_prob, stop_days = _barrier(
            stock_paths <= stop_price if is_bullish else stock_paths >= stop_price
        )
    else:
        stop_prob, stop_days = 0.0, None

    return StockFirstPassageResult(
        targets=target_estimates,
        invalidation=InvalidationEstimate(probability=stop_prob, expected_days=stop_days),
        sigma_stock=sigma_stock, mu=mu, horizon_days=horizon_days,
    )
