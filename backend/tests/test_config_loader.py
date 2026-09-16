"""Tests for app.services.config_loader's reward/risk override merging and
direction-conviction gate resolution."""
from unittest.mock import patch

import pytest

from app.services.config_loader import (
    load_direction_conviction_min_trend,
    load_reward_risk_cfg,
    merge_reward_risk_overrides,
)


def test_merge_with_no_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides({})
    assert merged == base


def test_merge_with_none_overrides_returns_base_config():
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides(None)
    assert merged == base


def test_merge_overrides_bullish_target_pct():
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": 0.12})
    assert merged["bullish_target_pct"] == 0.12
    # Untouched keys keep the base config's values.
    base = load_reward_risk_cfg()
    assert merged["bearish_target_pct"] == base["bearish_target_pct"]
    assert merged["premium_stop_pct"] == base["premium_stop_pct"]


def test_merge_overrides_all_four_rr_keys():
    merged = merge_reward_risk_overrides({
        "rr_bullish_target_pct": 0.12,
        "rr_bearish_target_pct": 0.09,
        "rr_bullish_invalidation_pct": 0.04,
        "rr_bearish_invalidation_pct": 0.05,
    })
    assert merged["bullish_target_pct"] == 0.12
    assert merged["bearish_target_pct"] == 0.09
    assert merged["bullish_invalidation_pct"] == 0.04
    assert merged["bearish_invalidation_pct"] == 0.05


def test_merge_ignores_unrelated_override_keys():
    """Other scan overrides (e.g. rsi_floor) must not leak into rr_cfg or raise."""
    merged = merge_reward_risk_overrides({"rsi_floor": 40, "rr_bullish_target_pct": 0.11})
    assert merged["bullish_target_pct"] == 0.11
    assert "rsi_floor" not in merged


def test_merge_does_not_mutate_the_cached_base_config():
    base_before = dict(load_reward_risk_cfg())
    merge_reward_risk_overrides({"rr_bullish_target_pct": 0.99})
    assert load_reward_risk_cfg() == base_before


# ── Finding 2/3: bounds validation + None-skip ────────────────────────────────

def test_merge_skips_none_override_value():
    """A None override (e.g. a cleared frontend field) must be silently
    skipped, not crash on float(None) -- this is Finding 3's fix."""
    base = load_reward_risk_cfg()
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": None})
    assert merged["bullish_target_pct"] == base["bullish_target_pct"]


@pytest.mark.parametrize("key", [
    "rr_bullish_target_pct", "rr_bearish_target_pct",
    "rr_bullish_invalidation_pct", "rr_bearish_invalidation_pct",
])
def test_merge_rejects_negative_value(key):
    with pytest.raises(ValueError, match=key):
        merge_reward_risk_overrides({key: -0.5})


@pytest.mark.parametrize("key", [
    "rr_bullish_target_pct", "rr_bearish_target_pct",
    "rr_bullish_invalidation_pct", "rr_bearish_invalidation_pct",
])
def test_merge_rejects_zero_value(key):
    with pytest.raises(ValueError, match=key):
        merge_reward_risk_overrides({key: 0})


def test_merge_rejects_value_above_target_cap():
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": 500})


def test_merge_rejects_value_above_invalidation_cap():
    with pytest.raises(ValueError, match="rr_bullish_invalidation_pct"):
        merge_reward_risk_overrides({"rr_bullish_invalidation_pct": 1.5})


def test_merge_rejects_non_finite_value():
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": float("inf")})


def test_merge_accepts_valid_in_range_value_at_target_cap():
    # Regression guard: the cap is inclusive (<=), not exclusive.
    merged = merge_reward_risk_overrides({"rr_bullish_target_pct": 2.0})
    assert merged["bullish_target_pct"] == 2.0


def test_merge_accepts_valid_in_range_value_at_invalidation_cap():
    merged = merge_reward_risk_overrides({"rr_bullish_invalidation_pct": 1.0})
    assert merged["bullish_invalidation_pct"] == 1.0


def test_merge_rejects_non_numeric_string_value_with_named_key():
    """Round 2 audit finding: a non-numeric string (e.g. a mistyped override)
    must raise the function's own well-messaged ValueError naming the
    offending key -- not Python's raw float() ValueError, which doesn't."""
    with pytest.raises(ValueError, match="rr_bullish_target_pct"):
        merge_reward_risk_overrides({"rr_bullish_target_pct": "abc"})


# ── Direction-conviction gate resolution ─────────────────────────────────────
#
# The gate this resolver feeds screens every non-Intraday scan in BOTH modes.
# Its bearish half was inverted (a `max_trend` ceiling instead of a floor) from
# 2026-06-18 until 2026-09-16, which deleted the strongest short setups and
# kept the names that were not falling, so the resolution rules are pinned
# here rather than left to the callers' own tests.

def _cfg(direction_conviction_by_horizon: dict) -> dict:
    """A scoring_rules.yaml stand-in carrying only the block under test."""
    return {
        "horizons": {
            horizon: {"direction_conviction": block}
            for horizon, block in direction_conviction_by_horizon.items()
        }
    }


