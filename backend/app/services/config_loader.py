"""Shared cached access to YAML config files.

A single lru_cache per config file avoids duplicate in-memory copies when
multiple modules (scan router, fundamentals_gate, etc.) need the same file.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from app.services.config_health import config_health

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


@lru_cache(maxsize=1)
def load_scoring_cfg() -> dict:
    """Return the parsed scoring_rules.yaml as a dict (cached after first load)."""
    import yaml
    return yaml.safe_load((_CONFIG_DIR / "scoring_rules.yaml").read_text())


# DOCC-4: the health poll compares this cache's live value with the file on disk.
config_health.watch(
    file="scoring_rules.yaml",
    loader="config_loader.load_scoring_cfg",
    fn=load_scoring_cfg,
    project=lambda doc: doc,
)


@lru_cache(maxsize=1)
def load_reward_risk_cfg() -> dict:
    """Return risk_rules.yaml's reward_risk block (invalidation percentages,
    premium_stop_pct, target_t1/t2/t3_pct). Shared by the scan pipeline and the
    per-contract recompute endpoint — both must build a trade plan off the
    same numbers."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["reward_risk"]


config_health.watch(
    file="risk_rules.yaml",
    loader="config_loader.load_reward_risk_cfg",
    fn=load_reward_risk_cfg,
    project=lambda doc: doc["reward_risk"],
    path="reward_risk",
)


@lru_cache(maxsize=1)
def load_exit_plan_cfg() -> dict:
    """Return risk_rules.yaml's exit_plan block (stop.atr_multiplier,
    target.rr_ratios, target.structural_snap.atr_multiplier)."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["exit_plan"]


config_health.watch(
    file="risk_rules.yaml",
    loader="config_loader.load_exit_plan_cfg",
    fn=load_exit_plan_cfg,
    project=lambda doc: doc["exit_plan"],
    path="exit_plan",
)


@lru_cache(maxsize=1)
def load_reprice_horizon_cfg() -> dict:
    """Return risk_rules.yaml's reprice_horizon block (source, fallback_days per
    HOLDING preset, custom.fraction, clamp.min_days / clamp.max_fraction_of_dte).

    Consumed only by app.scoring.reprice_horizon.resolve_reprice_days(), which
    is the single place the rule lives."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["reprice_horizon"]


config_health.watch(
    file="risk_rules.yaml",
    loader="config_loader.load_reprice_horizon_cfg",
    fn=load_reprice_horizon_cfg,
    project=lambda doc: doc["reprice_horizon"],
    path="reprice_horizon",
)


@lru_cache(maxsize=1)
def load_first_passage_cfg() -> dict:
    """Return risk_rules.yaml's first_passage block (Monte Carlo simulation
    tunables: max_drift_pct, n_paths, sigma_floor, sigma_ceiling)."""
    import yaml
    full = yaml.safe_load((_CONFIG_DIR / "risk_rules.yaml").read_text())
    return full["first_passage"]


config_health.watch(
    file="risk_rules.yaml",
    loader="config_loader.load_first_passage_cfg",
    fn=load_first_passage_cfg,
    project=lambda doc: doc["first_passage"],
    path="first_passage",
)


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


class ConvictionConfigError(ValueError):
    """A direction_conviction config fault, carrying `.path`: the dotted place
    in scoring_rules.yaml it is about (DOCC-4 plan §2.5). A ValueError, so
    every existing `except ValueError` still catches it; the message text is
    unchanged. The config health check reads `.path` instead of parsing it out
    of the message."""

    def __init__(self, message: str, path: str):
        super().__init__(message)
        self.path = path


