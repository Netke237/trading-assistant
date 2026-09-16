"""Shared cached access to YAML config files.

A single lru_cache per config file avoids duplicate in-memory copies when
multiple modules (scan router, fundamentals_gate, etc.) need the same file.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@lru_cache(maxsize=1)
def load_scoring_cfg() -> dict:
    """Return the parsed scoring_rules.yaml as a dict (cached after first load)."""
    import yaml
    return yaml.safe_load((_CONFIG_DIR / "scoring_rules.yaml").read_text())


@lru_cache(maxsize=1)
def load_reward_risk_cfg() -> dict:
    """Return risk_rules.yaml's reward_risk block (bullish/bearish target %,
    premium_stop_pct, target_t1/t2/t3_pct). Shared by the scan pipeline and the
    per-contract recompute endpoint — both must build a trade plan off the
    same numbers."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["reward_risk"]


@lru_cache(maxsize=1)
def load_exit_plan_cfg() -> dict:
    """Return risk_rules.yaml's exit_plan block (stop.atr_multiplier,
    target.rr_ratios, target.structural_snap.atr_multiplier)."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["exit_plan"]


@lru_cache(maxsize=1)
def load_reprice_horizon_cfg() -> dict:
    """Return risk_rules.yaml's reprice_horizon block (source, fallback_days per
    HOLDING preset, custom.fraction, clamp.min_days / clamp.max_fraction_of_dte).

    Consumed only by app.scoring.reprice_horizon.resolve_reprice_days(), which
    is the single place the rule lives."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["reprice_horizon"]


