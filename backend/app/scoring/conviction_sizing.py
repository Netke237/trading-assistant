"""Conviction-based position sizing — the single source of the multiplier.

This module exists because the formula used to live in two places that had
drifted apart:

    auto_trader.py   max(min_mult, min(1.0, conv / full))      # clamp
    stock_scan.py    min_mult + (1 - min_mult) * frac          # ramp

Those agree only at the endpoints. Under the config shipped at the time
(min_mult 0.5, full_conviction_pct 40) the clamp form binds for every
conviction from 0 to 20, so the whole bottom half of the conviction scale
produced one identical position size, and the two paths sized the same setup
up to 1.5x apart at conviction 20 — the scan card showing one number while
the auto-trader executed another.

The ramp is the form kept, because that is what a floor is for: it rescales
conviction onto [min_mult, 1] so every distinct conviction maps to a distinct
size while still guaranteeing the floor. Risk appetite is expressed through
min_mult, not through the shape of the curve.

Both callers now import this function. Do not re-inline it.

FAILURE POSTURE (§9.1 of the YAML config integrity plan, decided by Kenneth
2026-09-17: FAIL CLOSED). This block multiplies live broker orders on both
paths, so a value it cannot honour must stop the trade rather than default
to one. That amends the earlier "restrict the scan and nothing else" posture,
which was decided on the belief that nothing outside the scan touches money.
Concretely:

  * block absent, or `enabled` falsy  -> multiplier 1.0. Sizing is OFF by
    configuration. This is a decision, not a failure, and it is unchanged.
  * block present and usable          -> the ramp.
  * block present and NOT usable      -> `SizingConfigError`. The auto-trader
    refuses to fire (and alerts on the unattended path); POST /stock-scan
    refuses with a 500 naming the key. Neither ever falls back to 1.0 —
    "no sizing" and "sizing is broken" are the same number (full size) and
    must not be the same outcome.

  * `full_conviction_pct: 0`          -> falls back to the documented default
    of 40 (decision D-A1, Kenneth 2026-09-17, option (b)). Zero is the one
    degenerate value with a settled meaning: it used to divide by zero on the
    fire path and floor the multiplier on the card path, which is the same
    input producing two different sizes. It is recorded at ERROR — falling
    back is not the same as the file being right.

A NEGATIVE full_conviction_pct is NOT treated that way: it has no documented
meaning, and guessing one would size a live order off a number nobody chose.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

# The defaults a missing key falls back to. DEFAULT_FULL_CONVICTION_PCT is also
# where `full_conviction_pct: 0` lands, per D-A1.
DEFAULT_MIN_MULT = 0.5
DEFAULT_FULL_CONVICTION_PCT = 40.0


class SizingConfigError(RuntimeError):
    """`regime_sizing` is present but cannot be honoured.

    Deliberately a RuntimeError subclass: `AutoTradeService.fire` already
    signals every refusal that way and `POST /auto-trade/fire` already maps
    RuntimeError to a 400, so raising this cannot leak out of an existing
    handler as a 500. Callers that need to tell a sizing-config refusal from
    any other refusal (to alert on it) catch this type first.
    """


def _number(value: Any, key: str) -> float:
    """Return `value` as a finite float, or raise SizingConfigError naming `key`.

    Rejects bools (`min_mult: true` is 1.0 to float() — full size from a value
    that is not a multiplier) and rejects nan/inf, which survive every range
    comparison below and would otherwise reach the broker as a nan quantity.
    """
    if isinstance(value, bool):
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.{key} is a boolean ({value!r}) — "
            f"expected a number"
        )
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.{key} is not a number ({value!r})"
        ) from None
    if not math.isfinite(out):
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.{key} is not finite ({value!r})"
        )
    return out


def resolve_sizing(sizing: Mapping[str, Any] | None) -> tuple[float, float] | None:
    """Return `(min_mult, full_conviction_pct)`, or None when sizing is off.

    None means "configured off" — the caller uses a multiplier of 1.0. Raises
    `SizingConfigError` when the block is present but unusable; see this
    module's docstring for why that is not None.

    Callers that only need to know whether the block is usable (the scan
    endpoint validating before it does any work) call this and discard the
    result.
    """
    if sizing is None:
        return None
    if not isinstance(sizing, Mapping):
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing must be a mapping, got "
            f"{type(sizing).__name__}"
        )
    if not sizing.get("enabled", False):
        return None

    full = (
        _number(sizing["full_conviction_pct"], "full_conviction_pct")
        if "full_conviction_pct" in sizing
        else DEFAULT_FULL_CONVICTION_PCT
    )
    if full == 0:
        # D-A1 (b). Not silent: a zero here is still a file that needs fixing.
        logger.error(
            "regime_sizing.full_conviction_pct is 0 — falling back to the default "
            "%s. Fix scoring_rules.yaml; every position is being sized off a "
            "default, not off your config.",
            DEFAULT_FULL_CONVICTION_PCT,
        )
        full = DEFAULT_FULL_CONVICTION_PCT
    elif full < 0:
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.full_conviction_pct is negative "
            f"({full}) — a conviction scale cannot run backwards"
        )

    min_mult = (
        _number(sizing["min_mult"], "min_mult")
        if "min_mult" in sizing
        else DEFAULT_MIN_MULT
    )
    # Clamped rather than refused, which is the one place this function does NOT
    # fail closed: a min_mult outside [0, 1] still has an unambiguous safe
    # reading (a floor on a multiplier cannot exceed 1, and cannot be negative),
    # and clamping it can only size a position DOWN relative to the file.
    # Whether to refuse instead is open (§9.9) and is Kenneth's to decide; until
    # then the clamp records itself so a clamped run is not read as a correct one.
    if not 0.0 <= min_mult <= 1.0:
        logger.error(
            "regime_sizing.min_mult is %s, outside [0, 1] — clamped to %s. Fix "
            "scoring_rules.yaml.",
            min_mult, max(0.0, min(1.0, min_mult)),
        )
        min_mult = max(0.0, min(1.0, min_mult))

    return min_mult, full


def conviction_mult(conviction_pct: float, sizing: Mapping[str, Any] | None) -> float:
    """Return the position-size multiplier for `conviction_pct`, in [min_mult, 1].

    `sizing` is the `regime_sizing` block of scoring_rules.yaml. When the block
    is disabled or absent the multiplier is 1.0 (size unchanged); when it is
    present but unusable this raises `SizingConfigError` rather than returning
    1.0, because 1.0 is full size.

    Conviction is clamped into [0, full_conviction_pct] before scaling, so a
    headwind (negative conviction) floors at min_mult rather than going below
    it, and conviction above full_conviction_pct caps at 1.0.
    """
    resolved = resolve_sizing(sizing)
    if resolved is None:
        return 1.0
    lo, full = resolved

    conv = _number(conviction_pct, "conviction_pct")
    frac = max(0.0, min(conv / full, 1.0))

    return lo + (1.0 - lo) * frac
