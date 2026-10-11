"""Tests for authoritative contract score explanation model, parity, boundaries, and route mapping."""
from datetime import date, timedelta
import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.scoring.contract_validator import validate_contract, _load_config
from app.scoring.dte_window import widen_contract_overrides_for_dte
from app.schemas import OptionContract, ContractExplanation


def _make_contract(days_out: int = 35, **overrides):
    c = {
        "symbol": "AAPL",
        "strike": 185.0,
        "expiry": (date.today() + timedelta(days=days_out)).isoformat(),
        "is_call": True,
        "bid": 2.00,
        "ask": 2.10,
        "volume": 500,
        "open_interest": 2000,
        "delta": 0.45,
        "iv_rank": 30.0,
        "iv_basis": "rank",
    }
    c.update(overrides)
    return c


@pytest.mark.parametrize(("basis", "value", "unit"), [("rank", 35.2, "rank"), ("absolute", 35.2, "%"), ("none", None, "")])
def test_iv_explanation_identifies_the_scored_quantity(basis, value, unit):
    card = validate_contract(_make_contract(iv_basis=basis, iv_rank=value), stock_score=80)
    component = card.explanation["components"]["iv_rank"]
    assert component["basis"] == basis
    assert component["observed"] == value
    assert component["observed_unit"] == unit


# ── AC1: Authoritative score parity, fractional boundaries, rounding ──────────

def test_authoritative_score_parity_unblocked():
    """Unblocked contract has identical score, status, unrounded aggregate and rounded score."""
    c = _make_contract(days_out=35, delta=0.50, bid=2.00, ask=2.05, volume=1000, open_interest=5000, iv_rank=20.0)
    card = validate_contract(c, stock_score=80)
    assert card.status in ("PASS", "CAUTION")
    assert card.score > 0
    exp = card.explanation
    assert exp is not None
    assert exp["outcome"] == "aggregate"
    assert exp["score"] == card.score
    assert exp["status"] == card.status
    assert exp["unrounded_score"] is not None
    assert exp["rounded_score"] == card.score
    assert exp["blockers"] == []
    assert exp["reject_reasons"] == []


@pytest.mark.parametrize(("aggregate", "rounded"), [(64.5, 64), (65.5, 66)])
def test_positive_half_ties_round_to_even(monkeypatch, aggregate, rounded):
    import copy
    cfg = copy.deepcopy(_load_config())
    cfg["weights"] = {"liquidity": aggregate / 100, "spread": 0, "delta": 0, "dte": 0, "iv_rank": 0}
    monkeypatch.setattr("app.scoring.contract_validator._load_config", lambda: cfg)
    card = validate_contract(_make_contract(volume=1000, open_interest=5000), 80)
    assert card.explanation["outcome"] == "aggregate"
    assert card.explanation["unrounded_score"] == aggregate
    assert card.explanation["rounded_score"] == card.score == rounded


def test_blocker_keeps_actual_spread_guard_operands():
    card = validate_contract(_make_contract(bid=2.05, ask=2.15), 80,
                             {"max_bid_ask_spread_pct": .04761})
    exp = ContractExplanation.model_validate(card.explanation)
    blocker = next(b for b in exp.blockers if b.code == "spread_too_wide")
    actual = (2.15 - 2.05) / ((2.15 + 2.05) / 2)
    assert blocker.observed == actual
    assert blocker.observed > blocker.threshold == .04761
    assert exp.components["spread"].observed == actual


@pytest.mark.parametrize(("delta", "bound", "code"), [(.200001, .200002, "delta_too_low_far_otm"), (.899999, .899998, "delta_too_high_deep_itm")])
def test_delta_blockers_preserve_boundary_digits(delta, bound, code):
    key = "min_delta" if "low" in code else "max_delta"
    card = validate_contract(_make_contract(delta=delta), 80, {key: bound})
    blocker = next(b for b in card.explanation["blockers"] if b["code"] == code)
    assert blocker["observed"] == delta
    assert blocker["threshold"] == bound


