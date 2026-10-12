"""Unit tests for scan override wiring — stock_scorer.py and contract_validator.py."""

from __future__ import annotations

from datetime import date, timedelta
import copy
import pytest

from app.scoring.stock_scorer import score_stock
from app.scoring.contract_validator import validate_contract

# ── Shared test fixtures ──────────────────────────────────────────────────────

def _make_bars(n: int = 250) -> list[dict]:
    """Deterministic OHLCV bars: 250+ rows ensures slow EMA (200) can fire."""
    bars = []
    price = 100.0
    for i in range(n):
        price += 0.5
        bars.append({
            "open": price - 0.3,
            "high": price + 1.0,
            "low":  price - 0.5,
            "close": price,
            "volume": 1_000_000 + i * 1000,
        })
    return bars


_BARS = _make_bars()


@pytest.mark.parametrize("horizon", ["Intraday", "Swing", "Position"])
@pytest.mark.parametrize("mode", ["options", "stock"])
@pytest.mark.parametrize("basis", ["absolute", "rank"])
def test_stock_evidence_captures_effective_weights_rules_and_vintage(horizon, mode, basis):
    ov = {"weight_trend": 0.123, "weight_event": 0.321,
          "event_reject_days": 8, "event_caution_days": 19,
          "additive_adx_pass": 28.75, "ma_type": "SMA"}
    card = score_stock("AAPL", "Bullish", horizon, _BARS, iv_rank=40,
                       iv_basis=basis, overrides=ov, scoring_mode=mode)
    e = card.explanation
    assert e["score"] == card.score == round(e["unrounded_score"])
    assert e["status"] == card.status
    assert e["iv_basis"] == basis and e["horizon"] == horizon
    assert e["rounding"] == "python_round_ties_to_even"
    assert e["components"]["trend"]["config"]["additive"]["adx_pass"] == 28.75
    assert e["components"]["trend"]["config"]["crossover"]["ma_type"] == "SMA"
    assert e["components"]["event"]["config"] == {"reject_days": 8, "caution_days": 19}
    if mode == "stock":
        assert e["weights"]["event"] == 0
        assert sum(e["weights"].values()) == pytest.approx(1)
    else:
        assert e["weights"]["trend"] == 0.123
        assert e["weights"]["event"] == 0.321
    for rule in card.rules[:5]:
        component = e["components"][rule.name]
        assert component["raw_score"] == rule.score
        assert component["status"] == rule.status
        assert component["detail"] == rule.detail
        assert component["contribution"] == rule.score * e["weights"][rule.name]
    assert sum(c["contribution"] for c in e["components"].values()) == e["unrounded_score"]
    frozen = copy.deepcopy(e)
    ov["event_reject_days"] = 100
    card.rules[0].detail["method"] = "mutated"
    score_stock("AAPL", "Bearish", horizon, _BARS, overrides={"weight_trend": 0.9})
    assert e == frozen


@pytest.mark.parametrize("raw,rounded", [(54.5, 54), (55.5, 56)])
def test_stock_evidence_preserves_ties_to_even_and_pullback_cap(monkeypatch, raw, rounded):
    import app.scoring.stock_scorer as scorer
    monkeypatch.setattr(scorer, "_rule_trend", lambda *a, **kw: scorer.RuleResult("trend", "PASS", int(raw), {}))
    monkeypatch.setattr(scorer, "_rule_event", lambda *a, **kw: scorer.RuleResult("event", "REJECT", 1, {}))
    monkeypatch.setattr(scorer, "_rule_pullback", lambda *a, **kw: scorer.RuleResult("pullback", "REJECT", 0, {"reason": "too_deep"}))
    ov = {f"weight_{name}": 0 for name in ["trend", "pullback", "trigger", "event", "vol"]}
    ov.update(weight_trend=1, weight_event=0.5)
    card = score_stock("AAPL", "Bullish", "Swing", _BARS, overrides=ov)
    e = card.explanation
    assert card.score == rounded and card.status == "CAUTION"
    assert e["unrounded_score"] == raw
    assert e["raw_status"] == ("PASS" if rounded >= 55 else "CAUTION")
    assert e["caps"][0]["name"] == "pullback_timing"
    assert e["caps"][0]["detail"]["reason"] == "too_deep"


