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


def test_legacy_target_overrides_are_ignored():
    base = load_reward_risk_cfg()
    assert merge_reward_risk_overrides({"rr_bullish_target_pct": .12, "rr_bearish_target_pct": .09}) == base


def test_invalidation_overrides_do_not_mutate_base():
    base = dict(load_reward_risk_cfg())
    merged = merge_reward_risk_overrides({"rr_bullish_invalidation_pct": .04, "rr_bearish_invalidation_pct": .05})
    assert merged["bullish_invalidation_pct"] == .04
    assert merged["bearish_invalidation_pct"] == .05
    assert load_reward_risk_cfg() == base


def test_merge_ignores_unrelated_and_none_values():
    assert merge_reward_risk_overrides({"rsi_floor":40, "rr_bullish_invalidation_pct":None}) == load_reward_risk_cfg()


@pytest.mark.parametrize("key", ["rr_bullish_invalidation_pct", "rr_bearish_invalidation_pct"])
@pytest.mark.parametrize("value", [-1, 0, 1.01, float("nan"), float("inf"), "abc"])
def test_invalidation_validation(key,value):
    with pytest.raises(ValueError,match=key):merge_reward_risk_overrides({key:value})


def test_invalidation_inclusive_cap():
    assert merge_reward_risk_overrides({"rr_bullish_invalidation_pct":1})["bullish_invalidation_pct"] == 1


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


