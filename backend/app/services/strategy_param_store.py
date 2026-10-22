"""Strategy parameter store with YAML-based configuration and archive-on-adopt."""

from __future__ import annotations

import copy
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml


CFG = Path(__file__).parent.parent.parent / "config" / "strategy_params.yaml"

_CACHE: tuple[Path, dict, float] | None = None  # (cached_path, data, expires_at)
_CACHE_TTL = 60.0  # seconds; invalidated immediately on adopt()


def _load() -> dict:
    """Load strategy_params.yaml or return cached structure if fresh."""
    global _CACHE
    now = time.monotonic()
    if _CACHE is not None and _CACHE[0] == CFG and now < _CACHE[2]:
        return _CACHE[1]
    if not CFG.exists():
        data: dict = {"strategies": {}}
    else:
        data = yaml.safe_load(CFG.read_text(encoding="utf-8")) or {"strategies": {}}
    _CACHE = (CFG, data, now + _CACHE_TTL)
    return data


def _active_block(strategy: str, direction: str) -> dict:
    """The raw ``active[direction]`` dict (baseline keys + horizon sub-dicts).

    Supports both nested ``active: {bullish: {...}, bearish: {...}}``
    and legacy flat ``active: {...}`` (treated as the bullish set).
    """
    active = _load().get("strategies", {}).get(strategy, {}).get("active", {}) or {}
    key = direction.lower()
    if key in ("bullish", "bearish") and (
        "bullish" in active or "bearish" in active
    ):
        return active.get(key, {}) or {}
    # legacy flat active = bullish only
    return active if key == "bullish" else {}


def get_active(strategy: str, direction: str = "Bullish") -> dict:
    """The DIRECTION BASELINE params for a strategy + direction.

    Inside ``active.<direction>``, a key in ``TUNED_HORIZONS`` holds that
    horizon's profile (STOCKS-HORIZON-T1 H4, ADR 0001 decision 3); every other
    key is the baseline. Horizon sub-dicts are removed here, so callers that
    predate the profiles see exactly the set they always saw.

    Returns a deep copy, or an empty dict if not found. The caller should
    provide signal-function defaults if the strategy is unknown.
    """
    from app.services.horizon_profiles import TUNED_HORIZONS
    block = _active_block(strategy, direction)
    return copy.deepcopy({k: v for k, v in block.items() if k not in TUNED_HORIZONS})


def get_profile(
    strategy: str, direction: str, horizon: str | None,
) -> tuple[dict, Literal["tuned", "baseline"]]:
    """The params a scan or watch reads for ``direction`` x ``horizon``.

    ``({**baseline, **profile}, "tuned")`` when ``active.<direction>.<horizon>``
    exists, else ``(baseline, "baseline")``; ``horizon=None`` -> baseline. For
    ``mean_reversion_multi`` the merge is nested: ``variant_params`` merges per
    variant, so a profile naming one variant field keeps the others.
    """
    baseline = get_active(strategy, direction)
    if horizon is None:
        return baseline, "baseline"
    profile = _active_block(strategy, direction).get(horizon)
    if not isinstance(profile, dict):
        return baseline, "baseline"
    profile = copy.deepcopy(profile)
    merged = {**baseline, **profile}
    if "variant_params" in profile:
        base_vp = baseline.get("variant_params") or {}
        prof_vp = profile.get("variant_params") or {}
        merged["variant_params"] = {
            v: {**(base_vp.get(v) or {}), **(prof_vp.get(v) or {})}
            for v in {**base_vp, **prof_vp}
        }
    return merged, "tuned"


def get_search_by_horizon(strategy: str, direction: str, horizon: str) -> dict:
    """The tuner's grid for one cell (strategy x direction x tuned horizon):
    ``strategies.<s>.search_by_horizon.<direction>.<horizon>``. Multi grids
    address variant fields with dots (``mean_reversion_rsi.rsi_oversold``).
    Empty dict when absent. The legacy ``search:`` grid is separate."""
    sbh = _load().get("strategies", {}).get(strategy, {}).get("search_by_horizon", {}) or {}
    return copy.deepcopy((sbh.get(direction.lower(), {}) or {}).get(horizon, {}) or {})