@pytest.mark.parametrize("confidence", [None, 10, 50, 80])
@pytest.mark.parametrize("direction", ["Bullish", "Bearish"])
def test_stock_evidence_separates_gates_from_components(confidence, direction):
    from types import SimpleNamespace
    gate = {"enabled": True, "rejectBelow": 40, "cautionBelow": 60}
    regime = {"enabled": True, "headwind_reject_pct": -40,
              "headwind_caution_pct": -15, "require_stable_for_reject": True}
    fund_gate = {"enabled": True, "cautionBelow": 45, "rejectBelow": 30,
                 "cautionAbove": 70, "rejectAbove": 80}
    fund = SimpleNamespace(score=90, safety_flags=["negative_equity"], detail={"source": "fixture"})
    card = score_stock("AAPL", direction, "Swing", _BARS, confidence=confidence,
                       confidence_sample_size=17, confidence_gate=gate,
                       regime_signal={"conviction_pct": -45, "stability": "Stable"},
                       regime_gate=regime, fundamentals=fund, fundamentals_gate=fund_gate)
    e = card.explanation
    assert set(e["components"]) == {"trend", "pullback", "trigger", "event", "vol"}
    caps = {c["name"]: c for c in e["caps"]}
    assert caps["confidence"]["detail"]["confidence"] == confidence
    assert caps["confidence"]["detail"]["sample_size"] == 17
    # None caps at CAUTION (Unvalidated, STOCKS-HORIZON-P0A A5); it used to read PASS.
    assert caps["confidence"]["status"] == ("CAUTION" if confidence is None else "PASS" if confidence >= 60 else "REJECT" if confidence < 40 else "CAUTION")
    assert caps["regime"]["status"] == "REJECT"
    assert caps["fundamentals"]["detail"]["safety_flags"] == ["negative_equity"]
    assert e["status"] == "REJECT" == card.status
    gate["rejectBelow"] = 99
    fund.safety_flags.clear()
    assert e["gate_config"]["confidence"]["rejectBelow"] == 40
    assert caps["fundamentals"]["detail"]["safety_flags"] == ["negative_equity"]


def test_stock_evidence_keeps_missing_benchmark_explicit():
    card = score_stock("AAPL", "Bullish", "Swing", _BARS,
                       overrides={"trend_method": "relative_strength"})
    trend = card.explanation["components"]["trend"]
    assert trend["measured"] is False
    assert trend["detail"]["reason"] == "no_benchmark_data"
    assert trend["raw_score"] == 50  # authoritative placeholder, not a measured reading


def _expiry_str(days_from_today: int) -> str:
    return (date.today() + timedelta(days=days_from_today)).isoformat()


def _make_contract(*, bid=1.0, ask=1.10, delta=0.45, days=40, volume=500, oi=1000) -> dict:
    """days controls the expiry date (relative to today) so validator computes DTE correctly."""
    return {
        "symbol": "AAPL",
        "strike": 185,
        "expiry": _expiry_str(days),
        "is_call": True,
        "bid": bid,
        "ask": ask,
        "price": (bid + ask) / 2,
        "delta": delta,
        "theta": -0.05,
        "ivRank": 40,
        "volume": volume,
        "open_interest": oi,
    }


# ── stock_scorer overrides ────────────────────────────────────────────────────

def test_weight_override_changes_score():
    """Shifting all weight onto trend must produce a different total score."""
    card_default = score_stock("AAPL", "Bullish", "Swing", _BARS)
    card_trend_heavy = score_stock(
        "AAPL", "Bullish", "Swing", _BARS,
        overrides={
            "weight_trend":    0.9,
            "weight_pullback": 0.025,
            "weight_trigger":  0.025,
            "weight_event":    0.025,
            "weight_vol":      0.025,
        },
    )
    assert card_default.score != card_trend_heavy.score


def test_ma_type_sma_does_not_error():
    """SMA override must produce a valid 0–100 score without raising."""
    card = score_stock("AAPL", "Bullish", "Swing", _BARS, overrides={"ma_type": "SMA"})
    assert 0 <= card.score <= 100


def test_ma_type_ema_matches_default():
    """Explicit EMA override should not change the result vs the default."""
    card_default  = score_stock("AAPL", "Bullish", "Swing", _BARS)
    card_ema_expl = score_stock("AAPL", "Bullish", "Swing", _BARS, overrides={"ma_type": "EMA"})
    assert card_default.score == card_ema_expl.score