def test_direction_conviction_reads_the_shipped_config_as_mirrored_floors():
    """The shipped scoring_rules.yaml gates both directions on the SAME floor at
    each horizon, and exempts Intraday. Asserted as an equality between the two
    directions, so a change to one side alone fails here."""
    for horizon, expected in (("Swing", 30.0), ("Position", 40.0), ("Intraday", None)):
        bullish = load_direction_conviction_min_trend("Bullish", horizon)
        bearish = load_direction_conviction_min_trend("Bearish", horizon)
        assert bullish == expected, f"Bullish/{horizon}"
        assert bearish == expected, f"Bearish/{horizon}"
        assert bullish == bearish, (
            f"{horizon}: the two directions no longer mirror each other "
            f"(Bullish {bullish} vs Bearish {bearish})"
        )


def test_direction_conviction_yaml_value_beats_the_code_default():
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"position": {"bearish_min_trend": 55}})):
        assert load_direction_conviction_min_trend("Bearish", "Position") == 55.0
        # The key the stub did NOT set still falls back to the code default.
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0


def test_direction_conviction_falls_back_to_defaults_when_the_block_is_absent():
    """Deleting the YAML block must leave the gate at its shipped strength, not
    silently disable it — an absent threshold that read as 'no gate' would widen
    the screen without anyone noticing."""
    with patch("app.services.config_loader.load_scoring_cfg", return_value={"horizons": {}}):
        assert load_direction_conviction_min_trend("Bearish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bearish", "Position") == 40.0
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0
        # Intraday has no default, so it stays exempt.
        assert load_direction_conviction_min_trend("Bearish", "Intraday") is None


def test_direction_conviction_explicit_null_exempts_that_direction():
    """An explicit `null` is honoured rather than falling through to the
    default — that is how a horizon is deliberately exempted."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"position": {"bearish_min_trend": None}})):
        assert load_direction_conviction_min_trend("Bearish", "Position") is None
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0


def test_direction_conviction_accepts_the_range_boundaries():
    for value in (0, 100):
        with patch("app.services.config_loader.load_scoring_cfg",
                   return_value=_cfg({"swing": {"bearish_min_trend": value}})):
            assert load_direction_conviction_min_trend("Bearish", "Swing") == float(value)


@pytest.mark.parametrize("bad", ["abc", "", [], {}, float("nan"), float("inf"), -1, 101])
def test_direction_conviction_rejects_a_malformed_threshold(bad):
    """A malformed threshold must raise, not silently disable the gate: a typo
    in the config has to fail the scan loudly rather than quietly widening the
    screen to everything."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"swing": {"bearish_min_trend": bad}})):
        with pytest.raises(ValueError, match="bearish_min_trend"):
            load_direction_conviction_min_trend("Bearish", "Swing")


