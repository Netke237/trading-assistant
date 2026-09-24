"""Q3B -- config_loader direction_conviction validator hardening.

Plan: docs/superpowers/plans/2026-09-24-q3b-config-loader-hardening-plan.md
  1. Tuple paths: a key containing '.' cannot forge a legal path.
  2. No anchor-holder exemption: a holder carrying a direction_conviction is
     rejected even when a horizon merges it (plan round 1's finding).
  3. Any YAML alias cycle raises a named ValueError (main: RecursionError),
     and a cycle can never hide a misplaced block.
  4. Coverage: mixed-type unknown keys; a numeric Intraday threshold.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from app.services.config_loader import (
    _validated_direction_conviction_blocks,
    load_direction_conviction_min_trend,
    load_scoring_cfg,
)


def _load(text: str) -> dict:
    return yaml.safe_load(text)


def test_a_flat_dotted_key_cannot_forge_a_legal_path():
    """3a. A top-level key literally spelled `horizons.position` used to join to
    the legal string 'horizons.position.direction_conviction', pass validation,
    and sit inert while the gate ran on the real block's 40."""
    cfg = _load("""
horizons.position:
  direction_conviction: {bearish_min_trend: 99}
horizons:
  position:
    direction_conviction: {bearish_min_trend: 40}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\.position\.direction_conviction"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_dotted_key_inside_horizons_cannot_forge_either():
    cfg = {"horizons": {
        "position.x": {"direction_conviction": {"bearish_min_trend": 99}},
        "position": {"direction_conviction": {"bearish_min_trend": 40}},
    }}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


# ── 2. No anchor-holder exemption (plan round 1's finding) ─────────────────
# A holder carrying a direction_conviction is rejected even when a horizon
# merges it: YAML merges are shallow and first-wins, and PyYAML keeps no merge
# provenance, so "some horizon reads it" cannot prove every merging horizon
# does. Each shape below was accepted by the exemption tried at 83b98de.

def test_an_anchor_holder_whose_block_a_horizon_merges_is_rejected():
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bullish_min_trend: 55, bearish_min_trend: 45}
  position:
    <<: *dc
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\._defaults\.direction_conviction"):
            load_direction_conviction_min_trend("Bullish", "Position")


def test_a_holder_one_horizon_reads_and_another_overrides_is_rejected():
    """Plan round 1, repro A: Swing reads the holder's block, Position merges
    it then writes its own, and the shallow merge drops the holder's bearish
    45 -- Position Bearish would run on the default 40."""
    cfg = _load("""
horizons:
  _d: &d
    direction_conviction: {bullish_min_trend: 55, bearish_min_trend: 45}
  swing: {<<: *d}
  position:
    <<: *d
    direction_conviction: {bullish_min_trend: 60}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\._d\.direction_conviction"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_merge_list_that_shadows_a_holder_is_rejected():
    """Plan round 1, repro B: in a PyYAML merge list the FIRST entry wins, so
    the 70 merged into swing from _b is silently shadowed by _a's 55."""
    cfg = _load("""
_a: &a {direction_conviction: {bullish_min_trend: 55}}
_b: &b {direction_conviction: {bullish_min_trend: 70}}
horizons:
  swing: {<<: [*a, *b]}
  position: {<<: *b}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*_a\.direction_conviction"):
            load_direction_conviction_min_trend("Bullish", "Swing")


def test_a_block_aliased_into_a_horizon_from_a_holder_is_rejected():
    cfg = _load("""
_shared:
  direction_conviction: &blk {bearish_min_trend: 45}
horizons:
  swing:
    direction_conviction: *blk
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*_shared\.direction_conviction"):
            load_direction_conviction_min_trend("Bearish", "Swing")


def test_a_merge_inside_the_block_is_accepted():
    """The supported way to share numbers: merge a plain mapping INTO the
    block at its legal path."""
    cfg = _load("""
_dc: &dc {bullish_min_trend: 55, bearish_min_trend: 45}
horizons:
  swing:
    direction_conviction: *dc
  position:
    direction_conviction: {<<: *dc, bullish_min_trend: 60}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 55.0
        assert load_direction_conviction_min_trend("Bearish", "Swing") == 45.0
        assert load_direction_conviction_min_trend("Bullish", "Position") == 60.0
        assert load_direction_conviction_min_trend("Bearish", "Position") == 45.0


def test_an_anchor_holder_nobody_merges_is_still_rejected():
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bearish_min_trend: 45}
  position:
    weights: {trend: 0.3}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*horizons\._defaults"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_holder_block_overridden_by_the_horizon_is_still_rejected():
    """The horizon merges the holder but then writes its own block, so the
    holder's is never read -- editing it would change nothing."""
    cfg = _load("""
horizons:
  _defaults: &dc
    direction_conviction: {bearish_min_trend: 45}
  position:
    <<: *dc
    direction_conviction: {bearish_min_trend: 40}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_misplaced_null_block_gets_no_identity_exemption():
    """`None is None` everywhere, so a scalar must never borrow a legal
    horizon's identity. Misplaced `direction_conviction: null` under `vol`
    while position also has an explicit null: still rejected."""
    cfg = {"horizons": {"position": {
        "direction_conviction": None,
        "vol": {"direction_conviction": None},
    }}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bearish", "Position")


# Round 2 (the code) finding: the first exemption asked only "does SOME horizon
# read this object?", so a block aliased into the WRONG place was excused by
# another horizon's legal read, and the horizon the operator meant ran on its
# old threshold. Each case below was accepted at 0d02be6 and rejected on main.

@pytest.mark.parametrize("text,where", [
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    vol:
      direction_conviction: *b
""", r"horizons\.position\.vol\.direction_conviction"),
    ("""
horizons:
  _defaults: &d
    direction_conviction: {bullish_min_trend: 60, bearish_min_trend: 60}
  swing:
    <<: *d
  position:
    trend:
      <<: *d
""", r"horizons\.(_defaults|position\.trend)\.direction_conviction"),
    ("""
horizons:
  swing: &s
    direction_conviction: {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    vol: *s
""", r"horizons\.position\.vol\.direction_conviction"),
    # A mis-cased horizon aliasing another horizon's block: Position meant,
    # swing's block borrowed.
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  Position:
    direction_conviction: *b
""", r"horizons\.Position\.direction_conviction"),
    # An '_'-prefixed holder INSIDE a known horizon is still the wrong place
    # for that horizon, whoever else reads the object.
    ("""
horizons:
  swing:
    direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
  position:
    _local:
      direction_conviction: *b
""", r"horizons\.position\._local\.direction_conviction"),
    # A holder without the '_' convention is not an anchor holder.
    ("""
shared:
  direction_conviction: &b {bullish_min_trend: 60, bearish_min_trend: 60}
horizons:
  swing:
    direction_conviction: *b
""", r"shared\.direction_conviction"),
])
def test_a_block_read_elsewhere_does_not_excuse_a_wrong_placement(text, where):
    cfg = _load(text)
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block.*" + where):
            load_direction_conviction_min_trend("Bullish", "Position")


def test_a_null_block_in_an_anchor_holder_gets_no_exemption():
    """`None is None` everywhere: a holder's `direction_conviction: null` must
    not borrow position's explicit null as a legal read."""
    cfg = {"_holder": {"direction_conviction": None},
           "horizons": {"position": {"direction_conviction": None}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"misplaced direction_conviction block.*_holder"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_self_referential_anchor_is_a_named_error_not_recursion():
    """3. `horizons: &x {swing: *x}` used to recurse until RecursionError,
    which neither router catches -- a bare 500 with no detail. Any cycle is
    now the named ValueError."""
    cfg = _load("horizons: &x\n  swing: *x\n")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle in scoring_rules\.yaml at horizons\.swing"):
            load_direction_conviction_min_trend("Bullish", "Swing")


def test_a_cycle_does_not_hide_a_misplaced_block():
    cfg = _load("""
horizons: &x
  swing: *x
  position:
    vol:
      direction_conviction: {bearish_min_trend: 70}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle|misplaced direction_conviction block"):
            _validated_direction_conviction_blocks()


def test_mixed_type_unknown_keys_give_the_named_error_not_typeerror():
    """3d(i). Without `str(k)` in the sort, a bool key beside a str key raises
    TypeError from sorted(), which neither router catches."""
    cfg = {"horizons": {"position": {"direction_conviction": {
        True: 5, "typo_key": 7, "bearish_min_trend": 40,
    }}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="unknown direction_conviction key"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_numeric_intraday_threshold_in_the_yaml_is_honoured():
    """3d(ii). Intraday has no code default (exempt), so only the YAML can gate
    it -- and nothing pinned that a number written there is read."""
    cfg = {"horizons": {"intraday": {"direction_conviction": {
        "bullish_min_trend": 25, "bearish_min_trend": 35,
    }}}}
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Intraday") == 25.0
        assert load_direction_conviction_min_trend("Bearish", "Intraday") == 35.0


# ── 3. Any alias cycle is a named error (Q3 round 3's open finding) ─────────

def test_a_horizon_aliasing_its_enclosing_container_is_rejected():
    """Round 3 at 83b98de: the ancestor-only cycle CUT accepted this while
    Position read its default 40 -- the operator's block at
    horizons.position.vol.horizons.swing.direction_conviction is read by
    Swing, but the alias hides that position.vol is a wrong placement."""
    cfg = _load("""
horizons: &h
  swing:
    direction_conviction: {bullish_min_trend: 55}
  position:
    vol: *h
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle in scoring_rules\.yaml at horizons\.position\.vol"):
            load_direction_conviction_min_trend("Bullish", "Position")


def test_the_enclosing_alias_is_rejected_even_with_no_block_anywhere():
    """With no direction_conviction in the file at all, the only thing left
    to reject is the cycle itself -- so this pins that a cycle raises rather
    than being walked past."""
    cfg = _load("""
horizons: &h
  swing: {weights: {trend: 0.3}}
  position:
    vol: *h
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle in scoring_rules\.yaml at horizons\.position\.vol"):
            load_direction_conviction_min_trend("Bullish", "Position")


def test_a_cycle_outside_horizons_is_rejected_too():
    cfg = _load("""
trend: &t
  self: *t
horizons:
  position:
    direction_conviction: {bearish_min_trend: 40}
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle in scoring_rules\.yaml at trend\.self"):
            load_direction_conviction_min_trend("Bearish", "Position")


def test_a_cycle_through_a_list_is_rejected():
    cfg = _load("a: &l\n  - *l\nhorizons: {}\n")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match=r"alias cycle in scoring_rules\.yaml at a\.\[0\]"):
            _validated_direction_conviction_blocks()


def test_a_shared_non_cyclic_alias_is_not_a_cycle():
    """Sharing a container in two places is ordinary YAML, not a cycle."""
    cfg = _load("""
_common: &c {lookback: 20}
horizons:
  swing:
    vol: *c
    direction_conviction: {bullish_min_trend: 33}
  position:
    vol: *c
""")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 33.0
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0


def test_the_shipped_scoring_rules_still_load_unchanged():
    load_scoring_cfg.cache_clear()
    try:
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bearish", "Swing") == 30.0
        assert load_direction_conviction_min_trend("Bullish", "Position") == 40.0
        assert load_direction_conviction_min_trend("Bearish", "Position") == 40.0
        assert load_direction_conviction_min_trend("Bullish", "Intraday") is None
        assert load_direction_conviction_min_trend("Bearish", "Intraday") is None
    finally:
        load_scoring_cfg.cache_clear()


# ── Round 2's finding: blocks inside !!omap / !!pairs / !!set ───────────────
# Those tags load as tuples-in-a-list or a set, which the walker used to skip,
# so a block written there sat inert (main: operator 99, gate 30).

@pytest.mark.parametrize("text", [
    "horizons:\n  swing:\n    vol: !!omap\n      - direction_conviction: {bullish_min_trend: 99}\n",
    "horizons:\n  swing:\n    vol: !!pairs\n      - direction_conviction: {bullish_min_trend: 99}\n",
    "extras: !!omap\n  - a: 1\n  - direction_conviction: {bullish_min_trend: 99}\nhorizons: {}\n",
    "extras: !!omap\n  - a: {direction_conviction: {bullish_min_trend: 99}}\nhorizons: {}\n",
    "horizons:\n  swing:\n    vol: !!set {direction_conviction}\n",
])
def test_a_block_inside_an_omap_pairs_or_set_is_rejected(text):
    cfg = _load(text)
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        with pytest.raises(ValueError, match="misplaced direction_conviction block"):
            load_direction_conviction_min_trend("Bullish", "Swing")


def test_an_omap_elsewhere_without_a_block_is_accepted():
    cfg = _load("extras: !!omap\n  - a: 1\n  - b: [1, 2]\nhorizons:\n  swing:\n    direction_conviction: {bullish_min_trend: 33}\n")
    with patch("app.services.config_loader.load_scoring_cfg", return_value=cfg):
        assert load_direction_conviction_min_trend("Bullish", "Swing") == 33.0