def test_macd_override_applied():
    """MACD period override changes scoring output (histogram result differs)."""
    card_default = score_stock("AAPL", "Bullish", "Swing", _BARS)
    card_narrow  = score_stock("AAPL", "Bullish", "Swing", _BARS,
                               overrides={"macd_fast": 3, "macd_slow": 6, "macd_signal": 2})
    # Scores may differ; at minimum neither crashes and both are in range
    assert 0 <= card_default.score <= 100
    assert 0 <= card_narrow.score <= 100


def test_override_does_not_mutate_cached_config():
    """Two consecutive calls with conflicting overrides must not interfere."""
    card_a = score_stock("AAPL", "Bullish", "Swing", _BARS, overrides={"weight_trend": 0.9})
    card_b = score_stock("AAPL", "Bullish", "Swing", _BARS, overrides={"weight_trend": 0.1})
    # If the cache is being mutated, the second call would use 0.9 from the first.
    # The scores must reflect different weights.
    assert card_a.score != card_b.score


# ── contract_validator overrides ──────────────────────────────────────────────

def test_tight_spread_override_rejects_wide_contract():
    """Default spread (10 %) passes at 20 % ceiling; fails at 5 % ceiling."""
    contract = _make_contract(bid=1.0, ask=1.10)   # spread = ~9.5 %
    card_default = validate_contract(contract, 70)
    card_tight   = validate_contract(contract, 70, overrides={"max_bid_ask_spread_pct": 0.05})
    assert card_default.status != "REJECT" or "spread_too_wide" not in card_default.reject_reasons
    assert "spread_too_wide" in card_tight.reject_reasons


def test_min_dte_override_rejects_near_expiry():
    """Contract expiring in 25 days passes default min_dte=21 but fails min_dte=30."""
    contract = _make_contract(days=25)
    card_default = validate_contract(contract, 70)
    card_strict  = validate_contract(contract, 70, overrides={"min_dte": 30})
    assert "dte_too_short" not in card_default.reject_reasons
    assert "dte_too_short" in card_strict.reject_reasons


def test_min_volume_override_rejects_illiquid():
    """Contract with volume=50 passes default but fails min_volume=500."""
    contract = _make_contract(volume=50)
    card_default = validate_contract(contract, 70)
    card_strict  = validate_contract(contract, 70, overrides={"min_volume": 500})
    assert "volume_too_low" not in card_default.reject_reasons
    assert "volume_too_low" in card_strict.reject_reasons


def test_contract_override_does_not_mutate_cached_config():
    """Two calls with conflicting min_dte overrides must not share state."""
    contract = _make_contract(days=20)
    card_a = validate_contract(contract, 70, overrides={"min_dte": 25})  # reject (20 < 25)
    card_b = validate_contract(contract, 70, overrides={"min_dte": 5})   # pass  (20 >= 5)
    assert "dte_too_short" in card_a.reject_reasons
    assert "dte_too_short" not in card_b.reject_reasons


# ── soft-rank preferred-liquidity overrides ───────────────────────────────────
# The options-scan-liquidity-profiles work: preferred_volume_min/preferred_oi_min/
# preferred_spread_pct_max were previously fixed at their contract_rules.yaml
# defaults with no override path, even though the matching HARD-reject keys
# (min_volume/min_open_interest/max_bid_ask_spread_pct) have been overridable
# all along. A caller widening only the hard floor left a contract that now
# clears the reject/accept boundary still penalized by the untouched soft
# floor — see widen_contract_overrides_for_dte's docstring for the identical
# defect already fixed once for DTE.

def test_preferred_volume_min_override_removes_soft_flag():
    """volume=100 clears the hard floor (an optional floor, 0 = off by
    default) but is below the soft default (200), so it passes but carries
    thin_liquidity (OI 2000 is above its own Preferred floor, so volume is the
    only cause). Lowering preferred_volume_min to 50 removes the flag without
    touching the hard floor."""
    contract = _make_contract(volume=100, oi=2000)
    card_default = validate_contract(contract, 70)
    assert "volume_too_low" not in card_default.reject_reasons
    assert "thin_liquidity" in card_default.soft_flags
    card_override = validate_contract(contract, 70, overrides={"preferred_volume_min": 50})
    assert "thin_liquidity" not in card_override.soft_flags