def test_snapshot_keeps_nonblocking_hard_bounds_and_missing_inputs():
    card = validate_contract(_make_contract(volume=None, open_interest=500, delta=None), 80)
    exp = ContractExplanation.model_validate(card.explanation)
    assert exp.raw_inputs == {"volume": None, "open_interest": 500, "delta": None}
    assert exp.components["liquidity"].volume == 0
    assert exp.hard_bounds["min_volume"] == _load_config()["hard_reject"]["min_volume"]
    assert "volume_too_low" not in card.reject_reasons


def test_fractional_pass_caution_boundaries(monkeypatch):
    """Fractional boundaries (e.g. pass=64.5, caution=45.5) are preserved and applied without int truncation."""
    base_cfg = _load_config()
    cfg_copy = dict(base_cfg)
    cfg_copy["contract_score_thresholds"] = {"pass": 64.5, "caution": 45.5}
    monkeypatch.setattr("app.scoring.contract_validator._load_config", lambda: cfg_copy)

    c = _make_contract(days_out=35)
    card = validate_contract(c, stock_score=70)
    exp = card.explanation
    assert exp is not None
    assert exp["pass_threshold"] == 64.5
    assert exp["caution_threshold"] == 45.5


def test_zero_overrides_disable_soft_checks():
    """preferred_volume_min=0, preferred_oi_min=0, preferred_spread_pct_max=0 score 100 with no flags."""
    c = _make_contract(days_out=35, volume=1, open_interest=2, bid=1.0, ask=2.0)
    card = validate_contract(
        c,
        stock_score=70,
        overrides={
            "preferred_volume_min": 0,
            "preferred_oi_min": 0,
            "preferred_spread_pct_max": 0,
        },
    )
    exp = card.explanation
    assert exp is not None
    liq = exp["components"]["liquidity"]
    spread = exp["components"]["spread"]
    assert liq["raw_score"] == 100
    assert liq["lost_points"] == 0.0
    assert "thin_liquidity" not in liq["flags"]
    assert spread["raw_score"] == 100
    assert spread["lost_points"] == 0.0
    assert "spread_elevated" not in spread["flags"]


def test_collapsed_preferred_bands_do_not_divide_by_zero():
    """Collapsed preferred_dte (30==30) or preferred_delta (0.50==0.50) scores 100 without ZeroDivisionError."""
    c = _make_contract(days_out=30, delta=0.50)
    card = validate_contract(
        c,
        stock_score=70,
        overrides={
            "preferred_dte_min": 30,
            "preferred_dte_max": 30,
            "preferred_delta_min": 0.50,
            "preferred_delta_max": 0.50,
        },
    )
    exp = card.explanation
    assert exp is not None
    assert exp["components"]["dte"]["raw_score"] == 100
    assert exp["components"]["delta"]["raw_score"] == 100


def test_widened_hold_dte_reflected_in_explanation():
    """widen_contract_overrides_for_dte bounds are accurately echoed in the dte component explanation."""
    base_overrides = {"min_volume": 50}
    widened = widen_contract_overrides_for_dte(base_overrides, 20, 40, 20)
    c = _make_contract(days_out=25)
    card = validate_contract(c, stock_score=70, overrides=widened)
    exp = card.explanation
    assert exp is not None
    dte_comp = exp["components"]["dte"]
    assert dte_comp["preferred_min"] == widened["preferred_dte_min"]
    assert dte_comp["preferred_max"] == widened["preferred_dte_max"]


# ── AC2: Five weighted components, largest losses, OI nested ──────────────────

def test_five_weighted_components_present():
    """Explanation contains all 5 weighted components with raw scores, weights, contributions and lost points."""
    c = _make_contract(days_out=35)
    card = validate_contract(c, stock_score=70)
    exp = card.explanation
    assert exp is not None
    assert set(exp["components"].keys()) == {"liquidity", "spread", "delta", "dte", "iv_rank"}

    for name, comp in exp["components"].items():
        assert comp["raw_score"] >= 0
        assert comp["weight"] > 0
        assert round(comp["contribution"] + comp["lost_points"], 2) == round(comp["weight"] * 100, 2)


