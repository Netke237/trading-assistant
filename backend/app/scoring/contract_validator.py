from __future__ import annotations

import copy
import logging
import math
import yaml
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

from app.services.config_health import config_health

logger = logging.getLogger(__name__)

Status = Literal["PASS", "CAUTION", "REJECT"]

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "contract_rules.yaml"


@dataclass
class ContractScoreBreakdown:
    liquidity_score: int        # 0–100
    spread_score: int           # 0–100
    delta_score: int            # 0–100
    dte_score: int              # 0–100
    iv_rank_score: int          # 0–100
    oi_score: int               # 0–100


@dataclass
class ContractScoreCard:
    contract_id: str            # canonical ID: SYMBOL|STRIKE|EXPIRY|C/P
    symbol: str
    strike: float
    expiry: str
    is_call: bool
    score: int                  # 0–100 aggregate
    status: Status
    reject_reasons: list[str] = field(default_factory=list)  # hard-reject labels
    soft_flags: list[str] = field(default_factory=list)       # soft-rank labels
    breakdown: ContractScoreBreakdown = field(
        default_factory=lambda: ContractScoreBreakdown(0, 0, 0, 0, 0, 0)
    )
    detail: dict = field(default_factory=dict)
    explanation: dict | None = None
    # NO-LIVE-QUOTE (plan 3b): set when the graded row's quote was not live
    # (contract["quoteLive"] is False), with the row's quoteState
    # ('one_sided' | 'session_closed' | 'stale'). A row with no quoteLive key
    # (fixtures, hand-built dicts) reads as live and leaves both at default.
    no_live_quote: bool = False
    quote_state: str | None = None


@lru_cache(maxsize=1)
def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="contract_rules.yaml",
    loader="contract_validator._load_config",
    fn=_load_config,
    project=lambda doc: doc,
)


def dte_holding_multiplier() -> float:
    """DTE-to-holding-period ratio from contract_rules.yaml."""
    return float(_load_config().get("dte_holding_multiplier", 2.0))


def hard_reject_delta_band() -> tuple[float, float]:
    """(min_delta, max_delta) from contract_rules.yaml's hard_reject block --
    the same values _hard_reject_reasons() uses for real contract selection."""
    hr = _load_config()["hard_reject"]
    return float(hr["min_delta"]), float(hr["max_delta"])


def contract_caution_threshold() -> float | int:
    """contract_score_thresholds.caution from contract_rules.yaml -- the score
    below which validate_contract() returns REJECT with no reject reason. Not
    an override key, so the YAML value is the one every scan applied. Returned
    as written (not int()-truncated): a 45.5 would otherwise print as 45 next
    to a rejected score of 45."""
    return _load_config()["contract_score_thresholds"]["caution"]


# NO-LIVE-QUOTE: the fallback when quote_liveness.max_age_minutes is missing or
# unusable. 30 is the shipped value (Kenneth, Q-A); see contract_rules.yaml.
DEFAULT_QUOTE_MAX_AGE_MINUTES = 30
_warned_quote_age: set[str] = set()


def max_quote_age_seconds() -> float:
    """quote_liveness.max_age_minutes from contract_rules.yaml, in SECONDS --
    the oldest the fresher side of a chain row's quote may be and still count
    as live (app/data/quote_liveness.classify_quote). Read through the same
    cached loader as every other contract rule.

    A missing block or key, a non-numeric value (a bool, a string, NaN/inf) or a
    value <= 0 runs on DEFAULT_QUOTE_MAX_AGE_MINUTES and logs ONE warning per
    distinct bad value (this is read once per chain fetch, so an unthrottled
    warning would repeat for every name of every scan)."""
    block = _load_config().get("quote_liveness")
    val = block.get("max_age_minutes") if isinstance(block, dict) else None
    if is_finite_rule_value(val) and val > 0:
        return float(val) * 60.0
    key = repr(val)
    if key not in _warned_quote_age:
        _warned_quote_age.add(key)
        logger.warning(
            "contract_rules.yaml quote_liveness.max_age_minutes is %s -- "
            "using %d minutes", "missing" if val is None else f"unusable ({val!r})",
            DEFAULT_QUOTE_MAX_AGE_MINUTES,
        )
    return float(DEFAULT_QUOTE_MAX_AGE_MINUTES) * 60.0