def test_preferred_oi_min_override_removes_soft_flag():
    """oi=500 is above the hard default (200) but below the soft default
    (1000), so it passes but carries thin_liquidity (volume 2000 is above its
    own Preferred floor, so OI is the only cause)."""
    contract = _make_contract(volume=2000, oi=500)
    card_default = validate_contract(contract, 70)
    assert "open_interest_too_low" not in card_default.reject_reasons
    assert "thin_liquidity" in card_default.soft_flags
    card_override = validate_contract(contract, 70, overrides={"preferred_oi_min": 400})
    assert "thin_liquidity" not in card_override.soft_flags


def test_preferred_spread_pct_max_override_removes_soft_flag():
    """~10% spread is under the hard ceiling (20%) but over the soft one
    (8%), so it passes but carries spread_elevated."""
    contract = _make_contract(bid=1.0, ask=1.10, volume=2000, oi=2000)  # spread ~9.5%
    card_default = validate_contract(contract, 70)
    assert "spread_too_wide" not in card_default.reject_reasons
    assert "spread_elevated" in card_default.soft_flags
    card_override = validate_contract(contract, 70, overrides={"preferred_spread_pct_max": 0.15})
    assert "spread_elevated" not in card_override.soft_flags


def test_preferred_liquidity_overrides_do_not_mutate_cached_config():
    """Same regression guard as the hard-reject overrides above, for the new keys.
    OI 2000 clears its Preferred floor, so thin_liquidity on these cards comes
    from the volume override alone."""
    contract = _make_contract(volume=100, oi=2000)
    card_a = validate_contract(contract, 70, overrides={"preferred_volume_min": 50})
    card_b = validate_contract(contract, 70, overrides={"preferred_volume_min": 5000})
    assert "thin_liquidity" not in card_a.soft_flags
    assert "thin_liquidity" in card_b.soft_flags


def test_loose_tier_combined_override_clears_both_hard_and_soft_liquidity_gates():
    """The actual fix this override set exists for: a thin-but-not-worthless
    contract (volume=25, oi=90, spread~10%) that fails the DEFAULT hard floor
    on one axis (oi<200; the volume floor is 0, off, by default) must, under a
    'Loose' profile moving both the hard floor and its preferred counterpart to
    the same value per axis, pass the hard reject AND carry neither the
    liquidity nor the spread soft flag -- not merely avoid outright rejection
    while still losing the soft-score/soft-fail-count battle on the same axes."""
    contract = _make_contract(bid=1.0, ask=1.11, volume=25, oi=90)  # spread ~10.4%
    card_default = validate_contract(contract, 70)
    assert "volume_too_low" not in card_default.reject_reasons
    assert "open_interest_too_low" in card_default.reject_reasons

    loose_overrides = {
        "min_volume": 20, "min_open_interest": 75, "max_bid_ask_spread_pct": 0.30,
        "preferred_volume_min": 20, "preferred_oi_min": 75, "preferred_spread_pct_max": 0.30,
    }
    card_loose = validate_contract(contract, 70, overrides=loose_overrides)
    assert card_loose.reject_reasons == []
    assert "thin_liquidity" not in card_loose.soft_flags
    assert "spread_elevated" not in card_loose.soft_flags


# ── round-1 audit fixes: 0 as a "no preference" value, not a crash ──────────
# Both bugs below were reachable the moment preferred_volume_min/preferred_oi_min/
# preferred_spread_pct_max became override-able (this file, above) with a UI
# field whose own `min` bound is 0 -- before that commit, these three were
# fixed at their contract_rules.yaml defaults and could never be 0.

def test_preferred_volume_min_zero_does_not_raise_and_scores_full():
    """A bare division by preferred_volume_min crashes at 0; the fix treats
    0 as 'no preference on this axis' -- full score, no soft flag -- rather
    than ZeroDivisionError propagating up through scan.py as a per-symbol
    rejection reading the literal exception text."""
    contract = _make_contract(volume=1, oi=2000)  # volume deliberately tiny
    card = validate_contract(contract, 70, overrides={"preferred_volume_min": 0})
    assert "thin_liquidity" not in card.soft_flags
    assert card.breakdown.liquidity_score == 100