@pytest.mark.parametrize("bad", [True, False])
def test_direction_conviction_rejects_a_boolean_threshold(bad):
    """bool subclasses int, so a YAML `true` would otherwise pass float() as 1.0
    and install a floor that admits essentially every candidate — and `false`
    would become 0.0, a gate that rejects nothing at all."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"swing": {"bearish_min_trend": bad}})):
        with pytest.raises(ValueError, match="boolean"):
            load_direction_conviction_min_trend("Bearish", "Swing")


def test_direction_conviction_rejects_an_unknown_direction():
    with pytest.raises(ValueError, match="unknown direction"):
        load_direction_conviction_min_trend("Sideways", "Swing")


def test_direction_conviction_treats_an_unknown_horizon_as_exempt():
    """An unrecognised horizon has no floor to apply. It cannot reach here from
    the API — both request models Literal-restrict `horizon` — so returning None
    rather than raising keeps a non-scan caller from crashing on a horizon name
    this table simply does not cover."""
    assert load_direction_conviction_min_trend("Bearish", "Decade") is None


@pytest.mark.parametrize("block", [
    30,                                  # scalar written where a mapping belongs
    "30",                                # ditto, quoted
    [{"bearish_min_trend": 30}],         # list, e.g. a stray YAML "- "
])
def test_direction_conviction_rejects_a_block_that_is_not_a_mapping(block):
    """Round 1 audit finding: a block of the wrong SHAPE used to skip every
    validation and fall through to the code default, so the YAML edit was
    silently ignored while the user believed they had moved the gate."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": {"position": {"direction_conviction": block}}}):
        with pytest.raises(ValueError, match="direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


@pytest.mark.parametrize("typo", ["bearish_min_tren", "bearish_trend_min", "min_trend"])
def test_direction_conviction_rejects_a_misspelled_key(typo):
    """A misspelled key is the LIKELIEST config typo, and used to be the most
    dangerous: it matched nothing, so the resolver silently returned the code
    default and the edit had no effect at all."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"position": {typo: 30}})):
        with pytest.raises(ValueError, match="unknown direction_conviction key"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_direction_conviction_names_the_offending_key_and_horizon():
    """The message has to be actionable on its own — it is what reaches the
    operator as the 500 body when a scan refuses to start.

    The horizon is named in its YAML spelling (`swing`), not the caller's
    (`Swing`): the message exists to point at the line that needs editing, and
    that file spells its keys lower-case."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value=_cfg({"swing": {"bearish_min_tren": 30}})):
        with pytest.raises(ValueError) as exc:
            load_direction_conviction_min_trend("Bearish", "Swing")
    message = str(exc.value)
    assert "bearish_min_tren" in message          # what is wrong
    assert "swing" in message                     # where, as the YAML spells it
    assert "bearish_min_trend" in message         # what was expected


def test_direction_conviction_rejects_a_horizon_entry_that_is_not_a_mapping():
    """Round 2 audit finding: the previous version of this test asserted that
    `{"horizons": {"position": None}}` resolved to the code default, pinning the
    silent fallthrough as correct.

    It cannot be benign. `horizons.position` being None means the ENTIRE
    Position scoring block is gone — weights, trend, pullback, trigger, event,
    vol, stop_premium — and stock_scorer would have thrown long before the gate
    was consulted. Treating it as "use the defaults" hid a broken config file
    behind a plausible-looking number."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": {"position": None, "swing": {}}}):
        with pytest.raises(ValueError, match="horizons.position must be a mapping"):
            load_direction_conviction_min_trend("Bearish", "Position")


# ── Shapes that used to make the YAML block silently inert ───────────────────
#
# Round 2 audit: the round-1 hardening caught a bad LEAF key and a bad block
# shape, but a block at the wrong NESTING, a mis-cased or misspelled horizon
# key, and a wrong-shaped `horizons` parent all still fell through to the code
# defaults in total silence — which is the original finding's exact failure
# mode, just one level up.

def test_direction_conviction_rejects_a_block_nested_one_level_too_deep():
    """The likeliest typo for a block three levels down: indent it once more and
    it lands under a sibling key. Nothing sees it, the gate keeps running on its
    old threshold, and the operator believes they moved the screen."""
    cfg = {"horizons": {"position": {
        "stop_premium": {"pass_max_fraction": 0.6,
                         "direction_conviction": {"bearish_min_trend": 70}},
    }}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_direction_conviction_rejects_a_mis_cased_horizon_key():
    """`Position:` is what Horizon = Literal['Intraday','Swing','Position']
    shows everywhere in the codebase, so it is the natural thing to write — and
    the lookup is lower-cased, so as written the whole block was inert."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": {"Position": {
                   "direction_conviction": {"bearish_min_trend": 55}}}}):
        with pytest.raises(ValueError, match="must be lower-case"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_direction_conviction_rejects_a_misspelled_horizon_key():
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": {"positon": {
                   "direction_conviction": {"bearish_min_trend": 55}}}}):
        with pytest.raises(ValueError, match="unknown horizon"):
            load_direction_conviction_min_trend("Bearish", "Position")


@pytest.mark.parametrize("horizons", [None, [], [{"position": {}}], "position", 7])
def test_direction_conviction_rejects_a_horizons_parent_of_the_wrong_shape(horizons):
    """A stray `- ` turning the map into a list used to resolve to 'use the code
    defaults' rather than failing — a structurally broken config file reported
    as a working one."""
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": horizons}):
        with pytest.raises(ValueError, match="`horizons` must be a mapping"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_direction_conviction_validates_every_horizon_not_just_the_scanned_one():
    """A typo in the `swing` block used to survive every Position and Intraday
    scan and surface only the first time somebody ran a Swing scan."""
    cfg = {"horizons": {
        "swing":    {"direction_conviction": {"bearish_min_tren": 99}},   # typo
        "position": {"direction_conviction": {"bearish_min_trend": 40}},  # fine
    }}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="bearish_min_tren"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_shipped_yaml_and_code_defaults_agree():
    """The thresholds exist in two places that must not drift: the shipped YAML
    (what runs) and _DIRECTION_CONVICTION_DEFAULTS (what runs if the block is
    ever deleted).

    Round 2 audit described the trap this closes: edit the YAML, watch the
    endpoint tests go red, then "fix" them by editing the defaults to match —
    and end up with a gate running on the DEFAULTS while the YAML sits inert.
    Pinning the two together means that path fails here instead of passing.
    """
    import yaml
    from pathlib import Path
    from app.services.config_loader import _DIRECTION_CONVICTION_DEFAULTS

    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "config" / "scoring_rules.yaml").read_text()
    )
    for horizon, block in cfg["horizons"].items():
        declared = (block or {}).get("direction_conviction") or {}
        defaults = _DIRECTION_CONVICTION_DEFAULTS.get(horizon, {})
        for key in ("bullish_min_trend", "bearish_min_trend"):
            yaml_val = declared.get(key)
            code_val = defaults.get(key)
            assert (yaml_val is None) == (code_val is None), (
                f"{horizon}.{key}: YAML says {yaml_val!r}, code default says "
                f"{code_val!r} — one exempts the direction and the other gates it"
            )
            if yaml_val is not None:
                assert float(yaml_val) == float(code_val), (
                    f"{horizon}.{key}: YAML {yaml_val} != code default {code_val}. "
                    f"Change BOTH, or deleting the YAML block silently moves the gate."
                )