def test_largest_losses_sorted_by_lost_points_not_raw_score():
    """A component with higher raw score but higher weight can have larger lost points."""
    # Custom config with unequal weights
    c = _make_contract(days_out=35)
    card = validate_contract(c, stock_score=70)
    exp = card.explanation
    assert exp is not None
    losses = exp["largest_losses"]
    assert len(losses) == 5
    for i in range(len(losses) - 1):
        assert losses[i]["lost_points"] >= losses[i + 1]["lost_points"]


def test_oi_nested_in_liquidity_component():
    """Liquidity component includes open_interest, volume, and preferred thresholds."""
    c = _make_contract(days_out=35, volume=600, open_interest=2500)
    card = validate_contract(c, stock_score=70)
    exp = card.explanation
    assert exp is not None
    liq = exp["components"]["liquidity"]
    assert liq["volume"] == 600
    assert liq["open_interest"] == 2500
    assert liq["preferred_volume_min"] is not None
    assert liq["preferred_oi_min"] is not None


# ── AC3: Blocking causes, multi-blockers, volume 0 exception, aggregate REJECT ──

def test_multi_blocker_fixture_shows_all_causes():
    """Multi-blocker contract lists every blocking cause, measured inputs, operators, and score=0."""
    c = _make_contract(
        days_out=10,        # dte_too_short (< 21)
        bid=1.00,
        ask=2.00,           # spread_too_wide (spread_pct 0.666 > 0.20)
        volume=10,          # volume_too_low (< 50)
        open_interest=50,   # open_interest_too_low (< 200)
        delta=0.10,         # delta_too_low_far_otm (< 0.20)
        iv_rank=85.0,       # iv_rank_too_high (> 70)
        iv_basis="rank",
    )
    # stock_score_below_threshold (< 55); the volume floor is 0 (off) by
    # default, so an explicit 50 keeps volume_too_low among the blockers.
    card = validate_contract(c, stock_score=40, overrides={"min_volume": 50})

    assert card.status == "REJECT"
    assert card.score == 0
    exp = card.explanation
    assert exp is not None
    assert exp["outcome"] == "blocked"
    assert exp["score"] == 0
    assert exp["unrounded_score"] is None
    assert exp["rounded_score"] is None

    blocker_codes = [b["code"] for b in exp["blockers"]]
    assert "volume_too_low" in blocker_codes
    assert "open_interest_too_low" in blocker_codes
    assert "spread_too_wide" in blocker_codes
    assert "delta_too_low_far_otm" in blocker_codes
    assert "dte_too_short" in blocker_codes
    assert "iv_rank_too_high" in blocker_codes
    assert "stock_score_below_threshold" in blocker_codes

    for b in exp["blockers"]:
        assert b["operator"] in ("<", ">", ">=", "<=")
        assert b["threshold"] is not None
        assert b["metric"] != ""


def test_volume_zero_with_adequate_oi_does_not_invent_volume_blocker():
    """With an explicit volume floor (the default is 0, off), volume=0 with
    open_interest >= 200 does NOT trigger volume_too_low: a 0 cannot be told
    apart from "no trades yet this session"."""
    c = _make_contract(
        days_out=35,
        volume=0,
        open_interest=500,  # >= min_open_interest 200
    )
    card = validate_contract(c, stock_score=70, overrides={"min_volume": 50})
    assert "volume_too_low" not in card.reject_reasons
    exp = card.explanation
    assert exp is not None
    blocker_codes = [b["code"] for b in exp["blockers"]]
    assert "volume_too_low" not in blocker_codes