def test_direction_conviction_rejects_an_unknown_horizon_from_the_caller():
    """Round 3 audit finding: this used to return None — "exempt" — so an
    unrecognised horizon SILENTLY DISABLED the gate.

    That is the exact silent-widening this change exists to remove, left alive
    on the one axis the config validation cannot see. Unreachable from the API
    today (both request models Literal-restrict `horizon`), so raising costs
    nothing; the day `Horizon` gains a member and somebody forgets the config
    entry, it fails loudly instead of screening nothing at all."""
    with pytest.raises(ValueError, match="unknown horizon"):
        load_direction_conviction_min_trend("Bearish", "Decade")


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
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_direction_conviction_rejects_a_misspelled_horizon_key():
    with patch("app.services.config_loader.load_scoring_cfg",
               return_value={"horizons": {"positon": {
                   "direction_conviction": {"bearish_min_trend": 55}}}}):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
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
    ever lost).

    WHAT THIS DOES AND DOES NOT CATCH, corrected after round 3. Resolution is
    YAML-first, so the YAML always wins and the defaults are unreachable while
    it is present — this test therefore does NOT catch "the gate is running on
    the defaults while the YAML sits inert", which cannot happen, and it does
    NOT catch an edit that changes the YAML and the defaults together (the
    literal floor tables in the two funnel suites catch that, by running the
    endpoints).

    What it does catch is the two drifting APART, which matters because the
    defaults are the safety net: if they say something different from the
    shipped file, then the day the YAML block is lost or unreadable the gate
    silently moves instead of holding its ground.
    """
    import yaml
    from pathlib import Path
    from app.services.config_loader import _DIRECTION_CONVICTION_DEFAULTS

    cfg = yaml.safe_load(
        (Path(__file__).parent.parent / "config" / "scoring_rules.yaml").read_text()
    )
    # The UNION of both sides, not just the YAML's horizons: iterating only the
    # YAML meant a code default for a horizon the YAML never declares was never
    # examined (round 3 mutation M48 added one and survived).
    for horizon in sorted(set(cfg["horizons"]) | set(_DIRECTION_CONVICTION_DEFAULTS)):
        block = cfg["horizons"].get(horizon)
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


# ── Round 3: the validator must not own the `horizons` namespace ─────────────

@pytest.mark.parametrize("extra_key,extra_value", [
    ("weekly",    {"weights": {"trend": 0.3}}),           # a plausible new horizon
    ("_defaults", {"weights": {"trend": 0.3}}),           # the YAML anchor-holder idiom
    ("quarterly", None),                                  # even a broken unknown entry
])
def test_an_unrecognised_horizon_without_a_gate_block_is_none_of_our_business(
    extra_key, extra_value,
):
    """Round 3 audit finding: an earlier version rejected ANY key in `horizons`
    outside the known three, so a harmless additive edit to scoring_rules.yaml —
    a new horizon, or the `_defaults: &anchor` holder a YAML merge key needs —
    hard-500'd BOTH scan endpoints while every other consumer of the file
    carried on working.

    This feature owns `direction_conviction`, not the file."""
    cfg = {"horizons": {
        extra_key:  extra_value,
        "position": {"direction_conviction": {"bearish_min_trend": 40}},
    }}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bearish", "Position") == 40.0


# ── Round 3: misplacement is positional, at ANY depth ───────────────────────

@pytest.mark.parametrize("cfg,where", [
    # Two levels too deep. NOT hypothetical: the shipped file has real 3-deep
    # mappings at horizons.<h>.trend.{crossover,additive,relative_strength}, so
    # a double-indent lands somewhere that exists.
    ({"horizons": {"position": {"trend": {"additive": {
        "direction_conviction": {"bearish_min_trend": 70}}}}}},
     "two levels deep"),
    # Outside `horizons` altogether.
    ({"direction_conviction": {"bearish_min_trend": 70},
      "horizons": {"position": {}}},
     "file top level"),
    # Inside a list-valued sibling — the old mapping-only check skipped these.
    ({"horizons": {"position": {"variants": [
        {"direction_conviction": {"bearish_min_trend": 70}}]}}},
     "inside a list"),
])
def test_a_misplaced_block_is_rejected_at_any_depth(cfg, where):
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_misplacement_is_detected_under_a_LATER_sibling_not_just_the_first():
    """Round 3 mutation M44: restricting the search to the first sibling
    survived the suite, because the only misnesting test had exactly one
    sibling to search. In the shipped file `direction_conviction` is the 8th key
    under each horizon, so a real misnest lands under `weights`, `trend`,
    `pullback`, `trigger`, `event` or `vol` — never the first key."""
    cfg = {"horizons": {"position": {
        "weights":       {"trend": 0.3},
        "trend":         {"method": "additive"},
        "pullback":      {},
        "trigger":       {},
        "event":         {"reject_days": 21},
        "vol":           {},
        "stop_premium":  {"pass_max_fraction": 0.6,
                          "direction_conviction": {"bearish_min_trend": 70}},
    }}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_non_string_yaml_key_gives_a_named_error_not_an_attributeerror():
    """Round 3 mutation M35: PyYAML parses `on:`, `yes:` and `true:` as BOOLEAN
    keys and `1:` as an int. Without stringifying, `key.lower()` raises
    AttributeError — which neither router catches (both catch ValueError), so it
    escapes as a bare 500 with no `detail` and destroys the naming-the-offending-
    key guarantee this validation exists to provide."""
    for weird_key in (True, 1, None):
        cfg = {"horizons": {
            weird_key:  {"direction_conviction": {"bearish_min_trend": 70}},
            "position": {},
        }}
        with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
            with pytest.raises(ValueError, match="misplaced direction_conviction block"):
                load_direction_conviction_min_trend("Bearish", "Position")


def test_code_defaults_only_name_known_horizons():
    """Round 3 mutation M48: test_shipped_yaml_and_code_defaults_agree iterates
    the YAML's horizons, so a code default for a horizon the YAML never declares
    was never examined — a typo'd default key (`positon`) would sit inert
    forever, which is the exact failure the YAML side is hardened against."""
    from app.services.config_loader import (
        _DIRECTION_CONVICTION_DEFAULTS, _KNOWN_HORIZONS,
    )
    unknown = sorted(set(_DIRECTION_CONVICTION_DEFAULTS) - _KNOWN_HORIZONS)
    assert not unknown, (
        f"code defaults name horizon(s) {unknown} that the resolver will never "
        f"look up — a typo here is silently inert"
    )
    for horizon, block in _DIRECTION_CONVICTION_DEFAULTS.items():
        bad_keys = sorted(set(block) - {"bullish_min_trend", "bearish_min_trend"})
        assert not bad_keys, f"{horizon}: unusable default key(s) {bad_keys}"
