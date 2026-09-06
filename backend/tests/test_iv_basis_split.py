"""Phase A — `iv` and `ivRank` are two different quantities.

Until 2026-09-06 the option chain wrote raw implied volatility x 100 into a
field named `ivRank`, IBKR/tastytrade conditionally overwrote it with a genuine
percentile, and the scorer judged whichever arrived against one set of
thresholds. So a name at 45% IV was scored as though it sat at the 45th
percentile of its own 52-week range, and a name at 75% IV was hard-rejected
even when 75% is low for it.

`iv_basis` now says which quantity is in hand, and each quantity has its own
threshold set. See decision PHASE-A-NULL-IVRANK-2026-09-06.
"""
import copy

import pytest

from app.scoring.stock_scorer import _rule_vol, _horizon_cfg, score_stock


@pytest.fixture
def cfg():
    return copy.deepcopy(_horizon_cfg("Swing"))


def test_shipped_thresholds_live_on_the_absolute_path(cfg):
    # The 34/55 numbers are what this rule has ACTUALLY been applying, because
    # raw IV is what it was actually receiving. They must stay on the absolute
    # path or the split would silently change which candidates pass.
    v = cfg["vol"]
    assert (v["iv_abs_pass_max"], v["iv_abs_caution_max"]) == (34, 55)


@pytest.mark.parametrize(
    "iv, expected",
    [(20.0, "PASS"), (34.0, "PASS"), (45.0, "CAUTION"), (55.0, "CAUTION"), (75.0, "REJECT")],
)
def test_absolute_iv_keeps_todays_verdicts(cfg, iv, expected):
    assert _rule_vol(iv, cfg, iv_basis="absolute").status == expected


def test_the_basis_actually_selects_the_threshold_set(cfg):
    # Drive the two sets apart and prove the basis, not the value, decides.
    # Without this the split is cosmetic: both paths would read one set and the
    # rank path would stay as wrong as it was.
    cfg["vol"].update(
        iv_abs_pass_max=10, iv_abs_caution_max=20,
        iv_rank_pass_max=80, iv_rank_caution_max=90,
    )
    assert _rule_vol(50.0, cfg, iv_basis="absolute").status == "REJECT"
    assert _rule_vol(50.0, cfg, iv_basis="rank").status == "PASS"


def test_the_rule_reports_which_quantity_it_judged(cfg):
    # The verdict is uninterpretable without it: "iv_rank: 45" meant two
    # different things depending on which vendor answered.
    for basis in ("absolute", "rank"):
        assert _rule_vol(45.0, cfg, iv_basis=basis).detail["iv_basis"] == basis


def test_a_null_pass_max_still_skips_scoring_on_both_paths(cfg):
    # Intraday sets both to null. If only one set were nulled, the basis would
    # decide whether the rule runs at all rather than how it judges.
    cfg["vol"].update(iv_abs_pass_max=None, iv_rank_pass_max=None)
    for basis in ("absolute", "rank"):
        r = _rule_vol(45.0, cfg, iv_basis=basis)
        assert r.status == "PASS" and r.detail["scored"] is False


def test_no_volatility_at_all_is_caution_not_a_silent_pass(cfg):
    assert _rule_vol(None, cfg, iv_basis="none").status == "CAUTION"


# ── The Step 3 "IV pass max" knob has to reach the threshold that applies ────
#
# ROUND 1 finding (c). `_rule_vol` picks its threshold set by basis, so an
# override naming one set can only ever reach that basis. Until a second
# handler existed, `iv_rank_pass_max` was the sole knob and it wrote the
# PERCENTILE key -- which the rule reads only when IBKR or tastytrade supplied
# a real rank. On every other chain (the default configuration) the user's
# ceiling was silently inert.

def _bars(n: int = 250) -> list[dict]:
    """Deterministic rising OHLCV — enough rows for the 200-EMA to fire."""
    out, price = [], 100.0
    for i in range(n):
        price += 0.5
        out.append({
            "open": price - 0.3, "high": price + 1.0, "low": price - 0.5,
            "close": price, "volume": 1_000_000 + i * 1000,
        })
    return out


_BARS = _bars()


def _vol_rule(**kw):
    card = score_stock("AAPL", "Bullish", "Swing", _BARS, **kw)
    return next(r for r in card.rules if r.name == "vol")


def test_absolute_ceiling_override_reaches_the_default_path():
    # 30% absolute IV is under the shipped 34 ceiling, so it passes untouched.
    assert _vol_rule(iv_rank=30.0, iv_basis="absolute").status == "PASS"
    # Tightening the ceiling to 20 must move it. Before the `iv_abs_pass_max`
    # handler existed there was NO knob that could: this returned PASS however
    # low the user set the one control the panel offered.
    assert _vol_rule(
        iv_rank=30.0, iv_basis="absolute",
        overrides={"iv_abs_pass_max": 20},
    ).status == "CAUTION"


def test_percentile_ceiling_override_reaches_the_rank_path():
    assert _vol_rule(iv_rank=30.0, iv_basis="rank").status == "PASS"
    assert _vol_rule(
        iv_rank=30.0, iv_basis="rank",
        overrides={"iv_rank_pass_max": 20},
    ).status == "CAUTION"


def test_neither_ceiling_leaks_across_the_basis_it_names():
    # The whole point of two keys: a percentile ceiling must not judge an
    # absolute level, or the split is undone at the override layer.
    assert _vol_rule(
        iv_rank=30.0, iv_basis="absolute",
        overrides={"iv_rank_pass_max": 5},
    ).status == "PASS"
    assert _vol_rule(
        iv_rank=30.0, iv_basis="rank",
        overrides={"iv_abs_pass_max": 5},
    ).status == "PASS"


def test_a_null_override_disables_the_gate_on_the_absolute_path():
    # Mirrors the existing handler's `None if val is None` contract, which the
    # panel uses to mean "no ceiling" — it must work on the new key too.
    r = _vol_rule(
        iv_rank=90.0, iv_basis="absolute",
        overrides={"iv_abs_pass_max": None},
    )
    assert r.status == "PASS" and r.detail["scored"] is False