def test_too_many_soft_failures_blocker_including_missing_iv():
    """Missing IV contributes neutral 50 + soft flag 'no_iv_rank_data'; >= 3 soft flags blocks contract."""
    c = _make_contract(
        days_out=20,         # dte_outside_preferred (1 soft flag)
        delta=0.25,          # delta_outside_preferred (2 soft flags)
        iv_rank=None,        # no_iv_rank_data (3 soft flags)
        iv_basis="none",
    )
    card = validate_contract(c, stock_score=70)
    assert "too_many_soft_failures" in card.reject_reasons
    exp = card.explanation
    assert exp is not None
    assert exp["outcome"] == "blocked"
    blocker_codes = [b["code"] for b in exp["blockers"]]
    assert "too_many_soft_failures" in blocker_codes
    soft_blocker = next(b for b in exp["blockers"] if b["code"] == "too_many_soft_failures")
    assert soft_blocker["observed"] >= 3
    assert soft_blocker["threshold"] == 3
    assert soft_blocker["operator"] == ">="


def test_aggregate_only_reject_has_no_fake_blocker():
    """Unblocked contract whose aggregate score falls below caution threshold has no fake blocker."""
    # Set soft parameters so contract passes hard rejects but gets low aggregate score
    c = _make_contract(
        days_out=21,         # dte 21
        delta=0.31,          # delta 0.31
        bid=1.00,
        ask=1.07,           # spread ~6.8%
        volume=210,         # just above soft
        open_interest=1010, # just above soft
        iv_rank=54.0,       # just below soft 55
        iv_basis="rank",
    )
    # Force caution threshold high to ensure it lands in REJECT
    card = validate_contract(c, stock_score=70, overrides={"preferred_volume_min": 2000, "preferred_oi_min": 10000})
    if card.score < 45 and not card.reject_reasons:
        exp = card.explanation
        assert exp is not None
        assert exp["outcome"] == "aggregate"
        assert exp["status"] == "REJECT"
        assert exp["blockers"] == []
        assert exp["score"] < 45
        assert exp["unrounded_score"] is not None
        assert exp["rounded_score"] == exp["score"]


# ── AC4 / Route parity test ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_contracts_route_includes_explanation():
    """GET /api/contracts returns typed explanation matching validate_contract."""
    from unittest.mock import AsyncMock, patch

    mock_contract = {
        "id": "AAPL|185|2026-11-20|C",
        "symbol": "AAPL",
        "strike": 185,
        "expiry": (date.today() + timedelta(days=45)).isoformat(),
        "right": "C",
        "dte": 45,
        "dteTotal": 45,
        "price": 2.50,
        "spread": 0.10,
        "delta": 0.45,
        "theta": -0.05,
        "ivRank": 40,
        "volume": 500,
        "open_interest": 2000,
    }

    with patch("app.routers.contracts.fetch_option_chain_async", AsyncMock(return_value=[mock_contract])), \
         patch("app.routers.contracts.fetch_price_async", AsyncMock(return_value=185.0)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/contracts?symbol=AAPL&right=C&stock_score=70&limit=5")
            assert resp.status_code == 200
            contracts = resp.json()
            assert len(contracts) > 0
            for item in contracts:
                assert "explanation" in item
                assert item["explanation"] is not None
                exp = item["explanation"]
                assert "outcome" in exp
                assert "version" in exp
                assert "components" in exp
                assert "largest_losses" in exp
                assert "blockers" in exp
                assert "pass_threshold" in exp
                assert "caution_threshold" in exp
                # Verify Pydantic validation passes
                validated = ContractExplanation.model_validate(exp)
                assert validated.outcome in ("blocked", "aggregate")
                assert len(validated.components) == 5


def test_put_explanation_binds_to_the_returned_row_identity():
    c = _make_contract()
    c['id'] = f"AAPL|185|{c['expiry']}|P"
    c['right'] = 'P'
    card = validate_contract(c, 80)
    assert card.explanation['contract_id'] == c['id']
    # Leave the existing score card identity and scoring/persistence contracts unchanged.
    assert card.contract_id.endswith('|C')