def get_search_space(strategy: str) -> dict:
    """Get search space (hyperparameter grid) for a strategy.

    Returns a copy of the search params dict, or empty dict if strategy not found.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("search", {}))


def get_exit(strategy: str) -> dict:
    """Exit-policy params for a strategy — the ``exit:`` block, a sibling of
    ``active:``/``search:``.

    Deliberately NOT direction-keyed. Every exit thesis in ``strategy_engine`` is
    a mirror pair (measured move up / measured move down, mid-band from below /
    from above) implemented by the function's own ``if direction ==`` branch, so
    the tunables — how far to project, which lookback, which extension multiple —
    are direction-symmetric. Keeping them flat avoids a second place for the two
    directions to silently drift apart.

    Merged UNDER request/grid params at every call site, so an explicit override
    always wins. Returns {} for a strategy with no ``exit:`` block, in which case
    the signal function's own Python defaults apply.

    DURABILITY, which is half the reason this block exists: ``adopt()`` replaces
    ``active[direction]`` wholesale with the WFO tuner's winning grid combo, so a
    parameter that is not in ``search:`` is DELETED from ``active:`` the first
    time a proposal is adopted. ``exit:`` is never touched by ``adopt()``, so a
    rung-2/3 parameter written here keeps its configured value across every
    re-tune instead of silently reverting to the Python default.

    Note also that ``adopt()`` rewrites the whole YAML with ``yaml.safe_dump``,
    which destroys every comment in the file. Configuration prose in
    strategy_params.yaml is therefore best-effort; the durable record of why
    these values exist is this docstring and
    docs/superpowers/plans/2026-08-22-stock-exit-targets-plan.md.
    """
    return dict(_load().get("strategies", {}).get(strategy, {}).get("exit", {}))


def get_windows() -> dict:
    """Get rolling window configuration."""
    return dict(
        _load().get(
            "windows",
            {"type": "rolling", "train_months": 12, "test_months": 3},
        )
    )


def get_costs() -> dict:
    """Get transaction cost configuration."""
    return dict(
        _load().get("costs", {"fee_pct": 0.001, "slippage_pct": 0.001})
    )


def get_direction() -> str:
    """Optimization direction, normalised to 'Bullish' | 'Bearish' (fix #1)."""
    from app.services.strategy_backtest import normalize_direction
    return normalize_direction(_load().get("direction", "bullish"))


def get_optimization_config() -> dict:
    """Get optimization eligibility thresholds (min_trades, min_consistency)."""
    return dict(_load().get("optimization", {"min_trades": 20, "min_consistency": 0.5}))


def get_job_retention() -> dict:
    """Get job retention policy — max_completed: keep only the last N finished jobs."""
    return dict(_load().get("job_retention", {"max_completed": 100}))


def adopt(strategy: str, params: dict, direction: str = "Bullish",
          horizon: str | None = None) -> None:
    """Archive then write ``active[direction]`` = params (atomic, backup-first).

    ``horizon=None`` replaces the direction BASELINE and keeps every horizon
    profile sub-dict (STOCKS-HORIZON-T1 H4). With a tuned horizon it writes
    only ``active[direction][horizon]`` and leaves the baseline alone.

    Migrates a legacy flat ``active: {...}`` to nested ``{bullish: {...}}``
    on the first direction-keyed write so the file stays forward-compatible.

    Creates a backup of the YAML before overwriting.
    Uses atomic write (tmp-then-replace) to prevent corruption on crash.
    """
    global _CACHE
    from app.services.horizon_profiles import TUNED_HORIZONS
    if horizon is not None and horizon not in TUNED_HORIZONS:
        raise ValueError(f"adopt: {horizon!r} is not a tuned horizon")
    # Deep-copy so the in-memory cache is never mutated before the write succeeds.
    data = copy.deepcopy(_load())

    # Archive the current config before modification (if it exists)
    if CFG.exists():
        # UUID suffix guarantees uniqueness even for rapid double-adopt calls.
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = CFG.with_suffix(f".bak.{timestamp}-{uuid.uuid4().hex[:8]}.yaml")
        shutil.copy(CFG, backup_path)

    # Update the active parameters for this strategy + direction
    strat = data.setdefault("strategies", {}).setdefault(strategy, {})
    active = strat.get("active", {})
    # Migrate legacy flat active → nested bullish on first nested write
    if active and not ({"bullish", "bearish"} & set(active.keys())):
        active = {"bullish": active}
    current = active.get(direction.lower()) or {}
    if horizon is None:
        new_block = copy.deepcopy(params)
        for h in TUNED_HORIZONS:
            if h in current:
                new_block[h] = current[h]
    else:
        new_block = dict(current)
        new_block[horizon] = copy.deepcopy(params)
    active[direction.lower()] = new_block
    strat["active"] = active

    # Write back to YAML using atomic write (tmp-then-replace)
    tmp = CFG.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    os.replace(tmp, CFG)
    # Invalidate cache AFTER the write succeeds — no window of stale reads.
    _CACHE = None


def get_composite_trigger_defaults() -> dict:
    """Get default composite trigger thresholds from strategy_params.yaml."""
    return dict(
        _load().get(
            "composite_trigger",
            {
                "conviction_min": 60,
                "p_transition_min": 0.35,
                "p_stay_min": 0.70,
                "min_confirmations": 1,
            },
        )
    )


# ── Per-horizon tuner config (STOCKS-HORIZON-T1 H8) ───────────────────────────
# The `tuning:` block's values come from ADR 0001 decision 4 (costs, fire-rate
# floors) and decision STOCKS-HORIZON-T1-DESIGN-2026-10-05 (windows: train is
# 2-4 x test; Annual's test of 12 months is under 2 x its 200-day hold, as
# decided, and the report says so). Rationale lives here and in the plan:
# adopt() rewrites the YAML with safe_dump, which drops comments.

def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_keys(node, expected: set[str], where: str) -> dict:
    if not isinstance(node, dict):
        raise ValueError(f"{where} must be a mapping, got {type(node).__name__}")
    unknown = sorted(set(node) - expected, key=str)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}")
    missing = sorted(expected - set(node))
    if missing:
        raise ValueError(f"{where}: missing key(s) {missing}")
    return node