@lru_cache(maxsize=1)
def load_first_passage_cfg() -> dict:
    """Return risk_rules.yaml's first_passage block (Monte Carlo simulation
    tunables: max_drift_pct, n_paths, sigma_floor, sigma_ceiling)."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["first_passage"]


# ── Direction-conviction gate ────────────────────────────────────────────────
# The minimum trend score a candidate must reach to count as having real
# directional structure. Applied by BOTH scan paths (routers/scan.py for
# options, routers/stock_scan.py for stocks), which is why it resolves here
# rather than being spelled out twice.
#
# A FLOOR IN BOTH DIRECTIONS, NEVER A CEILING. Every trend method in
# scoring/stock_scorer.py — _trend_crossover, _trend_additive and
# _trend_relative_strength — is direction-aware: each scores how strongly price
# is moving IN THE DIRECTION BEING TRADED (bearish awards its points for close
# BELOW the MA, a falling slope, and relative strength negated). So a high trend
# score on a Bearish scan means a strong DOWNtrend, which is exactly the setup a
# put wants, and "no directional structure" — the only thing this gate exists to
# remove — is a LOW score on either side.
#
# Until 2026-09-16 the bearish side applied a `max_trend` CEILING, which
# inverted the gate: it deleted the strongest short setups and kept the names
# that were not falling. scoring/first_passage.py agreed with the scorer rather
# than with the gate all along — its drift term is
# `direction_sign * (trend_score - 50)`, so a high trend score on a put already
# produced downward drift. The ceiling is gone; do not reintroduce one here.
#
# These are the DEFAULTS. scoring_rules.yaml's
# horizons.<horizon>.direction_conviction overrides them per horizon, and an
# explicit `null` there disables the gate for that direction.
_DIRECTION_CONVICTION_KEYS = frozenset({"bullish_min_trend", "bearish_min_trend"})
_DIRECTION_CONVICTION_KEYS_TEXT = "bullish_min_trend / bearish_min_trend"

# NOTE ON THE NUMBERS: the bearish floors MIRROR the bullish ones rather than
# having been measured. The bullish side is the one with live history behind it;
# the bearish side was a ceiling for three months, so there is no observed
# bearish pass-rate to tune against — a mirror is the only defensible starting
# point, not a validated one. UNMEASURED in the same sense as this repo's
# iv_rank_* and pass_max_fraction thresholds. Revisit once a few real bearish
# scans have run and the survivor count can be looked at; one edit either way.
_DIRECTION_CONVICTION_DEFAULTS: dict[str, dict[str, float | None]] = {
    "swing":    {"bullish_min_trend": 30.0, "bearish_min_trend": 30.0},
    "position": {"bullish_min_trend": 40.0, "bearish_min_trend": 40.0},
    # "intraday" is deliberately ABSENT — exempt in both directions, because
    # intraday reversals are common regardless of the daily trend. An absent
    # horizon means no gate, so this is the exemption, not an oversight.
}


_KNOWN_HORIZONS = frozenset({"swing", "intraday", "position"})


def _walk_direction_conviction_paths(node, path: tuple[str, ...] = ()):
    """Yield the dotted path of every `direction_conviction` key anywhere in the
    config, at any depth, through mappings and lists alike.

    Keys are stringified: PyYAML parses `on:`, `yes:` and `true:` as BOOLEANS
    and `1:` as an int, so a bare `key.lower()` on a raw key would blow up with
    an AttributeError instead of the named error this module promises — and
    neither router catches AttributeError, so it would escape as a bare 500
    with no `detail` at all.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            key_text = str(key)
            if key_text == "direction_conviction":
                yield ".".join(path + (key_text,)), value
            else:
                yield from _walk_direction_conviction_paths(value, path + (key_text,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk_direction_conviction_paths(value, path + (f"[{index}]",))


def _validated_direction_conviction_blocks() -> dict[str, dict | None]:
    """Return {horizon_key: direction_conviction block or None} for the known
    horizons, having checked where every `direction_conviction` in the file
    actually sits.

    This exists because a config edit that is SILENTLY IGNORED is the worst
    outcome for this particular gate: the operator believes they moved the
    screen, the scan keeps running on the old number, and nothing says
    otherwise. That already happened once, for three months.

    THE RULE IS POSITIONAL, and deliberately narrow. Every
    `direction_conviction` key in the file must sit at exactly
    `horizons.<known horizon>.direction_conviction`. Anywhere else — one level
    too deep under a sibling such as `vol`, two levels deep under
    `trend.additive`, at the file's top level, inside a list, or under a
    horizon key that is misspelled (`positon:`) or mis-cased (`Position:`,
    which is exactly how `Horizon = Literal['Intraday','Swing','Position']`
    spells it everywhere else in the codebase) — is a block that will never be
    read, so it is an error rather than a silent no-op.

    WHAT THIS DELIBERATELY DOES NOT DO is police the `horizons` namespace. An
    earlier version rejected any key in `horizons` outside the known three,
    which meant a harmless additive edit — a new horizon, or the standard
    `_defaults: &anchor` holder that a YAML merge key needs — hard-500'd BOTH
    scan endpoints while every other consumer of this file carried on working.
    This feature owns `direction_conviction`; it does not own the file. An
    unrecognised horizon carrying no `direction_conviction` is none of its
    business.
    """
    cfg = load_scoring_cfg()
    horizons = cfg.get("horizons")
    if not isinstance(horizons, dict):
        raise ValueError(
            f"invalid scoring_rules.yaml: `horizons` must be a mapping of "
            f"{sorted(_KNOWN_HORIZONS)}, got {type(horizons).__name__}"
        )

    legal_paths = {f"horizons.{h}.direction_conviction" for h in _KNOWN_HORIZONS}
    for found_path, _block in _walk_direction_conviction_paths(cfg):
        if found_path not in legal_paths:
            raise ValueError(
                f"misplaced direction_conviction block in scoring_rules.yaml: "
                f"found at {found_path}, but it must sit at one of "
                f"{sorted(legal_paths)} — as written it is never read, so the "
                f"gate silently keeps running on its previous threshold"
            )

    blocks: dict[str, dict | None] = {}
    for key_text in sorted(_KNOWN_HORIZONS):
        if key_text not in horizons:
            continue
        horizon_cfg = horizons[key_text]
        # Only the KNOWN horizons are shape-checked. One of them not being a
        # mapping means its whole scoring block is gone, which cannot be
        # benign; an unrecognised sibling key is left alone (see above).
        if not isinstance(horizon_cfg, dict):
            raise ValueError(
                f"invalid scoring_rules.yaml: horizons.{key_text} must be a "
                f"mapping, got {type(horizon_cfg).__name__}"
            )

        block = horizon_cfg.get("direction_conviction")
        if block is not None and not isinstance(block, dict):
            raise ValueError(
                f"invalid direction_conviction block for horizon {key_text!r}: "
                f"expected a mapping of {_DIRECTION_CONVICTION_KEYS_TEXT}, got {block!r}"
            )
        if isinstance(block, dict):
            unknown = sorted(str(k) for k in set(block) - _DIRECTION_CONVICTION_KEYS)
            if unknown:
                raise ValueError(
                    f"unknown direction_conviction key(s) {unknown} for horizon "
                    f"{key_text!r}: expected {_DIRECTION_CONVICTION_KEYS_TEXT}"
                )
        blocks[key_text] = block

    return blocks


def load_direction_conviction_min_trend(direction: str, horizon: str) -> float | None:
    """Return the minimum trend score a `direction` scan requires at `horizon`,
    or None when no gate applies (Intraday today).

    Resolution order, per direction:
      1. scoring_rules.yaml horizons.<horizon>.direction_conviction.<dir>_min_trend
         when that key is PRESENT — including an explicit `null`, which means
         "no gate for this direction" and is honoured rather than falling
         through to the default.
      2. Otherwise _DIRECTION_CONVICTION_DEFAULTS for that horizon.
      3. Otherwise None — no gate.

    Raises ValueError on a malformed threshold (non-numeric, boolean, or
    outside the 0-100 range a trend score can actually take), and on a config
    whose SHAPE would make the block silently inert — see
    _validated_direction_conviction_blocks, which checks every horizon, not
    just the one being scanned. A typo in the config must fail the scan loudly,
    not quietly widen the screen.
    """
    dir_key = f"{direction.strip().lower()}_min_trend"
    if dir_key not in ("bullish_min_trend", "bearish_min_trend"):
        raise ValueError(
            f"unknown direction {direction!r}: expected 'Bullish' or 'Bearish'"
        )
    horizon_key = horizon.strip().lower()
    # An unrecognised horizon RAISES rather than returning None. Returning None
    # means "exempt", so an unknown horizon would silently disable the gate —
    # the exact silent-widening this whole change exists to remove, left alive
    # on the one axis the config validation cannot see. Unreachable from the
    # API today (both request models Literal-restrict `horizon`), so this costs
    # nothing; the day `Horizon` gains a member and the config entry is
    # forgotten, it fails loudly instead of screening nothing.
    if horizon_key not in _KNOWN_HORIZONS:
        raise ValueError(
            f"unknown horizon {horizon!r}: expected one of {sorted(_KNOWN_HORIZONS)}"
        )

    # EVERY horizon is validated on every call, not just the one being scanned.
    # Scoping validation to the scanned horizon meant a typo in the `swing`
    # block survived every Position and Intraday scan and only surfaced the
    # first time somebody ran a Swing scan.
    blocks = _validated_direction_conviction_blocks()
    block = blocks.get(horizon_key)

    if isinstance(block, dict) and dir_key in block:
        raw = block[dir_key]
    else:
        raw = _DIRECTION_CONVICTION_DEFAULTS.get(horizon_key, {}).get(dir_key)

    if raw is None:
        return None
    # `isinstance(raw, bool)` first: bool is a subclass of int, so a YAML
    # `true` would otherwise sail through float() as 1.0 and install a gate
    # that passes essentially everything.
    if isinstance(raw, bool):
        raise ValueError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is a boolean, expected a number in [0, 100] or null"
        )
    try:
        val = float(raw)
    except (ValueError, TypeError):
        raise ValueError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is not a number in [0, 100] or null"
        )
    if not math.isfinite(val) or not (0.0 <= val <= 100.0):
        raise ValueError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is outside the 0-100 range a trend score can take"
        )
    return val


