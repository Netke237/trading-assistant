"""The shared `regime_gate` threshold resolver.

Piece 2 round 1 finding 3: the Step-3 "Headwind reject %" control reached the
STOCK scan and nothing else — not the options scan that produces every armable
card, and not the fire path. The three sites now share one resolver, and these
tests are what that sharing is worth: they pin the contract once for all three.
"""
import pytest

from app.services.regime_gate import resolve_regime_gate

YAML = {
    "enabled": True,
    "headwind_caution_pct": -15,
    "headwind_reject_pct": -40,
    "require_stable_for_reject": True,
}


def test_no_overrides_returns_the_yaml_values():
    assert resolve_regime_gate(YAML) == YAML


def test_each_override_replaces_only_its_own_key():
    out = resolve_regime_gate(YAML, reject_pct=-80)
    assert out["headwind_reject_pct"] == -80
    assert out["headwind_caution_pct"] == -15, "the other threshold must not move"
    assert out["enabled"] is True
    assert out["require_stable_for_reject"] is True


def test_zero_is_a_threshold_and_not_an_absence():
    """The reason the check is `is not None` and not a truthiness test.

    0 is inside the Step-3 control's own -100..0 range and means "any headwind
    at all caps this". A falsy test would silently discard it and fall back to
    the YAML -40, which is 40 points looser than what the trader asked for.
    """
    out = resolve_regime_gate(YAML, caution_pct=0, reject_pct=0)
    assert out["headwind_caution_pct"] == 0
    assert out["headwind_reject_pct"] == 0


def test_the_base_is_never_mutated():
    """The YAML doc behind `base` is lru_cached and handed out BY REFERENCE at
    all three call sites, so a write-through would repoint every later reader in
    the process — until a restart, since that is the only thing that clears the
    cache."""
    base = dict(YAML)
    resolve_regime_gate(base, caution_pct=-1, reject_pct=-2)
    assert base == YAML


def test_an_absent_block_stays_absent_rather_than_becoming_a_live_gate():
    """None/{} means the gate is off. An override must not conjure one into
    existence: `_regime_cap` requires a truthy `enabled` before it caps
    anything, and nothing here adds one."""
    for base in (None, {}):
        out = resolve_regime_gate(base, caution_pct=-15, reject_pct=-40)
        assert out.get("enabled") in (None, False)


def test_enabled_and_require_stable_are_not_overridable_by_any_caller():
    """Deliberate scope: these two are config, not per-run parameters. The
    signature is the enforcement — there is no argument that can reach them."""
    import inspect
    params = set(inspect.signature(resolve_regime_gate).parameters)
    assert params == {"base", "caution_pct", "reject_pct"}


@pytest.mark.parametrize("module_path, attr", [
    ("app.routers.scan", "_resolve_regime_gate"),
    ("app.routers.stock_scan", "_resolve_regime_gate"),
])
def test_both_scan_routers_use_this_exact_function(module_path, attr):
    """Same-object identity, not "looks equivalent".

    The anti-drift standard already used for `conviction_mult`: two routers that
    merely agree today can be edited apart tomorrow, and the gap only shows up
    as two scans disagreeing about one symbol.
    """
    import importlib
    mod = importlib.import_module(module_path)
    assert getattr(mod, attr) is resolve_regime_gate


def test_the_fire_path_resolves_through_it_too():
    """The auto-trader imports it inside the function, so identity is asserted
    through behaviour: an ArmedStrategy snapshot must produce exactly what the
    shared resolver produces from the same two numbers."""
    import app.services.auto_trader as at
    strategy = at.ArmedStrategy(
        broker="ibkr_paper", symbol="MSFT", option_symbol="MSFT260620C00185000",
        action="BUY", direction="Bullish", quantity=1, order_type="LMT",
        limit_price=2.50, conid=None, horizon="Position",
        regime_headwind_caution_pct=-25, regime_headwind_reject_pct=-80,
    )
    assert at._resolve_regime_gate(strategy) == resolve_regime_gate(
        at._load_regime_gate_config(), -25, -80,
    )