def test_preferred_oi_min_zero_does_not_raise_and_scores_full():
    contract = _make_contract(volume=2000, oi=1)  # oi deliberately tiny
    card = validate_contract(contract, 70, overrides={"preferred_oi_min": 0})
    assert "thin_liquidity" not in card.soft_flags
    assert card.breakdown.oi_score == 100


def test_preferred_spread_pct_max_zero_does_not_score_zero_or_always_flag():
    """This one never raised (spread_pct is never negative, so the original
    ternary happened to route max_pct<=0 into its `else 0` branch) but scored
    0 and always flagged -- the opposite of what dragging the ceiling to
    nothing should mean. Same fix as the two above: 0 means no preference."""
    contract = _make_contract(bid=1.0, ask=1.10, volume=2000, oi=2000)
    card = validate_contract(contract, 70, overrides={"preferred_spread_pct_max": 0})
    assert "spread_elevated" not in card.soft_flags
    assert card.breakdown.spread_score == 100


def test_preferred_volume_min_override_survives_liquidity_detail_construction():
    """int(), not float(): a fractional override used to reach the response
    detail dict, where LiquidityDetail's `int` field raised on construction --
    caught and swallowed by both callers (_safe() in routers/scan.py,
    _safe_detail() in routers/contracts.py), silently dropping the whole
    liquidityDetail block with no error anywhere. Constructing the model
    directly from the returned detail, the way both real callers do, is what
    would have caught this -- asserting only on contract_validator's own
    output would not have."""
    from app.schemas import LiquidityDetail
    contract = _make_contract(volume=250, oi=2000)
    card = validate_contract(contract, 70, overrides={"preferred_volume_min": 205.7})
    assert isinstance(card.detail["liquidity"]["preferred_volume_min"], int)
    LiquidityDetail(**card.detail["liquidity"])  # must not raise


# ROUND 2 AUDIT FINDING: plain int() truncates any override in the open
# interval (0, 1) down to 0, which _score_liquidity's own "<= 0 means no
# preference" branch (added by round 1's fix, above) then reads as "disable
# this check entirely" -- the opposite of what a caller sending a strict
# near-zero value intended. The two round-1 fixes are independent everywhere
# except this interval, where they actively conflict. `_int_pref_override`
# floors (0, 1) to 1 -- still "> 0" -- instead of letting it fall to 0.

def test_preferred_volume_min_fractional_override_still_flags_thin_liquidity():
    """override=0.5 must NOT be silently read as 'no preference' (int(0.5)==0
    would fall into the <= 0 branch); it must behave as a strict near-zero
    floor of 1, still catching a genuinely zero-volume contract."""
    contract = _make_contract(volume=0, oi=2000)
    card = validate_contract(contract, 70, overrides={"preferred_volume_min": 0.5})
    assert "thin_liquidity" in card.soft_flags
    assert card.breakdown.liquidity_score < 100


def test_preferred_oi_min_fractional_override_still_flags_thin_liquidity():
    contract = _make_contract(volume=2000, oi=0)
    card = validate_contract(contract, 70, overrides={"preferred_oi_min": 0.9})
    assert "thin_liquidity" in card.soft_flags
    assert card.breakdown.oi_score < 100


# ── WI-12: off-hours null-data guard ─────────────────────────────────────────

def test_zero_volume_with_adequate_oi_is_not_rejected():
    """With an explicit volume floor (the default is 0, off), volume=0 is
    exempt when OI >= min_open_interest: a 0 cannot be told apart from "no
    trades yet this session", so OI is the liquidity proxy."""
    contract = _make_contract(volume=0, oi=1000)  # OI well above 200 default
    card = validate_contract(contract, 70, overrides={"min_volume": 50})
    assert "volume_too_low" not in card.reject_reasons


def test_zero_volume_with_zero_oi_is_rejected():
    """volume=0 AND oi=0 is genuinely illiquid — must still reject."""
    contract = _make_contract(volume=0, oi=0)
    card = validate_contract(contract, 70)
    assert "open_interest_too_low" in card.reject_reasons


def test_low_nonzero_volume_is_rejected():
    """volume=10 (real but below an explicit floor of 50) must still trigger
    volume_too_low; the default floor is 0 (off)."""
    contract = _make_contract(volume=10, oi=1000)
    card = validate_contract(contract, 70, overrides={"min_volume": 50})
    assert "volume_too_low" in card.reject_reasons