def _hard_reject_reasons(contract: dict, cfg: dict) -> list[str]:
    """Return list of hard-reject reason strings. Empty = no hard reject."""
    hr = cfg["hard_reject"]
    reasons = []

    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0
    iv_rank = contract.get("iv_rank")
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    delta = abs(contract.get("delta") or 0)

    expiry_str = contract.get("expiry", "")
    try:
        expiry_date = date.fromisoformat(expiry_str)
        dte = (expiry_date - date.today()).days
    except (ValueError, TypeError):
        dte = 0

    # min_volume is an optional hard floor, 0 = off (the default; FR-25 treats
    # volume as soft, scored under the Preferred liquidity floors). For an
    # explicit floor above 0, volume == 0 is exempt when OI is adequate: a 0 is
    # Tradier's session-to-date count and cannot be told apart from "no trades
    # yet this session", so OI is the liquidity proxy there. Off-hours rows are
    # rejected or labelled by the quote-liveness rule (no_live_quote), not here.
    if (
        hr["min_volume"] > 0
        and volume < hr["min_volume"]
        and not (volume == 0 and oi >= hr["min_open_interest"])
    ):
        reasons.append("volume_too_low")
    if oi < hr["min_open_interest"]:
        reasons.append("open_interest_too_low")
    if spread_pct > hr["max_bid_ask_spread_pct"]:
        reasons.append("spread_too_wide")
    if delta < hr["min_delta"]:
        reasons.append("delta_too_low_far_otm")
    if delta > hr["max_delta"]:
        reasons.append("delta_too_high_deep_itm")
    if dte < hr["min_dte"]:
        reasons.append("dte_too_short")
    if dte > hr["max_dte"]:
        reasons.append("dte_too_long")
    # `iv_rank` holds EITHER an IV rank OR an absolute IV, and
    # `iv_basis` (set in app/data/augment.py) says which -- so pick the ceiling
    # that judges the quantity we actually have
    # (PHASE-A-NULL-IVRANK-2026-09-06). Judging a 75% absolute IV against a
    # rank ceiling is what used to hard-reject names whose vol was in
    # fact low FOR THEM. Basis "none" means no vol figure at all, and
    # `iv_rank is None` already skips the gate.
    _iv_key = "max_iv_rank" if contract.get("iv_basis") == "rank" else "max_iv_abs"
    # Fall back to the rank key rather than skipping the gate outright,
    # so a hand-built cfg carrying only the old key still hard-rejects.
    max_iv = hr.get(_iv_key, hr.get("max_iv_rank"))
    if max_iv is not None and iv_rank is not None and iv_rank > max_iv:
        # ROUND 4 finding 10. The CEILING is picked by basis two lines up, but
        # the reason was a fixed string, and scan.py aggregates these verbatim
        # into the rejected-candidate list the user reads ("iv_rank_too_high(7)").
        # On the default path that reported "absolute IV above max_iv_abs" under
        # the rank's name -- the same mislabel this phase exists to remove,
        # in the text explaining why a candidate was thrown away.
        reasons.append(
            "iv_rank_too_high" if contract.get("iv_basis") == "rank" else "iv_too_high"
        )

    return reasons


def _int_pref_override(val: float) -> int:
    """int(val), except a value strictly between 0 and 1 floors to 1 rather
    than 0. Used for preferred_volume_min/preferred_oi_min overrides: plain
    truncation would turn a fractional "make this stricter" value into 0,
    which _score_liquidity reads as "no preference" -- the opposite of intent
    (ROUND 2 AUDIT FINDING, options-scan-liquidity-profiles, 2026-09-15)."""
    if 0 < val < 1:
        return 1
    return int(val)