def _walk_direction_conviction_paths(node, path: tuple[str, ...] = (), ancestors: frozenset[int] = frozenset()):
    """Yield the path (a TUPLE of key segments) of every `direction_conviction`
    key anywhere in the config, at any depth, through mappings and lists alike.

    Keys are stringified: PyYAML parses `on:`, `yes:` and `true:` as BOOLEANS
    and `1:` as an int, so a bare `key.lower()` on a raw key would blow up with
    an AttributeError instead of the named error this module promises — and
    neither router catches AttributeError, so it would escape as a bare 500
    with no `detail` at all.

    THE PATH IS A TUPLE, NOT A DOTTED STRING. Joined on '.', a top-level key
    literally spelled `horizons.position` produced the legal string
    'horizons.position.direction_conviction', passed validation, and sat inert
    while the gate ran on the real block. A '.' inside a segment cannot
    synthesise a separator in a tuple.

    `ancestors` holds the ids of the containers on the CURRENT path only.
    yaml.safe_load accepts recursive aliases (`horizons: &x {swing: *x}`),
    which used to recurse until RecursionError — a bare 500 again. ANY cycle
    now raises the named ValueError instead. It is not cut and walked past:
    cutting let `horizons: &h {..., position: {vol: *h}}` hide a misplaced
    block while Position ran on its default. A container that is merely
    SHARED (aliased in two places, no cycle) is walked again under each path,
    because where a block sits is exactly what the caller judges — skipping
    every revisit let `position: {vol: *swing}` hide a misplaced block behind
    swing's legal one.
    """
    if isinstance(node, (dict, list, tuple)):
        if id(node) in ancestors:
            raise ConvictionConfigError(
                f"alias cycle in scoring_rules.yaml at {'.'.join(path) or '<root>'}: "
                f"a YAML alias refers back to a mapping or list that contains it, "
                f"so the direction_conviction blocks cannot be located reliably",
                path=".".join(path),
            )
        ancestors = ancestors | {id(node)}
    if isinstance(node, dict):
        for key, value in node.items():
            key_text = str(key)
            if key_text == "direction_conviction":
                yield path + (key_text,), value
            else:
                yield from _walk_direction_conviction_paths(value, path + (key_text,), ancestors)
    elif isinstance(node, (list, tuple)):
        # `!!omap` and `!!pairs` load as a LIST of (key, value) TUPLES, so a
        # tuple whose key is direction_conviction is a block like any other --
        # skipping tuples let `vol: !!omap [direction_conviction: {...}]`
        # sit inert while the gate ran on the default.
        if isinstance(node, tuple) and len(node) == 2 and str(node[0]) == "direction_conviction":
            yield path + ("direction_conviction",), node[1]
            return
        for index, value in enumerate(node):
            yield from _walk_direction_conviction_paths(value, path + (f"[{index}]",), ancestors)
    elif isinstance(node, (set, frozenset)):
        # `!!set` loads as a set of keys whose values are all null.
        if any(str(member) == "direction_conviction" for member in node):
            yield path + ("direction_conviction",), None


