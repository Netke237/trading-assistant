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
    refuses with a 500 naming the key. Neither falls back to 1.0 —
    "no sizing" and "sizing is broken" are the same number (full size) and
    must not be the same outcome.

    ONE EXCEPTION, and it is not a refusal: a `min_mult` outside [0, 1] is
    CLAMPED and logged, not refused (see below). Clamped to 1.0 that IS full
    size, so `min_mult: 30` — percent where a fraction belongs — sizes every
    order at full. It is recorded at ERROR rather than refused because
    clamp-vs-refuse is section 9.9, which is Kenneth's to decide.

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

# Where `full_conviction_pct: 0` lands, per D-A1 — and the ONLY default in this
# module. There is deliberately no default for min_mult: it used to fall back to
# 0.5 while the shipped file says 0.3, so `min_mul: 0.3` (one dropped character)
# sized every position 67% larger than the file read. A missing key now refuses.
DEFAULT_FULL_CONVICTION_PCT = 40.0

# The keys a present block must carry. Not a closed schema — an UNRECOGNISED key
# is named in the error as a hint but never refuses on its own, because closing
# the subtree is section 9.8 and Kenneth has not decided it. A misspelled key is
# caught by the REQUIRED one it displaced going missing, which needs no decision.
REQUIRED_KEYS = ("enabled", "min_mult", "full_conviction_pct")

# full_conviction_pct is a point on the 0-100 conviction scale, while its
# sibling min_mult is a FRACTION — so `full_conviction_pct: 0.40` is the natural
# mistake, and it is the dangerous one: any value at or below the current
# conviction saturates the ramp at 1.0, i.e. full size. Bounded to whole
# percentage points of that scale.
MIN_FULL_CONVICTION_PCT = 1.0
MAX_FULL_CONVICTION_PCT = 100.0


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


def _unknown_key_hint(sizing: Mapping[str, Any]) -> str:
    """Name the keys that are present and not recognised, as a HINT only.

    A misspelling shows up twice: the required key it displaced is missing, and
    the misspelling itself is here. Refusing on an unrecognised key alone is
    section 9.8 (is a declared family closed?) and is undecided, so this text
    only helps the reader fix the file — it never decides the outcome.
    """
    unknown = sorted(k for k in sizing if k not in REQUIRED_KEYS)
    if not unknown:
        return ""
    return f" Unrecognised key(s) present: {', '.join(repr(k) for k in unknown)}."


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
    if not sizing:
        return None  # the loader's own {} for a file that carries no such block

    # `enabled` FIRST, and its absence is a refusal: a populated block that has
    # lost its `enabled: true` line, or misspelled it, used to read as "sizing
    # off" and fire at FULL SIZE — the exact collapse this module exists to
    # remove. `enabled: false` short-circuits before the rest is checked, so
    # junk inside a deliberately disabled block stays inert.
    if "enabled" not in sizing:
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing has no `enabled` key, so it "
            f"cannot be read as on or off.{_unknown_key_hint(sizing)}"
        )
    enabled = sizing["enabled"]
    if not isinstance(enabled, bool):
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.enabled is not a boolean "
            f"({enabled!r}) — a quoted \"false\" is TRUE to Python, and an "
            f"unquoted typo is a string, not a switch"
        )
    if not enabled:
        return None

    missing = [k for k in REQUIRED_KEYS if k not in sizing]
    if missing:
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing is enabled but missing "
            f"{', '.join(missing)}.{_unknown_key_hint(sizing)} A partial block "
            f"used to fall back to a built-in default, and for min_mult that "
            f"default (0.5) is not the shipped floor (0.3)"
        )

    full = _number(sizing["full_conviction_pct"], "full_conviction_pct")
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
    elif not MIN_FULL_CONVICTION_PCT <= full <= MAX_FULL_CONVICTION_PCT:
        raise SizingConfigError(
            f"scoring_rules.yaml: regime_sizing.full_conviction_pct is {full}, "
            f"outside [{MIN_FULL_CONVICTION_PCT:g}, {MAX_FULL_CONVICTION_PCT:g}] "
            f"— it is a point on the 0-100 conviction scale, not a fraction like "
            f"min_mult. Any value at or below the current conviction sizes every "
            f"order at FULL"
        )

    min_mult = _number(sizing["min_mult"], "min_mult")
    # Clamped rather than refused, which is the one place this function does NOT
    # fail closed. The earlier rationale here -- "clamping can only size a
    # position DOWN relative to the file" -- was FALSE and round 1 said so: a
    # min_mult above 1 clamps to 1.0, which is FULL SIZE, so `min_mult: 30`
    # (percent where a fraction belongs) enlarges every order rather than
    # shrinking it. It stays a clamp only because clamp-vs-refuse is section 9.9
    # and Kenneth has not ruled; the ERROR line is what stops a clamped run
    # being read as a correct one. RECOMMENDED to him: refuse above 1.
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

    # NOT routed through _number: that message names a key of
    # scoring_rules.yaml, and `conviction_pct` is not one. It arrives from
    # regime_monitor's cache (fire path) or the scan's regime_signal, so a bad
    # value here is a DATA fault and must not be reported, alerted or recorded
    # as a broken config file.
    if isinstance(conviction_pct, bool) or not isinstance(conviction_pct, (int, float)):
        raise ValueError(
            f"conviction_pct must be a number, got {conviction_pct!r}"
        )
    conv = float(conviction_pct)
    if not math.isfinite(conv):
        raise ValueError(f"conviction_pct is not finite ({conviction_pct!r})")

    frac = max(0.0, min(conv / full, 1.0))

    return lo + (1.0 - lo) * frac