def _score_liquidity(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
    """Returns (liquidity_score, oi_score, flags).

    ROUND 1 AUDIT FINDING (options-scan-liquidity-profiles, 2026-09-15):
    `preferred_volume_min`/`preferred_oi_min` became override-able in the same
    commit that added this guard, and the new Execution Parameters field for
    each allows 0 as its minimum -- a reachable UI value with no way to
    disable the soft check otherwise. Before that commit both were fixed at
    their contract_rules.yaml defaults (200/1000) and could never be 0, so an
    unconditional division was safe by construction; it stopped being safe
    the moment either became a live input. `<= 0` reads as "no preference on
    this axis" -- the natural meaning of dragging the floor down to nothing --
    and scores it as a full pass with no flag, rather than raising
    ZeroDivisionError (which propagated all the way to a per-symbol scan
    rejection reading the literal exception text) or silently keeping the
    fixed value at a 0 boundary would otherwise imply."""
    sr = cfg["soft_rank"]
    flags = []
    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0
    pref_volume_min = sr["preferred_volume_min"]
    pref_oi_min = sr["preferred_oi_min"]

    vol_score = 100 if pref_volume_min <= 0 else min(100, int(volume / pref_volume_min * 60))
    oi_score = 100 if pref_oi_min <= 0 else min(100, int(oi / pref_oi_min * 60))
    score = (vol_score + oi_score) // 2

    # ONE soft flag for the liquidity axis (CONTRACT-LIQUIDITY-DTE fix 2):
    # volume and open interest together count as at most one soft miss toward
    # max_soft_fail_count. It replaces low_volume / low_open_interest, which
    # spent two slots on one axis. The score above is unchanged.
    if (pref_volume_min > 0 and volume < pref_volume_min) or (
        pref_oi_min > 0 and oi < pref_oi_min
    ):
        flags.append("thin_liquidity")
    return score, oi_score, flags


def _score_spread(contract: dict, cfg: dict) -> tuple[int, float, list[str]]:
    sr = cfg["soft_rank"]
    bid = contract.get("bid") or 0
    ask = contract.get("ask") or 0
    mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
    spread_pct = (ask - bid) / mid if mid > 0 else 1.0
    flags = []

    # Same "<= 0 means no preference" rule _score_liquidity applies, for the
    # same reason: preferred_spread_pct_max became override-able alongside
    # preferred_volume_min/preferred_oi_min above, with the identical UI
    # `min: 0`. This one never raised (the ternary below happens to route a
    # zero-or-negative max_pct into its `else 0` branch, since spread_pct is
    # never negative), but "always score 0, always flag" is the opposite of
    # what dragging the ceiling down to nothing should mean, and was every
    # bit as unreachable-until-this-commit as the division above.
    max_pct = sr["preferred_spread_pct_max"]
    if max_pct <= 0:
        return 100, spread_pct, []
    score = max(0, int((1 - spread_pct / max_pct) * 100)) if spread_pct < max_pct else 0
    score = min(score, 100)

    if spread_pct > max_pct:
        flags.append("spread_elevated")
    return score, spread_pct, flags


def _score_delta(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    sr = cfg["soft_rank"]
    delta = abs(contract.get("delta") or 0)
    flags = []
    d_min = sr["preferred_delta_min"]
    d_max = sr["preferred_delta_max"]

    if d_min <= delta <= d_max:
        # Linear score peaking at 0.50
        centre = (d_min + d_max) / 2
        half_range = (d_max - d_min) / 2
        # half_range is 0 only when min==max (a collapsed override); delta sits
        # exactly on centre in that case, so it's a perfect score, not a divide by zero.
        score = 100 if half_range == 0 else int(100 * (1 - abs(delta - centre) / half_range))
    else:
        score = 20
        flags.append("delta_outside_preferred")
    return score, flags


def _score_dte(contract: dict, cfg: dict) -> tuple[int, int, list[str]]:
    # sr["preferred_dte_min"] intentionally equals cfg["hard_reject"]["min_dte"] in the
    # shipped default (contract_rules.yaml) and in every override dte_window.py's
    # widen_contract_overrides_for_dte() produces — that function always sets both to the
    # same widened value on purpose (see its docstring). That makes the `dte < d_min` half
    # of the distance-decay branch below unreachable today for any contract that has
    # already cleared the hard-reject min_dte check. Left in place (not deleted): the
    # `overrides` dict `validate_contract()` accepts (ScanRequest.overrides is an
    # unconstrained free-form dict) already lets a caller set min_dte/preferred_dte_min
    # independently, so a caller diverging them is a real reachable path via the public
    # API today, not just a hypothetical future one — no shipped frontend code path does
    # this yet, but this comment shouldn't claim otherwise.
    sr = cfg["soft_rank"]
    expiry_str = contract.get("expiry", "")
    flags = []
    try:
        dte = (date.fromisoformat(expiry_str) - date.today()).days
    except (ValueError, TypeError):
        return 0, 0, ["dte_parse_error"]

    d_min = sr["preferred_dte_min"]
    d_max = sr["preferred_dte_max"]
    half_range = (d_max - d_min) / 2

    if d_min <= dte <= d_max:
        centre = (d_min + d_max) / 2
        # half_range is 0 when a hold-derived override collapses min==max (e.g. a
        # Custom range typed as the same day twice) — dte sits exactly on centre
        # in that case, so it's a perfect score, not a divide by zero.
        score = 100 if half_range == 0 else int(100 * (1 - abs(dte - centre) / half_range))
    else:
        # A flat score here previously scored a 1-day miss identically to a
        # 100-day miss (and higher than sitting exactly on the boundary, which
        # scores 0 above) — decay linearly from 25 at the boundary to 0 over a
        # span equal to half_range, so misses are graded by how far off they are.
        distance = d_min - dte if dte < d_min else dte - d_max
        decay_span = half_range if half_range > 0 else 1
        score = max(0, int(25 * (1 - distance / decay_span)))
        flags.append("dte_outside_preferred")
    return score, dte, flags


def _preferred_iv_max(contract: dict, cfg: dict) -> float:
    """The soft ceiling matching the quantity `iv_rank` actually holds.

    `iv_basis` is set by app/data/augment.py and is "rank" only when IBKR or
    tastytrade supplied an IV rank; every other chain carries an
    absolute IV, which the `preferred_iv_abs_max` numbers have in fact been
    judging all along (PHASE-A-NULL-IVRANK-2026-09-06).
    """
    sr = cfg["soft_rank"]
    key = (
        "preferred_iv_rank_max"
        if contract.get("iv_basis") == "rank"
        else "preferred_iv_abs_max"
    )
    # Fall back to the rank key so a caller passing a hand-built cfg
    # (the unit tests do) keeps working without the absolute key present.
    return float(sr[key] if key in sr else sr["preferred_iv_rank_max"])


def _score_iv_rank(contract: dict, cfg: dict) -> tuple[int, list[str]]:
    iv_rank = contract.get("iv_rank")
    flags = []

    if iv_rank is None:
        return 50, ["no_iv_rank_data"]  # neutral

    # Same basis split as the hard-reject ceiling above: score the absolute
    # level against the absolute soft ceiling, a rank against the
    # rank one (PHASE-A-NULL-IVRANK-2026-09-06).
    max_pref = _preferred_iv_max(contract, cfg)
    if iv_rank <= max_pref:
        # Denominator guard: max_pref == 0 divides by zero when iv_rank <= 0
        # too. Upper-clamped to 100 since a very negative iv_rank would
        # otherwise push the score above the function's 0-100 contract.
        denom = max(max_pref, 1e-9)
        score = max(0, min(100, int(100 * (1 - iv_rank / denom))))
    else:
        # Denominator guard: max_pref == 100 divides by zero for any rank > 100
        # (reachable now that the tastytrade adapter no longer clamps).
        denom = max(100 - max_pref, 1e-9)
        score = max(0, min(100, int(20 * (1 - (iv_rank - max_pref) / denom))))
        flags.append("iv_rank_elevated")
    return score, flags


# Every key validate_contract() accepts in `overrides`, with the section of the
# config it replaces and the cast applied to it. Keys not listed here are
# ignored (ScanRequest.overrides is one free-form dict shared with the stock
# scorer, the R/R model and the gates). ONE table, read by validate_contract()
# and by effective_contract_overrides() below, so what a scan records as the
# rules it applied (ScanResult.contract_rules) cannot drift from what it applied.
_CONTRACT_OVERRIDES: dict[str, tuple[str, Callable[[Any], float | int]]] = {
    "max_bid_ask_spread_pct": ("hard_reject", float),
    "max_delta":              ("hard_reject", float),
    "min_delta":              ("hard_reject", float),
    "min_volume":             ("hard_reject", int),
    "min_open_interest":      ("hard_reject", int),
    "min_dte":                ("hard_reject", int),
    "max_dte":                ("hard_reject", int),
    "max_iv_rank":            ("hard_reject", float),
    "max_iv_abs":             ("hard_reject", float),
    "preferred_dte_min":      ("soft_rank",   int),
    "preferred_dte_max":      ("soft_rank",   int),
    "min_stock_score":        ("hard_reject", int),
    # Below: the SOFT-RANK counterparts of the hard-reject liquidity/
    # spread keys above. Added so a caller can move both together, the
    # same reason `widen_contract_overrides_for_dte` (dte_window.py)
    # sets `preferred_dte_min`/`max` to the SAME widened value as
    # `min_dte`/`max_dte` rather than leaving them at their fixed
    # config default: a contract already forgiven by the hard-reject
    # check must not then take a soft-fail penalty for the same
    # reason, or the caller's "let more through" override is silently
    # undone by a fixed preferred-band it has no way to reach.
    # `_score_liquidity`/`_score_spread` read these from `sr` on every
    # call, so raising or lowering them changes both the soft flag AND
    # the 0-100 sub-score, not merely the reject/accept boundary.
    # ROUND 1 AUDIT FINDING: int(), not float(), matching their
    # hard-reject siblings (min_volume/min_open_interest above) and
    # LiquidityDetail's own `int` typing (schemas/__init__.py). A
    # float() cast here let a fractional value (the new UI field's
    # `step` is not enforced by its own input handler) reach the
    # response `detail` block, where pydantic's `int` field then
    # raised on construction -- caught and swallowed by both callers
    # (_safe() in routers/scan.py, _safe_detail() in
    # routers/contracts.py), silently dropping the whole
    # liquidityDetail block from the card with no error anywhere.
    #
    # ROUND 2 AUDIT FINDING: plain int() truncates any override in
    # (0, 1) -- e.g. a mistyped `0.5` -- down to 0, which then hits
    # _score_liquidity's own "<= 0 means no preference" branch and
    # silently DISABLES the check the caller was trying to make
    # strict, the opposite of the value they set. `_int_pref_override`
    # (above) floors that open interval to 1 (a strict near-zero
    # threshold, still "> 0") instead of 0; <= 0 and >= 1 are
    # unchanged from plain int().
    "preferred_volume_min":     ("soft_rank", _int_pref_override),
    "preferred_oi_min":         ("soft_rank", _int_pref_override),
    "preferred_spread_pct_max": ("soft_rank", float),
}

CONTRACT_OVERRIDE_KEYS: frozenset[str] = frozenset(_CONTRACT_OVERRIDES)


def is_finite_rule_value(val: Any) -> bool:
    """True for a contract-rule value that can be recorded, sent back and
    applied: a real int/float (not a bool) that is finite as a float.

    The ONE check behind _parse_contract_rules (GET /api/contracts), the
    watched-contracts grading validator (POST /api/watched-contracts) and the
    scan's recording of ScanResult.contract_rules. If the three drifted, a
    scan could record rules that a star's POST then refuses, silently
    degrading the star to YAML grading."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    try:
        return math.isfinite(val)
    except OverflowError:  # an int too large for a float
        return False


def effective_contract_overrides(overrides: dict | None) -> dict[str, float | int]:
    """The contract-rule overrides validate_contract() applies for `overrides`:
    only the keys it reads, each cast exactly as it casts them. Raises
    ValueError/TypeError on a value the cast refuses, as validate_contract would.

    A scan records this on its result (ScanResult.contract_rules) and Step 6
    sends it back to /api/contracts, so the contracts table grades every
    contract with the rules the trade cards were graded with."""
    return {
        key: _CONTRACT_OVERRIDES[key][1](val)
        for key, val in (overrides or {}).items()
        if key in _CONTRACT_OVERRIDES
    }


def effective_dte_limits(overrides: dict | None) -> tuple[int, int, int, int]:
    """(min_dte, preferred_dte_min, preferred_dte_max, max_dte) as
    validate_contract() applies them for `overrides`: each the override when
    present, else contract_rules.yaml's, cast as validate_contract casts it.

    The chain fetch picks its one expiry from these when no hold window is set
    (market._pick_expiration_without_window). It used to take the first 21+ day
    expiry whatever the rules said, so a min_dte override of 45 fetched an
    expiry every contract of which was rejected as dte_too_short and the symbol
    dropped out of the scan. With a hold window the scan uses
    dte_window.widened_min_dte and the window instead, which replace these.
    """
    cfg = _load_config()
    eff = effective_contract_overrides(overrides)
    return (
        int(eff.get("min_dte", cfg["hard_reject"]["min_dte"])),
        int(eff.get("preferred_dte_min", cfg["soft_rank"]["preferred_dte_min"])),
        int(eff.get("preferred_dte_max", cfg["soft_rank"]["preferred_dte_max"])),
        int(eff.get("max_dte", cfg["hard_reject"]["max_dte"])),
    )


def _contract_id(contract: dict) -> str:
    side = "C" if contract.get("is_call", True) else "P"
    return f"{contract.get('symbol', '')}|{contract.get('strike', '')}|{contract.get('expiry', '')}|{side}"


def validate_contract(
    contract: dict,
    stock_score: int,
    overrides: dict | None = None,
    *,
    quote_mode: Literal["reject", "label"] = "reject",
) -> ContractScoreCard:
    """
    Validate and score an option contract.

    Args:
        contract:    Option contract dict (see Section 3 for shape)
        stock_score: Aggregate stock score from StockScoreCard (0–100).
                     The configured options floor defaults to 45, independently
                     of the stock `pass` bar (55) in scoring_rules.yaml.
        overrides:   Optional dict of hard-reject and soft-rank overrides; the
                     keys read are _CONTRACT_OVERRIDES' (others are ignored).
        quote_mode:  What a row whose quote is not live does (NO-LIVE-QUOTE,
                     plan 3b). The rule fires only when contract["quoteLive"]
                     is False; a missing key reads as live.
                     "reject" (the default, so a new caller is safe): the row
                     is REJECT with reject_reasons exactly ["no_live_quote"];
                     no other hard rule is evaluated for it. The soft scores
                     are still computed so the breakdown renders.
                     "label" (Step 6 / the Watchlist refresh): the row is
                     graded exactly as a live one, then capped at CAUTION and
                     flagged ("no_live_quote" soft flag, card.no_live_quote,
                     card.quote_state). A one_sided row still hard-rejects as
                     spread_too_wide there, from its own numbers.

    Returns:
        ContractScoreCard with score, status, hard-reject reasons, soft flags,
        and score breakdown.
    """
    cfg = copy.deepcopy(_load_config())
    for key, val in effective_contract_overrides(overrides).items():
        cfg[_CONTRACT_OVERRIDES[key][0]][key] = val
    contract_id = _contract_id(contract)

    if quote_mode not in ("reject", "label"):
        raise ValueError(f"quote_mode must be 'reject' or 'label', not {quote_mode!r}")
    # NO-LIVE-QUOTE: `is False`, not falsiness -- an absent key is live.
    no_live_quote = contract.get("quoteLive") is False
    quote_state = contract.get("quoteState") if no_live_quote else None
    quote_rejected = no_live_quote and quote_mode == "reject"

    if quote_rejected:
        # Short-circuit: the row's numbers are not a live market, so no other
        # hard rule is judged on them (and none accumulates beside this one).
        reject_reasons = ["no_live_quote"]
    else:
        reject_reasons = _hard_reject_reasons(contract, cfg)
        if stock_score < cfg["hard_reject"]["min_stock_score"]:
            reject_reasons.append("stock_score_below_threshold")

    liq_score, oi_score_val, liq_flags = _score_liquidity(contract, cfg)
    spread_score, spread_pct, spread_flags = _score_spread(contract, cfg)
    delta_score, delta_flags = _score_delta(contract, cfg)
    dte_score, dte, dte_flags = _score_dte(contract, cfg)
    iv_score, iv_flags = _score_iv_rank(contract, cfg)

    sr = cfg["soft_rank"]
    detail = {
        "dte": {
            "dte": dte,
            "preferred_min": sr["preferred_dte_min"],
            "preferred_max": sr["preferred_dte_max"],
        },
        "delta": {
            "delta": abs(contract.get("delta") or 0),
            "preferred_min": sr["preferred_delta_min"],
            "preferred_max": sr["preferred_delta_max"],
        },
        "iv_rank": {
            "iv_rank": contract.get("iv_rank"),
            # Which quantity `iv_rank` holds, so the UI can label the number
            # honestly instead of printing an absolute IV under "IV rank".
            # Callers that predate the split (fixtures, hand-built dicts) set
            # no basis; they were passing an absolute IV, so that is the
            # default -- except when there is no figure at all.
            "iv_basis": contract.get(
                "iv_basis",
                "none" if contract.get("iv_rank") is None else "absolute",
            ),
            "preferred_max": _preferred_iv_max(contract, cfg),
        },
        "liquidity": {
            "volume": contract.get("volume") or 0,
            "open_interest": contract.get("open_interest") or 0,
            "preferred_volume_min": sr["preferred_volume_min"],
            "preferred_oi_min": sr["preferred_oi_min"],
        },
        "spread": {
            "spread_pct": spread_pct,
            "preferred_max_pct": sr["preferred_spread_pct_max"],
        },
    }

    soft_flags = liq_flags + spread_flags + delta_flags + dte_flags + iv_flags
    soft_fail_count = len(soft_flags)

    if not quote_rejected and soft_fail_count >= cfg["hard_reject"]["max_soft_fail_count"]:
        reject_reasons.append("too_many_soft_failures")

    if no_live_quote and quote_mode == "label":
        # Added AFTER soft_fail_count: the label grades the row exactly as a
        # live one, so it must not count toward too_many_soft_failures.
        soft_flags = soft_flags + ["no_live_quote"]

    hr = cfg["hard_reject"]
    volume = contract.get("volume") or 0
    oi = contract.get("open_interest") or 0
    delta_val = abs(contract.get("delta") or 0)
    iv_rank_val = contract.get("iv_rank")
    iv_basis_val = contract.get(
        "iv_basis",
        "none" if iv_rank_val is None else "absolute",
    )
    _iv_key = "max_iv_rank" if iv_basis_val == "rank" else "max_iv_abs"
    max_iv_val = hr.get(_iv_key, hr.get("max_iv_rank"))

    blockers = []
    for r in reject_reasons:
        if r == "no_live_quote":
            blockers.append({
                "code": "no_live_quote",
                "label": "No live quote",
                "metric": "quote_state",
                "observed": quote_state,
                "threshold": "live",
                "operator": "!=",
            })
        elif r == "volume_too_low":
            blockers.append({
                "code": "volume_too_low",
                "label": "Volume too low",
                "metric": "volume",
                "observed": volume,
                "threshold": hr["min_volume"],
                "operator": "<",
            })
        elif r == "open_interest_too_low":
            blockers.append({
                "code": "open_interest_too_low",
                "label": "Open interest too low",
                "metric": "open_interest",
                "observed": oi,
                "threshold": hr["min_open_interest"],
                "operator": "<",
            })
        elif r == "spread_too_wide":
            blockers.append({
                "code": "spread_too_wide",
                "label": "Spread too wide",
                "metric": "spread_pct",
                "observed": spread_pct,
                "threshold": hr["max_bid_ask_spread_pct"],
                "operator": ">",
            })
        elif r == "delta_too_low_far_otm":
            blockers.append({
                "code": "delta_too_low_far_otm",
                "label": "Delta too low (far OTM)",
                "metric": "delta",
                "observed": delta_val,
                "threshold": hr["min_delta"],
                "operator": "<",
            })
        elif r == "delta_too_high_deep_itm":
            blockers.append({
                "code": "delta_too_high_deep_itm",
                "label": "Delta too high (deep ITM)",
                "metric": "delta",
                "observed": delta_val,
                "threshold": hr["max_delta"],
                "operator": ">",
            })
        elif r == "dte_too_short":
            blockers.append({
                "code": "dte_too_short",
                "label": "DTE too short",
                "metric": "dte",
                "observed": dte,
                "threshold": hr["min_dte"],
                "operator": "<",
            })
        elif r == "dte_too_long":
            blockers.append({
                "code": "dte_too_long",
                "label": "DTE too long",
                "metric": "dte",
                "observed": dte,
                "threshold": hr["max_dte"],
                "operator": ">",
            })
        elif r == "iv_rank_too_high":
            blockers.append({
                "code": "iv_rank_too_high",
                "label": "IV rank too high",
                "metric": "iv_rank",
                "observed": iv_rank_val,
                "threshold": max_iv_val,
                "operator": ">",
            })
        elif r == "iv_too_high":
            blockers.append({
                "code": "iv_too_high",
                "label": "IV too high",
                "metric": "iv",
                "observed": iv_rank_val,
                "threshold": max_iv_val,
                "operator": ">",
            })
        elif r == "stock_score_below_threshold":
            blockers.append({
                "code": "stock_score_below_threshold",
                "label": "Stock score below threshold",
                "metric": "stock_score",
                "observed": stock_score,
                "threshold": hr["min_stock_score"],
                "operator": "<",
            })
        elif r == "too_many_soft_failures":
            blockers.append({
                "code": "too_many_soft_failures",
                "label": "Too many soft failures",
                "metric": "soft_fail_count",
                "observed": soft_fail_count,
                "threshold": hr["max_soft_fail_count"],
                "operator": ">=",
            })
        else:
            blockers.append({
                "code": r,
                "label": r.replace("_", " ").title(),
                "metric": r,
                "observed": None,
                "threshold": "",
                "operator": "",
            })

    weights = cfg["weights"]
    liq_w = float(weights["liquidity"])
    spread_w = float(weights["spread"])
    delta_w = float(weights["delta"])
    dte_w = float(weights["dte"])
    iv_w = float(weights["iv_rank"])

    components_dict = {
        "liquidity": {
            "name": "liquidity",
            "wire_name": "liquidity",
            "raw_score": liq_score,
            "weight": liq_w,
            "contribution": liq_score * liq_w,
            "lost_points": liq_w * 100 - (liq_score * liq_w),
            "observed": volume,
            "observed_unit": "contracts",
            "basis": None,
            "preferred_min": sr["preferred_volume_min"],
            "preferred_max": None,
            "flags": liq_flags,
            "volume": volume,
            "open_interest": oi,
            "preferred_volume_min": sr["preferred_volume_min"],
            "preferred_oi_min": sr["preferred_oi_min"],
        },
        "spread": {
            "name": "spread",
            "wire_name": "spread",
            "raw_score": spread_score,
            "weight": spread_w,
            "contribution": spread_score * spread_w,
            "lost_points": spread_w * 100 - (spread_score * spread_w),
            "observed": spread_pct,
            "observed_unit": "%",
            "basis": None,
            "preferred_min": None,
            "preferred_max": sr["preferred_spread_pct_max"],
            "flags": spread_flags,
        },
        "delta": {
            "name": "delta",
            "wire_name": "delta",
            "raw_score": delta_score,
            "weight": delta_w,
            "contribution": delta_score * delta_w,
            "lost_points": delta_w * 100 - (delta_score * delta_w),
            "observed": delta_val,
            "observed_unit": "",
            "basis": None,
            "preferred_min": sr["preferred_delta_min"],
            "preferred_max": sr["preferred_delta_max"],
            "flags": delta_flags,
        },
        "dte": {
            "name": "dte",
            "wire_name": "dteFit",
            "raw_score": dte_score,
            "weight": dte_w,
            "contribution": dte_score * dte_w,
            "lost_points": dte_w * 100 - (dte_score * dte_w),
            "observed": dte,
            "observed_unit": "days",
            "basis": None,
            "preferred_min": sr["preferred_dte_min"],
            "preferred_max": sr["preferred_dte_max"],
            "flags": dte_flags,
        },
        "iv_rank": {
            "name": "iv_rank",
            "wire_name": "ivAttractiveness",
            "raw_score": iv_score,
            "weight": iv_w,
            "contribution": iv_score * iv_w,
            "lost_points": iv_w * 100 - (iv_score * iv_w),
            "observed": iv_rank_val,
            "observed_unit": "%" if iv_basis_val == "absolute" else ("rank" if iv_basis_val == "rank" else ""),
            "basis": iv_basis_val,
            "preferred_min": None,
            "preferred_max": _preferred_iv_max(contract, cfg),
            "flags": iv_flags,
        },
    }

    largest_losses = sorted(
        list(components_dict.values()),
        key=lambda c: c["lost_points"],
        reverse=True,
    )

    thresholds = cfg["contract_score_thresholds"]
    pass_thresh = float(thresholds["pass"])
    caution_thresh = float(thresholds["caution"])

    if reject_reasons:
        final_score = 0
        final_status: Status = "REJECT"
        unrounded_score = None
        rounded_score = None
        outcome = "blocked"
    else:
        weighted = (
            liq_score * liq_w
            + spread_score * spread_w
            + delta_score * delta_w
            + dte_score * dte_w
            + iv_score * iv_w
        )
        final_score = round(weighted)
        unrounded_score = weighted
        rounded_score = final_score
        outcome = "aggregate"
        if final_score >= pass_thresh:
            final_status = "PASS"
        elif final_score >= caution_thresh:
            final_status = "CAUTION"
        else:
            final_status = "REJECT"
        # NO-LIVE-QUOTE label mode: a row priced off a quote that is not live
        # never reads PASS. The score is left as graded.
        if no_live_quote and final_status == "PASS":
            final_status = "CAUTION"

    explanation = {
        "version": 1,
        "contract_id": contract.get("id") or contract_id,
        "evaluated_at": date.today().isoformat(),
        "outcome": outcome,
        "score": final_score,
        "status": final_status,
        "unrounded_score": unrounded_score,
        "rounded_score": rounded_score,
        "pass_threshold": pass_thresh,
        "caution_threshold": caution_thresh,
        "weights": {
            "liquidity": liq_w,
            "spread": spread_w,
            "delta": delta_w,
            "dte": dte_w,
            "iv_rank": iv_w,
        },
        "components": components_dict,
        "largest_losses": largest_losses,
        "blockers": blockers,
        "reject_reasons": list(reject_reasons),
        "soft_flags": list(soft_flags),
        "soft_fail_count": soft_fail_count,
        "max_soft_fail_count": hr["max_soft_fail_count"],
        "hard_bounds": {
            key: hr[key] for key in (
                "min_volume", "min_open_interest", "max_bid_ask_spread_pct",
                "min_delta", "max_delta", "min_dte", "max_dte", "min_stock_score",
            )
        } | {"max_iv": max_iv_val},
        "raw_inputs": {key: contract.get(key) for key in ("volume", "open_interest", "delta")},
    }

    if reject_reasons:
        return ContractScoreCard(
            contract_id=contract_id,
            symbol=contract.get("symbol", ""),
            strike=float(contract.get("strike", 0)),
            expiry=contract.get("expiry", ""),
            is_call=contract.get("is_call", True),
            score=0,
            status="REJECT",
            reject_reasons=reject_reasons,
            soft_flags=soft_flags,
            breakdown=ContractScoreBreakdown(
                liquidity_score=liq_score,
                spread_score=spread_score,
                delta_score=delta_score,
                dte_score=dte_score,
                iv_rank_score=iv_score,
                oi_score=oi_score_val,
            ),
            detail=detail,
            explanation=explanation,
            no_live_quote=no_live_quote,
            quote_state=quote_state,
        )

    return ContractScoreCard(
        contract_id=contract_id,
        symbol=contract.get("symbol", ""),
        strike=float(contract.get("strike", 0)),
        expiry=contract.get("expiry", ""),
        is_call=contract.get("is_call", True),
        score=final_score,
        status=final_status,
        reject_reasons=[],
        soft_flags=soft_flags,
        breakdown=ContractScoreBreakdown(
            liquidity_score=liq_score,
            spread_score=spread_score,
            delta_score=delta_score,
            dte_score=dte_score,
            iv_rank_score=iv_score,
            oi_score=oi_score_val,
        ),
        detail=detail,
        explanation=explanation,
        no_live_quote=no_live_quote,
        quote_state=quote_state,
    )
