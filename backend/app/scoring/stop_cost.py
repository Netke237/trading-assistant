"""Stop-vs-premium gate — Black-Scholes at today's date (Q3 / Q7).

Spec: docs/superpowers/plans/2026-09-02-gate-basis-spec.md.

The question: **what share of this option's premium is gone by the time the
underlying reaches the stop?** The old answer (frontend `stopPremiumRisk`)
was the straight line `|stop - spot| x |delta|`, capped at the premium. On a
wide stop that cap binds constantly — on the reference chain below it pinned
four of eight strikes at exactly 100%, so the gate could not tell a 220 call
from a 240 call and merely restated that a long option's maximum loss is its
premium.

The new basis reprices the contract AT the stop price with Black-Scholes,
at **today's** remaining life:

    loss = premium - BS(stop_price, K, dte/365, r, iv)

Two deliberate properties:

* **Curvature is included.** Delta falls as the stock falls, so a straight
  line charges a loss the contract cannot actually produce.
* **No theta.** Today's time-to-expiry, not the exit plan's half-life. The
  gate has to fire before any button has been pressed, and the round-5
  measurement put the half-life assumption at ~39 points of error against
  ~17 for linear-vs-curvature — it was the larger error of the two.
  Repricing at a horizon is the barrier race's job and drives sizing; it
  never drives this verdict (spec §5).

Where the IV comes from: the contract's own mid, inverted with the
**bracketed** solver `_compute_iv_bs` (brentq). NOT `bs_iv`, the Newton loop
in app/models/black_scholes.py — docs/superpowers/plans/
2026-09-03-bs-iv-convergence-findings.md measured that one returning None on
60-69% of the quotable OTM call wing, which is precisely the half of the
chain this gate exists to discriminate; brentq recovers every one of those
cases and has zero genuine solver failures across the whole sweep. A caller
that already holds a vendor IV may pass it instead.

Two states, PASS and CAUTION — never REJECT, never red, never blocking (D8).
The gate sorts candidates by how survivable their own stop is; it is not a
verdict on the trade. A third state, `None` ("not computed"), covers every
case where the arithmetic has no honest answer — see `compute_stop_cost`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Optional

from app.data.market import _compute_iv_bs
from app.models.black_scholes import bs_price
from app.services.config_loader import load_scoring_cfg

# The risk-free rate this gate prices at. 0.05 is `_compute_iv_bs`'s own
# default, so the IV that comes out of the mid and the price that goes back in
# at the stop are computed under one rate — an inverted-at-one-rate,
# repriced-at-another pair does not reproduce the premium at spot and would
# put a small unexplained bias in every fraction.
RISK_FREE_RATE = 0.05

# Every horizon token this API is known to carry, mapped onto the scoring
# horizon whose YAML block holds the threshold. It has to span BOTH live
# domains, because both reach the backend under the name `horizon_preset` and
# a mismatch would give the card and this gate two different thresholds for
# the same contract:
#
#   * the SEVEN-key preset domain (`HorizonKey` in frontend/lib/horizonPresets
#     .ts, and what FirstPassageRequest.horizon_preset carries today), whose
#     Quarterly / SemiAnnual / Annual rows all declare `scoringHorizon:
#     'Position'` and whose Custom row declares 'Swing';
#   * the THREE-key scoring domain, which is what the card itself resolves to
#     before looking a threshold up (`scoringHorizonFromLabel(scanHorizon)`).
#
# Keys are normalised (lowercased, non-letters stripped, anything from a "("
# onwards dropped), so the display strings those helpers produce — "Position
# (15-45d)", "Semi-annual" — land on the same row as the bare key.
_PRESET_TO_HORIZON = {
    "intraday":   "intraday",
    "swing":      "swing",
    "position":   "position",
    "quarterly":  "position",
    "semiannual": "position",
    "annual":     "position",
    "custom":     "swing",
}

# An unrecognised or absent preset resolves here rather than to the loosest
# line, so an unknown horizon fails toward caution. Same choice, and the same
# reason, as the frontend's `getStopPremiumThresholds` fallback.
DEFAULT_HORIZON_KEY = "swing"

# A premium below one cent has no printable card: every figure in this gate is
# rendered from a pair rounded to cents, so a $0.004 premium would print a
# percentage beside "$0.00 of $0.00 premium" — four mutually contradictory
# zeroes. Mirrors the same floor, tested on the RAW premium for the same
# reason, in frontend/lib/risk.ts.
MIN_PREMIUM = 0.01


@dataclass(frozen=True)
class StopCost:
    """What the stop costs, in the three forms the card prints.

    `premium`, `value_at_stop` and `loss_dollar` are per share and all three
    are quantized to cents, so the card's equation adds up EXACTLY as printed:
    "$5.20 premium - $1.49 at $185.87 = $3.71 of $5.20 premium". `fraction` is
    derived FROM that quantized pair and rounded to hundredths, and the status
    is decided on that same rounded number. One number, printed and judged:
    deciding the colour at full precision and the percentage at printed
    precision lets them straddle the threshold in opposite directions, which is
    how the old card came to print "70% OF PREMIUM" in PASS green (see the note
    in frontend/lib/risk.ts).

    `premium` and `stop_price` are ECHOED INPUTS, not results, and they are
    here because the frontend presenter takes this block and nothing else
    (spec section 3: `stopPremiumRisk(c: StopCostOut | null)`). Every figure
    the badge prints has to be reachable from one object, or the card is back
    to composing a number out of two vintages -- the premium it was priced at
    and whatever `contractDetails.mid` happens to hold at render time.
    """
    loss_dollar:       float
    value_at_stop:     float
    fraction:          float
    status:            Literal["PASS", "CAUTION"]
    pass_max_fraction: float
    premium:           float
    stop_price:        float
    basis:             Literal["bs_today"] = "bs_today"


def horizon_key(preset: Optional[str]) -> str:
    """Map a horizon token onto the scoring horizon whose threshold applies.

    Mirrors the frontend's own collapse (`HORIZON_PRESETS[].scoringHorizon`):
    seven presets, three scoring horizons, Quarterly / SemiAnnual / Annual all
    landing on Position. Collapsing them to Swing instead — which is what a
    bare "is it one of the three?" test does — would price a 200-day hold at
    the Swing line while the card beside it used the Position line, for the
    same contract.

    An ABSENT or genuinely unrecognised value resolves to Swing, not to
    Position: "no preset was sent" is not the same statement as "this is a
    year-long hold", and Swing is the app's own default preset.
    """
    if not preset:
        return DEFAULT_HORIZON_KEY
    token = re.sub(r"[^a-z]", "", preset.split("(")[0].lower())
    return _PRESET_TO_HORIZON.get(token, DEFAULT_HORIZON_KEY)


def pass_max_fraction_for(preset: Optional[str], cfg: Optional[dict] = None) -> float:
    """The horizon's `stop_premium.pass_max_fraction` from scoring_rules.yaml.

    One source of truth, the same one /api/config/stop-premium-thresholds
    serves the client from — this gate must not carry a second hardcoded copy
    to drift away from the YAML the operator actually edits.
    """
    cfg = cfg if cfg is not None else load_scoring_cfg()
    horizons = cfg["horizons"]
    return float(horizons[horizon_key(preset)]["stop_premium"]["pass_max_fraction"])


def compute_stop_cost(
    *,
    stop_price:     float,
    stock_price:    float,
    strike:         float,
    dte:            int,
    premium:        float,
    is_call:        bool,
    iv_pct:         Optional[float] = None,
    horizon_preset: Optional[str] = None,
    cfg:            Optional[dict] = None,
) -> Optional[StopCost]:
    """Price the contract at `stop_price` and grade the loss against premium.

    `iv_pct` is ABSOLUTE implied volatility in PERCENT (0-100), the same unit
    and the same field as `ContractDetails.iv` / `ContractQuoteResponse.iv`,
    NOT the decimal Black-Scholes takes. None means "solve it from the mid".

    Returns None — the card's third state, "not computed", which must never
    render as a silent PASS — when the arithmetic has no honest answer:

    * any non-finite input, or a non-positive price/strike/premium;
    * a premium under a cent (MIN_PREMIUM);
    * `dte < 1`: `bs_price` returns 0.0 for T <= 0, which would report every
      expiring contract as a 100% loss at any stop — including one that is
      deep in the money at that stop and worth its intrinsic value;
    * the IV could not be backed out of the mid. `_compute_iv_bs` refuses a
      mid at or under intrinsic (an arbitrage-violating quote), which is the
      case both solvers otherwise answer with a confidently wrong sigma.

    `fraction` is clamped to [0, 1]: a caller-supplied `iv_pct` need not
    reproduce the contract's own mid, so BS at the stop can legitimately come
    back above the premium (a negative loss) on an IV that disagrees with the
    quote. `value_at_stop` and `loss_dollar` are reported unclamped — they are
    the printed inputs, and hiding that disagreement would be hiding the one
    signal that the supplied IV and the quote do not describe the same
    contract.
    """
    values = (stop_price, stock_price, strike, premium)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        return None
    if stop_price <= 0 or stock_price <= 0 or strike <= 0:
        return None
    if premium < MIN_PREMIUM:
        return None
    if dte < 1:
        return None

    if iv_pct is None:
        iv_dec = _compute_iv_bs(
            mid=premium, S=stock_price, K=strike, dte=dte,
            is_call=is_call, r=RISK_FREE_RATE,
        )
    else:
        if not math.isfinite(iv_pct) or iv_pct <= 0:
            return None
        iv_dec = iv_pct / 100.0
    if iv_dec is None or iv_dec <= 0:
        return None

    raw_value = bs_price(stop_price, strike, dte / 365.0, RISK_FREE_RATE, iv_dec, is_call)
    value_at_stop = round(raw_value, 2)
    # THE PREMIUM IS QUANTIZED BEFORE THE SUBTRACTION, not after. The card
    # prints all three figures to the cent and Kenneth checks the line by
    # subtracting the two he can see, so the only version that survives a hand
    # check is the one those two numbers actually produce. Rounding
    # `premium - value_at_stop` from a RAW premium instead lets the printed
    # premium and the printed loss disagree by a cent whenever the mid sits on
    # a half-cent -- an ordinary quote, since a mid is (bid + ask) / 2.
    # Quantized first, `premium_c - value_at_stop` is exact to the cent by
    # construction and the round() below only clears binary dust.
    #
    # Guarded above by `premium < MIN_PREMIUM` on the RAW value, so this cannot
    # be zero: 0.0099 is refused before it could round up to 0.01.
    premium_c = round(premium, 2)
    loss_dollar = round(premium_c - value_at_stop, 2)
    fraction = round(min(max(loss_dollar / premium_c, 0.0), 1.0), 2)

    pass_max = pass_max_fraction_for(horizon_preset, cfg)
    # Epsilon so a fraction sitting exactly ON the line lands on CAUTION
    # rather than on whichever side binary representation puts it.
    status: Literal["PASS", "CAUTION"] = "CAUTION" if fraction + 1e-9 >= pass_max else "PASS"

    return StopCost(
        loss_dollar=loss_dollar,
        value_at_stop=value_at_stop,
        fraction=fraction,
        status=status,
        pass_max_fraction=pass_max,
        premium=premium_c,
        stop_price=stop_price,
    )
