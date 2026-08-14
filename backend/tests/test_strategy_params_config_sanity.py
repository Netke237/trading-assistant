"""Config-sanity test for backend/config/strategy_params.yaml (PLAN_TIER1_RISK_SAFETY.md #3).

Walks every strategy's `active.<direction>` params and, for every param that also
appears in that strategy's `search` grid, asserts the live active value is one of
the values the WFO optimizer actually searches over. A value drifting outside its
own search grid (e.g. pullback_ema.active.bearish.ema_period = 35 when
search.ema_period was [20, 50]) means the optimizer can never validate — or
challenge — the value actually running live; this test exists specifically to
catch that class of drift for every strategy in the file, not just the one that
was already found.

Reads the real shipped config directly off disk (not through strategy_param_store,
which some other tests monkeypatch to a temp file) so this test always reflects
what's actually deployed.
"""
from __future__ import annotations

from pathlib import Path

import yaml

CFG_PATH = Path(__file__).parent.parent / "config" / "strategy_params.yaml"


def _load_strategies() -> dict:
    data = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
    return data.get("strategies", {})


def test_config_file_is_readable():
    strategies = _load_strategies()
    assert strategies, "strategy_params.yaml must define at least one strategy"


def test_every_active_value_falls_within_its_own_search_grid():
    strategies = _load_strategies()
    violations: list[str] = []

    for strat_name, strat_cfg in strategies.items():
        search = strat_cfg.get("search")
        if not search:
            # Strategies without a search block are intentionally excluded from
            # WFO (documented inline in the yaml, e.g. mean_reversion_vwap,
            # breakout_setup) — nothing to validate.
            continue

        active = strat_cfg.get("active", {})
        for direction, direction_params in active.items():
            if not isinstance(direction_params, dict):
                continue
            for param_key, active_value in direction_params.items():
                if param_key not in search:
                    # Not every active param is tuned by the optimizer (e.g.
                    # boolean flags, interval strings) — only check params the
                    # search grid actually covers.
                    continue
                grid = search[param_key]
                if active_value not in grid:
                    violations.append(
                        f"{strat_name}.active.{direction}.{param_key} = {active_value!r} "
                        f"is not in search.{param_key} = {grid!r}"
                    )

    assert not violations, (
        "Live strategy param(s) outside their own WFO search grid:\n"
        + "\n".join(violations)
    )