def _validated_direction_conviction_blocks(cfg: dict | None = None) -> dict[str, dict | None]:
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

    `cfg` defaults to the running `load_scoring_cfg()`; the config health check
    passes the doc parsed from disk (DOCC-4).
    """
    if cfg is None:
        cfg = load_scoring_cfg()
    horizons = cfg.get("horizons")
    if not isinstance(horizons, dict):
        raise ConvictionConfigError(
            f"invalid scoring_rules.yaml: `horizons` must be a mapping of "
            f"{sorted(_KNOWN_HORIZONS)}, got {type(horizons).__name__}",
            path="horizons",
        )

    legal_paths = {("horizons", h, "direction_conviction") for h in _KNOWN_HORIZONS}
    # NO ANCHOR-HOLDER EXEMPTION, deliberately. A `_defaults: &d` holder that
    # itself carries a direction_conviction is rejected even when a horizon
    # merges it. YAML merges are shallow and first-wins, and PyYAML keeps no
    # record of which horizons merged what, so "some horizon reads this block"
    # cannot tell whether EVERY horizon that merged it still does: with
    # `swing: {<<: *d}` and `position: {<<: *d, direction_conviction:
    # {bullish_min_trend: 60}}`, the holder's bearish value is silently gone
    # for Position. Put the block at horizons.<horizon>.direction_conviction
    # itself (a merge INSIDE the block is fine).
    for found_path, _block in _walk_direction_conviction_paths(cfg):
        if found_path not in legal_paths:
            raise ConvictionConfigError(
                f"misplaced direction_conviction block in scoring_rules.yaml: "
                f"found at {'.'.join(found_path)}, but it must sit at one of "
                f"{sorted('.'.join(p) for p in legal_paths)} — as written it is "
                f"never read, so the gate silently keeps running on its previous "
                f"threshold",
                path=".".join(found_path),
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
            raise ConvictionConfigError(
                f"invalid scoring_rules.yaml: horizons.{key_text} must be a "
                f"mapping, got {type(horizon_cfg).__name__}",
                path=f"horizons.{key_text}",
            )

        block = horizon_cfg.get("direction_conviction")
        if block is not None and not isinstance(block, dict):
            raise ConvictionConfigError(
                f"invalid direction_conviction block for horizon {key_text!r}: "
                f"expected a mapping of {_DIRECTION_CONVICTION_KEYS_TEXT}, got {block!r}",
                path=f"horizons.{key_text}.direction_conviction",
            )
        if isinstance(block, dict):
            unknown = sorted(str(k) for k in set(block) - _DIRECTION_CONVICTION_KEYS)
            if unknown:
                raise ConvictionConfigError(
                    f"unknown direction_conviction key(s) {unknown} for horizon "
                    f"{key_text!r}: expected {_DIRECTION_CONVICTION_KEYS_TEXT}",
                    path=f"horizons.{key_text}.direction_conviction",
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
    return _resolve_min_trend(blocks.get(horizon_key), horizon_key, dir_key, horizon)


def _resolve_min_trend(block: dict | None, horizon_key: str, dir_key: str,
                       horizon: str) -> float | None:
    """The value checks of `load_direction_conviction_min_trend`, shared with
    `direction_conviction_value_errors` so the health check raises exactly the
    message a scan raises. `horizon` is the caller's spelling (title case from
    a request), used only in the message."""
    path = f"horizons.{horizon_key}.direction_conviction.{dir_key}"
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
        raise ConvictionConfigError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is a boolean, expected a number in [0, 100] or null",
            path=path,
        )
    try:
        val = float(raw)
    except (ValueError, TypeError):
        raise ConvictionConfigError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is not a number in [0, 100] or null",
            path=path,
        )
    if not math.isfinite(val) or not (0.0 <= val <= 100.0):
        raise ConvictionConfigError(
            f"invalid direction_conviction.{dir_key} for horizon {horizon!r}: "
            f"{raw!r} is outside the 0-100 range a trend score can take",
            path=path,
        )
    return val


def direction_conviction_value_errors(cfg: dict) -> list[tuple[str, str]]:
    """Every value error `load_direction_conviction_min_trend` would raise on
    `cfg`, over all three horizons and both directions, as (path, message).
    Pure; the caller has already run `_validated_direction_conviction_blocks(cfg)`.
    Horizons are passed title-case, as the scans pass them, so each message is
    byte-identical to the one a scan raises (DOCC-4 plan §2.3)."""
    blocks = _validated_direction_conviction_blocks(cfg)
    errors: list[tuple[str, str]] = []
    for horizon in ("Intraday", "Swing", "Position"):
        key = horizon.lower()
        for dir_key in ("bullish_min_trend", "bearish_min_trend"):
            try:
                _resolve_min_trend(blocks.get(key), key, dir_key, horizon)
            except ConvictionConfigError as exc:
                errors.append((exc.path, str(exc)))
    return errors


# Maps the Step 3 "Reward/Risk" panel's override keys (frontend/lib/
# executionParamDefaults.ts) onto risk_rules.yaml's reward_risk block keys.
_RR_OVERRIDE_KEY_MAP = {
    "rr_bullish_invalidation_pct": "bullish_invalidation_pct",
    "rr_bearish_invalidation_pct": "bearish_invalidation_pct",
}

# Upper bound for each override key, mirroring the Step 3 UI's own `max` for
# these fields (frontend/app/(frame)/screener/step-3-direction/page.tsx). Both
# invalidation overrides must additionally be > 0 (and finite) — see merge_reward_risk_overrides.
_RR_OVERRIDE_CAPS = {
    "rr_bullish_invalidation_pct": 1.0,
    "rr_bearish_invalidation_pct": 1.0,
}


def effective_rr_overrides(overrides: dict | None) -> dict[str, float]:
    """The rr_* keys of `overrides` that merge_reward_risk_overrides applies,
    as floats, keyed by their override names (invalidation percentages and optional target multiple).

    Same validation as merge_reward_risk_overrides (None skipped, invalid
    raises ValueError), so what a scan records is exactly what it priced with.
    """
    out: dict[str, float] = {}
    merged = merge_reward_risk_overrides(overrides)
    for override_key, cfg_key in _RR_OVERRIDE_KEY_MAP.items():
        if overrides and overrides.get(override_key) is not None:
            out[override_key] = float(merged[cfg_key])
    if overrides and overrides.get("rr_target_r_multiple") is not None:
        out["rr_target_r_multiple"] = resolve_target_r_multiple(overrides)
    return out


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


def resolve_target_r_multiple(overrides: dict | None) -> float:
    """One target multiple for option reward/risk and exit-plan rows."""
    value = (overrides or {}).get("rr_target_r_multiple")
    if value is None:
        value = load_exit_plan_cfg()["target"]["rr_ratios"][0]
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("rr_target_r_multiple must be finite and in (0, 10]")
    if not math.isfinite(value) or not 0 < value <= 10:
        raise ValueError("rr_target_r_multiple must be finite and in (0, 10]")
    return value


# Maps Step 3 "Entry Quality" panel override keys (frontend/lib/executionParamDefaults.ts)
# onto scoring_rules.yaml entry_quality config block keys.
_ENTRY_OVERRIDE_KEY_MAP = {
    "entry_spread_tolerance_pct": "spread_tolerance_pct",
    "entry_max_slippage_pct": "max_slippage_pct",
    "entry_min_premium": "min_premium",
}

_ENTRY_OVERRIDE_CAPS = {
    "entry_spread_tolerance_pct": 1.0,
    "entry_max_slippage_pct": 1.0,
    "entry_min_premium": 100.0,
}


def effective_entry_overrides(overrides: dict | None) -> dict[str, float]:
    """The entry_* keys of `overrides` that resolve_entry_config applies,
    as floats, keyed by their override names. Zero is a valid override value.
    None or omitted keys are skipped.
    """
    out: dict[str, float] = {}
    if not overrides:
        return out
    for override_key, cap in _ENTRY_OVERRIDE_CAPS.items():
        if override_key in overrides:
            val = overrides[override_key]
            if val is not None:
                try:
                    val = float(val)
                except (ValueError, TypeError):
                    raise ValueError(
                        f"invalid {override_key}={val!r}: must be a finite number in [0, {cap}]"
                    )
                if not math.isfinite(val) or val < 0 or val > cap:
                    raise ValueError(
                        f"invalid {override_key}={val!r}: must be a finite number in [0, {cap}]"
                    )
                out[override_key] = val
    return out


def resolve_entry_config(overrides: dict | None = None) -> EntryConfig:
    """Return an EntryConfig constructed from per-request entry_* or direct keys,
    falling back to scoring_rules.yaml's entry_quality defaults for omitted or None keys.

    Zero (0 / 0.0) is an explicit, valid override value (e.g. 0% slippage or 0% spread tolerance).
    Invalid, non-finite, negative, or above-cap values raise ValueError.
    """
    from app.scoring.entry_quality import EntryConfig

    if not overrides:
        return EntryConfig()

    kwargs: dict[str, float] = {}
    for override_key, cfg_key in _ENTRY_OVERRIDE_KEY_MAP.items():
        cap = _ENTRY_OVERRIDE_CAPS[override_key]
        raw_val = None
        active_key = override_key
        if override_key in overrides and overrides[override_key] is not None:
            raw_val = overrides[override_key]
            active_key = override_key
        elif cfg_key in overrides and overrides[cfg_key] is not None:
            raw_val = overrides[cfg_key]
            active_key = cfg_key

        if raw_val is not None:
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                raise ValueError(
                    f"invalid {active_key}={raw_val!r}: must be a finite number in [0, {cap}]"
                )
            if not math.isfinite(val) or val < 0 or val > cap:
                raise ValueError(
                    f"invalid {active_key}={raw_val!r}: must be a finite number in [0, {cap}]"
                )
            kwargs[cfg_key] = val

    return EntryConfig(**kwargs)