def _require(ok: bool, where: str, rule: str, value) -> None:
    if not ok:
        raise ValueError(f"{where} must be {rule}, got {value!r}")


def get_tuning_config() -> dict:
    """The validated ``tuning:`` block (a deep copy). Unknown or missing keys
    and out-of-range values raise ``ValueError`` naming the key."""
    from app.services.horizon_profiles import TUNED_HORIZONS
    data = _load()
    if "tuning" not in data:
        raise ValueError("strategy_params.yaml: missing the `tuning:` block")
    cfg = copy.deepcopy(data["tuning"])
    horizons = set(TUNED_HORIZONS)
    _check_keys(cfg, {"cost_per_leg", "stress_cost_per_leg", "held_out_months", "exit_buffer_days",
                      "windows", "fire_rate_floor_per_day", "adoption", "min_train_trades",
                      "min_folds_not_thin", "basket", "gates"}, "tuning")
    for k in ("cost_per_leg", "stress_cost_per_leg"):
        _require(_num(cfg[k]) and 0 <= cfg[k] < 0.1, f"tuning.{k}", "a number in [0, 0.1)", cfg[k])
    for k in ("held_out_months", "min_train_trades", "min_folds_not_thin"):
        _require(_int(cfg[k]) and cfg[k] >= 1, f"tuning.{k}", "an integer >= 1", cfg[k])
    _require(_int(cfg["exit_buffer_days"]) and cfg["exit_buffer_days"] >= 0,
             "tuning.exit_buffer_days", "an integer >= 0", cfg["exit_buffer_days"])
    _check_keys(cfg["windows"], horizons, "tuning.windows")
    for h in TUNED_HORIZONS:
        w = _check_keys(cfg["windows"][h], {"train_months", "test_months"}, f"tuning.windows.{h}")
        for k in ("train_months", "test_months"):
            _require(_int(w[k]) and w[k] >= 1, f"tuning.windows.{h}.{k}", "an integer >= 1", w[k])
    floors = _check_keys(cfg["fire_rate_floor_per_day"], horizons, "tuning.fire_rate_floor_per_day")
    for h in TUNED_HORIZONS:
        _require(_num(floors[h]) and floors[h] >= 0, f"tuning.fire_rate_floor_per_day.{h}",
                 "a number >= 0", floors[h])
    a = _check_keys(cfg["adoption"], {"ci_level", "min_oos_trades", "min_symbols",
                                      "bootstrap_resamples", "seed"}, "tuning.adoption")
    _require(_num(a["ci_level"]) and 0 < a["ci_level"] < 1, "tuning.adoption.ci_level",
             "a number in (0, 1)", a["ci_level"])
    for k in ("min_oos_trades", "min_symbols", "bootstrap_resamples"):
        _require(_int(a[k]) and a[k] >= 1, f"tuning.adoption.{k}", "an integer >= 1", a[k])
    _require(_int(a["seed"]), "tuning.adoption.seed", "an integer", a["seed"])
    b = _check_keys(cfg["basket"], {"per_sector"}, "tuning.basket")
    _require(_int(b["per_sector"]) and b["per_sector"] >= 1, "tuning.basket.per_sector",
             "an integer >= 1", b["per_sector"])
    g = _check_keys(cfg["gates"], {"min_price", "max_price"}, "tuning.gates")
    for k in ("min_price", "max_price"):
        _require(g[k] is None or (_num(g[k]) and g[k] >= 0), f"tuning.gates.{k}",
                 "null or a number >= 0", g[k])
    return cfg