# Maps the Step 3 "Reward/Risk" panel's override keys (frontend/lib/
# executionParamDefaults.ts) onto risk_rules.yaml's reward_risk block keys.
_RR_OVERRIDE_KEY_MAP = {
    "rr_bullish_target_pct":       "bullish_target_pct",
    "rr_bearish_target_pct":       "bearish_target_pct",
    "rr_bullish_invalidation_pct": "bullish_invalidation_pct",
    "rr_bearish_invalidation_pct": "bearish_invalidation_pct",
}

# Upper bound for each override key, mirroring the Step 3 UI's own `max` for
# these fields (frontend/app/(frame)/screener/step-3-direction/page.tsx). All
# four must additionally be > 0 (and finite) — see merge_reward_risk_overrides.
_RR_OVERRIDE_CAPS = {
    "rr_bullish_target_pct":       2.0,
    "rr_bearish_target_pct":       2.0,
    "rr_bullish_invalidation_pct": 1.0,
    "rr_bearish_invalidation_pct": 1.0,
}


def merge_reward_risk_overrides(overrides: dict | None) -> dict:
    """Return risk_rules.yaml's reward_risk block with any per-request rr_*
    overrides applied on top.

    Returns a fresh dict every call — load_reward_risk_cfg()'s cached dict is
    never mutated, so a later call with different (or no) overrides isn't
    affected by an earlier one.

    A `None` override value is silently skipped (not applied) rather than
    raising — e.g. a request that supplies some but not all rr_* keys, or a
    frontend field the user cleared back to its default (None), must not
    crash on float(None). A present-but-invalid value (non-finite, <= 0, or
    above this key's cap) raises ValueError with a clear message, so a typo
    or malformed override fails loudly instead of producing a nonsensical
    trade plan (e.g. a negative target, or a triple-digit target %) silently.
    """
    merged = dict(load_reward_risk_cfg())
    for override_key, cfg_key in _RR_OVERRIDE_KEY_MAP.items():
        if not overrides or override_key not in overrides:
            continue
        val = overrides[override_key]
        if val is None:
            continue
        cap = _RR_OVERRIDE_CAPS[override_key]
        try:
            val = float(val)
        except (ValueError, TypeError):
            raise ValueError(
                f"invalid {override_key}={val!r}: must be a finite number in (0, {cap}]"
            )
        if not math.isfinite(val) or val <= 0 or val > cap:
            raise ValueError(
                f"invalid {override_key}={val!r}: must be a finite number in (0, {cap}]"
            )
        merged[cfg_key] = val
    return merged
